"""Tests for core helpers added for the CLI/TUI (the rest of core is covered
through the MCP tool tests)."""
import json
import urllib.parse

import pytest

from things_mcp import core
from things_mcp.core import ThingsError


def _items(**by_uuid):
    return lambda uuid: by_uuid.get(uuid)


@pytest.fixture
def sent(mocker):
    """Capture URLs passed to execute_url."""
    return mocker.patch('things_mcp.url_scheme.execute_url')


@pytest.fixture
def token(mocker):
    return mocker.patch('things.token', return_value='tok')


def test_update_items_single_todo_uses_update_url(mocker, sent, token):
    mocker.patch('things.get', side_effect=_items(t1={'uuid': 't1', 'type': 'to-do'}))
    assert core.update_items(['t1'], completed=True) == 1
    url = sent.call_args.args[0]
    assert url.startswith('things:///update?')
    assert 'id=t1' in url and 'completed=true' in url and 'auth-token=tok' in url


def test_update_items_many_todos_use_one_json_call(mocker, sent, token):
    mocker.patch('things.get', side_effect=_items(
        t1={'uuid': 't1', 'type': 'to-do'}, t2={'uuid': 't2', 'type': 'to-do'}))
    assert core.update_items(['t1', 't2'], when='tomorrow') == 2
    assert sent.call_count == 1
    url = sent.call_args.args[0]
    assert url.startswith('things:///json?')
    payload = json.loads(urllib.parse.unquote(url.split('data=')[1].split('&')[0]))
    assert [p['id'] for p in payload] == ['t1', 't2']
    assert payload[0]['attributes'] == {'when': 'tomorrow'}


def test_update_items_title_on_many_todos_sends_one_update_each(mocker, sent, token):
    mocker.patch('things.get', side_effect=_items(
        t1={'uuid': 't1', 'type': 'to-do'}, t2={'uuid': 't2', 'type': 'to-do'}))
    core.update_items(['t1', 't2'], title='Same')
    assert sent.call_count == 2
    assert all(c.args[0].startswith('things:///update?') for c in sent.call_args_list)


def test_update_items_project_uses_update_project(mocker, sent, token):
    mocker.patch('things.get', side_effect=_items(p1={'uuid': 'p1', 'type': 'project'}))
    core.update_items(['p1'], canceled=True)
    assert sent.call_args.args[0].startswith('things:///update-project?')


def test_update_items_rejects_todo_only_change_on_project(mocker, sent):
    mocker.patch('things.get', side_effect=_items(p1={'uuid': 'p1', 'type': 'project'}))
    with pytest.raises(ThingsError, match="Projects don't support: list"):
        core.update_items(['p1'], list='Work')
    sent.assert_not_called()


def test_update_items_rejects_other_types_and_missing(mocker, sent):
    mocker.patch('things.get', side_effect=_items(h1={'uuid': 'h1', 'type': 'heading', 'title': 'H'}))
    with pytest.raises(ThingsError, match='is a heading'):
        core.update_items(['h1'], completed=True)
    with pytest.raises(ThingsError, match="No item with UUID 'nope'"):
        core.update_items(['nope'], completed=True)
    sent.assert_not_called()


def test_update_items_requires_a_change():
    with pytest.raises(ThingsError, match='No changes'):
        core.update_items(['t1'], when=None)


def test_area_items_combines_projects_and_todos(mocker):
    mocker.patch('things.projects', return_value=[{'uuid': 'p', 'type': 'project'}])
    mocker.patch('things.todos', return_value=[{'uuid': 't', 'type': 'to-do'}])
    assert [i['uuid'] for i in core.area_items('a')] == ['p', 't']


def test_logbook_rejects_bad_period():
    with pytest.raises(ThingsError, match="Invalid period 'soon'"):
        core.logbook('soon')


def test_database_path_honours_thingsdb(monkeypatch, tmp_path):
    db = tmp_path / 'main.sqlite'
    db.write_text('')
    monkeypatch.setenv('THINGSDB', str(db))
    assert core.database_path() == str(db)
    monkeypatch.setenv('THINGSDB', str(tmp_path / 'missing.sqlite'))
    assert core.database_path() is None


def test_duplicate_uses_update_with_duplicate_flag(mocker, sent, token):
    mocker.patch('things.get', side_effect=_items(
        t1={'uuid': 't1', 'type': 'to-do'}, p1={'uuid': 'p1', 'type': 'project'},
        h1={'uuid': 'h1', 'type': 'heading'}))
    core.duplicate('t1')
    assert sent.call_args.args[0].startswith('things:///update?') and 'duplicate=true' in sent.call_args.args[0]
    core.duplicate('p1')
    assert sent.call_args.args[0].startswith('things:///update-project?')
    with pytest.raises(ThingsError):
        core.duplicate('h1')


def test_evening_uuids_reads_start_bucket(monkeypatch, tmp_path):
    from tests.fixtures import things_db
    db = tmp_path / 'main.sqlite'
    things_db.build(str(db))
    monkeypatch.setenv('THINGSDB', str(db))
    assert core.evening_uuids() == {'TODO-EVE'}
    monkeypatch.setenv('THINGSDB', str(tmp_path / 'missing.sqlite'))
    assert core.evening_uuids() == set()
