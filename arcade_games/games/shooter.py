"""Space Shooter game."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class ShooterGame(Game):
    name = "shooter"
    min_h = 20
    min_w = 40
    supports_difficulty = True

    _ENEMY_ART = {'basic': '<V>', 'zigzag': '<W>', 'diver': '<X>', 'tank': '[=]'}
    _BOSS_ART = [' [===] ', '/|||||\\', ' \\___/ ']

    # Pacing table (SPEC.md section 2): 33 ms / 30 Hz tick, ship 1 cell/tick,
    # fire cooldown 180 ms, player bullet 1.5 c/t, enemy bullet 0.5 c/t (a
    # strict 3:1 ratio), wave ramp on spawn rate AND enemy speed.
    _TICK_MS = 33
    _FIRE_COOLDOWN_MS = 180
    _POWERUP_MS = 10000
    _WAVE_MSG_MS = 1500
    _PLAYER_BULLET_DY = 1.5
    _ENEMY_BULLET_DY = 0.5
    _BOSS_SPEED = 0.66
    _MAX_PLAYER_BULLETS = 4
    # Bumped whenever get_save_data()'s schema changes. setup() only trusts
    # a save whose stamp matches: blind setattr from an older/newer schema
    # (missing 'fire_cooldown'/'anim'/'fire_timer', ...) used to load fine
    # and then crash later inside update() with an uncaught AttributeError,
    # since only setup() is wrapped by _run_loop's schema-mismatch recovery
    # (shooter-12).
    _SAVE_VERSION = 2

    def setup(self):
        saved = self._load_save(self.name)
        if saved and saved.get('_v') == self._SAVE_VERSION:
            # The difficulty just chosen at the picker (self.difficulty, set
            # by the caller before setup()) must win over whatever was in
            # effect when the save was written, not the other way around.
            # That means every value difficulty actually controls (lives,
            # base_enemy_speed, base_spawn_rate, boss_fire_rate) has to be
            # re-derived from the picker's choice, not restored verbatim
            # from the save (shooter-12).
            diff = self.difficulty
            for k, v in saved.items():
                if k in ('_v', 'difficulty'):
                    continue
                setattr(self, k, v)
            self.difficulty = diff
            self.lives = {'easy': 5, 'medium': 3, 'hard': 2}[diff]
            self.base_enemy_speed = {'easy': 0.35, 'medium': 0.55, 'hard': 0.8}[diff]
            self.base_spawn_rate = {'easy': 1250, 'medium': 900, 'hard': 600}[diff]
            self.boss_fire_rate = {'easy': 1000, 'medium': 600, 'hard': 360}[diff]
            self._update_wave_params()
            self._fit_bounds()
            return
        diff = self.difficulty
        self.lives = {'easy': 5, 'medium': 3, 'hard': 2}[diff]
        self.base_enemy_speed = {'easy': 0.35, 'medium': 0.55, 'hard': 0.8}[diff]
        self.base_spawn_rate = {'easy': 1250, 'medium': 900, 'hard': 600}[diff]
        self.boss_fire_rate = {'easy': 1000, 'medium': 600, 'hard': 360}[diff]
        self.player_x = self.w // 2
        self.score = 0
        self.wave = 1
        self.kills = 0
        self.kills_needed = 10
        self.fire_cooldown = 0
        self.spawn_timer = self.base_spawn_rate
        self.bullets = []
        self.enemy_bullets = []
        self.enemies = []
        self.particles = []
        self.powerups = []
        self.spread = 0
        self.shield = False
        self.speed_boost = 0
        self.boss = None
        self.wave_msg_timer = 0
        self._update_wave_params()
        self._fit_bounds()

    def _fit_bounds(self):
        # A save from a wider/taller terminal resumed in a smaller one must
        # not leave the ship, bullets or enemies parked off-screen. Clamping
        # only x (as before) left enemy/bullet y untouched, so a save from a
        # taller terminal could resume with enemies already past
        # self.h - 3 and cost a life on the very first tick (shooter-12).
        self.player_x = max(2, min(self.w - 2, self.player_x))
        if self.boss:
            self.boss['x'] = max(1, min(self.w - 8, self.boss['x']))
            self.boss['y'] = max(1, min(self.h - 6, self.boss.get('y', 2)))
        for e in self.enemies:
            e['x'] = max(0, min(self.w - 4, e['x']))
            e['base_x'] = max(0, min(self.w - 4, e.get('base_x', e['x'])))
            e['y'] = max(1, min(self.h - 4, e['y']))
        for b in self.bullets:
            b['x'] = max(0, min(self.w - 1, b['x']))
            b['y'] = max(0, min(self.h - 1, b['y']))
        for b in self.enemy_bullets:
            b['x'] = max(0, min(self.w - 1, b['x']))
            b['y'] = max(0, min(self.h - 1, b['y']))
        for p in self.powerups:
            p['x'] = max(0, min(self.w - 1, p['x']))
            p['y'] = max(0, min(self.h - 1, p['y']))

    def on_resize(self):
        self._fit_bounds()

    def _update_wave_params(self):
        # Wave ramp: both spawn rate and enemy speed climb, so late waves
        # are actually harder, not just longer.
        factor = 1 + 0.12 * (self.wave - 1)
        self.enemy_speed = min(self.base_enemy_speed * factor,
                               self.base_enemy_speed * 3.0)
        self.spawn_rate = max(250, self.base_spawn_rate / factor)

    def get_timeout(self):
        return self._TICK_MS

    def get_controls(self):
        return [('A/D', 'Move ship'), ('Space', 'Fire'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        return [('Wave', self.wave), ('Kills', self.kills)]

    def get_save_data(self):
        return {
            '_v': self._SAVE_VERSION,
            'lives': self.lives,
            'base_enemy_speed': self.base_enemy_speed,
            'base_spawn_rate': self.base_spawn_rate,
            'boss_fire_rate': self.boss_fire_rate,
            'enemy_speed': self.enemy_speed,
            'spawn_rate': self.spawn_rate,
            'player_x': self.player_x, 'score': self.score,
            'wave': self.wave, 'kills': self.kills,
            'kills_needed': self.kills_needed,
            'fire_cooldown': self.fire_cooldown,
            'spawn_timer': self.spawn_timer,
            'bullets': self.bullets, 'enemy_bullets': self.enemy_bullets,
            'enemies': self.enemies, 'particles': self.particles,
            'powerups': self.powerups,
            'spread': self.spread, 'shield': self.shield,
            'speed_boost': self.speed_boost, 'boss': self.boss,
            'wave_msg_timer': self.wave_msg_timer,
        }

    def handle_input(self, key):
        # Fire is edge-triggered: one press, one shot, gated by a cooldown
        # so mashing or holding Space cannot bypass it either. Steering is
        # continuous and lives in update() instead.
        if key == ord(' '):
            self._try_fire()

    def _try_fire(self):
        if self.fire_cooldown > 0:
            return
        # Enforce the cap per-bullet (append while under it) instead of
        # rejecting the whole volley when the cap can't fit every bullet a
        # single fire event would add. Rejecting the volley made SPREAD (3
        # bullets/shot) fire LESS often than a plain shot whenever 2+
        # bullets were already alive: 600 ticks of cleared-cooldown firing
        # gave 160 volleys without spread vs only 98 with it, a 39% drop.
        # A powerup must never be a downgrade.
        if len(self.bullets) >= self._MAX_PLAYER_BULLETS:
            return
        self.fire_cooldown = self._FIRE_COOLDOWN_MS
        by = self.h - 4
        self.bullets.append({'x': float(self.player_x), 'y': float(by)})
        if self.spread > 0:
            if len(self.bullets) < self._MAX_PLAYER_BULLETS:
                self.bullets.append({'x': float(self.player_x - 2), 'y': float(by + 1)})
            if len(self.bullets) < self._MAX_PLAYER_BULLETS:
                self.bullets.append({'x': float(self.player_x + 2), 'y': float(by + 1)})

    def _enemy_fire_delay(self):
        # Firing frequency also ramps with wave, on top of speed/spawn rate.
        lo = max(400, 1400 - self.wave * 70)
        hi = max(lo + 400, 2400 - self.wave * 90)
        return random.randint(lo, hi)

    def _spawn_enemy(self):
        if self.boss or self.w < 9:
            return  # randint(3, w-6) needs w >= 9; bail on ultra-narrow screens
        types = ['basic'] * 50 + ['zigzag'] * 25 + ['diver'] * 15 + ['tank'] * 10
        etype = random.choice(types)
        hp = 3 if etype == 'tank' else 1
        x = float(random.randint(3, max(3, self.w - 6)))
        self.enemies.append({
            'x': x, 'base_x': x, 'y': 2.0,
            'type': etype, 'hp': hp, 'anim': 0,
            'fire_timer': self._enemy_fire_delay(),
        })

    def _spawn_boss(self):
        self.boss = {
            'x': float(self.w // 2 - 3), 'y': 2,
            'hp': 10 + self.wave * 5,
            'max_hp': 10 + self.wave * 5,
            'fire_timer': self.boss_fire_rate, 'dir': 1,
        }

    def _add_particles(self, x, y, count=3):
        for _ in range(count):
            self.particles.append({
                'x': x + random.randint(-1, 1),
                'y': y + random.randint(-1, 1),
                'ch': random.choice(['*', '+', '.']),
                'ttl': random.randint(2, 5),
            })

    def update(self):
        if self.fire_cooldown > 0:
            self.fire_cooldown -= self._TICK_MS
        if self.speed_boost > 0:
            self.speed_boost -= self._TICK_MS
        if self.spread > 0:
            self.spread -= self._TICK_MS
        if self.wave_msg_timer > 0:
            self.wave_msg_timer -= self._TICK_MS

        # Continuous ship steering: at most one step per tick, reading keys
        # collected since the last update() instead of moving inside
        # handle_input() (which would tie speed to OS key-repeat).
        speed = 2 if self.speed_boost > 0 else 1
        if self.held(curses.KEY_LEFT, ord('a')):
            self.player_x = max(2, self.player_x - speed)
        if self.held(curses.KEY_RIGHT, ord('d')):
            self.player_x = min(self.w - 2, self.player_x + speed)

        # Move bullets. 1.5 c/t player vs 0.5 c/t enemy keeps the canonical
        # 3:1 speed ratio.
        self.bullets = [{'x': b['x'], 'y': b['y'] - self._PLAYER_BULLET_DY}
                        for b in self.bullets if b['y'] > 0]
        new_eb = []
        for b in self.enemy_bullets:
            nx = b['x'] + b.get('dx', 0.0)
            ny = b['y'] + b.get('dy', self._ENEMY_BULLET_DY)
            if ny < self.h:
                new_eb.append({'x': nx, 'y': ny,
                               'dx': b.get('dx', 0.0),
                               'dy': b.get('dy', self._ENEMY_BULLET_DY)})
        self.enemy_bullets = new_eb

        # Move enemies and let them fire: every regular type now shoots,
        # loosely aimed toward the ship's current column.
        for e in self.enemies:
            e['anim'] += 1
            if e['type'] == 'basic':
                e['y'] += self.enemy_speed
            elif e['type'] == 'zigzag':
                e['y'] += self.enemy_speed
                offset = abs((e['anim'] % 20) - 10) - 5
                e['x'] = max(1, min(self.w - 4, e['base_x'] + offset))
            elif e['type'] == 'diver':
                e['y'] += self.enemy_speed * 1.5
                if e['x'] < self.player_x:
                    e['x'] += 1
                elif e['x'] > self.player_x:
                    e['x'] -= 1
            elif e['type'] == 'tank':
                e['y'] += self.enemy_speed * 0.6
            e['fire_timer'] -= self._TICK_MS
            if e['fire_timer'] <= 0 and e['y'] > 1:
                if e['x'] < self.player_x - 1:
                    dx = 0.3
                elif e['x'] > self.player_x + 1:
                    dx = -0.3
                else:
                    dx = 0.0
                self.enemy_bullets.append({'x': e['x'] + 1, 'y': e['y'] + 1,
                                           'dx': dx, 'dy': self._ENEMY_BULLET_DY})
                e['fire_timer'] = self._enemy_fire_delay()

        # Boss movement and shooting.
        if self.boss:
            b = self.boss
            b['x'] += b['dir'] * self._BOSS_SPEED
            if b['x'] <= 1:
                b['dir'] = 1
            elif b['x'] >= self.w - 8:
                b['dir'] = -1
            b['fire_timer'] -= self._TICK_MS
            if b['fire_timer'] <= 0:
                b['fire_timer'] = self.boss_fire_rate
                self.enemy_bullets.append({'x': b['x'] + 3, 'y': b['y'] + 3,
                                           'dx': 0.0, 'dy': self._ENEMY_BULLET_DY})

        # Player bullets hit enemies/boss.
        new_bullets = []
        for b in self.bullets:
            hit = False
            if self.boss:
                bx, by = self.boss['x'], self.boss['y']
                if by <= b['y'] <= by + 2 and bx <= b['x'] <= bx + 6:
                    self.boss['hp'] -= 1
                    self._add_particles(b['x'], b['y'])
                    if self.boss['hp'] <= 0:
                        self._add_particles(bx + 3, by + 1, 8)
                        self.score += 500
                        self.boss = None
                        self.wave += 1
                        self.kills = 0
                        self.kills_needed = 10 + self.wave * 2
                        self.wave_msg_timer = self._WAVE_MSG_MS
                        self._update_wave_params()
                    hit = True
            if not hit:
                for e in self.enemies:
                    art_w = len(self._ENEMY_ART[e['type']])
                    if (abs(b['y'] - e['y']) <= 1 and
                            e['x'] <= b['x'] <= e['x'] + art_w - 1):
                        e['hp'] -= 1
                        if e['hp'] <= 0:
                            self._add_particles(e['x'] + art_w // 2, e['y'])
                            self.kills += 1
                            pts = {'basic': 10, 'zigzag': 20,
                                   'diver': 25, 'tank': 50}
                            self.score += pts.get(e['type'], 10)
                            if random.random() < 0.1:
                                ptype = random.choice(['S', 'O', '>'])
                                self.powerups.append({
                                    'x': float(e['x']), 'y': float(e['y']),
                                    'type': ptype,
                                })
                        hit = True
                        break
            if not hit:
                new_bullets.append(b)
        self.bullets = new_bullets
        self.enemies = [e for e in self.enemies if e['hp'] > 0]

        # Enemy bullets hit the player.
        px, py = self.player_x, self.h - 3
        new_eb2 = []
        for b in self.enemy_bullets:
            if abs(b['x'] - px) <= 1 and abs(b['y'] - py) <= 1:
                if self.shield:
                    self.shield = False
                else:
                    self.lives -= 1
                    self._add_particles(px, py, 5)
                    if self.lives <= 0:
                        self.game_over = True
                        return
            else:
                new_eb2.append(b)
        self.enemy_bullets = new_eb2

        # Any enemy that reaches the ship's row costs a life, whether or
        # not it lines up with the ship: letting one slip past the bottom
        # used to be a free despawn, which made cornering trivially safe.
        survivors = []
        for e in self.enemies:
            if e['y'] >= self.h - 3:
                if self.shield:
                    self.shield = False
                else:
                    self.lives -= 1
                    self._add_particles(px, py, 5)
                    if self.lives <= 0:
                        self.game_over = True
                        return
            else:
                survivors.append(e)
        self.enemies = survivors

        # Move and collect power-ups.
        new_pups = []
        for p in self.powerups:
            p['y'] += 0.33
            if p['y'] >= self.h:
                continue
            if abs(p['x'] - px) <= 2 and abs(p['y'] - py) <= 1:
                if p['type'] == 'S':
                    self.spread = self._POWERUP_MS
                elif p['type'] == 'O':
                    self.shield = True
                elif p['type'] == '>':
                    self.speed_boost = self._POWERUP_MS
            else:
                new_pups.append(p)
        self.powerups = new_pups

        # Particles decay.
        self.particles = [{'x': p['x'], 'y': p['y'], 'ch': p['ch'],
                          'ttl': p['ttl'] - 1}
                         for p in self.particles if p['ttl'] > 1]

        # Spawn enemies.
        self.spawn_timer -= self._TICK_MS
        if self.spawn_timer <= 0 and not self.boss:
            self._spawn_enemy()
            self.spawn_timer = self.spawn_rate

        # Wave progression.
        if not self.boss and self.kills >= self.kills_needed:
            self.wave += 1
            self.kills = 0
            self.kills_needed = 10 + self.wave * 2
            self.wave_msg_timer = self._WAVE_MSG_MS
            self._update_wave_params()
            if self.wave % 5 == 0:
                self._spawn_boss()

    def draw(self):
        # Header: title, HUD line, lives. Each lives on its own row so the
        # status footer (drawn last, full width) never overlaps them even
        # at min_w.
        self.safe_addstr(0, 2, 'SPACE SHOOTER', curses.A_BOLD)
        lives_s = '*' * max(0, self.lives)
        self.safe_addstr(0, max(0, self.w - len(lives_s) - 2), lives_s,
                         curses.color_pair(2) | curses.A_BOLD)

        info = f'Score:{self.score}  Wave:{self.wave}  Kills:{self.kills}/{self.kills_needed}'
        tags = []
        if self.spread > 0:
            tags.append('SPREAD')
        if self.shield:
            tags.append('SHIELD')
        if self.speed_boost > 0:
            tags.append('SPEED')
        if tags:
            info += '   ' + ' '.join(tags)
        self.safe_addstr(1, 2, info, curses.color_pair(3) | curses.A_BOLD)

        # Wave announcement
        if self.wave_msg_timer > 0:
            self.center_text(self.h // 3, f'  WAVE {self.wave}  ',
                             curses.A_BOLD | curses.A_REVERSE)

        # Enemies
        for e in self.enemies:
            art = self._ENEMY_ART[e['type']]
            color = {'basic': 2, 'zigzag': 5, 'diver': 3, 'tank': 6}
            self.safe_addstr(int(e['y']), int(e['x']), art,
                             curses.color_pair(color.get(e['type'], 7))
                             | curses.A_BOLD)

        # Boss
        if self.boss:
            bx, by = int(self.boss['x']), int(self.boss['y'])
            for i, line in enumerate(self._BOSS_ART):
                self.safe_addstr(by + i, bx, line,
                                 curses.color_pair(2) | curses.A_BOLD)
            hp_w = min(20, self.w - 10)
            filled = max(0, int(hp_w * self.boss['hp'] / self.boss['max_hp']))
            bar = '#' * filled + '-' * (hp_w - filled)
            self.center_text(by + 4, f'[{bar}]', curses.color_pair(2))

        # Bullets
        for b in self.bullets:
            self.safe_addstr(int(b['y']), int(b['x']), '|',
                             curses.color_pair(3) | curses.A_BOLD)
        for b in self.enemy_bullets:
            self.safe_addstr(int(b['y']), int(b['x']), '.',
                             curses.color_pair(2) | curses.A_BOLD)

        # Power-ups
        for p in self.powerups:
            self.safe_addstr(int(p['y']), int(p['x']), p['type'],
                             curses.color_pair(1) | curses.A_BOLD
                             | curses.A_REVERSE)

        # Particles
        for p in self.particles:
            self.safe_addstr(int(p['y']), int(p['x']), p['ch'],
                             curses.color_pair(3))

        # Player ship
        self.safe_addstr(self.h - 3, self.player_x - 1, '/A\\',
                         curses.color_pair(1) | curses.A_BOLD)
        if self.shield:
            self.safe_addstr(self.h - 2, self.player_x - 2, '(===)',
                             curses.color_pair(4) | curses.A_BOLD)

        self.draw_status_bar('A/D:Move Spc:Fire ?:Help Esc:Quit')
