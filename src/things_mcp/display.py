"""Presentation helpers shared by the CLI and TUI: list grouping (as in the
Things app) and the labelled detail text for any item.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional

from . import core
from .formatters import format_area, format_heading, format_project, format_tag, format_todo

# ---------------------------------------------------------------------------
# Grouping, like the Things lists
# ---------------------------------------------------------------------------

Groups = list[tuple[Optional[str], list]]


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
    """By start date, soonest first (things.py doesn't return them in date order)."""
    ordered = sorted(items, key=lambda i: str(i.get('start_date') or '9999'))
    return group_by(lambda i: _day_label(i.get('start_date')), ordered, ungrouped_first=False)


def group_by_location(items: list) -> Groups:
    return group_by(lambda i: i.get('project_title') or i.get('area_title'), items)


def group_logbook(items: list) -> Groups:
    return group_by(lambda i: _day_label(i.get('stop_date')), items, ungrouped_first=False)


def group_by_heading(items: list) -> Groups:
    return group_by(lambda i: i.get('heading_title'), items)


def without_headings(items: list) -> list:
    """Headings already appear as group titles; don't also list them as rows."""
    return [i for i in items if i.get('type') != 'heading']


# ---------------------------------------------------------------------------
# Detail text
# ---------------------------------------------------------------------------

def detail(item: dict) -> str:
    """Full labelled detail for any item type (reuses the MCP formatters)."""
    kind = item.get('type')
    if kind == 'project':
        return format_project(item, include_items=True)
    if kind == 'area':
        return format_area(item, include_items=True)
    if kind == 'heading':
        return format_heading(item, include_items=True)
    if kind == 'tag':
        return format_tag(item, include_items=True)
    return format_todo(item)
