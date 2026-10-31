"""Look and feel for the TUI: a Things-dark palette, list icons, and the
Rich renderables for rows, headings and the detail card.

Colours approximate the Things 3 Mac app in dark mode (each built-in list has
its own icon colour; the system blue is used for selection). Icons are plain
Unicode by default so they work in any monospaced font; set
``THINGS_TUI_ICONS=nerd`` to use Nerd Font glyphs instead.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

from rich.text import Text
from textual.theme import Theme

# ---------------------------------------------------------------------------
# Palette (Things 3, dark mode — approximate)
# ---------------------------------------------------------------------------

BG = '#1c1d1f'          # list background
SIDEBAR = '#242528'     # sidebar background
PANEL = '#26272a'       # hover/subtle fills (flat layout uses BG for panes)
RULE = '#3a3b40'        # separators
FG = '#e6e6e8'          # primary text
MUTED = '#8e8e93'       # secondary text
FAINT = '#5c5d62'       # tertiary text
BLUE = '#0a84ff'        # system accent / selection
RED = '#ff453a'         # deadlines
AMBER = '#ffb340'       # retro accent

LIST_COLOURS = {
    'inbox': '#3e9bff',
    'today': '#ffd60a',
    'evening': '#9fb4ef',
    'upcoming': '#ff375f',
    'anytime': '#30c8b8',
    'someday': '#cdb77d',
    'logbook': '#34c759',
    'trash': MUTED,
    'project': '#5e9cff',
    'area': '#a1a1a6',
    'search': MUTED,
}

TAG_FG = '#d1d1d6'

THEME = Theme(
    name='things-dark',
    primary=BLUE,
    secondary=LIST_COLOURS['anytime'],
    accent=AMBER,
    warning=LIST_COLOURS['today'],
    error=RED,
    success=LIST_COLOURS['logbook'],
    foreground=FG,
    background=BG,
    surface=SIDEBAR,
    panel=PANEL,
    dark=True,
)

# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

UNICODE_ICONS = {
    'inbox': '⊟', 'today': '★', 'evening': '☾', 'upcoming': '▦', 'anytime': '≋',
    'someday': '◫', 'logbook': '✔', 'trash': '⌫', 'area': '⬢', 'project': '◔',
    'search': '⌕', 'deadline': '⚑', 'checklist': '≡', 'notes': '✎', 'reminder': '◷', 'heading': '▸',
    'todo': '☐', 'done': '☑', 'canceled': '☒', 'project_done': '●', 'project_canceled': '⊘',
}

# Nerd Font (v3) glyphs, from the Font Awesome range so they're widely present.
NERD_ICONS = {
    **UNICODE_ICONS,
    'inbox': '', 'today': '', 'evening': '', 'upcoming': '',
    'anytime': '', 'someday': '', 'logbook': '', 'trash': '',
    'area': '', 'project': '', 'search': '', 'deadline': '',
    'checklist': '', 'notes': '', 'heading': '',
    'todo': '', 'done': '', 'canceled': '',
}

ICONS = NERD_ICONS if os.environ.get('THINGS_TUI_ICONS', '').lower() == 'nerd' else UNICODE_ICONS


def icon(name: str, colour: Optional[str] = None) -> Text:
    return Text(ICONS[name], style=colour or LIST_COLOURS.get(name, MUTED))


# ---------------------------------------------------------------------------
# Sidebar logo: "THINGS 3" in a 5-pixel bitmap font, drawn with half blocks
# ---------------------------------------------------------------------------

LOGO_PIXELS = [            # '#' = on; 5 rows per letter
    ['###', '.#.', '.#.', '.#.', '.#.'],           # T
    ['#.#', '#.#', '###', '#.#', '#.#'],           # H
    ['###', '.#.', '.#.', '.#.', '###'],           # I
    ['#..#', '##.#', '#.##', '#..#', '#..#'],      # N
    ['.###', '#...', '#.##', '#..#', '.###'],      # G
    ['.##', '#..', '.#.', '..#', '##.'],           # S
    ['###', '..#', '.##', '..#', '###'],           # 3
]


def _half_blocks(bitmap: list) -> list:
    """5 pixel rows -> 3 text rows (two pixel rows per text row)."""
    rows = bitmap + ['.' * len(bitmap[0])]
    return [''.join('█' if t == '#' and b == '#' else '▀' if t == '#' else '▄' if b == '#' else ' '
                    for t, b in zip(top, bottom))
            for top, bottom in zip(rows[0::2], rows[1::2])]


LOGO_GLYPHS = [_half_blocks(b) for b in LOGO_PIXELS]


def logo() -> Text:
    """THINGS 3 in amber: 1 column between letters, 2 before the 3 (30 wide)."""
    t = Text(style=f'bold {AMBER}')
    for row in range(3):
        for n, glyph in enumerate(LOGO_GLYPHS):
            if n:
                t.append('  ' if n == len(LOGO_GLYPHS) - 1 else ' ')
            t.append(glyph[row])
        if row < 2:
            t.append('\n')
    return t


EMPTY_MESSAGES = {
    'inbox': 'Inbox zero.', 'today': 'Nothing left for today.', 'upcoming': 'Nothing scheduled.',
    'anytime': 'Nothing here.', 'someday': 'No someday plans.', 'logbook': 'Nothing logged this month.',
    'trash': 'Trash is empty.',
}


def empty_state(list_key: str) -> Text:
    return Text(EMPTY_MESSAGES.get(list_key, 'Nothing here.'), style=FAINT, justify='center')


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def checkbox(item: dict) -> Text:
    kind, status = item.get('type'), item.get('status')
    if kind == 'project':
        if status == 'completed':
            return icon('project_done', LIST_COLOURS['logbook'])
        if status == 'canceled':
            return icon('project_canceled', FAINT)
        return icon('project', LIST_COLOURS['project'])
    if kind == 'area':
        return icon('area')
    if kind == 'heading':
        return icon('heading', LIST_COLOURS['project'])
    if status == 'completed':
        return icon('done', BLUE)
    if status == 'canceled':
        return icon('canceled', FAINT)
    return icon('todo', MUTED)


def title_cell(item: dict) -> Text:
    """Completed: muted (as in Things' Logbook). Canceled: faint and struck through."""
    status = item.get('status')
    if status == 'completed':
        style = MUTED
    elif status == 'canceled':
        style = f'{FAINT} strike'
    else:
        style = 'bold ' + FG if item.get('type') == 'project' else FG
    return Text(item.get('title') or '(untitled)', style=style)


def _parse_day(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def short_day(d: date) -> str:
    today = date.today()
    delta = (d - today).days
    if delta == 1:
        return 'Tomorrow'
    if 1 < delta < 7:
        return f"{d:%a}"
    return f"{d.day} {d:%b}" + (f" {d.year}" if d.year != today.year else '')


def deadline_badge(value) -> Optional[Text]:
    d = _parse_day(value)
    if d is None:
        return None
    delta = (d - date.today()).days
    if delta < 0:
        label, style = f"{-delta} day{'s' if delta != -1 else ''} ago", f'bold {RED}'
    elif delta == 0:
        label, style = 'today', f'bold {RED}'
    elif delta <= 7:
        label, style = f"{delta} day{'s' if delta != 1 else ''} left", RED
    else:
        label, style = short_day(d), f'{RED} dim'
    return Text(f"{ICONS['deadline']} {label}", style=style)


def info_cell(item: dict, list_key: str, evening: bool = False) -> Text:
    """Right-hand details: schedule badge, deadline, checklist progress, #tags."""
    parts: list[Text] = []
    start = _parse_day(item.get('start_date'))
    if item.get('status') in ('completed', 'canceled'):
        stopped = _parse_day(item.get('stop_date'))
        if stopped and list_key != 'logbook':  # the Logbook's date headings already say it
            parts.append(Text(short_day(stopped) if stopped != date.today() else 'today', style=FAINT))
    elif evening and list_key != 'today':
        parts.append(icon('evening'))
    elif start == date.today() and list_key != 'today':
        parts.append(icon('today'))
    elif start and start > date.today() and list_key != 'upcoming':
        parts.append(Text(f"{ICONS['upcoming']} {short_day(start)}", style=MUTED))

    badge = deadline_badge(item.get('deadline'))
    if badge:
        parts.append(badge)

    checklist = item.get('checklist')
    if isinstance(checklist, list) and checklist:
        done = sum(1 for c in checklist if c.get('status') == 'completed')
        parts.append(Text(f"{ICONS['checklist']} {done}/{len(checklist)}", style=MUTED))
    if item.get('tags'):
        parts.append(Text(' '.join(f"#{tag}" for tag in item['tags']), style=TAG_FG))
    return Text('  ').join(parts)


WHERE_WIDTH = 24  # longest location shown in a row before it's shortened with …


def where_text(item: dict, omit: Optional[str] = None) -> str:
    """'Area › Project › Heading', leaving out ``omit`` (the group heading
    the row already sits under)."""
    parts = [item.get('area_title'), item.get('project_title'), item.get('heading_title')]
    return ' › '.join(p for p in parts if p and p != omit)


def where_cell(item: dict, omit: Optional[str] = None) -> Text:
    text = where_text(item, omit)
    if len(text) > WHERE_WIDTH:
        text = text[:WHERE_WIDTH - 1].rstrip() + '…'
    return Text(text, style=FAINT)


def group_heading(label: str, list_key: str) -> Text:
    """Title cell for a group heading row: bold, in the list's colour, no
    symbol, so it starts in the checkbox column (unindented). The table adds
    a blank row above each one."""
    if label == 'This Evening':
        return Text(label, style=f"bold {LIST_COLOURS['evening']}")
    return Text(label, style=f"bold {LIST_COLOURS.get(list_key, LIST_COLOURS['project'])}")


def row_title(item: dict) -> Text:
    """Checkbox, title and (if it has notes) a faint ✎, in one cell so headings
    can line up with the checkboxes."""
    t = Text.assemble(checkbox(item), '  ', title_cell(item))
    if item.get('notes') and item.get('type') in ('to-do', 'project'):
        t.append(f" {ICONS['notes']}", style=FAINT)
    return t


def list_banner(label: str, list_key: str, count: int) -> Text:
    """The big list title above the items, like Things' list header."""
    kind = list_key.split(':', 1)[0]
    name = kind if kind in ('project', 'area', 'search') else list_key
    colour = LIST_COLOURS.get(name, BLUE)
    t = Text()
    t.append(f" {ICONS.get(name, ICONS['project'])} ", style=f'bold {colour}')
    t.append(label, style=f'bold {FG}')
    t.append(f"   {count} item{'s' if count != 1 else ''}", style=FAINT)
    return t


def sidebar_entry(label: str, key: str, count: Optional[int] = None, width: int = 32) -> Text:
    kind = key.split(':', 1)[0]
    name = kind if kind in ('project', 'area') else key
    t = Text(' ')
    t.append_text(icon(name))
    t.append('  ')
    t.append(label, style=f'bold {FG}' if kind == 'area' else FG)
    if count:
        pad = max(1, width - t.cell_len - len(str(count)))
        t.append(' ' * pad)
        t.append(str(count), style=MUTED)
    return t


# ---------------------------------------------------------------------------
# Detail card
# ---------------------------------------------------------------------------

def _age(value) -> str:
    try:
        days = (datetime.now() - datetime.fromisoformat(str(value).replace(' ', 'T'))).days
    except ValueError:
        return ''
    if days < 1:
        return 'today'
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 365:
        return f"{days // 30} month{'s' if days >= 60 else ''} ago"
    return f"{days // 365} year{'s' if days >= 730 else ''} ago"


DETAIL_INDENT = '   '  # lines up with the title text, after "☐  "


def detail_card(item: dict, evening: bool = False) -> Text:
    """A Things-like card for a to-do or project: title, then notes, checklist
    and metadata, all indented under the title text."""
    t = Text()
    t.append_text(checkbox(item))
    t.append('  ')
    title = title_cell(item).copy()
    title.stylize('bold')
    t.append_text(title)
    t.append('\n')

    if item.get('notes'):
        t.append('\n')
        for line in str(item['notes']).strip().splitlines():
            t.append(f"{DETAIL_INDENT}{line}\n", style=MUTED)

    checklist = item.get('checklist')
    if isinstance(checklist, list) and checklist:
        t.append('\n')
        for c in checklist:
            done = c.get('status') == 'completed'
            t.append(DETAIL_INDENT)
            t.append(f"{ICONS['done'] if done else ICONS['todo']}  ", style=BLUE if done else MUTED)
            t.append(f"{c.get('title', '')}\n", style=MUTED if done else FG)

    meta: list[tuple[Text, str]] = []
    start = _parse_day(item.get('start_date'))
    if evening:
        meta.append((icon('evening'), 'This Evening'))
    elif start == date.today():
        meta.append((icon('today'), 'Today'))
    elif start:
        meta.append((icon('upcoming'), f"{start:%A} {start.day} {start:%B}"
                     + (f" {start.year}" if start.year != date.today().year else '')))
    elif item.get('start') == 'Someday':
        meta.append((icon('someday'), 'Someday'))
    elif item.get('start') == 'Inbox':
        meta.append((icon('inbox'), 'Inbox'))
    if item.get('reminder_time'):
        meta.append((Text(ICONS['reminder'], style=AMBER), f"Reminder at {item['reminder_time']}"))
    deadline = _parse_day(item.get('deadline'))
    badge = deadline_badge(item.get('deadline'))
    if deadline and badge:
        meta.append((Text(ICONS['deadline'], style=RED),
                     f"Deadline {deadline:%a} {deadline.day} {deadline:%b} · {badge.plain[2:]}"))
    where = where_text(item)
    if where:
        meta.append((icon('project'), where))
    if item.get('tags'):
        meta.append((Text('#', style=MUTED), '  '.join(f"#{tag}" for tag in item['tags'])))
    if item.get('stop_date'):
        verb = 'Canceled' if item.get('status') == 'canceled' else 'Completed'
        meta.append((icon('logbook'), f"{verb} {_age(item['stop_date'])}"))
    elif item.get('created'):
        meta.append((Text('+', style=FAINT), f"Created {_age(item['created'])}"))

    if meta:
        t.append('\n')
        for ic, label in meta:
            t.append(DETAIL_INDENT)
            t.append_text(ic)
            t.append(f"  {label}\n", style=MUTED)
    t.rstrip()
    return t
