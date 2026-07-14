"""Pac-Man."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game
from .. import config


# ─── Pac-Man ────────────────────────────────────────────────────────────────
#
# Movement model: every entity's position is (tile_y, tile_x, progress,
# direction), where tile_y/tile_x is the last tile CENTER the entity passed
# through, progress in [0, 1) is how far it has moved from that center
# toward the next tile along `direction`, and the rendered/collision
# position is tile + direction * progress. Direction changes (a queued
# player turn, a ghost re-targeting) are only evaluated exactly at a
# center (progress == 0), matching the original arcade's tile-quantized
# turning. This lets Pac and the ghosts move at fractional tiles-per-tick
# (arcade speeds are well under one tile per 20 ms tick) instead of the
# old one-tile-per-tick hop, which was 1.65x arcade speed.
#
# NOTE on self.ticks: the base Game class increments self.ticks in the run
# loop, AFTER update() returns. tests/test_games.py calls update() directly
# (bypassing the loop) for its scripted-input tests, so self.ticks never
# advances there. This game's internal pacing (scatter/chase clock, fright
# timer, ghost-house starvation release, animation) has correctness
# requirements a frozen clock would break, so it keeps its own private
# tick counter (self._clock) incremented at the top of update(), same as
# the old self.frame did. This is a deliberate deviation from "delete
# self.frame, use self.ticks".

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

    # name, color pair, glyph. Ghosts render distinctly by letter and
    # color while hunting/scattering; frightened ghosts lose their
    # identity (uniform, per canon) and eaten ghosts show as eyes.
    _GHOST_CONFIGS = [
        ('Blinky', 2, 'B'),
        ('Pinky', 5, 'P'),
        ('Inky', 4, 'I'),
        ('Clyde', 3, 'Y'),
    ]
    _CORNERS = [(0, 26), (0, 0), (21, 26), (21, 0)]  # scatter targets, TR/TL/BR/BL

    # Ghost-house dot counters (Pac-Man Dossier): Pinky (and, since this
    # maze starts him in the pen too, Blinky) leave immediately; Inky and
    # Clyde wait for the level's global dot count. Anti-starvation release
    # (STARVE_TICKS below) covers the case where Pac-Man never gets close
    # enough to feed the counter.
    _RELEASE_THRESHOLDS = {
        1: {'Blinky': 0, 'Pinky': 0, 'Inky': 30, 'Clyde': 60},
        2: {'Blinky': 0, 'Pinky': 0, 'Inky': 0, 'Clyde': 50},
        'default': {'Blinky': 0, 'Pinky': 0, 'Inky': 0, 'Clyde': 0},
    }

    # Scatter/chase wave lengths in seconds, by level tier (Dossier).
    _PHASE_SECONDS_L1 = [7, 20, 7, 20, 5, 20, 5]
    _PHASE_SECONDS_L2_4 = [7, 20, 7, 20, 5, 1033, 1 / 60]
    _PHASE_SECONDS_L5_PLUS = [5, 20, 5, 20, 5, 1037, 1 / 60]

    # (14, 13) is a wall tile (the vertical divider in that row of _MAZE);
    # a fruit spawned there could never be reached or collected and drew
    # visibly embedded in the wall (pacman-16). (14, 14) is the open tile
    # immediately beside it, reachable via the normal corridor.
    _FRUIT_POS = (14, 14)

    PAC_TILES_PER_SEC = 7.58   # arcade-exact
    GHOST_BASE_FRAC = 0.75
    GHOST_MAX_FRAC = 0.95
    GHOST_FRAC_STEP = 0.01     # +1%/level toward the 95% cap
    FRIGHT_FRAC = 0.5
    TUNNEL_FRAC = 0.4
    EATEN_FRAC = 2.0
    STARVE_TICKS = 150         # anti-starvation ghost release (canon ~4s; tuned to 3s)
    FRUIT_TICKS = 500          # ~10s a bonus fruit stays on screen
    DYING_TICKS = 60           # ~1.2s death animation
    LEVEL_PAUSE_TICKS = 90     # ~1.8s pause between levels
    EXTRA_LIFE_SCORE = 10000

    def setup(self):
        saved = self._load_save(self.name)
        self._high = config.load_high_score(self.name)
        if saved:
            self.maze = saved['maze']
            self.score = saved['score']
            self.lives = saved['lives']
            self.level = saved.get('level', 1)
            self.pac_y = saved['pac_y']
            self.pac_x = saved['pac_x']
            self.pac_progress = saved.get('pac_progress', 0.0)
            self.pac_dir = tuple(saved['pac_dir'])
            self.next_dir = tuple(saved['next_dir'])
            # Direct-index every field (no .get() defaults): an old-schema
            # save (pre-rewrite, no 'progress'/'released'/...) must raise
            # KeyError here, inside setup(), where _run_loop's schema guard
            # catches it and falls back to a clean re-init, instead of
            # silently loading a partial ghost dict that KeyErrors later
            # from inside update()/draw() (uncaught, a real crash).
            self.ghosts = [{
                'name': g['name'], 'color': g['color'], 'glyph': g['glyph'],
                'y': g['y'], 'x': g['x'], 'progress': g['progress'],
                'dir': tuple(g['dir']), 'eaten': g['eaten'],
                'released': g['released'], 'release_at': g['release_at'],
                'corner': g['corner'],
                'eaten_this_energizer': g['eaten_this_energizer'],
            } for g in saved['ghosts']]
            self.frightened = saved['frightened']
            self.frightened_timer = saved['frightened_timer']
            self.chain = saved.get('chain', 0)
            self._clock = saved.get('clock', 0)
            self.dots_left = saved['dots_left']
            self.dots_eaten_level = saved.get('dots_eaten_level', 0)
            self.starve_timer = saved.get('starve_timer', 0)
            self.mode = saved.get('mode', 'scatter')
            self.mode_phase = saved.get('mode_phase', 0)
            self.mode_timer = saved.get('mode_timer', None)
            self.fruit_active = saved.get('fruit_active', False)
            self.fruit_timer = saved.get('fruit_timer', 0)
            self.fruit_spawned_70 = saved.get('fruit_spawned_70', False)
            self.fruit_spawned_170 = saved.get('fruit_spawned_170', False)
            self.extra_life_awarded = saved.get('extra_life_awarded', False)
            self._dying = saved.get('dying', 0)
            self._level_pause = saved.get('level_pause', 0)
            self._rng = random.Random(1000 + self.level)
            return

        self.maze = [list(row) for row in self._MAZE]
        self.score = 0
        self.lives = 3
        self.level = 1
        self._dying = 0
        self._level_pause = 0
        self._clock = 0
        self.chain = 0
        self.dots_eaten_level = 0
        self.starve_timer = 0
        self.frightened = False
        self.frightened_timer = 0
        self.fruit_active = False
        self.fruit_timer = 0
        self.fruit_spawned_70 = False
        self.fruit_spawned_170 = False
        self.extra_life_awarded = False
        self.dots_left = sum(1 for row in self.maze for c in row if c in ('.', 'O'))
        # Reseeded identically per level (see class docstring) so ghost
        # behavior is deterministic and patternable, not global-RNG mush.
        self._rng = random.Random(1000 + self.level)

        self.pac_y, self.pac_x = 16, 13
        for ry, row in enumerate(self.maze):
            for rx, ch in enumerate(row):
                if ch == 'C':
                    self.pac_y, self.pac_x = ry, rx
                    self.maze[ry][rx] = ' '
        self.pac_progress = 0.0
        self.pac_dir = (0, 0)
        self.next_dir = (0, 1)

        self.ghosts = []
        home_y, home_x = 10, 13
        offsets = [(0, 0), (0, -1), (0, 1), (0, 2)]
        for (gname, color, glyph), (oy, ox), corner in zip(
                self._GHOST_CONFIGS, offsets, self._CORNERS):
            self.ghosts.append({'name': gname, 'color': color, 'glyph': glyph,
                                'y': home_y + oy, 'x': home_x + ox,
                                'progress': 0.0, 'dir': (0, 1),
                                'eaten': False, 'released': False,
                                'release_at': 0, 'corner': list(corner),
                                'eaten_this_energizer': False})
        self._setup_ghost_release()
        self._enter_phase(0)

    # ── static maze helpers ─────────────────────────────────────────────

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

    def _in_house(self, y, x):
        """True inside the ghost house interior (row 10, cols 10-16 of
        _MAZE): the pen ghosts start in and the only tile a released ghost
        should ever be routed back toward the door from. The old test,
        `y >= 9`, covered rows 9-21 (13 of the maze's 22 rows) and made
        every released ghost in the bottom 60% of the maze treat itself as
        still-in-the-pen: chase/scatter/fright all silently no-op there and
        route to the door instead (pacman-1, pacman-6)."""
        return y == 10 and 10 <= x <= 16

    def _in_tunnel(self, y, x):
        """True on the genuine side-tunnel segment: row 10, columns outside
        the ghost-house interior (9-17 are the pen's walls/door column).
        _MAZE also has open-looking rows at 8 and 12 (row[0]/row[-1] both
        non-wall), but those are sealed dead pockets at cols 5/21, not
        actually connected to the wraparound edge, so they must not get the
        tunnel slowdown; only row 10 truly wraps."""
        return y == 10 and (x <= 8 or x >= 18)

    def get_timeout(self):
        return 20  # 50 Hz simulation tick (see SPEC pacing table)

    def _pac_speed(self):
        return self.PAC_TILES_PER_SEC * (self.get_timeout() / 1000.0)

    def _ghost_frac(self):
        return min(self.GHOST_MAX_FRAC,
                   self.GHOST_BASE_FRAC + self.GHOST_FRAC_STEP * (self.level - 1))

    def _fright_ticks(self):
        seconds = max(1, min(6, 7 - self.level))
        return int(seconds * 1000 / self.get_timeout())

    def _fruit_value(self):
        lvl = self.level
        if lvl <= 1:
            return 100
        if lvl == 2:
            return 300
        if lvl <= 4:
            return 500
        if lvl <= 6:
            return 700
        if lvl <= 8:
            return 1000
        if lvl <= 10:
            return 2000
        if lvl <= 12:
            return 3000
        return 5000

    # ── scatter/chase wave clock ────────────────────────────────────────

    def _phase_table(self):
        if self.level == 1:
            secs = self._PHASE_SECONDS_L1
        elif self.level in (2, 3, 4):
            secs = self._PHASE_SECONDS_L2_4
        else:
            secs = self._PHASE_SECONDS_L5_PLUS
        per_sec = 1000.0 / self.get_timeout()
        return [max(1, round(s * per_sec)) for s in secs]

    def _enter_phase(self, idx):
        table = self._phase_table()
        self.mode_phase = idx
        if idx >= len(table):
            self.mode = 'chase'          # final phase: chase forever
            self.mode_timer = None
        else:
            self.mode = 'scatter' if idx % 2 == 0 else 'chase'
            self.mode_timer = table[idx]

    def _force_reverse_all(self):
        """Ghosts must reverse on every scatter/chase mode change and when
        fright starts. Exempt eaten ghosts (returning home) and ghosts
        still inside/at the ghost house, INCLUDING the door tile itself
        (9,13): arcade canon exempts ghosts entering or leaving the house
        from the forced reversal, and _in_house is deliberately tile-exact
        (row 10, cols 10-16 only) so it does not cover the door tile a
        released ghost passes through one row above."""
        for ghost in self.ghosts:
            if (ghost['eaten'] or not ghost['released']
                    or self._in_house(ghost['y'], ghost['x'])
                    or self._is_ghost_door(ghost['y'], ghost['x'])):
                continue
            self._reverse_ghost(ghost)

    def _reverse_ghost(self, ghost):
        dy, dx = ghost['dir']
        if (dy, dx) == (0, 0):
            return
        if ghost['progress'] <= 1e-9:
            ghost['dir'] = (-dy, -dx)
            return
        ghost['y'] += dy
        ghost['x'] = self._wrap_x(ghost['x'] + dx)
        ghost['progress'] = 1.0 - ghost['progress']
        ghost['dir'] = (-dy, -dx)

    # ── ghost house release ─────────────────────────────────────────────

    def _setup_ghost_release(self):
        thresholds = self._RELEASE_THRESHOLDS.get(self.level, self._RELEASE_THRESHOLDS['default'])
        for ghost in self.ghosts:
            at = thresholds[ghost['name']]
            ghost['release_at'] = at
            ghost['released'] = self.dots_eaten_level >= at
        self.starve_timer = 0

    # ── entity motion engine ────────────────────────────────────────────

    def _advance(self, ty, tx, progress, direction, decide_fn, speed, on_enter=None):
        """Move one entity by `speed` tiles this tick. At a tile center
        (progress == 0) decide_fn(ty, tx, direction) picks the direction
        to commit to for the next leg (None means stop, staying put).
        on_enter(ty, tx), if given, fires the instant a new tile center is
        reached (dot pickup, fruit, ghost revival, etc). If on_enter
        returns a truthy value, movement stops for the rest of this tick
        (the entity's state just changed underneath the in-flight
        decide_fn/speed, e.g. an eaten ghost reviving mid-tick; the next
        tick's caller re-derives both from the new state)."""
        remaining = speed
        guard = 0
        while remaining > 1e-9 and guard < 8:
            guard += 1
            if progress <= 1e-9:
                progress = 0.0
                nd = decide_fn(ty, tx, direction)
                if nd is None:
                    return ty, tx, 0.0, (0, 0)
                direction = nd
            step = min(remaining, 1.0 - progress)
            progress += step
            remaining -= step
            if progress >= 1.0 - 1e-9:
                ty, tx = ty + direction[0], self._wrap_x(tx + direction[1])
                progress = 0.0
                if on_enter and on_enter(ty, tx):
                    # on_enter signals a hard state change at this exact
                    # arrival (e.g. an eaten ghost reviving in the pen).
                    # Stop consuming the tick's remaining distance under
                    # the OLD decide_fn/speed; the next tick re-evaluates
                    # both from the entity's new state.
                    return ty, tx, 0.0, direction
        return ty, tx, progress, direction

    def _disp(self, ty, tx, progress, direction):
        """Rendered/collision tile position, rounded to the character grid."""
        ry = ty + direction[0] * progress
        rx = tx + direction[1] * progress
        return round(ry), self._wrap_x(round(rx))

    def _best_dir(self, ty, tx, direction, target, allow_door):
        """The legal direction that minimizes straight-line distance to
        `target`, honoring the no-reversal rule, in canon tie-break order
        (Up, Left, Down, Right). Falls back to reversing only when every
        other direction is blocked (a dead end)."""
        reverse = (-direction[0], -direction[1])
        best, best_dist = None, None
        for d in ((-1, 0), (0, -1), (1, 0), (0, 1)):
            if d == reverse and direction != (0, 0):
                continue
            ny, nx = ty + d[0], self._wrap_x(tx + d[1])
            if self._is_wall(ny, nx):
                continue
            if self._is_ghost_door(ny, nx) and not allow_door:
                continue
            dist = (ny - target[0]) ** 2 + (nx - target[1]) ** 2
            if best_dist is None or dist < best_dist:
                best_dist, best = dist, d
        if best is not None:
            return best
        ny, nx = ty + reverse[0], self._wrap_x(tx + reverse[1])
        if not self._is_wall(ny, nx) and (allow_door or not self._is_ghost_door(ny, nx)):
            return reverse
        return None

    def _pac_decide(self, ty, tx, direction):
        for d in (self.next_dir, direction):
            if d == (0, 0):
                continue
            ny, nx = ty + d[0], self._wrap_x(tx + d[1])
            if not self._is_wall(ny, nx) and not self._is_ghost_door(ny, nx):
                return d
        return None

    def _decide_eaten(self, ty, tx, direction):
        return self._best_dir(ty, tx, direction, (10, 13), allow_door=True)

    def _decide_house_exit(self, ty, tx, direction):
        return self._best_dir(ty, tx, direction, (8, 13), allow_door=True)

    def _decide_frightened(self, ty, tx, direction):
        reverse = (-direction[0], -direction[1])
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        self._rng.shuffle(dirs)
        for d in dirs:
            if d == reverse and direction != (0, 0):
                continue
            ny, nx = ty + d[0], self._wrap_x(tx + d[1])
            if self._is_wall(ny, nx) or self._is_ghost_door(ny, nx):
                continue  # a frightened ghost may not hide in the pen (pacman-9)
            return d
        ny, nx = ty + reverse[0], self._wrap_x(tx + reverse[1])
        if not self._is_wall(ny, nx) and not self._is_ghost_door(ny, nx):
            return reverse
        return None

    def _pinky_target(self):
        """4 tiles ahead of Pac-Man, including the canon overflow bug: when
        Pac faces up, the target is 4 up AND 4 left."""
        dy, dx = self.pac_dir
        ty, tx = self.pac_y + dy * 4, self.pac_x + dx * 4
        if (dy, dx) == (-1, 0):
            tx -= 4
        return ty, tx

    def _inky_target(self, blinky):
        """The vector from Blinky to a point 2 tiles ahead of Pac (same
        up-overflow bug), doubled from Blinky's position."""
        dy, dx = self.pac_dir
        py, px = self.pac_y + dy * 2, self.pac_x + dx * 2
        if (dy, dx) == (-1, 0):
            px -= 2
        by, bx = blinky['y'], blinky['x']
        return by + 2 * (py - by), bx + 2 * (px - bx)

    def _ghost_target(self, ghost, blinky):
        if self.mode == 'scatter':
            return ghost['corner']
        name = ghost['name']
        if name == 'Blinky':
            return (self.pac_y, self.pac_x)
        if name == 'Pinky':
            return self._pinky_target()
        if name == 'Inky':
            return self._inky_target(blinky)
        # Clyde: chase beyond 8 tiles, flee to his corner within it.
        dy, dx = ghost['y'] - self.pac_y, ghost['x'] - self.pac_x
        if (dy * dy + dx * dx) ** 0.5 > 8:
            return (self.pac_y, self.pac_x)
        return ghost['corner']

    def _decide_hunt(self, ghost, blinky, ty, tx, direction):
        target = self._ghost_target(ghost, blinky)
        return self._best_dir(ty, tx, direction, target, allow_door=False)

    def _revive_on_enter(self, ty, tx, ghost):
        """Fires the instant an eaten ghost's fractional movement reaches a
        new tile center (the same on_enter mechanism Pac uses for dots,
        not a float-equality test on end-of-tick progress, which the
        fractional-movement engine can skip over entirely). Revives the
        ghost the moment it arrives at the pen tile, restoring normal
        speed and targeting from the very next tick."""
        if (ty, tx) == (10, 13):
            ghost['eaten'] = False
            ghost['released'] = True
            return True
        return False

    def _is_edible(self, ghost):
        """THE definition of "blue and eatable", read by every site that
        cares (movement AI, collision, render) so they can never disagree.

        A ghost eaten during a fright window and revived is NOT edible again
        on that same energizer (arcade canon: it comes back out of the pen in
        its normal state, even while the other ghosts are still blue). So it
        must ALSO hunt instead of flee, and run at normal speed instead of
        fright speed -- which is what re-deriving this condition separately in
        _move_one_ghost got wrong: it tested the global fright window alone,
        so a revived ghost kept running away from Pac at half speed while
        being lethal and drawn in its own color. Only a NEW energizer clears
        eaten_this_energizer and makes it edible again.

        A ghost that is currently 'eaten' (a pair of eyes heading home) is not
        edible either: it cannot be eaten twice.
        """
        return (self.frightened and not ghost['eaten']
                and not ghost['eaten_this_energizer'])

    def _move_one_ghost(self, ghost, blinky):
        in_house = self._in_house(ghost['y'], ghost['x'])
        on_enter = None
        if ghost['eaten']:
            speed = self._pac_speed() * self.EATEN_FRAC
            fn = self._decide_eaten
            on_enter = lambda ty, tx, g=ghost: self._revive_on_enter(ty, tx, g)
        elif not ghost['released']:
            return
        elif in_house:
            speed = self._pac_speed() * self._ghost_frac()
            fn = self._decide_house_exit
        elif self._is_edible(ghost):
            speed = self._pac_speed() * self.FRIGHT_FRAC
            fn = self._decide_frightened
        else:
            speed = self._pac_speed() * self._ghost_frac()
            fn = lambda ty, tx, d, g=ghost, b=blinky: self._decide_hunt(g, b, ty, tx, d)

        if not ghost['eaten'] and not in_house and self._in_tunnel(ghost['y'], ghost['x']):
            speed = self._pac_speed() * self.TUNNEL_FRAC

        ghost['y'], ghost['x'], ghost['progress'], ghost['dir'] = self._advance(
            ghost['y'], ghost['x'], ghost['progress'], ghost['dir'], fn, speed, on_enter)

    # ── per-tick game state ─────────────────────────────────────────────

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self.next_dir = (-1, 0)
        elif key in (curses.KEY_DOWN, ord('s')):
            self.next_dir = (1, 0)
        elif key in (curses.KEY_LEFT, ord('a')):
            self.next_dir = (0, -1)
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.next_dir = (0, 1)

    def _maybe_award_extra_life(self):
        if not self.extra_life_awarded and self.score >= self.EXTRA_LIFE_SCORE:
            self.extra_life_awarded = True
            self.lives += 1

    def _pac_on_enter(self, ty, tx):
        cell = self.maze[ty][tx]
        if cell in ('.', 'O'):
            self.maze[ty][tx] = ' '
            self.score += 50 if cell == 'O' else 10
            self.dots_left -= 1
            self.dots_eaten_level += 1
            self.starve_timer = 0
            self._maybe_award_extra_life()
            if cell == 'O':
                self.frightened = True
                self.frightened_timer = self._fright_ticks()
                self.chain = 0
                for ghost in self.ghosts:
                    ghost['eaten_this_energizer'] = False
                self._force_reverse_all()
            if not self.fruit_spawned_70 and self.dots_eaten_level >= 70:
                self.fruit_spawned_70 = True
                self.fruit_active, self.fruit_timer = True, self.FRUIT_TICKS
            elif not self.fruit_spawned_170 and self.dots_eaten_level >= 170:
                self.fruit_spawned_170 = True
                self.fruit_active, self.fruit_timer = True, self.FRUIT_TICKS
        if self.fruit_active and (ty, tx) == self._FRUIT_POS:
            self.score += self._fruit_value()
            self.fruit_active = False
            self._maybe_award_extra_life()

    def _check_collision(self):
        """Resolve pac/ghost overlap on the rendered (rounded) grid.
        Returns True on a fatal (dying) hit."""
        py, px = self._disp(self.pac_y, self.pac_x, self.pac_progress, self.pac_dir)
        for ghost in self.ghosts:
            if ghost['eaten'] or not ghost['released']:
                continue
            gy, gx = self._disp(ghost['y'], ghost['x'], ghost['progress'], ghost['dir'])
            if (gy, gx) != (py, px):
                continue
            if self._is_edible(ghost):
                ghost['eaten'] = True
                ghost['eaten_this_energizer'] = True
                self.score += 200 * (2 ** min(self.chain, 3))
                self.chain += 1
                self._maybe_award_extra_life()
            else:
                self._dying = self.DYING_TICKS
                return True
        return False

    def _reset_positions(self):
        self.pac_y, self.pac_x = 16, 13
        self.pac_progress = 0.0
        self.pac_dir = (0, 0)
        self.next_dir = (0, 1)
        self.frightened = False
        self.frightened_timer = 0
        self.chain = 0
        home_y, home_x = 10, 13
        offsets = [(0, 0), (0, -1), (0, 1), (0, 2)]
        for ghost, (oy, ox) in zip(self.ghosts, offsets):
            ghost['y'] = home_y + oy
            ghost['x'] = home_x + ox
            ghost['progress'] = 0.0
            ghost['dir'] = (0, 1)
            ghost['eaten'] = False
            ghost['eaten_this_energizer'] = False
            ghost['released'] = self.dots_eaten_level >= ghost['release_at']
        self.starve_timer = 0
        self._rng = random.Random(1000 + self.level)

    def _advance_level(self):
        self.level += 1
        self.maze = [list(row) for row in self._MAZE]
        self.dots_left = sum(1 for row in self.maze for c in row if c in ('.', 'O'))
        self.dots_eaten_level = 0
        self.fruit_active = False
        self.fruit_spawned_70 = False
        self.fruit_spawned_170 = False
        self._rng = random.Random(1000 + self.level)
        self._setup_ghost_release()
        self._enter_phase(0)
        self._reset_positions()
        self._level_pause = self.LEVEL_PAUSE_TICKS

    def update(self):
        self._clock += 1

        if self._dying > 0:
            self._dying -= 1
            if self._dying == 0:
                self.lives -= 1
                if self.lives <= 0:
                    self.game_over = True
                else:
                    self._reset_positions()
            return

        if self._level_pause > 0:
            self._level_pause -= 1
            return

        self.pac_y, self.pac_x, self.pac_progress, self.pac_dir = self._advance(
            self.pac_y, self.pac_x, self.pac_progress, self.pac_dir,
            self._pac_decide, self._pac_speed(), self._pac_on_enter)

        # Collision must be resolved BEFORE the last-dot win check: eating
        # the last dot on the same tick a ghost lands on Pac-Man used to
        # grant immunity to an otherwise fatal hit, since the level-advance
        # branch used to run first and return before collision was ever
        # checked.
        if self._check_collision():
            return

        if self.dots_left <= 0:
            self._advance_level()
            return

        if self.fruit_active:
            self.fruit_timer -= 1
            if self.fruit_timer <= 0:
                self.fruit_active = False

        if self.frightened:
            self.frightened_timer -= 1
            if self.frightened_timer <= 0:
                self.frightened = False
        elif self.mode_timer is not None:
            self.mode_timer -= 1
            if self.mode_timer <= 0:
                self._enter_phase(self.mode_phase + 1)
                self._force_reverse_all()

        self.starve_timer += 1
        pending = next((g for g in self.ghosts if not g['released']), None)
        if pending is not None and (self.dots_eaten_level >= pending['release_at']
                                    or self.starve_timer >= self.STARVE_TICKS):
            pending['released'] = True
            self.starve_timer = 0

        blinky = self.ghosts[0]
        for ghost in self.ghosts:
            self._move_one_ghost(ghost, blinky)

        self._check_collision()

    # ── rendering ────────────────────────────────────────────────────────

    def draw(self):
        maze_rows = self._maze_rows()
        maze_cols = self._maze_cols()
        off_y = max(1, (self.h - maze_rows - 3) // 2)
        off_x = max(0, (self.w - maze_cols) // 2)

        header = (f' PAC-MAN  Lvl:{self.level}  Score:{self.score}  '
                 f'Hi:{self._high}  Lives:{"c" * self.lives} ')
        self.safe_addstr(off_y - 1, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD | curses.color_pair(3))

        for ry, row in enumerate(self.maze):
            for rx, ch in enumerate(row):
                sy, sx = off_y + ry, off_x + rx
                if ch == '#':
                    self.safe_addstr(sy, sx, '#', curses.color_pair(6) | curses.A_BOLD)
                elif ch == '.':
                    self.safe_addstr(sy, sx, '.', curses.color_pair(7))
                elif ch == 'O':
                    if (self._clock // 6) % 2 == 0:
                        self.safe_addstr(sy, sx, 'O', curses.color_pair(3) | curses.A_BOLD)
                elif ch == '-':
                    self.safe_addstr(sy, sx, '-', curses.color_pair(5))

        if self.fruit_active:
            fy, fx = self._FRUIT_POS
            self.safe_addstr(off_y + fy, off_x + fx, '*', curses.color_pair(2) | curses.A_BOLD)

        for ghost in self.ghosts:
            gy, gx = self._disp(ghost['y'], ghost['x'], ghost['progress'], ghost['dir'])
            sy, sx = off_y + gy, off_x + gx
            if ghost['eaten']:
                ch, attr = '"', curses.color_pair(7) | curses.A_BOLD
            elif (self._is_edible(ghost) and ghost['released']
                  and not self._in_house(ghost['y'], ghost['x'])):
                near_end = self.frightened_timer <= max(1, int(2000 / self.get_timeout()))
                blink = near_end and (self._clock // 5) % 2 == 0
                ch, attr = 'm', (curses.color_pair(7) if blink else curses.color_pair(6)) | curses.A_BOLD
            else:
                ch, attr = ghost['glyph'], curses.color_pair(ghost['color']) | curses.A_BOLD
            self.safe_addstr(sy, sx, ch, attr)

        # Pac-Man drawn last so the death blink shows on top of the killer ghost.
        if self._dying == 0 or (self._dying % 8 < 4):
            py, px = self._disp(self.pac_y, self.pac_x, self.pac_progress, self.pac_dir)
            pac_ch = 'C' if (self._clock // 3) % 2 == 0 else 'o'
            self.safe_addstr(off_y + py, off_x + px, pac_ch, curses.color_pair(3) | curses.A_BOLD)

        if self._level_pause > 0:
            self.center_text(off_y + maze_rows // 2, f' LEVEL {self.level} ',
                             curses.A_REVERSE | curses.A_BOLD)

        self.draw_status_bar('WASD:Move ?:Help Esc:Quit')

    def get_controls(self):
        return [('WASD/Arrows', 'Move Pac-Man'), ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        total = sum(1 for row in self._MAZE for c in row if c in ('.', 'O'))
        return [('Level reached', self.level),
                ('Lives left', self.lives),
                ('Dots eaten (level)', total - self.dots_left)]

    def get_save_data(self):
        return {'maze': [list(row) for row in self.maze], 'score': self.score,
                'lives': self.lives, 'level': self.level,
                'pac_y': self.pac_y, 'pac_x': self.pac_x,
                'pac_progress': self.pac_progress,
                'pac_dir': list(self.pac_dir), 'next_dir': list(self.next_dir),
                'ghosts': [{**g, 'dir': list(g['dir'])} for g in self.ghosts],
                'frightened': self.frightened,
                'frightened_timer': self.frightened_timer,
                'chain': self.chain, 'clock': self._clock,
                'dots_left': self.dots_left, 'dots_eaten_level': self.dots_eaten_level,
                'starve_timer': self.starve_timer,
                'mode': self.mode, 'mode_phase': self.mode_phase, 'mode_timer': self.mode_timer,
                'fruit_active': self.fruit_active, 'fruit_timer': self.fruit_timer,
                'fruit_spawned_70': self.fruit_spawned_70,
                'fruit_spawned_170': self.fruit_spawned_170,
                'extra_life_awarded': self.extra_life_awarded,
                'dying': self._dying, 'level_pause': self._level_pause}
