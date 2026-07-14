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

    # Deflection angle range, in degrees, mapped continuously across where
    # the ball hits the paddle (dead center -> MIN_DEFLECT_DEG, either tip
    # -> MAX_DEFLECT_DEG). This replaces an earlier 8-zone quantization
    # whose two center zones were BOTH mapped to a flat (0 deg) return:
    # any paddle that tracks the ball (the AI, or a competent player)
    # naturally centers on it, so most real hits landed in that double-
    # wide flat zone, and once one flat return happened the next contact
    # landed back in it too -- a self-reinforcing near-flat rally that
    # took a small random jitter (2-6 deg) to even nudge, and routinely
    # ran 100+ hits and 30-300+ SECONDS per point between two players who
    # were both just doing their job (correctness re-audit finding: median
    # point 17-47s, 39% of points over 30s, one point ran 322s). A
    # continuous mapping with a real minimum angle means there is no flat
    # return left to converge on: EVERY hit sends the ball back at a
    # clearly non-trivial angle, so a rally only continues as long as both
    # sides keep successfully reading real deflection, not as a side
    # effect of both paddles converging on the field's physical center.
    MIN_DEFLECT_DEG = 20
    MAX_DEFLECT_DEG = 60

    # Player paddle cap, cells/tick (roughly 30 cells/sec at the 16ms tick).
    # This is also the ceiling every AI_SPEED entry below must stay under:
    # the AI's continuous per-tick move is not gated by held()/autorepeat
    # the way the player's is, so if ai_speed >= PLAYER_SPEED the AI can
    # physically out-run any human paddle regardless of how well the human
    # reads the ball -- an unwinnable match, not just a hard one (final
    # correctness audit finding #1). 'hard' used to be 0.68 (~42 c/s),
    # comfortably faster than the player's fixed 30 c/s pace, which made
    # hard mode unbeatable on paddle speed alone. Difficulty now comes only
    # from prediction noise (AI_ERROR) and reaction latency (AI_REACT); all
    # three AI_SPEED entries stay strictly below PLAYER_SPEED so a human
    # paddle moving at its own achievable rate can always keep pace.
    #
    # PLAYER_SPEED must also clear the ball's own vertical speed, which the
    # earlier value did not. The ball tops out at SPEED_LEVELS[2] = 0.85
    # c/t, and MAX_DEFLECT_DEG = 60, so its peak vertical component is
    # 0.85 * sin(60) = 0.736 c/t (about 46 rows/sec). At the old
    # PLAYER_SPEED of 0.48 (30 rows/sec) the ball climbed and fell 1.5x
    # faster than any paddle could follow, so a player who READS the ball
    # and chases it could never arrive in time: a reactive bot lost 11/12
    # on easy and 12/12 on medium and hard, while a bot that PREDICTED the
    # arrival row won 12/12 on every difficulty. That is not a difficulty
    # curve, it is a cliff between "impossible" and "trivial" with no skill
    # gradient in between. 0.85 c/t (about 53 rows/sec) clears the ball's
    # 0.736 with real margin, so tracking the ball is a viable way to play
    # and prediction is a refinement rather than the only option.
    PLAYER_SPEED = 0.85
    AI_SPEED = {'easy': 0.42, 'medium': 0.62, 'hard': 0.78}
    # AI_ERROR is a uniform +-row offset applied to the AI's ONE committed
    # prediction per approach (see the one-shot-commit comment in update()).
    # The paddle is PADDLE_H=5 rows tall, so a prediction within 2.5 rows of
    # the true arrival row still connects -- these values used to be 3.0 /
    # 1.5 / 0.5, all comfortably UNDER that 2.5-row miss threshold except a
    # fraction of easy's, so medium and hard mathematically could not miss
    # (measured 100% catch rate against a wide spread of angles/speeds) no
    # matter how the rest of the match played out (final correctness
    # re-audit finding: the AI could not win a single point from a
    # competent player on any difficulty). Retuned so each difficulty has a
    # real, escalating chance to actually miss (measured catch rate against
    # a spread of random incoming shots: ~72% easy, ~92% medium, ~98% hard).
    AI_ERROR = {'easy': 6.0, 'medium': 3.5, 'hard': 2.7}
    # Reaction latency in ticks, scaled up from the old 40 ms tick so the
    # real-world reaction delay (ticks * tick_ms) is unchanged.
    AI_REACT = {'easy': 20, 'medium': 10, 'hard': 5}

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

    def _wall_rows(self):
        # Single source of truth for the rows the top/bottom walls are
        # drawn on, shared by draw() (what gets painted) and update() (what
        # the ball bounces off). Previously update() clamped ball_y to
        # these exact rows on a bounce, so at the instant of a bounce the
        # ball glyph was drawn on the same cell as the wall dash, erasing
        # part of the wall it was supposedly bouncing off (final
        # correctness audit finding #3). Callers that need where the ball
        # is allowed to rest must use the interior cell just past these
        # (wall + 1 / wall - 1), never the wall row itself.
        ph = self._ph()
        return 2, ph - 3

    def setup(self):
        # In a network game the host owns physics (left paddle); the guest sends
        # its paddle (right) and renders the host's authoritative state.
        self.net = getattr(self, 'net', None)
        self.role = getattr(self, 'role', 'host')
        # AI reaction-commit bookkeeping (see the AI target prediction block
        # in update()): transient per-approach state, not meaningful to
        # persist across a save, so it is (re)initialized here unconditionally
        # rather than through the save/restore path.
        self._ai_locked = False
        self._ai_approach_ticks = 0
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
            self.ai_speed = self.AI_SPEED[diff]
            self.ai_error = self.AI_ERROR[diff]
            self.ai_react = self.AI_REACT[diff]
            self.player_speed = self.PLAYER_SPEED
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
        self.ai_speed = self.AI_SPEED[diff]
        self.ai_error = self.AI_ERROR[diff]
        self.ai_react = self.AI_REACT[diff]
        self.player_speed = self.PLAYER_SPEED
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
        # Continuous deflection: how far from paddle-center the ball hit
        # sets the SIGN (top half sends it up, bottom half sends it down),
        # and how far from center sets the MAGNITUDE, scaled linearly from
        # MIN_DEFLECT_DEG (a near-center hit) to MAX_DEFLECT_DEG (a hit
        # right at either tip). There is no hit position that returns the
        # ball flat -- see the MIN_DEFLECT_DEG comment above for why that
        # matters (the old flat zone was the actual cause of the grind).
        offset = hit_frac - 0.5  # -0.5 (top) .. +0.5 (bottom)
        if offset > 0:
            sign = 1.0
        elif offset < 0:
            sign = -1.0
        else:
            # Exact dead center: no side to bias from, pick one at random
            # rather than always breaking the same way.
            sign = 1.0 if random.random() < 0.5 else -1.0
        magnitude = self.MIN_DEFLECT_DEG + abs(offset) * 2 * (
            self.MAX_DEFLECT_DEG - self.MIN_DEFLECT_DEG)
        return math.radians(sign * magnitude)

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
            d = self.steer_dir((ord('w'), curses.KEY_UP), (ord('s'), curses.KEY_DOWN))
            if d < 0:
                self.ai_y = max(2.0, self.ai_y - self.player_speed)
            elif d > 0:
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
        # auto-repeat (the paddle-moves-on-key-event bug). held() (default
        # latch_ms, i.e. the core's 180ms continuous-motion latch), not the
        # raw event-only edge: at this game's 16ms tick, an unlatched check
        # only saw a key on 34-45% of ticks under realistic OS autorepeat
        # (the event rate is slower than the tick rate), so the paddle
        # crawled at 10-14 c/s instead of its intended ~30 c/s while the AI
        # paddle, which moves unconditionally every tick, did not share
        # that penalty (final correctness audit finding #1, part 1).
        d = self.steer_dir((ord('w'), curses.KEY_UP), (ord('s'), curses.KEY_DOWN))
        if d < 0:
            self.player_y = max(2.0, self.player_y - self.player_speed)
        elif d > 0:
            self.player_y = min(float(top), self.player_y + self.player_speed)

        if self.serving:
            if self.net and self.role == 'host':
                self.net.send(self._state())
            return

        self.ball_x += self.ball_dx
        self.ball_y += self.ball_dy

        # Wall bounce (top/bottom). Clamp to one cell INSIDE the wall
        # (top_wall_y+1 / bottom_wall_y-1), never onto the wall row itself:
        # the wall is drawn on top_wall_y/bottom_wall_y (see draw()), so
        # resting the ball there would paint the ball glyph directly over
        # the wall dash on every bounce frame, erasing it (final
        # correctness audit finding #3). Resting one cell inside instead
        # still reads as "bounced off the wall surface" while never
        # touching the pixel the wall owns.
        top_wall_y, bottom_wall_y = self._wall_rows()
        if self.ball_y <= top_wall_y + 1:
            self.ball_y = float(top_wall_y + 1)
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= bottom_wall_y - 1:
            self.ball_y = float(bottom_wall_y - 1)
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
            # AI target prediction. Commits to exactly ONE noisy prediction
            # per approach (ai_react ticks after the ball turns toward the
            # AI), then holds it for the rest of that approach, instead of
            # redrawing a fresh random error every ai_react ticks for as
            # long as the ball keeps coming. Continuous resampling was
            # measured to make AI_ERROR nearly irrelevant: the paddle only
            # moves toward the CURRENT target at ai_speed, so a fast stream
            # of independent, zero-mean-noise targets acts as a low-pass
            # filter on the paddle's own path -- it settles near the TRUE
            # mean position by the time the ball arrives regardless of how
            # large AI_ERROR is (measured: 100% catch rate at every
            # difficulty even with AI_ERROR pushed to 3-8x its tuned
            # values). A single committed guess is what actually makes a
            # missed read possible, which is what AI_ERROR was always
            # supposed to control (final correctness re-audit finding: the
            # AI could not lose a single point to a competent player on any
            # difficulty).
            if self.ball_dx > 0:
                self._ai_approach_ticks += 1
                if not self._ai_locked and self._ai_approach_ticks >= self.ai_react:
                    dist = max(1.0, ai_x - self.ball_x)
                    pred_y = self.ball_y + self.ball_dy * (dist / max(0.1, abs(self.ball_dx)))
                    # Reflect the straight-line projection off the top/
                    # bottom walls instead of just clamping it into range.
                    # A plain clamp collapses every prediction that would
                    # cross a wall before reaching the paddle onto the
                    # wall itself, which is only ever correct if the ball
                    # happens to arrive exactly there -- for any other
                    # case it is simply the wrong row, so the AI moved to
                    # (and sat at) a point the ball was never going to
                    # reach, missing returns a player using the same
                    # linear-projection instinct would make. Folding the
                    # projection back and forth across the legal travel
                    # band (a triangle wave) matches the ball's real
                    # bounce physics, so the AI's skill genuinely comes
                    # from AI_ERROR/AI_REACT (as intended) instead of
                    # being artificially capped by a naive, bounce-blind
                    # prediction on top of them.
                    top_wall, bottom_wall = self._wall_rows()
                    lo, hi = float(top_wall + 1), float(bottom_wall - 1)
                    span = hi - lo
                    if span > 0:
                        period = 2 * span
                        folded = (pred_y - lo) % period
                        if folded > span:
                            folded = period - folded
                        pred_y = lo + folded
                    pred_y += random.uniform(-self.ai_error, self.ai_error)
                    self.ai_target = max(2.0, min(float(ph - 3), pred_y))
                    self._ai_locked = True
                # else: still reacting (not yet ai_react ticks into this
                # approach) or already locked -- ai_target holds steady.
            else:
                self._ai_locked = False
                self._ai_approach_ticks = 0
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

        # Top/bottom walls. update()'s wall-bounce now rests the ball one
        # cell inside these rows (see _wall_rows()), never on them, so the
        # ball glyph can never overwrite a wall dash. These used to not be
        # drawn at all, so the field boundary was invisible and the ball
        # appeared to bounce off nothing.
        top_wall_y, bottom_wall_y = self._wall_rows()
        wall = '-' * pw
        self.safe_addstr(oy + top_wall_y, ox, wall, curses.color_pair(4))
        self.safe_addstr(oy + bottom_wall_y, ox, wall, curses.color_pair(4))

        # Center net: spans exactly the real playfield (top_wall_y to
        # bottom_wall_y inclusive), the same rows the ball can occupy. This
        # used to run one row past bottom_wall_y, which made the net's
        # bottom edge actively misleading about where the ball bounces.
        # Strictly BETWEEN the two walls (never on top_wall_y or
        # bottom_wall_y themselves) and phased off top_wall_y rather than
        # off row 0, so the dotted pattern starts right after the top wall
        # and stops right before the bottom wall instead of drawing over
        # the top wall (old: phase was against absolute row parity, and
        # top_wall_y=2 is even, so it collided with the top wall but the
        # inclusive range also ran one row further than the bottom wall
        # needed, making the two walls look different).
        mid_x = ox + pw // 2
        for y in range(top_wall_y + 1, bottom_wall_y):
            if (y - top_wall_y) % 2 == 0:
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
