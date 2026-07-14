"""Snake."""
try:
    import curses
except ImportError:
    curses = None
import random

from ..game import Game


class SnakeGame(Game):
    name = "snake"
    min_h = 15
    min_w = 30
    # Snake is steered tick-by-tick and every cell of travel matters: the
    # base class's default catch-up burst (up to 3 ticks in one iteration
    # after a stall, none of them drawn) could silently advance the snake
    # up to 3 cells with no frame shown and no chance to react, and the
    # turn queue (depth 2) could not even steer the 3rd of those ticks
    # (snake-3). Capping catch-up at 1 tick means a stall costs the game
    # some elapsed time (the tick clock resyncs to "now" afterward) instead
    # of ever moving blind.
    max_catchup_ticks = 1

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.board_h = saved['bh']
            self.board_w = saved['bw']
            self.board_y = max(1, (self.h - self.board_h) // 2)
            self.board_x = max(1, (self.w - self.board_w) // 2)
            self.snake = [tuple(p) for p in saved['snake']]
            self.direction = tuple(saved['dir'])
            # Older saves stored a single 'ndir' slot; fold it into the new
            # FIFO queue so a resumed game does not lose a queued turn.
            if 'pending' in saved:
                self.pending = [tuple(p) for p in saved['pending']]
            elif 'ndir' in saved and tuple(saved['ndir']) != self.direction:
                self.pending = [tuple(saved['ndir'])]
            else:
                self.pending = []
            self.food = tuple(saved['food']) if saved['food'] else None
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
        self.pending = []  # queued turns, FIFO depth 2, validated at apply time
        self.score = 0
        self.food = None
        self._spawn_food()
        self._fit_bounds()

    def _fit_bounds(self):
        # Require a terminal at least as big as the (possibly resumed) board, so
        # run()'s size gate shows "too small" instead of drawing walls off-screen.
        self.min_w = max(30, self.board_w + 2)
        self.min_h = max(15, self.board_h + 3)

    def on_resize(self):
        # Board is a fixed size chosen at setup(); this keeps the too-small
        # gate (min_h/min_w) consistent with it after a resize instead of
        # only ever being computed once.
        self._fit_bounds()

    def get_save_data(self):
        return {'bh': self.board_h, 'bw': self.board_w,
                'snake': self.snake, 'dir': self.direction,
                'pending': self.pending,
                'food': self.food, 'score': self.score}

    def _spawn_food(self):
        snake_set = set(self.snake)
        empty = [(y, x) for y in range(1, self.board_h - 1)
                 for x in range(1, self.board_w - 1) if (y, x) not in snake_set]
        # Board full: no cell left to place food. Leave self.food as None
        # (never a stale pellet drawn under the snake); the caller treats
        # this as the win condition.
        self.food = random.choice(empty) if empty else None

    def get_timeout(self):
        # Per-move delay. With the fixed-timestep loop this is the true
        # cadence: 150ms at score 0 ramping to a 90ms floor by score 30
        # (~6.7 -> 11 cells/sec), deliberate and chunky per spec.
        return max(90, 150 - self.score * 2)

    def handle_input(self, key):
        if key == curses.KEY_UP or key == ord('w'):
            d = (-1, 0)
        elif key == curses.KEY_DOWN or key == ord('s'):
            d = (1, 0)
        elif key == curses.KEY_LEFT or key == ord('a'):
            d = (0, -1)
        elif key == curses.KEY_RIGHT or key == ord('d'):
            d = (0, 1)
        else:
            return
        # FIFO turn queue, depth 2, validated at APPLY time (in update()),
        # not here. A same-tick Up-then-Left both get queued even though
        # the committed direction hasn't advanced yet, so a fast L-turn
        # works; a direct reversal is only rejected when it is about to be
        # applied against whatever direction is actually committed then.
        # A turn identical to the one already at the back of the queue (or
        # to the committed direction if the queue is empty) is dropped so
        # key-repeat noise can't clog both queue slots.
        ref = self.pending[-1] if self.pending else self.direction
        if d != ref and len(self.pending) < 2:
            self.pending.append(d)

    def update(self):
        if self.pending:
            d = self.pending.pop(0)
            dy0, dx0 = self.direction
            if d != (-dy0, -dx0):  # reject only a direct reversal
                self.direction = d
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
            if self.food is None:
                # No empty cell left anywhere on the board: the snake fills
                # it entirely. That is a win, not a stall.
                self.won = True
                self.game_over = True
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
        self.draw_status_bar('WASD:Move ?:Help Esc:Quit')

    def get_controls(self):
        return [('WASD', 'Move'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Length', len(self.snake))]
