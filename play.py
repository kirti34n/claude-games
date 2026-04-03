"""
play - Terminal mini games collection

Usage:
    play              Launch interactive game menu (needs terminal)
    play snake        Play Snake interactively
    play tetris       Play Tetris interactively
    play 2048         Play 2048 interactively
    play dino         Play Dino Runner interactively
    play breakout     Play Breakout interactively

    play cli                  Show in-conversation game menu
    play cli start snake      Start Snake (turn-based)
    play cli start 2048       Start 2048
    play cli start minesweeper  Start Minesweeper
    play cli <move>           Make a move (up/down/left/right)
    play cli reveal <r> <c>   Minesweeper: reveal cell
    play cli flag <r> <c>     Minesweeper: toggle flag
    play cli show             Show current board
    play cli quit             End current game

    play --version    Show version
    play --help       Show this help

Install:
    pip install claude-games
"""

__version__ = '2.2.0'

import curses
import json
import locale
import os
import random
import sys
import time
from pathlib import Path


def _open_in_terminal(game_args: str = ''):
    """Launch the game in a split pane or new window (for piped environments like Claude Code)."""
    import shutil
    import subprocess
    play_bin = shutil.which('play') or sys.argv[0]
    cmd_str = f'{play_bin} {game_args}'.strip()

    # Prefer tmux split pane — game runs alongside Claude in the same terminal
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

    # tmux available but not in a session — start one with the game
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
    if sys.stdin.isatty() and sys.stdout.isatty():
        return curses.wrapper(func)

    # No TTY — try to open in a split pane or new window
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


# ─── Colors ──────────────────────────────────────────────────────────────────

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)
    if curses.COLORS >= 8:
        curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_RED)
        curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_GREEN)
        curses.init_pair(10, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(11, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(12, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
        curses.init_pair(13, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(14, curses.COLOR_BLACK, curses.COLOR_WHITE)


# ─── Base Game ───────────────────────────────────────────────────────────────

class Game:
    name = "game"
    min_h = 20
    min_w = 40

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.score = 0
        self.paused = False
        self.game_over = False
        self.won = False
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
        curses.curs_set(0)
        self.setup()
        self.h, self.w = self.stdscr.getmaxyx()
        self.stdscr.clear()
        self.draw()
        self.stdscr.noutrefresh()
        curses.doupdate()

        timeout = self.get_timeout()
        self.stdscr.timeout(timeout)

        while True:
            key = self.stdscr.getch()
            self.h, self.w = self.stdscr.getmaxyx()

            if key == 27 or key == ord('q'):
                if not self.game_over:
                    self._auto_save()
                return 'quit'
            if key == ord('p') and not self.game_over:
                self.paused = not self.paused
                if self.paused:
                    self.center_text(self.h // 2,
                                     '  PAUSED  -  Press P to resume  ',
                                     curses.A_REVERSE | curses.A_BOLD)
                    self.stdscr.noutrefresh()
                    curses.doupdate()
                continue
            if self.paused:
                continue
            if not self.game_over:
                self.handle_input(key)
                self.update()

            # Update timeout if it changed (e.g. snake speeds up)
            new_timeout = self.get_timeout()
            if new_timeout != timeout:
                timeout = new_timeout
                self.stdscr.timeout(timeout)

            self.stdscr.erase()
            if self.h < self.min_h or self.w < self.min_w:
                self.center_text(self.h // 2,
                                 f'Terminal too small ({self.w}x{self.h})')
                self.center_text(self.h // 2 + 1,
                                 f'Need at least {self.min_w}x{self.min_h}')
                self.stdscr.noutrefresh()
                curses.doupdate()
                continue
            self.draw()
            if self.game_over:
                return self._game_over_screen()
            self.stdscr.noutrefresh()
            curses.doupdate()

    def _game_over_screen(self):
        mid = self.h // 2
        if self.won:
            self.center_text(mid - 2, '  YOU WIN!  ',
                             curses.color_pair(1) | curses.A_BOLD)
        else:
            self.center_text(mid - 2, '  GAME OVER  ',
                             curses.color_pair(2) | curses.A_BOLD)
        self.center_text(mid, f'  Score: {self.score}  ', curses.A_BOLD)
        high = load_high_score(self.name)
        if self.score > high:
            save_high_score(self.name, self.score)
            self.center_text(mid + 1, '  NEW HIGH SCORE!  ',
                             curses.color_pair(3) | curses.A_BOLD)
        else:
            self.center_text(mid + 1, f'  High Score: {high}  ',
                             curses.color_pair(3))
        self.center_text(mid + 3, '  [R] Retry   [Q] Quit  ',
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
        if nh in self.snake:
            self.game_over = True
            return
        self.snake.insert(0, nh)
        if nh == self.food:
            self.score += 1
            self._spawn_food()
        else:
            self.snake.pop()

    def draw(self):
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
                         ' WASD:Move  P:Pause  ESC:Quit ',
                         curses.color_pair(4))


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
        self.safe_addstr(sy + gh + 2, sx, ' WASD:Move  ESC:Quit ',
                         curses.color_pair(4))


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
        dt = gy + int(self.dino_y) - 2
        db = gy + int(self.dino_y)
        dl, dr = self.dino_x + 1, self.dino_x + 2  # tighter dino hitbox
        for obs in self.obstacles:
            ox = int(obs['x'])
            art = obs['art']
            oh = len(art)
            ow = max(len(l) for l in art)
            # Shrink obstacle hitbox by 1 on each side (spaces in art)
            if (dr >= ox + 1 and dl <= ox + ow - 2 and
                    db >= gy - oh + 1 and dt <= gy):
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
        hi = f'HI: {max(self.score, load_high_score(self.name))}'
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
                         'W/Space: Jump   P: Pause   ESC: Quit',
                         curses.color_pair(4))


# ─── Breakout ────────────────────────────────────────────────────────────────

class BreakoutGame(Game):
    name = "breakout"
    min_h = 22
    min_w = 44

    def setup(self):
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
                         ' A/D:Move  Space:Launch  P:Pause  ESC:Quit ',
                         curses.color_pair(4))


# ─── Menu ────────────────────────────────────────────────────────────────────

_GAMES = [
    ("Snake",       "Classic snake - eat food, grow longer",     SnakeGame),
    ("Tetris",      "Stack blocks, clear lines",                 TetrisGame),
    ("2048",        "Slide and merge tiles to reach 2048",       Game2048),
    ("Dino Runner", "Jump over obstacles, survive!",             DinoGame),
    ("Breakout",    "Break all the bricks with a bouncing ball", BreakoutGame),
]

_TITLE = [
    " ╔═╗╦  ╔═╗╦ ╦╔╦╗╔═╗  ╔═╗╔═╗╔╦╗╔═╗╔═╗ ",
    " ║  ║  ╠═╣║ ║ ║║║╣   ║ ╦╠═╣║║║║╣ ╚═╗ ",
    " ╚═╝╩═╝╩ ╩╚═╝═╩╝╚═╝  ╚═╝╩ ╩╩ ╩╚═╝╚═╝ ",
]

_GAME_MAP = {g[0].lower().replace(' ', ''): g[2] for g in _GAMES}
_GAME_MAP.update({'dino': DinoGame, '2048': Game2048})


def _safe(stdscr, y, x, text, attr=0):
    h, w = stdscr.getmaxyx()
    if 0 <= y < h and 0 <= x < w:
        try:
            stdscr.addstr(y, x, text[:max(0, w - x)], attr)
        except curses.error:
            pass


def _run_game(stdscr, cls):
    curses.curs_set(0)
    init_colors()
    while True:
        result = cls(stdscr).run()
        if result != 'retry':
            break


def _menu(stdscr):
    curses.curs_set(0)
    init_colors()
    sel = 0
    stdscr.clear()
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 18 or w < 44:
            _safe(stdscr, h // 2, max(0, (w - 30) // 2),
                  f'Need 44x18 terminal ({w}x{h})', curses.A_BOLD)
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
        for i, (name, desc, cls) in enumerate(_GAMES):
            y = ly + i * 2
            if y + 1 >= h - 2:
                break
            hi = load_high_score(cls.name)
            if i == sel:
                _safe(stdscr, y, bx, ' > ', curses.color_pair(1))
                _safe(stdscr, y, bx + 3, f'{name:<14}',
                      curses.A_BOLD | curses.A_REVERSE)
            else:
                _safe(stdscr, y, bx + 3, f'{name:<14}', curses.A_BOLD)
            sv = Game.has_save(cls.name)
            if sv is not None:
                _safe(stdscr, y, bx + 18, f'[Resume:{sv}]',
                      curses.color_pair(1))
            elif hi > 0:
                _safe(stdscr, y, bx + 18, f'[Best: {hi}]',
                      curses.color_pair(3))
            _safe(stdscr, y + 1, bx + 3, desc[:38], curses.color_pair(4))

        cy = min(h - 2, ly + len(_GAMES) * 2 + 1)
        ctrl = "Up/Down: Select   Enter: Play   Q: Quit"
        _safe(stdscr, cy, max(0, (w - len(ctrl)) // 2), ctrl,
              curses.color_pair(7))
        stdscr.noutrefresh()
        curses.doupdate()

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')):
            sel = (sel - 1) % len(_GAMES)
        elif key in (curses.KEY_DOWN, ord('j')):
            sel = (sel + 1) % len(_GAMES)
        elif key in (curses.KEY_ENTER, 10, 13):
            _run_game(stdscr, _GAMES[sel][2])
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
    if nh in s['snake']:
        s['over'] = True
        return s
    s['snake'].insert(0, nh)
    if nh == s['food']:
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

def _cli_ms_init(size=9, num_mines=10):
    cells = [(r, c) for r in range(size) for c in range(size)]
    mines = set(random.sample(cells, min(num_mines, len(cells) - 1)))
    nums = [[0] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if (r, c) in mines:
                nums[r][c] = -1
                continue
            cnt = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < size and 0 <= nc < size and (nr, nc) in mines:
                        cnt += 1
            nums[r][c] = cnt
    return {'game': 'minesweeper', 'size': size,
            'mines': [list(m) for m in mines], 'nums': nums,
            'revealed': [], 'flagged': [],
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
        elif (r, c) in mines_set:
            s['over'] = True
            revealed |= mines_set
        else:
            stack = [(r, c)]
            while stack:
                cr, cc = stack.pop()
                if (cr, cc) in revealed:
                    continue
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
    lines = [f"MINESWEEPER   Mines left: ~{len(mines_set) - len(flagged)}"]
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


# ─── CLI Dispatcher ──────────────────────────────────────────────────────────

_CLI_GAMES = {
    'snake': (_cli_snake_init, _cli_snake_move, _cli_snake_render),
    '2048': (_cli_2048_init, _cli_2048_move, _cli_2048_render),
    'minesweeper': (_cli_ms_init, _cli_ms_move, _cli_ms_render),
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
                 'minesweeper': _cli_ms_render}
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
            print()
            print('Start a game:  play cli start <game>')
            print('Interactive:   ! play  (full-screen curses games)')
        return

    cmd = args[0].lower()

    if cmd == 'start':
        name = args[1].lower() if len(args) > 1 else ''
        if name in ('ms', 'mines'):
            name = 'minesweeper'
        if name not in _CLI_GAMES:
            print(f'Unknown game: {name}')
            print('Available: snake, 2048, minesweeper')
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

    else:
        print(f'Unknown: {cmd}')
        print('Commands: start <game> | up/down/left/right | reveal/flag <r> <c> | show | quit')


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    locale.setlocale(locale.LC_ALL, '')
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
        _curses_wrapper(lambda s, c=cls: (init_colors(), _run_game(s, c)), cmd)
    else:
        print(f'Unknown game: {cmd}')
        print('Available: ' + ', '.join(n for n, _, _ in _GAMES))
        sys.exit(1)


if __name__ == '__main__':
    main()
