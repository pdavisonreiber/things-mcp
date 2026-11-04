"""Tests for the ``things`` command-line interface."""
import json

import pytest
from click.testing import CliRunner

from things_mcp import cli
from things_mcp.core import ThingsError

TODOS = [
    {'uuid': 'AAAA1111', 'title': 'Buy milk', 'type': 'to-do', 'status': 'incomplete',
     'project_title': 'Errands', 'deadline': '2026-11-02', 'tags': ['shop']},
    {'uuid': 'BBBB2222', 'title': 'Write report', 'type': 'to-do', 'status': 'incomplete',
     'area_title': 'Work', 'start_date': '2026-10-31'},
    {'uuid': 'CCCC3333', 'title': 'Old thing', 'type': 'to-do', 'status': 'completed',
     'stop_date': '2026-10-30 09:00:00'},
]
BY_UUID = {t['uuid']: t for t in TODOS}
BY_UUID['PROJ0001'] = {'uuid': 'PROJ0001', 'title': 'Launch', 'type': 'project'}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path, mocker):
    """Keep the listing-number cache in a temp dir and stub item lookups."""
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    mocker.patch('things_mcp.core.get', side_effect=BY_UUID.get)
    mocker.patch('things.tasks', return_value=list(BY_UUID.values()))
    mocker.patch('things.areas', return_value=[])


@pytest.fixture
def run():
    runner = CliRunner()
    return lambda *args: runner.invoke(cli.main, list(args), catch_exceptions=False)


def test_today_lists_numbered_rows_with_summary(mocker, run):
    mocker.patch('things_mcp.core.today', return_value=TODOS[:2])
    result = run('today')
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].startswith('1  ☐  Buy milk')
    assert 'Errands' in lines[0] and '⚑' in lines[0] and '#shop' in lines[0]
    assert lines[1].startswith('2  ☐  Write report')
    assert all(line == line.rstrip() for line in lines)  # no trailing padding when piped


def test_no_command_shows_today_when_not_a_terminal(mocker, run):
    mocker.patch('things_mcp.core.today', return_value=TODOS[:1])
    assert 'Buy milk' in run().output


def test_no_command_opens_tui_in_a_terminal(mocker, run):
    mocker.patch('things_mcp.cli._interactive', return_value=True)
    tui = mocker.patch('things_mcp.tui.run')
    run()
    tui.assert_called_once()


def test_tomorrow_lists_only_tomorrows_todos(mocker, run):
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    later = (date.today() + timedelta(days=5)).isoformat()
    mocker.patch('things.upcoming', return_value=[
        {'uuid': 'T1', 'title': 'Dentist', 'type': 'to-do', 'status': 'incomplete', 'start_date': tomorrow},
        {'uuid': 'T2', 'title': 'Later thing', 'type': 'to-do', 'status': 'incomplete', 'start_date': later},
    ])
    mocker.patch('things_mcp.core.filter_someday_project_tasks', side_effect=lambda items: items)
    output = run('tomorrow').output
    assert 'Dentist' in output and 'Later thing' not in output


def test_empty_list_message(mocker, run):
    mocker.patch('things_mcp.core.inbox', return_value=[])
    assert run('inbox').output.strip() == 'Inbox is empty'


def test_limit_and_offset_number_from_offset(mocker, run):
    mocker.patch('things_mcp.core.today', return_value=TODOS)
    result = run('today', '--limit', '1', '--offset', '1')
    assert result.output.splitlines()[0].startswith('2  ☐  Write report')
    assert 'Showing 2-2 of 3' in result.output


def test_json_output_matches_mcp_envelope(mocker, run):
    mocker.patch('things_mcp.core.today', return_value=TODOS)
    data = json.loads(run('today', '--json', '-n', '2').output)
    assert data['count'] == 2 and data['total'] == 3 and data['limit'] == 2 and data['offset'] == 0
    assert [i['uuid'] for i in data['items']] == ['AAAA1111', 'BBBB2222']


def test_done_resolves_numbers_from_last_listing(mocker, run):
    mocker.patch('things_mcp.core.today', return_value=TODOS[:2])
    update = mocker.patch('things_mcp.core.update_items', return_value=2)
    run('today')
    result = run('done', '1', '2')
    assert result.exit_code == 0
    update.assert_called_once_with(['AAAA1111', 'BBBB2222'], completed=True)
    assert 'Completed 2 items' in result.output


def test_unknown_number_is_a_friendly_error(run):
    result = CliRunner().invoke(cli.main, ['done', '7'])
    assert result.exit_code == 1
    assert 'No item #7 in the last listing' in result.output


def test_uuid_prefix_resolution(mocker, run):
    update = mocker.patch('things_mcp.core.update_items', return_value=1)
    run('schedule', 'tomorrow', 'BBBB')
    update.assert_called_once_with(['BBBB2222'], when='tomorrow')


def test_ambiguous_prefix(mocker):
    mocker.patch('things.tasks', return_value=[
        {'uuid': 'ABCD1', 'title': 'One'}, {'uuid': 'ABCD2', 'title': 'Two'}])
    result = CliRunner().invoke(cli.main, ['done', 'ABCD'])
    assert result.exit_code == 1
    assert 'matches several items' in result.output


def test_add_passes_options_and_joins_title(mocker, run):
    add = mocker.patch('things_mcp.core.add_todo')
    result = run('add', 'Buy', 'oat', 'milk', '-w', 'today', '-t', 'shop', '-t', 'home',
                 '-c', 'one', '--in', 'PROJ0001')
    assert result.exit_code == 0
    add.assert_called_once_with(
        'Buy oat milk', notes=None, when='today', deadline=None, tags=['shop', 'home'],
        checklist_items=['one'], list_id='PROJ0001', list_title=None, heading=None, heading_id=None,
    )
    assert "Added 'Buy oat milk'" in result.output


def test_update_todo_builds_changes(mocker, run):
    update = mocker.patch('things_mcp.core.update_todo')
    run('update', 'AAAA1111', '--title', 'Buy oat milk', '--tags', '', '--clear-checklist')
    update.assert_called_once_with('AAAA1111', title='Buy oat milk', tags=[], checklist_items=[])


def test_update_project_rejects_todo_only_options(mocker):
    mocker.patch('things_mcp.core.update_project')
    result = CliRunner().invoke(cli.main, ['update', 'PROJ0001', '--heading', 'X'])
    assert result.exit_code == 1
    assert "Projects don't support: heading" in result.output


def test_update_with_nothing_to_change(mocker):
    result = CliRunner().invoke(cli.main, ['update', 'AAAA1111'])
    assert result.exit_code == 1
    assert 'Nothing to change' in result.output


def test_move_requires_destination():
    result = CliRunner().invoke(cli.main, ['move', 'AAAA1111'])
    assert result.exit_code == 1
    assert 'Say where to' in result.output


def test_core_errors_become_click_errors(mocker):
    mocker.patch('things_mcp.core.logbook', side_effect=ThingsError("Invalid period 'x'."))
    result = CliRunner().invoke(cli.main, ['logbook', '--period', 'x'])
    assert result.exit_code == 1
    assert "Error: Invalid period 'x'." in result.output


def test_missing_osascript_explains_macos_requirement(mocker):
    err = FileNotFoundError(2, 'No such file', 'osascript')
    mocker.patch('things_mcp.core.add_area', side_effect=err)
    result = CliRunner().invoke(cli.main, ['add-area', 'Home'])
    assert result.exit_code == 1
    assert 'needs macOS' in result.output


def test_show_prints_detail(mocker, run):
    mocker.patch('things.get', return_value=None)  # formatter lookups
    result = run('show', 'AAAA1111')
    assert 'Title: Buy milk' in result.output and 'UUID: AAAA1111' in result.output


def test_open_passes_builtin_lists_through(mocker, run):
    show = mocker.patch('things_mcp.core.show_in_app')
    run('open', 'upcoming')
    show.assert_called_once_with('upcoming')


def test_tag_usage(mocker, run):
    mocker.patch('things_mcp.core.tag_usage', return_value=[('shop', 2, 5)])
    assert run('tags', '--usage').output.strip() == '#shop: 2 open, 5 total'


def test_tagged_with_unknown_tag_is_empty_not_an_error(mocker):
    mocker.patch('things.tags', return_value=[{'title': 'shop'}])
    todos = mocker.patch('things.todos')
    result = CliRunner().invoke(cli.main, ['tagged', 'nosuchtag'])
    assert result.exit_code == 0 and 'Nothing tagged #nosuchtag' in result.output
    todos.assert_not_called()   # things.py raises ValueError for unknown tags


def test_update_area_refuses_non_areas(mocker):
    update = mocker.patch('things_mcp.core.update_area')
    result = CliRunner().invoke(cli.main, ['update-area', 'AAAA1111', '--title', 'X'])
    assert result.exit_code == 1 and "isn't an area" in result.output
    update.assert_not_called()


def test_recent_leaves_out_headings(mocker, run):
    mocker.patch('things_mcp.core.recent', return_value=[
        {'uuid': 'H1', 'title': 'A heading', 'type': 'heading'},
        {'uuid': 'T1', 'title': 'A to-do', 'type': 'to-do', 'status': 'incomplete'}])
    out = run('recent').output
    assert 'A to-do' in out and 'A heading' not in out
