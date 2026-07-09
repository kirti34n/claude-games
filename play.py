"""
play - Terminal mini games collection

Usage:
    play              Launch interactive game menu (needs terminal)
    play snake        Play Snake interactively
    play tetris       Play Tetris interactively
    play 2048         Play 2048 interactively
    play dino         Play Dino Runner interactively
    play breakout     Play Breakout interactively
    play shooter      Play Space Shooter interactively
    play pong         Play Pong interactively
    play flappy       Play Flappy Bird interactively
    play mines        Play Minesweeper interactively
    play pacman       Play Pac-Man interactively
    play sokoban      Play Sokoban interactively
    play reversi      Play Reversi / Othello vs AI
    play frogger      Play Frogger interactively

    play cli                    Show in-conversation game menu
    play cli start snake        Start Snake (turn-based)
    play cli start 2048         Start 2048
    play cli start minesweeper  Start Minesweeper
    play cli start connect4     Start Connect4
    play cli <move>             Make a move (up/down/left/right)
    play cli <1-7>              Connect4: drop in column
    play cli reveal <r> <c>     Minesweeper: reveal cell
    play cli flag <r> <c>       Minesweeper: toggle flag
    play cli show               Show current board
    play cli quit               End current game

    play --version    Show version
    play --help       Show this help

Install:
    pip install claude-games

Note: the full-screen games use Python's curses module. It ships with Python on
Linux/macOS; on Windows `pip install claude-games` also pulls in windows-curses.
The turn-based `play cli ...` games and text commands work with no curses at all.
"""

__version__ = '2.5.0'

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None
import json
import locale
import os
import random
import sys
import time
from pathlib import Path

_HAS_CURSES = curses is not None


def _open_in_terminal(game_args: str = ''):
    """Launch the game in a split pane or new window (for piped environments like Claude Code)."""
    import shutil
    import subprocess
    play_bin = shutil.which('play') or sys.argv[0]
    cmd_str = f'{play_bin} {game_args}'.strip()

    # Native Windows: open the game in its own new console window. Use an argv
    # list + CREATE_NEW_CONSOLE so subprocess quotes paths that contain spaces
    # (e.g. C:\Program Files\...) correctly, instead of a shell string.
    if os.name == 'nt':
        try:
            if play_bin.endswith('.py'):
                argv = [sys.executable, play_bin]
            else:
                argv = [play_bin]
            argv += game_args.split()
            subprocess.Popen(argv, creationflags=subprocess.CREATE_NEW_CONSOLE)
            return True
        except Exception:
            return False

    # Prefer tmux split pane: game runs alongside Claude in the same terminal
    tmux = shutil.which('tmux')
    if tmux and os.environ.get('TMUX'):
        subprocess.Popen(
            [tmux, 'split-window', '-h', '-l', '50%', 'bash', '-lc', cmd_str],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # WSL2: use Windows Terminal tab
    wt = shutil.which('wt.exe')
    if wt:
        subprocess.Popen([wt, 'wsl.exe', '--', 'bash', '-lc', cmd_str],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # tmux available but not in a session: start one with the game
    if tmux:
        subprocess.Popen(
            [tmux, 'new-session', '-d', '-s', 'play', 'bash', '-lc', cmd_str],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # Fallback: try common Linux terminals
    for term in ('gnome-terminal', 'xterm', 'konsole', 'xfce4-terminal'):
        t = shutil.which(term)
        if t:
            if term == 'gnome-terminal':
                subprocess.Popen([t, '--', 'bash', '-lc', cmd_str],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen([t, '-e', f'bash -lc "{cmd_str}"'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


def _curses_wrapper(func, game_name: str = ''):
    """Like curses.wrapper but opens a new terminal window when no TTY is available."""
    if not _HAS_CURSES:
        print("The interactive games need Python's curses module, which isn't "
              "available here.", file=sys.stderr)
        if os.name == 'nt':
            print("On Windows, install it with:  pip install windows-curses",
                  file=sys.stderr)
        print("Or play the turn-based versions with no terminal needed:\n"
              "  play cli start snake   (also: 2048, minesweeper, connect4)",
              file=sys.stderr)
        sys.exit(1)
    if sys.stdin.isatty() and sys.stdout.isatty():
        return curses.wrapper(func)

    # No TTY: try to open in a split pane or new window
    if _open_in_terminal(game_name):
        name = game_name or 'game menu'
        if os.environ.get('TMUX'):
            print(f'Opened {name} in a tmux split pane. Switch with Ctrl-B + arrow keys.')
        else:
            print(f'Opened {name} in a new terminal window.')
        return
    print("No terminal available. Run 'play' directly in your terminal.", file=sys.stderr)
    sys.exit(1)

# ─── Config ──────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'claude-games'
SCORES_FILE = CONFIG_DIR / 'scores.json'
GAME_STATE_FILE = CONFIG_DIR / 'current_game.json'


def _ensure_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_high_score(name: str) -> int:
    try:
        return json.loads(SCORES_FILE.read_text()).get(name, 0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0


def save_high_score(name: str, score: int):
    _ensure_config()
    try:
        scores = json.loads(SCORES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        scores = {}
    scores[name] = max(score, scores.get(name, 0))
    SCORES_FILE.write_text(json.dumps(scores, indent=2))


# ─── Colors & Themes ─────────────────────────────────────────────────────────

# Themes reference colors by name (not curses.COLOR_*) so this module imports
# even when curses is unavailable; names resolve to curses constants in
# init_colors(), which only runs on the interactive (curses) path.
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
        cfg = json.loads((CONFIG_DIR / 'config.json').read_text())
        _current_theme = cfg.get('theme', 'default')
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def _save_theme(name):
    global _current_theme
    _current_theme = name
    _ensure_config()
    cfg_file = CONFIG_DIR / 'config.json'
    try:
        cfg = json.loads(cfg_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = {}
    cfg['theme'] = name
    cfg_file.write_text(json.dumps(cfg, indent=2))


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


# ─── Base Game ───────────────────────────────────────────────────────────────

class Game:
    name = "game"
    min_h = 20
    min_w = 40
    supports_difficulty = False

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.score = 0
        self.paused = False
        self.game_over = False
        self.won = False
        self._show_help = False
        self.difficulty = 'medium'
        self.h, self.w = stdscr.getmaxyx()

    def safe_addstr(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        text = text[:max(0, w - x)]
        if not text:
            return
        try:
            self.stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def center_text(self, y, text, attr=0):
        x = max(0, (self.w - len(text)) // 2)
        self.safe_addstr(y, x, text, attr)

    def draw_box(self, y, x, h, w, attr=0):
        self.safe_addstr(y, x, '┌' + '─' * (w - 2) + '┐', attr)
        for i in range(1, h - 1):
            self.safe_addstr(y + i, x, '│', attr)
            self.safe_addstr(y + i, x + w - 1, '│', attr)
        self.safe_addstr(y + h - 1, x, '└' + '─' * (w - 2) + '┘', attr)

    def setup(self):
        pass

    def handle_input(self, key):
        pass

    def update(self):
        pass

    def draw(self):
        pass

    def get_controls(self):
        """Override to return list of (key, description) tuples for help overlay."""
        return []

    def get_stats(self):
        """Override to return list of (label, value) strings for game over screen."""
        return []

    def _draw_help_overlay(self):
        controls = self.get_controls()
        if not controls:
            return
        box_w = max(len(k) + len(d) + 6 for k, d in controls) + 4
        box_w = max(box_w, 20)
        box_h = len(controls) + 4
        sy = max(0, (self.h - box_h) // 2)
        sx = max(0, (self.w - box_w) // 2)
        for i in range(box_h):
            self.safe_addstr(sy + i, sx, ' ' * box_w)
        self.draw_box(sy, sx, box_h, box_w, curses.A_BOLD)
        self.center_text(sy, ' CONTROLS ', curses.A_BOLD | curses.A_REVERSE)
        for i, (key, desc) in enumerate(controls):
            self.safe_addstr(sy + 2 + i, sx + 2, f'{key:<8} {desc}')
        self.center_text(sy + box_h - 1, ' ? to close ', curses.color_pair(4))

    @staticmethod
    def _select_difficulty(stdscr):
        options = ['Easy', 'Medium', 'Hard']
        sel = 1
        while True:
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            mid_y = h // 2
            _safe(stdscr, mid_y - 3, max(0, (w - 20) // 2),
                  'SELECT DIFFICULTY', curses.A_BOLD)
            for i, opt in enumerate(options):
                y = mid_y - 1 + i
                if i == sel:
                    _safe(stdscr, y, max(0, (w - 14) // 2),
                          f'  > {opt} <  ',
                          curses.A_BOLD | curses.A_REVERSE)
                else:
                    _safe(stdscr, y, max(0, (w - 14) // 2),
                          f'    {opt}    ')
            _safe(stdscr, mid_y + 3, max(0, (w - 26) // 2),
                  'Up/Down: Select  Enter: OK', curses.color_pair(4))
            stdscr.noutrefresh()
            curses.doupdate()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('w'), ord('k')):
                sel = (sel - 1) % 3
            elif key in (curses.KEY_DOWN, ord('s'), ord('j')):
                sel = (sel + 1) % 3
            elif key in (curses.KEY_ENTER, 10, 13):
                return options[sel].lower()
            elif key in (27, ord('q')):
                return 'medium'

    def get_timeout(self):
        return 100

    def get_save_data(self):
        """Override to return serializable state dict. None = no save."""
        return None

    def _auto_save(self):
        data = self.get_save_data()
        if data is not None:
            _ensure_config()
            (CONFIG_DIR / f'save_{self.name}.json').write_text(json.dumps(data))

    @staticmethod
    def _load_save(name):
        f = CONFIG_DIR / f'save_{name}.json'
        if f.exists():
            try:
                data = json.loads(f.read_text())
                f.unlink()
                return data
            except Exception:
                f.unlink(missing_ok=True)
        return None

    @staticmethod
    def has_save(name):
        f = CONFIG_DIR / f'save_{name}.json'
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text()).get('score', 0)
        except Exception:
            return None

    def run(self):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            self.setup()
        except Exception:
            # Save was valid JSON but an incompatible schema (older/newer
            # version, truncation). _load_save already consumed it, so a clean
            # re-init starts a fresh game instead of crashing on resume.
            diff = self.difficulty
            self.__init__(self.stdscr)
            self.difficulty = diff  # keep the caller-selected difficulty
            self.setup()
        self.h, self.w = self.stdscr.getmaxyx()

        timeout = self.get_timeout()
        self.stdscr.timeout(timeout)

        first = True
        while True:
            key = -1 if first else self.stdscr.getch()
            first = False
            self.h, self.w = self.stdscr.getmaxyx()

            if key == 27 or key == ord('q'):
                if not self.game_over:
                    self._auto_save()
                self.stdscr.nodelay(False)
                return 'quit'
            if key == ord('p') and not self.game_over:
                self.paused = not self.paused
            elif key == ord('?') or key == ord('H'):
                self._show_help = not self._show_help
            elif key != -1 and self._show_help:
                self._show_help = False  # any other key closes help

            # Update timeout if it changed (e.g. snake speeds up)
            new_timeout = self.get_timeout()
            if new_timeout != timeout:
                timeout = new_timeout
                self.stdscr.timeout(timeout)

            self.stdscr.erase()
            # Size gate runs BEFORE advancing state, so a shrunk terminal pauses
            # the game (visibly) instead of playing on invisibly.
            if self.h < self.min_h or self.w < self.min_w:
                self.center_text(self.h // 2,
                                 f'Terminal too small ({self.w}x{self.h})')
                self.center_text(self.h // 2 + 1,
                                 f'Need at least {self.min_w}x{self.min_h}')
                self.stdscr.noutrefresh()
                curses.doupdate()
                continue

            active = not self.paused and not self._show_help and not self.game_over
            if active:
                if key != -1:
                    self.handle_input(key)
                self.update()

            self.draw()
            if self.game_over and not self._show_help:
                return self._game_over_screen()
            if self._show_help:
                self._draw_help_overlay()
            elif self.paused:
                self.center_text(self.h // 2,
                                 '  PAUSED  -  Press P to resume  ',
                                 curses.A_REVERSE | curses.A_BOLD)
            self.stdscr.noutrefresh()
            curses.doupdate()

    def _game_over_screen(self):
        mid = self.h // 2
        if self.won:
            self.center_text(mid - 3, '  YOU WIN!  ',
                             curses.color_pair(1) | curses.A_BOLD)
        else:
            self.center_text(mid - 3, '  GAME OVER  ',
                             curses.color_pair(2) | curses.A_BOLD)
        self.center_text(mid - 1, f'  Score: {self.score}  ', curses.A_BOLD)
        high = load_high_score(self.name)
        if self.score > high:
            save_high_score(self.name, self.score)
            self.center_text(mid, '  NEW HIGH SCORE!  ',
                             curses.A_REVERSE | curses.A_BOLD)
            curses.beep()
        else:
            self.center_text(mid, f'  High Score: {high}  ',
                             curses.color_pair(3))
        stats = self.get_stats()
        for i, (label, value) in enumerate(stats):
            self.center_text(mid + 2 + i, f'  {label}: {value}  ',
                             curses.color_pair(4))
        bottom = mid + 2 + len(stats) + 1
        self.center_text(bottom, '  [R] Retry   [Q] Quit  ',
                         curses.color_pair(4))
        self.stdscr.noutrefresh()
        curses.doupdate()
        self.stdscr.nodelay(False)
        while True:
            key = self.stdscr.getch()
            if key == ord('r'):
                (CONFIG_DIR / f'save_{self.name}.json').unlink(missing_ok=True)
                return 'retry'
            if key == ord('q') or key == 27:
                return 'quit'


# ─── Snake ───────────────────────────────────────────────────────────────────

class SnakeGame(Game):
    name = "snake"
    min_h = 15
    min_w = 30

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.board_h = saved['bh']
            self.board_w = saved['bw']
            self.board_y = max(1, (self.h - self.board_h) // 2)
            self.board_x = max(1, (self.w - self.board_w) // 2)
            self.snake = [tuple(p) for p in saved['snake']]
            self.direction = tuple(saved['dir'])
            self.next_direction = tuple(saved['ndir'])
            self.food = tuple(saved['food'])
            self.score = saved['score']
            self._fit_bounds()
            return
        self.board_h = min(22, self.h - 4)
        self.board_w = min(50, self.w - 4)
        self.board_y = max(1, (self.h - self.board_h) // 2)
        self.board_x = max(1, (self.w - self.board_w) // 2)
        mid_y = self.board_h // 2
        mid_x = self.board_w // 2
        self.snake = [(mid_y, mid_x), (mid_y, mid_x - 1), (mid_y, mid_x - 2)]
        self.direction = (0, 1)
        self.next_direction = (0, 1)
        self.score = 0
        self.food = None
        self._spawn_food()
        self._fit_bounds()

    def _fit_bounds(self):
        # Require a terminal at least as big as the (possibly resumed) board, so
        # run()'s size gate shows "too small" instead of drawing walls off-screen.
        self.min_w = max(30, self.board_w + 2)
        self.min_h = max(15, self.board_h + 3)

    def get_save_data(self):
        return {'bh': self.board_h, 'bw': self.board_w,
                'snake': self.snake, 'dir': self.direction,
                'ndir': self.next_direction,
                'food': self.food, 'score': self.score}

    def _spawn_food(self):
        snake_set = set(self.snake)
        empty = [(y, x) for y in range(1, self.board_h - 1)
                 for x in range(1, self.board_w - 1) if (y, x) not in snake_set]
        if empty:
            self.food = random.choice(empty)

    def get_timeout(self):
        return max(80, 180 - self.score * 3)

    def handle_input(self, key):
        dy, dx = self.direction
        if (key == curses.KEY_UP or key == ord('w')) and dy != 1:
            self.next_direction = (-1, 0)
        elif (key == curses.KEY_DOWN or key == ord('s')) and dy != -1:
            self.next_direction = (1, 0)
        elif (key == curses.KEY_LEFT or key == ord('a')) and dx != 1:
            self.next_direction = (0, -1)
        elif (key == curses.KEY_RIGHT or key == ord('d')) and dx != -1:
            self.next_direction = (0, 1)

    def update(self):
        self.direction = self.next_direction
        dy, dx = self.direction
        hy, hx = self.snake[0]
        nh = (hy + dy, hx + dx)
        ny, nx = nh
        if ny <= 0 or ny >= self.board_h - 1 or nx <= 0 or nx >= self.board_w - 1:
            self.game_over = True
            return
        grow = (nh == self.food)
        # The tail vacates its cell this tick (unless growing), so chasing your
        # own tail is legal: only the segments that remain count as collisions.
        body = self.snake if grow else self.snake[:-1]
        if nh in body:
            self.game_over = True
            return
        self.snake.insert(0, nh)
        if grow:
            self.score += 1
            self._spawn_food()
        else:
            self.snake.pop()

    def draw(self):
        # Re-center every frame so a resize keeps the board centered.
        self.board_y = max(1, (self.h - self.board_h) // 2)
        self.board_x = max(1, (self.w - self.board_w) // 2)
        by, bx = self.board_y, self.board_x
        self.safe_addstr(by - 1, bx, f' SNAKE  Score: {self.score} ',
                         curses.A_BOLD)
        self.draw_box(by, bx, self.board_h, self.board_w)
        if self.food:
            fy, fx = self.food
            self.safe_addstr(by + fy, bx + fx, '*',
                             curses.color_pair(2) | curses.A_BOLD)
        for i, (sy, sx) in enumerate(self.snake):
            ch = '@' if i == 0 else 'o'
            self.safe_addstr(by + sy, bx + sx, ch,
                             curses.color_pair(1) | curses.A_BOLD)
        self.safe_addstr(by + self.board_h, bx,
                         ' WASD:Move  P:Pause  ?:Help  ESC:Quit ',
                         curses.color_pair(4))

    def get_controls(self):
        return [('WASD', 'Move'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Length', len(self.snake))]


# ─── Tetris ──────────────────────────────────────────────────────────────────

_SHAPES = {
    'I': [[1, 1, 1, 1]],
    'O': [[1, 1], [1, 1]],
    'T': [[0, 1, 0], [1, 1, 1]],
    'S': [[0, 1, 1], [1, 1, 0]],
    'Z': [[1, 1, 0], [0, 1, 1]],
    'J': [[1, 0, 0], [1, 1, 1]],
    'L': [[0, 0, 1], [1, 1, 1]],
}
_PIECE_COLORS = {'I': 4, 'O': 3, 'T': 5, 'S': 1, 'Z': 2, 'J': 6, 'L': 3}


def _rotate_cw(shape):
    return [list(row) for row in zip(*shape[::-1])]


class TetrisGame(Game):
    name = "tetris"
    ROWS, COLS = 20, 10
    min_h = 24
    min_w = 40

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.board = saved['board']
            self.score = saved['score']
            self.lines = saved['lines']
            self.level = saved['level']
            self.cur_type = saved['ct']
            self.next_type = saved['nt']
            self.cur = saved['cur']
            self.cur_y = saved['cy']
            self.cur_x = saved['cx']
            self.last_drop = time.time()
            return
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.score = self.lines = 0
        self.level = 1
        self.next_type = random.choice(list(_SHAPES))
        self._spawn()
        self.last_drop = time.time()

    def get_save_data(self):
        return {'board': self.board, 'score': self.score,
                'lines': self.lines, 'level': self.level,
                'ct': self.cur_type, 'nt': self.next_type,
                'cur': self.cur, 'cy': self.cur_y, 'cx': self.cur_x}

    @property
    def drop_interval(self):
        return max(0.05, 0.8 - (self.level - 1) * 0.07)

    def _spawn(self):
        self.cur_type = self.next_type
        self.next_type = random.choice(list(_SHAPES))
        self.cur = [row[:] for row in _SHAPES[self.cur_type]]
        self.cur_y = 0
        self.cur_x = (self.COLS - len(self.cur[0])) // 2
        if self._hit(self.cur, self.cur_y, self.cur_x):
            self.game_over = True

    def _hit(self, shape, py, px):
        for r, row in enumerate(shape):
            for c, v in enumerate(row):
                if v:
                    ny, nx = py + r, px + c
                    if ny < 0 or ny >= self.ROWS or nx < 0 or nx >= self.COLS:
                        return True
                    if self.board[ny][nx]:
                        return True
        return False

    def _lock(self):
        color = _PIECE_COLORS[self.cur_type]
        for r, row in enumerate(self.cur):
            for c, v in enumerate(row):
                if v:
                    self.board[self.cur_y + r][self.cur_x + c] = color
        cleared = 0
        new_board = []
        for row in self.board:
            if all(cell != 0 for cell in row):
                cleared += 1
            else:
                new_board.append(row)
        for _ in range(cleared):
            new_board.insert(0, [0] * self.COLS)
        self.board = new_board
        self.lines += cleared
        self.score += [0, 100, 300, 500, 800][min(cleared, 4)] * self.level
        self.level = self.lines // 10 + 1
        self._spawn()

    def get_timeout(self):
        return 50

    def handle_input(self, key):
        if key == curses.KEY_LEFT or key == ord('a'):
            if not self._hit(self.cur, self.cur_y, self.cur_x - 1):
                self.cur_x -= 1
        elif key == curses.KEY_RIGHT or key == ord('d'):
            if not self._hit(self.cur, self.cur_y, self.cur_x + 1):
                self.cur_x += 1
        elif key == curses.KEY_DOWN or key == ord('s'):
            if not self._hit(self.cur, self.cur_y + 1, self.cur_x):
                self.cur_y += 1
                self.score += 1
        elif key == curses.KEY_UP or key == ord('w'):
            rotated = _rotate_cw(self.cur)
            for dx in [0, -1, 1, -2, 2]:
                if not self._hit(rotated, self.cur_y, self.cur_x + dx):
                    self.cur = rotated
                    self.cur_x += dx
                    break
        elif key == ord(' '):
            while not self._hit(self.cur, self.cur_y + 1, self.cur_x):
                self.cur_y += 1
                self.score += 2
            self._lock()
            self.last_drop = time.time()

    def update(self):
        now = time.time()
        if now - self.last_drop >= self.drop_interval:
            if not self._hit(self.cur, self.cur_y + 1, self.cur_x):
                self.cur_y += 1
            else:
                self._lock()
            self.last_drop = now

    def draw(self):
        bw = self.COLS * 2 + 2
        sx = max(0, (self.w - bw - 16) // 2)
        sy = max(0, (self.h - self.ROWS - 2) // 2)
        self.draw_box(sy, sx, self.ROWS + 2, bw)

        for r in range(self.ROWS):
            for c in range(self.COLS):
                cell = self.board[r][c]
                if cell:
                    self.safe_addstr(sy + 1 + r, sx + 1 + c * 2, '[]',
                                     curses.color_pair(cell) | curses.A_BOLD)

        # Ghost
        gy = self.cur_y
        while not self._hit(self.cur, gy + 1, self.cur_x):
            gy += 1
        if gy != self.cur_y:
            col = _PIECE_COLORS[self.cur_type]
            for r, row in enumerate(self.cur):
                for c, v in enumerate(row):
                    if v:
                        self.safe_addstr(sy + 1 + gy + r,
                                         sx + 1 + (self.cur_x + c) * 2,
                                         '..', curses.color_pair(col))

        # Current piece
        col = _PIECE_COLORS[self.cur_type]
        for r, row in enumerate(self.cur):
            for c, v in enumerate(row):
                if v:
                    self.safe_addstr(sy + 1 + self.cur_y + r,
                                     sx + 1 + (self.cur_x + c) * 2, '[]',
                                     curses.color_pair(col) | curses.A_BOLD)

        # Panel
        px = sx + bw + 2
        self.safe_addstr(sy, px, 'TETRIS', curses.A_BOLD)
        self.safe_addstr(sy + 2, px, f'Score: {self.score}')
        self.safe_addstr(sy + 3, px, f'Lines: {self.lines}')
        self.safe_addstr(sy + 4, px, f'Level: {self.level}')
        self.safe_addstr(sy + 6, px, 'Next:')
        nxt = _SHAPES[self.next_type]
        nc = _PIECE_COLORS[self.next_type]
        for r, row in enumerate(nxt):
            for c, v in enumerate(row):
                if v:
                    self.safe_addstr(sy + 7 + r, px + c * 2, '[]',
                                     curses.color_pair(nc) | curses.A_BOLD)
        self.safe_addstr(sy + 11, px, 'A/D Move')
        self.safe_addstr(sy + 12, px, ' W  Rotate')
        self.safe_addstr(sy + 13, px, ' S  Soft drop')
        self.safe_addstr(sy + 14, px, 'SPC Hard drop')
        self.safe_addstr(sy + 15, px, ' P  Pause')
        self.safe_addstr(sy + 16, px, 'ESC Quit')

    def get_controls(self):
        return [('A/D', 'Move left/right'), ('W', 'Rotate'),
                ('S', 'Soft drop'), ('Space', 'Hard drop'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Lines', self.lines), ('Level', self.level)]


# ─── 2048 ────────────────────────────────────────────────────────────────────

class Game2048(Game):
    name = "2048"
    SIZE = 4
    min_h = 22
    min_w = 36

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.grid = saved['grid']
            self.score = saved['score']
            self.won = saved.get('won', False)
            return
        self.grid = [[0] * self.SIZE for _ in range(self.SIZE)]
        self.score = 0
        self.won = False
        self._add_tile()
        self._add_tile()

    def get_save_data(self):
        return {'grid': self.grid, 'score': self.score, 'won': self.won}

    def _add_tile(self):
        empty = [(r, c) for r in range(self.SIZE) for c in range(self.SIZE)
                 if self.grid[r][c] == 0]
        if empty:
            r, c = random.choice(empty)
            self.grid[r][c] = 4 if random.random() < 0.1 else 2

    def _slide(self, row):
        tiles = [x for x in row if x]
        merged, pts, i = [], 0, 0
        while i < len(tiles):
            if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
                v = tiles[i] * 2
                merged.append(v)
                pts += v
                i += 2
            else:
                merged.append(tiles[i])
                i += 1
        return merged + [0] * (self.SIZE - len(merged)), pts

    def _move(self, d):
        old = [row[:] for row in self.grid]
        pts = 0
        if d == 'left':
            for r in range(self.SIZE):
                self.grid[r], p = self._slide(self.grid[r])
                pts += p
        elif d == 'right':
            for r in range(self.SIZE):
                rev, p = self._slide(self.grid[r][::-1])
                self.grid[r] = rev[::-1]
                pts += p
        elif d == 'up':
            for c in range(self.SIZE):
                col = [self.grid[r][c] for r in range(self.SIZE)]
                col, p = self._slide(col)
                pts += p
                for r in range(self.SIZE):
                    self.grid[r][c] = col[r]
        elif d == 'down':
            for c in range(self.SIZE):
                col = [self.grid[r][c] for r in range(self.SIZE)]
                rev, p = self._slide(col[::-1])
                pts += p
                for r in range(self.SIZE):
                    self.grid[r][c] = rev[::-1][r]
        changed = self.grid != old
        if changed:
            self.score += pts
            self._add_tile()
            if not self.won and any(self.grid[r][c] == 2048
                                    for r in range(self.SIZE)
                                    for c in range(self.SIZE)):
                self.won = True
        return changed

    def _can_move(self):
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                if self.grid[r][c] == 0:
                    return True
                if c + 1 < self.SIZE and self.grid[r][c] == self.grid[r][c + 1]:
                    return True
                if r + 1 < self.SIZE and self.grid[r][c] == self.grid[r + 1][c]:
                    return True
        return False

    def get_timeout(self):
        return -1

    def handle_input(self, key):
        dirs = {curses.KEY_LEFT: 'left', curses.KEY_RIGHT: 'right',
                curses.KEY_UP: 'up', curses.KEY_DOWN: 'down',
                ord('a'): 'left', ord('d'): 'right',
                ord('w'): 'up', ord('s'): 'down'}
        if key in dirs and self._move(dirs[key]) and not self._can_move():
            self.game_over = True

    def update(self):
        pass

    def _tile_attr(self, v):
        if v == 0:
            return curses.color_pair(0)
        t = {2: 7, 4: 4, 8: 1, 16: 3, 32: 5, 64: 2, 128: 3, 256: 4,
             512: 1, 1024: 2, 2048: 3}
        pair = t.get(v, 7)
        attr = curses.color_pair(pair)
        if v >= 16:
            attr |= curses.A_BOLD
        if v == 2048:
            attr |= curses.A_REVERSE
        return attr

    def draw(self):
        cw = 7
        gw = cw * self.SIZE + self.SIZE + 1
        gh = 3 * self.SIZE + self.SIZE + 1
        sx = max(0, (self.w - gw) // 2)
        sy = max(0, (self.h - gh - 4) // 2)
        self.safe_addstr(sy, sx, ' 2 0 4 8 ', curses.A_BOLD | curses.A_REVERSE)
        sc = f'Score: {self.score}'
        self.safe_addstr(sy, sx + gw - len(sc), sc,
                         curses.color_pair(3) | curses.A_BOLD)
        sy += 2

        top = '┌' + ('─' * cw + '┬') * (self.SIZE - 1) + '─' * cw + '┐'
        self.safe_addstr(sy, sx, top)
        for r in range(self.SIZE):
            ry = sy + 1 + r * 4
            for sub in range(3):
                self.safe_addstr(ry + sub, sx, '│')
                for c in range(self.SIZE):
                    v = self.grid[r][c]
                    cx = sx + 1 + c * (cw + 1)
                    if sub == 1 and v:
                        self.safe_addstr(ry + sub, cx, str(v).center(cw),
                                         self._tile_attr(v))
                    else:
                        self.safe_addstr(ry + sub, cx, ' ' * cw)
                    self.safe_addstr(ry + sub, cx + cw, '│')
            if r < self.SIZE - 1:
                sep = '├' + ('─' * cw + '┼') * (self.SIZE - 1) + '─' * cw + '┤'
                self.safe_addstr(ry + 3, sx, sep)
            else:
                bot = '└' + ('─' * cw + '┴') * (self.SIZE - 1) + '─' * cw + '┘'
                self.safe_addstr(ry + 3, sx, bot)
        if self.won:
            self.center_text(sy + gh + 1, '  You reached 2048! Keep going!  ',
                             curses.color_pair(3) | curses.A_BOLD)
        self.safe_addstr(sy + gh + 2, sx, ' WASD:Move  ?:Help  ESC:Quit ',
                         curses.color_pair(4))

    def get_controls(self):
        return [('WASD', 'Slide tiles'), ('ESC', 'Quit')]

    def get_stats(self):
        max_tile = max(self.grid[r][c] for r in range(self.SIZE)
                       for c in range(self.SIZE))
        return [('Best Tile', max_tile)]


# ─── Dino Runner ─────────────────────────────────────────────────────────────

_DINO = [[" O ", "/|\\", "/ \\"], [" O ", "/|\\", "| \\"]]
_CACTUS_SM = [" ^ ", " | "]
_CACTUS_LG = [" ^ ", "/|\\", " | ", " | "]
_CACTUS_XL = [" ^ ", "/|\\", "-|-", " | ", " | "]


class DinoGame(Game):
    name = "dino"
    min_h = 15
    min_w = 50

    @property
    def ground_y(self):
        return self.h - 5

    def setup(self):
        self._hi = load_high_score(self.name)  # cache; can't change mid-game
        saved = self._load_save(self.name)
        if saved:
            self.dino_x = 8
            self.dino_y = saved['dino_y']
            self.velocity = saved['velocity']
            self.on_ground = saved['on_ground']
            self.gravity = 0.5
            self.jump_power = -2.0
            self.obstacles = saved['obstacles']
            self.speed = saved['speed']
            self.score = saved['score']
            self.frame = saved['frame']
            self.spawn_timer = saved['spawn_timer']
            return
        self.dino_x = 8
        self.dino_y = 0.0
        self.velocity = 0.0
        self.on_ground = True
        self.gravity = 0.5
        self.jump_power = -2.0
        self.obstacles = []
        self.speed = 1.0
        self.score = 0
        self.frame = 0
        self.spawn_timer = 30

    def get_save_data(self):
        return {'score': self.score, 'speed': self.speed, 'frame': self.frame,
                'dino_y': self.dino_y, 'velocity': self.velocity,
                'on_ground': self.on_ground, 'spawn_timer': self.spawn_timer,
                'obstacles': self.obstacles}

    def get_timeout(self):
        return 40

    def handle_input(self, key):
        if (key == ord(' ') or key == curses.KEY_UP or key == ord('w')) and self.on_ground:
            self.velocity = self.jump_power
            self.on_ground = False

    def update(self):
        self.frame += 1
        if self.frame % 3 == 0:
            self.score += 1
        self.speed = min(3.0, 1.0 + self.score / 100.0)

        prev_dino_y = self.dino_y  # for coherent swept collision below
        if not self.on_ground:
            self.dino_y += self.velocity
            self.velocity += self.gravity
            if self.dino_y >= 0:
                self.dino_y = 0.0
                self.velocity = 0.0
                self.on_ground = True

        for obs in self.obstacles:
            obs['x'] -= self.speed
        self.obstacles = [o for o in self.obstacles if o['x'] > -6]

        self.spawn_timer -= 1
        if self.spawn_timer <= 0:
            self._spawn()

        gy = self.ground_y
        db = gy + int(self.dino_y)
        dt = db - 2
        dl, dr = self.dino_x + 1, self.dino_x + 2  # tighter dino hitbox
        # Only sweep the columns an obstacle crossed this tick when the dino was
        # on the ground the WHOLE tick - that is the case a fast obstacle could
        # tunnel through the narrow hitbox. While the dino is airborne/landing,
        # use the forgiving single end-position test so clearing a cactus and
        # touching down beside it is not a false hit.
        grounded = (prev_dino_y == 0.0 and self.dino_y == 0.0)
        for obs in self.obstacles:
            art = obs['art']
            oh = len(art)
            ow = max(len(l) for l in art)
            if grounded:
                lo = int(obs['x'])
                hi = int(obs['x'] + self.speed)
                hit_x = (lo + 1 <= dr and hi + ow - 2 >= dl)
            else:
                ox = int(obs['x'])
                hit_x = (ox + 1 <= dr and ox + ow - 2 >= dl)
            if hit_x and db >= gy - oh + 1 and dt <= gy:
                self.game_over = True
                return

    def _spawn(self):
        if self.obstacles and self.obstacles[-1]['x'] > self.w - 20:
            self.spawn_timer = 5
            return
        kind = random.choices(['sm', 'lg', 'xl'], weights=[50, 35, 15])[0]
        art = {'sm': _CACTUS_SM, 'lg': _CACTUS_LG, 'xl': _CACTUS_XL}[kind]
        self.obstacles.append({'x': float(self.w), 'art': art})
        mn = max(15, int(30 / self.speed))
        mx = max(25, int(55 / self.speed))
        self.spawn_timer = random.randint(mn, mx)

    def draw(self):
        gy = self.ground_y
        sc = f'Score: {self.score}'
        hi = f'HI: {max(self.score, self._hi)}'
        self.safe_addstr(1, self.w - len(sc) - 2, sc, curses.A_BOLD)
        self.safe_addstr(1, self.w - len(sc) - len(hi) - 4, hi,
                         curses.color_pair(3))
        self.safe_addstr(1, 2, 'DINO RUNNER', curses.A_BOLD)

        anim = (self.frame // 4) % 2
        art = _DINO[anim if self.on_ground else 0]
        dy = gy + int(self.dino_y)
        for i, line in enumerate(art):
            self.safe_addstr(dy - len(art) + 1 + i, self.dino_x, line,
                             curses.color_pair(1) | curses.A_BOLD)

        for obs in self.obstacles:
            ox = int(obs['x'])
            for i, line in enumerate(obs['art']):
                self.safe_addstr(gy - len(obs['art']) + 1 + i, ox, line,
                                 curses.color_pair(2) | curses.A_BOLD)

        self.safe_addstr(gy + 1, 0, '─' * self.w, curses.color_pair(4))
        off = int(self.frame * self.speed) % 6
        for x in range(off, self.w - 1, 6):
            self.safe_addstr(gy + 2, x, '.', curses.color_pair(4))
        self.safe_addstr(self.h - 1, 2,
                         'W/Space: Jump  P: Pause  ?: Help  ESC: Quit',
                         curses.color_pair(4))

    def get_controls(self):
        return [('W/Space', 'Jump'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Speed', f'{self.speed:.1f}x')]


# ─── Breakout ────────────────────────────────────────────────────────────────

class BreakoutGame(Game):
    name = "breakout"
    min_h = 22
    min_w = 44

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.area_w = saved['area_w']
            self.area_h = saved['area_h']
            self.area_x = (self.w - self.area_w) // 2
            self.area_y = (self.h - self.area_h) // 2
            self.paddle_w = saved['paddle_w']
            self.paddle_y = self.area_h - 3
            self.paddle_x = saved['paddle_x']
            self.ball_x = saved['ball_x']
            self.ball_y = saved['ball_y']
            self.ball_dx = saved['ball_dx']
            self.ball_dy = saved['ball_dy']
            self.ball_moving = saved['ball_moving']
            self.brick_w = saved['brick_w']
            self.brick_rows = saved['brick_rows']
            self.brick_start_y = saved['brick_start_y']
            self.bricks_per_row = saved['bricks_per_row']
            self.brick_off_x = saved['brick_off_x']
            self.bricks = {(int(k.split(',')[0]), int(k.split(',')[1])): v
                           for k, v in saved['bricks'].items()}
            self.score = saved['score']
            self.lives = saved['lives']
            self._fit_bounds()
            return

        self.area_w = min(52, self.w - 4)
        self.area_h = min(28, self.h - 4)
        self.area_x = (self.w - self.area_w) // 2
        self.area_y = (self.h - self.area_h) // 2

        self.paddle_w = 8
        self.paddle_y = self.area_h - 3
        self.paddle_x = (self.area_w - self.paddle_w) // 2

        self.ball_x = float(self.area_w // 2)
        self.ball_y = float(self.paddle_y - 1)
        self.ball_dx = 1.0
        self.ball_dy = -1.0
        self.ball_moving = False

        self.brick_w = 4
        self.brick_rows = 4
        self.brick_start_y = 3
        usable = self.area_w - 2
        self.bricks_per_row = usable // self.brick_w
        total = self.bricks_per_row * self.brick_w
        self.brick_off_x = 1 + (usable - total) // 2
        colors = [2, 3, 1, 4]
        self.bricks = {(r, c): colors[r]
                       for r in range(self.brick_rows)
                       for c in range(self.bricks_per_row)}
        self.score = 0
        self.lives = 3
        self._fit_bounds()

    def _fit_bounds(self):
        # Gate on the actual play-area footprint so a resumed/resized terminal
        # smaller than the board shows "too small" instead of drawing off-screen.
        self.min_w = max(44, self.area_w + 2)
        self.min_h = max(22, self.area_h + 2)

    def get_save_data(self):
        bricks = {f'{r},{c}': v for (r, c), v in self.bricks.items()}
        return {'score': self.score, 'lives': self.lives,
                'paddle_x': self.paddle_x, 'paddle_w': self.paddle_w,
                'ball_x': self.ball_x, 'ball_y': self.ball_y,
                'ball_dx': self.ball_dx, 'ball_dy': self.ball_dy,
                'ball_moving': self.ball_moving,
                'area_w': self.area_w, 'area_h': self.area_h,
                'brick_rows': self.brick_rows, 'bricks_per_row': self.bricks_per_row,
                'brick_off_x': self.brick_off_x, 'brick_w': self.brick_w,
                'brick_start_y': self.brick_start_y, 'bricks': bricks}

    def get_timeout(self):
        return 60

    def handle_input(self, key):
        if key == curses.KEY_LEFT or key == ord('a'):
            self.paddle_x = max(1, self.paddle_x - 3)
            if not self.ball_moving:
                self.ball_x = float(self.paddle_x + self.paddle_w // 2)
        elif key == curses.KEY_RIGHT or key == ord('d'):
            self.paddle_x = min(self.area_w - self.paddle_w - 1,
                                self.paddle_x + 3)
            if not self.ball_moving:
                self.ball_x = float(self.paddle_x + self.paddle_w // 2)
        elif key == ord(' ') and not self.ball_moving:
            self.ball_moving = True
            self.ball_dx = random.choice([-1.0, 1.0])
            self.ball_dy = -1.0

    def update(self):
        if not self.ball_moving:
            return
        nx = self.ball_x + self.ball_dx
        ny = self.ball_y + self.ball_dy
        # Wall bounces
        if nx <= 1:
            self.ball_dx = abs(self.ball_dx)
            nx = 1.0
        elif nx >= self.area_w - 2:
            self.ball_dx = -abs(self.ball_dx)
            nx = float(self.area_w - 2)
        if ny <= 1:
            self.ball_dy = abs(self.ball_dy)
            ny = 1.0
        # Paddle bounce
        if (int(ny) >= self.paddle_y - 1 and int(ny) <= self.paddle_y
                and self.ball_dy > 0
                and self.paddle_x - 1 <= int(nx) <= self.paddle_x + self.paddle_w):
            self.ball_dy = -abs(self.ball_dy)
            hit = (nx - self.paddle_x) / self.paddle_w
            self.ball_dx = (hit - 0.5) * 2.0
            if abs(self.ball_dx) < 0.4:
                self.ball_dx = 0.4 if self.ball_dx >= 0 else -0.4
            # Cap ball speed
            spd = (self.ball_dx ** 2 + self.ball_dy ** 2) ** 0.5
            if spd > 2.0:
                self.ball_dx *= 2.0 / spd
                self.ball_dy *= 2.0 / spd
            ny = float(self.paddle_y - 1)
        if ny >= self.area_h - 2:
            self.lives -= 1
            if self.lives <= 0:
                self.game_over = True
                return
            self._reset_ball()
            return

        br = int(ny) - self.brick_start_y
        if 0 <= br < self.brick_rows:
            bc = (int(nx) - self.brick_off_x) // self.brick_w
            if 0 <= bc < self.bricks_per_row and (br, bc) in self.bricks:
                del self.bricks[(br, bc)]
                self.ball_dy = -self.ball_dy
                self.score += (self.brick_rows - br) * 10
        self.ball_x, self.ball_y = nx, ny
        if not self.bricks:
            self.won = True
            self.game_over = True

    def _reset_ball(self):
        self.ball_moving = False
        self.ball_x = float(self.paddle_x + self.paddle_w // 2)
        self.ball_y = float(self.paddle_y - 1)

    def draw(self):
        # Re-center each frame (never negative) so resize/resume stays on-screen.
        self.area_x = max(0, (self.w - self.area_w) // 2)
        self.area_y = max(0, (self.h - self.area_h) // 2)
        ax, ay = self.area_x, self.area_y
        self.draw_box(ay, ax, self.area_h, self.area_w)
        hearts = '*' * self.lives
        self.safe_addstr(ay, ax + 2,
                         f' BREAKOUT  Score:{self.score}  Lives:{hearts} ',
                         curses.A_BOLD)
        for (r, c), color in self.bricks.items():
            self.safe_addstr(ay + self.brick_start_y + r,
                             ax + self.brick_off_x + c * self.brick_w, '[##]',
                             curses.color_pair(color) | curses.A_BOLD)
        self.safe_addstr(ay + self.paddle_y, ax + self.paddle_x,
                         '=' * self.paddle_w,
                         curses.color_pair(7) | curses.A_BOLD)
        self.safe_addstr(ay + int(self.ball_y), ax + int(self.ball_x), 'O',
                         curses.color_pair(3) | curses.A_BOLD)
        if not self.ball_moving:
            self.center_text(ay + self.area_h // 2,
                             ' Press SPACE to launch ball ',
                             curses.color_pair(4) | curses.A_REVERSE)
        self.safe_addstr(ay + self.area_h, ax,
                         ' A/D:Move  Space:Launch  ?:Help  ESC:Quit ',
                         curses.color_pair(4))

    def get_controls(self):
        return [('A/D', 'Move paddle'), ('Space', 'Launch ball'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        total = self.brick_rows * self.bricks_per_row
        broken = total - len(self.bricks)
        return [('Bricks', f'{broken}/{total}'), ('Lives left', self.lives)]


# ─── Space Shooter ──────────────────────────────────────────────────────────

class ShooterGame(Game):
    name = "shooter"
    min_h = 20
    min_w = 40
    supports_difficulty = True

    _ENEMY_ART = {'basic': '<V>', 'zigzag': '<W>', 'diver': '<X>', 'tank': '[=]'}
    _BOSS_ART = [' [===] ', '/|||||\\', ' \\___/ ']

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            for k, v in saved.items():
                setattr(self, k, v)
            return
        diff = self.difficulty
        self.lives = {'easy': 5, 'medium': 3, 'hard': 2}[diff]
        self.enemy_speed = {'easy': 0.5, 'medium': 0.8, 'hard': 1.2}[diff]
        self.spawn_rate = {'easy': 25, 'medium': 18, 'hard': 12}[diff]
        self.boss_fire_rate = {'easy': 20, 'medium': 12, 'hard': 7}[diff]
        self.player_x = self.w // 2
        self.score = 0
        self.wave = 1
        self.kills = 0
        self.kills_needed = 10
        self.frame = 0
        self.spawn_timer = 20
        self.bullets = []
        self.enemy_bullets = []
        self.enemies = []
        self.particles = []
        self.powerups = []
        self.spread = 0
        self.shield = False
        self.speed_boost = 0
        self.boss = None
        self.wave_msg_timer = 0

    def get_timeout(self):
        return 50

    def get_controls(self):
        return [('A/D', 'Move ship'), ('Space', 'Fire'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Wave', self.wave), ('Kills', self.kills)]

    def get_save_data(self):
        return {
            'difficulty': self.difficulty,
            'lives': self.lives, 'enemy_speed': self.enemy_speed,
            'spawn_rate': self.spawn_rate, 'boss_fire_rate': self.boss_fire_rate,
            'player_x': self.player_x, 'score': self.score,
            'wave': self.wave, 'kills': self.kills,
            'kills_needed': self.kills_needed, 'frame': self.frame,
            'spawn_timer': self.spawn_timer,
            'bullets': self.bullets, 'enemy_bullets': self.enemy_bullets,
            'enemies': self.enemies, 'particles': self.particles,
            'powerups': self.powerups,
            'spread': self.spread, 'shield': self.shield,
            'speed_boost': self.speed_boost, 'boss': self.boss,
            'wave_msg_timer': self.wave_msg_timer,
        }

    def handle_input(self, key):
        speed = 3 if self.speed_boost > 0 else 2
        if key == curses.KEY_LEFT or key == ord('a'):
            self.player_x = max(2, self.player_x - speed)
        elif key == curses.KEY_RIGHT or key == ord('d'):
            self.player_x = min(self.w - 2, self.player_x + speed)
        elif key == ord(' '):
            self._fire()

    def _fire(self):
        by = self.h - 4
        self.bullets.append({'x': self.player_x, 'y': by})
        if self.spread > 0:
            self.bullets.append({'x': self.player_x - 2, 'y': by + 1})
            self.bullets.append({'x': self.player_x + 2, 'y': by + 1})

    def _spawn_enemy(self):
        if self.boss or self.w < 9:
            return  # randint(3, w-6) needs w >= 9; bail on ultra-narrow screens
        types = ['basic'] * 50 + ['zigzag'] * 25 + ['diver'] * 15 + ['tank'] * 10
        etype = random.choice(types)
        hp = 3 if etype == 'tank' else 1
        x = random.randint(3, max(3, self.w - 6))
        self.enemies.append({
            'x': x, 'base_x': x, 'y': 2,
            'type': etype, 'hp': hp, 'frame': 0,
        })

    def _spawn_boss(self):
        self.boss = {
            'x': self.w // 2 - 3, 'y': 2,
            'hp': 10 + self.wave * 5,
            'max_hp': 10 + self.wave * 5,
            'fire_timer': self.boss_fire_rate, 'dir': 1,
        }

    def _add_particles(self, x, y, count=3):
        for _ in range(count):
            self.particles.append({
                'x': x + random.randint(-1, 1),
                'y': y + random.randint(-1, 1),
                'ch': random.choice(['*', '+', '.']),
                'ttl': random.randint(2, 5),
            })

    def update(self):
        self.frame += 1
        if self.speed_boost > 0:
            self.speed_boost -= 1
        if self.spread > 0:
            self.spread -= 1
        if self.wave_msg_timer > 0:
            self.wave_msg_timer -= 1

        # Move bullets
        self.bullets = [{'x': b['x'], 'y': b['y'] - 1}
                        for b in self.bullets if b['y'] > 0]
        self.enemy_bullets = [{'x': b['x'], 'y': b['y'] + 1}
                              for b in self.enemy_bullets if b['y'] < self.h]

        # Move enemies
        for e in self.enemies:
            e['frame'] += 1
            if e['type'] == 'basic':
                e['y'] += self.enemy_speed
            elif e['type'] == 'zigzag':
                e['y'] += self.enemy_speed
                offset = abs((e['frame'] % 20) - 10) - 5
                e['x'] = e['base_x'] + offset
                e['x'] = max(1, min(self.w - 4, e['x']))
            elif e['type'] == 'diver':
                e['y'] += self.enemy_speed * 1.5
                if e['x'] < self.player_x:
                    e['x'] += 1
                elif e['x'] > self.player_x:
                    e['x'] -= 1
            elif e['type'] == 'tank':
                e['y'] += self.enemy_speed * 0.6
        self.enemies = [e for e in self.enemies if e['y'] < self.h - 2]

        # Boss movement and shooting
        if self.boss:
            b = self.boss
            b['x'] += b['dir']
            if b['x'] <= 1:
                b['dir'] = 1
            elif b['x'] >= self.w - 8:
                b['dir'] = -1
            b['fire_timer'] -= 1
            if b['fire_timer'] <= 0:
                b['fire_timer'] = self.boss_fire_rate
                self.enemy_bullets.append({'x': b['x'] + 3, 'y': b['y'] + 3})

        # Player bullets hit enemies/boss
        new_bullets = []
        for b in self.bullets:
            hit = False
            if self.boss:
                bx, by = self.boss['x'], self.boss['y']
                if by <= b['y'] <= by + 2 and bx <= b['x'] <= bx + 6:
                    self.boss['hp'] -= 1
                    self._add_particles(b['x'], b['y'])
                    if self.boss['hp'] <= 0:
                        self._add_particles(bx + 3, by + 1, 8)
                        self.score += 500
                        self.boss = None
                        self.wave += 1
                        self.kills = 0
                        self.kills_needed = 10 + self.wave * 2
                        self.wave_msg_timer = 30
                    hit = True
            if not hit:
                for e in self.enemies:
                    art_w = len(self._ENEMY_ART[e['type']])
                    if (abs(b['y'] - int(e['y'])) <= 1 and
                            e['x'] <= b['x'] <= e['x'] + art_w - 1):
                        e['hp'] -= 1
                        if e['hp'] <= 0:
                            self._add_particles(e['x'] + art_w // 2, int(e['y']))
                            self.kills += 1
                            pts = {'basic': 10, 'zigzag': 20,
                                   'diver': 25, 'tank': 50}
                            self.score += pts.get(e['type'], 10)
                            if random.random() < 0.1:
                                ptype = random.choice(['S', 'O', '>'])
                                self.powerups.append({
                                    'x': e['x'], 'y': int(e['y']),
                                    'type': ptype,
                                })
                        hit = True
                        break
            if not hit:
                new_bullets.append(b)
        self.bullets = new_bullets
        self.enemies = [e for e in self.enemies if e['hp'] > 0]

        # Enemy bullets hit player
        px, py = self.player_x, self.h - 3
        new_eb = []
        for b in self.enemy_bullets:
            if abs(b['x'] - px) <= 1 and abs(b['y'] - py) <= 1:
                if self.shield:
                    self.shield = False
                else:
                    self.lives -= 1
                    self._add_particles(px, py, 5)
                    if self.lives <= 0:
                        self.game_over = True
                        return
            else:
                new_eb.append(b)
        self.enemy_bullets = new_eb

        # Enemies collide with player
        for e in self.enemies:
            art_w = len(self._ENEMY_ART[e['type']])
            if (int(e['y']) >= self.h - 4 and
                    abs(e['x'] + art_w // 2 - px) <= 2):
                if self.shield:
                    self.shield = False
                else:
                    self.lives -= 1
                    self._add_particles(px, py, 5)
                    if self.lives <= 0:
                        self.game_over = True
                        return
                e['hp'] = 0
        self.enemies = [e for e in self.enemies if e['hp'] > 0]

        # Move and collect power-ups
        if self.frame % 2 == 0:
            for p in self.powerups:
                p['y'] += 1
        new_pups = []
        for p in self.powerups:
            if p['y'] >= self.h:
                continue
            if abs(p['x'] - px) <= 2 and abs(p['y'] - py) <= 1:
                if p['type'] == 'S':
                    self.spread = 200
                elif p['type'] == 'O':
                    self.shield = True
                elif p['type'] == '>':
                    self.speed_boost = 200
            else:
                new_pups.append(p)
        self.powerups = new_pups

        # Particles decay
        self.particles = [{'x': p['x'], 'y': p['y'], 'ch': p['ch'],
                          'ttl': p['ttl'] - 1}
                         for p in self.particles if p['ttl'] > 1]

        # Spawn enemies
        self.spawn_timer -= 1
        if self.spawn_timer <= 0 and not self.boss:
            self._spawn_enemy()
            self.spawn_timer = self.spawn_rate

        # Wave progression
        if not self.boss and self.kills >= self.kills_needed:
            self.wave += 1
            self.kills = 0
            self.kills_needed = 10 + self.wave * 2
            self.wave_msg_timer = 30
            if self.wave % 5 == 0:
                self._spawn_boss()

    def draw(self):
        # Header
        self.safe_addstr(0, 2, 'SPACE SHOOTER', curses.A_BOLD)
        info = f'Score:{self.score}  Wave:{self.wave}  '
        self.safe_addstr(0, 17, info,
                         curses.color_pair(3) | curses.A_BOLD)
        lives_s = '*' * self.lives
        self.safe_addstr(0, self.w - self.lives - 2, lives_s,
                         curses.color_pair(2) | curses.A_BOLD)

        # Wave announcement
        if self.wave_msg_timer > 0:
            self.center_text(self.h // 3, f'  WAVE {self.wave}  ',
                             curses.A_BOLD | curses.A_REVERSE)

        # Enemies
        for e in self.enemies:
            art = self._ENEMY_ART[e['type']]
            color = {'basic': 2, 'zigzag': 5, 'diver': 3, 'tank': 6}
            self.safe_addstr(int(e['y']), int(e['x']), art,
                             curses.color_pair(color.get(e['type'], 7))
                             | curses.A_BOLD)

        # Boss
        if self.boss:
            bx, by = self.boss['x'], self.boss['y']
            for i, line in enumerate(self._BOSS_ART):
                self.safe_addstr(by + i, bx, line,
                                 curses.color_pair(2) | curses.A_BOLD)
            hp_w = min(20, self.w - 10)
            filled = max(0, int(hp_w * self.boss['hp'] / self.boss['max_hp']))
            bar = '#' * filled + '-' * (hp_w - filled)
            self.center_text(by + 4, f'[{bar}]', curses.color_pair(2))

        # Bullets
        for b in self.bullets:
            self.safe_addstr(b['y'], b['x'], '|',
                             curses.color_pair(3) | curses.A_BOLD)
        for b in self.enemy_bullets:
            self.safe_addstr(b['y'], b['x'], '.',
                             curses.color_pair(2) | curses.A_BOLD)

        # Power-ups
        for p in self.powerups:
            self.safe_addstr(p['y'], p['x'], p['type'],
                             curses.color_pair(1) | curses.A_BOLD
                             | curses.A_REVERSE)

        # Particles
        for p in self.particles:
            self.safe_addstr(p['y'], p['x'], p['ch'],
                             curses.color_pair(3))

        # Player ship
        self.safe_addstr(self.h - 3, self.player_x - 1, '/A\\',
                         curses.color_pair(1) | curses.A_BOLD)
        if self.shield:
            self.safe_addstr(self.h - 2, self.player_x - 2, '(===)',
                             curses.color_pair(4) | curses.A_BOLD)

        # Status bar
        parts = []
        if self.spread > 0:
            parts.append('SPREAD')
        if self.shield:
            parts.append('SHIELD')
        if self.speed_boost > 0:
            parts.append('SPEED')
        if parts:
            self.safe_addstr(self.h - 1, 2, ' '.join(parts),
                             curses.color_pair(1) | curses.A_BOLD)
        self.safe_addstr(self.h - 1, self.w - 28,
                         'A/D:Move Space:Fire ?:Help',
                         curses.color_pair(4))


# ─── Pong ───────────────────────────────────────────────────────────────────

class PongGame(Game):
    name = "pong"
    min_h = 18
    min_w = 40
    supports_difficulty = True

    PADDLE_H = 5
    WIN_SCORE = 11

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            for k, v in saved.items():
                setattr(self, k, v)
            return
        diff = self.difficulty
        # Values chosen so the paddle step (max(1, round(ai_speed*2))) is a
        # distinct 1 / 2 / 3 cells per move across the three difficulties.
        self.ai_speed = {'easy': 0.5, 'medium': 1.0, 'hard': 1.5}[diff]
        self.ai_error = {'easy': 3.0, 'medium': 1.5, 'hard': 0.5}[diff]
        self.ai_react = {'easy': 8, 'medium': 4, 'hard': 2}[diff]
        self.player_y = self.h // 2 - self.PADDLE_H // 2
        self.ai_y = self.h // 2 - self.PADDLE_H // 2
        self.ai_target = float(self.h // 2)
        self.player_score = 0
        self.ai_score = 0
        self.score = 0
        self.ball_x = float(self.w // 2)
        self.ball_y = float(self.h // 2)
        self.ball_dx = 0.0
        self.ball_dy = 0.0
        self.serving = True
        self.server = 'player'
        self.rally = 0
        self.frame = 0

    def get_timeout(self):
        return 40

    def get_controls(self):
        return [('W/S', 'Move paddle'), ('Space', 'Serve'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('You', self.player_score), ('AI', self.ai_score)]

    def get_save_data(self):
        return {
            'difficulty': self.difficulty,
            'ai_speed': self.ai_speed, 'ai_error': self.ai_error,
            'ai_react': self.ai_react,
            'player_y': self.player_y, 'ai_y': self.ai_y,
            'ai_target': self.ai_target,
            'player_score': self.player_score, 'ai_score': self.ai_score,
            'score': self.score,
            'ball_x': self.ball_x, 'ball_y': self.ball_y,
            'ball_dx': self.ball_dx, 'ball_dy': self.ball_dy,
            'serving': self.serving, 'server': self.server,
            'rally': self.rally, 'frame': self.frame,
        }

    def _serve(self):
        self.ball_x = float(self.w // 2)
        self.ball_y = float(self.h // 2)
        dx = 1.0 if self.server == 'player' else -1.0
        self.ball_dx = dx
        self.ball_dy = random.choice([-0.5, 0.5])
        self.serving = False
        self.rally = 0

    def handle_input(self, key):
        if key == ord('w') or key == curses.KEY_UP:
            self.player_y = max(2, self.player_y - 2)
        elif key == ord('s') or key == curses.KEY_DOWN:
            self.player_y = min(self.h - self.PADDLE_H - 2, self.player_y + 2)
        elif key == ord(' ') and self.serving:
            self._serve()

    def update(self):
        self.frame += 1
        if self.serving:
            return

        self.ball_x += self.ball_dx
        self.ball_y += self.ball_dy

        # Wall bounce (top/bottom)
        if self.ball_y <= 2:
            self.ball_y = 2.0
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= self.h - 3:
            self.ball_y = float(self.h - 3)
            self.ball_dy = -abs(self.ball_dy)

        # Player paddle (left, x=4)
        if (self.ball_dx < 0 and 3 <= int(self.ball_x) <= 5 and
                self.player_y - 1 <= int(self.ball_y) <= self.player_y + self.PADDLE_H):
            self.ball_dx = abs(self.ball_dx)
            hit = (self.ball_y - self.player_y) / self.PADDLE_H
            self.ball_dy = (hit - 0.5) * 2.0
            self.rally += 1
            self._speed_up()

        # AI paddle (right, x=w-5)
        ai_x = self.w - 5
        if (self.ball_dx > 0 and ai_x - 1 <= int(self.ball_x) <= ai_x + 1 and
                self.ai_y - 1 <= int(self.ball_y) <= self.ai_y + self.PADDLE_H):
            self.ball_dx = -abs(self.ball_dx)
            hit = (self.ball_y - self.ai_y) / self.PADDLE_H
            self.ball_dy = (hit - 0.5) * 2.0
            self.rally += 1
            self._speed_up()

        # Scoring
        if self.ball_x <= 1:
            self.ai_score += 1
            self.server = 'player'
            self.serving = True
            self._check_win()
        elif self.ball_x >= self.w - 2:
            self.player_score += 1
            self.score = self.player_score
            self.server = 'ai'
            self.serving = True
            self._check_win()

        # AI target prediction
        if self.frame % self.ai_react == 0:
            if self.ball_dx > 0:
                dist = max(1.0, ai_x - self.ball_x)
                pred_y = self.ball_y + self.ball_dy * (dist / max(0.1, abs(self.ball_dx)))
                pred_y += random.uniform(-self.ai_error, self.ai_error)
                self.ai_target = max(2.0, min(float(self.h - 3), pred_y))
            else:
                self.ai_target = float(self.h // 2)

        # AI movement
        ai_center = self.ai_y + self.PADDLE_H / 2.0
        if ai_center < self.ai_target - 0.5:
            move = max(1, round(self.ai_speed * 2))
            self.ai_y = min(self.h - self.PADDLE_H - 2, self.ai_y + move)
        elif ai_center > self.ai_target + 0.5:
            move = max(1, round(self.ai_speed * 2))
            self.ai_y = max(2, self.ai_y - move)

    def _speed_up(self):
        speed = (self.ball_dx ** 2 + self.ball_dy ** 2) ** 0.5
        if speed < 2.5:
            self.ball_dx *= 1.05
            self.ball_dy *= 1.05

    def _check_win(self):
        if self.player_score >= self.WIN_SCORE:
            self.won = True
            self.game_over = True
        elif self.ai_score >= self.WIN_SCORE:
            self.game_over = True

    def draw(self):
        # Title
        self.safe_addstr(0, 2, 'PONG', curses.A_BOLD)

        # Scores
        score_s = f'{self.player_score}    {self.ai_score}'
        self.center_text(1, score_s, curses.A_BOLD)
        sc_x = max(0, (self.w - len(score_s)) // 2)
        self.safe_addstr(1, max(0, sc_x - 4), 'YOU',
                         curses.color_pair(1))
        self.safe_addstr(1, min(self.w - 3, sc_x + len(score_s) + 1), 'CPU',
                         curses.color_pair(2))

        # Center net
        mid_x = self.w // 2
        for y in range(2, self.h - 1):
            if y % 2 == 0:
                self.safe_addstr(y, mid_x, ':', curses.color_pair(4))

        # Player paddle (left)
        for i in range(self.PADDLE_H):
            self.safe_addstr(self.player_y + i, 4, '|',
                             curses.color_pair(1) | curses.A_BOLD)

        # AI paddle (right)
        for i in range(self.PADDLE_H):
            self.safe_addstr(self.ai_y + i, self.w - 5, '|',
                             curses.color_pair(2) | curses.A_BOLD)

        # Ball
        if not self.serving:
            self.safe_addstr(int(self.ball_y), int(self.ball_x), 'O',
                             curses.color_pair(3) | curses.A_BOLD)
        else:
            self.center_text(self.h // 2, ' Press SPACE to serve ',
                             curses.color_pair(4) | curses.A_REVERSE)

        # Controls
        self.safe_addstr(self.h - 1, 2,
                         'W/S:Move  Space:Serve  ?:Help',
                         curses.color_pair(4))


# ─── Flappy Bird ────────────────────────────────────────────────────────────

class FlappyGame(Game):
    name = "flappy"
    min_h = 20
    min_w = 50

    GRAVITY = 0.3
    JUMP_VEL = -1.5
    PIPE_GAP = 6
    PIPE_WIDTH = 3
    PIPE_INTERVAL = 35
    BIRD_X = 10

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.bird_y = saved['bird_y']
            self.bird_vel = saved['bird_vel']
            self.pipes = saved['pipes']
            self.score = saved['score']
            self.frame = saved['frame']
            self.speed = saved['speed']
            self.pipe_timer = saved['pipe_timer']
            # A shorter resumed terminal could leave the bird at/below the new
            # ground; clamp so resuming doesn't instantly end the run.
            self.bird_y = max(1.0, min(self.bird_y, self.h - 3.0))
            return
        self.bird_y = float(self.h // 2)
        self.bird_vel = 0.0
        self.pipes = []
        self.score = 0
        self.frame = 0
        self.speed = 1.0
        self.pipe_timer = self.PIPE_INTERVAL

    def get_timeout(self):
        return 50

    def handle_input(self, key):
        if key in (ord(' '), ord('w'), curses.KEY_UP):
            self.bird_vel = self.JUMP_VEL

    def update(self):
        self.frame += 1
        self.speed = min(3.0, 1.0 + self.score * 0.04)

        self.bird_vel += self.GRAVITY
        self.bird_y += self.bird_vel

        ground_y = self.h - 2
        if self.bird_y < 1 or self.bird_y >= ground_y:
            self.game_over = True
            return

        self.pipe_timer -= 1
        if self.pipe_timer <= 0:
            max_gap = max(4, ground_y - self.PIPE_GAP - 2)
            gap_start = random.randint(2, max_gap)
            self.pipes.append({'x': float(self.w - 1), 'gap_top': gap_start,
                               'scored': False})
            self.pipe_timer = max(20, int(self.PIPE_INTERVAL / self.speed))

        bird_row = int(self.bird_y)
        for p in self.pipes:
            p['x'] -= self.speed
            px = int(p['x'])
            gap_bot = p['gap_top'] + self.PIPE_GAP
            if px <= self.BIRD_X < px + self.PIPE_WIDTH:
                if bird_row < p['gap_top'] or bird_row >= gap_bot:
                    self.game_over = True
                    return
            if not p['scored'] and p['x'] + self.PIPE_WIDTH < self.BIRD_X:
                p['scored'] = True
                self.score += 1

        self.pipes = [p for p in self.pipes if p['x'] + self.PIPE_WIDTH > 0]

    def draw(self):
        ground_y = self.h - 2
        hi = load_high_score(self.name)
        self.safe_addstr(0, 2, 'FLAPPY BIRD', curses.A_BOLD)
        sc_str = f'Score: {self.score}  HI: {max(self.score, hi)}'
        self.safe_addstr(0, self.w - len(sc_str) - 2, sc_str,
                         curses.color_pair(3) | curses.A_BOLD)

        for p in self.pipes:
            px = int(p['x'])
            gap_top = p['gap_top']
            gap_bot = gap_top + self.PIPE_GAP
            for col in range(self.PIPE_WIDTH):
                cx = px + col
                if cx < 0 or cx >= self.w:
                    continue
                for row in range(1, gap_top):
                    ch = '+' if col in (0, self.PIPE_WIDTH - 1) and row == gap_top - 1 else '|'
                    self.safe_addstr(row, cx, ch,
                                     curses.color_pair(1) | curses.A_BOLD)
                for row in range(gap_bot, ground_y):
                    ch = '+' if col in (0, self.PIPE_WIDTH - 1) and row == gap_bot else '|'
                    self.safe_addstr(row, cx, ch,
                                     curses.color_pair(1) | curses.A_BOLD)

        self.safe_addstr(ground_y, 0, '─' * self.w, curses.color_pair(4))
        bird_row = int(self.bird_y)
        bird_ch = '>' if self.bird_vel <= 0 else 'v'
        self.safe_addstr(bird_row, self.BIRD_X, bird_ch,
                         curses.color_pair(3) | curses.A_BOLD)
        self.safe_addstr(self.h - 1, 2,
                         'W/Space: Flap  P: Pause  ?: Help  ESC: Quit',
                         curses.color_pair(4))

    def get_controls(self):
        return [('W/Space', 'Flap'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Speed', f'{self.speed:.1f}x')]

    def get_save_data(self):
        return {'bird_y': self.bird_y, 'bird_vel': self.bird_vel,
                'pipes': self.pipes, 'score': self.score, 'frame': self.frame,
                'speed': self.speed, 'pipe_timer': self.pipe_timer}


# ─── Minesweeper (Interactive) ──────────────────────────────────────────────

class MinesweeperGame(Game):
    name = "minesweeper_i"
    min_h = 22
    min_w = 40
    supports_difficulty = True

    _NUM_COLORS = {1: 6, 2: 1, 3: 2, 4: 5, 5: 3, 6: 4, 7: 7, 8: 7}

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.rows = saved['rows']
            self.cols = saved['cols']
            self.num_mines = saved['mines']
            self.grid = saved['grid']
            self.revealed = saved['revealed']
            self.flagged = saved['flagged']
            self.cur_r = saved['cur_r']
            self.cur_c = saved['cur_c']
            self.score = saved['score']
            self.frame = saved['frame']
            self.first_reveal = saved['first_reveal']
            self.difficulty = saved.get('difficulty', self.difficulty)
            self._fit_bounds()
            return
        cfg = {'easy': (9, 9, 10), 'medium': (16, 16, 40), 'hard': (16, 30, 99)}
        self.rows, self.cols, self.num_mines = cfg.get(self.difficulty, (9, 9, 10))
        self.cur_r = self.rows // 2
        self.cur_c = self.cols // 2
        self.score = 0
        self.frame = 0
        self.first_reveal = True
        self.grid = [[0] * self.cols for _ in range(self.rows)]
        self.revealed = [[False] * self.cols for _ in range(self.rows)]
        self.flagged = [[False] * self.cols for _ in range(self.rows)]
        self._fit_bounds()

    def _fit_bounds(self):
        # The hard board is 30 cols = 60 render columns, far wider than the
        # class min_w=40, so gate on the real board size to avoid clipping.
        self.min_w = max(40, self.cols * 2 + 4)
        self.min_h = max(22, self.rows + 6)

    def _place_mines(self, safe_r, safe_c):
        forbidden = set()
        for dr in range(-1, 2):
            for dc in range(-1, 2):
                nr, nc = safe_r + dr, safe_c + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    forbidden.add((nr, nc))
        candidates = [(r, c) for r in range(self.rows) for c in range(self.cols)
                      if (r, c) not in forbidden]
        mines = random.sample(candidates, min(self.num_mines, len(candidates)))
        for r, c in mines:
            self.grid[r][c] = -1
        for r in range(self.rows):
            for c in range(self.cols):
                if self.grid[r][c] == -1:
                    continue
                self.grid[r][c] = sum(
                    1 for dr in range(-1, 2) for dc in range(-1, 2)
                    if (dr or dc) and 0 <= r + dr < self.rows
                    and 0 <= c + dc < self.cols and self.grid[r + dr][c + dc] == -1)

    def _flood_reveal(self, r, c):
        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if cr < 0 or cr >= self.rows or cc < 0 or cc >= self.cols:
                continue
            if self.revealed[cr][cc] or self.flagged[cr][cc]:
                continue
            self.revealed[cr][cc] = True
            if self.grid[cr][cc] == -1:
                continue
            self.score += 1
            if self.grid[cr][cc] == 0:
                for dr in range(-1, 2):
                    for dc in range(-1, 2):
                        if dr or dc:
                            stack.append((cr + dr, cc + dc))

    def _reveal_cell(self, r, c):
        if self.revealed[r][c] or self.flagged[r][c]:
            return
        if self.first_reveal:
            self.first_reveal = False
            self._place_mines(r, c)
        if self.grid[r][c] == -1:
            self.revealed[r][c] = True
            self.game_over = True
            return
        self._flood_reveal(r, c)
        unrevealed_safe = sum(
            1 for rr in range(self.rows) for cc in range(self.cols)
            if not self.revealed[rr][cc] and self.grid[rr][cc] != -1)
        if unrevealed_safe == 0:
            self.won = True
            self.game_over = True

    def get_timeout(self):
        return 200

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self.cur_r = max(0, self.cur_r - 1)
        elif key in (curses.KEY_DOWN, ord('s')):
            self.cur_r = min(self.rows - 1, self.cur_r + 1)
        elif key in (curses.KEY_LEFT, ord('a')):
            self.cur_c = max(0, self.cur_c - 1)
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.cur_c = min(self.cols - 1, self.cur_c + 1)
        elif key == ord(' '):
            self._reveal_cell(self.cur_r, self.cur_c)
        elif key in (ord('f'), ord('F')):
            if not self.revealed[self.cur_r][self.cur_c]:
                self.flagged[self.cur_r][self.cur_c] = \
                    not self.flagged[self.cur_r][self.cur_c]

    def update(self):
        if not self.game_over:
            self.frame += 1

    def draw(self):
        show_mines = self.game_over
        cell_w = 2
        grid_w = self.cols * cell_w
        sx = max(1, (self.w - grid_w) // 2)
        sy = max(2, (self.h - self.rows - 4) // 2)

        flags = sum(self.flagged[r][c]
                    for r in range(self.rows) for c in range(self.cols))
        elapsed = self.frame // 5
        header = f' MINESWEEPER  Mines:{self.num_mines - flags}  Time:{elapsed}s '
        self.safe_addstr(sy - 2, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        diff_label = f'[{self.difficulty.upper()} {self.rows}x{self.cols}]'
        self.safe_addstr(sy - 1, max(0, (self.w - len(diff_label)) // 2),
                         diff_label, curses.color_pair(4))

        for r in range(self.rows):
            for c in range(self.cols):
                is_cursor = (r == self.cur_r and c == self.cur_c)
                rev = curses.A_REVERSE if is_cursor else 0
                if self.flagged[r][c] and not self.revealed[r][c]:
                    ch, attr = 'F', curses.color_pair(2) | curses.A_BOLD | rev
                elif not self.revealed[r][c]:
                    if show_mines and self.grid[r][c] == -1:
                        ch, attr = '*', curses.color_pair(2) | curses.A_BOLD | rev
                    else:
                        ch, attr = '#', curses.color_pair(7) | rev
                else:
                    v = self.grid[r][c]
                    if v == -1:
                        ch, attr = '*', curses.color_pair(2) | curses.A_BOLD | rev
                    elif v == 0:
                        ch, attr = '.', curses.color_pair(7) | rev
                    else:
                        pair = self._NUM_COLORS.get(v, 7)
                        ch, attr = str(v), curses.color_pair(pair) | curses.A_BOLD | rev
                self.safe_addstr(sy + r, sx + c * cell_w, ch, attr)

        hint = 'WASD:Move  Space:Reveal  F:Flag  ?:Help  ESC:Quit'
        self.safe_addstr(sy + self.rows + 1,
                         max(0, (self.w - len(hint)) // 2),
                         hint, curses.color_pair(4))

    def get_controls(self):
        return [('WASD/Arrows', 'Move cursor'), ('Space', 'Reveal cell'),
                ('F', 'Toggle flag'), ('P', 'Pause'), ('ESC', 'Quit / save')]

    def get_stats(self):
        elapsed = self.frame // 5
        flags = sum(self.flagged[r][c]
                    for r in range(self.rows) for c in range(self.cols))
        return [('Time', f'{elapsed}s'), ('Flags', f'{flags}/{self.num_mines}'),
                ('Cells', self.score)]

    def get_save_data(self):
        return {'rows': self.rows, 'cols': self.cols, 'mines': self.num_mines,
                'grid': self.grid, 'revealed': self.revealed,
                'flagged': self.flagged, 'cur_r': self.cur_r, 'cur_c': self.cur_c,
                'score': self.score, 'frame': self.frame,
                'first_reveal': self.first_reveal,
                'difficulty': self.difficulty}


# ─── Pac-Man ────────────────────────────────────────────────────────────────

class PacManGame(Game):
    name = "pacman"
    min_h = 24
    min_w = 30

    _MAZE = [
        "###########################",
        "#............#............#",
        "#.####.#####.#.#####.####.#",
        "#O####.#####.#.#####.####O#",
        "#.........................#",
        "#.####.##.#######.##.####.#",
        "#......##....#....##......#",
        "######.#####   #####.######",
        "     #.#           #.#     ",
        "######.# ####-#### #.######",
        "      .  #       #  .      ",
        "######.# ######### #.######",
        "     #.#           #.#     ",
        "######.# ######### #.######",
        "#............#............#",
        "#.####.#####.#.#####.####.#",
        "#O..##.......C.......##..O#",
        "###.##.##.#######.##.##.###",
        "#......##....#....##......#",
        "#.##########.#.##########.#",
        "#.........................#",
        "###########################",
    ]

    _GHOST_CONFIGS = [
        ('Blinky', 2, 'chase'),
        ('Pinky', 5, 'ahead'),
        ('Inky', 4, 'random'),
        ('Clyde', 3, 'clyde'),
    ]

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.maze = saved['maze']
            self.score = saved['score']
            self.lives = saved['lives']
            self.pac_y = saved['pac_y']
            self.pac_x = saved['pac_x']
            self.pac_dir = tuple(saved['pac_dir'])
            self.next_dir = tuple(saved['next_dir'])
            self.ghosts = [dict(g) for g in saved['ghosts']]
            for g in self.ghosts:
                g['dir'] = tuple(g['dir'])
            self.frightened = saved['frightened']
            self.frightened_timer = saved['frightened_timer']
            self.frame = saved['frame']
            self.ghost_speed = saved['ghost_speed']
            self.dots_left = saved['dots_left']
            self._dying = saved.get('dying', 0)
            return

        self.maze = [list(row) for row in self._MAZE]
        self.score = 0
        self.lives = 3
        self._dying = 0
        self.frame = 0
        self.ghost_speed = 3
        self.frightened = False
        self.frightened_timer = 0
        self.dots_left = sum(1 for row in self.maze for c in row if c in ('.', 'O'))

        self.pac_y, self.pac_x = 16, 13
        for ry, row in enumerate(self.maze):
            for rx, ch in enumerate(row):
                if ch == 'C':
                    self.pac_y, self.pac_x = ry, rx
                    self.maze[ry][rx] = ' '
        self.pac_dir = (0, 0)
        self.next_dir = (0, 1)

        home_y, home_x = 10, 13
        self.ghosts = []
        offsets = [(0, 0), (0, -1), (0, 1), (0, 2)]
        for i, (gname, cpair, behavior) in enumerate(self._GHOST_CONFIGS):
            oy, ox = offsets[i]
            self.ghosts.append({'y': home_y + oy, 'x': home_x + ox,
                                'dir': (0, 1), 'color': cpair,
                                'behavior': behavior, 'name': gname,
                                'eaten': False})

    def _maze_rows(self):
        return len(self.maze)

    def _maze_cols(self):
        return len(self.maze[0]) if self.maze else 0

    def _is_wall(self, y, x):
        if y < 0 or y >= self._maze_rows() or x < 0 or x >= self._maze_cols():
            return True
        return self.maze[y][x] == '#'

    def _is_ghost_door(self, y, x):
        if y < 0 or y >= self._maze_rows() or x < 0 or x >= self._maze_cols():
            return False
        return self.maze[y][x] == '-'

    def _wrap_x(self, x):
        return x % self._maze_cols()

    def _try_move_pac(self, dy, dx):
        ny = self.pac_y + dy
        nx = self._wrap_x(self.pac_x + dx)
        if not self._is_wall(ny, nx) and not self._is_ghost_door(ny, nx):
            return ny, nx
        return None

    def get_timeout(self):
        return 80

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self.next_dir = (-1, 0)
        elif key in (curses.KEY_DOWN, ord('s')):
            self.next_dir = (1, 0)
        elif key in (curses.KEY_LEFT, ord('a')):
            self.next_dir = (0, -1)
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.next_dir = (0, 1)

    def _in_pen(self, y, x):
        """True while a ghost is still inside the ghost house (or on the door)."""
        return 9 <= y <= 10 and 9 <= x <= 17

    def _move_ghost(self, ghost):
        gy, gx = ghost['y'], ghost['x']
        gdir = ghost['dir']
        reverse = (-gdir[0], -gdir[1])
        in_pen = self._in_pen(gy, gx)

        # Frightened ghosts (that haven't been eaten) flee in a random direction.
        if self.frightened and not ghost['eaten']:
            dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
            random.shuffle(dirs)
            for d in dirs:
                if d == reverse:
                    continue
                ny, nx = gy + d[0], self._wrap_x(gx + d[1])
                if not self._is_wall(ny, nx):
                    ghost['dir'] = d
                    ghost['y'], ghost['x'] = ny, nx
                    return
            ny, nx = gy + reverse[0], self._wrap_x(gx + reverse[1])
            if not self._is_wall(ny, nx):
                ghost['dir'] = reverse
                ghost['y'], ghost['x'] = ny, nx
            return

        # Choose a target cell to steer toward.
        if ghost['eaten']:
            ty, tx = 10, 13                       # return home to the pen
        elif in_pen:
            ty, tx = 8, 13                         # head up and out through the door
        else:
            b = ghost['behavior']
            if b == 'chase':
                ty, tx = self.pac_y, self.pac_x
            elif b == 'ahead':
                ty = self.pac_y + self.pac_dir[0] * 4
                tx = self.pac_x + self.pac_dir[1] * 4
            elif b == 'clyde':
                dist = abs(gy - self.pac_y) + abs(gx - self.pac_x)
                ty, tx = (self.pac_y, self.pac_x) if dist > 8 \
                    else (self._maze_rows() - 2, 1)
            else:  # 'random' (Inky): wander, but no longer refuse the door
                dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
                random.shuffle(dirs)
                for d in dirs:
                    if d == reverse:
                        continue
                    ny, nx = gy + d[0], self._wrap_x(gx + d[1])
                    if not self._is_wall(ny, nx):
                        ghost['dir'] = d
                        ghost['y'], ghost['x'] = ny, nx
                        return
                ny, nx = gy + reverse[0], self._wrap_x(gx + reverse[1])
                if not self._is_wall(ny, nx):     # dead end: turn around
                    ghost['dir'] = reverse
                    ghost['y'], ghost['x'] = ny, nx
                return

        # Greedy distance-minimizing step. The door is passable only for ghosts
        # that are leaving the pen or returning home, so free ghosts can't
        # wander back inside.
        allow_door = ghost['eaten'] or in_pen
        best_dir, best_dist = None, 10 ** 9
        for d in [(-1, 0), (0, 1), (1, 0), (0, -1)]:
            if d == reverse and not ghost['eaten']:
                continue
            ny, nx = gy + d[0], self._wrap_x(gx + d[1])
            if self._is_wall(ny, nx):
                continue
            if self._is_ghost_door(ny, nx) and not allow_door:
                continue
            dist = abs(ny - ty) + abs(nx - tx)
            if dist < best_dist:
                best_dist, best_dir = dist, d

        # Reverse fallback: if the only open neighbor is behind us, turn around
        # instead of freezing (fixes ghosts stalling in pen dead-ends).
        if best_dir is None:
            ny, nx = gy + reverse[0], self._wrap_x(gx + reverse[1])
            if not self._is_wall(ny, nx) and \
                    (allow_door or not self._is_ghost_door(ny, nx)):
                best_dir = reverse

        if best_dir:
            ghost['dir'] = best_dir
            ghost['y'] += best_dir[0]
            ghost['x'] = self._wrap_x(ghost['x'] + best_dir[1])
            if ghost['eaten'] and ghost['y'] == 10 and ghost['x'] == 13:
                ghost['eaten'] = False

    def _reset_positions(self):
        self.pac_y, self.pac_x = 16, 13
        self.pac_dir = (0, 0)
        self.next_dir = (0, 1)
        self.frightened = False
        self.frightened_timer = 0
        home_y, home_x = 10, 13
        offsets = [(0, 0), (0, -1), (0, 1), (0, 2)]
        for i, ghost in enumerate(self.ghosts):
            oy, ox = offsets[i]
            ghost['y'] = home_y + oy
            ghost['x'] = home_x + ox
            ghost['dir'] = (0, 1)
            ghost['eaten'] = False

    def update(self):
        if self._dying > 0:
            self._dying -= 1
            if self._dying == 0:
                self.lives -= 1
                if self.lives <= 0:
                    self.game_over = True
                else:
                    self._reset_positions()
            return

        self.frame += 1

        moved = False
        pos = self._try_move_pac(*self.next_dir)
        if pos:
            self.pac_dir = self.next_dir
            self.pac_y, self.pac_x = pos
            moved = True
        else:
            pos = self._try_move_pac(*self.pac_dir)
            if pos:
                self.pac_y, self.pac_x = pos
                moved = True

        if moved:
            cell = self.maze[self.pac_y][self.pac_x]
            if cell == '.':
                self.maze[self.pac_y][self.pac_x] = ' '
                self.score += 10
                self.dots_left -= 1
            elif cell == 'O':
                self.maze[self.pac_y][self.pac_x] = ' '
                self.score += 50
                self.dots_left -= 1
                self.frightened = True
                self.frightened_timer = 30
                for ghost in self.ghosts:
                    if not ghost['eaten']:
                        ghost['dir'] = (-ghost['dir'][0], -ghost['dir'][1])

        if self.dots_left <= 0:
            self.game_over = True
            self.won = True
            return

        # Check after pac moves so walking into a ghost (or swapping cells with
        # one on the same frame) is not missed.
        if self._ghost_collision():
            return

        if self.frightened:
            self.frightened_timer -= 1
            if self.frightened_timer <= 0:
                self.frightened = False

        if self.frame % self.ghost_speed == 0:
            for ghost in self.ghosts:
                self._move_ghost(ghost)
            if self._ghost_collision():
                return

        if self.frame % 150 == 0 and self.ghost_speed > 1:
            self.ghost_speed = max(1, self.ghost_speed - 1)

    def _ghost_collision(self):
        """Resolve pac/ghost overlap. Returns True on a fatal (dying) hit."""
        for ghost in self.ghosts:
            if ghost['eaten']:
                continue
            if ghost['y'] == self.pac_y and ghost['x'] == self.pac_x:
                if self.frightened:
                    ghost['eaten'] = True
                    self.score += 200
                else:
                    self._dying = 20
                    return True
        return False

    def draw(self):
        maze_rows = self._maze_rows()
        maze_cols = self._maze_cols()
        off_y = max(1, (self.h - maze_rows - 3) // 2)
        off_x = max(0, (self.w - maze_cols) // 2)

        hi = load_high_score(self.name)
        header = f' PAC-MAN  Score:{self.score}  Hi:{hi}  Lives:{"C" * self.lives} '
        self.safe_addstr(off_y - 1, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD | curses.color_pair(3))

        for ry, row in enumerate(self.maze):
            for rx, ch in enumerate(row):
                sy, sx_pos = off_y + ry, off_x + rx
                if ch == '#':
                    self.safe_addstr(sy, sx_pos, '#',
                                     curses.color_pair(6) | curses.A_BOLD)
                elif ch == '.':
                    self.safe_addstr(sy, sx_pos, '.', curses.color_pair(7))
                elif ch == 'O':
                    self.safe_addstr(sy, sx_pos, 'O',
                                     curses.color_pair(3) | curses.A_BOLD)
                elif ch == '-':
                    self.safe_addstr(sy, sx_pos, '-', curses.color_pair(5))

        if self._dying == 0 or (self._dying % 4 < 2):
            self.safe_addstr(off_y + self.pac_y, off_x + self.pac_x, 'C',
                             curses.color_pair(3) | curses.A_BOLD)

        for ghost in self.ghosts:
            gy, gx = off_y + ghost['y'], off_x + ghost['x']
            if ghost['eaten']:
                ch, attr = 'x', curses.color_pair(7)
            elif self.frightened:
                blink = self.frightened_timer <= 8 and self.frame % 4 >= 2
                attr = curses.color_pair(7 if blink else 6) | curses.A_BOLD
                ch = 'M'
            else:
                ch, attr = 'M', curses.color_pair(ghost['color']) | curses.A_BOLD
            self.safe_addstr(gy, gx, ch, attr)

        self.safe_addstr(off_y + maze_rows, max(0, (self.w - 44) // 2),
                         'WASD/Arrows:Move  P:Pause  ?:Help  ESC:Quit',
                         curses.color_pair(4))

    def get_controls(self):
        return [('WASD/Arrows', 'Move Pac-Man'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        total = sum(1 for row in self._MAZE for c in row if c in ('.', 'O'))
        return [('Lives left', self.lives),
                ('Dots eaten', total - self.dots_left)]

    def get_save_data(self):
        return {'maze': [list(row) for row in self.maze], 'score': self.score,
                'lives': self.lives, 'pac_y': self.pac_y, 'pac_x': self.pac_x,
                'pac_dir': list(self.pac_dir), 'next_dir': list(self.next_dir),
                'ghosts': [{**g, 'dir': list(g['dir'])} for g in self.ghosts],
                'frightened': self.frightened,
                'frightened_timer': self.frightened_timer,
                'frame': self.frame, 'ghost_speed': self.ghost_speed,
                'dots_left': self.dots_left, 'dying': self._dying}


# ─── Sokoban ─────────────────────────────────────────────────────────────────

class SokobanGame(Game):
    name = "sokoban"
    min_h = 16
    min_w = 30
    # '#' wall, '.' target, '$' box, '*' box-on-target, '@' player, '+' player-on-target
    _LEVELS = [
        ["#####",
         "#@$.#",
         "#####"],
        ["#####",
         "#@  #",
         "#$  #",
         "#.  #",
         "#####"],
        ["######",
         "#@ $.#",
         "# $ .#",
         "######"],
        ["#######",
         "#  .  #",
         "# #$# #",
         "#.$@$.#",
         "# #$# #",
         "#  .  #",
         "#######"],
    ]

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.level_idx = saved['level']
            self._parse_level(self.level_idx)
            self.boxes = {tuple(b) for b in saved['boxes']}
            self.py, self.px = saved['py'], saved['px']
            self.moves = saved['moves']
            self.pushes = saved['pushes']
            self.score = saved['score']
            self.history = []
            return
        self.level_idx = 0
        self.moves = 0
        self.pushes = 0
        self.score = 0
        self._start_level(self.level_idx)

    def _parse_level(self, idx):
        rows = self._LEVELS[idx]
        self.rows = len(rows)
        self.cols = max(len(r) for r in rows)
        self.walls = set()
        self.targets = set()
        self._init_boxes = set()
        self._init_player = (1, 1)
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                if ch == '#':
                    self.walls.add((r, c))
                elif ch in '.+*':
                    self.targets.add((r, c))
                if ch in '$*':
                    self._init_boxes.add((r, c))
                if ch in '@+':
                    self._init_player = (r, c)
        self.min_w = max(30, self.cols + 4)
        self.min_h = max(16, self.rows + 6)

    def _start_level(self, idx):
        self._parse_level(idx)
        self.boxes = set(self._init_boxes)
        self.py, self.px = self._init_player
        self.history = []

    def get_timeout(self):
        return -1  # turn-based: block until a key is pressed

    def _move(self, dy, dx):
        ny, nx = self.py + dy, self.px + dx
        if (ny, nx) in self.walls:
            return
        if (ny, nx) in self.boxes:
            by, bx = ny + dy, nx + dx
            if (by, bx) in self.walls or (by, bx) in self.boxes:
                return
            self.history.append((self.py, self.px, set(self.boxes), True))
            self.boxes.discard((ny, nx))
            self.boxes.add((by, bx))
            self.py, self.px = ny, nx
            self.moves += 1
            self.pushes += 1
        else:
            self.history.append((self.py, self.px, set(self.boxes), False))
            self.py, self.px = ny, nx
            self.moves += 1

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self._move(-1, 0)
        elif key in (curses.KEY_DOWN, ord('s')):
            self._move(1, 0)
        elif key in (curses.KEY_LEFT, ord('a')):
            self._move(0, -1)
        elif key in (curses.KEY_RIGHT, ord('d')):
            self._move(0, 1)
        elif key in (ord('u'), ord('z')):
            if self.history:
                self.py, self.px, self.boxes, was_push = self.history.pop()
                self.moves = max(0, self.moves - 1)
                if was_push:
                    self.pushes = max(0, self.pushes - 1)
        elif key in (ord('r'), ord('R')):
            self._start_level(self.level_idx)

    def update(self):
        if self.game_over:
            return
        if self.boxes == self.targets:
            self.score += 1  # one point per solved level
            if self.level_idx + 1 < len(self._LEVELS):
                self.level_idx += 1
                self._start_level(self.level_idx)
            else:
                self.won = True
                self.game_over = True

    def draw(self):
        off_y = max(1, (self.h - self.rows - 3) // 2)
        off_x = max(0, (self.w - self.cols) // 2)
        header = (f' SOKOBAN  Level {self.level_idx + 1}/{len(self._LEVELS)}'
                  f'  Moves:{self.moves}  Pushes:{self.pushes} ')
        self.safe_addstr(off_y - 1, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        for r in range(self.rows):
            for c in range(self.cols):
                cell = (r, c)
                if cell in self.walls:
                    ch, attr = '#', curses.color_pair(6) | curses.A_BOLD
                elif cell == (self.py, self.px):
                    ch = '+' if cell in self.targets else '@'
                    attr = curses.color_pair(4) | curses.A_BOLD
                elif cell in self.boxes:
                    on = cell in self.targets
                    ch = '*' if on else '$'
                    attr = curses.color_pair(1 if on else 2) | curses.A_BOLD
                elif cell in self.targets:
                    ch, attr = '.', curses.color_pair(3) | curses.A_BOLD
                else:
                    ch, attr = ' ', 0
                self.safe_addstr(off_y + r, off_x + c, ch, attr)
        hint = 'WASD:Move  U:Undo  R:Reset  ?:Help  ESC:Quit'
        self.safe_addstr(off_y + self.rows + 1,
                         max(0, (self.w - len(hint)) // 2), hint,
                         curses.color_pair(4))

    def get_controls(self):
        return [('WASD/Arrows', 'Push boxes'), ('U / Z', 'Undo move'),
                ('R', 'Reset level'), ('ESC', 'Quit / save')]

    def get_stats(self):
        return [('Levels solved', self.score),
                ('Moves', self.moves), ('Pushes', self.pushes)]

    def get_save_data(self):
        return {'level': self.level_idx, 'boxes': [list(b) for b in self.boxes],
                'py': self.py, 'px': self.px, 'moves': self.moves,
                'pushes': self.pushes, 'score': self.score}


# ─── Reversi / Othello ───────────────────────────────────────────────────────

class ReversiGame(Game):
    name = "reversi"
    min_h = 20
    min_w = 34
    supports_difficulty = False
    N = 8
    _DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    _WEIGHTS = [
        [120, -20,  20,   5,   5,  20, -20, 120],
        [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
        [ 20,  -5,  15,   3,   3,  15,  -5,  20],
        [  5,  -5,   3,   3,   3,   3,  -5,   5],
        [  5,  -5,   3,   3,   3,   3,  -5,   5],
        [ 20,  -5,  15,   3,   3,  15,  -5,  20],
        [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
        [120, -20,  20,   5,   5,  20, -20, 120],
    ]

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.board = saved['board']
            self.cur_r = saved['cur_r']
            self.cur_c = saved['cur_c']
            self.turn = saved['turn']
            self.score = saved['score']
            self.message = saved.get('message', '')
            return
        n = self.N
        self.board = [[0] * n for _ in range(n)]
        m = n // 2
        self.board[m - 1][m - 1] = self.board[m][m] = 2   # white = AI
        self.board[m - 1][m] = self.board[m][m - 1] = 1   # black = player
        self.cur_r = self.cur_c = m
        self.turn = 1
        self.score = 2
        self.message = 'Your move (black)'

    def get_timeout(self):
        return -1

    def _flips(self, board, r, c, player):
        if board[r][c] != 0:
            return []
        opp = 3 - player
        out = []
        for dy, dx in self._DIRS:
            line, y, x = [], r + dy, c + dx
            while 0 <= y < self.N and 0 <= x < self.N and board[y][x] == opp:
                line.append((y, x)); y += dy; x += dx
            if line and 0 <= y < self.N and 0 <= x < self.N and board[y][x] == player:
                out.extend(line)
        return out

    def _valid_moves(self, board, player):
        moves = {}
        for r in range(self.N):
            for c in range(self.N):
                if board[r][c] == 0:
                    f = self._flips(board, r, c, player)
                    if f:
                        moves[(r, c)] = f
        return moves

    def _apply(self, board, r, c, player, flips):
        board[r][c] = player
        for (y, x) in flips:
            board[y][x] = player

    def _counts(self):
        b = sum(row.count(1) for row in self.board)
        w = sum(row.count(2) for row in self.board)
        return b, w

    def _ai_move(self, valid):
        best, best_score = [], -10 ** 9
        for (r, c), flips in valid.items():
            s = self._WEIGHTS[r][c] + len(flips)
            if s > best_score:
                best_score, best = s, [(r, c)]
            elif s == best_score:
                best.append((r, c))
        return random.choice(best)

    def _finish(self):
        b, w = self._counts()
        self.score = b
        self.won = b > w
        self.game_over = True
        self.message = ('You win!' if b > w else
                        'Draw' if b == w else 'AI wins')

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self.cur_r = (self.cur_r - 1) % self.N
        elif key in (curses.KEY_DOWN, ord('s')):
            self.cur_r = (self.cur_r + 1) % self.N
        elif key in (curses.KEY_LEFT, ord('a')):
            self.cur_c = (self.cur_c - 1) % self.N
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.cur_c = (self.cur_c + 1) % self.N
        elif key in (curses.KEY_ENTER, ord(' '), 10, 13):
            if self.turn == 1:
                valid = self._valid_moves(self.board, 1)
                if (self.cur_r, self.cur_c) in valid:
                    self._apply(self.board, self.cur_r, self.cur_c, 1,
                                valid[(self.cur_r, self.cur_c)])
                    self.turn = 2

    def update(self):
        if self.game_over:
            return
        # Resolve turns/passes until it is the player's move (with a legal
        # option) or neither side can move. The bound safely exceeds the most
        # AI moves/passes possible in one call (one disc placed per cell).
        for _ in range(self.N * self.N + 4):
            pv = self._valid_moves(self.board, 1)
            av = self._valid_moves(self.board, 2)
            b, _w = self._counts()
            self.score = b
            if not pv and not av:
                self._finish()
                return
            if self.turn == 1:
                if pv:
                    self.message = 'Your move (black)'
                    return
                self.message = 'No move - you pass'
                self.turn = 2
            else:
                if av:
                    r, c = self._ai_move(av)
                    self._apply(self.board, r, c, 2, av[(r, c)])
                    self.message = f'AI played {chr(65 + c)}{r + 1}'
                    self.turn = 1
                else:
                    self.message = 'AI passes'
                    self.turn = 1

    def draw(self):
        b, w = self._counts()
        gw = self.N * 2 + 3
        sx = max(0, (self.w - gw) // 2)
        sy = max(1, (self.h - self.N - 4) // 2)
        self.safe_addstr(sy - 1, sx, ' REVERSI ', curses.A_BOLD | curses.A_REVERSE)
        score = f'You(X):{b}   AI(O):{w}'
        self.safe_addstr(sy - 1, sx + gw - len(score), score,
                         curses.color_pair(3) | curses.A_BOLD)
        self.safe_addstr(sy, sx + 3,
                         ' '.join(chr(65 + c) for c in range(self.N)),
                         curses.color_pair(4))
        valid = self._valid_moves(self.board, 1) if self.turn == 1 else {}
        for r in range(self.N):
            self.safe_addstr(sy + 1 + r, sx, f'{r + 1:>2}', curses.color_pair(4))
            for c in range(self.N):
                v = self.board[r][c]
                is_cur = (r == self.cur_r and c == self.cur_c)
                hi = curses.A_REVERSE if is_cur else 0
                if v == 1:
                    ch, attr = 'X', curses.color_pair(1) | curses.A_BOLD | hi
                elif v == 2:
                    ch, attr = 'O', curses.color_pair(2) | curses.A_BOLD | hi
                elif (r, c) in valid:
                    ch, attr = '*', curses.color_pair(3) | hi
                else:
                    ch, attr = '.', curses.color_pair(6) | hi
                self.safe_addstr(sy + 1 + r, sx + 3 + c * 2, ch, attr)
        self.safe_addstr(sy + self.N + 1, sx, self.message[:gw + 6],
                         curses.color_pair(3))
        hint = 'WASD:Move  Space:Place  ?:Help  ESC:Quit'
        self.safe_addstr(sy + self.N + 2, sx, hint, curses.color_pair(4))

    def get_controls(self):
        return [('WASD/Arrows', 'Move cursor'), ('Space/Enter', 'Place disc'),
                ('ESC', 'Quit / save')]

    def get_stats(self):
        b, w = self._counts()
        return [('You (X)', b), ('AI (O)', w)]

    def get_save_data(self):
        return {'board': self.board, 'cur_r': self.cur_r, 'cur_c': self.cur_c,
                'turn': self.turn, 'score': self.score, 'message': self.message}


# ─── Frogger ─────────────────────────────────────────────────────────────────

class FroggerGame(Game):
    name = "frogger"
    min_h = 20
    min_w = 44
    FIELD_W = 40
    # (type, direction, speed cells/frame) from top row to bottom row.
    _LANES = [
        ('home',  0, 0.0),
        ('river', 1, 0.60),
        ('river', -1, 0.45),
        ('river', 1, 0.30),
        ('safe',  0, 0.0),
        ('road', -1, 0.55),
        ('road', 1, 0.40),
        ('road', -1, 0.30),
        ('safe',  0, 0.0),
    ]
    _HOME_BAYS = [4, 14, 24, 34]

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.frog_row = saved['frog_row']
            self.frog_x = saved['frog_x']
            self.lanes = saved['lanes']
            self.lives = saved['lives']
            self.score = saved['score']
            self.homes = saved['homes']
            self.frame = saved['frame']
            self.best_row = saved['best_row']
            return
        self._new_game()

    def _new_game(self):
        self.frame = 0
        self.lives = 3
        self.score = 0
        self.homes = [False] * len(self._HOME_BAYS)
        self.lanes = []
        for typ, _d, _spd in self._LANES:
            ents = []
            if typ in ('road', 'river'):
                gap = 9 if typ == 'river' else 8
                x = 0
                while x < self.FIELD_W:
                    ents.append(float(x))
                    x += gap
            self.lanes.append({'ents': ents})
        self._reset_frog()

    def _reset_frog(self):
        self.frog_row = len(self._LANES) - 1
        self.frog_x = float(self.FIELD_W // 2)
        self.best_row = self.frog_row

    def get_timeout(self):
        return 90

    def _ent_width(self, typ):
        return 5 if typ == 'river' else 3

    def _covers(self, ent, width, col):
        s = int(ent) % self.FIELD_W
        return any((s + k) % self.FIELD_W == col for k in range(width))

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self.frog_row = max(0, self.frog_row - 1)
            if self.frog_row < self.best_row:
                self.best_row = self.frog_row
                self.score += 10
        elif key in (curses.KEY_DOWN, ord('s')):
            self.frog_row = min(len(self._LANES) - 1, self.frog_row + 1)
        elif key in (curses.KEY_LEFT, ord('a')):
            self.frog_x = max(0.0, self.frog_x - 1)
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.frog_x = min(self.FIELD_W - 1.0, self.frog_x + 1)

    def _die(self):
        self.lives -= 1
        if self.lives <= 0:
            self.game_over = True
        else:
            self._reset_frog()

    def _reach_home(self):
        col = int(round(self.frog_x))
        bay = min(range(len(self._HOME_BAYS)),
                  key=lambda i: abs(self._HOME_BAYS[i] - col))
        if abs(self._HOME_BAYS[bay] - col) > 2 or self.homes[bay]:
            self._die()          # missed a bay or landed on a filled one
            return
        self.homes[bay] = True
        self.score += 50
        if all(self.homes):
            self.score += 200
            self.won = True
            self.game_over = True
        else:
            self._reset_frog()

    def update(self):
        if self.game_over:
            return
        self.frame += 1
        row = self.frog_row
        typ, d, spd = self._LANES[row]
        # Decide river contact from the FRAME-START positions (before logs move)
        # in continuous space, so a frog that starts on a log rides with it
        # instead of slipping off its back edge; it only drowns if it hopped
        # into open water or is carried off-screen.
        on_log = False
        if typ == 'river':
            width = self._ent_width('river')
            on_log = any(0 <= (self.frog_x - e) % self.FIELD_W < width
                         for e in self.lanes[row]['ents'])
        # Advance all traffic.
        for i, (t, dd, ss) in enumerate(self._LANES):
            if t in ('road', 'river'):
                self.lanes[i]['ents'] = [(e + dd * ss) % self.FIELD_W
                                         for e in self.lanes[i]['ents']]
        if typ == 'home':
            self._reach_home()
        elif typ == 'river':
            if not on_log:
                self._die()
                return
            self.frog_x += d * spd  # carried by the log, in lockstep
            if self.frog_x < 0 or self.frog_x > self.FIELD_W - 1:
                self._die()
        elif typ == 'road':
            # Cars move onto a stationary frog, so check AFTER they advance.
            col = int(round(self.frog_x))
            if any(self._covers(e, self._ent_width('road'), col)
                   for e in self.lanes[row]['ents']):
                self._die()

    def draw(self):
        fw = self.FIELD_W
        sx = max(0, (self.w - fw) // 2)
        sy = max(1, (self.h - len(self._LANES) - 3) // 2)
        header = f' FROGGER  Score:{self.score}  Lives:{"@" * self.lives} '
        self.safe_addstr(sy - 1, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        for i, (typ, d, spd) in enumerate(self._LANES):
            y = sy + i
            if typ == 'home':
                self.safe_addstr(y, sx, '^' * fw, curses.color_pair(1))
                for bi, bx in enumerate(self._HOME_BAYS):
                    ch = 'O' if self.homes[bi] else '_'
                    self.safe_addstr(y, sx + bx, ch,
                                     curses.color_pair(1) | curses.A_BOLD)
            elif typ == 'safe':
                self.safe_addstr(y, sx, '-' * fw, curses.color_pair(4))
            elif typ == 'river':
                self.safe_addstr(y, sx, '~' * fw, curses.color_pair(6))
                for e in self.lanes[i]['ents']:
                    for k in range(self._ent_width('river')):
                        cx = (int(e) + k) % fw
                        self.safe_addstr(y, sx + cx, '#',
                                         curses.color_pair(3) | curses.A_BOLD)
            else:  # road
                for e in self.lanes[i]['ents']:
                    for k in range(self._ent_width('road')):
                        cx = (int(e) + k) % fw
                        ch = '[' if k == 0 else (']' if k == 2 else 'o')
                        self.safe_addstr(y, sx + cx, ch,
                                         curses.color_pair(2) | curses.A_BOLD)
        fy = sy + self.frog_row
        self.safe_addstr(fy, sx + int(round(self.frog_x)), '@',
                         curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
        hint = 'WASD/Arrows:Hop  P:Pause  ?:Help  ESC:Quit'
        self.safe_addstr(sy + len(self._LANES) + 1,
                         max(0, (self.w - len(hint)) // 2), hint,
                         curses.color_pair(4))

    def get_controls(self):
        return [('WASD/Arrows', 'Hop'), ('P', 'Pause'), ('ESC', 'Quit / save')]

    def get_stats(self):
        return [('Homes filled', f'{sum(self.homes)}/{len(self.homes)}'),
                ('Lives left', self.lives)]

    def get_save_data(self):
        return {'frog_row': self.frog_row, 'frog_x': self.frog_x,
                'lanes': self.lanes, 'lives': self.lives, 'score': self.score,
                'homes': self.homes, 'frame': self.frame,
                'best_row': self.best_row}


# ─── Menu ────────────────────────────────────────────────────────────────────

_ICONS = {'snake': '~o~', 'tetris': '[#]', '2048': ' 2K', 'dino': '/^\\',
          'breakout': '[=]', 'shooter': '/A\\', 'pong': '|O|',
          'flappy': '>>=', 'minesweeper_i': '[*]', 'pacman': 'C.M',
          'sokoban': '[$]', 'reversi': 'XO ', 'frogger': '@^^'}

_GAMES = [
    ("Snake",         "Classic snake - eat food, grow longer",     SnakeGame),
    ("Tetris",        "Stack blocks, clear lines",                 TetrisGame),
    ("2048",          "Slide and merge tiles to reach 2048",       Game2048),
    ("Dino Runner",   "Jump over obstacles, survive!",             DinoGame),
    ("Breakout",      "Break all the bricks with a bouncing ball", BreakoutGame),
    ("Space Shooter", "Blast enemies, defeat bosses",              ShooterGame),
    ("Pong",          "Classic paddle game vs AI",                 PongGame),
    ("Flappy Bird",   "Flap through pipes, don't crash",          FlappyGame),
    ("Minesweeper",   "Uncover cells, avoid mines",               MinesweeperGame),
    ("Pac-Man",       "Eat dots, avoid ghosts",                   PacManGame),
    ("Sokoban",       "Push every box onto a target",             SokobanGame),
    ("Reversi",       "Outflank the AI on an 8x8 board",          ReversiGame),
    ("Frogger",       "Hop across road and river to the bays",    FroggerGame),
]

_TITLE = [
    " ╔═╗╦  ╔═╗╦ ╦╔╦╗╔═╗  ╔═╗╔═╗╔╦╗╔═╗╔═╗ ",
    " ║  ║  ╠═╣║ ║ ║║║╣   ║ ╦╠═╣║║║║╣ ╚═╗ ",
    " ╚═╝╩═╝╩ ╩╚═╝═╩╝╚═╝  ╚═╝╩ ╩╩ ╩╚═╝╚═╝ ",
]

_GAME_MAP = {g[0].lower().replace(' ', ''): g[2] for g in _GAMES}
_GAME_MAP.update({'dino': DinoGame, '2048': Game2048,
                  'shooter': ShooterGame, 'space': ShooterGame,
                  'pong': PongGame, 'flappy': FlappyGame,
                  'bird': FlappyGame, 'mines': MinesweeperGame,
                  'sweep': MinesweeperGame, 'pacman': PacManGame,
                  'pac': PacManGame, 'sokoban': SokobanGame,
                  'boxes': SokobanGame, 'reversi': ReversiGame,
                  'othello': ReversiGame, 'frogger': FroggerGame,
                  'frog': FroggerGame})


def _safe(stdscr, y, x, text, attr=0):
    h, w = stdscr.getmaxyx()
    if 0 <= y < h and 0 <= x < w:
        try:
            stdscr.addstr(y, x, text[:max(0, w - x)], attr)
        except curses.error:
            pass


def _run_game(stdscr, cls):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    _load_theme()  # honor saved theme even on direct `play <game>` launch
    init_colors()
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
    _load_theme()
    init_colors()
    sel = 0
    scroll = 0
    stdscr.clear()
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 28 or w < 44:
            _safe(stdscr, h // 2, max(0, (w - 30) // 2),
                  f'Need 44x28 terminal ({w}x{h})', curses.A_BOLD)
            stdscr.noutrefresh()
            curses.doupdate()
            stdscr.getch()
            continue

        ty = max(1, h // 2 - len(_GAMES) - 5)
        for i, line in enumerate(_TITLE):
            _safe(stdscr, ty + i, max(0, (w - len(line)) // 2), line,
                  curses.color_pair(4) | curses.A_BOLD)
        sub = "Play while you wait"
        _safe(stdscr, ty + len(_TITLE), max(0, (w - len(sub)) // 2), sub,
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
            hi = load_high_score(cls.name)
            icon = _ICONS.get(cls.name, '   ')
            if i == sel:
                _safe(stdscr, y, bx, ' > ', curses.color_pair(1))
                _safe(stdscr, y, bx + 3, icon,
                      curses.color_pair(5) | curses.A_BOLD)
                _safe(stdscr, y, bx + 7, f'{name:<14}',
                      curses.A_BOLD | curses.A_REVERSE)
            else:
                _safe(stdscr, y, bx + 3, icon, curses.color_pair(5))
                _safe(stdscr, y, bx + 7, f'{name:<14}', curses.A_BOLD)
            sv = Game.has_save(cls.name)
            if sv is not None:
                _safe(stdscr, y, bx + 22, f'[Resume:{sv}]',
                      curses.color_pair(1) | curses.A_BOLD)
            elif hi > 0:
                _safe(stdscr, y, bx + 22, f'[Best: {hi}]',
                      curses.color_pair(3))
            _safe(stdscr, y + 1, bx + 7, desc[:38], curses.color_pair(4))
        if scroll > 0:
            _safe(stdscr, ly - 1, bx + 7, '^ more', curses.color_pair(3))
        if end < len(_GAMES):
            _safe(stdscr, ly + (end - scroll) * 2, bx + 7, 'v more',
                  curses.color_pair(3))

        cy = min(h - 2, ly + visible * 2 + 1)
        ctrl = "Up/Down: Select  Enter: Play  T: Theme  ?: Help  Q: Quit"
        _safe(stdscr, cy, max(0, (w - len(ctrl)) // 2), ctrl,
              curses.color_pair(7))
        theme_label = f'Theme: {_current_theme}'
        _safe(stdscr, cy + 1, max(0, (w - len(theme_label)) // 2),
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
        elif key in (ord('t'), ord('T')):
            names = list(_THEMES.keys())
            idx = names.index(_current_theme) if _current_theme in names else 0
            _save_theme(names[(idx + 1) % len(names)])
            init_colors()
        elif key in (ord('q'), 27):
            break


# ─── CLI: Snake ──────────────────────────────────────────────────────────────

def _cli_place_food(h, w, snake):
    snake_set = {tuple(p) for p in snake}
    empty = [(y, x) for y in range(1, h - 1) for x in range(1, w - 1)
             if (y, x) not in snake_set]
    return list(random.choice(empty)) if empty else [1, 1]


def _cli_snake_init():
    h, w = 12, 20
    my, mx = h // 2, w // 2
    snake = [[my, mx], [my, mx - 1], [my, mx - 2]]
    return {'game': 'snake', 'h': h, 'w': w, 'snake': snake,
            'dir': [0, 1], 'food': _cli_place_food(h, w, snake),
            'score': 0, 'over': False}


def _cli_snake_move(s, action):
    dirs = {'up': [-1, 0], 'down': [1, 0], 'left': [0, -1], 'right': [0, 1]}
    if action not in dirs:
        return s
    nd = dirs[action]
    od = s['dir']
    if nd[0] != -od[0] or nd[1] != -od[1]:
        s['dir'] = nd
    hy, hx = s['snake'][0]
    dy, dx = s['dir']
    nh = [hy + dy, hx + dx]
    if nh[0] <= 0 or nh[0] >= s['h'] - 1 or nh[1] <= 0 or nh[1] >= s['w'] - 1:
        s['over'] = True
        return s
    grow = (nh == s['food'])
    # The tail moves out of its cell unless we eat, so following the tail is
    # legal: exclude the last segment when not growing.
    body = s['snake'] if grow else s['snake'][:-1]
    if nh in body:
        s['over'] = True
        return s
    s['snake'].insert(0, nh)
    if grow:
        s['score'] += 1
        s['food'] = _cli_place_food(s['h'], s['w'], s['snake'])
    else:
        s['snake'].pop()
    return s


def _cli_snake_render(s):
    lines = [f"SNAKE   Score: {s['score']}"]
    lines.append('┌' + '─' * (s['w'] - 2) + '┐')
    snake_set = {tuple(p) for p in s['snake']}
    head = tuple(s['snake'][0])
    food = tuple(s['food'])
    for y in range(1, s['h'] - 1):
        row = '│'
        for x in range(1, s['w'] - 1):
            if (y, x) == head:
                row += '@'
            elif (y, x) in snake_set:
                row += 'o'
            elif (y, x) == food:
                row += '*'
            else:
                row += '·'
        row += '│'
        lines.append(row)
    lines.append('└' + '─' * (s['w'] - 2) + '┘')
    if s['over']:
        lines.append(f"GAME OVER!  Final score: {s['score']}")
    else:
        lines.append('Move: up / down / left / right')
    return '\n'.join(lines)


# ─── CLI: 2048 ───────────────────────────────────────────────────────────────

def _cli_2048_add_tile(grid):
    empty = [(r, c) for r in range(4) for c in range(4) if grid[r][c] == 0]
    if empty:
        r, c = random.choice(empty)
        grid[r][c] = 4 if random.random() < 0.1 else 2


def _cli_2048_slide(row):
    tiles = [x for x in row if x]
    merged, pts, i = [], 0, 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            v = tiles[i] * 2
            merged.append(v)
            pts += v
            i += 2
        else:
            merged.append(tiles[i])
            i += 1
    return merged + [0] * (4 - len(merged)), pts


def _cli_2048_init():
    grid = [[0] * 4 for _ in range(4)]
    _cli_2048_add_tile(grid)
    _cli_2048_add_tile(grid)
    return {'game': '2048', 'grid': grid, 'score': 0, 'over': False, 'won': False}


def _cli_2048_can_move(g):
    for r in range(4):
        for c in range(4):
            if g[r][c] == 0:
                return True
            if c + 1 < 4 and g[r][c] == g[r][c + 1]:
                return True
            if r + 1 < 4 and g[r][c] == g[r + 1][c]:
                return True
    return False


def _cli_2048_move(s, action):
    if action not in ('up', 'down', 'left', 'right'):
        return s
    old = [row[:] for row in s['grid']]
    g, pts = s['grid'], 0
    if action == 'left':
        for r in range(4):
            g[r], p = _cli_2048_slide(g[r])
            pts += p
    elif action == 'right':
        for r in range(4):
            rev, p = _cli_2048_slide(g[r][::-1])
            g[r] = rev[::-1]
            pts += p
    elif action == 'up':
        for c in range(4):
            col, p = _cli_2048_slide([g[r][c] for r in range(4)])
            pts += p
            for r in range(4):
                g[r][c] = col[r]
    elif action == 'down':
        for c in range(4):
            col, p = _cli_2048_slide([g[r][c] for r in range(4)][::-1])
            pts += p
            col = col[::-1]
            for r in range(4):
                g[r][c] = col[r]
    if g != old:
        s['score'] += pts
        _cli_2048_add_tile(g)
        if not s['won'] and any(g[r][c] == 2048 for r in range(4) for c in range(4)):
            s['won'] = True
    if not _cli_2048_can_move(g):
        s['over'] = True
    return s


def _cli_2048_render(s):
    g = s['grid']
    cw = 6
    lines = [f"2048   Score: {s['score']}"]
    top = '┌' + ('─' * cw + '┬') * 3 + '─' * cw + '┐'
    sep = '├' + ('─' * cw + '┼') * 3 + '─' * cw + '┤'
    bot = '└' + ('─' * cw + '┴') * 3 + '─' * cw + '┘'
    lines.append(top)
    for r in range(4):
        row = '│'
        for c in range(4):
            v = g[r][c]
            row += (str(v).center(cw) if v else ' ' * cw) + '│'
        lines.append(row)
        lines.append(sep if r < 3 else bot)
    if s['won']:
        lines.append('You reached 2048! Keep going!')
    if s['over']:
        lines.append(f"GAME OVER!  Final score: {s['score']}")
    else:
        lines.append('Move: up / down / left / right')
    return '\n'.join(lines)


# ─── CLI: Minesweeper ────────────────────────────────────────────────────────

def _cli_ms_place_mines(s, safe_r, safe_c):
    """Place mines after the first reveal, keeping that cell and its neighbors
    mine-free so the first click is always safe (matches the interactive game)."""
    size = s['size']
    forbidden = {(safe_r + dr, safe_c + dc)
                 for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
    cells = [(r, c) for r in range(size) for c in range(size)
             if (r, c) not in forbidden]
    mines = set(random.sample(cells, min(s['num_mines'], len(cells))))
    nums = [[0] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if (r, c) in mines:
                nums[r][c] = -1
                continue
            nums[r][c] = sum(
                1 for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                if 0 <= r + dr < size and 0 <= c + dc < size
                and (r + dr, c + dc) in mines)
    s['mines'] = [list(m) for m in mines]
    s['nums'] = nums
    s['placed'] = True


def _cli_ms_init(size=9, num_mines=10):
    # Mines are placed lazily on the first reveal so it is always safe.
    return {'game': 'minesweeper', 'size': size, 'num_mines': num_mines,
            'mines': [], 'nums': [[0] * size for _ in range(size)],
            'placed': False, 'revealed': [], 'flagged': [],
            'over': False, 'won': False, 'score': 0}


def _cli_ms_move(s, action):
    parts = action.split()
    if len(parts) < 3 or parts[0] not in ('reveal', 'flag'):
        return s
    try:
        r, c = int(parts[1]) - 1, int(parts[2]) - 1
    except (ValueError, IndexError):
        return s
    sz = s['size']
    if r < 0 or r >= sz or c < 0 or c >= sz:
        return s

    mines_set = {tuple(m) for m in s['mines']}
    revealed = {tuple(p) for p in s['revealed']}
    flagged = {tuple(p) for p in s['flagged']}

    if parts[0] == 'flag':
        if (r, c) in revealed:
            pass
        elif (r, c) in flagged:
            flagged.discard((r, c))
        else:
            flagged.add((r, c))
    elif parts[0] == 'reveal':
        if (r, c) in flagged or (r, c) in revealed:
            pass
        else:
            if not s.get('placed', len(s.get('mines', [])) > 0):
                _cli_ms_place_mines(s, r, c)
                mines_set = {tuple(m) for m in s['mines']}
            if (r, c) in mines_set:
                s['over'] = True
                revealed |= mines_set
            else:
                stack = [(r, c)]
                while stack:
                    cr, cc = stack.pop()
                    if (cr, cc) in revealed or (cr, cc) in flagged:
                        continue  # never auto-reveal a flagged cell
                    revealed.add((cr, cc))
                    if s['nums'][cr][cc] == 0:
                        for dr in (-1, 0, 1):
                            for dc in (-1, 0, 1):
                                nr, nc = cr + dr, cc + dc
                                if 0 <= nr < sz and 0 <= nc < sz and (nr, nc) not in revealed:
                                    stack.append((nr, nc))

    s['revealed'] = [list(p) for p in revealed]
    s['flagged'] = [list(p) for p in flagged]

    safe_total = sz * sz - len(mines_set)
    revealed_safe = len(revealed - mines_set)
    if revealed_safe == safe_total and not s['over']:
        s['won'] = True
        s['over'] = True
        s['score'] = safe_total
    return s


def _cli_ms_render(s):
    sz = s['size']
    mines_set = {tuple(m) for m in s['mines']}
    revealed = {tuple(p) for p in s['revealed']}
    flagged = {tuple(p) for p in s['flagged']}
    total_mines = s.get('num_mines', len(mines_set))
    lines = [f"MINESWEEPER   Mines left: ~{total_mines - len(flagged)}"]
    hdr = '     ' + ''.join(f'{c + 1:>3}' for c in range(sz))
    lines.append(hdr)
    lines.append('    ┌' + '───' * sz + '┐')
    for r in range(sz):
        row = f' {r + 1:>2} │'
        for c in range(sz):
            if (r, c) in flagged and not s['over']:
                row += ' F '
            elif (r, c) not in revealed:
                row += ' . '
            elif (r, c) in mines_set:
                row += ' X '
            elif s['nums'][r][c] == 0:
                row += '   '
            else:
                row += f' {s["nums"][r][c]} '
        row += '│'
        lines.append(row)
    lines.append('    └' + '───' * sz + '┘')
    if s['won']:
        lines.append('YOU WIN! All safe cells revealed!')
    elif s['over']:
        lines.append('BOOM! You hit a mine!')
    else:
        lines.append('Commands: reveal <row> <col>  |  flag <row> <col>')
    return '\n'.join(lines)


# ─── CLI: Connect4 ───────────────────────────────────────────────────────────

def _cli_c4_init():
    return {
        'game': 'connect4',
        'board': [[0] * 7 for _ in range(6)],
        'score': 0,
        'over': False,
        'won': False,
        'turn': 1,
        'last_col': None,
    }


def _cli_c4_check_win(board, player):
    rows, cols = 6, 7
    # Horizontal
    for r in range(rows):
        for c in range(cols - 3):
            if all(board[r][c + i] == player for i in range(4)):
                return True
    # Vertical
    for r in range(rows - 3):
        for c in range(cols):
            if all(board[r + i][c] == player for i in range(4)):
                return True
    # Diagonal down-right
    for r in range(rows - 3):
        for c in range(cols - 3):
            if all(board[r + i][c + i] == player for i in range(4)):
                return True
    # Diagonal down-left
    for r in range(rows - 3):
        for c in range(3, cols):
            if all(board[r + i][c - i] == player for i in range(4)):
                return True
    return False


def _cli_c4_drop(board, col, player):
    """Drop piece into col (0-indexed). Returns row placed, or -1 if full."""
    for r in range(5, -1, -1):
        if board[r][col] == 0:
            board[r][col] = player
            return r
    return -1


def _cli_c4_is_full(board):
    return all(board[0][c] != 0 for c in range(7))


def _cli_c4_ai_move(board):
    """Return best column (0-indexed) for AI."""
    # Check AI winning move
    for c in range(7):
        if board[0][c] == 0:
            test = [row[:] for row in board]
            _cli_c4_drop(test, c, 2)
            if _cli_c4_check_win(test, 2):
                return c
    # Block player winning move
    for c in range(7):
        if board[0][c] == 0:
            test = [row[:] for row in board]
            _cli_c4_drop(test, c, 1)
            if _cli_c4_check_win(test, 1):
                return c
    # Prefer center columns: 3, 2, 4, 1, 5, 0, 6
    for c in (3, 2, 4, 1, 5, 0, 6):
        if board[0][c] == 0:
            return c
    return -1


def _cli_c4_move(s, action):
    if s.get('over'):
        return s
    action = action.strip()
    try:
        col = int(action) - 1
    except ValueError:
        return s
    if col < 0 or col > 6:
        return s
    if s['board'][0][col] != 0:
        return s

    # Player move
    _cli_c4_drop(s['board'], col, 1)
    s['last_col'] = col
    if _cli_c4_check_win(s['board'], 1):
        s['over'] = True
        s['won'] = True
        s['score'] = 1
        return s
    if _cli_c4_is_full(s['board']):
        s['over'] = True
        return s

    # AI move
    ai_col = _cli_c4_ai_move(s['board'])
    if ai_col >= 0:
        _cli_c4_drop(s['board'], ai_col, 2)
        s['last_col'] = ai_col
        if _cli_c4_check_win(s['board'], 2):
            s['over'] = True
            s['won'] = False
            s['score'] = 0
            return s
        if _cli_c4_is_full(s['board']):
            s['over'] = True
    return s


def _cli_c4_render(s):
    lines = [f"CONNECT 4   Score: {s['score']}"]
    lines.append('  1 2 3 4 5 6 7')
    lines.append(' ┌─────────────┐')
    glyphs = {0: '.', 1: 'X', 2: 'O'}
    for r in range(6):
        row = ' │'
        for c in range(7):
            row += glyphs[s['board'][r][c]] + ' '
        row = row.rstrip(' ') + '│'
        lines.append(row)
    lines.append(' └─────────────┘')
    if s['won']:
        lines.append('You win!')
    elif s.get('over'):
        if not s['won'] and _cli_c4_is_full(s['board']) and not _cli_c4_check_win(s['board'], 2):
            lines.append("It's a draw!")
        else:
            lines.append('AI wins!')
    else:
        lines.append('Your turn (1-7):')
    return '\n'.join(lines)


# ─── CLI Dispatcher ──────────────────────────────────────────────────────────

_CLI_GAMES = {
    'snake': (_cli_snake_init, _cli_snake_move, _cli_snake_render),
    '2048': (_cli_2048_init, _cli_2048_move, _cli_2048_render),
    'minesweeper': (_cli_ms_init, _cli_ms_move, _cli_ms_render),
    'connect4': (_cli_c4_init, _cli_c4_move, _cli_c4_render),
}


def _load_game_state():
    try:
        return json.loads(GAME_STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _save_game_state(state):
    _ensure_config()
    GAME_STATE_FILE.write_text(json.dumps(state))


def _cli_render(state):
    renderers = {'snake': _cli_snake_render, '2048': _cli_2048_render,
                 'minesweeper': _cli_ms_render, 'connect4': _cli_c4_render}
    return renderers.get(state['game'], lambda s: 'Unknown game')(state)


def _cli_mode(args):
    if not args:
        state = _load_game_state()
        if state and not state.get('over'):
            print(_cli_render(state))
        else:
            print('CLAUDE GAMES')
            print('────────────')
            print('  snake        Classic snake, turn by turn')
            print('  2048         Slide and merge number tiles')
            print('  minesweeper  Uncover cells, avoid mines')
            print('  connect4     Drop pieces, get four in a row')
            print()
            print('Start a game:  play cli start <game>')
            print('Interactive:   ! play  (full-screen curses games)')
        return

    cmd = args[0].lower()

    if cmd == 'start':
        name = args[1].lower() if len(args) > 1 else ''
        if name in ('ms', 'mines'):
            name = 'minesweeper'
        if name in ('c4',):
            name = 'connect4'
        if name not in _CLI_GAMES:
            print(f'Unknown game: {name}')
            print('Available: snake, 2048, minesweeper, connect4')
            return
        init_fn = _CLI_GAMES[name][0]
        state = init_fn()
        _save_game_state(state)
        print(_cli_render(state))

    elif cmd == 'show':
        state = _load_game_state()
        if state:
            print(_cli_render(state))
        else:
            print('No active game. Run: play cli start <game>')

    elif cmd == 'quit':
        state = _load_game_state()
        if state:
            save_high_score(state['game'], state.get('score', 0))
            GAME_STATE_FILE.unlink(missing_ok=True)
            print(f"Game ended. Final score: {state.get('score', 0)}")
        else:
            print('No active game.')

    elif cmd in ('up', 'down', 'left', 'right'):
        state = _load_game_state()
        if not state:
            print('No active game. Run: play cli start <game>')
            return
        if state.get('over'):
            print(_cli_render(state))
            return
        move_fn = _CLI_GAMES[state['game']][1]
        state = move_fn(state, cmd)
        _save_game_state(state)
        if state.get('over'):
            save_high_score(state['game'], state.get('score', 0))
        print(_cli_render(state))

    elif cmd in ('reveal', 'flag'):
        state = _load_game_state()
        if not state or state.get('game') != 'minesweeper':
            print('No active minesweeper game.')
            return
        if state.get('over'):
            print(_cli_render(state))
            return
        action = ' '.join(args)
        state = _cli_ms_move(state, action)
        _save_game_state(state)
        if state.get('over'):
            save_high_score(state['game'], state.get('score', 0))
        print(_cli_render(state))

    elif cmd.isdigit():
        # Connect4 column move
        state = _load_game_state()
        if not state or state.get('game') != 'connect4':
            print('No active connect4 game.')
            return
        if state.get('over'):
            print(_cli_render(state))
            return
        state = _cli_c4_move(state, cmd)
        _save_game_state(state)
        if state.get('over'):
            save_high_score(state['game'], state.get('score', 0))
        print(_cli_render(state))

    else:
        print(f'Unknown: {cmd}')
        print('Commands: start <game> | up/down/left/right | 1-7 (connect4) | reveal/flag <r> <c> | show | quit')


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    # Ensure box-drawing / unicode output doesn't crash on a legacy console
    # (e.g. Windows cp1252). errors='replace' keeps text commands alive.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    try:
        locale.setlocale(locale.LC_ALL, '')
    except (locale.Error, ValueError):
        pass
    args = sys.argv[1:]

    if not args:
        _curses_wrapper(_menu)
        return

    cmd = args[0].lower().strip('-')

    # Quick move shortcuts: play w/a/s/d (no Claude needed, use with ! prefix)
    _shortcuts = {'w': 'up', 'a': 'left', 's': 'down', 'd': 'right',
                  'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right'}
    if cmd in _shortcuts:
        state = _load_game_state()
        if state and not state.get('over'):
            _cli_mode([_shortcuts[cmd]])
            return

    # Connect4 column shortcut: play 3 (drops in column 3). Exclude real game
    # names like "2048" so `play 2048` still launches the interactive game.
    if cmd.isdigit() and cmd not in _GAME_MAP:
        state = _load_game_state()
        if state and state.get('game') == 'connect4' and not state.get('over'):
            _cli_mode([cmd])
            return

    # Direct game commands: play reveal/flag/show/quit/new
    if cmd in ('reveal', 'flag'):
        _cli_mode(args)
        return
    if cmd == 'show':
        _cli_mode(['show'])
        return
    if cmd in ('quit', 'stop', 'end'):
        _cli_mode(['quit'])
        return
    if cmd == 'new':
        game = args[1] if len(args) > 1 else ''
        _cli_mode(['start', game])
        return

    if cmd == 'cli':
        _cli_mode(args[1:])
    elif cmd in ('h', 'help'):
        print(__doc__.strip())
    elif cmd in ('v', 'version'):
        print(f'play {__version__}')
    elif cmd in ('list', 'ls'):
        for name, desc, cls in _GAMES:
            hi = load_high_score(cls.name)
            hs = f'  [Best: {hi}]' if hi else ''
            print(f'  {name:<14} {desc}{hs}')
    elif cmd in _GAME_MAP:
        cls = _GAME_MAP[cmd]
        _curses_wrapper(lambda s, c=cls: _run_game(s, c), cmd)
    else:
        print(f'Unknown game: {cmd}')
        print('Available: ' + ', '.join(n for n, _, _ in _GAMES))
        sys.exit(1)


if __name__ == '__main__':
    main()
