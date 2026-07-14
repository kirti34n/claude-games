"""Frogger."""
try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class FroggerGame(Game):
    name = "frogger"
    min_h = 20
    min_w = 44
    supports_difficulty = True

    FIELD_W = 40
    TICK_MS = 33                  # 30 Hz, per spec section 2
    # A hop is a discrete, committal grid step: at most one per tick, and it
    # cannot be repeated until this cooldown drains. ~110 ms is the arcade
    # recovery time; 3 ticks at 33 ms/tick (99 ms) is the closest multiple.
    HOP_COOLDOWN_TICKS = 3
    TURTLE_SURFACED_TICKS = 90    # ~3.0 s visible
    TURTLE_SUBMERGED_TICKS = 45   # ~1.5 s submerged (frogger-5: diving turtles)
    # Respawn grace: while OS key auto-repeat re-queues a still-held hop key
    # every tick, a fresh respawn used to accept and apply that hop
    # immediately (_reset_frog only cleared the queue at the moment of
    # death, not afterward), hopping the frog straight back into the traffic
    # that just killed it. A brief freeze that keeps discarding the queued
    # direction gives the player a chance to actually release/redirect the
    # key, matching the arcade's own death pause.
    DEATH_FREEZE_TICKS = 30       # ~1.0 s at the 33 ms tick

    # (type, direction, base cells/sec at level 1, medium difficulty).
    # 'turtle' is a river-type lane whose platforms periodically submerge.
    _LANES = [
        ('home',   0, 0.0),
        ('river',  1, 2.4),
        ('turtle', -1, 3.0),
        ('river',  1, 1.8),
        ('safe',   0, 0.0),
        ('road',  -1, 3.6),
        ('road',   1, 5.2),
        ('road',  -1, 2.6),
        ('safe',   0, 0.0),
    ]
    _HOME_BAYS = [4, 12, 20, 28, 36]   # five bays (frogger-3)

    _DIFF_LIVES = {'easy': 4, 'medium': 3, 'hard': 3}
    _DIFF_SPEED = {'easy': 0.85, 'medium': 1.0, 'hard': 1.2}
    _DIFF_TIME = {'easy': 35.0, 'medium': 30.0, 'hard': 25.0}

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.difficulty = saved.get('difficulty', self.difficulty)
            self.frog_row = saved['frog_row']
            self.frog_x = saved['frog_x']
            self.lanes = saved['lanes']
            self.lives = saved['lives']
            self.score = saved['score']
            self.homes = saved['homes']
            self.best_row = saved['best_row']
            # A save from before the 4-bay -> 5-bay layout (or a different
            # lane count) is schema-incompatible, not merely stale: loading
            # it verbatim would desync self.homes / self.frog_row from the
            # current _HOME_BAYS / _LANES and IndexError deep inside draw()
            # instead of setup(). Raise here so _run_loop's existing
            # recovery path (a fresh game) catches it, same as malformed JSON.
            if len(self.homes) != len(self._HOME_BAYS) or self.frog_row >= len(self._LANES):
                raise ValueError('incompatible frogger save schema')
            self.level = saved.get('level', 1)
            self.time_left = saved.get('time_left', self._DIFF_TIME[self.difficulty])
            self.hop_cooldown = 0
            self._queued_dir = None
            self._anim_tick = 0
            self._death_freeze = saved.get('death_freeze', 0)
            return
        self._new_game()

    def _new_game(self):
        self.level = 1
        self.lives = self._DIFF_LIVES[self.difficulty]
        self.score = 0
        self.homes = [False] * len(self._HOME_BAYS)
        self.hop_cooldown = 0
        self._queued_dir = None
        self._anim_tick = 0
        self._death_freeze = 0
        self._spawn_lanes()
        self._reset_frog()

    def _spawn_lanes(self):
        self.lanes = []
        for i, (typ, _d, _spd) in enumerate(self._LANES):
            if typ in ('road', 'river', 'turtle'):
                width = self._ent_width(typ)
                base_gap = 8 if typ == 'road' else 9
                # Traffic thickens with level, floored at width+2 so entities
                # can never overlap or fuse (frogger-4), even at high levels.
                gap = max(width + 2, base_gap - (self.level - 1))
                ents = self._make_entities(width, gap, i)
            else:
                ents = []
            self.lanes.append({'ents': ents})

    def _make_entities(self, width, target_gap, lane_index):
        # Entities are spaced EVENLY around the field (spacing * count ==
        # FIELD_W exactly), so the x=39->0 wrap seam has the same gap as
        # everywhere else. The old fixed-step generator (frogger-4) instead
        # left a narrower final gap at that seam, which fused two logs into
        # a permanent mega-platform.
        count = max(1, self.FIELD_W // target_gap)
        spacing = self.FIELD_W / count
        offset = (lane_index * 3) % spacing
        return [(i * spacing + offset) % self.FIELD_W for i in range(count)]

    def _reset_frog(self):
        self.frog_row = len(self._LANES) - 1
        self.frog_x = float(self.FIELD_W // 2)
        self.best_row = self.frog_row
        self.hop_cooldown = 0
        self._queued_dir = None
        self.time_left = self._DIFF_TIME[self.difficulty]

    def get_timeout(self):
        return self.TICK_MS

    def _ent_width(self, typ):
        if typ == 'river':
            return 5
        if typ in ('road', 'turtle'):
            return 3
        return 0

    def _covers(self, ent, width, col):
        s = int(ent) % self.FIELD_W
        return any((s + k) % self.FIELD_W == col for k in range(width))

    def _lane_speed(self, row):
        _typ, d, base = self._LANES[row]
        level_mult = min(2.0, 1.0 + 0.12 * (self.level - 1))
        diff_mult = self._DIFF_SPEED[self.difficulty]
        cells_per_sec = base * level_mult * diff_mult
        return d, cells_per_sec * (self.TICK_MS / 1000.0)

    def _turtle_submerged(self):
        cycle = self.TURTLE_SURFACED_TICKS + self.TURTLE_SUBMERGED_TICKS
        return (self._anim_tick % cycle) >= self.TURTLE_SURFACED_TICKS

    def handle_input(self, key):
        # Edge-triggered: a keypress only QUEUES a hop direction, it never
        # mutates frog_row/frog_x directly. update() performs at most one
        # hop per tick (gated by hop_cooldown) and checks the landed lane
        # immediately, in the SAME update() call (frogger-1: the old code
        # moved the frog here with zero collision checking, so buffered
        # keypresses could carry it clean through the road and river
        # between two ticks).
        if key in (curses.KEY_UP, ord('w')):
            self._queued_dir = 'up'
        elif key in (curses.KEY_DOWN, ord('s')):
            self._queued_dir = 'down'
        elif key in (curses.KEY_LEFT, ord('a')):
            self._queued_dir = 'left'
        elif key in (curses.KEY_RIGHT, ord('d')):
            self._queued_dir = 'right'

    def _apply_hop(self, direction):
        if direction == 'up' and self.frog_row > 0:
            self.frog_row -= 1
            if self.frog_row < self.best_row:
                self.best_row = self.frog_row
                self.score += 10
        elif direction == 'down':
            self.frog_row = min(len(self._LANES) - 1, self.frog_row + 1)
        elif direction == 'left':
            self.frog_x = max(0.0, self.frog_x - 1.0)
        elif direction == 'right':
            self.frog_x = min(self.FIELD_W - 1.0, self.frog_x + 1.0)

    def _die(self):
        # Clamp before the frog can be drawn again: a river/edge death can
        # leave frog_x fractionally outside [0, FIELD_W-1], which used to
        # draw the frog one column outside the field on the final life
        # (frogger-10).
        self.frog_x = min(self.FIELD_W - 1.0, max(0.0, self.frog_x))
        self.lives -= 1
        if self.lives <= 0:
            self.game_over = True
        else:
            self._reset_frog()
            self._death_freeze = self.DEATH_FREEZE_TICKS

    def _reach_home(self):
        col = int(round(self.frog_x))
        bay = min(range(len(self._HOME_BAYS)),
                  key=lambda i: abs(self._HOME_BAYS[i] - col))
        if abs(self._HOME_BAYS[bay] - col) > 2 or self.homes[bay]:
            self._die()          # missed a bay or landed on a filled one
            return
        self.homes[bay] = True
        # Canonical time bonus: the faster the bay is reached, the bigger it is.
        self.score += 50 + int(self.time_left) * 2
        if all(self.homes):
            self.score += 1000
            self.level += 1
            self.homes = [False] * len(self._HOME_BAYS)
            self._spawn_lanes()
        self._reset_frog()

    def update(self):
        if self.game_over:
            return
        if self._death_freeze > 0:
            self._death_freeze -= 1
            # Discard any hop a still-held key re-queues during the freeze,
            # so the very first tick of control also can't walk the frog
            # straight back into the traffic that just killed it.
            self._queued_dir = None
            return
        self._anim_tick += 1

        # The 30 s clock is Frogger's real antagonist: it is what forces a
        # committal hop into a gap instead of waiting for a perfectly safe
        # one (frogger-2).
        self.time_left -= self.TICK_MS / 1000.0
        if self.time_left <= 0:
            self._die()
            return

        if self.hop_cooldown > 0:
            self.hop_cooldown -= 1

        row_before = self.frog_row
        pre_typ = self._LANES[row_before][0]
        pre_col = int(round(self.frog_x))
        was_on_platform = False
        if pre_typ in ('river', 'turtle'):
            width = self._ent_width(pre_typ)
            submerged = pre_typ == 'turtle' and self._turtle_submerged()
            was_on_platform = (not submerged) and any(
                self._covers(e, width, pre_col) for e in self.lanes[row_before]['ents'])

        # Advance all traffic, once, every tick.
        for i, (t, _d, _bs) in enumerate(self._LANES):
            if t in ('road', 'river', 'turtle'):
                d, cells = self._lane_speed(i)
                self.lanes[i]['ents'] = [(e + d * cells) % self.FIELD_W
                                         for e in self.lanes[i]['ents']]

        hopped = False
        direction = self._queued_dir
        if direction and self.hop_cooldown <= 0:
            self._queued_dir = None
            self._apply_hop(direction)
            self.hop_cooldown = self.HOP_COOLDOWN_TICKS
            hopped = True

        row = self.frog_row
        typ = self._LANES[row][0]

        if typ == 'home':
            if hopped:
                self._reach_home()   # the row the frog left is irrelevant; only
            return                  # the lane actually entered this tick matters

        if typ in ('river', 'turtle'):
            width = self._ent_width(typ)
            col = int(round(self.frog_x))
            if hopped:
                # Just landed here this tick: judge against what is here now.
                submerged = typ == 'turtle' and self._turtle_submerged()
                on_platform = (not submerged) and any(
                    self._covers(e, width, col) for e in self.lanes[row]['ents'])
            else:
                # Stationary: judge against the pre-move snapshot (matches
                # what was actually drawn under the frog last frame), then
                # ride the platform in lockstep so the frog never slips off
                # its back edge.
                on_platform = was_on_platform
            if not on_platform:
                self._die()
                return
            if not hopped:
                d, cells = self._lane_speed(row)
                self.frog_x += d * cells
                if self.frog_x < 0 or self.frog_x > self.FIELD_W - 1:
                    self._die()   # carried off-screen by the log/turtle
            return

        if typ == 'road':
            # Cars can slide onto a stationary frog, so check post-move.
            col = int(round(self.frog_x))
            if any(self._covers(e, self._ent_width('road'), col)
                   for e in self.lanes[row]['ents']):
                self._die()

    def draw(self):
        fw = self.FIELD_W
        n = len(self._LANES)
        sx = max(0, (self.w - fw) // 2)
        sy = max(1, (self.h - n - 3) // 2)
        header = (f' FROGGER  Lv{self.level}  Score:{self.score} '
                  f' Lives:{"@" * self.lives}  Time:{max(0, int(self.time_left)):02d} ')
        self.safe_addstr(max(0, sy - 2), max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        self.draw_box(sy - 1, max(0, sx - 1), n + 2, fw + 2, curses.color_pair(7))
        for i, (typ, _d, _spd) in enumerate(self._LANES):
            y = sy + i
            if typ == 'home':
                self.safe_addstr(y, sx, '^' * fw, curses.color_pair(1))
                for bi, bx in enumerate(self._HOME_BAYS):
                    # Draw the bay as wide as its catch zone (bx-2..bx+2) so the
                    # target the player aims at matches where a landing counts.
                    slot = '[=O=]' if self.homes[bi] else '[___]'
                    self.safe_addstr(y, sx + bx - 2, slot,
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
            elif typ == 'turtle':
                self.safe_addstr(y, sx, '~' * fw, curses.color_pair(6))
                submerged = self._turtle_submerged()
                ch = '.' if submerged else 'O'
                attr = curses.color_pair(6) if submerged else (curses.color_pair(5) | curses.A_BOLD)
                for e in self.lanes[i]['ents']:
                    for k in range(self._ent_width('turtle')):
                        cx = (int(e) + k) % fw
                        self.safe_addstr(y, sx + cx, ch, attr)
            else:  # road
                for e in self.lanes[i]['ents']:
                    for k in range(self._ent_width('road')):
                        cx = (int(e) + k) % fw
                        ch = '[' if k == 0 else (']' if k == 2 else 'o')
                        self.safe_addstr(y, sx + cx, ch,
                                         curses.color_pair(2) | curses.A_BOLD)
        fy = sy + self.frog_row
        fx = sx + int(round(self.frog_x))
        self.safe_addstr(fy, fx, '@',
                         curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
        self.draw_status_bar('WASD:Hop ?:Help Esc:Quit')

    def get_controls(self):
        return [('WASD/Arrows', 'Hop'), ('P', 'Pause'), ('ESC', 'Quit / save')]

    def get_stats(self):
        return [('Level', self.level),
                ('Homes filled', f'{sum(self.homes)}/{len(self.homes)}'),
                ('Lives left', self.lives)]

    def get_save_data(self):
        return {'difficulty': self.difficulty,
                'frog_row': self.frog_row, 'frog_x': self.frog_x,
                'lanes': self.lanes, 'lives': self.lives, 'score': self.score,
                'homes': self.homes, 'best_row': self.best_row,
                'level': self.level, 'time_left': self.time_left,
                'death_freeze': self._death_freeze}
