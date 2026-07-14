"""2048."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game


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
            # reached_2048 replaces the old sticky 'won' flag: it only
            # drives the in-play banner, never the end-of-game screen (see
            # 2048-1). Fall back to the legacy key for old saves.
            self.reached_2048 = saved.get('reached_2048', saved.get('won', False))
            return
        self.grid = [[0] * self.SIZE for _ in range(self.SIZE)]
        self.score = 0
        self.reached_2048 = False
        self._add_tile()
        self._add_tile()

    def get_save_data(self):
        return {'grid': self.grid, 'score': self.score,
                'reached_2048': self.reached_2048}

    def _add_tile(self):
        empty = [(r, c) for r in range(self.SIZE) for c in range(self.SIZE)
                 if self.grid[r][c] == 0]
        if empty:
            r, c = random.choice(empty)
            self.grid[r][c] = 4 if random.random() < 0.1 else 2

    def _slide_track(self, vals):
        """vals: SIZE values (0 for empty) in slide order, index 0 nearest
        the wall the row/column is sliding toward. Returns the compacted
        result plus enough bookkeeping to animate it: new_vals, points,
        moves (from_idx, to_idx, value) for every source tile, and merges
        (the set of to_idx slots where two tiles combined)."""
        tiles = [(i, v) for i, v in enumerate(vals) if v]
        new_vals = [0] * self.SIZE
        moves = []
        merges = []
        i, dest, pts = 0, 0, 0
        while i < len(tiles):
            idx_a, val_a = tiles[i]
            if i + 1 < len(tiles) and tiles[i + 1][1] == val_a:
                idx_b, _ = tiles[i + 1]
                moves.append((idx_a, dest, val_a))
                moves.append((idx_b, dest, val_a))
                merged = val_a * 2
                new_vals[dest] = merged
                pts += merged
                merges.append(dest)
                i += 2
            else:
                moves.append((idx_a, dest, val_a))
                new_vals[dest] = val_a
                i += 1
            dest += 1
        return new_vals, pts, moves, merges

    def _move(self, d):
        old = [row[:] for row in self.grid]
        pts = 0
        moves = []
        merge_cells = set()

        def process_line(cells):
            vals = [self.grid[r][c] for r, c in cells]
            new_vals, p, line_moves, merges = self._slide_track(vals)
            for from_idx, to_idx, val in line_moves:
                fr, fc = cells[from_idx]
                tr, tc = cells[to_idx]
                moves.append((fr, fc, tr, tc, val))
            for to_idx in merges:
                merge_cells.add(cells[to_idx])
            for i, (r, c) in enumerate(cells):
                self.grid[r][c] = new_vals[i]
            return p

        if d == 'left':
            for r in range(self.SIZE):
                pts += process_line([(r, c) for c in range(self.SIZE)])
        elif d == 'right':
            for r in range(self.SIZE):
                pts += process_line([(r, c) for c in range(self.SIZE - 1, -1, -1)])
        elif d == 'up':
            for c in range(self.SIZE):
                pts += process_line([(r, c) for r in range(self.SIZE)])
        elif d == 'down':
            for c in range(self.SIZE):
                pts += process_line([(r, c) for r in range(self.SIZE - 1, -1, -1)])

        changed = self.grid != old
        if changed:
            self.score += pts
            self._animate_move(moves, merge_cells)
            self._add_tile()
            if any(self.grid[r][c] == 2048
                   for r in range(self.SIZE) for c in range(self.SIZE)):
                self.reached_2048 = True
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
        # Edge-triggered discrete action: one slide per keypress, no
        # cooldown, matches canonical 2048 exactly.
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

    def _layout(self):
        cw = 7
        gw = cw * self.SIZE + self.SIZE + 1
        gh = 3 * self.SIZE + self.SIZE + 1
        sx = max(0, (self.w - gw) // 2)
        sy = max(0, (self.h - gh - 4) // 2)
        return cw, gw, gh, sx, sy

    def _cell_pos(self, grid_sy, sx, cw, r, c):
        # The content sub-row (the middle of the 3-row-tall cell).
        return grid_sy + 1 + r * 4 + 1, sx + 1 + c * (cw + 1)

    def _draw_header(self, sx, sy, gw):
        self.safe_addstr(sy, sx, ' 2 0 4 8 ', curses.A_BOLD | curses.A_REVERSE)
        sc = f'Score: {self.score}'
        self.safe_addstr(sy, sx + gw - len(sc), sc,
                         curses.color_pair(3) | curses.A_BOLD)

    def _draw_grid_shell(self, sy, sx, cw, gh):
        """Border and blank cell interiors only, no tile text. Shared by
        draw() and the slide/merge animation so the frame is identical."""
        top = '┌' + ('─' * cw + '┬') * (self.SIZE - 1) + '─' * cw + '┐'
        self.safe_addstr(sy, sx, top)
        for r in range(self.SIZE):
            ry = sy + 1 + r * 4
            for sub in range(3):
                self.safe_addstr(ry + sub, sx, '│')
                for c in range(self.SIZE):
                    cx = sx + 1 + c * (cw + 1)
                    self.safe_addstr(ry + sub, cx, ' ' * cw)
                    self.safe_addstr(ry + sub, cx + cw, '│')
            if r < self.SIZE - 1:
                sep = '├' + ('─' * cw + '┼') * (self.SIZE - 1) + '─' * cw + '┤'
                self.safe_addstr(ry + 3, sx, sep)
            else:
                bot = '└' + ('─' * cw + '┴') * (self.SIZE - 1) + '─' * cw + '┘'
                self.safe_addstr(ry + 3, sx, bot)

    def _animate_move(self, moves, merge_cells):
        """Slide every source tile toward its destination over a few real
        frames, then pop the merged value at merge cells on the last
        frame. No-op (falls straight through) when there is nothing to
        animate or when self.net is set, per the animate() contract."""
        if not moves or getattr(self, 'net', None) is not None:
            return
        cw, gw, gh, sx, sy = self._layout()
        grid_sy = sy + 2
        frame_delays = (40, 40, 40, 60)
        n = len(frame_delays)
        step = [0]
        for _ in self.animate(frame_delays):
            step[0] += 1
            t = step[0] / n
            last = step[0] == n
            self.stdscr.erase()
            self._draw_header(sx, sy, gw)
            self._draw_grid_shell(grid_sy, sx, cw, gh)
            popped = set()
            for fr, fc, tr, tc, val in moves:
                if last and (tr, tc) in merge_cells:
                    if (tr, tc) in popped:
                        continue
                    popped.add((tr, tc))
                    y, x = self._cell_pos(grid_sy, sx, cw, tr, tc)
                    v = self.grid[tr][tc]
                    self.safe_addstr(y, x, str(v).center(cw),
                                     self._tile_attr(v) | curses.A_REVERSE)
                    continue
                y0, x0 = self._cell_pos(grid_sy, sx, cw, fr, fc)
                y1, x1 = self._cell_pos(grid_sy, sx, cw, tr, tc)
                y = round(y0 + (y1 - y0) * t)
                x = round(x0 + (x1 - x0) * t)
                self.safe_addstr(y, x, str(val).center(cw), self._tile_attr(val))

    def draw(self):
        cw, gw, gh, sx, sy = self._layout()
        self._draw_header(sx, sy, gw)
        grid_sy = sy + 2
        self._draw_grid_shell(grid_sy, sx, cw, gh)
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                v = self.grid[r][c]
                if v:
                    y, x = self._cell_pos(grid_sy, sx, cw, r, c)
                    self.safe_addstr(y, x, str(v).center(cw), self._tile_attr(v))
        if self.reached_2048:
            self.center_text(grid_sy + gh + 1, '  You reached 2048! Keep going!  ',
                             curses.color_pair(3) | curses.A_BOLD)
        self.draw_status_bar('WASD:Move ?:Help Esc:Quit')

    def get_controls(self):
        return [('WASD', 'Slide tiles'), ('ESC', 'Quit')]

    def get_stats(self):
        max_tile = max(self.grid[r][c] for r in range(self.SIZE)
                       for c in range(self.SIZE))
        return [('Best Tile', max_tile)]
