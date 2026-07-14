"""Dino Runner."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game
from .. import config


# A little right-facing T-rex (two run frames with alternating legs), a duck
# frame, three saguaro cacti, and a pterodactyl. Every glyph used here is one
# of the quadrant/full blocks render.GLYPHS already maps to ASCII (U+2596-
# 259F plus the plain block set), so nothing here goes mojibake in ascii_mode.
_DINO = [
    [" ▗▟▖", "▗██▛", " ▙▟ "],
    [" ▗▟▖", "▗██▛", " ▟▙ "],
]
# Same 4-column footprint as the standing sprite (_DINO), not 6: a wider
# duck sprite used to extend past the dino's own hitbox columns (dino_x+1,
# dino_x+2) on both sides, so a cactus outside the (correctly inset) duck
# hitbox still visibly overlapped the sprite's tail for a few ticks even
# though the collision itself was already right. Matching the standing
# sprite's width keeps the visible overlap the same as the standing pose's.
_DINO_DUCK = [
    ["▗▄▄█"],
    ["▖▄▄▙"],
]
_CACTUS_SM = ["▗█ ", " █ "]
_CACTUS_LG = ["▖█▗", "▝█▘", " █ ", " █ "]
_CACTUS_XL = ["▖█▗", "▝█▘", "▖█▗", "▝█▘", " █ "]
# Plain ASCII (no glyph mapping needed): a flapping pterodactyl, two frames.
_PTERO = [
    ["^  ^", " vv "],
    [" vv ", "^  ^"],
]

# Jump physics. The Chrome T-Rex jump is a plain parabola (constant gravity,
# an instantaneous launch impulse) that returns to the ground when velocity
# integrates position back to 0; this is that same shape, just scaled to a
# ~30 Hz tick and a row-granular grid instead of 60 fps and pixels. The pair
# below is not arbitrary: it was chosen by brute-forcing every obstacle
# height against every game speed and every possible launch tick until one
# combination cleared everything with margin to spare. See
# test_dino_every_ground_obstacle_clearable_by_some_jump_timing in
# tests/test_games.py, which drives this exact code to prove it.
GRAVITY = 0.3
JUMP_POWER = -2.0

SPEED_MIN = 0.55
SPEED_MAX = 1.5
# ~120s ramp at the 33ms tick this game runs at (get_timeout()).
RAMP_TICKS = int(120 * 1000 / 33)

# Every obstacle's collision box is inset by one column from each edge of
# its drawn art, same idea as Chrome's own (smaller-than-sprite) hit boxes:
# it keeps near-miss grazes from reading as unfair. dino_x never changes
# (the dino does not move horizontally), so dl/dr are fixed columns too.
_HITBOX_INSET = 1

# kind -> geometry. 'oh' (obstacle height, rows) only matters for 'ground'
# obstacles, where the dino must be at or above that many rows of air to
# clear it. 'ptero_high' instead occupies a fixed row band at head height
# (see update()): ducking clears it for the obstacle's whole horizontal
# window with no timing needed, and jumping also clears it, but only with
# the right launch timing (dino-10: 7 clearing jump-launch ticks exist at
# every speed).
_GEOMETRY = {
    'sm': {'art': _CACTUS_SM, 'anim': False, 'oh': len(_CACTUS_SM),
           'full_w': 3, 'hitbox_w': 1, 'band': 'ground'},
    'lg': {'art': _CACTUS_LG, 'anim': False, 'oh': len(_CACTUS_LG),
           'full_w': 3, 'hitbox_w': 1, 'band': 'ground'},
    'xl': {'art': _CACTUS_XL, 'anim': False, 'oh': len(_CACTUS_XL),
           'full_w': 3, 'hitbox_w': 1, 'band': 'ground'},
    'ptero_low': {'art': _PTERO, 'anim': True, 'oh': len(_PTERO[0]),
                  'full_w': 4, 'hitbox_w': 2, 'band': 'ground'},
    'ptero_high': {'art': _PTERO, 'anim': True, 'oh': 0,
                   'full_w': 4, 'hitbox_w': 2, 'band': 'high'},
}


class DinoGame(Game):
    name = "dino"
    min_h = 15
    min_w = 50

    @property
    def ground_y(self):
        return self.h - 5

    def setup(self):
        self._hi = config.load_high_score(self.name)  # cache; can't change mid-game
        saved = self._load_save(self.name)
        if saved:
            self.dino_x = 8
            self.dino_y = saved['dino_y']
            self.velocity = saved['velocity']
            self.on_ground = saved['on_ground']
            self.obstacles = saved['obstacles']
            self.speed = saved['speed']
            self.score = saved['score']
            self.ticks = saved['ticks']
            self.spawn_timer = saved['spawn_timer']
            self.ducking = False
            return
        self.dino_x = 8
        self.dino_y = 0.0
        self.velocity = 0.0
        self.on_ground = True
        self.ducking = False
        self.obstacles = []
        self.speed = SPEED_MIN
        self.score = 0
        self.spawn_timer = 40

    def get_save_data(self):
        return {'score': self.score, 'speed': self.speed, 'ticks': self.ticks,
                'dino_y': self.dino_y, 'velocity': self.velocity,
                'on_ground': self.on_ground, 'spawn_timer': self.spawn_timer,
                'obstacles': self.obstacles}

    def get_timeout(self):
        return 33  # 30 Hz: fast and reflexive, per the pacing spec

    def handle_input(self, key):
        # Jump is edge-triggered (a discrete launch impulse), same category
        # as Flappy's flap: it belongs in handle_input, not update(). Duck
        # is the continuous one and is read via self.held() in update().
        if (key == ord(' ') or key == curses.KEY_UP or key == ord('w')) and self.on_ground:
            self.velocity = JUMP_POWER
            self.on_ground = False

    def update(self):
        if self.ticks % 4 == 0:
            self.score += 1
        self.speed = min(SPEED_MAX, SPEED_MIN +
                         (SPEED_MAX - SPEED_MIN) * self.ticks / RAMP_TICKS)

        if not self.on_ground:
            self.dino_y += self.velocity
            self.velocity += GRAVITY
            if self.dino_y >= 0:
                self.dino_y = 0.0
                self.velocity = 0.0
                self.on_ground = True

        # Ducking only makes sense (and only reduces the hitbox) while
        # grounded; you cannot duck out of a jump you already committed to.
        self.ducking = self.on_ground and self.held(curses.KEY_DOWN, ord('s'))

        gy = self.ground_y
        h = int(-self.dino_y)
        body_h = 1 if self.ducking else 3
        db = gy - h                # dino's lowest occupied row (feet)
        dt = db - (body_h - 1)     # dino's highest occupied row (head)
        dl, dr = self.dino_x + 1, self.dino_x + 2

        survivors = []
        for obs in self.obstacles:
            geo = _GEOMETRY[obs['kind']]
            prev_x = obs['x']
            obs['x'] -= self.speed
            # Swept horizontal test between last tick's and this tick's
            # position: at low speed the obstacle barely moves and this
            # reduces to a point test, but at high speed a narrow hitbox
            # could otherwise be stepped clean over in one tick (dino-8's
            # sibling bug: tunneling, not vanishing).
            left = obs['x'] + _HITBOX_INSET
            right = prev_x + _HITBOX_INSET + geo['hitbox_w'] - 1
            hit_x = not (right < dl or left > dr)
            if hit_x:
                if geo['band'] == 'ground':
                    if db >= gy - geo['oh'] + 1 and dt <= gy:
                        self.game_over = True
                        return
                else:  # 'high': a fixed head-height band; clearable by a held
                        # duck through the whole window, or by a jump with the
                        # right launch timing (dino-10)
                    top_p, bot_p = gy - 2, gy - 1
                    if dt <= bot_p and db >= top_p:
                        self.game_over = True
                        return
            if obs['x'] + geo['full_w'] > -1:
                survivors.append(obs)
        self.obstacles = survivors

        self.spawn_timer -= 1
        if self.spawn_timer <= 0:
            self._spawn()

    def _spawn(self):
        if self.obstacles and self.obstacles[-1]['x'] > self.w - 20:
            self.spawn_timer = 5
            return
        kinds = ['sm', 'lg', 'xl']
        weights = [50, 30, 12]
        if self.score >= 15:  # ease new runs in on cacti alone for a couple seconds
            kinds += ['ptero_low', 'ptero_high']
            weights += [4, 4]
        kind = random.choices(kinds, weights=weights)[0]
        self.obstacles.append({'x': float(self.w), 'kind': kind})
        # Gap is a roughly constant on-screen distance divided by speed, so
        # obstacles get more frequent (not closer together) as the game
        # speeds up, matching the canonical ramp.
        mn = max(30, int(45 / self.speed))
        mx = max(55, int(85 / self.speed))
        self.spawn_timer = random.randint(mn, mx)

    def draw(self):
        gy = self.ground_y
        sc = f'Score: {self.score}'
        hi = f'HI: {max(self.score, self._hi)}'
        self.safe_addstr(1, self.w - len(sc) - 2, sc, curses.A_BOLD)
        self.safe_addstr(1, self.w - len(sc) - len(hi) - 4, hi,
                         curses.color_pair(3))
        self.safe_addstr(1, 2, 'DINO RUNNER', curses.A_BOLD)

        anim = (self.ticks // 4) % 2
        art = _DINO_DUCK[anim] if self.ducking else _DINO[anim if self.on_ground else 0]
        db = gy - int(-self.dino_y)
        for i, line in enumerate(art):
            self.safe_addstr(db - len(art) + 1 + i, self.dino_x, line,
                             curses.color_pair(1) | curses.A_BOLD)

        for obs in self.obstacles:
            geo = _GEOMETRY[obs['kind']]
            oart = geo['art'][anim] if geo['anim'] else geo['art']
            anchor = gy if geo['band'] == 'ground' else gy - 1
            ox = int(obs['x'])
            for i, line in enumerate(oart):
                self.safe_addstr(anchor - len(oart) + 1 + i, ox, line,
                                 curses.color_pair(2) | curses.A_BOLD)

        self.safe_addstr(gy + 1, 0, '─' * self.w, curses.color_pair(4))
        # Scrolls the same direction as obstacles (leftward, decreasing x)
        # instead of the old code's rightward-walking offset, which made
        # the ground read as running backwards under the dino (dino-3).
        off = (-int(self.ticks * self.speed)) % 6
        for x in range(off, self.w - 1, 6):
            self.safe_addstr(gy + 2, x, '.', curses.color_pair(4))
        self.draw_status_bar('W/Spc:Jump S:Duck P:Pause ?:Help Esc:Quit')

    def get_controls(self):
        return [('W/Space', 'Jump'), ('Down/S', 'Duck'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Speed', f'{self.speed:.2f}x')]
