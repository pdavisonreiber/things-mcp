"""``things`` — a command-line interface to Things 3.

Built on the same ``core`` module as the MCP server: reads come from the
Things database via things.py, writes go through the Things URL scheme (or
AppleScript for Areas).

Items can be referred to by:
  * the number shown next to them in the most recent listing (``things done 3``),
  * a full UUID, or
  * a unique UUID prefix (at least 4 characters).

URL-scheme writes are fire-and-forget: the command returns once macOS has
handed the URL to Things, so a listing run immediately afterwards may not
show the change yet.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Callable, Optional

import click
import things
from rich.console import Console
from rich.table import Table

from . import core, display, style
from .core import ThingsError

BUILTIN_LISTS = ('inbox', 'today', 'upcoming', 'anytime', 'someday', 'logbook', 'trash')


# ---------------------------------------------------------------------------
# Item references (numbers from the last listing, UUIDs, UUID prefixes)
# ---------------------------------------------------------------------------

def _cache_file() -> Path:
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return Path(base) / 'things-mcp' / 'last-list.json'


def _save_refs(numbered: dict[int, str]) -> None:
    path = _cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({str(k): v for k, v in numbered.items()}))
    except OSError:
        pass  # numbering is a convenience; never fail a listing over it


def _load_refs() -> dict[str, str]:
    try:
        return json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        return {}


def resolve_ref(ref: str) -> str:
    """Turn a listing number, UUID or UUID prefix into a UUID."""
    ref = ref.strip()
    if ref.isdigit():
        refs = _load_refs()
        if ref in refs:
            return refs[ref]
        raise ThingsError(f"No item #{ref} in the last listing — run a list command (e.g. 'things today') first.")
    if core.get(ref):
        return ref
    if len(ref) >= 4:
        candidates = [*(things.tasks(status=None) or []), *(things.areas() or [])]
        matches = {c['uuid']: c for c in candidates if c['uuid'].startswith(ref)}
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            names = ', '.join(f"{m['title']} ({u[:8]})" for u, m in list(matches.items())[:5])
            raise ThingsError(f"'{ref}' matches several items: {names}")
    raise ThingsError(f"No item matches '{ref}'")


def _resolve_all(refs) -> list[str]:
    return [resolve_ref(r) for r in refs]


def _resolve_opt(ref: Optional[str]) -> Optional[str]:
    return resolve_ref(ref) if ref else None


def _resolve_named(ref: Optional[str], kind: str) -> Optional[str]:
    """Like _resolve_opt, but also accepts a project or area title (exact, any case)."""
    if not ref:
        return None
    try:
        return resolve_ref(ref)
    except ThingsError:
        candidates = core.projects() if kind == 'project' else core.areas()
        matches = [c['uuid'] for c in candidates if (c.get('title') or '').casefold() == ref.strip().casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ThingsError(f"Several {kind}s are called '{ref}'; use its number or UUID")
        raise


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _console() -> Console:
    """Rich console for list output. When piped (not a terminal) Rich drops the
    colours; a generous width keeps rows from being cut short."""
    console = Console(highlight=False)
    if not console.is_terminal:
        console = Console(highlight=False, width=160)
    return console


def _print_items(items: list, *, limit: Optional[int], offset: int, as_json: bool,
                 long: bool, empty: str, list_key: str = '',
                 group: Optional[Callable[[list], display.Groups]] = None) -> None:
    """Print a listing. Rows are grouped like the Things list (``group``),
    numbered in the order they're shown, and paged with ``limit``/``offset``."""
    # Order rows as they'll be shown (grouping can reorder, e.g. Upcoming by
    # date), then page through that order so numbers match what's printed.
    ordered = [(label, item) for label, members in (group(items) if group else [(None, items)])
               for item in members]
    total = len(ordered)
    end = total if limit is None else offset + limit
    page = ordered[offset:end]
    page_items = [item for _, item in page]

    if as_json:
        click.echo(json.dumps({
            'items': page_items, 'count': len(page_items), 'total': total,
            'offset': offset, 'limit': limit,
        }, default=str, indent=2, ensure_ascii=False))
        return

    if not page:
        click.echo(empty if total == 0 else f"Nothing to show (offset {offset} is past the end of {total} items)")
        return

    if long:
        click.echo('\n\n'.join(display.detail(item) for item in page_items))
    else:
        evening = core.evening_uuids()
        colour_key = list_key.split(':', 1)[0] if list_key else ''
        table = Table(show_header=False, box=None, padding=(0, 1), pad_edge=False)
        table.add_column(justify='right', style=style.FAINT, no_wrap=True)
        table.add_column(no_wrap=True, overflow='ellipsis')
        table.add_column(no_wrap=True)
        table.add_column(no_wrap=True)
        current = None
        for n, (label, item) in enumerate(page, start=offset + 1):
            if label != current:
                if label:
                    if n > offset + 1:
                        table.add_row('', '', '', '')
                    table.add_row('', style.group_heading(label, colour_key), '', '')
                current = label
            table.add_row(str(n), style.row_title(item),
                          style.where_cell(item, omit=label) if colour_key != 'project' else '',
                          style.info_cell(item, list_key, evening=item.get('uuid') in evening))
        console = _console()
        if console.is_terminal:
            console.print(table)
        else:  # plain text: drop the table's trailing padding
            with console.capture() as captured:
                console.print(table)
            click.echo('\n'.join(line.rstrip() for line in captured.get().splitlines()))

    numbered = {n: item['uuid'] for n, item in enumerate(page_items, start=offset + 1) if item.get('uuid')}
    _save_refs(numbered)
    if len(page) < total:
        click.echo(click.style(f"\nShowing {offset + 1}-{offset + len(page)} of {total}", dim=True))


def list_options(default_limit: Optional[int] = None):
    """Shared --limit/--offset/--json/--long options for listing commands."""
    def decorator(f):
        f = click.option('--long', '-l', 'long', is_flag=True, help='Show full details for each item.')(f)
        f = click.option('--json', 'as_json', is_flag=True, help='Print JSON (same shape as the MCP structured output).')(f)
        f = click.option('--offset', type=click.IntRange(min=0), default=0, show_default=True, help='Skip this many items.')(f)
        f = click.option('--limit', '-n', type=click.IntRange(min=1), default=default_limit,
                         show_default=default_limit is not None, help='Show at most this many items.')(f)
        return f
    return decorator


def _sent(message: str) -> None:
    click.echo(f"{message} — sent to Things")


# ---------------------------------------------------------------------------
# CLI group with friendly error handling
# ---------------------------------------------------------------------------

class _Group(click.Group):
    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except ThingsError as e:
            raise click.ClickException(str(e))
        except sqlite3.Error as e:
            raise click.ClickException(
                f"Couldn't read the Things database ({e}). Is Things 3 installed? "
                "Set THINGSDB to the database path if it lives somewhere unusual."
            )
        except FileNotFoundError as e:
            if e.filename in ('osascript', 'open'):
                raise click.ClickException(f"'{e.filename}' not found — writing to Things needs macOS.")
            raise
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or '').strip() or str(e)
            raise click.ClickException(f"Things rejected the command: {detail}")


@click.group(cls=_Group, invoke_without_command=True,
             context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(package_name='things-mcp')
@click.pass_context
def main(ctx):
    """Things 3 from the command line. With no command, shows Today.

    Refer to items by the number shown in the last listing, a UUID, or a
    UUID prefix.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(today_cmd)


# ---------------------------------------------------------------------------
# Built-in lists
# ---------------------------------------------------------------------------

# Grouping per built-in list, as in the Things app (and the TUI).
LIST_GROUPS = {
    'today': display.group_today,
    'upcoming': display.group_upcoming,
    'anytime': display.group_by_location,
    'someday': display.group_by_location,
}


def _simple_list(name: str, help_text: str):
    """A listing command backed by the core function of the same name."""
    @main.command(name=name, help=help_text)
    @list_options()
    def command(limit, offset, as_json, long):
        items = getattr(core, name)()
        if name in ('anytime', 'someday'):
            items = display.without_headings(items)
        _print_items(items, list_key=name, group=LIST_GROUPS.get(name), limit=limit, offset=offset, as_json=as_json, long=long,
                     empty=f"{name.capitalize()} is empty")
    return command


inbox_cmd = _simple_list('inbox', 'To-dos in the Inbox.')
today_cmd = _simple_list('today', 'To-dos in Today (excluding Someday projects).')
upcoming_cmd = _simple_list('upcoming', 'Scheduled to-dos (excluding Someday projects).')
anytime_cmd = _simple_list('anytime', 'To-dos in Anytime (excluding Someday projects).')
someday_cmd = _simple_list('someday', 'To-dos in Someday, including those in Someday projects.')
trash_cmd = _simple_list('trash', 'Trashed to-dos.')


@main.command('logbook')
@click.option('--period', '-p', default='7d', show_default=True, help="How far back, e.g. 3d, 2w, 1m, 1y.")
@click.option('--project', 'project_ref', help='Only items from this project (number, UUID, prefix or title).')
@list_options(default_limit=50)
def logbook_cmd(period, project_ref, limit, offset, as_json, long):
    """Completed and canceled items, newest first."""
    items = core.logbook(period, _resolve_named(project_ref, 'project'))
    _print_items(items, list_key='logbook', group=display.group_logbook, limit=limit, offset=offset,
                 as_json=as_json, long=long, empty='Nothing logged in that period')


@main.command('recent')
@click.argument('period', default='1d')
@list_options()
def recent_cmd(period, limit, offset, as_json, long):
    """Open items created in the last PERIOD (default 1d), newest first."""
    _print_items(display.without_headings(core.recent(period)), limit=limit, offset=offset,
                 as_json=as_json, long=long, empty=f"Nothing created in the last {period}")


# ---------------------------------------------------------------------------
# Projects, areas, tags, headings
# ---------------------------------------------------------------------------

@main.command('todos')
@click.option('--project', 'project_ref', help='Only to-dos in this project (number, UUID, prefix or title).')
@list_options()
def todos_cmd(project_ref, limit, offset, as_json, long):
    """All open to-dos, optionally in one project."""
    project = _resolve_named(project_ref, 'project')
    _print_items(core.todos(project), list_key='project' if project else '',
                 group=display.group_by_heading if project else None, limit=limit, offset=offset,
                 as_json=as_json, long=long, empty='No to-dos found')


@main.command('projects')
@list_options()
def projects_cmd(limit, offset, as_json, long):
    """Open projects."""
    _print_items(core.projects(), limit=limit, offset=offset, as_json=as_json, long=long, empty='No projects')


@main.command('areas')
@list_options()
def areas_cmd(limit, offset, as_json, long):
    """Areas."""
    _print_items(core.areas(), limit=limit, offset=offset, as_json=as_json, long=long, empty='No areas')


@main.command('tags')
@click.option('--usage', is_flag=True, help='Show how many items use each tag.')
@click.option('--unused', is_flag=True, help='Only tags no item uses (implies --usage).')
@list_options()
def tags_cmd(usage, unused, limit, offset, as_json, long):
    """Tags."""
    if not (usage or unused):
        _print_items(core.tags(), limit=limit, offset=offset, as_json=as_json, long=long, empty='No tags')
        return
    rows = core.tag_usage(only_unused=unused)
    if as_json:
        click.echo(json.dumps([{'tag': t, 'open': o, 'total': a} for t, o, a in rows], indent=2, ensure_ascii=False))
        return
    if not rows:
        click.echo('No unused tags' if unused else 'No tags')
    for title, open_count, all_count in rows:
        click.echo(f"#{title}: {open_count} open, {all_count} total")


@main.command('tagged')
@click.argument('tag')
@list_options()
def tagged_cmd(tag, limit, offset, as_json, long):
    """Open to-dos with TAG."""
    _print_items(core.tagged_items(tag), limit=limit, offset=offset, as_json=as_json, long=long,
                 empty=f"Nothing tagged #{tag}")


@main.command('headings')
@click.option('--project', 'project_ref', help='Only headings in this project (number, UUID, prefix or title).')
@list_options()
def headings_cmd(project_ref, limit, offset, as_json, long):
    """Headings, optionally in one project."""
    _print_items(core.headings(_resolve_named(project_ref, 'project')), limit=limit, offset=offset,
                 as_json=as_json, long=long, empty='No headings')


# ---------------------------------------------------------------------------
# Search and detail
# ---------------------------------------------------------------------------

@main.command('search')
@click.argument('query', nargs=-1, required=True)
@list_options()
def search_cmd(query, limit, offset, as_json, long):
    """Search to-do titles and notes."""
    text = ' '.join(query)
    _print_items(core.search(text), list_key='search', group=display.group_by_location,
                 limit=limit, offset=offset, as_json=as_json, long=long,
                 empty=f"Nothing matches '{text}'")


@main.command('find')
@click.option('--status', type=click.Choice(['incomplete', 'completed', 'canceled']))
@click.option('--start-date', help='YYYY-MM-DD, optionally with an operator such as ">=2026-01-01".')
@click.option('--stop-date', help="Completion date, e.g. '>=2026-01-01', 'past'.")
@click.option('--deadline', help='YYYY-MM-DD, optionally with an operator.')
@click.option('--tag')
@click.option('--area', 'area_ref', help='Area (number, UUID, prefix or title).')
@click.option('--project', 'project_ref', help='Project (number, UUID, prefix or title).')
@click.option('--type', 'kind', type=click.Choice(['to-do', 'project', 'heading']))
@click.option('--last', help="Created within, e.g. 3d, 1w.")
@list_options()
def find_cmd(status, start_date, stop_date, deadline, tag, area_ref, project_ref, kind, last,
             limit, offset, as_json, long):
    """Search with filters (same as the MCP search_advanced tool)."""
    items = core.search_advanced(
        status=status, start_date=start_date, stop_date=stop_date, deadline=deadline,
        tag=tag, area=_resolve_named(area_ref, 'area'), project=_resolve_named(project_ref, 'project'),
        type=kind, last=last,
    )
    _print_items(items, limit=limit, offset=offset, as_json=as_json, long=long, empty='No matches')


@main.command('show')
@click.argument('ref')
@click.option('--json', 'as_json', is_flag=True, help='Print the raw item as JSON.')
def show_cmd(ref, as_json):
    """Show full details of one item."""
    item = core.get(resolve_ref(ref))
    if not item:
        raise ThingsError(f"'{ref}' no longer exists — list again to refresh the numbers.")
    if as_json:
        click.echo(json.dumps(item, default=str, indent=2, ensure_ascii=False))
    else:
        click.echo(display.detail(item))


@main.command('open')
@click.argument('target', default='today')
def open_cmd(target):
    """Reveal an item or list (inbox, today, upcoming, …) in the Things app."""
    core.show_in_app(target if target.lower() in BUILTIN_LISTS else resolve_ref(target))


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------

def _split_tags(value: Optional[str]) -> Optional[list[str]]:
    if value is None:
        return None
    return [t.strip() for t in value.split(',') if t.strip()]


@main.command('add')
@click.argument('title', nargs=-1, required=True)
@click.option('--notes')
@click.option('--when', '-w', help='today, tomorrow, evening, anytime, someday, YYYY-MM-DD or YYYY-MM-DD@HH:MM.')
@click.option('--deadline', '-d', help='YYYY-MM-DD.')
@click.option('--tag', '-t', 'tags', multiple=True, help='Tag (repeatable; must already exist).')
@click.option('--checklist', '-c', multiple=True, help='Checklist item (repeatable).')
@click.option('--list', 'list_title', help='Project or area title to add to.')
@click.option('--in', 'list_ref', help='Project or area to add to (number, UUID or prefix).')
@click.option('--heading', help='Heading title within the project.')
@click.option('--heading-id', 'heading_ref', help='Heading (number, UUID or prefix).')
def add_cmd(title, notes, when, deadline, tags, checklist, list_title, list_ref, heading, heading_ref):
    """Create a to-do. TITLE can be several words without quotes."""
    text = ' '.join(title)
    core.add_todo(
        text, notes=notes, when=when, deadline=deadline, tags=list(tags) or None,
        checklist_items=list(checklist) or None, list_id=_resolve_opt(list_ref),
        list_title=list_title, heading=heading, heading_id=_resolve_opt(heading_ref),
    )
    _sent(f"Added '{text}'")


@main.command('add-project')
@click.argument('title', nargs=-1, required=True)
@click.option('--notes')
@click.option('--when', '-w')
@click.option('--deadline', '-d')
@click.option('--tag', '-t', 'tags', multiple=True)
@click.option('--area', 'area_title', help='Area title to add to.')
@click.option('--area-id', 'area_ref', help='Area (number, UUID or prefix).')
@click.option('--todo', 'todos', multiple=True, help='Initial to-do (repeatable).')
def add_project_cmd(title, notes, when, deadline, tags, area_title, area_ref, todos):
    """Create a project."""
    text = ' '.join(title)
    core.add_project(
        text, notes=notes, when=when, deadline=deadline, tags=list(tags) or None,
        area_id=_resolve_opt(area_ref), area_title=area_title, todos=list(todos) or None,
    )
    _sent(f"Added project '{text}'")


@main.command('add-area')
@click.argument('title', nargs=-1, required=True)
def add_area_cmd(title):
    """Create an area (via AppleScript)."""
    text = ' '.join(title)
    area_id = core.add_area(text)
    click.echo(f"Created area '{text}' ({area_id})")


# ---------------------------------------------------------------------------
# Changing
# ---------------------------------------------------------------------------

@main.command('update')
@click.argument('ref')
@click.option('--title')
@click.option('--notes')
@click.option('--when', '-w')
@click.option('--deadline', '-d')
@click.option('--tags', help='Comma-separated tags, replacing existing ones ("" clears).')
@click.option('--add-tag', '-t', 'add_tags', multiple=True, help='Tag to add (repeatable; to-dos only).')
@click.option('--list', 'list_title', help='Move to this project/area title (to-dos only).')
@click.option('--in', 'list_ref', help='Move to this project/area (to-dos only).')
@click.option('--heading', help='Move under this heading title (to-dos only).')
@click.option('--heading-id', 'heading_ref', help='Move under this heading (to-dos only).')
@click.option('--checklist', multiple=True, help='Replace the checklist (repeatable; to-dos only).')
@click.option('--clear-checklist', is_flag=True, help='Remove all checklist items (to-dos only).')
@click.option('--prepend', multiple=True, help='Checklist item to add at the top (to-dos only).')
@click.option('--append', multiple=True, help='Checklist item to add at the bottom (to-dos only).')
def update_cmd(ref, title, notes, when, deadline, tags, add_tags, list_title, list_ref, heading,
               heading_ref, checklist, clear_checklist, prepend, append):
    """Change a to-do or project."""
    uuid = resolve_ref(ref)
    item = core.get(uuid)
    if not item:
        raise ThingsError(f"'{ref}' no longer exists — list again to refresh the numbers.")
    common = {'title': title, 'notes': notes, 'when': when, 'deadline': deadline,
              'tags': _split_tags(tags)}
    todo_only = {
        'add_tags': list(add_tags) or None,
        'list': list_title,
        'list_id': _resolve_opt(list_ref),
        'heading': heading,
        'heading_id': _resolve_opt(heading_ref),
        'checklist_items': [] if clear_checklist else (list(checklist) or None),
        'prepend_checklist_items': list(prepend) or None,
        'append_checklist_items': list(append) or None,
    }
    changes = {k: v for k, v in {**common, **todo_only}.items() if v is not None}
    if not changes:
        raise ThingsError("Nothing to change — pass at least one option (see --help).")
    kind = item.get('type')
    if kind == 'project':
        unsupported = sorted(k for k in todo_only if todo_only[k] is not None)
        if unsupported:
            raise ThingsError(f"Projects don't support: {', '.join(unsupported)}")
        core.update_project(uuid, **changes)
    elif kind == 'to-do':
        core.update_todo(uuid, **changes)
    elif kind == 'area':
        raise ThingsError(f"'{item.get('title')}' is an area; use update-area for areas.")
    else:
        raise ThingsError(f"'{item.get('title')}' is a {kind}; only to-dos and projects can be updated.")
    _sent(f"Updated '{item.get('title')}'")


def _bulk(refs, verb: str, **changes) -> None:
    count = core.update_items(_resolve_all(refs), **changes)
    _sent(f"{verb} {count} item{'s' if count != 1 else ''}")


@main.command('done')
@click.argument('refs', nargs=-1, required=True)
def done_cmd(refs):
    """Mark to-dos/projects complete."""
    _bulk(refs, 'Completed', completed=True)


@main.command('cancel')
@click.argument('refs', nargs=-1, required=True)
def cancel_cmd(refs):
    """Mark to-dos/projects canceled."""
    _bulk(refs, 'Canceled', canceled=True)


@main.command('reopen')
@click.argument('refs', nargs=-1, required=True)
def reopen_cmd(refs):
    """Mark completed/canceled to-dos/projects open again."""
    _bulk(refs, 'Reopened', completed=False)


@main.command('schedule')
@click.argument('when')
@click.argument('refs', nargs=-1, required=True)
def schedule_cmd(when, refs):
    """Set WHEN (today, tomorrow, evening, anytime, someday, YYYY-MM-DD) on items."""
    _bulk(refs, f"Scheduled ({when})", when=when)


@main.command('deadline')
@click.argument('date')
@click.argument('refs', nargs=-1, required=True)
def deadline_cmd(date, refs):
    """Set a deadline (YYYY-MM-DD) on items."""
    _bulk(refs, f"Set deadline {date} on", deadline=date)


@main.command('move')
@click.argument('refs', nargs=-1, required=True)
@click.option('--to', 'list_title', help='Project or area title.')
@click.option('--to-id', 'list_ref', help='Project or area (number, UUID or prefix).')
@click.option('--heading', help='Heading title within the destination project.')
def move_cmd(refs, list_title, list_ref, heading):
    """Move to-dos into a project or area."""
    if not (list_title or list_ref or heading):
        raise ThingsError("Say where to: --to TITLE, --to-id REF or --heading TITLE.")
    _bulk(refs, 'Moved', list=list_title, list_id=_resolve_opt(list_ref), heading=heading)


@main.command('tag')
@click.argument('refs', nargs=-1, required=True)
@click.option('--add', '-a', 'add', multiple=True, help='Tag to add (repeatable).')
@click.option('--set', 'replace', help='Comma-separated tags replacing existing ones.')
def tag_cmd(refs, add, replace):
    """Add or replace tags on to-dos."""
    if not add and replace is None:
        raise ThingsError("Pass --add TAG or --set TAGS.")
    _bulk(refs, 'Tagged', add_tags=list(add) or None, tags=_split_tags(replace))


@main.command('update-area')
@click.argument('ref')
@click.option('--title', help='New name.')
@click.option('--tags', help='Comma-separated tags, replacing existing ones.')
def update_area_cmd(ref, title, tags):
    """Rename an area or set its tags (via AppleScript)."""
    uuid = resolve_ref(ref)
    item = core.get(uuid) or {}
    if item.get('type') != 'area':
        raise ThingsError(f"'{item.get('title', ref)}' isn't an area — list areas with 'things areas' first.")
    core.update_area(uuid, title=title, tags=_split_tags(tags))
    click.echo(f"Updated area '{item.get('title')}'")


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------

@main.command('tui')
def tui_cmd():
    """Open the full-screen terminal interface."""
    try:
        from .tui import run
    except ImportError as e:
        raise click.ClickException(
            f"The TUI needs the 'tui' extra ({e.name} is missing): "
            "pip install 'things-mcp[tui]' or uv sync --extra tui"
        )
    run()


if __name__ == '__main__':
    main()
