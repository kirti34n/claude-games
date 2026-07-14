"""Tetris."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game

# SRS piece definitions: each piece has 4 rotation states (0, R, 2, L) as a
# list of (row, col) cell coordinates inside a fixed bounding box (row 0 is
# the top of the box). These are the canonical Tetris Guideline SRS shapes,
# not a naive matrix rotation, which is what makes real wall kicks (and
# therefore floor kicks and T-spins) possible.
_SHAPES = {
    'I': {
        '0': [(1, 0), (1, 1), (1, 2), (1, 3)],
        'R': [(0, 2), (1, 2), (2, 2), (3, 2)],
        '2': [(2, 0), (2, 1), (2, 2), (2, 3)],
        'L': [(0, 1), (1, 1), (2, 1), (3, 1)],
    },
    'O': {
        '0': [(0, 0), (0, 1), (1, 0), (1, 1)],
        'R': [(0, 0), (0, 1), (1, 0), (1, 1)],
        '2': [(0, 0), (0, 1), (1, 0), (1, 1)],
        'L': [(0, 0), (0, 1), (1, 0), (1, 1)],
    },
    'T': {
        '0': [(0, 1), (1, 0), (1, 1), (1, 2)],
        'R': [(0, 1), (1, 1), (1, 2), (2, 1)],
        '2': [(1, 0), (1, 1), (1, 2), (2, 1)],
        'L': [(0, 1), (1, 0), (1, 1), (2, 1)],
    },
    'S': {
        '0': [(0, 1), (0, 2), (1, 0), (1, 1)],
        'R': [(0, 1), (1, 1), (1, 2), (2, 2)],
        '2': [(1, 1), (1, 2), (2, 0), (2, 1)],
        'L': [(0, 0), (1, 0), (1, 1), (2, 1)],
    },
    'Z': {
        '0': [(0, 0), (0, 1), (1, 1), (1, 2)],
        'R': [(0, 2), (1, 1), (1, 2), (2, 1)],
        '2': [(1, 0), (1, 1), (2, 1), (2, 2)],
        'L': [(0, 1), (1, 0), (1, 1), (2, 0)],
    },
    'J': {
        '0': [(0, 0), (1, 0), (1, 1), (1, 2)],
        'R': [(0, 1), (0, 2), (1, 1), (2, 1)],
        '2': [(1, 0), (1, 1), (1, 2), (2, 2)],
        'L': [(0, 1), (1, 1), (2, 0), (2, 1)],
    },
    'L': {
        '0': [(0, 2), (1, 0), (1, 1), (1, 2)],
        'R': [(0, 1), (1, 1), (2, 1), (2, 2)],
        '2': [(1, 0), (1, 1), (1, 2), (2, 0)],
        'L': [(0, 0), (0, 1), (1, 1), (2, 1)],
    },
}
_BOX = {'I': 4, 'O': 2}  # bounding box side length; everything else is 3


def _box_size(piece_type):
    return _BOX.get(piece_type, 3)


# One color pair per piece, all seven distinct (tetris-7): the previous
# code mapped both O and L to pair 3. Some themes only expose 4 unique
# colors across their 7 pairs (retro, ocean), so a same-color collision
# between two pieces there is a theme palette limit, not a mapping bug.
_PIECE_COLORS = {'S': 1, 'Z': 2, 'O': 3, 'I': 4, 'T': 5, 'J': 6, 'L': 7}

_ROT_CW = {'0': 'R', 'R': '2', '2': 'L', 'L': '0'}

# SRS wall kick tables: (from_state, to_state) -> ordered list of (dx, dy)
# offsets to try. dy is positive DOWNWARD (board convention); the published
# Guideline table uses positive-up y, so every dy below is the negation of
# the canonical value. The O piece needs no table (it never kicks).
_KICKS_JLSTZ = {
    ('0', 'R'): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    ('R', '0'): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    ('R', '2'): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    ('2', 'R'): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    ('2', 'L'): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    ('L', '2'): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    ('L', '0'): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    ('0', 'L'): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
}
_KICKS_I = {
    ('0', 'R'): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    ('R', '0'): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    ('R', '2'): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
    ('2', 'R'): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    ('2', 'L'): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    ('L', '2'): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    ('L', '0'): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    ('0', 'L'): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
}

_TICK_MS = 16
_LOCK_DELAY_MS = 500
_MAX_LOCK_RESETS = 15  # Extended Placement cap: after this many resets a
                        # grounded piece locks on schedule no matter what.
# curses delivers no key-up event at all, only getch() codes for actual
# keydown events (a genuine physical press, or the OS's own auto-repeat
# resending the same code after its own repeat-start delay, commonly
# 500ms+ on Windows/X11). There is therefore no way to observe "is this
# key still held right now": any attempt to infer holding from how
# recently an event arrived (a "recency window") is indistinguishable from
# noise at exactly the timescales that matter, and produced two measured
# bugs in an earlier version of this file: a single Down press reading as
# a 4-row hold because four consecutive 16ms ticks all landed inside a
# 50ms recency window, and a released key continuing to read as held for
# the length of that window so the piece kept sliding after the finger
# left the key.
#
# The honest model (SPEC 2.1, this is a withdrawn requirement, not a
# design choice we're free to relitigate): react to key EVENTS only, one
# shift/soft-drop per event, applied on the tick inside update() (never
# inside handle_input so a burst of polls before a tick can't multiply the
# effect). _RATE_CAP_MS then bounds how often an event may actually take
# effect, so a fast repeat stream (or a mashed key) cannot exceed the
# guideline auto-repeat rate. The delay before a genuinely held key's
# SECOND shift is therefore whatever delay the OS's own key-repeat takes
# to resend the keycode: that is the terminal's key-repeat delay, it
# belongs to the user's OS, and it is not something faked here.
_RATE_CAP_MS = 33
_HARD_DROP_REARM_MS = 150


class TetrisGame(Game):
    name = "tetris"
    ROWS, COLS = 20, 10
    BUFFER = 2  # hidden rows above the visible field; enables Lock Out
    TOTAL_ROWS = ROWS + BUFFER
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
            self.rot = saved['rot']
            self.cur_y = saved['cy']
            self.cur_x = saved['cx']
            self.bag = saved['bag']
            self._reset_timers()
            return
        self.board = [[0] * self.COLS for _ in range(self.TOTAL_ROWS)]
        self.score = self.lines = 0
        self.level = 1
        self.bag = []
        self.next_type = self._draw_bag()
        self._reset_timers()
        self._spawn()

    def _reset_timers(self):
        self.gravity_timer = 0
        self.lock_timer = 0
        self.lock_resets = 0
        # Rate-cap cooldowns for the two event-driven continuous inputs
        # (shift, soft drop). Starting each at the cap means the very
        # first key event is never delayed: a lone tap always acts
        # immediately, and only a SECOND event arriving inside the cap
        # window gets held back.
        self._shift_cooldown = _RATE_CAP_MS
        self._drop_cooldown = _RATE_CAP_MS
        self._hard_drop_armed = True
        self._hard_drop_idle = _HARD_DROP_REARM_MS

    def get_save_data(self):
        return {'board': self.board, 'score': self.score,
                'lines': self.lines, 'level': self.level,
                'ct': self.cur_type, 'nt': self.next_type, 'rot': self.rot,
                'cy': self.cur_y, 'cx': self.cur_x, 'bag': self.bag}

    def _draw_bag(self):
        # 7-bag randomizer (tetris-3): every piece appears exactly once
        # per shuffled bag of 7, so droughts and floods are bounded instead
        # of the old uniform random.choice, which could repeat or omit a
        # piece for arbitrarily long stretches.
        if not self.bag:
            self.bag = list(_SHAPES.keys())
            random.shuffle(self.bag)
        return self.bag.pop()

    def _gravity_ms(self):
        # Guideline level curve: (0.8 - (level-1)*0.007) ** (level-1)
        # seconds/row, giving 1000ms at level 1. Floored at 50ms so high
        # levels stay playable instead of the curve's true near-zero tail.
        n = min(self.level - 1, 20)
        secs = (0.8 - n * 0.007) ** n
        return max(50, int(secs * 1000))

    def _collides(self, shape, py, px):
        for r, c in shape:
            ny, nx = py + r, px + c
            if nx < 0 or nx >= self.COLS or ny < 0 or ny >= self.TOTAL_ROWS:
                return True
            if self.board[ny][nx]:
                return True
        return False

    def _spawn(self):
        self.cur_type = self.next_type
        self.next_type = self._draw_bag()
        self.rot = '0'
        size = _box_size(self.cur_type)
        # Every non-I piece's spawn state occupies local rows 0-1 of its
        # box; cur_y = BUFFER puts both of those rows at or below the top
        # visible line, so the WHOLE piece is visible on the spawn frame
        # (the hidden buffer still exists above it for Lock Out purposes,
        # just unused by any piece's spawn orientation). The old
        # BUFFER - 1 put local row 0 inside the hidden buffer, so 6 of the
        # 7 pieces (everything but I) rendered with 1-2 of their 4 cells
        # missing on the spawn frame, e.g. a spawned S or O looked like an
        # unidentifiable 2-cell pair.
        self.cur_y = self.BUFFER
        self.cur_x = (self.COLS - size) // 2
        self.lock_timer = 0
        self.lock_resets = 0
        self.gravity_timer = 0
        if self._collides(_SHAPES[self.cur_type][self.rot], self.cur_y, self.cur_x):
            self.game_over = True  # Block Out: no room to spawn

    def _register_move(self):
        # Extended Placement lock delay: any successful move or rotation
        # resets the lock countdown while the piece is resting, up to
        # _MAX_LOCK_RESETS times, so deliberate maneuvering (including
        # T-spins) has real breathing room without granting infinite time.
        shape = _SHAPES[self.cur_type][self.rot]
        if self._collides(shape, self.cur_y + 1, self.cur_x):
            if self.lock_resets < _MAX_LOCK_RESETS:
                self.lock_timer = 0
                self.lock_resets += 1
        else:
            self.lock_timer = 0
            self.lock_resets = 0

    def _try_shift(self, dx):
        shape = _SHAPES[self.cur_type][self.rot]
        if not self._collides(shape, self.cur_y, self.cur_x + dx):
            self.cur_x += dx
            self._register_move()
            return True
        return False

    def _try_rotate(self):
        if self.cur_type == 'O':
            return
        frm, to = self.rot, _ROT_CW[self.rot]
        kicks = _KICKS_I if self.cur_type == 'I' else _KICKS_JLSTZ
        shape = _SHAPES[self.cur_type][to]
        for dx, dy in kicks[(frm, to)]:
            ny, nx = self.cur_y + dy, self.cur_x + dx
            if not self._collides(shape, ny, nx):
                self.rot = to
                self.cur_y, self.cur_x = ny, nx
                self._register_move()
                return

    def _hard_drop(self):
        shape = _SHAPES[self.cur_type][self.rot]
        dist = 0
        while not self._collides(shape, self.cur_y + 1, self.cur_x):
            self.cur_y += 1
            dist += 1
        self.score += dist * 2
        self._lock()

    def _lock(self):
        shape = _SHAPES[self.cur_type][self.rot]
        color = _PIECE_COLORS[self.cur_type]
        # Guideline Lock Out requires the ENTIRE piece to be above the
        # visible field, not just any one cell of it: using the piece's top
        # row here topped a stack out as soon as its highest cell grazed
        # the buffer, well before a player would expect game over.
        bottom_row = max(self.cur_y + r for r, c in shape)
        for r, c in shape:
            self.board[self.cur_y + r][self.cur_x + c] = color
        if bottom_row < self.BUFFER:
            self.game_over = True  # Lock Out
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
        if cleared:
            self.lines += cleared
            self.score += [0, 100, 300, 500, 800][min(cleared, 4)] * self.level
            self.level = self.lines // 10 + 1
        self.lock_timer = 0
        self.lock_resets = 0
        if not self.game_over:
            self._spawn()

    def get_timeout(self):
        return _TICK_MS

    def handle_input(self, key):
        # Discrete, edge-triggered actions only. Continuous movement
        # (shift, soft drop) lives in update(), gated on held state.
        if key == curses.KEY_UP or key == ord('w'):
            self._try_rotate()
        elif key == ord(' '):
            if self._hard_drop_armed:
                self._hard_drop_armed = False
                self._hard_drop()

    def _update_shift(self):
        # Event-driven, tick-applied, rate-capped: see the comment block
        # above _RATE_CAP_MS. self.keys reflects exactly the key events
        # received since the last update(), so held() here is "did a shift
        # event arrive for this tick", never an inferred hold state.
        self._shift_cooldown += _TICK_MS
        left = self.held(curses.KEY_LEFT, ord('a'))
        right = self.held(curses.KEY_RIGHT, ord('d'))
        direction = -1 if left and not right else (1 if right and not left else 0)
        if direction and self._shift_cooldown >= _RATE_CAP_MS:
            # Bank the overshoot past the cap instead of zeroing it: ticks
            # only advance the cooldown in whole _TICK_MS steps, so a hard
            # reset to 0 throws away however many ms this tick already
            # ran past _RATE_CAP_MS, forcing every repeat to wait a full
            # extra tick (33ms rounds up to 48ms, not honouring the cap).
            # Carrying the remainder into the next cycle means real elapsed
            # time is never lost, so the repeats settle on a long-run
            # average of exactly _RATE_CAP_MS (mostly 32ms gaps with an
            # occasional 48ms one, averaging to 33ms), not 48ms every time.
            self._shift_cooldown -= _RATE_CAP_MS
            self._try_shift(direction)

    def _update_fall(self):
        shape = _SHAPES[self.cur_type][self.rot]
        # Soft drop: event-driven and rate-capped exactly like shift, so a
        # single Down press advances the piece by exactly one row and
        # awards exactly one point. See _RATE_CAP_MS: there is no way to
        # tell a genuinely held key apart from a fast repeat stream, so a
        # held key advances at the capped rate rather than once per tick.
        self._drop_cooldown += _TICK_MS
        if self.held(curses.KEY_DOWN, ord('s')):
            if self._drop_cooldown >= _RATE_CAP_MS:
                # See the matching comment in _update_shift: bank the
                # overshoot instead of zeroing it, so the cap is honoured
                # at its true 33ms average instead of rounding up to 48ms.
                self._drop_cooldown -= _RATE_CAP_MS
                if not self._collides(shape, self.cur_y + 1, self.cur_x):
                    self.cur_y += 1
                    self.score += 1
                    self._register_move()
            self.gravity_timer = 0
            return
        self.gravity_timer += _TICK_MS
        gms = self._gravity_ms()
        if self.gravity_timer >= gms:
            self.gravity_timer -= gms
            if not self._collides(shape, self.cur_y + 1, self.cur_x):
                self.cur_y += 1
                # Natural gravity is not a player action: unlike a shift or
                # rotation, it must not spend one of the 15 Extended
                # Placement lock resets the instant a piece first touches
                # down. _update_lock() already starts the lock-delay
                # countdown fresh (lock_timer reads 0 there whenever the
                # piece isn't resting) the moment it becomes newly grounded;
                # no help is needed here, and calling _register_move() used
                # to burn a reset before the player had touched anything.

    def _update_lock(self):
        shape = _SHAPES[self.cur_type][self.rot]
        if self._collides(shape, self.cur_y + 1, self.cur_x):
            self.lock_timer += _TICK_MS
            if self.lock_timer >= _LOCK_DELAY_MS:
                self._lock()
        else:
            self.lock_timer = 0

    def update(self):
        self._update_shift()
        self._update_fall()
        if self.game_over:
            return
        self._update_lock()
        # Re-arm hard drop only after Space has been genuinely absent for
        # longer than any real OS auto-repeat gap (tetris-4 / tetris-5's
        # sibling bug: without this a held key chain-drops every piece).
        if self.held(ord(' ')):
            self._hard_drop_idle = 0
        else:
            self._hard_drop_idle += _TICK_MS
            if self._hard_drop_idle >= _HARD_DROP_REARM_MS:
                self._hard_drop_armed = True

    def draw(self):
        bw = self.COLS * 2 + 2
        sx = max(0, (self.w - bw - 16) // 2)
        sy = max(0, (self.h - self.ROWS - 2) // 2)
        self.draw_box(sy, sx, self.ROWS + 2, bw)

        for r in range(self.BUFFER, self.TOTAL_ROWS):
            for c, cell in enumerate(self.board[r]):
                if cell:
                    self.safe_addstr(sy + 1 + (r - self.BUFFER), sx + 1 + c * 2,
                                     '[]', curses.color_pair(cell) | curses.A_BOLD)

        shape = _SHAPES[self.cur_type][self.rot]

        # Ghost: project the current piece straight down.
        gy = self.cur_y
        while not self._collides(shape, gy + 1, self.cur_x):
            gy += 1
        if gy != self.cur_y:
            col = _PIECE_COLORS[self.cur_type]
            for r, c in shape:
                ny = gy + r
                if ny >= self.BUFFER:
                    self.safe_addstr(sy + 1 + (ny - self.BUFFER),
                                     sx + 1 + (self.cur_x + c) * 2,
                                     '..', curses.color_pair(col))

        # Current piece. Cells still inside the hidden buffer at spawn are
        # simply not drawn, which is what a real buffer zone looks like.
        col = _PIECE_COLORS[self.cur_type]
        for r, c in shape:
            ny = self.cur_y + r
            if ny >= self.BUFFER:
                self.safe_addstr(sy + 1 + (ny - self.BUFFER),
                                 sx + 1 + (self.cur_x + c) * 2, '[]',
                                 curses.color_pair(col) | curses.A_BOLD)

        # Panel
        px = sx + bw + 2
        self.safe_addstr(sy, px, 'TETRIS', curses.A_BOLD)
        self.safe_addstr(sy + 2, px, f'Score: {self.score}')
        self.safe_addstr(sy + 3, px, f'Lines: {self.lines}')
        self.safe_addstr(sy + 4, px, f'Level: {self.level}')
        self.safe_addstr(sy + 6, px, 'Next:')
        nc = _PIECE_COLORS[self.next_type]
        for r, c in _SHAPES[self.next_type]['0']:
            self.safe_addstr(sy + 7 + r, px + c * 2, '[]',
                             curses.color_pair(nc) | curses.A_BOLD)

        # A plain joined string here always overflowed at this class's own
        # min_w=40 (73 chars into 38 usable columns), truncating mid-word
        # and losing Pause/Help/Quit entirely (INFRA-7). Passing a
        # priority-ordered list instead lets render.status_bar guarantee
        # every hint it draws is a complete, uncut segment: it keeps
        # whichever prefix fits and drops the rest cleanly, the same way
        # Minesweeper already drops '?:Help' by hand at min_w, instead of
        # rendering a corrupted fragment of the next one.
        self.draw_status_bar(['A/D:Move', 'W:Rotate', 'S:Soft drop',
                               'SPC:Hard drop', 'P:Pause', '?:Help',
                               'ESC:Quit'])

    def get_controls(self):
        return [('A/D', 'Move left/right'), ('W', 'Rotate'),
                ('S', 'Soft drop'), ('Space', 'Hard drop'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Lines', self.lines), ('Level', self.level)]
