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
    'search': '⌕', 'deadline': '⚑', 'checklist': '≡', 'notes': '¶', 'heading': '▸',
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
# Retro bits
# ---------------------------------------------------------------------------

def _wm_gradient() -> Text:
    return Text.assemble(('▓▒░ ', AMBER), ('T H I N G S', f'bold {AMBER}'), (' ░▒▓', AMBER))


def _wm_prompt() -> Text:
    return Text.assemble(('~/', MUTED), ('things', f'bold {AMBER}'), (' ❯ ', LIST_COLOURS['logbook']),
                         ('█', AMBER))


def _wm_dos() -> Text:
    return Text.assemble(('C:\\', MUTED), ('THINGS', f'bold {AMBER}'), ('>', MUTED), ('_', f'bold {AMBER}'))


def _wm_stripes() -> Text:
    # The six stripes of the 1977 Apple logo, then the name.
    t = Text()
    for colour in ('#61bb46', '#fdb827', '#f5821f', '#e03a3e', '#963d97', '#009ddc'):
        t.append('▌', style=colour)
    t.append(' things', style=f'bold {FG}')
    return t


def _wm_manpage() -> Text:
    return Text.assemble(('THINGS(1)', f'bold {AMBER}'), ('   Getting Things Done Manual', MUTED))


def _wm_c64() -> Text:
    c64 = '#a5a5ff'
    return Text.assemble(('LOAD "THINGS",8,1', f'bold {c64}'), ('  ', ''), ('READY.', c64), (' █', c64))


def _wm_badge() -> Text:
    return Text.assemble((' THINGS ', f'bold {BG} on {AMBER}'), (' 3 ', f'bold {AMBER} on {RULE}'))


def _wm_checkbox() -> Text:
    return Text.assemble(('[', MUTED), ('x', f'bold {AMBER}'), (']', MUTED), (' things', f'bold {FG}'))


def _wm_hex() -> Text:
    return Text.assemble(('0x', MUTED), ('7H1N65', f'bold {AMBER}'), ('  // things', FAINT))


WORDMARKS = {
    'gradient': _wm_gradient,
    'prompt': _wm_prompt,
    'dos': _wm_dos,
    'stripes': _wm_stripes,
    'manpage': _wm_manpage,
    'c64': _wm_c64,
    'badge': _wm_badge,
    'checkbox': _wm_checkbox,
    'hex': _wm_hex,
}


def title_bar() -> Text:
    """Top bar (left side): the wordmark. Pick one with THINGS_TUI_WORDMARK."""
    name = os.environ.get('THINGS_TUI_WORDMARK', 'gradient').lower()
    return WORDMARKS.get(name, _wm_gradient)()


# ---------------------------------------------------------------------------
# Sidebar logo: "THINGS" in a few 3-line fonts
# ---------------------------------------------------------------------------

def _from_pixels(*letters: list) -> list:
    """Turn 5-row pixel bitmaps ('#' = on) into 3 rows of half blocks."""
    glyphs = []
    for bitmap in letters:
        rows = bitmap + ['.' * len(bitmap[0])]          # pad to 6 pixel rows
        glyph = []
        for top, bottom in zip(rows[0::2], rows[1::2]):
            glyph.append(''.join(
                '█' if t == '#' and b == '#' else '▀' if t == '#' else '▄' if b == '#' else ' '
                for t, b in zip(top, bottom)))
        glyphs.append(glyph)
    return glyphs


# Each font: (glyphs for T H I N G S, each a list of 3 rows; gap between letters)
LOGO_FONTS = {
    # Box drawing, double lines (after FIGlet's "Calvin S").
    'box': ([['╔╦╗', ' ║ ', ' ╩ '], ['╦ ╦', '╠═╣', '╩ ╩'], ['╦', '║', '╩'],
             ['╔╗╔', '║║║', '╝╚╝'], ['╔═╗', '║ ╦', '╚═╝'], ['╔═╗', '╚═╗', '╚═╝']], 0),
    # Box drawing, heavy lines (after FIGlet's "Future").
    'heavy': ([['┏┳┓', ' ┃ ', ' ╹ '], ['╻ ╻', '┣━┫', '╹ ╹'], ['╻', '┃', '╹'],
               ['┏┓╻', '┃┗┫', '╹ ╹'], ['┏━╸', '┃╺┓', '┗━┛'], ['┏━┓', '┗━┓', '┗━┛']], 0),
    # A 5-pixel-tall bitmap font drawn with half blocks: THINGS3.
    'pixel': (_from_pixels(
        ['###', '.#.', '.#.', '.#.', '.#.'],
        ['#.#', '#.#', '###', '#.#', '#.#'],
        ['###', '.#.', '.#.', '.#.', '###'],
        ['#..#', '##.#', '#.##', '#..#', '#..#'],
        ['.###', '#...', '#.##', '#..#', '.###'],
        ['.##', '#..', '.#.', '..#', '##.'],
        ['###', '..#', '.##', '..#', '###'],
    ), 1),
    # The 2-line block font with a shade underneath.
    'shade': ([['▀█▀', ' █ ', '░░░'], ['█ █', '█▀█', '░░░'], ['█', '█', '░'],
               ['█▄ █', '█ ▀█', '░░░░'], ['█▀▀', '█▄█', '░░░'], ['█▀', '▄█', '░░']], 1),
}

STRIPE_COLOURS = ('#61bb46', '#fdb827', '#f5821f', '#e03a3e', '#963d97', '#009ddc')
THREE_COLOUR = AMBER  # colour of the '3' in THINGS3


def logo(font: Optional[str] = None, colours: Optional[str] = None) -> Text:
    """'THINGS' in a 3-line font. Font from THINGS_TUI_LOGO (box, heavy, pixel,
    shade); amber, or the Apple stripes with THINGS_TUI_LOGO_COLOURS=stripes."""
    font = font or os.environ.get('THINGS_TUI_LOGO', 'pixel').lower()
    glyphs, gap = LOGO_FONTS.get(font, LOGO_FONTS['pixel'])
    mode = colours or os.environ.get('THINGS_TUI_LOGO_COLOURS', 'amber').lower()
    palette = (STRIPE_COLOURS if mode == 'stripes' else (AMBER,) * 6) + (THREE_COLOUR,) * (len(glyphs) - 6)
    t = Text()
    for row in range(3):
        for n, (glyph, colour) in enumerate(zip(glyphs, palette)):
            if n and gap:
                t.append(' ' * gap)
            text = glyph[row]
            if font == 'shade' and row == 2:
                t.append(text, style='#7a5a20')
            else:
                t.append(text, style=f'bold {colour}')
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


def title_bar_right() -> Text:
    now = datetime.now()
    return Text(f"{now:%a} {now.day} {now:%b}".upper() + f"  {now:%H:%M} ", style=MUTED)


def spaced(label: str) -> str:
    """Letter-spaced small caps for section rules, e.g. 'T H I S  E V E N I N G'."""
    return '  '.join(' '.join(word.upper()) for word in label.split())


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
    finished = item.get('status') in ('completed', 'canceled')
    style = f'{FAINT} strike' if finished else ('bold ' + FG if item.get('type') == 'project' else FG)
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
    """Right-hand details: schedule badge, deadline, checklist, notes, tag pills."""
    parts: list[Text] = []
    start = _parse_day(item.get('start_date'))
    if item.get('status') in ('completed', 'canceled'):
        stopped = _parse_day(item.get('stop_date'))
        if stopped:
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
    if item.get('notes'):
        parts.append(Text(ICONS['notes'], style=FAINT))

    if item.get('tags'):
        parts.append(Text(' '.join(f"#{tag}" for tag in item['tags']), style=TAG_FG))
    return Text('  ').join(parts)


def where_cell(item: dict) -> Text:
    parts = [item.get('area_title'), item.get('project_title'), item.get('heading_title')]
    return Text(' › '.join(p for p in parts if p), style=FAINT)


def group_heading(label: str, list_key: str) -> tuple[Text, Text]:
    """(icon cell, title cell) for a group heading row in the item table."""
    # Subheadings: bold, in the list's colour, with an icon. The table adds a
    # blank row above each one.
    if label == 'This Evening':
        return icon('evening'), Text(label, style=f"bold {LIST_COLOURS['evening']}")
    colour = LIST_COLOURS.get(list_key, LIST_COLOURS['project'])
    if list_key in ('upcoming', 'logbook'):
        return Text('▍', style=colour), Text(label, style=f'bold {colour}')
    return icon('heading', colour), Text(label, style=f'bold {colour}')


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


def sidebar_entry(label: str, key: str, count: Optional[int] = None, width: int = 28) -> Text:
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


def detail_card(item: dict, evening: bool = False) -> Text:
    """A Things-like card for a to-do or project: title, notes, checklist, metadata."""
    t = Text()
    t.append_text(checkbox(item))
    t.append('  ')
    t.append_text(title_cell(item).copy())
    t.stylize('bold', 0, len(t))
    t.append('\n')

    if item.get('notes'):
        t.append('\n')
        t.append(str(item['notes']).strip(), style=MUTED)
        t.append('\n')

    checklist = item.get('checklist')
    if isinstance(checklist, list) and checklist:
        t.append('\n')
        for c in checklist:
            done = c.get('status') == 'completed'
            t.append(f"  {ICONS['done'] if done else ICONS['todo']} ", style=BLUE if done else MUTED)
            t.append(c.get('title', ''), style=f'{FAINT} strike' if done else FG)
            t.append('\n')

    meta: list[tuple[Text, str]] = []
    start = _parse_day(item.get('start_date'))
    if evening:
        meta.append((icon('evening'), 'This Evening'))
    elif start == date.today():
        meta.append((icon('today'), 'Today'))
    elif start:
        meta.append((icon('upcoming'), f"{start:%A} {start.day} {start:%B %Y}"))
    elif item.get('start') == 'Someday':
        meta.append((icon('someday'), 'Someday'))
    elif item.get('start') == 'Inbox':
        meta.append((icon('inbox'), 'Inbox'))
    if item.get('reminder_time'):
        meta.append((Text('⏰', style=AMBER), f"Reminder {item['reminder_time']}"))
    badge = deadline_badge(item.get('deadline'))
    if badge:
        meta.append((Text(ICONS['deadline'], style=RED), f"Deadline {item['deadline']} ({badge.plain[2:]})"))
    where = where_cell(item).plain
    if where:
        meta.append((icon('project'), where))
    if item.get('tags'):
        meta.append((Text('#', style=MUTED), ', '.join(item['tags'])))
    if item.get('created'):
        meta.append((Text('+', style=FAINT), f"Created {_age(item['created'])}"))
    if item.get('stop_date'):
        meta.append((icon('logbook'), f"{str(item.get('status', 'done')).capitalize()} {str(item['stop_date'])[:16]}"))

    if meta:
        t.append('\n')
        for ic, label in meta:
            t.append('  ')
            t.append_text(ic)
            t.append(f"  {label}\n", style=MUTED)
    t.append(f"\n  {item.get('uuid', '')}", style=FAINT)
    return t
