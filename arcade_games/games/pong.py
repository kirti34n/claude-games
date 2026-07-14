"""Pong."""
import math
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class PongGame(Game):
    name = "pong"
    supports_difficulty = True

    PADDLE_H = 5
    WIN_SCORE = 11
    # Fixed logical field, always. Drawing centers it in the live terminal so
    # collision math never depends on window size (pong-8): shrinking the
    # terminal used to gift free points because the field boundary was the
    # live column count. Net mode already did this; solo now matches it.
    NET_FIELD_W = 60
    NET_FIELD_H = 20
    # The declared minimum IS the fixed field: setup() used to overwrite
    # these unconditionally with NET_FIELD_W/H, which made a separate
    # 40x18 class-level value dead and misleading (anything reading
    # PongGame.min_w/min_h directly, e.g. the game picker, before an
    # instance runs setup() saw a size the game never actually accepts).
    min_w = NET_FIELD_W
    min_h = NET_FIELD_H

    # Ball speed ratchet: 0.35 -> 0.85 cells/tick over a 2-threshold, 3-step
    # rally ladder (SPEC section 2). Speed resets to the base level on every
    # serve; only sustained rallies climb it.
    SPEED_LEVELS = (0.35, 0.6, 0.85)
    RALLY_THRESHOLDS = (4, 8)

    # 8 quantized deflection zones with a double-wide flat center (zones 3
    # and 4 both return the ball dead straight). Index 0 = top of the
    # paddle, 7 = bottom.
    ZONE_ANGLES_DEG = (-60, -45, -30, 0, 0, 30, 45, 60)

    # Bumped whenever get_save_data()'s schema changes. setup() only trusts
    # a save whose stamp matches; an older/newer schema falls through to a
    # fresh game instead of blind-setattr'ing missing fields (e.g. 'rally',
    # added after this field existed) and crashing later inside update()
    # with an uncaught AttributeError (mirrors shooter's _SAVE_VERSION /
    # shooter-12).
    _SAVE_VERSION = 1

    def _pw(self):
        return self.NET_FIELD_W

    def _ph(self):
        return self.NET_FIELD_H

    def _origin(self):
        return (max(0, (self.h - self.NET_FIELD_H) // 2),
                max(0, (self.w - self.NET_FIELD_W) // 2))

    def setup(self):
        # In a network game the host owns physics (left paddle); the guest sends
        # its paddle (right) and renders the host's authoritative state.
        self.net = getattr(self, 'net', None)
        self.role = getattr(self, 'role', 'host')
        saved = self._load_save(self.name) if not self.net else None
        if saved and saved.get('_v') == self._SAVE_VERSION:
            # The difficulty just chosen at the picker (self.difficulty, set
            # by the caller before setup()) must win over whatever was in
            # effect when the save was written (shooter-12's second half):
            # otherwise re-entering at a new difficulty silently resumes the
            # old one.
            diff = self.difficulty
            for k, v in saved.items():
                if k in ('_v', 'difficulty'):
                    continue
                setattr(self, k, v)
            self.difficulty = diff
            # Every value difficulty actually controls has to be re-derived
            # from the picker's choice, not restored verbatim from the save
            # (shooter-12's second half): otherwise the label says one
            # difficulty while the AI plays another.
            self.ai_speed = {'easy': 0.24, 'medium': 0.45, 'hard': 0.68}[diff]
            self.ai_error = {'easy': 3.0, 'medium': 1.5, 'hard': 0.5}[diff]
            self.ai_react = {'easy': 20, 'medium': 10, 'hard': 5}[diff]
            self.net = None
            self.role = 'host'
            # The field is a fixed 60x20 regardless of mode (see NET_FIELD_W/
            # H above); the fresh-start path below sets min_w/min_h to match,
            # but this resume path used to fall through without it, leaving
            # the class defaults (40x18) in place. That let the too-small
            # gate admit e.g. a 45x19 terminal and draw the 60-wide field
            # clipped, the right paddle and a third of the playfield
            # off-screen.
            self.min_w, self.min_h = self.NET_FIELD_W, self.NET_FIELD_H
            return
        diff = self.difficulty
        # AI cells/tick, tuned so the AI's real-world speed (cells/sec) stays
        # roughly 15 / 28 / 42 across easy/medium/hard at the 16 ms tick.
        self.ai_speed = {'easy': 0.24, 'medium': 0.45, 'hard': 0.68}[diff]
        self.ai_error = {'easy': 3.0, 'medium': 1.5, 'hard': 0.5}[diff]
        # Reaction latency in ticks, scaled up from the old 40 ms tick so the
        # real-world reaction delay (ticks * tick_ms) is unchanged.
        self.ai_react = {'easy': 20, 'medium': 10, 'hard': 5}[diff]
        self.player_speed = 0.48  # cells/tick, roughly 30 cells/sec
        # Field is fixed regardless of mode, so gate on it always.
        self.min_w, self.min_h = self.NET_FIELD_W, self.NET_FIELD_H
        pw, ph = self._pw(), self._ph()
        self.player_y = float(ph // 2 - self.PADDLE_H // 2)
        self.ai_y = float(ph // 2 - self.PADDLE_H // 2)
        self.ai_target = float(ph // 2)
        self.player_score = 0
        self.ai_score = 0
        self.score = 0
        self.ball_x = float(pw // 2)
        self.ball_y = float(ph // 2)
        self.ball_dx = 0.0
        self.ball_dy = 0.0
        self.serving = True
        self.server = 'player'
        self.rally = 0

    def get_timeout(self):
        return 16

    def net_pump(self):
        # PongGame never overrode this (it inherited the base class's no-op),
        # so the socket was only ever touched from inside update(), which
        # help/pause/resize/the too-small gate all stop from running. Opening
        # `?`, resizing, or shrinking below the 60x20 field used to freeze
        # the match for both players (NET-2), and once net.py grew its
        # heartbeat/timeout (NET-3) that freeze escalated into an outright
        # "Opponent disconnected" after 8s of silence.
        if not self.net:
            return
        if not self.net.alive:
            self.game_over = True
            self.message = 'Opponent disconnected'
            return
        self.net.pump()

    def get_controls(self):
        return [('W/S', 'Move paddle'), ('Space', 'Serve'),
                ('P', 'Pause'), ('ESC', 'Quit')]

    def get_stats(self):
        stats = [('You', self.player_score), ('AI', self.ai_score)]
        # Surface the reason the match ended (e.g. a net disconnect) in the
        # game-over banner instead of leaving a bare "GAME OVER" that reads
        # as an ordinary loss (matches Reversi/Connect Four, which already
        # show self.message).
        if self.game_over and getattr(self, 'message', ''):
            stats.append(('Note', self.message))
        return stats

    def get_save_data(self):
        if self.net:
            return None  # never resume a network game
        return {
            '_v': self._SAVE_VERSION,
            'difficulty': self.difficulty,
            'ai_speed': self.ai_speed, 'ai_error': self.ai_error,
            'ai_react': self.ai_react, 'player_speed': self.player_speed,
            'player_y': self.player_y, 'ai_y': self.ai_y,
            'ai_target': self.ai_target,
            'player_score': self.player_score, 'ai_score': self.ai_score,
            'score': self.score,
            'ball_x': self.ball_x, 'ball_y': self.ball_y,
            'ball_dx': self.ball_dx, 'ball_dy': self.ball_dy,
            'serving': self.serving, 'server': self.server,
            'rally': self.rally,
        }

    def _serve(self):
        self.ball_x = float(self._pw() // 2)
        self.ball_y = float(self._ph() // 2)
        # Serve TOWARD the side that just missed (pong-5), retaining the
        # vertical direction the ball had at the moment it went out instead
        # of a coin flip. Only the very first serve of a match (no prior
        # miss, dy still 0) has nothing to retain, so that one is random.
        if self.ball_dy > 0:
            dy_sign = 1.0
        elif self.ball_dy < 0:
            dy_sign = -1.0
        else:
            dy_sign = random.choice([-1.0, 1.0])
        dx_sign = -1.0 if self.server == 'player' else 1.0
        angle = math.radians(20) * dy_sign
        speed = self.SPEED_LEVELS[0]
        self.ball_dx = dx_sign * speed * math.cos(angle)
        self.ball_dy = speed * math.sin(angle)
        self.serving = False
        self.rally = 0

    def handle_input(self, key):
        # Serve is the only discrete, edge-triggered action here; paddle
        # movement is continuous and lives in update() (see below).
        if key != ord(' ') or not self.serving:
            return
        if self.net and self.role == 'guest':
            # The guest can't call _serve() itself (the host owns physics);
            # it asks the host to serve, and only when it is the guest's
            # turn (NET-6: the guest could never serve before this).
            if self.server == 'ai':
                self.net.send({'type': 'serve'})
            return
        if self.net and self.role == 'host':
            if self.server == 'player':
                self._serve()
            return
        self._serve()

    def _state(self):
        return {'type': 's', 'bx': self.ball_x, 'by': self.ball_y,
                'py': self.player_y, 'ay': self.ai_y,
                'psc': self.player_score, 'asc': self.ai_score,
                'sv': self.serving, 'srv': self.server, 'go': self.game_over}

    @staticmethod
    def _num(v, default):
        # Accept only finite numbers from the peer (reject NaN / Infinity / junk).
        return v if isinstance(v, (int, float)) and v == v \
            and -1e6 < v < 1e6 else default

    def _apply_state(self, m):
        pw, ph = self._pw(), self._ph()
        self.ball_x = max(0.0, min(pw - 1.0, self._num(m.get('bx'), self.ball_x)))
        self.ball_y = max(0.0, min(ph - 1.0, self._num(m.get('by'), self.ball_y)))
        self.player_y = max(2.0, min(float(ph - self.PADDLE_H - 2),
                                     self._num(m.get('py'), self.player_y)))
        self.player_score = int(self._num(m.get('psc'), self.player_score))
        self.ai_score = int(self._num(m.get('asc'), self.ai_score))
        self.serving = bool(m.get('sv', self.serving))
        if m.get('srv') in ('player', 'ai'):
            self.server = m.get('srv')
        self.score = self.ai_score  # guest is the right paddle; show its score
        # guest keeps its own ai_y (responsive); the host trusts what it receives
        if (m.get('go') or self.player_score >= self.WIN_SCORE
                or self.ai_score >= self.WIN_SCORE):
            self.game_over = True
            self.won = self.ai_score >= self.WIN_SCORE  # guest is the right paddle

    def _deflect(self, paddle_y):
        hit_frac = (self.ball_y - paddle_y) / self.PADDLE_H
        hit_frac = max(0.0, min(0.999, hit_frac))
        zone = int(hit_frac * 8)
        return math.radians(self.ZONE_ANGLES_DEG[zone])

    def _speed_for_rally(self):
        if self.rally >= self.RALLY_THRESHOLDS[1]:
            return self.SPEED_LEVELS[2]
        if self.rally >= self.RALLY_THRESHOLDS[0]:
            return self.SPEED_LEVELS[1]
        return self.SPEED_LEVELS[0]

    def update(self):
        if self.net and not self.net.alive:
            self.game_over = True
            self.message = 'Opponent disconnected'
            return
        ph = self._ph()
        top = ph - self.PADDLE_H - 2

        if self.net and self.role == 'guest':
            # Guest paddle moves locally every tick for responsiveness, then
            # is sent to the host, which is authoritative for the match.
            if self.held(ord('w'), curses.KEY_UP):
                self.ai_y = max(2.0, self.ai_y - self.player_speed)
            elif self.held(ord('s'), curses.KEY_DOWN):
                self.ai_y = min(float(top), self.ai_y + self.player_speed)
            self.net.send({'type': 'p', 'y': self.ai_y})
            # NET-8 root cause: this used to be a blind `while poll() is not
            # None` loop, which pulls EVERY queued message off the front of
            # the inbox and silently discards anything that isn't 's' --
            # including the peer's reliable '_rematch' frame if it arrives
            # (e.g. queued behind a final 's' while this side sat on the
            # help overlay) before update() next runs. poll_type() only
            # ever removes 's' frames, leaving anything else (already acked
            # on receipt, so never resent) sitting in the inbox for
            # _net_await_rematch to read after this game loop returns.
            latest = None
            m = self.net.poll_type(('s',))
            while m is not None:
                latest = m
                m = self.net.poll_type(('s',))
            if latest:
                self._apply_state(latest)
            return

        pw = self._pw()
        if self.net and self.role == 'host':
            m = self.net.poll_type(('p', 'serve'))
            while m is not None:
                if m.get('type') == 'p':
                    y = self._num(m.get('y'), None)
                    if y is not None:
                        self.ai_y = max(2.0, min(float(top), float(y)))
                elif m.get('type') == 'serve':
                    if self.serving and self.server == 'ai':
                        self._serve()
                m = self.net.poll_type(('p', 'serve'))

        # Continuous paddle movement (host or solo left paddle). Moving here
        # instead of handle_input() decouples paddle speed from OS key
        # auto-repeat (the paddle-moves-on-key-event bug).
        if self.held(ord('w'), curses.KEY_UP):
            self.player_y = max(2.0, self.player_y - self.player_speed)
        elif self.held(ord('s'), curses.KEY_DOWN):
            self.player_y = min(float(top), self.player_y + self.player_speed)

        if self.serving:
            if self.net and self.role == 'host':
                self.net.send(self._state())
            return

        self.ball_x += self.ball_dx
        self.ball_y += self.ball_dy

        # Wall bounce (top/bottom)
        if self.ball_y <= 2:
            self.ball_y = 2.0
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= ph - 3:
            self.ball_y = float(ph - 3)
            self.ball_dy = -abs(self.ball_dy)

        # Player paddle (left, x=4). Collision spans exactly the drawn cells.
        py = int(round(self.player_y))
        if (self.ball_dx < 0 and 3 <= int(self.ball_x) <= 5 and
                py <= int(self.ball_y) <= py + self.PADDLE_H - 1):
            self.rally += 1
            angle = self._deflect(py)
            speed = self._speed_for_rally()
            self.ball_dx = speed * math.cos(angle)
            self.ball_dy = speed * math.sin(angle)

        # Right paddle (x = pw-5)
        ai_x = pw - 5
        ay = int(round(self.ai_y))
        if (self.ball_dx > 0 and ai_x - 1 <= int(self.ball_x) <= ai_x + 1 and
                ay <= int(self.ball_y) <= ay + self.PADDLE_H - 1):
            self.rally += 1
            angle = self._deflect(ay)
            speed = self._speed_for_rally()
            self.ball_dx = -speed * math.cos(angle)
            self.ball_dy = speed * math.sin(angle)

        # Scoring
        if self.ball_x <= 1:
            self.ai_score += 1
            self.server = 'player'  # ball is served back toward whoever missed
            self.serving = True
            self._check_win()
        elif self.ball_x >= pw - 2:
            self.player_score += 1
            self.score = self.player_score
            self.server = 'ai'
            self.serving = True
            self._check_win()

        # The right paddle is the AI (solo) or the guest (network).
        if not self.net:
            # AI target prediction
            if self.ticks % self.ai_react == 0:
                if self.ball_dx > 0:
                    dist = max(1.0, ai_x - self.ball_x)
                    pred_y = self.ball_y + self.ball_dy * (dist / max(0.1, abs(self.ball_dx)))
                    pred_y += random.uniform(-self.ai_error, self.ai_error)
                    self.ai_target = max(2.0, min(float(ph - 3), pred_y))
                else:
                    self.ai_target = float(ph // 2)
            # AI movement
            ai_center = self.ai_y + self.PADDLE_H / 2.0
            if ai_center < self.ai_target - 0.5:
                self.ai_y = min(float(top), self.ai_y + self.ai_speed)
            elif ai_center > self.ai_target + 0.5:
                self.ai_y = max(2.0, self.ai_y - self.ai_speed)

        if self.net and self.role == 'host':
            self.net.send(self._state())

    def _check_win(self):
        if self.player_score >= self.WIN_SCORE:
            self.won = True
            self.game_over = True
        elif self.ai_score >= self.WIN_SCORE:
            self.game_over = True

    def draw(self):
        oy, ox = self._origin()   # centers the fixed field in the live terminal
        pw, ph = self._pw(), self._ph()

        def field_center(y, text, attr):
            self.safe_addstr(oy + y, ox + max(0, (pw - len(text)) // 2), text, attr)

        self.safe_addstr(oy, ox + 2, 'PONG', curses.A_BOLD)

        # Scores + side labels
        score_s = f'{self.player_score}    {self.ai_score}'
        sc_x = ox + max(0, (pw - len(score_s)) // 2)
        self.safe_addstr(oy + 1, sc_x, score_s, curses.A_BOLD)
        if not self.net:
            left_lab, right_lab = 'YOU', 'CPU'
        elif self.role == 'host':
            left_lab, right_lab = 'YOU', 'OPP'
        else:
            left_lab, right_lab = 'OPP', 'YOU'
        self.safe_addstr(oy + 1, max(ox, sc_x - len(left_lab) - 1), left_lab,
                         curses.color_pair(1))
        self.safe_addstr(oy + 1, sc_x + len(score_s) + 1, right_lab,
                         curses.color_pair(2))

        # Top/bottom walls, drawn exactly on the rows the physics bounces
        # off (update()'s wall-bounce clamps ball_y to 2 on top and ph-3 on
        # bottom). These used to not be drawn at all, so the field boundary
        # was invisible and the ball appeared to bounce off nothing.
        top_wall_y = 2
        bottom_wall_y = ph - 3
        wall = '-' * pw
        self.safe_addstr(oy + top_wall_y, ox, wall, curses.color_pair(4))
        self.safe_addstr(oy + bottom_wall_y, ox, wall, curses.color_pair(4))

        # Center net: spans exactly the real playfield (top_wall_y to
        # bottom_wall_y inclusive), the same rows the ball can occupy. This
        # used to run one row past bottom_wall_y, which made the net's
        # bottom edge actively misleading about where the ball bounces.
        mid_x = ox + pw // 2
        for y in range(top_wall_y, bottom_wall_y + 1):
            if y % 2 == 0:
                self.safe_addstr(oy + y, mid_x, ':', curses.color_pair(4))

        # Paddles
        py, ay = int(round(self.player_y)), int(round(self.ai_y))
        for i in range(self.PADDLE_H):
            self.safe_addstr(oy + py + i, ox + 4, '|',
                             curses.color_pair(1) | curses.A_BOLD)
            self.safe_addstr(oy + ay + i, ox + pw - 5, '|',
                             curses.color_pair(2) | curses.A_BOLD)

        # Ball / serve prompt
        if not self.serving:
            self.safe_addstr(oy + int(self.ball_y), ox + int(self.ball_x), 'O',
                             curses.color_pair(3) | curses.A_BOLD)
        elif self.net and self.role == 'guest':
            if self.server == 'ai':
                field_center(ph // 2, ' Press SPACE to serve ',
                             curses.color_pair(4) | curses.A_REVERSE)
            else:
                field_center(ph // 2, ' Waiting for host to serve ',
                             curses.color_pair(4) | curses.A_REVERSE)
        elif self.net and self.role == 'host' and self.server != 'player':
            field_center(ph // 2, ' Waiting for opponent to serve ',
                         curses.color_pair(4) | curses.A_REVERSE)
        else:
            field_center(ph // 2, ' Press SPACE to serve ',
                         curses.color_pair(4) | curses.A_REVERSE)

        # List form (not a plain string): at Pong's own min_w=40 the plain
        # string clipped character-wise mid-word ("...ESC:Qu") and lost
        # "?:Help" entirely (INFRA-7). The list form drops whole segments
        # instead, keeping the escape hatches.
        self.draw_status_bar(['W/S:Move', 'Space:Serve', 'P:Pause',
                               'ESC:Quit', '?:Help'])
