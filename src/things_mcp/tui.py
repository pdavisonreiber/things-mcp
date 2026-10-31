"""``things tui`` — a full-screen terminal interface to Things 3 (Textual).

Layout follows the Things Mac app: a sidebar grouped like Things' (Inbox /
Today, Upcoming, Anytime, Someday / Logbook, Trash / projects / areas with
their projects nested beneath), and the selected list grouped the way Things
groups it (This Evening, Upcoming by date, Anytime by project, projects by
heading). A detail pane stands in for Things' inline to-do expansion.

Key bindings follow Things' Mac shortcuts with ⌘ dropped and ⇧ kept: ⌘K
complete → k, ⇧⌘M move → M, ⌘S When → s, ⌘1–⌘6 → 1–6, and so on. ⌃ and ⌥
are dropped too where terminals can't send them reliably (⌃[ is Escape;
⌥ is usually a character modifier on macOS), so ⌃] (start date +1 day)
becomes ], and ⌥⌘K (cancel) becomes K. Press ? for the full list.

Reads come from the Things database via ``core``. Writes go through the
Things URL scheme, which is fire-and-forget, so the app updates the row it
changed straight away, then re-reads the database a moment later. It also
watches the database file and refreshes whenever Things saves, so edits made
in the Things app show up here too.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import core, display
from .core import ThingsError

REFRESH_AFTER_WRITE = 1.0   # seconds to wait before re-reading after a write
DB_POLL_INTERVAL = 2.0      # seconds between database change checks
HEADER_PREFIX = 'hdr:'      # row keys for group headings in the item table

Groups = list[tuple[Optional[str], list]]


# ---------------------------------------------------------------------------
# Grouping, like the Things lists
# ---------------------------------------------------------------------------

def no_groups(items: list) -> Groups:
    return [(None, items)]


def group_by(key: Callable[[dict], Optional[str]], items: list, ungrouped_first: bool = True) -> Groups:
    """Group items by key, keeping first-seen order (and the items' order)."""
    groups: dict[Optional[str], list] = {}
    for item in items:
        groups.setdefault(key(item) or None, []).append(item)
    ordered = list(groups.items())
    if ungrouped_first:
        ordered.sort(key=lambda g: g[0] is not None)  # stable: only moves None first
    return ordered


def group_today(items: list) -> Groups:
    """Today, then This Evening (as in Things)."""
    evening = core.evening_uuids()
    return [(None, [i for i in items if i['uuid'] not in evening]),
            ('This Evening', [i for i in items if i['uuid'] in evening])]


def _day_label(value) -> Optional[str]:
    if not value:
        return None
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    if d == date.today() + timedelta(days=1):
        return 'Tomorrow'
    return f"{d:%a} {d.day} {d:%b}" + (f" {d.year}" if d.year != date.today().year else '')


def group_upcoming(items: list) -> Groups:
    return group_by(lambda i: _day_label(i.get('start_date')), items, ungrouped_first=False)


def group_by_location(items: list) -> Groups:
    return group_by(lambda i: i.get('project_title') or i.get('area_title'), items)


def group_logbook(items: list) -> Groups:
    return group_by(lambda i: _day_label(i.get('stop_date')), items, ungrouped_first=False)


def group_by_heading(items: list) -> Groups:
    return group_by(lambda i: i.get('heading_title'), items)


# ---------------------------------------------------------------------------
# Sidebar sources
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """Something the sidebar can show: a built-in list, project, area or search."""
    key: str
    label: str
    fetch: Callable[[], list]
    add_defaults: dict = field(default_factory=dict)  # applied to new to-dos
    group: Callable[[list], Groups] = no_groups
    read_only: bool = False


BUILTIN_ORDER = ['inbox', 'today', 'upcoming', 'anytime', 'someday', 'logbook']  # ⌘1–⌘6


def builtin_sources() -> list[Source]:
    return [
        Source('inbox', 'Inbox', core.inbox),
        Source('today', 'Today', core.today, {'when': 'today'}, group_today),
        Source('upcoming', 'Upcoming', core.upcoming, group=group_upcoming),
        Source('anytime', 'Anytime', core.anytime, {'when': 'anytime'}, group_by_location),
        Source('someday', 'Someday', core.someday, {'when': 'someday'}, group_by_location),
        Source('logbook', 'Logbook', lambda: core.logbook('1m'), group=group_logbook, read_only=True),
        Source('trash', 'Trash', core.trash, read_only=True),
    ]


def project_source(p: dict) -> Source:
    return Source(f"project:{p['uuid']}", p['title'], lambda uuid=p['uuid']: core.todos(uuid),
                  {'list_id': p['uuid']}, group_by_heading)


def area_source(a: dict) -> Source:
    return Source(f"area:{a['uuid']}", a['title'], lambda uuid=a['uuid']: core.area_items(uuid),
                  {'list_id': a['uuid']})


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class PromptScreen(ModalScreen[Optional[str]]):
    """A one-line text prompt. Enter submits (possibly empty); Escape cancels (None)."""

    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    def __init__(self, question: str, value: str = '', placeholder: str = ''):
        super().__init__()
        self.question = question
        self.value = value
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id='prompt'):
            yield Label(self.question)
            yield Input(value=self.value, placeholder=self.placeholder)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class ItemTable(DataTable):
    """The item list. Arrow keys left/right go back / enter (Things: ⌘← / ⌘→)."""

    BINDINGS = [
        Binding('left', 'app.go_back', 'Back', show=False),
        Binding('right', 'app.enter_item', 'Enter project', show=False),
        Binding('alt+up', 'cursor_first', 'Select first', show=False),
        Binding('alt+down', 'cursor_last', 'Select last', show=False),
    ]

    def action_cursor_first(self) -> None:
        if self.row_count:
            self.move_cursor(row=0)

    def action_cursor_last(self) -> None:
        if self.row_count:
            self.move_cursor(row=self.row_count - 1)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class ThingsApp(App):
    TITLE = 'Things'
    CSS = """
    #sidebar { width: 32; border-right: solid $panel; }
    #main { width: 1fr; }
    #items { height: 2fr; }
    #detail-pane { height: 1fr; border-top: solid $panel; padding: 0 1; }
    PromptScreen { align: center middle; }
    #prompt { width: 70; height: auto; padding: 1 2; border: thick $accent; background: $surface; }
    """

    # Things Mac shortcut in the description where it differs from the key.
    BINDINGS = [
        # Create
        Binding('n', 'new_todo', 'New'),
        Binding('space', 'new_todo', 'New to-do (Space)', show=False),
        # Edit
        Binding('d', 'duplicate', 'Duplicate (⌘D)', show=False),
        Binding('k', 'complete', 'Done'),
        Binding('K', 'cancel_item', 'Cancel (⌥⌘K)', show=False),
        # Move
        Binding('M', 'move', 'Move'),
        # Dates
        Binding('s', 'when', 'When'),
        Binding('t', 'start("today")', 'Start Today (⌘T)', show=False),
        Binding('e', 'start("evening")', 'Start This Evening (⌘E)', show=False),
        Binding('r', 'start("anytime")', 'Start Anytime (⌘R)', show=False),
        Binding('o', 'start("someday")', 'Start Someday (⌘O)', show=False),
        Binding('right_square_bracket', 'shift_start(1)', 'Start date +1 day (⌃])', show=False),
        Binding('left_square_bracket', 'shift_start(-1)', 'Start date -1 day (⌃[)', show=False),
        Binding('right_curly_bracket', 'shift_start(7)', 'Start date +1 week (⌃⇧])', show=False),
        Binding('left_curly_bracket', 'shift_start(-7)', 'Start date -1 week (⌃⇧[)', show=False),
        Binding('D', 'deadline', 'Deadline (⇧⌘D)', show=False),
        Binding('full_stop', 'shift_deadline(1)', 'Deadline +1 day (⌃.)', show=False),
        Binding('comma', 'shift_deadline(-1)', 'Deadline -1 day (⌃,)', show=False),
        Binding('greater_than_sign', 'shift_deadline(7)', 'Deadline +1 week (⌃⇧.)', show=False),
        Binding('less_than_sign', 'shift_deadline(-7)', 'Deadline -1 week (⌃⇧,)', show=False),
        # Tags
        Binding('T', 'edit_tags', 'Tags'),
        # Windows
        Binding('slash', 'toggle_sidebar', 'Show/hide sidebar (⌘/)', show=False),
        # Search & navigate
        Binding('f', 'find', 'Find'),
        Binding('O', 'jump', 'Go to list… (⇧⌘O)', show=False),
        *[Binding(str(n), f'go({n})', f'Go to {k.capitalize()} (⌘{n})', show=False)
          for n, k in enumerate(BUILTIN_ORDER, start=1)],
        Binding('L', 'show_in_parent', 'Show in parent list (⌘L)', show=False),
        # Not in Things
        Binding('ctrl+o', 'open_in_things', 'Show in Things app', show=False),
        Binding('ctrl+r', 'refresh', 'Refresh', show=False),
        Binding('question_mark', 'help', 'Keys'),
        Binding('q', 'quit', 'Quit'),
    ]

    def __init__(self, db_path: Optional[str] = None):
        super().__init__()
        self.db_path = db_path
        self.sources: dict[str, Source] = {}
        self.current: Optional[Source] = None
        self.items: dict[str, dict] = {}
        self.history: list[str] = []
        self._db_stamp = self._stamp()

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield OptionList(id='sidebar')
            with Vertical(id='main'):
                yield ItemTable(id='items', cursor_type='row', zebra_stripes=True)
                with VerticalScroll(id='detail-pane'):
                    yield Static(id='detail')
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#items', DataTable)
        table.add_column('', key='mark', width=1)
        table.add_column('Title', key='title')
        table.add_column('Where', key='where')
        table.add_column('When', key='when')
        table.add_column('Deadline', key='deadline')
        table.add_column('Tags', key='tags')
        self.load_sidebar()
        self.select_source('today')
        if self.db_path:
            self.set_interval(DB_POLL_INTERVAL, self.check_database)

    # -- sidebar -------------------------------------------------------------

    def load_sidebar(self) -> None:
        """Build the sidebar in Things' order: Inbox / Today, Upcoming,
        Anytime, Someday / Logbook, Trash / loose projects / areas, each
        followed by its projects."""
        builtins = {s.key: s for s in builtin_sources()}
        sources = list(builtins.values())
        options: list = []
        for group in (['inbox'], ['today', 'upcoming', 'anytime', 'someday'], ['logbook', 'trash']):
            if options:
                options.append(None)
            options += [Option(builtins[k].label, id=k) for k in group]

        try:
            projects, areas = core.projects(), core.areas()
        except Exception as e:  # database unavailable: still show the shell
            self.notify(f"Couldn't read Things: {e}", severity='error')
            projects, areas = [], []
        area_ids = {a['uuid'] for a in areas}
        loose = [p for p in projects if p.get('area') not in area_ids]
        if loose:
            options.append(None)
            for p in loose:
                s = project_source(p)
                sources.append(s)
                options.append(Option(f"○ {p['title']}", id=s.key))
        for a in areas:
            options.append(None)
            s = area_source(a)
            sources.append(s)
            options.append(Option(Text(f"▣ {a['title']}", style='bold'), id=s.key))
            for p in projects:
                if p.get('area') == a['uuid']:
                    ps = project_source(p)
                    sources.append(ps)
                    options.append(Option(f"  ○ {p['title']}", id=ps.key))

        if self.current and self.current.key.startswith('search:'):
            sources.append(self.current)
        self.sources = {s.key: s for s in sources}

        sidebar = self.query_one('#sidebar', OptionList)
        sidebar.clear_options()
        sidebar.add_options(options)
        if self.current and self.current.key in self.sources:
            self._highlight_sidebar(self.current.key)

    def _highlight_sidebar(self, key: str) -> None:
        sidebar = self.query_one('#sidebar', OptionList)
        try:
            sidebar.highlighted = sidebar.get_option_index(key)
        except Exception:
            sidebar.highlighted = None

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        # Rebuilding the sidebar queues highlight events for options that are
        # no longer highlighted by the time they're handled; ignore those.
        if event.option_list.highlighted != event.option_index:
            return
        key = event.option.id
        if key and (self.current is None or key != self.current.key):
            self.select_source(key)

    def select_source(self, key: str, remember: bool = True) -> None:
        source = self.sources.get(key)
        if source is None:
            return
        if remember and self.current and self.current.key != key:
            self.history.append(self.current.key)
        self.current = source
        self.sub_title = source.label
        self._highlight_sidebar(key)
        self.load_items()

    # -- items ---------------------------------------------------------------

    def load_items(self, keep_cursor: bool = False) -> None:
        if self.current is None:
            return
        table = self.query_one('#items', DataTable)
        selected = self.selected_uuid() if keep_cursor else None
        try:
            items = self.current.fetch()
            groups = self.current.group(items)
        except Exception as e:
            self.notify(str(e), severity='error')
            items, groups = [], []
        self.items = {i['uuid']: i for i in items if i.get('uuid')}
        table.clear()
        for n, (label, members) in enumerate(groups):
            if not members:
                continue
            if label:
                table.add_row('', Text(label, style='bold'), '', '', '', '',
                              key=f"{HEADER_PREFIX}{n}")
            for item in members:
                if item.get('uuid'):
                    table.add_row(*self._cells(item), key=item['uuid'])
        if selected in self.items:
            table.move_cursor(row=table.get_row_index(selected))
        self.show_detail()

    def _cells(self, item: dict) -> list:
        finished = item.get('status') in ('completed', 'canceled')
        title_style = 'dim strike' if finished else ''
        return [
            display.mark(item),
            Text(item.get('title') or '(untitled)', style=title_style),
            Text(display.location(item), style='dim'),
            display.when(item),
            str(item.get('deadline') or ''),
            Text(display.tag_text(item), style='cyan'),
        ]

    def _redraw_row(self, uuid: str) -> None:
        table = self.query_one('#items', DataTable)
        item = self.items[uuid]
        for column, value in zip(('mark', 'title', 'where', 'when', 'deadline', 'tags'), self._cells(item)):
            table.update_cell(uuid, column, value)

    def selected_uuid(self) -> Optional[str]:
        table = self.query_one('#items', DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        return None if row_key.value.startswith(HEADER_PREFIX) else row_key.value

    def selected_item(self) -> Optional[dict]:
        uuid = self.selected_uuid()
        return self.items.get(uuid) if uuid else None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_detail()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Return opens the selected item (Things: Return)."""
        self.action_enter_item()

    def show_detail(self) -> None:
        detail = self.query_one('#detail', Static)
        item = self.selected_item()
        if item is None:
            detail.update(Text('Nothing selected', style='dim'))
            return
        try:
            detail.update(Text(display.detail(item)))
        except Exception as e:
            detail.update(Text(f"{item.get('title')}\n\n(couldn't load details: {e})"))

    # -- refreshing ----------------------------------------------------------

    def _stamp(self):
        if not self.db_path:
            return None
        stamps = []
        for path in (self.db_path, self.db_path + '-wal'):
            try:
                stamps.append(os.stat(path).st_mtime_ns)
            except OSError:
                stamps.append(None)
        return tuple(stamps)

    def check_database(self) -> None:
        """Refresh when Things has written to its database since last check."""
        stamp = self._stamp()
        if stamp != self._db_stamp:
            self._db_stamp = stamp
            self.refresh_data()

    def refresh_data(self) -> None:
        if isinstance(self.screen, PromptScreen):
            return  # don't redraw under an open prompt; the next poll will catch up
        self.load_sidebar()
        self.load_items(keep_cursor=True)

    def action_refresh(self) -> None:
        self.refresh_data()

    # -- navigation ----------------------------------------------------------

    def action_go(self, n: int) -> None:
        self.select_source(BUILTIN_ORDER[n - 1])

    def action_go_back(self) -> None:
        while self.history:
            key = self.history.pop()
            if key in self.sources:
                self.select_source(key, remember=False)
                return

    def action_enter_item(self) -> None:
        """Enter a project/area row, or open a to-do for editing (rename)."""
        item = self.selected_item()
        if item is None:
            return
        kind = item.get('type')
        key = {'project': f"project:{item['uuid']}", 'area': f"area:{item['uuid']}"}.get(kind)
        if key and key in self.sources and key != self.current.key:
            self.select_source(key)
        elif kind in ('to-do', 'project'):
            self.action_rename()

    def action_show_in_parent(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        project = item.get('project')
        if not project and item.get('heading'):
            heading = core.get(item['heading']) or {}
            project = heading.get('project')
        key = (f"project:{project}" if project else
               f"area:{item['area']}" if item.get('area') else
               {'Inbox': 'inbox', 'Anytime': 'anytime', 'Someday': 'someday'}.get(item.get('start')))
        if key in self.sources:
            self.select_source(key)
            uuid = item['uuid']
            if uuid in self.items:
                table = self.query_one('#items', DataTable)
                table.move_cursor(row=table.get_row_index(uuid))
        else:
            self.notify("No parent list to show", severity='warning')

    def action_jump(self) -> None:
        """Type a list, project or area name to go there (Things: Type Travel / ⇧⌘O)."""
        def go(text: str) -> None:
            needle = text.lower()
            candidates = [s for s in self.sources.values() if not s.key.startswith('search:')]
            match = (next((s for s in candidates if s.label.lower().startswith(needle)), None)
                     or next((s for s in candidates if needle in s.label.lower()), None))
            if match:
                self.select_source(match.key)
                self.query_one('#items', DataTable).focus()
            else:
                self.notify(f"No list matches '{text}'", severity='warning')
        self._ask('Go to list, project or area', go)

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one('#sidebar', OptionList)
        sidebar.display = not sidebar.display
        if not sidebar.display:
            self.query_one('#items', DataTable).focus()

    def action_find(self) -> None:
        def run_search(query: str) -> None:
            source = Source(f"search:{query}", f"Search: {query}", lambda: core.search(query),
                            group=group_by_location, read_only=True)
            self.sources[source.key] = source
            if self.current:
                self.history.append(self.current.key)
            self.current = source
            self.sub_title = source.label
            self.query_one('#sidebar', OptionList).highlighted = None
            self.load_items()
            self.query_one('#items', DataTable).focus()
        self._ask('Find to-dos', run_search)

    def action_help(self) -> None:
        if self.screen.query('HelpPanel'):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def action_open_in_things(self) -> None:
        item = self.selected_item()
        target = item['uuid'] if item else (self.current.key if self.current else 'today')
        if ':' in target:
            target = target.split(':', 1)[1]
        try:
            core.show_in_app(target)
        except Exception as e:
            self.notify(f"Couldn't open Things: {e}", severity='error')

    # -- writes --------------------------------------------------------------

    def _write(self, fn: Callable[[], object], message: str) -> bool:
        """Run a write, report the outcome, and schedule a re-read."""
        try:
            fn()
        except ThingsError as e:
            self.notify(str(e), severity='error')
            return False
        except Exception as e:
            self.notify(f"Couldn't update Things: {e}", severity='error')
            return False
        self.notify(message, timeout=2)
        self.set_timer(REFRESH_AFTER_WRITE, self.refresh_data)
        return True

    def _editable_item(self, todos_only: bool = False) -> Optional[dict]:
        item = self.selected_item()
        if item is None:
            return None
        allowed = ('to-do',) if todos_only else ('to-do', 'project')
        if item.get('type') not in allowed:
            self.notify(f"Only {' and '.join(t + 's' for t in allowed)} can be changed this way",
                        severity='warning')
            return None
        return item

    def _ask(self, question: str, then: Callable[[str], None], value: str = '',
             placeholder: str = '', allow_empty: bool = False) -> None:
        def done(answer: Optional[str]) -> None:
            if answer is not None and (answer or allow_empty):
                then(answer)
        self.push_screen(PromptScreen(question, value, placeholder), done)

    def _change(self, item: dict, message: str, local: Optional[dict] = None, **changes) -> None:
        """Send a change for one item; on success apply ``local`` to the row."""
        if self._write(lambda: core.update_items([item['uuid']], **changes), message) and local:
            item.update(local)
            self._redraw_row(item['uuid'])

    def action_new_todo(self) -> None:
        if self.current is None or self.current.read_only:
            self.notify("Can't add to this list", severity='warning')
            return
        defaults = dict(self.current.add_defaults)
        self._ask(f"New to-do in {self.current.label}",
                  lambda title: self._write(lambda: core.add_todo(title, **defaults), f"Added '{title}'"))

    def action_duplicate(self) -> None:
        item = self._editable_item()
        if item:
            self._write(lambda: core.duplicate(item['uuid']), f"Duplicated '{item['title']}'")

    def action_complete(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        reopen = item.get('status') == 'completed'
        self._change(item, f"{'Reopened' if reopen else 'Completed'} '{item['title']}'",
                     {'status': 'incomplete' if reopen else 'completed'}, completed=not reopen)

    def action_cancel_item(self) -> None:
        item = self._editable_item()
        if item:
            self._change(item, f"Canceled '{item['title']}'", {'status': 'canceled'}, canceled=True)

    def action_when(self) -> None:
        item = self._editable_item()
        if item:
            self._ask(f"When should '{item['title']}' happen?",
                      lambda when: self._change(item, f"Scheduled for {when}", when=when),
                      placeholder='today, tomorrow, evening, anytime, someday, 2026-11-15, 2026-11-15@09:00')

    def action_start(self, when: str) -> None:
        item = self._editable_item()
        if item:
            label = {'today': 'Today', 'evening': 'This Evening', 'anytime': 'Anytime', 'someday': 'Someday'}[when]
            self._change(item, f"Moved '{item['title']}' to {label}", when=when)

    @staticmethod
    def _shifted(value, days: int) -> date:
        try:
            base = date.fromisoformat(str(value)[:10]) if value else date.today()
        except ValueError:
            base = date.today()
        return base + timedelta(days=days)

    def action_shift_start(self, days: int) -> None:
        item = self._editable_item()
        if item is None:
            return
        new = self._shifted(item.get('start_date'), days)
        when = 'today' if new <= date.today() else new.isoformat()
        start = date.today().isoformat() if when == 'today' else when
        self._change(item, f"Start date {start}", {'start_date': start}, when=when)

    def action_deadline(self) -> None:
        item = self._editable_item()
        if item:
            self._ask(f"Deadline for '{item['title']}'",
                      lambda d: self._change(item, f"Deadline {d}", {'deadline': d}, deadline=d),
                      value=str(item.get('deadline') or ''), placeholder='YYYY-MM-DD')

    def action_shift_deadline(self, days: int) -> None:
        item = self._editable_item()
        if item:
            new = self._shifted(item.get('deadline'), days).isoformat()
            self._change(item, f"Deadline {new}", {'deadline': new}, deadline=new)

    def action_move(self) -> None:
        item = self._editable_item(todos_only=True)
        if item:
            self._ask(f"Move '{item['title']}' to which project or area?",
                      lambda dest: self._change(item, f"Moved to {dest}", list=dest),
                      placeholder='Project or area title')

    def action_edit_tags(self) -> None:
        item = self._editable_item()
        if item is None:
            return

        def apply(text: str) -> None:
            tags = [t.strip().lstrip('#') for t in text.split(',') if t.strip()]
            self._change(item, f"Tags: {' '.join('#' + t for t in tags) or 'none'}", {'tags': tags}, tags=tags)
        self._ask(f"Tags for '{item['title']}' (comma-separated; must already exist)", apply,
                  value=', '.join(item.get('tags') or []), allow_empty=True)

    def action_rename(self) -> None:
        item = self._editable_item()
        if item:
            self._ask('Rename', lambda title: self._change(item, f"Renamed to '{title}'",
                                                           {'title': title}, title=title),
                      value=item.get('title') or '')


def run() -> None:
    """Entry point for ``things-tui`` and ``things tui``."""
    db_path = core.database_path()
    if db_path is None:
        sys.exit(
            "Couldn't find the Things 3 database. Things TUI runs on the Mac where "
            "Things is installed; set THINGSDB if the database lives somewhere unusual."
        )
    ThingsApp(db_path=db_path).run()


if __name__ == '__main__':
    run()
