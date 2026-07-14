"""Frogger."""
try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class FroggerGame(Game):
    name = "frogger"
    min_h = 20
    # Wide enough for the header at its own worst case (6-digit score, 4
    # lives on easy): 44 was narrower than the header could reach after
    # completing just level 1 (score 1110+ truncates Time, the exact stat
    # the whole game is built around), and it kept shrinking as the score
    # grew from there.
    min_w = 48
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
            # Not part of the save schema on purpose (see _lock_ride).
            self._ride = None
            row_typ = self._LANES[self.frog_row][0]
            if row_typ in ('river', 'turtle'):
                # Lock onto the platform RIGHT NOW, against the lanes
                # exactly as saved, before update() ever runs again and
                # advances them. Locking lazily inside update() instead
                # would compare this stale, already-one-tick-old frog_x
                # against entities that had *already* taken their first
                # post-resume step -- the same one-tick skew that made
                # riding unsafe before frogger-11 was fixed, just
                # relocated to the load boundary instead of every tick.
                # If this fails (corrupt/incompatible save), leave _ride
                # None; the first update() dies on it exactly as an
                # invalid saved position always has.
                width = self._ent_width(row_typ)
                submerged = row_typ == 'turtle' and self._turtle_submerged()
                self._lock_ride(self.frog_row, width, submerged)
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
        # No platform is locked onto right after a (re)spawn; see _lock_ride.
        self._ride = None

    def get_timeout(self):
        return self.TICK_MS

    def _ent_width(self, typ):
        if typ == 'river':
            return 5
        if typ in ('road', 'turtle'):
            return 3
        return 0

    def _q(self, v):
        """The one shared quantizer for turning a continuous position into a
        grid column -- used for entities here AND for the frog's column
        everywhere in this file (int(round(...))). Entities used to be
        quantized with int()/floor while the frog was quantized with
        round(): while riding, frog_x - entity stayed EXACTLY constant, but
        floor() steps down only at the .0 boundary while round() steps up
        at .5, so the two DISAGREED on which relative cell the frog was
        over purely from the mismatch, not from any real drift -- reading a
        frog on the log's edge cell as having slipped into the water. Both
        sides must use the same function or the "constant offset" invariant
        that makes riding safe stops holding once the position is
        fractional.
        """
        return int(round(v)) % self.FIELD_W

    def _covers(self, ent, width, col):
        s = self._q(ent)
        return any((s + k) % self.FIELD_W == col for k in range(width))

    def _find_platform(self, row, col, width):
        """Return (entity_index, cell_offset) if `col` sits on one of this
        row's entities right now, else None. `cell_offset` is `col`'s
        position within that entity's span (0..width-1) -- the exact `k`
        draw() uses to place that entity's cells, so a caller that pins to
        (entity_index, cell_offset) can never disagree with what gets
        drawn. Entities are spaced at least width+2 apart (_spawn_lanes),
        so at most one can ever match."""
        fw = self.FIELD_W
        for i, e in enumerate(self.lanes[row]['ents']):
            off = (col - self._q(e)) % fw
            if off < width:
                return i, off
        return None

    def _lock_ride(self, row, width, submerged):
        """(Re)attach the frog to whichever platform entity is under it
        right now, storing (row, entity_index, cell_offset) in self._ride
        and pinning frog_x to entity_value + cell_offset (cell_offset is an
        int).

        This is the fix for frogger-11: rounding commutes with adding an
        integer -- round(x + n) == round(x) + n for any integer n, always,
        no boundary cases -- so once frog_x is exactly
        `entity_value + cell_offset`, round(frog_x) equals
        round(entity_value) + cell_offset on every future tick with zero
        drift, by that identity alone.

        The old code instead left frog_x as the bare rounded landing
        column and separately re-accumulated d*cells onto it every tick
        afterward -- a SECOND float meant to stay in lockstep with the
        entity's own float. It started already one tick "behind" (entities
        advance before a hop is resolved, so the entity had already taken
        this tick's step while the newly-landed frog_x had not), and two
        independently-advancing, independently-rounded floats with a
        non-integer difference between them do not round in lockstep: at
        a platform's edge cells specifically (where the frog's rounded
        column is only a fraction of a cell from falling to the next
        integer either way), that lag was enough to flip which side of a
        rounding boundary the frog and its own platform landed on, a few
        ticks apart, and _covers() -- driven by two separately-rounded
        values -- read that as the frog having slipped off, or stayed
        safely on, a platform whose drawn cells said otherwise (frogger-11
        death-on-every-log/turtle, frogger-12 the mirror false-safe).

        Returns True if locked; False if there is no platform under the
        current column right now (caller must _die())."""
        col = int(round(self.frog_x)) % self.FIELD_W
        match = None if submerged else self._find_platform(row, col, width)
        if match is None:
            return False
        idx, off = match
        self._ride = (row, idx, off)
        self._ride_edge_x = float(col)
        self.frog_x = (self.lanes[row]['ents'][idx] + off) % self.FIELD_W
        return True

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
            submerged = typ == 'turtle' and self._turtle_submerged()
            if hopped:
                # Just landed here this tick: lock onto whatever is under
                # the frog right now (see _lock_ride for why this is what
                # eliminates the drift, not just the landing-tick check).
                if not self._lock_ride(row, width, submerged):
                    self._die()
                return
            ride = self._ride
            if ride is None or ride[0] != row:
                # Defensive only: every real path that can put the frog on
                # a river/turtle row locks a ride for it already (a hop,
                # just above, or setup() immediately on loading a save
                # mid-ride, before this tick's traffic advance runs) --
                # this re-lock exists purely so an unreachable/corrupt
                # state fails the same way an invalid position always has
                # (a single wasted life), never a silent misread. Note
                # this DOES carry the same one-tick skew a hop landing
                # avoids (frog_x here can be stale relative to the
                # traffic advance a few lines above), which is exactly
                # why setup() does not rely on this path for the load
                # case.
                if not self._lock_ride(row, width, submerged):
                    self._die()
                return
            _row, idx, off = ride
            # Track the frog's OWN unwrapped displacement since it locked
            # on, separately from the entity's own (wrapped-every-tick)
            # position, so "carried past the edge of the visible field"
            # keeps meaning what it always meant here: this specific
            # physical log/turtle -- not whatever entity happens to be
            # re-using that render slot after a wrap -- carried the frog
            # off-screen. The DRAWN/collision position below is derived
            # fresh from the entity every tick and never touches this.
            d, cells = self._lane_speed(row)
            self._ride_edge_x += d * cells
            if self._ride_edge_x < 0 or self._ride_edge_x > self.FIELD_W - 1:
                self._die()   # carried off-screen by the log/turtle
                return
            if submerged:
                self._die()
                return
            # Re-pin every tick: the entity is the single source of truth,
            # so this can never drift from what draw() renders for it.
            self.frog_x = (self.lanes[row]['ents'][idx] + off) % self.FIELD_W
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
        # Compact, single-spaced form: comfortably fits min_w even at a
        # 6-digit score (the old double-spaced form exceeded its own
        # declared min_w=44 the moment a player finished level 1).
        header = (f' FROGGER Lv{self.level} Score:{self.score} '
                  f'Lives:{"@" * self.lives} Time:{max(0, int(self.time_left)):02d} ')
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
                        cx = (self._q(e) + k) % fw
                        self.safe_addstr(y, sx + cx, '#',
                                         curses.color_pair(3) | curses.A_BOLD)
            elif typ == 'turtle':
                self.safe_addstr(y, sx, '~' * fw, curses.color_pair(6))
                submerged = self._turtle_submerged()
                ch = '.' if submerged else 'O'
                attr = curses.color_pair(6) if submerged else (curses.color_pair(5) | curses.A_BOLD)
                for e in self.lanes[i]['ents']:
                    for k in range(self._ent_width('turtle')):
                        cx = (self._q(e) + k) % fw
                        self.safe_addstr(y, sx + cx, ch, attr)
            else:  # road
                for e in self.lanes[i]['ents']:
                    for k in range(self._ent_width('road')):
                        cx = (self._q(e) + k) % fw
                        ch = '[' if k == 0 else (']' if k == 2 else 'o')
                        self.safe_addstr(y, sx + cx, ch,
                                         curses.color_pair(2) | curses.A_BOLD)
        fy = sy + self.frog_row
        # Must go through the shared quantizer _q() (which wraps % FIELD_W),
        # not a bare int(round(...)): while riding, frog_x = (entity +
        # offset) % FIELD_W can sit in [FIELD_W - 0.5, FIELD_W), and
        # int(round()) on that yields FIELD_W -- one column past the last
        # legal field column -- painting '@' over the play-area's right
        # border while collision (which does use _q()) still reads the frog
        # at column 0. That drew the frog safe while it wasn't drawn on any
        # platform at all, and corrupted the border (frogger draw-vs-
        # collision disagreement).
        fx = sx + self._q(self.frog_x)
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
