"""Tests for the Textual TUI, driven headlessly with Textual's Pilot."""
import pytest

pytest.importorskip('textual')

from textual.widgets import DataTable, Input, OptionList  # noqa: E402

from things_mcp.tui import PromptScreen, ThingsApp  # noqa: E402

TODAY = [
    {'uuid': 't1', 'title': 'Buy milk', 'type': 'to-do', 'status': 'incomplete', 'tags': ['shop']},
    {'uuid': 't2', 'title': 'Write report', 'type': 'to-do', 'status': 'incomplete'},
]
INBOX = [{'uuid': 'i1', 'title': 'Inbox thing', 'type': 'to-do', 'status': 'incomplete'}]


@pytest.fixture
def core(mocker):
    """Stub every core read the TUI makes, and the writes it can trigger."""
    m = mocker.patch('things_mcp.tui.core')
    m.today.return_value = [dict(t) for t in TODAY]
    m.inbox.return_value = list(INBOX)
    m.projects.return_value = [{'uuid': 'p1', 'title': 'Launch', 'type': 'project'}]
    m.areas.return_value = [{'uuid': 'a1', 'title': 'Work', 'type': 'area'}]
    m.todos.return_value = []
    m.search.return_value = [INBOX[0]]
    mocker.patch('things_mcp.tui.display.detail', side_effect=lambda item: f"DETAIL {item['title']}")
    return m


def _titles(app):
    table = app.query_one('#items', DataTable)
    return [str(table.get_row_at(i)[1]) for i in range(table.row_count)]


def _mark(app, uuid):
    return app.query_one('#items', DataTable).get_cell(uuid, 'mark')


async def test_starts_on_today_with_sidebar(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.current.key == 'today'
        assert _titles(app) == ['Buy milk', 'Write report']
        sidebar = app.query_one('#sidebar', OptionList)
        ids = [sidebar.get_option_at_index(i).id for i in range(sidebar.option_count)]
        assert 'project:p1' in ids and 'area:a1' in ids


async def test_complete_updates_row_immediately(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        app.query_one('#items', DataTable).focus()
        await pilot.press('x')
        core.update_items.assert_called_once_with(['t1'], completed=True)
        assert _mark(app, 't1') == '✓'
        await pilot.press('x')  # toggles back
        core.update_items.assert_called_with(['t1'], completed=False)
        assert _mark(app, 't1') == '☐'


async def test_add_uses_current_list_defaults(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        app.query_one('#items', DataTable).focus()
        await pilot.press('a')
        assert isinstance(app.screen, PromptScreen)
        app.screen.query_one(Input).value = 'Call Sam'
        await pilot.press('enter')
        core.add_todo.assert_called_once_with('Call Sam', when='today')


async def test_escape_cancels_prompt_without_writing(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        app.query_one('#items', DataTable).focus()
        await pilot.press('s')
        await pilot.press('escape')
        assert not isinstance(app.screen, PromptScreen)
        core.update_items.assert_not_called()


async def test_sidebar_navigation_switches_list(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        sidebar = app.query_one('#sidebar', OptionList)
        sidebar.focus()
        sidebar.highlighted = 0  # Inbox
        await pilot.pause()
        assert app.current.key == 'inbox'
        assert _titles(app) == ['Inbox thing']


async def test_project_list_adds_into_project(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        app.select_source('project:p1')
        core.todos.assert_called_with('p1')
        app.query_one('#items', DataTable).focus()
        await pilot.press('a')
        app.screen.query_one(Input).value = 'Draft plan'
        await pilot.press('enter')
        core.add_todo.assert_called_once_with('Draft plan', list_id='p1')


async def test_search_shows_results_and_blocks_add(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        app.query_one('#items', DataTable).focus()
        await pilot.press('slash')
        app.screen.query_one(Input).value = 'inbox'
        await pilot.press('enter')
        core.search.assert_called_once_with('inbox')
        assert _titles(app) == ['Inbox thing']
        await pilot.press('a')
        assert not isinstance(app.screen, PromptScreen)


async def test_write_errors_are_reported_not_raised(core):
    from things_mcp.core import ThingsError
    core.update_items.side_effect = ThingsError('nope')
    app = ThingsApp()
    async with app.run_test() as pilot:
        app.query_one('#items', DataTable).focus()
        await pilot.press('x')
        assert _mark(app, 't1') == '☐'  # no optimistic change on failure


async def test_detail_follows_cursor(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        table = app.query_one('#items', DataTable)
        table.focus()
        await pilot.press('down')
        await pilot.pause()
        assert 'DETAIL Write report' in str(app.query_one('#detail').render())
