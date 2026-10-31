"""Front-end-agnostic Things operations shared by the MCP server, CLI and TUI.

Everything here returns plain Python data (lists of things.py item dicts, IDs,
counts) and raises ``ThingsError`` for user-facing problems. Presentation —
MCP ``ToolResult`` envelopes, CLI rows, TUI widgets — lives in the front ends.

Reads go through things.py (read-only SQLite access). Writes go through the
Things URL scheme or, for Areas, AppleScript — see ``url_scheme``. URL-scheme
writes are fire-and-forget: they return once macOS has handed the URL to
Things, not once Things has saved the change.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable, Optional

import things

from . import url_scheme


class ThingsError(Exception):
    """A user-facing error (bad UUID, bad period, missing auth token, …).

    The message is shown to the user verbatim by every front end.
    """


# ---------------------------------------------------------------------------
# Someday filtering
# ---------------------------------------------------------------------------

def _get_someday_context():
    """Return (someday_project_ids, heading_to_project) for Someday filtering.

    Returns:
        Tuple of (set of Someday project UUIDs, dict mapping heading UUID to project UUID)
    """
    try:
        someday_project_ids = {p['uuid'] for p in (things.projects(start='Someday') or [])}
    except Exception:
        return set(), {}
    if not someday_project_ids:
        return set(), {}
    # Build heading -> project mapping for headings inside Someday projects
    heading_to_project = {}
    for proj_id in someday_project_ids:
        try:
            headings = things.tasks(type='heading', project=proj_id)
            for h in (headings or []):
                heading_to_project[h['uuid']] = proj_id
        except Exception:
            pass
    return someday_project_ids, heading_to_project


def _is_in_someday_project(todo, someday_project_ids, heading_to_project):
    """Check if a todo belongs to a Someday project, directly or via heading."""
    if todo.get('project') in someday_project_ids:
        return True
    if not todo.get('project') and todo.get('heading'):
        return todo['heading'] in heading_to_project
    return False


def filter_someday_project_tasks(todos):
    """Filter out tasks that belong to Someday projects.

    This matches Things UI behavior where tasks from Someday projects
    don't appear in Today, Upcoming, or Anytime views. Handles both
    direct project membership and tasks under headings in Someday projects.
    """
    someday_project_ids, heading_to_project = _get_someday_context()
    if not someday_project_ids:
        return todos
    return [todo for todo in todos if not _is_in_someday_project(todo, someday_project_ids, heading_to_project)]


def _today_fallback():
    """Re-implementation of ``things.today()`` with a None-safe sort key.

    Workaround for an upstream things-py bug (see things-mcp #43): the
    library's ``today()`` aggregates three task sets and sorts the union
    on ``(today_index, start_date)``. The "unconfirmed overdue" branch
    selects tasks via ``start_date=False`` — i.e. tasks with a deadline
    today but no start date — so ``start_date`` is None for those rows.
    Mixed with the other two branches (which have string start_dates),
    the tuple comparison crashes with
    ``'<' not supported between instances of 'NoneType' and 'str'``.

    We push None start_dates to the end with a sentinel string.
    """
    regular = things.tasks(
        start_date=True, start="Anytime", index="todayIndex", include_items=True
    ) or []
    unconfirmed_scheduled = things.tasks(
        start_date="past", start="Someday", index="todayIndex", include_items=True
    ) or []
    unconfirmed_overdue = things.tasks(
        start_date=False, deadline="past", deadline_suppressed=False, include_items=True
    ) or []
    result = [*regular, *unconfirmed_scheduled, *unconfirmed_overdue]
    result.sort(key=lambda t: (
        t["today_index"] if t.get("today_index") is not None else 0,
        t["start_date"] if t.get("start_date") is not None else "9999-99-99",
    ))
    return result


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r'(\d+)([dwmy])')
_PERIOD_DAYS = {'d': 1, 'w': 7, 'm': 30, 'y': 365}


def parse_period(period: str):
    """Return a timedelta for strings like '7d', '2w', '3m', '1y', or None."""
    match = _PERIOD_RE.fullmatch(period.strip().lower())
    if not match:
        return None
    return timedelta(days=int(match.group(1)) * _PERIOD_DAYS[match.group(2)])


def item_datetime(todo, key):
    """Parse a todo's local-time date field (e.g. 'stop_date', 'created') into a
    naive datetime, or None if absent/unparseable."""
    value = todo.get(key)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace(' ', 'T'))
    except ValueError:
        return None


def _require_period(period: str, example: str) -> timedelta:
    delta = parse_period(period)
    if delta is None:
        raise ThingsError(
            f"Invalid period {period!r}. Use a number followed by d/w/m/y, "
            f"e.g. {example}."
        )
    return delta


def _require_project(project_uuid: str) -> None:
    project = things.get(project_uuid)
    if not project or project.get('type') != 'project':
        raise ThingsError(f"Error: Invalid project UUID '{project_uuid}'")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def inbox() -> list:
    return things.inbox(include_items=True) or []


def today() -> list:
    try:
        todos = things.today(include_items=True)
    except TypeError:
        todos = _today_fallback()
    return filter_someday_project_tasks(todos or [])


def upcoming() -> list:
    return filter_someday_project_tasks(things.upcoming(include_items=True) or [])


def anytime() -> list:
    return filter_someday_project_tasks(things.anytime(include_items=True) or [])


def someday() -> list:
    """Someday list, plus Anytime tasks that live in a Someday project
    (things.py doesn't inherit a project's Someday status)."""
    todos = things.someday(include_items=True)
    if todos is None:
        todos = []
    someday_project_ids, heading_to_project = _get_someday_context()
    if someday_project_ids:
        anytime_todos = things.anytime(include_items=True) or []
        existing_uuids = {t['uuid'] for t in todos}
        for todo in anytime_todos:
            if _is_in_someday_project(todo, someday_project_ids, heading_to_project) and todo['uuid'] not in existing_uuids:
                todos.append(todo)
    return todos


def logbook(period: str = "7d", project_uuid: Optional[str] = None) -> list:
    """Completed and canceled items stopped within ``period``, newest first."""
    # things.last(period, status='completed') filters on creationDate, not
    # stopDate — so tasks created before the window but completed inside it
    # are invisible (which is most tasks in real use). Fetch all logged
    # tasks and filter on stop_date in Python. The Logbook holds both
    # completed and canceled tasks, so query both statuses.
    delta = _require_period(period, "'7d', '2w', '3m', '1y'")
    cutoff = datetime.now() - delta
    logged = []
    for status in ('completed', 'canceled'):
        logged.extend(things.tasks(status=status, include_items=True, project=project_uuid) or [])
    in_window = []
    for todo in logged:
        stopped = item_datetime(todo, 'stop_date')
        if stopped is not None and stopped >= cutoff:
            in_window.append((stopped, todo))
    in_window.sort(key=lambda pair: pair[0], reverse=True)
    return [t for _, t in in_window]


def trash() -> list:
    return things.trash(include_items=True) or []


def todos(project_uuid: Optional[str] = None, include_items: bool = True) -> list:
    if project_uuid:
        _require_project(project_uuid)
    return things.todos(project=project_uuid, start=None, include_items=include_items) or []


def projects() -> list:
    return things.projects() or []


def areas() -> list:
    return things.areas() or []


def area_items(area_uuid: str) -> list:
    """Open projects and to-dos that sit directly in an area."""
    return [*(things.projects(area=area_uuid) or []), *(things.todos(area=area_uuid) or [])]


def tags() -> list:
    return things.tags() or []


def tagged_items(tag: str) -> list:
    return things.todos(tag=tag, include_items=True) or []


def tag_usage(only_unused: bool = False, tag_list: Optional[list] = None) -> list[tuple[str, int, int]]:
    """Return (tag, open_count, total_count) rows, most-used first
    (or alphabetical unused tags when ``only_unused``). Pass ``tag_list`` to
    reuse an already-fetched list of tags."""
    rows = []
    for tag in (tags() if tag_list is None else tag_list):
        title = tag['title']
        open_count = len(things.todos(tag=title) or [])
        all_count = len(things.tasks(tag=title, status=None) or [])
        rows.append((title, open_count, all_count))
    if only_unused:
        rows = [r for r in rows if r[2] == 0]
        rows.sort(key=lambda r: r[0].lower())
    else:
        rows.sort(key=lambda r: (-r[2], r[0].lower()))
    return rows


def headings(project_uuid: Optional[str] = None) -> list:
    if project_uuid:
        _require_project(project_uuid)
        return things.tasks(type='heading', project=project_uuid) or []
    return things.tasks(type='heading') or []


def search(query: str) -> list:
    return things.search(query, include_items=True) or []


def search_advanced(status=None, start_date=None, stop_date=None, deadline=None,
                    tag=None, area=None, project=None, type=None, last=None) -> list:
    filters = {
        "status": status, "start_date": start_date, "stop_date": stop_date,
        "deadline": deadline, "tag": tag, "area": area, "project": project,
        "last": last,
    }
    search_params = {k: v for k, v in filters.items() if v}
    if type:
        # things.todos() hardcodes type="to-do", so use things.tasks()
        return things.tasks(type=type, include_items=True, **search_params) or []
    return things.todos(include_items=True, **search_params) or []


def recent(period: str) -> list:
    """Open items created within a rolling window ending now."""
    delta = _require_period(period, "'1d', '2w', '3m', '1y'")
    # things.last() compares the local-time creation date against SQLite's
    # UTC 'now', so its window is skewed by the UTC offset (west of UTC, '1d'
    # misses items from earlier in the day). It also rejects months. Over-fetch
    # by a day and filter on 'created' (local time) in Python.
    items = things.last(f"{delta.days + 1}d", include_items=True) or []
    cutoff = datetime.now() - delta
    return [t for t in items
            if (created := item_datetime(t, 'created')) is not None and created >= cutoff]


def get(uuid: str):
    """Fetch any item (to-do, project, heading, area, tag) by UUID, or None."""
    try:
        return things.get(uuid)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def add_todo(title, notes=None, when=None, deadline=None, tags=None,
             checklist_items=None, list_id=None, list_title=None,
             heading=None, heading_id=None) -> None:
    url_scheme.execute_url(url_scheme.add_todo(
        title=title, notes=notes, when=when, deadline=deadline, tags=tags,
        checklist_items=checklist_items, list_id=list_id, list_title=list_title,
        heading=heading, heading_id=heading_id,
    ))


def add_project(title, notes=None, when=None, deadline=None, tags=None,
                area_id=None, area_title=None, todos=None) -> None:
    url_scheme.execute_url(url_scheme.add_project(
        title=title, notes=notes, when=when, deadline=deadline, tags=tags,
        area_id=area_id, area_title=area_title, todos=todos,
    ))


def update_todo(id, **changes) -> None:
    """Update one to-do. ``changes`` are url_scheme.update_todo keyword args."""
    url_scheme.execute_url(url_scheme.update_todo(id=id, **changes))


def update_project(id, **changes) -> None:
    """Update one project. ``changes`` are url_scheme.update_project keyword args."""
    url_scheme.execute_url(url_scheme.update_project(id=id, **changes))


def bulk_update_todos(ids: list, list=None, list_id=None, tags=None, add_tags=None,
                      when=None, deadline=None, heading=None, heading_id=None,
                      completed=None, canceled=None) -> int:
    """Apply the same change to many to-dos via one ``things:///json`` call.

    Returns the number of to-dos submitted.
    """
    if not ids:
        raise ThingsError("No items to update")

    attributes: dict = {}
    if list_id is not None:
        attributes['list-id'] = list_id
    elif list is not None:
        attributes['list'] = list
    if tags is not None:
        attributes['tags'] = tags
    if add_tags is not None:
        attributes['add-tags'] = add_tags
    if when is not None:
        attributes['when'] = when
    if deadline is not None:
        attributes['deadline'] = deadline
    if heading_id is not None:
        attributes['heading-id'] = heading_id
    elif heading is not None:
        attributes['heading'] = heading
    if completed is not None:
        attributes['completed'] = completed
    if canceled is not None:
        attributes['canceled'] = canceled

    if not attributes:
        raise ThingsError("No changes specified — pass at least one attribute (list, tags, when, …).")

    token = things.token()
    if not token:
        raise ThingsError(
            "THINGS_AUTH_TOKEN not configured. Bulk updates require it. "
            "Enable in Things → Settings → General → Manage."
        )

    payload = [
        {"type": "to-do", "operation": "update", "id": uid, "attributes": attributes}
        for uid in ids
    ]
    url_scheme.execute_url(url_scheme.json_command(payload, auth_token=token))
    return len(ids)


def update_items(uuids: Iterable[str], **changes) -> int:
    """Apply the same change to a mix of to-dos and projects.

    Changes accepted by both item types: title, notes, when, deadline, tags,
    completed, canceled. To-dos additionally accept add_tags, list, list_id,
    heading, heading_id and the checklist arguments. One to-do goes through ``update``; several go through a single
    bulk ``json`` call. Projects are updated one at a time.

    Returns the number of items submitted.
    """
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        raise ThingsError("No changes specified.")
    todo_ids, project_ids = [], []
    for uuid in uuids:
        item = get(uuid)
        if not item:
            raise ThingsError(f"No item with UUID '{uuid}'")
        kind = item.get('type')
        if kind == 'to-do':
            todo_ids.append(uuid)
        elif kind == 'project':
            project_ids.append(uuid)
        else:
            raise ThingsError(f"'{item.get('title', uuid)}' is a {kind}; only to-dos and projects can be changed this way")

    project_ok = {'title', 'notes', 'when', 'deadline', 'tags', 'completed', 'canceled'}
    if project_ids and set(changes) - project_ok:
        bad = ", ".join(sorted(set(changes) - project_ok))
        raise ThingsError(f"Projects don't support: {bad}")

    bulk_ok = {'list', 'list_id', 'tags', 'add_tags', 'when', 'deadline',
               'heading', 'heading_id', 'completed', 'canceled'}
    if len(todo_ids) == 1 or (todo_ids and set(changes) - bulk_ok):
        # Single item, or a change the bulk JSON call doesn't cover (title,
        # notes, checklist): one update URL per to-do.
        for tid in todo_ids:
            update_todo(tid, **changes)
    elif todo_ids:
        bulk_update_todos(todo_ids, **changes)
    for pid in project_ids:
        update_project(pid, **changes)
    return len(todo_ids) + len(project_ids)


def add_area(title: str) -> str:
    """Create an Area via AppleScript; returns its UUID."""
    return url_scheme.add_area(title=title)


def update_area(id: str, title: Optional[str] = None, tags: Optional[list] = None) -> None:
    if title is None and tags is None:
        raise ThingsError("No changes specified — pass title and/or tags.")
    url_scheme.update_area(area_id=id, title=title, tags=tags)


def show_in_app(id: str, query: Optional[str] = None, filter_tags: Optional[list] = None) -> None:
    """Reveal an item or built-in list in the Things app."""
    url_scheme.execute_url(url_scheme.show(id=id, query=query, filter_tags=filter_tags))


def search_in_app(query: str) -> None:
    """Open the Things app's search with ``query``."""
    url_scheme.execute_url(url_scheme.search(query))


def database_path() -> Optional[str]:
    """Path to the Things SQLite file things.py reads, or None if not found."""
    import os
    from things import database
    path = os.environ.get(database.ENVIRONMENT_VARIABLE_WITH_FILEPATH) or getattr(database, 'DEFAULT_FILEPATH', None)
    return path if path and os.path.exists(path) else None
