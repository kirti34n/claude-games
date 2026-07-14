"""Color themes for the curses UI.

Themes reference colors by name (not curses.COLOR_*) so this module imports
even when curses is unavailable; names resolve to curses constants in
init_colors(), which only runs on the interactive (curses) path.
"""
import json

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None

from . import config

_HAS_CURSES = curses is not None

_THEMES = {
    'default': [
        (1, 'GREEN'), (2, 'RED'), (3, 'YELLOW'), (4, 'CYAN'),
        (5, 'MAGENTA'), (6, 'BLUE'), (7, 'WHITE'),
    ],
    'retro': [
        (1, 'YELLOW'), (2, 'RED'), (3, 'GREEN'), (4, 'WHITE'),
        (5, 'RED'), (6, 'YELLOW'), (7, 'GREEN'),
    ],
    'ocean': [
        (1, 'CYAN'), (2, 'MAGENTA'), (3, 'WHITE'), (4, 'BLUE'),
        (5, 'CYAN'), (6, 'BLUE'), (7, 'WHITE'),
    ],
}

_current_theme = 'default'


def _load_theme():
    global _current_theme
    try:
        cfg = json.loads((config.CONFIG_DIR / 'config.json').read_text())
        _current_theme = cfg.get('theme', 'default')
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def _save_theme(name):
    global _current_theme
    _current_theme = name
    config._ensure_config()
    cfg_file = config.CONFIG_DIR / 'config.json'
    try:
        cfg = json.loads(cfg_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = {}
    cfg['theme'] = name
    config._atomic_write_json(cfg_file, cfg)


def _color(name):
    return getattr(curses, 'COLOR_' + name, 0)


def init_colors():
    """Initialize color pairs, degrading gracefully on mono/limited terminals."""
    if not _HAS_CURSES:
        return
    try:
        curses.start_color()
    except curses.error:
        return
    if not curses.has_colors():
        return
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    theme = _THEMES.get(_current_theme, _THEMES['default'])
    for pair_id, name in theme:
        try:
            curses.init_pair(pair_id, _color(name), bg)
        except curses.error:
            pass
    if curses.COLORS >= 8:
        highlight = [
            (8, 'WHITE', 'RED'), (9, 'WHITE', 'GREEN'), (10, 'BLACK', 'YELLOW'),
            (11, 'WHITE', 'BLUE'), (12, 'WHITE', 'MAGENTA'), (13, 'BLACK', 'CYAN'),
            (14, 'BLACK', 'WHITE'),
        ]
        for pid, fg, bgn in highlight:
            try:
                curses.init_pair(pid, _color(fg), _color(bgn))
            except curses.error:
                pass
