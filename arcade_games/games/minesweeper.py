"""Minesweeper (Interactive)."""
import json
import random
import time

try:
    import curses
except ImportError:
    curses = None

from ..game import Game
from .. import config


class MinesweeperGame(Game):
    name = "minesweeper_i"
    min_h = 22
    min_w = 40
    supports_difficulty = True
    # self.score is a revealed-cell count, which saturates across
    # difficulties instead of comparing like with like (a 381-cell Hard win
    # permanently outranks any Easy/Medium win and neither can register
    # again). The real canonical record is the per-difficulty best time
    # tracked below (_best_times_path/_record_best_time); opt this game out
    # of the base class's single cross-difficulty high score entirely
    # instead of computing and saving a number that is actively misleading
    # on the game-over screen (mines-5).
    track_high_score = False

    _NUM_COLORS = {1: 6, 2: 1, 3: 2, 4: 5, 5: 3, 6: 4, 7: 7, 8: 7}
    _NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                  (0, 1), (1, -1), (1, 0), (1, 1)]

    def setup(self):
        self._load_best_times()
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
            self.first_reveal = saved['first_reveal']
            elapsed = saved.get('elapsed', 0)
            # Rebase the wall clock so the elapsed time at save is preserved
            # across a resume, without counting time the app was closed.
            self.timer_start = None if self.first_reveal else time.monotonic() - elapsed
            self.difficulty = saved.get('difficulty', self.difficulty)
            self.detonated = set()
            self._new_best = False
            self._fit_bounds()
            return
        cfg = {'easy': (9, 9, 10), 'medium': (16, 16, 40), 'hard': (16, 30, 99)}
        self.rows, self.cols, self.num_mines = cfg.get(self.difficulty, (9, 9, 10))
        self.cur_r = self.rows // 2
        self.cur_c = self.cols // 2
        self.score = 0
        self.first_reveal = True
        self.timer_start = None
        self.detonated = set()
        self._new_best = False
        self.grid = [[0] * self.cols for _ in range(self.rows)]
        self.revealed = [[False] * self.cols for _ in range(self.rows)]
        self.flagged = [[False] * self.cols for _ in range(self.rows)]
        self._fit_bounds()

    def _fit_bounds(self):
        # The hard board is 30 cols = 60 render columns, far wider than the
        # class min_w=40, so gate on the real board size to avoid clipping.
        self.min_w = max(40, self.cols * 2 + 4)
        self.min_h = max(22, self.rows + 6)

    def on_resize(self):
        self._fit_bounds()

    def _best_times_path(self):
        return config.CONFIG_DIR / 'minesweeper_best_times.json'

    def _load_best_times(self):
        # Per-difficulty best clear time (seconds), kept separate from the
        # base class's single cross-difficulty config.save_high_score(name,
        # score): that mechanism compares raw self.score (revealed-cell
        # count) across ALL difficulties for one 'minesweeper_i' key, so a
        # single Hard win (up to 381 safe cells) permanently outranks any
        # Easy or Medium win (at most 71) and neither can ever register
        # again. Time-to-clear, tracked per difficulty here, is the
        # canonical Minesweeper record.
        try:
            self._best_times = json.loads(self._best_times_path().read_text())
        except Exception:
            self._best_times = {}

    def _record_best_time(self):
        elapsed = self._elapsed()
        best = self._best_times.get(self.difficulty)
        if best is None or elapsed < best:
            self._best_times[self.difficulty] = elapsed
            self._new_best = True
            try:
                config._atomic_write_json(self._best_times_path(), self._best_times)
            except OSError:
                pass

    def _elapsed(self):
        # Real wall clock armed on the first reveal, capped at 999 the way
        # the physical Minesweeper timer digits are. Not derived from a
        # tick counter, so it cannot be stopped or desynced by pause, a
        # terminal resize, or a stalled/slow frame.
        if self.timer_start is None:
            return 0
        return min(999, int(time.monotonic() - self.timer_start))

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

    def _detonate(self, r, c):
        self.revealed[r][c] = True
        self.detonated.add((r, c))
        self.game_over = True

    def _reveal_cell(self, r, c):
        if self.revealed[r][c] or self.flagged[r][c]:
            return
        if self.first_reveal:
            self.first_reveal = False
            self.timer_start = time.monotonic()
            self._place_mines(r, c)
        if self.grid[r][c] == -1:
            self._detonate(r, c)
            return
        self._flood_reveal(r, c)
        self._check_win()

    def _chord(self, r, c):
        # Chording: reveal on an already-opened numbered cell. If the
        # number of flags on its 8 neighbors matches the cell's number,
        # every remaining unflagged neighbor is revealed at once, exactly
        # as if each had been clicked individually. This is the core
        # speed mechanic of real Minesweeper; without it every number
        # must be opened cell by cell.
        v = self.grid[r][c]
        if not self.revealed[r][c] or v <= 0:
            return
        flags = sum(1 for dr, dc in self._NEIGHBORS
                    if 0 <= r + dr < self.rows and 0 <= c + dc < self.cols
                    and self.flagged[r + dr][c + dc])
        if flags != v:
            return
        for dr, dc in self._NEIGHBORS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                continue
            if self.flagged[nr][nc] or self.revealed[nr][nc]:
                continue
            if self.grid[nr][nc] == -1:
                self._detonate(nr, nc)
            else:
                self._flood_reveal(nr, nc)
        if not self.game_over:
            self._check_win()

    def _check_win(self):
        unrevealed_safe = sum(
            1 for rr in range(self.rows) for cc in range(self.cols)
            if not self.revealed[rr][cc] and self.grid[rr][cc] != -1)
        if unrevealed_safe == 0:
            self.won = True
            self.game_over = True
            # Auto-flag every remaining mine, matching canonical behavior.
            for rr in range(self.rows):
                for cc in range(self.cols):
                    if self.grid[rr][cc] == -1:
                        self.flagged[rr][cc] = True
            self._record_best_time()

    def get_timeout(self):
        # Not a game clock: update() is a no-op and every state change is
        # still edge-triggered in handle_input(), one action per keypress.
        # A blocking -1 timeout used to mean draw() (and therefore the
        # header's real wall-clock "Time:Ns") only ran when a key arrived,
        # so the displayed timer visibly froze between keypresses and only
        # jumped forward on the next move. This just sets the poll/redraw
        # cadence so the display stays live; get_timeout() capping poll_ms
        # at 20ms in the run loop means draw() still runs every ~20ms
        # regardless of the number returned here.
        return 250

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
            r, c = self.cur_r, self.cur_c
            if self.revealed[r][c]:
                self._chord(r, c)
            else:
                self._reveal_cell(r, c)
        elif key in (ord('f'), ord('F')):
            if not self.revealed[self.cur_r][self.cur_c]:
                self.flagged[self.cur_r][self.cur_c] = \
                    not self.flagged[self.cur_r][self.cur_c]

    def update(self):
        pass  # all state changes are edge-triggered in handle_input

    def draw(self):
        show_mines = self.game_over
        cell_w = 2
        grid_w = self.cols * cell_w
        sx = max(1, (self.w - grid_w) // 2)
        sy = max(2, (self.h - self.rows - 4) // 2)

        flags = sum(self.flagged[r][c]
                    for r in range(self.rows) for c in range(self.cols))
        elapsed = self._elapsed()
        header = f' MINESWEEPER  Mines:{self.num_mines - flags}  Time:{elapsed}s '
        self.safe_addstr(sy - 2, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        best = self._best_times.get(self.difficulty)
        best_str = f'{best}s' if best is not None else '--'
        diff_label = f'[{self.difficulty.upper()} {self.rows}x{self.cols}]  Best:{best_str}'
        self.safe_addstr(sy - 1, max(0, (self.w - len(diff_label)) // 2),
                         diff_label, curses.color_pair(4))

        for r in range(self.rows):
            for c in range(self.cols):
                is_cursor = (r == self.cur_r and c == self.cur_c)
                rev = curses.A_REVERSE if is_cursor else 0
                v = self.grid[r][c]
                if self.flagged[r][c] and not self.revealed[r][c]:
                    if self.game_over and not self.won and v != -1:
                        # A flag that turned out to be on a safe cell.
                        ch, attr = 'X', curses.color_pair(2) | curses.A_BOLD | rev
                    else:
                        ch, attr = 'F', curses.color_pair(2) | curses.A_BOLD | rev
                elif not self.revealed[r][c]:
                    if show_mines and v == -1:
                        exploded = curses.A_REVERSE if (r, c) in self.detonated else 0
                        ch, attr = '*', curses.color_pair(2) | curses.A_BOLD | exploded | rev
                    else:
                        ch, attr = '#', curses.color_pair(7) | rev
                else:
                    if v == -1:
                        exploded = curses.A_REVERSE if (r, c) in self.detonated else 0
                        ch, attr = '*', curses.color_pair(2) | curses.A_BOLD | exploded | rev
                    elif v == 0:
                        ch, attr = '.', curses.color_pair(7) | rev
                    else:
                        pair = self._NUM_COLORS.get(v, 7)
                        ch, attr = str(v), curses.color_pair(pair) | curses.A_BOLD | rev
                self.safe_addstr(sy + r, sx + c * cell_w, ch, attr)

        # List form (not a plain string): at Minesweeper's own min_w=40 the
        # plain string had to drop '?:Help' by hand to fit, leaving players
        # with no way to discover the help overlay (INFRA-7). The list form
        # keeps both escape hatches ('Esc:Quit' and '?:Help') first and
        # drops whole ordinary segments instead, growing back in as the
        # board (and therefore min_w) grows on medium/hard.
        self.draw_status_bar(['WASD:Move', 'Space:Reveal', 'F:Flag',
                               'Esc:Quit', '?:Help'])

    def get_controls(self):
        return [('WASD/Arrows', 'Move cursor'),
                ('Space', 'Reveal cell (chord if already open)'),
                ('F', 'Toggle flag'), ('P', 'Pause'), ('ESC', 'Quit / save')]

    def get_stats(self):
        elapsed = self._elapsed()
        flags = sum(self.flagged[r][c]
                    for r in range(self.rows) for c in range(self.cols))
        best = self._best_times.get(self.difficulty)
        stats = [('Time', f'{elapsed}s'),
                 ('Best', f'{best}s' if best is not None else 'none'),
                 ('Flags', f'{flags}/{self.num_mines}'), ('Cells', self.score)]
        if self._new_best:
            stats.append(('Record', 'NEW BEST TIME!'))
        return stats

    def get_save_data(self):
        return {'rows': self.rows, 'cols': self.cols, 'mines': self.num_mines,
                'grid': self.grid, 'revealed': self.revealed,
                'flagged': self.flagged, 'cur_r': self.cur_r, 'cur_c': self.cur_c,
                'score': self.score, 'elapsed': self._elapsed(),
                'first_reveal': self.first_reveal,
                'difficulty': self.difficulty}
