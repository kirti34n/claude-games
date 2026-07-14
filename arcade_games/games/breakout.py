"""Breakout."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game

# Canonical 4-tier speed ratchet. Ball speed (cells/tick) only ever goes up
# within a serve: it is the number of the four trigger conditions satisfied
# so far (volley 4, volley 12, orange row hit, red row hit), each latched
# once, so the order they happen in does not matter.
SPEED_LEVELS = (0.35, 0.4875, 0.625, 0.7625, 0.9)

# Row 0 is the top row (farthest from the paddle, hardest to reach, worth
# the most and the one that ratchets speed to max), row 3 is the row
# closest to the paddle. Matches the canonical yellow/green/orange/red
# 1/3/5/7 wall, compressed to one row per tier since this board is 4 rows
# deep rather than arcade's 8.
ROW_SCORES = (7, 5, 3, 1)
ROW_STYLE = {
    0: (2, curses.A_BOLD if curses else 0),   # red, top
    1: (5, curses.A_BOLD if curses else 0),   # orange stand-in (magenta)
    2: (1, curses.A_BOLD if curses else 0),   # green
    3: (3, curses.A_BOLD if curses else 0),   # yellow, bottom
}


class BreakoutGame(Game):
    name = "breakout"
    min_h = 22
    min_w = 44
    PADDLE_SPEED = 2  # cells per tick, continuous while A/D or arrows held

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.area_w = saved['area_w']
            self.area_h = saved['area_h']
            self.area_x = (self.w - self.area_w) // 2
            self.area_y = (self.h - self.area_h) // 2
            self.paddle_full_w = saved['paddle_full_w']
            self.paddle_w = saved['paddle_w']
            self.paddle_halved = saved['paddle_halved']
            self.paddle_y = self.area_h - 3
            self.paddle_x = saved['paddle_x']
            self.paddle_hits = saved['paddle_hits']
            self.ball_x = saved['ball_x']
            self.ball_y = saved['ball_y']
            self.ball_dx = saved['ball_dx']
            self.ball_dy = saved['ball_dy']
            self.ball_speed = saved['ball_speed']
            self.ball_moving = saved['ball_moving']
            self.tier_volley4 = saved['tier_volley4']
            self.tier_volley12 = saved['tier_volley12']
            self.tier_orange = saved['tier_orange']
            self.tier_red = saved['tier_red']
            self.wall = saved['wall']
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

        self.paddle_full_w = 8
        self.paddle_w = self.paddle_full_w
        self.paddle_halved = False
        self.paddle_y = self.area_h - 3
        self.paddle_x = (self.area_w - self.paddle_w) // 2
        self.paddle_hits = 0

        self.ball_speed = SPEED_LEVELS[0]
        self.ball_x = float(self.area_w // 2)
        self.ball_y = float(self.paddle_y - 1)
        self.ball_dx = 0.0
        self.ball_dy = -self.ball_speed
        self.ball_moving = False

        self.tier_volley4 = False
        self.tier_volley12 = False
        self.tier_orange = False
        self.tier_red = False

        self.wall = 1
        self.brick_w = 4
        self.brick_rows = 4
        self.brick_start_y = 3
        self.score = 0
        self.lives = 3
        self._layout_bricks()
        self._fill_wall()
        self._fit_bounds()

    def _layout_bricks(self):
        usable = self.area_w - 2
        self.bricks_per_row = usable // self.brick_w
        total = self.bricks_per_row * self.brick_w
        self.brick_off_x = 1 + (usable - total) // 2

    def _fill_wall(self):
        self.bricks = {(r, c): ROW_STYLE[r][0]
                       for r in range(self.brick_rows)
                       for c in range(self.bricks_per_row)}

    def _fit_bounds(self):
        # Gate on the actual play-area footprint so a resumed/resized terminal
        # smaller than the board shows "too small" instead of drawing off-screen.
        self.min_w = max(44, self.area_w + 2)
        self.min_h = max(22, self.area_h + 2)

    def on_resize(self):
        self._fit_bounds()

    def get_save_data(self):
        bricks = {f'{r},{c}': v for (r, c), v in self.bricks.items()}
        return {'score': self.score, 'lives': self.lives,
                'paddle_x': self.paddle_x, 'paddle_w': self.paddle_w,
                'paddle_full_w': self.paddle_full_w,
                'paddle_halved': self.paddle_halved,
                'paddle_hits': self.paddle_hits,
                'ball_x': self.ball_x, 'ball_y': self.ball_y,
                'ball_dx': self.ball_dx, 'ball_dy': self.ball_dy,
                'ball_speed': self.ball_speed,
                'ball_moving': self.ball_moving,
                'tier_volley4': self.tier_volley4,
                'tier_volley12': self.tier_volley12,
                'tier_orange': self.tier_orange,
                'tier_red': self.tier_red,
                'wall': self.wall,
                'area_w': self.area_w, 'area_h': self.area_h,
                'brick_rows': self.brick_rows, 'bricks_per_row': self.bricks_per_row,
                'brick_off_x': self.brick_off_x, 'brick_w': self.brick_w,
                'brick_start_y': self.brick_start_y, 'bricks': bricks}

    def get_timeout(self):
        return 25

    def handle_input(self, key):
        # Edge-triggered: launching the ball is a discrete action, not
        # continuous movement, so it stays here.
        if key == ord(' ') and not self.ball_moving:
            self.ball_moving = True
            hit_ratio = random.choice([-0.6, 0.6])
            self._serve_direction(hit_ratio)

    def _serve_direction(self, hit_ratio):
        mag = (hit_ratio ** 2 + 1) ** 0.5
        self.ball_dx = hit_ratio / mag * self.ball_speed
        self.ball_dy = -1.0 / mag * self.ball_speed

    def _move_paddle(self):
        if self.held(curses.KEY_LEFT, ord('a')):
            self.paddle_x = max(1, self.paddle_x - self.PADDLE_SPEED)
        elif self.held(curses.KEY_RIGHT, ord('d')):
            self.paddle_x = min(self.area_w - self.paddle_w - 1,
                                self.paddle_x + self.PADDLE_SPEED)

    def _bump_speed_tier(self):
        tier = (int(self.tier_volley4) + int(self.tier_volley12)
                + int(self.tier_orange) + int(self.tier_red))
        new_speed = SPEED_LEVELS[tier]
        if new_speed != self.ball_speed:
            factor = new_speed / self.ball_speed
            self.ball_dx *= factor
            self.ball_dy *= factor
            self.ball_speed = new_speed

    def update(self):
        self._move_paddle()
        if not self.ball_moving:
            self.ball_x = float(self.paddle_x + self.paddle_w // 2)
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
            if not self.paddle_halved:
                self.paddle_halved = True
                self.paddle_w = max(2, self.paddle_full_w // 2)
                self.paddle_x = min(self.paddle_x,
                                    self.area_w - self.paddle_w - 1)
        # Paddle bounce
        if (int(ny) >= self.paddle_y - 1 and int(ny) <= self.paddle_y
                and self.ball_dy > 0
                and self.paddle_x <= int(nx) <= self.paddle_x + self.paddle_w - 1):
            self.paddle_hits += 1
            if self.paddle_hits >= 4:
                self.tier_volley4 = True
            if self.paddle_hits >= 12:
                self.tier_volley12 = True
            self._bump_speed_tier()
            center = self.paddle_x + self.paddle_w / 2.0
            hit_ratio = (nx - center) / (self.paddle_w / 2.0)
            hit_ratio = max(-1.0, min(1.0, hit_ratio))
            self._serve_direction(hit_ratio)
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
                self.score += ROW_SCORES[br] if br < len(ROW_SCORES) else 1
                if br == 0:
                    self.tier_red = True
                    self._bump_speed_tier()
                elif br == 1:
                    self.tier_orange = True
                    self._bump_speed_tier()
        self.ball_x, self.ball_y = nx, ny
        if not self.bricks:
            if self.wall == 1:
                self.wall = 2
                self._fill_wall()
            else:
                self.won = True
                self.game_over = True

    def _reset_ball(self):
        self.ball_moving = False
        self.ball_x = float(self.paddle_x + self.paddle_w // 2)
        self.ball_y = float(self.paddle_y - 1)
        self.ball_speed = SPEED_LEVELS[0]
        self.ball_dx = 0.0
        self.ball_dy = -self.ball_speed
        self.paddle_hits = 0
        self.tier_volley4 = False
        self.tier_volley12 = False
        self.tier_orange = False
        self.tier_red = False
        self.paddle_halved = False
        self.paddle_w = self.paddle_full_w

    def draw(self):
        # Re-center each frame (never negative) so resize/resume stays on-screen.
        self.area_x = max(0, (self.w - self.area_w) // 2)
        self.area_y = max(0, (self.h - self.area_h) // 2)
        ax, ay = self.area_x, self.area_y
        self.draw_box(ay, ax, self.area_h, self.area_w)
        hearts = '*' * self.lives
        wall_tag = f'  Wall:{self.wall}' if self.wall > 1 else ''
        self.safe_addstr(ay, ax + 2,
                         f' BREAKOUT  Score:{self.score}  Lives:{hearts}{wall_tag} ',
                         curses.A_BOLD)
        for (r, c), color in self.bricks.items():
            _, attr = ROW_STYLE.get(r, (color, curses.A_BOLD))
            self.safe_addstr(ay + self.brick_start_y + r,
                             ax + self.brick_off_x + c * self.brick_w, '[##]',
                             curses.color_pair(color) | attr)
        self.safe_addstr(ay + self.paddle_y, ax + self.paddle_x,
                         '=' * self.paddle_w,
                         curses.color_pair(7) | curses.A_BOLD)
        self.safe_addstr(ay + int(self.ball_y), ax + int(self.ball_x), 'O',
                         curses.color_pair(3) | curses.A_BOLD)
        if not self.ball_moving:
            self.center_text(ay + self.area_h // 2,
                             ' Press SPACE to launch ball ',
                             curses.color_pair(4) | curses.A_REVERSE)
        self.draw_status_bar(' A/D:Move  Space:Launch  ?:Help  ESC:Quit ')

    def get_controls(self):
        return [('A/D', 'Move paddle'), ('Space', 'Launch ball'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        total = self.brick_rows * self.bricks_per_row
        broken = total - len(self.bricks) if self.wall == 1 else total
        return [('Bricks', f'{broken}/{total}'), ('Wall reached', self.wall),
                ('Lives left', self.lives)]
