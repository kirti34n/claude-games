"""The curses main menu (play.py 3646-3766)."""
try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None

from . import config
from . import render
from . import theme
from .game import Game
from .net import _net_menu
from .registry import _GAMES, _ICONS, _TITLE


def _run_game(stdscr, cls):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    theme._load_theme()  # honor saved theme even on direct `play <game>` launch
    theme.init_colors()
    difficulty = None
    while True:
        game = cls(stdscr)
        if game.supports_difficulty:
            # has_save() returns the saved score (possibly 0) or None; only
            # skip the difficulty picker when a save actually exists.
            if difficulty is None and Game.has_save(game.name) is None:
                difficulty = Game._select_difficulty(stdscr)
            if difficulty:
                game.difficulty = difficulty
        result = game.run()
        stdscr.nodelay(False)  # restore blocking input for the menu
        if result != 'retry':
            break


def _menu(stdscr):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    theme._load_theme()
    theme.init_colors()
    sel = 0
    scroll = 0
    stdscr.clear()
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 28 or w < 44:
            render._safe(stdscr, h // 2, max(0, (w - 30) // 2),
                  f'Need 44x28 terminal ({w}x{h})', curses.A_BOLD)
            stdscr.noutrefresh()
            curses.doupdate()
            stdscr.getch()
            continue

        ty = max(1, h // 2 - len(_GAMES) - 5)
        for i, line in enumerate(_TITLE):
            render._safe(stdscr, ty + i, max(0, (w - len(line)) // 2), line,
                  curses.color_pair(4) | curses.A_BOLD)
        sub = "Play while you wait"
        render._safe(stdscr, ty + len(_TITLE), max(0, (w - len(sub)) // 2), sub,
              curses.color_pair(3))

        ly = ty + len(_TITLE) + 2
        bx = max(0, (w - 42) // 2)
        # Scroll a window of games so the highlighted row is always drawn, even
        # when the full 13-game list is taller than the terminal.
        visible = max(1, (h - 3 - ly) // 2)
        if sel < scroll:
            scroll = sel
        elif sel >= scroll + visible:
            scroll = sel - visible + 1
        scroll = max(0, min(scroll, max(0, len(_GAMES) - visible)))
        end = min(len(_GAMES), scroll + visible)
        for i in range(scroll, end):
            name, desc, cls = _GAMES[i]
            y = ly + (i - scroll) * 2
            # cls.track_high_score == False (Minesweeper: its self.score is a
            # revealed-cell count that saturates across difficulties and
            # tracks its own per-difficulty best-time instead, mines-5) opts
            # a game out of this saturating cross-difficulty number
            # entirely, so a stale legacy value left in scores.json from
            # before the opt-out is never read or shown here again.
            hi = config.load_high_score(cls.name) if cls.track_high_score else 0
            icon = _ICONS.get(cls.name, '   ')
            if i == sel:
                render._safe(stdscr, y, bx, ' > ', curses.color_pair(1))
                render._safe(stdscr, y, bx + 3, icon,
                      curses.color_pair(5) | curses.A_BOLD)
                render._safe(stdscr, y, bx + 7, f'{name:<14}',
                      curses.A_BOLD | curses.A_REVERSE)
            else:
                render._safe(stdscr, y, bx + 3, icon, curses.color_pair(5))
                render._safe(stdscr, y, bx + 7, f'{name:<14}', curses.A_BOLD)
            sv = Game.has_save(cls.name)
            if sv is not None:
                render._safe(stdscr, y, bx + 22, f'[Resume:{sv}]',
                      curses.color_pair(1) | curses.A_BOLD)
            elif hi > 0:
                render._safe(stdscr, y, bx + 22, f'[Best: {hi}]',
                      curses.color_pair(3))
            render._safe(stdscr, y + 1, bx + 7, desc[:38], curses.color_pair(4))
        if scroll > 0:
            render._safe(stdscr, ly - 1, bx + 7, '^ more', curses.color_pair(3))
        if end < len(_GAMES):
            render._safe(stdscr, ly + (end - scroll) * 2, bx + 7, 'v more',
                  curses.color_pair(3))

        cy = min(h - 2, ly + visible * 2 + 1)
        ctrl = "Up/Down: Select  Enter: Play  M: Multiplayer  T: Theme  Q: Quit"
        render._safe(stdscr, cy, max(0, (w - len(ctrl)) // 2), ctrl,
              curses.color_pair(7))
        theme_label = f'Theme: {theme._current_theme}'
        render._safe(stdscr, cy + 1, max(0, (w - len(theme_label)) // 2),
              theme_label, curses.color_pair(4))
        stdscr.noutrefresh()
        curses.doupdate()

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')):
            sel = (sel - 1) % len(_GAMES)
        elif key in (curses.KEY_DOWN, ord('j')):
            sel = (sel + 1) % len(_GAMES)
        elif key in (curses.KEY_ENTER, 10, 13):
            _run_game(stdscr, _GAMES[sel][2])
            stdscr.nodelay(False)
        elif key in (ord('m'), ord('M')):
            _net_menu(stdscr)
            stdscr.nodelay(False)
        elif key in (ord('t'), ord('T')):
            names = list(theme._THEMES.keys())
            idx = names.index(theme._current_theme) if theme._current_theme in names else 0
            theme._save_theme(names[(idx + 1) % len(names)])
            theme.init_colors()
        elif key in (ord('q'), 27):
            break
