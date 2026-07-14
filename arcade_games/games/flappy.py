"""Flappy Bird."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game
from .. import config


class FlappyGame(Game):
    name = "flappy"
    min_h = 20
    min_w = 50

    # Canon: flap ASSIGNS velocity (not additive), the ceiling is solid but
    # harmless, fall speed is clamped, and there is deliberately NO
    # difficulty ramp. That last point is Flappy's defining design decision;
    # do not reintroduce one.
    GRAVITY = 0.09
    FLAP_VEL = -0.75
    TERMINAL_VEL = 0.9
    SCROLL_SPEED = 0.66
    PIPE_GAP = 7
    PIPE_WIDTH = 3
    PIPE_INTERVAL = 53
    BIRD_X = 10
    GAP_MARGIN_FRAC = 0.2

    def setup(self):
        self._hi = config.load_high_score(self.name)  # cache; don't re-read every draw()
        saved = self._load_save(self.name)
        if saved:
            self.bird_y = saved['bird_y']
            self.bird_vel = saved['bird_vel']
            self.pipes = saved['pipes']
            self.score = saved['score']
            self.pipe_timer = saved['pipe_timer']
            self.started = saved.get('started', True)
            self.dying = saved.get('dying', False)
            self._fit_bounds()
            # A shorter resumed terminal could leave the bird at/below the new
            # ground; clamp so resuming doesn't instantly end the run. Must
            # stay strictly above the death row (ground_y - 1, see update()'s
            # `>= ground_y - 1` check): clamping to exactly that row landed
            # the bird already dead on the very next update() (flappy-5).
            self.bird_y = max(1.0, min(self.bird_y, self.ground_y - 2.0))
            return
        self._fit_bounds()
        self.bird_y = float(self.h // 2)
        self.bird_vel = 0.0
        self.pipes = []
        self.score = 0
        self.pipe_timer = self.PIPE_INTERVAL
        self.started = False  # Get Ready: world is frozen until the first flap
        self.dying = False

    def _fit_bounds(self):
        self.ground_y = self.h - 2
        if hasattr(self, 'bird_y'):
            # Same off-by-one as the resume clamp above: must stay strictly
            # above ground_y - 1, the row update() treats as lethal.
            self.bird_y = max(1.0, min(self.bird_y, self.ground_y - 2.0))

    def on_resize(self):
        self._fit_bounds()

    def get_timeout(self):
        return 33

    def handle_input(self, key):
        # Discrete, edge-triggered: one keypress assigns one flap. Holding
        # the key re-arms it every repeat, same as tapping fast, which is
        # safe now that the ceiling is harmless instead of lethal.
        if key in (ord(' '), ord('w'), curses.KEY_UP):
            if self.dying:
                return
            self.started = True
            self.bird_vel = self.FLAP_VEL

    def update(self):
        if self.dying:
            # Death fall: gravity keeps acting, input is ignored, the world
            # is frozen (no pipe movement, no scoring) until the bird
            # settles on the ground and the game-over screen takes over.
            self.bird_vel = min(self.bird_vel + self.GRAVITY, self.TERMINAL_VEL)
            self.bird_y += self.bird_vel
            if self.bird_y >= self.ground_y - 1:
                self.bird_y = float(self.ground_y - 1)
                self.game_over = True
            return

        if not self.started:
            return  # Get Ready: the bird does not fall until the first flap

        self.bird_vel = min(self.bird_vel + self.GRAVITY, self.TERMINAL_VEL)
        self.bird_y += self.bird_vel

        # The ceiling is a solid wall, but it is harmless: it stops the
        # climb, it does not end the run. Exactly one lethal surface below.
        if self.bird_y < 1.0:
            self.bird_y = 1.0
            if self.bird_vel < 0:
                self.bird_vel = 0.0

        if self.bird_y >= self.ground_y - 1:
            self.bird_y = float(self.ground_y - 1)
            self.dying = True
            return

        self.pipe_timer -= 1
        if self.pipe_timer <= 0:
            playable_bottom = self.ground_y - 1
            margin = max(1, round((playable_bottom - 1) * self.GAP_MARGIN_FRAC))
            lo = 1 + margin
            hi = playable_bottom - self.PIPE_GAP - margin
            if hi < lo:
                hi = lo
            gap_start = random.randint(lo, hi)
            self.pipes.append({'x': float(self.w - 1), 'gap_top': gap_start,
                               'scored': False})
            self.pipe_timer = self.PIPE_INTERVAL

        bird_row = int(round(self.bird_y))
        for p in self.pipes:
            p['x'] -= self.SCROLL_SPEED
            px = int(p['x'])
            gap_bot = p['gap_top'] + self.PIPE_GAP
            if px <= self.BIRD_X < px + self.PIPE_WIDTH:
                if bird_row < p['gap_top'] or bird_row >= gap_bot:
                    self.dying = True
                    return
            if not p['scored'] and p['x'] + self.PIPE_WIDTH < self.BIRD_X:
                p['scored'] = True
                self.score += 1

        self.pipes = [p for p in self.pipes if p['x'] + self.PIPE_WIDTH > 0]

    def draw(self):
        self.safe_addstr(0, 2, 'FLAPPY BIRD', curses.A_BOLD)
        sc_str = f'Score: {self.score}  HI: {max(self.score, self._hi)}'
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
                for row in range(gap_bot, self.ground_y):
                    ch = '+' if col in (0, self.PIPE_WIDTH - 1) and row == gap_bot else '|'
                    self.safe_addstr(row, cx, ch,
                                     curses.color_pair(1) | curses.A_BOLD)

        self.safe_addstr(self.ground_y, 0, '─' * self.w, curses.color_pair(4))

        bird_row = int(round(self.bird_y))
        if self.dying:
            bird_ch = 'X'
            bird_attr = curses.color_pair(2) | curses.A_BOLD
        else:
            bird_ch = '>' if self.bird_vel <= 0 else 'v'
            bird_attr = curses.color_pair(3) | curses.A_BOLD
        self.safe_addstr(bird_row, self.BIRD_X, bird_ch, bird_attr)

        if not self.started and not self.dying:
            self.center_text(self.h // 2 - 3, 'GET READY!', curses.A_BOLD)
            self.center_text(self.h // 2 - 2, 'Press W or Space to flap',
                             curses.color_pair(4))

        self.draw_status_bar('W/Space: Flap  P: Pause  ?: Help  ESC: Quit')

    def get_controls(self):
        return [('W/Space', 'Flap'), ('P', 'Pause'), ('ESC', 'Quit')]

    def _medal(self):
        if self.score >= 40:
            return 'Platinum'
        if self.score >= 30:
            return 'Gold'
        if self.score >= 20:
            return 'Silver'
        if self.score >= 10:
            return 'Bronze'
        return None

    def get_stats(self):
        medal = self._medal()
        return [('Medal', medal)] if medal else []

    def get_save_data(self):
        return {'bird_y': self.bird_y, 'bird_vel': self.bird_vel,
                'pipes': self.pipes, 'score': self.score,
                'pipe_timer': self.pipe_timer, 'started': self.started,
                'dying': self.dying}
