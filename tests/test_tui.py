"""Tests for the Textual TUI, driven headlessly with Textual's Pilot."""
from datetime import date, timedelta

import pytest

pytest.importorskip('textual')

from textual.widgets import DataTable, Input, OptionList  # noqa: E402

from things_mcp.tui import PromptScreen, ThingsApp  # noqa: E402
from things_mcp.tui_style import ICONS  # noqa: E402

TODAY = [
    {'uuid': 't1', 'title': 'Buy milk', 'type': 'to-do', 'status': 'incomplete', 'tags': ['shop'],
     'start_date': date.today().isoformat()},
    {'uuid': 't2', 'title': 'Write report', 'type': 'to-do', 'status': 'incomplete', 'project': 'p1'},
    {'uuid': 't3', 'title': 'Call mum', 'type': 'to-do', 'status': 'incomplete'},
]
INBOX = [{'uuid': 'i1', 'title': 'Inbox thing', 'type': 'to-do', 'status': 'incomplete', 'start': 'Inbox'}]


@pytest.fixture
def core(mocker):
    """Stub every core read the TUI makes, and the writes it can trigger."""
    m = mocker.patch('things_mcp.tui.core')
    m.today.return_value = [dict(t) for t in TODAY]
    m.inbox.return_value = list(INBOX)
    m.upcoming.return_value = []
    m.evening_uuids.return_value = {'t3'}
    m.projects.return_value = [
        {'uuid': 'p0', 'title': 'Loose project', 'type': 'project'},
        {'uuid': 'p1', 'title': 'Launch', 'type': 'project', 'area': 'a1'},
    ]
    m.areas.return_value = [{'uuid': 'a1', 'title': 'Work', 'type': 'area'}]
    m.todos.return_value = [{'uuid': 't2', 'title': 'Write report', 'type': 'to-do', 'heading_title': 'Prep'}]
    m.area_items.return_value = [{'uuid': 'p1', 'title': 'Launch', 'type': 'project'}]
    m.search.return_value = [INBOX[0]]
    mocker.patch('things_mcp.tui.display.detail', side_effect=lambda item: f"DETAIL {item['title']}")
    return m


def _titles(app):
    table = app.query_one('#items', DataTable)
    return [t for t in (str(table.get_row_at(i)[2]) for i in range(table.row_count)) if t]


def _mark(app, uuid):
    return str(app.query_one('#items', DataTable).get_cell(uuid, 'mark'))


DONE, OPEN, CANCELED = ICONS['done'], ICONS['todo'], ICONS['canceled']


async def _start(app, pilot):
    await pilot.pause()
    app.query_one('#items', DataTable).focus()


async def _answer(app, pilot, text):
    assert isinstance(app.screen, PromptScreen)
    app.screen.query_one(Input).value = text
    await pilot.press('enter')


async def test_today_groups_this_evening(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.current.key == 'today'
        assert _titles(app) == ['Buy milk', 'Write report', 'This Evening', 'Call mum']


async def test_sidebar_follows_things_order_and_nests_projects(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        sidebar = app.query_one('#sidebar', OptionList)
        ids = [sidebar.get_option_at_index(i).id for i in range(sidebar.option_count)]
        assert ids[:7] == ['inbox', 'today', 'upcoming', 'anytime', 'someday', 'logbook', 'trash']
        # loose projects before areas; a project follows its area
        assert ids.index('project:p0') < ids.index('area:a1') < ids.index('project:p1')
        assert ids.index('project:p1') == ids.index('area:a1') + 1


async def test_k_completes_and_toggles_back(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('k')
        core.update_items.assert_called_once_with(['t1'], completed=True)
        assert _mark(app, 't1') == DONE
        await pilot.press('k')
        core.update_items.assert_called_with(['t1'], completed=False)
        assert _mark(app, 't1') == OPEN


async def test_shift_k_cancels(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('K')
        core.update_items.assert_called_once_with(['t1'], canceled=True)
        assert _mark(app, 't1') == CANCELED


@pytest.mark.parametrize('key,when', [('t', 'today'), ('e', 'evening'), ('r', 'anytime'), ('o', 'someday')])
async def test_start_shortcuts(core, key, when):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press(key)
        core.update_items.assert_called_once_with(['t1'], when=when)


async def test_bracket_keys_shift_start_date(core):
    app = ThingsApp()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('right_square_bracket')
        core.update_items.assert_called_once_with(['t1'], when=tomorrow)
        await pilot.press('left_square_bracket')  # back to today -> 'today'
        core.update_items.assert_called_with(['t1'], when='today')


async def test_period_and_comma_shift_deadline(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('greater_than_sign')
        week = (date.today() + timedelta(days=7)).isoformat()
        core.update_items.assert_called_once_with(['t1'], deadline=week)


async def test_n_adds_with_current_list_defaults(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('n')
        await _answer(app, pilot, 'Call Sam')
        core.add_todo.assert_called_once_with('Call Sam', when='today')


async def test_escape_cancels_prompt_without_writing(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('s')
        await pilot.press('escape')
        assert not isinstance(app.screen, PromptScreen)
        core.update_items.assert_not_called()


async def test_shift_t_edits_tags_prefilled_and_can_clear(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('T')
        assert app.screen.query_one(Input).value == 'shop'
        await _answer(app, pilot, '')
        core.update_items.assert_called_once_with(['t1'], tags=[])


async def test_shift_m_moves(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('M')
        await _answer(app, pilot, 'Errands')
        core.update_items.assert_called_once_with(['t1'], list='Errands')


async def test_d_duplicates(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('d')
        core.duplicate.assert_called_once_with('t1')


async def test_number_keys_go_to_lists_and_left_goes_back(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('1')
        assert app.current.key == 'inbox' and _titles(app) == ['Inbox thing']
        await pilot.press('3')
        assert app.current.key == 'upcoming'
        app.query_one('#items', DataTable).focus()
        await pilot.press('left')
        assert app.current.key == 'inbox'


async def test_project_groups_by_heading_and_adds_into_project(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        app.select_source('project:p1')
        core.todos.assert_called_with('p1')
        assert _titles(app) == ['Prep', 'Write report']
        await pilot.pause()
        assert app.selected_uuid() == 't2'  # cursor skips the heading row
        await pilot.press('n')
        await _answer(app, pilot, 'Draft plan')
        core.add_todo.assert_called_once_with('Draft plan', list_id='p1')


async def test_enter_on_project_row_enters_project(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        app.select_source('area:a1')
        app.query_one('#items', DataTable).focus()
        await pilot.press('enter')
        assert app.current.key == 'project:p1'


async def test_enter_on_todo_renames(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('enter')
        assert app.screen.query_one(Input).value == 'Buy milk'
        await _answer(app, pilot, 'Buy oat milk')
        core.update_items.assert_called_once_with(['t1'], title='Buy oat milk')


async def test_shift_l_shows_in_parent(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('down')
        await pilot.press('L')
        assert app.current.key == 'project:p1'


async def test_shift_o_jumps_by_name(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('O')
        await _answer(app, pilot, 'laun')
        assert app.current.key == 'project:p1'


async def test_f_finds_and_blocks_add(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('f')
        await _answer(app, pilot, 'inbox')
        core.search.assert_called_once_with('inbox')
        assert 'Inbox thing' in _titles(app)
        await pilot.press('n')
        assert not isinstance(app.screen, PromptScreen)


async def test_slash_toggles_sidebar(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('slash')
        assert not app.query_one('#sidebar').display
        await pilot.press('slash')
        assert app.query_one('#sidebar').display


async def test_write_errors_are_reported_not_raised(core):
    from things_mcp.core import ThingsError
    core.update_items.side_effect = ThingsError('nope')
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('k')
        assert _mark(app, 't1') == OPEN  # no optimistic change on failure


async def test_detail_follows_cursor(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('down')
        await pilot.pause()
        detail = str(app.query_one('#detail').render())
        assert 'Write report' in detail and 't2' in detail


async def test_question_mark_toggles_key_help(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('question_mark')
        await pilot.pause()
        assert app.screen.query('HelpPanel')
        await pilot.press('question_mark')
        await pilot.pause()
        assert not app.screen.query('HelpPanel')


async def test_cursor_skips_spacer_and_heading_rows(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('down', 'down')  # t1 -> t2 -> (gap, This Evening) -> t3
        await pilot.pause()
        assert app.selected_uuid() == 't3'
        await pilot.press('up')
        await pilot.pause()
        assert app.selected_uuid() == 't2'


def test_logo_reads_things_3_and_fits_the_sidebar():
    from things_mcp import tui_style
    rows = tui_style.logo().plain.split('\n')
    assert len(rows) == 3
    assert {len(r) for r in rows} == {30}
    assert rows[0].startswith('▀█▀')  # T


async def test_empty_list_shows_logo_state(core):
    core.inbox.return_value = []
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('1')
        await pilot.pause()
        assert not app.query_one('#items', DataTable).display
        empty = app.query_one('#empty')
        assert empty.display and 'Inbox zero.' in str(empty.render())
        await pilot.press('2')
        await pilot.pause()
        assert app.query_one('#items', DataTable).display and not empty.display


def test_upcoming_groups_are_in_date_order():
    from things_mcp.tui import group_upcoming
    later = (date.today() + timedelta(days=9)).isoformat()
    sooner = (date.today() + timedelta(days=1)).isoformat()
    groups = group_upcoming([{'uuid': 'a', 'start_date': later}, {'uuid': 'b', 'start_date': sooner}])
    assert [g[0] for g in groups] == ['Tomorrow', groups[1][0]] and groups[1][1][0]['uuid'] == 'a'


async def test_detail_updates_after_completing(core):
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('k')
        await pilot.pause()
        assert DONE in str(app.query_one('#detail').render())


async def test_anytime_hides_heading_rows(core):
    core.anytime.return_value = [
        {'uuid': 'h1', 'title': 'Prep', 'type': 'heading', 'project_title': 'Launch'},
        {'uuid': 'a1', 'title': 'Draft', 'type': 'to-do', 'project_title': 'Launch'}]
    app = ThingsApp()
    async with app.run_test() as pilot:
        await _start(app, pilot)
        await pilot.press('4')
        await pilot.pause()
        assert 'h1' not in app.items and 'a1' in app.items
