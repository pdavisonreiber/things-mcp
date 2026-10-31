"""``things tui`` — a full-screen terminal interface to Things 3 (Textual).

Layout: a sidebar of lists, projects and areas; a table of the selected
list's items; and a detail pane for the highlighted item.

Reads come from the Things database via ``core``. Writes go through the
Things URL scheme, which is fire-and-forget, so the app updates the row it
changed straight away ("optimistic" update), then re-reads the database a
moment later. It also watches the database file and refreshes whenever
Things saves, so edits made in the Things app show up here too.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
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


@dataclass
class Source:
    """Something the sidebar can show: a built-in list, project, area or search."""
    key: str
    label: str
    fetch: Callable[[], list]
    add_defaults: dict = field(default_factory=dict)  # applied to 'a' (add to-do)
    read_only: bool = False


def builtin_sources() -> list[Source]:
    return [
        Source('inbox', 'Inbox', core.inbox),
        Source('today', 'Today', core.today, {'when': 'today'}),
        Source('upcoming', 'Upcoming', core.upcoming),
        Source('anytime', 'Anytime', core.anytime, {'when': 'anytime'}),
        Source('someday', 'Someday', core.someday, {'when': 'someday'}),
        Source('logbook', 'Logbook', lambda: core.logbook('1m'), read_only=True),
        Source('trash', 'Trash', core.trash, read_only=True),
    ]


class PromptScreen(ModalScreen[Optional[str]]):
    """A one-line text prompt. Enter submits; Escape cancels."""

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
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ThingsApp(App):
    TITLE = 'Things'
    CSS = """
    #sidebar { width: 30; border-right: solid $panel; }
    #main { width: 1fr; }
    #items { height: 2fr; }
    #detail-pane { height: 1fr; border-top: solid $panel; padding: 0 1; }
    PromptScreen { align: center middle; }
    #prompt { width: 70; height: auto; padding: 1 2; border: thick $accent; background: $surface; }
    """

    BINDINGS = [
        Binding('x', 'toggle_complete', 'Done'),
        Binding('space', 'toggle_complete', 'Done', show=False),
        Binding('c', 'cancel_item', 'Cancel'),
        Binding('a', 'add', 'Add'),
        Binding('s', 'schedule', 'When'),
        Binding('d', 'deadline', 'Deadline'),
        Binding('m', 'move', 'Move'),
        Binding('t', 'tag', 'Tag'),
        Binding('e', 'rename', 'Rename'),
        Binding('o', 'open_in_things', 'Open'),
        Binding('slash', 'search', 'Search'),
        Binding('r', 'refresh', 'Refresh'),
        Binding('q', 'quit', 'Quit'),
    ]

    def __init__(self, db_path: Optional[str] = None):
        super().__init__()
        self.db_path = db_path
        self.sources: dict[str, Source] = {}
        self.current: Optional[Source] = None
        self.items: dict[str, dict] = {}
        self._db_stamp = self._stamp()

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield OptionList(id='sidebar')
            with Vertical(id='main'):
                yield DataTable(id='items', cursor_type='row', zebra_stripes=True)
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
        sources = builtin_sources()
        options: list = [Option(s.label, id=s.key) for s in sources]
        try:
            projects, areas = core.projects(), core.areas()
        except Exception as e:  # database unavailable: still show the shell
            self.notify(f"Couldn't read Things: {e}", severity='error')
            projects, areas = [], []
        if projects:
            options += [None, Option(Text('PROJECTS', style='bold dim'), disabled=True)]
            for p in projects:
                s = Source(f"project:{p['uuid']}", p['title'],
                           lambda uuid=p['uuid']: core.todos(uuid), {'list_id': p['uuid']})
                sources.append(s)
                options.append(Option(f"○ {p['title']}", id=s.key))
        if areas:
            options += [None, Option(Text('AREAS', style='bold dim'), disabled=True)]
            for a in areas:
                s = Source(f"area:{a['uuid']}", a['title'],
                           lambda uuid=a['uuid']: core.area_items(uuid), {'list_id': a['uuid']})
                sources.append(s)
                options.append(Option(f"▣ {a['title']}", id=s.key))
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
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        # Rebuilding the sidebar queues highlight events for options that are
        # no longer highlighted by the time they're handled; ignore those.
        if event.option_list.highlighted != event.option_index:
            return
        key = event.option.id
        if key and (self.current is None or key != self.current.key):
            self.select_source(key)

    def select_source(self, key: str) -> None:
        source = self.sources.get(key)
        if source is None:
            return
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
        except Exception as e:
            self.notify(str(e), severity='error')
            items = []
        self.items = {i['uuid']: i for i in items if i.get('uuid')}
        table.clear()
        for item in self.items.values():
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
        return row_key.value

    def selected_item(self) -> Optional[dict]:
        uuid = self.selected_uuid()
        return self.items.get(uuid) if uuid else None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_detail()

    def show_detail(self) -> None:
        detail = self.query_one('#detail', Static)
        item = self.selected_item()
        if item is None:
            detail.update(Text('Nothing here', style='dim'))
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

    def _editable_item(self) -> Optional[dict]:
        item = self.selected_item()
        if item is None:
            return None
        if item.get('type') not in ('to-do', 'project'):
            self.notify("Only to-dos and projects can be changed here", severity='warning')
            return None
        return item

    def action_toggle_complete(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        reopen = item.get('status') == 'completed'
        if self._write(lambda: core.update_items([item['uuid']], completed=not reopen),
                       f"{'Reopened' if reopen else 'Completed'} '{item['title']}'"):
            item['status'] = 'incomplete' if reopen else 'completed'
            self._redraw_row(item['uuid'])

    def action_cancel_item(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        if self._write(lambda: core.update_items([item['uuid']], canceled=True),
                       f"Canceled '{item['title']}'"):
            item['status'] = 'canceled'
            self._redraw_row(item['uuid'])

    def _ask(self, question: str, then: Callable[[str], None], value: str = '', placeholder: str = '') -> None:
        def done(answer: Optional[str]) -> None:
            if answer:
                then(answer)
        self.push_screen(PromptScreen(question, value, placeholder), done)

    def action_add(self) -> None:
        if self.current is None or self.current.read_only:
            self.notify("Can't add to this list", severity='warning')
            return
        defaults = dict(self.current.add_defaults)
        self._ask(f"New to-do in {self.current.label}",
                  lambda title: self._write(lambda: core.add_todo(title, **defaults), f"Added '{title}'"))

    def action_schedule(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        self._ask(f"When should '{item['title']}' happen?",
                  lambda when: self._write(lambda: core.update_items([item['uuid']], when=when),
                                           f"Scheduled '{item['title']}' for {when}"),
                  placeholder='today, tomorrow, evening, anytime, someday, 2026-11-15, 2026-11-15@09:00')

    def action_deadline(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        self._ask(f"Deadline for '{item['title']}'",
                  lambda date: self._write(lambda: core.update_items([item['uuid']], deadline=date),
                                           f"Deadline {date} set"),
                  value=str(item.get('deadline') or ''), placeholder='YYYY-MM-DD')

    def action_move(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        if item.get('type') != 'to-do':
            self.notify("Only to-dos can be moved", severity='warning')
            return
        self._ask(f"Move '{item['title']}' to which project or area?",
                  lambda dest: self._write(lambda: core.update_items([item['uuid']], list=dest),
                                           f"Moved to {dest}"),
                  placeholder='Project or area title')

    def action_tag(self) -> None:
        item = self._editable_item()
        if item is None:
            return
        if item.get('type') != 'to-do':
            self.notify("Tags can only be added to to-dos here", severity='warning')
            return

        def apply(text: str) -> None:
            tags = [t.strip().lstrip('#') for t in text.split(',') if t.strip()]
            self._write(lambda: core.update_items([item['uuid']], add_tags=tags),
                        f"Tagged {' '.join('#' + t for t in tags)}")
        self._ask(f"Add tags to '{item['title']}' (comma-separated; must already exist)", apply)

    def action_rename(self) -> None:
        item = self._editable_item()
        if item is None:
            return

        def apply(title: str) -> None:
            if self._write(lambda: core.update_items([item['uuid']], title=title), f"Renamed to '{title}'"):
                item['title'] = title
                self._redraw_row(item['uuid'])
        self._ask('Rename', apply, value=item.get('title') or '')

    def action_open_in_things(self) -> None:
        item = self.selected_item()
        target = item['uuid'] if item else (self.current.key if self.current else 'today')
        if ':' in target:
            target = target.split(':', 1)[1]
        try:
            core.show_in_app(target)
        except Exception as e:
            self.notify(f"Couldn't open Things: {e}", severity='error')

    def action_search(self) -> None:
        def run_search(query: str) -> None:
            source = Source(f"search:{query}", f"Search: {query}", lambda: core.search(query), read_only=True)
            self.sources[source.key] = source
            self.current = source
            self.sub_title = source.label
            self.query_one('#sidebar', OptionList).highlighted = None
            self.load_items()
            self.query_one('#items', DataTable).focus()
        self._ask('Search to-dos', run_search)


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
