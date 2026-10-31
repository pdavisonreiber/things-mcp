"""Compact, one-line presentation helpers shared by the CLI and TUI.

The MCP formatters in ``formatters.py`` produce verbose, labelled blocks meant
for language models. These helpers produce short human-facing summaries and
rely only on fields things.py already returns on each row (``project_title``,
``area_title``, ``heading_title``), so rendering a long list costs no extra
database queries.
"""

from __future__ import annotations

from .formatters import format_area, format_heading, format_project, format_tag, format_todo

_TODO_MARKS = {'completed': '✓', 'canceled': '✗'}
_PROJECT_MARKS = {'completed': '◉', 'canceled': '⊘'}


def mark(item: dict) -> str:
    """A one-character status/type marker."""
    kind = item.get('type')
    status = item.get('status')
    if kind == 'to-do':
        return _TODO_MARKS.get(status, '☐')
    if kind == 'project':
        return _PROJECT_MARKS.get(status, '○')
    if kind == 'heading':
        return '§'
    if kind == 'area':
        return '▣'
    if kind == 'tag':
        return '#'
    return '·'


def location(item: dict) -> str:
    """Where an item lives, e.g. 'Work › Launch › Prep'."""
    parts = [item.get('area_title'), item.get('project_title'), item.get('heading_title')]
    return ' › '.join(p for p in parts if p)


def when(item: dict) -> str:
    """The schedule shown next to an item: a start date, or This Evening/Someday."""
    if item.get('stop_date'):
        return str(item['stop_date'])[:10]
    if item.get('start_date'):
        text = str(item['start_date'])
        if item.get('reminder_time'):
            text += f" {item['reminder_time']}"
        return text
    if item.get('start') == 'Someday':
        return 'Someday'
    return ''


def tag_text(item: dict) -> str:
    return ' '.join(f"#{t}" for t in item.get('tags') or [])


def checklist_progress(item: dict) -> str:
    checklist = item.get('checklist')
    if not isinstance(checklist, list) or not checklist:
        return ''
    done = sum(1 for c in checklist if c.get('status') == 'completed')
    return f"{done}/{len(checklist)}"


def summary(item: dict) -> str:
    """Secondary text for a row: location, schedule, deadline, checklist, tags."""
    bits = [
        location(item),
        when(item),
        f"due {item['deadline']}" if item.get('deadline') else '',
        f"☑ {checklist_progress(item)}" if checklist_progress(item) else '',
        tag_text(item),
    ]
    return ' · '.join(b for b in bits if b)


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
