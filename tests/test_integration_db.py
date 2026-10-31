"""Integration tests: the CLI, MCP tools and TUI against a synthetic Things
database, so real things.py queries run (nothing below things.py is mocked).

Writes still can't reach Things here, so execute_url is patched to capture
the URLs that would be sent.
"""
import json
import re

import pytest
from click.testing import CliRunner

from tests._helpers import tool_text
from tests.fixtures import things_db
from things_mcp import cli, server


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / 'main.sqlite'
    things_db.build(str(path))
    monkeypatch.setenv('THINGSDB', str(path))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    return str(path)


@pytest.fixture
def sent(mocker):
    return mocker.patch('things_mcp.url_scheme.execute_url')


def things(*args):
    result = CliRunner().invoke(cli.main, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def titles(output):
    """Titles of the numbered rows in a listing (skips group headings)."""
    rows = []
    for line in output.splitlines():
        m = re.match(r'^\s*\d+\s+\S\s+(.+?)(?:\s{2,}|$)', line)
        if m:
            rows.append(m.group(1).removesuffix(' ✎'))
    return rows


def test_today_excludes_someday_project_tasks():
    assert titles(things('today')) == ['Write brief', 'Book venue', 'Buy milk', 'Call mum']


def test_upcoming_and_someday():
    assert titles(things('upcoming')) == ['Renew passport']
    someday = titles(things('someday'))
    assert 'Someday thing' in someday and 'Learn Japanese' in someday


def test_logbook_window_uses_completion_date():
    assert titles(things('logbook', '--period', '7d')) == ['Filed taxes']
    assert 'Ancient chore' in titles(things('logbook', '--period', '2m'))


def test_row_summary_uses_things_py_titles():
    out = things('today')
    assert 'Launch' in out and '⚑' in out and '≡ 1/2' in out and '#errand' in out


def test_tag_usage_and_recent():
    assert things('tags', '--usage').splitlines() == ['#errand: 1 open, 1 total', '#unused: 0 open, 0 total']
    assert titles(things('recent', '1d')) == ['Inbox idea']


def test_json_items_are_raw_things_rows():
    data = json.loads(things('today', '--json'))
    assert data['total'] == 4
    assert data['items'][0]['project_title'] == 'Launch'
    assert [c['title'] for c in data['items'][0]['checklist']] == ['Outline', 'Draft']


def test_show_by_number_and_prefix():
    things('today')
    assert 'Title: Write brief' in things('show', '1')
    assert 'Title: Buy milk' in things('show', 'TODO-MI')


def test_done_by_number_sends_update_with_db_token(sent):
    things('today')
    things('done', '3')
    url = sent.call_args.args[0]
    assert url.startswith('things:///update?') and 'id=TODO-MILK' in url
    assert 'auth-token=test-token' in url


def test_bulk_schedule_sends_one_json_call(sent):
    things('today')
    things('schedule', 'tomorrow', '1', '2')
    assert sent.call_count == 1
    assert sent.call_args.args[0].startswith('things:///json?')


async def test_mcp_tools_read_same_database():
    text = tool_text(await server.get_today())
    assert 'Write brief' in text and 'Learn Japanese' not in text
    result = await server.get_projects(limit=1)
    assert result.structured_content['total'] == 2


async def test_tui_loads_sidebar_and_today(database):
    pytest.importorskip('textual')
    from textual.widgets import DataTable, OptionList
    from things_mcp.tui import ThingsApp

    app = ThingsApp(db_path=database)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one('#items', DataTable)
        # Today, then a "This Evening" group read from startBucket
        rows = [app.items[k]['title'] if (k := table.coordinate_to_cell_key((i, 0))[0].value) in app.items
                else str(table.get_row_at(i)[1]) for i in range(table.row_count)]
        assert rows == ['Write brief', 'Book venue', 'Buy milk', '', 'This Evening', 'Call mum']
        sidebar = app.query_one('#sidebar', OptionList)
        ids = {sidebar.get_option_at_index(i).id for i in range(sidebar.option_count)}
        assert {'project:PROJ-LAUNCH', 'area:AREA-HOME'} <= ids
        # Launch (in Work) is listed right after its area, indented
        order = [sidebar.get_option_at_index(i).id for i in range(sidebar.option_count)]
        assert order.index('project:PROJ-LAUNCH') == order.index('area:AREA-WORK') + 1
        app.select_source('area:AREA-HOME')
        assert list(app.items) == ['TODO-MILK']
