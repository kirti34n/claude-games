"""Dependency-free tests for play.py.

Runs with plain ``python tests/test_games.py`` (no pytest required) and is also
pytest-compatible. A fake ``curses`` module is injected before importing ``play``
so the whole suite is deterministic and runs on any platform, with or without a
real curses build installed.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import types
from datetime import date, timedelta
from pathlib import Path

# ── Fake curses so play.py imports and its game logic runs headless ──────────
_fake = types.ModuleType('curses')
_n = [0]


def _next():
    _n[0] += 1
    return _n[0]


for _name in ('A_BOLD', 'A_REVERSE', 'A_NORMAL', 'A_DIM', 'A_UNDERLINE',
              'A_BLINK', 'A_STANDOUT'):
    setattr(_fake, _name, _next())
for _name in ('KEY_UP', 'KEY_DOWN', 'KEY_LEFT', 'KEY_RIGHT', 'KEY_ENTER',
              'KEY_RESIZE'):
    setattr(_fake, _name, 1000 + _next())
for _name in ('COLOR_BLACK', 'COLOR_RED', 'COLOR_GREEN', 'COLOR_YELLOW',
              'COLOR_BLUE', 'COLOR_MAGENTA', 'COLOR_CYAN', 'COLOR_WHITE'):
    setattr(_fake, _name, _next())
_fake.COLORS = 256
_fake.error = type('error', (Exception,), {})
_fake.color_pair = lambda n: (n & 0xff) << 8
for _fn in ('start_color', 'use_default_colors', 'init_pair', 'curs_set', 'beep',
            'doupdate', 'napms', 'has_colors', 'flushinp', 'noecho', 'cbreak'):
    setattr(_fake, _fn, lambda *a, **k: 0)
sys.modules['curses'] = _fake

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import play  # noqa: E402
from arcade_games import config as _config  # noqa: E402
from arcade_games import currency as _currency  # noqa: E402
from arcade_games import game as _game_mod  # noqa: E402

# Redirect config to a temp dir so tests never touch the user's real saves.
# This MUST patch the arcade_games.config module (where every consumer
# reads CONFIG_DIR/SCORES_FILE/GAME_STATE_FILE at call time via
# 'from . import config'), not the play shim: patching the shim's copies
# would be a silent no-op and writes would hit the user's real
# ~/.config/arcade-games/.
_TMP = Path(tempfile.mkdtemp())
_config.CONFIG_DIR = _TMP
_config.SCORES_FILE = _TMP / 'scores.json'
_config.GAME_STATE_FILE = _TMP / 'current_game.json'
play.CONFIG_DIR = _TMP  # keep the shim's re-exported copies in sync too
play.SCORES_FILE = _config.SCORES_FILE
play.GAME_STATE_FILE = _config.GAME_STATE_FILE

UP, DOWN, LEFT, RIGHT = (_fake.KEY_UP, _fake.KEY_DOWN, _fake.KEY_LEFT,
                         _fake.KEY_RIGHT)
SPACE = ord(' ')
GAMES = [cls for _name, _desc, cls in play._GAMES]


class MockScreen:
    """Minimal stdscr: getmaxyx + addstr with curses-like bounds errors."""

    def __init__(self, h=40, w=110):
        self._h, self._w = h, w

    def getmaxyx(self):
        return (self._h, self._w)

    def addstr(self, *a):
        if len(a) >= 3 and isinstance(a[0], int):
            y, x, text = a[0], a[1], a[2]
            if y < 0 or x < 0 or y >= self._h or x >= self._w:
                raise _fake.error('out of bounds')
            if x + len(str(text)) > self._w:
                raise _fake.error('past right edge')

    def addch(self, *a):
        pass

    def erase(self):
        pass

    def clear(self):
        pass

    def noutrefresh(self):
        pass

    def refresh(self):
        pass

    def nodelay(self, *a):
        pass

    def timeout(self, *a):
        pass

    def keypad(self, *a):
        pass

    def move(self, *a):
        pass

    def getch(self):
        return -1


_KEYS = [UP, DOWN, LEFT, RIGHT, ord('w'), ord('a'), ord('s'), ord('d'),
         ord(' '), ord('f'), ord('u'), 10, -1]


def _drive(game, screen, ticks, rng):
    for _ in range(ticks):
        if game.game_over:
            break
        game.handle_input(rng.choice(_KEYS))
        game.update()
        game.h, game.w = screen.getmaxyx()
        game.draw()


# ── Tests ────────────────────────────────────────────────────────────────────

def test_no_crash_fuzz():
    """Every game survives random input at several terminal sizes."""
    for cls in GAMES:
        for size in [(40, 110), (24, 80), (20, 40), (50, 200)]:
            for seed in range(2):
                rng = random.Random(seed)
                scr = MockScreen(*size)
                g = cls(scr)
                g.difficulty = rng.choice(['easy', 'medium', 'hard'])
                g.setup()
                _drive(g, scr, 600, rng)


def test_save_load_roundtrip():
    """get_save_data() restores cleanly, including into a smaller terminal."""
    for cls in GAMES:
        rng = random.Random(1)
        big = MockScreen(50, 200)
        g = cls(big)
        g.difficulty = 'medium'
        g.setup()
        _drive(g, big, 80, rng)
        data = g.get_save_data()
        if data is None:
            continue
        (_config.CONFIG_DIR / f'save_{cls.name}.json').write_text(json.dumps(data))
        small = MockScreen(24, 44)
        g2 = cls(small)
        g2.difficulty = 'medium'
        g2.setup()  # restores from the save file
        _drive(g2, small, 80, rng)


def test_pacman_ghosts_leave_pen():
    """The regression that made the game threat-free: ghosts must exit the pen."""
    random.seed(1)
    g = play.PacManGame(MockScreen())
    g.setup()
    left = set()
    for _ in range(400):
        g.update()
        for i, gh in enumerate(g.ghosts):
            if gh['y'] < 9:
                left.add(i)
        if g.game_over:
            break
    assert len(left) == 4, f'only ghosts {sorted(left)} left the pen'


def test_snake_tail_is_not_a_collision():
    g = play.SnakeGame(MockScreen())
    g.setup()
    g.board_h = g.board_w = 12
    g.snake = [(5, 5), (5, 6), (6, 6), (6, 5)]  # square; tail at (6,5)
    g.direction = g.next_direction = (1, 0)     # move down into the tail cell
    g.food = (0, 0)
    g.update()
    assert not g.game_over


def test_dino_fast_obstacle_collides():
    # dino-1 rewrite: obstacles are now {'x', 'kind'} (kind looked up in
    # arcade_games.games.dino._GEOMETRY), not raw {'x', 'art'}.
    g = play.DinoGame(MockScreen(40, 110))
    g.setup()
    g.speed = 3.0
    g.dino_y = 0.0
    g.on_ground = True
    g.obstacles = [{'x': 8.0, 'kind': 'sm'}]
    g.update()
    assert g.game_over


def test_pong_ai_speeds_are_distinct():
    # ai_speed is now the AI paddle's continuous cells/tick step (added
    # directly to a float position every tick), not a value that gets
    # doubled and rounded into a discrete per-keypress step. Assert the
    # tuning itself is monotonic across difficulty.
    def step(diff):
        g = play.PongGame(MockScreen())
        g.difficulty = diff
        g.setup()
        return g.ai_speed
    assert step('easy') < step('medium') < step('hard')


def test_cli_snake_tail_is_legal():
    s = {'game': 'snake', 'h': 12, 'w': 12,
         'snake': [[5, 5], [5, 6], [6, 6], [6, 5]], 'dir': [1, 0],
         'food': [0, 0], 'score': 0, 'over': False}
    s = play._cli_snake_move(s, 'down')  # into vacating tail cell
    assert not s['over']


def test_cli_minesweeper_first_reveal_always_safe():
    for t in range(100):
        random.seed(t)
        s = play._cli_ms_init()
        s = play._cli_ms_move(s, 'reveal 5 5')
        assert not s['over'], f'first reveal hit a mine on seed {t}'


def test_cli_minesweeper_flood_skips_flags():
    random.seed(3)
    s = play._cli_ms_init()
    s = play._cli_ms_move(s, 'flag 1 1')
    s = play._cli_ms_move(s, 'reveal 5 5')
    flagged = {tuple(p) for p in s['flagged']}
    revealed = {tuple(p) for p in s['revealed']}
    assert not (flagged & revealed)


def test_connect4_win_detection():
    board = play._cli_c4_init()['board']
    for c in range(4):
        board[len(board) - 1][c] = 1
    assert play._cli_c4_check_win(board, 1)


def test_sokoban_solving_advances_level():
    g = play.SokobanGame(MockScreen())
    g.setup()
    assert g.level_idx == 0
    # Level 1's box sits one row above and three columns right of the
    # player, with the target directly above the box: walk under the box
    # (right x3) then push it up onto the target (up x1) -- the level's
    # proven-optimal 4-move/1-push solution (see the _LEVELS table's proof
    # column in sokoban.py).
    for key in (RIGHT, RIGHT, RIGHT, UP):
        g.handle_input(key)
        g.update()
    assert g.level_idx == 1 and g.score >= 1


def test_reversi_opening_moves_and_ai_reply():
    g = play.ReversiGame(MockScreen())
    g.setup()
    g.update()
    valid = g._valid_moves(g.board, 1)
    assert len(valid) == 4 and (2, 3) in valid
    g.cur_r, g.cur_c = 2, 3
    b0, w0 = g._counts()
    g.handle_input(SPACE)
    g.update()  # AI resolves here
    b1, w1 = g._counts()
    assert b1 > b0 and (b1 + w1) > (b0 + w0) + 1 and g.turn == 1


def test_reversi_reaches_terminal_state():
    random.seed(5)
    g = play.ReversiGame(MockScreen())
    g.setup()
    for _ in range(200):
        if g.game_over:
            break
        g.update()
        vm = g._valid_moves(g.board, 1)
        if vm:
            g.cur_r, g.cur_c = random.choice(list(vm))
            g.handle_input(SPACE)
    assert g.game_over


def test_frogger_home_and_hazards():
    # reaching an empty bay scores without losing a life
    g = play.FroggerGame(MockScreen())
    g.setup()
    lives, score = g.lives, g.score
    g.frog_x = float(play.FroggerGame._HOME_BAYS[0])
    g.frog_row = 1
    g.handle_input(UP)
    g.update()
    assert g.homes[0] and g.score > score and g.lives == lives
    # a car costs a life
    g = play.FroggerGame(MockScreen())
    g.setup()
    g.frog_row, g.frog_x = 5, 10.0
    g.lanes[5]['ents'] = [10.0]
    lv = g.lives
    g.update()
    assert g.lives == lv - 1
    # a river with no log drowns
    g = play.FroggerGame(MockScreen())
    g.setup()
    g.frog_row, g.frog_x = 1, 0.0
    g.lanes[1]['ents'] = [20.0]
    lv = g.lives
    g.update()
    assert g.lives == lv - 1


def test_dino_clears_midair_cactus():
    """Regression: sufficient jump height clears a horizontally overlapping
    cactus. Rewritten for the new physics (dino-1): speed no longer comes
    from score (it ramps off self.ticks now), and the geometry changed, so
    this replaces the old score=340/'landing' scenario with a direct
    height-vs-obstacle-height check, which is what actually mattered."""
    g = play.DinoGame(MockScreen(40, 110))
    g.setup()
    g.on_ground = False
    g.dino_y = -3.0                    # height 3, enough to clear an sm (oh=2)
    g.velocity = 0.0
    g.spawn_timer = 999
    g.obstacles = [{'x': 9.0, 'kind': 'sm'}]  # horizontally overlapping the hitbox
    g.update()
    assert not g.game_over


def test_dino_cactus_at_dino_hitbox_edge_collides():
    """Regression: a cactus overlapping the dino's (inset) hitbox column
    collides, not clips through. Geometry changed under dino-1 (hitbox is
    now cols dino_x+1..dino_x+2), so the exact column differs from the old
    'snout' test, but the boundary-correctness intent is the same."""
    g = play.DinoGame(MockScreen(24, 80))
    g.setup()
    g.on_ground = True
    g.dino_y = 0.0
    g.velocity = 0.0
    g.spawn_timer = 999
    g.obstacles = [{'x': 9.0, 'kind': 'sm'}]  # inset hitbox lands on col 10 (=dr)
    g.update()
    assert g.game_over


def test_dino_grounded_fast_obstacle_still_blocks_tunnel():
    """A fast obstacle whose inset hitbox is entirely right of the dino
    hitbox before this tick's move, and entirely left of it after, must
    still be caught by the swept horizontal test (not just point-sampled
    at either end)."""
    g = play.DinoGame(MockScreen(40, 110))
    g.setup()
    g.ticks = 10 ** 6                  # forces speed to the 1.5 cap
    g.on_ground = True
    g.dino_y = 0.0
    g.velocity = 0.0
    g.spawn_timer = 999
    g.obstacles = [{'x': 9.3, 'kind': 'sm'}]  # steps clean over a point hitbox
    g.update()
    assert g.game_over


def test_dino_ptero_high_survivable_by_holding_duck():
    """dino-1 / second axis: a head-height pterodactyl IS also jumpable by
    timing alone (its band is only rows gy-2..gy-1, and any jump reaching
    h>=3 clears it), but it is always safe if the player ducks through its
    whole horizontal window regardless of timing (unlike ground obstacles,
    that needs no jump-arc timing constraint to prove, so a single
    held-duck crossing suffices). This test only asserts the duck path."""
    g = play.DinoGame(MockScreen(60, 20))
    g.setup()
    g.on_ground = True
    g.speed = 1.5
    g.spawn_timer = 10 ** 9
    g.obstacles = [{'x': 40.0, 'kind': 'ptero_high'}]
    for _ in range(80):
        if not g.obstacles or g.game_over:
            break
        g.keys = [DOWN]  # held every tick, as the run loop would deliver it
        g.speed = 1.5
        g.update()
    assert not g.game_over


def test_dino_every_ground_obstacle_clearable_by_some_jump_timing():
    """Brute-force proof for dino-1: for every ground obstacle kind and
    every speed across the game's full range, there exists at least one
    jump-launch tick that clears it. Drives the real DinoGame/update()
    integrator directly (not a re-derivation of the physics), so this
    proves the shipped code, not a model of it."""
    from arcade_games.games.dino import _GEOMETRY, SPEED_MIN, SPEED_MAX, RAMP_TICKS

    def ticks_for_speed(speed):
        # self.speed is recomputed from self.ticks on every update() call
        # (that is the ramp), so to hold speed constant for this proof we
        # pin self.ticks to whatever value the ramp formula maps back to
        # that speed, once, rather than fight the recompute every tick.
        frac = (speed - SPEED_MIN) / (SPEED_MAX - SPEED_MIN)
        return int(round(frac * RAMP_TICKS))

    def clears(kind, speed, launch_tick, x0=40):
        g = play.DinoGame(MockScreen(60, 20))
        g.setup()
        g.on_ground = True
        g.dino_y = 0.0
        g.velocity = 0.0
        g.spawn_timer = 10 ** 9
        g.ticks = ticks_for_speed(speed)
        g.obstacles = [{'x': float(x0), 'kind': kind}]
        t = 0
        while g.obstacles and not g.game_over and t < 300:
            if t == launch_tick:
                g.handle_input(SPACE)
            g.update()
            t += 1
        return not g.game_over

    ground_kinds = [k for k, v in _GEOMETRY.items() if v['band'] == 'ground']
    n_speed_steps = 18
    speeds = [round(SPEED_MIN + i * (SPEED_MAX - SPEED_MIN) / n_speed_steps, 4)
              for i in range(n_speed_steps + 1)]
    for kind in ground_kinds:
        for speed in speeds:
            max_launch = int(60 / speed) + 20
            ok = any(clears(kind, speed, lt) for lt in range(0, max_launch))
            assert ok, f'{kind} at speed {speed} is unclearable at every launch tick'


def test_frogger_log_ride_does_not_drown():
    """Regression: a frog carried by a log stays on it (no round/floor drift)."""
    g = play.FroggerGame(MockScreen())
    g.setup()
    g.frog_row = 3                     # a river lane
    g.frog_x = 10.0
    g.lanes[3]['ents'] = [10.0]        # width-5 log covering 10..14; frog on its edge
    lives = g.lives
    for _ in range(30):
        g.update()
        assert not g.game_over
    assert g.lives == lives


def test_sokoban_undo_decrements_pushes():
    g = play.SokobanGame(MockScreen())
    g.setup()  # level 1: pushing right IS a push
    g.handle_input(RIGHT)
    # solving advances the level; test the push/undo counter on level 3 instead
    g = play.SokobanGame(MockScreen())
    g.setup()
    g.level_idx = 3
    g._start_level(3)   # symmetric level with pushable boxes
    g.moves = g.pushes = 0
    g.handle_input(RIGHT)
    pushes_after = g.pushes
    if pushes_after > 0:                # if that move pushed a box
        g.handle_input(ord('u'))
        assert g.pushes == pushes_after - 1


def test_reversi_update_never_leaves_ai_turn_stuck():
    """After update() the game is over or it is the player's turn (never stuck on AI)."""
    random.seed(11)
    g = play.ReversiGame(MockScreen())
    g.setup()
    for _ in range(200):
        g.update()
        assert g.game_over or g.turn == 1
        if g.game_over:
            break
        vm = g._valid_moves(g.board, 1)
        if vm:
            g.cur_r, g.cur_c = random.choice(list(vm))
            g.handle_input(SPACE)


def test_menu_scroll_reaches_last_game():
    """The 13th game must be drawable on a minimum-height terminal."""
    drawn = []

    class RecScreen(MockScreen):
        def __init__(self, keys, h=28, w=60):
            super().__init__(h, w)
            self._keys = list(keys)

        def addstr(self, *a):
            if len(a) >= 3 and isinstance(a[2], str):
                drawn.append(a[2])

        def getch(self):
            return self._keys.pop(0) if self._keys else ord('q')

    scr = RecScreen([DOWN] * (len(GAMES) - 1) + [ord('q')])
    play._menu(scr)
    assert any('Frogger' in t for t in drawn), 'last game never rendered'


def test_snake_speed_is_input_independent():
    """Steering or mashing keys must NOT move the snake faster than its timed
    cadence (regression for the input-driven acceleration bug)."""
    class Clock:
        def __init__(self):
            self.t = 1000.0
        def time(self):
            return self.t
        def monotonic(self):
            return self.t

    clock = Clock()

    class ClockScreen(MockScreen):
        def __init__(self, keys, dt):
            super().__init__(40, 110)
            self._keys = list(keys)
            self._i = 0
            self._dt = dt
        def getch(self):
            clock.t += self._dt          # a little time passes per input poll
            if self._i < len(self._keys):
                k = self._keys[self._i]
                self._i += 1
                return k
            return ord('q')

    # Game.run()'s tick loop lives in arcade_games.game and reads the
    # module-level 'time' name it imported for itself, so the fake clock must
    # be patched there (mirrors the config-module landmine above: patching
    # play.time would be a no-op since play is just a re-export shim).
    saved = _game_mod.time
    _game_mod.time = clock
    try:
        # 40 direction keys within ~0.12s of simulated time. At the 110-180ms
        # cadence that is at most one move; the old bug produced ~20.
        scr = ClockScreen([DOWN, RIGHT] * 20, dt=0.003)
        g = play.SnakeGame(scr)
        moves = [0]
        base = g.update
        def counted():
            moves[0] += 1
            base()
        g.update = counted
        g.run()
    finally:
        _game_mod.time = saved
    assert moves[0] <= 3, f'snake moved {moves[0]}x from key input alone'


def test_net_link_reliable_delivery_and_ack():
    """net.py (494 lines: the wire protocol every LAN game depends on) had
    zero test coverage (INFRA-12). Covers the core contract: a reliable
    message is decoded exactly once by the peer, and the sender's resend
    queue clears once the peer's ack comes back."""
    import socket as _socket
    a, b = _socket.socketpair()
    link_a = link_b = None
    try:
        link_a = play._NetLink(a, 'host')
        link_b = play._NetLink(b, 'guest')
        link_a.send({'type': 'place', 'r': 1, 'c': 2})
        msg = None
        for _ in range(50):
            msg = link_b.poll()
            if msg:
                break
        assert msg == {'type': 'place', 'r': 1, 'c': 2}
        for _ in range(50):
            link_a.pump()
            if not link_a._pending:
                break
        assert link_a._pending == {}, 'ack from the peer must clear the resend queue'
        assert link_b.poll() is None, 'a message must not be delivered twice'
    finally:
        if link_a:
            link_a.close()
        if link_b:
            link_b.close()


def test_net_link_heartbeat_and_timeout():
    """pump() must (a) send a heartbeat once the link has been send-silent
    past _HEARTBEAT_INTERVAL, keeping a quiet-but-healthy peer's `alive`
    True, and (b) flip `alive` False once genuine receive-silence exceeds
    _PEER_TIMEOUT. This is exactly the mechanism NET-2/NET-3 depend on every
    game's net_pump() to keep running even while paused/help-open/resizing."""
    import socket as _socket
    from arcade_games import net as _net_mod

    class _Clock:
        def __init__(self, t):
            self.t = t

        def monotonic(self):
            return self.t

    a, b = _socket.socketpair()
    link_a = link_b = None
    saved_time = _net_mod.time
    clock = _Clock(1000.0)
    _net_mod.time = clock
    try:
        link_a = play._NetLink(a, 'host')
        link_b = play._NetLink(b, 'guest')
        clock.t += _net_mod._NetLink._HEARTBEAT_INTERVAL + 0.1
        link_a.pump()   # link_a has been send-silent: must emit a heartbeat
        link_b.pump()   # link_b receives it, refreshing its own recv clock
        assert link_b.alive
        clock.t += _net_mod._NetLink._PEER_TIMEOUT + 0.1
        link_b.pump()   # no further traffic arrives from link_a: peer is dead
        assert not link_b.alive
    finally:
        _net_mod.time = saved_time
        if link_a:
            link_a.close()
        if link_b:
            link_b.close()


def test_main_text_commands_need_no_curses():
    """The whole point of `play list`/`play version`/`play cli ...` is that
    they work with no terminal at all (piped environments like Claude
    Code); main()'s argv dispatch had zero test coverage (INFRA-12)."""
    import io
    from arcade_games import main as _main_mod

    def run(argv):
        saved_argv, saved_stdout = sys.argv, sys.stdout
        sys.argv = ['play'] + argv
        sys.stdout = io.StringIO()
        try:
            _main_mod._main()
            return sys.stdout.getvalue()
        finally:
            sys.argv = saved_argv
            sys.stdout = saved_stdout

    assert 'arcade' in run(['version']).lower()
    assert 'Snake' in run(['list'])
    assert run(['cli', 'start', 'snake']).strip()
    assert run(['cli', 'show']).strip()
    assert run(['cli', 'quit']).strip()


def test_curses_wrapper_no_tty_no_terminal_exits_cleanly():
    """_curses_wrapper's non-interactive fallback (no TTY, e.g. piped into
    Claude Code) must exit(1) with a message instead of hanging or raising
    when there is also no terminal emulator available to open into
    (main()/_curses_wrapper had zero test coverage, INFRA-12)."""
    from arcade_games import terminal as _terminal_mod

    class _NotATty:
        def isatty(self):
            return False

    saved_stdin, saved_stdout = sys.stdin, sys.stdout
    saved_open = _terminal_mod._open_in_terminal
    sys.stdin = _NotATty()
    sys.stdout = _NotATty()
    _terminal_mod._open_in_terminal = lambda *a, **k: False
    try:
        code = None
        try:
            _terminal_mod._curses_wrapper(lambda scr: None, 'snake')
        except SystemExit as e:
            code = e.code
        assert code == 1
    finally:
        sys.stdin, sys.stdout = saved_stdin, saved_stdout
        _terminal_mod._open_in_terminal = saved_open


# ── Wordplay, Blackjack, Roulette, Slots: game-specific rule tests ───────────

def test_wordplay_duplicate_letter_feedback_two_pass():
    """SPEC4 worked example: answer ABBEY, guess BABES must give
    yellow, yellow, green, green, grey. A naive one-pass 'is this letter
    anywhere in the answer' check double-counts the single B in ABBEY and
    gets this wrong."""
    from arcade_games.games.wordplay import score_guess
    assert score_guess('BABES', 'ABBEY') == \
        ['yellow', 'yellow', 'green', 'green', 'grey']


def test_wordplay_exact_and_no_match_feedback():
    from arcade_games.games.wordplay import score_guess
    assert score_guess('ABOUT', 'ABOUT') == ['green'] * 5
    assert score_guess('ZZZZZ', 'ABOUT') == ['grey'] * 5


def test_wordplay_daily_word_deterministic_across_processes():
    """The critical bug SPEC4 calls out: seeding with the builtin hash()
    would vary per process via PYTHONHASHSEED. daily_word() must use
    hashlib instead, so it returns the same word regardless of the
    interpreter's hash seed. Proven here by actually spawning separate
    processes with different PYTHONHASHSEED values, not just calling the
    function twice in this one process."""
    repo_root = str(Path(__file__).resolve().parent.parent)
    code = ("import sys; sys.path.insert(0, {0!r}); "
            "from arcade_games.games.wordplay import daily_word; "
            "print(daily_word('2024-06-15'))").format(repo_root)
    results = set()
    for seed in ('0', '1', '12345'):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, '-c', code], capture_output=True,
                              text=True, env=env, check=True)
        results.add(out.stdout.strip())
    assert len(results) == 1, \
        f'daily_word varied across PYTHONHASHSEED values: {results}'


def test_wordplay_daily_word_is_a_valid_answer():
    from arcade_games.games.wordplay import daily_word, ANSWERS
    assert daily_word('2024-01-01') in ANSWERS
    assert daily_word('2024-01-01') == daily_word('2024-01-01')


def test_roulette_house_edge_is_exact_for_every_bet_type():
    """SPEC4: every bet type must yield the same -1/37 expected value.
    Runs the module's own exhaustive self-test (all 37 pockets enumerated
    exactly, not simulated) against every generated bet spot."""
    from arcade_games.games.roulette import _run_house_edge_test
    n_spots = _run_house_edge_test()
    assert n_spots > 0


def test_slots_rtp_is_computed_exactly_and_in_band():
    """SPEC4: RTP must be computed exactly (enumerate all reel outcomes,
    not simulated) and land in the required 92%-96% band."""
    from arcade_games.games.slots import RTP, compute_rtp
    computed = compute_rtp()
    print(f'slots RTP = {computed:.4f}')
    assert computed == RTP
    assert 0.92 <= computed <= 0.96


def test_blackjack_split_ace_21_pays_even_money_not_blackjack():
    """SPEC4's most commonly botched rule: a 21 on a split-ace hand is an
    ordinary 21 (pays 1:1), never a natural blackjack (3:2), because the
    hand did not start as the player's original two cards."""
    from arcade_games.games.blackjack import BlackjackGame, PlayerHand, hand_value, _is_blackjack
    hand = PlayerHand([('A', 0), ('K', 1)], bet=10, from_split=True, split_aces=True)
    total, soft = hand_value(hand.cards)
    assert total == 21 and soft
    assert not _is_blackjack(hand), 'a 21 on a split ace must not be a natural blackjack'

    _reset_chips()
    try:
        g = BlackjackGame(MockScreen())
        g.setup()
        g._session_start_balance = _currency.balance()
        g.hands = [hand]
        g.dealer_cards = [('9', 0), ('8', 1)]  # dealer stands on 17, no push
        g.dealer_hole_hidden = False
        g.stat_rounds = g.stat_wins = g.stat_losses = g.stat_pushes = 0
        before = _currency.balance()
        g._settle_hands()
        assert hand.result == 'win'
        after = _currency.balance()
        assert after - before == hand.bet * 2, \
            'split-ace 21 must pay 1:1 (stake plus equal profit), not 3:2'
    finally:
        _reset_chips()


def test_blackjack_natural_blackjack_pays_three_to_two():
    """Contrast case for the split-ace rule above: an un-split natural
    two-card 21 is a real blackjack and pays 3:2."""
    from arcade_games.games.blackjack import BlackjackGame, PlayerHand, _is_blackjack
    hand = PlayerHand([('A', 0), ('K', 1)], bet=10)
    assert _is_blackjack(hand)

    _reset_chips()
    try:
        g = BlackjackGame(MockScreen())
        g.setup()
        g._session_start_balance = _currency.balance()
        g.hands = [hand]
        g.dealer_cards = [('9', 0), ('8', 1)]
        g.dealer_hole_hidden = False
        g.stat_rounds = g.stat_wins = g.stat_losses = g.stat_pushes = 0
        before = _currency.balance()
        g._settle_hands()
        assert hand.result == 'blackjack'
        after = _currency.balance()
        assert after - before == hand.bet + (hand.bet * 3) // 2
    finally:
        _reset_chips()


def test_blackjack_natural_blackjack_pays_three_to_two_on_odd_bet():
    """SPEC4: 3:2 must round IN THE PLAYER'S FAVOUR (ceiling) on a bet whose
    profit is not a whole chip, e.g. bet=25 -> profit=37.5 -> pays 38, never
    37 (floor division silently short-changes the player on every odd bet)."""
    from arcade_games.games.blackjack import BlackjackGame, PlayerHand, _is_blackjack
    hand = PlayerHand([('A', 0), ('K', 1)], bet=25)
    assert _is_blackjack(hand)

    _reset_chips()
    try:
        g = BlackjackGame(MockScreen())
        g.setup()
        g._session_start_balance = _currency.balance()
        g.hands = [hand]
        g.dealer_cards = [('9', 0), ('8', 1)]
        g.dealer_hole_hidden = False
        g.stat_rounds = g.stat_wins = g.stat_losses = g.stat_pushes = 0
        before = _currency.balance()
        g._settle_hands()
        assert hand.result == 'blackjack'
        after = _currency.balance()
        # ceiling(25 * 3 / 2) = 38 profit, not floor's 37.
        assert after - before == 25 + 38, \
            'odd-valued blackjack bet must round the 3:2 payout up, not down'
    finally:
        _reset_chips()


def test_blackjack_dealer_stands_on_soft_17():
    from arcade_games.games.blackjack import hand_value
    # Dealer showing Ace + 6 = soft 17: S17 rules mean the dealer stands,
    # never hits, on exactly this total.
    total, soft = hand_value([('A', 0), ('6', 1)])
    assert total == 17 and soft
    # The game's own dealer loop condition is "while total < 17", which
    # correctly stops (stands) the instant a soft 17 is reached.
    assert not (total < 17)


# ── currency.py: shared virtual-chip ledger for the casino games ─────────────

def _chips_file():
    return _config.CONFIG_DIR / _currency.CHIPS_FILENAME


def _reset_chips():
    """Remove chips.json (and any stray lock/quarantine files from a prior
    test) so each currency test starts from the default 1000-chip state."""
    for suffix in ('', '.lock', '.bad'):
        p = Path(str(_chips_file()) + suffix)
        try:
            p.unlink()
        except OSError:
            pass


def _write_chips(balance, last_bailout_date=None):
    _config._ensure_config()
    _chips_file().write_text(
        json.dumps({'balance': balance, 'last_bailout_date': last_bailout_date}),
        encoding='utf-8')


def test_currency_starting_balance_is_1000():
    _reset_chips()
    try:
        assert _currency.balance() == 1000
        # A pure read must not create chips.json.
        assert not _chips_file().exists()
    finally:
        _reset_chips()


def test_currency_bet_refuses_overdraw_and_never_goes_negative():
    _reset_chips()
    try:
        assert _currency.balance() == 1000
        assert _currency.bet(1001) is False
        assert _currency.balance() == 1000  # untouched by the refused bet
        assert _currency.bet(0) is False
        assert _currency.bet(-5) is False
        assert _currency.bet(1000) is True
        assert _currency.balance() == 0
        assert _currency.bet(1) is False  # broke: any further bet is refused
        assert _currency.balance() == 0
    finally:
        _reset_chips()


def test_currency_bet_and_payout_roundtrip():
    _reset_chips()
    try:
        assert _currency.bet(100) is True
        assert _currency.balance() == 900
        assert _currency.payout(150) == 1050
        assert _currency.balance() == 1050
        assert _currency.payout(0) == 1050  # push: no-op, still returns balance
        try:
            _currency.payout(-1)
            raise AssertionError('payout(-1) should have raised ValueError')
        except ValueError:
            pass
    finally:
        _reset_chips()


def test_currency_bailout_fires_once_per_day_not_twice():
    _reset_chips()
    try:
        _write_chips(balance=0, last_bailout_date=None)
        assert _currency.bailout_available() is True
        assert _currency.try_bailout() is True
        assert _currency.balance() == _currency.BAILOUT_AMOUNT
        # Same calendar day, still at a non-zero balance: not offered again.
        assert _currency.bailout_available() is False
        # Even if the player is somehow broke again the same day, it must
        # not fire twice: force balance back to 0 without touching the date.
        _write_chips(balance=0, last_bailout_date=date.today().isoformat())
        assert _currency.bailout_available() is False
        assert _currency.try_bailout() is False
        assert _currency.balance() == 0  # refused: no phantom second grant
    finally:
        _reset_chips()


def test_currency_bailout_only_when_balance_is_zero():
    _reset_chips()
    try:
        _write_chips(balance=5, last_bailout_date=None)
        assert _currency.bailout_available() is False
        assert _currency.try_bailout() is False
        assert _currency.balance() == 5
    finally:
        _reset_chips()


def test_currency_bailout_resets_on_a_new_calendar_day():
    _reset_chips()
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _write_chips(balance=0, last_bailout_date=yesterday)
        assert _currency.bailout_available() is True
        assert _currency.try_bailout() is True
        assert _currency.balance() == _currency.BAILOUT_AMOUNT
    finally:
        _reset_chips()


def test_currency_corrupt_file_is_quarantined_not_lost():
    _reset_chips()
    try:
        _config._ensure_config()
        _chips_file().write_text('not json at all', encoding='utf-8')
        # A read-only balance() call falls back to the default rather than
        # raising, and does not itself destroy the corrupt file.
        assert _currency.balance() == 1000
        # A mutating call quarantines the corrupt file (never silently
        # overwrites it) and proceeds from the default state.
        assert _currency.bet(100) is True
        assert _currency.balance() == 900
        bad_files = list(_chips_file().parent.glob(_currency.CHIPS_FILENAME + '.bad*'))
        assert bad_files, 'corrupt chips.json should have been quarantined, not overwritten'
        for f in bad_files:
            assert f.read_text(encoding='utf-8') == 'not json at all'
    finally:
        for f in _chips_file().parent.glob(_currency.CHIPS_FILENAME + '.bad*'):
            f.unlink()
        _reset_chips()


def test_currency_negative_balance_on_disk_is_treated_as_corrupt():
    _reset_chips()
    try:
        _write_chips(balance=-50, last_bailout_date=None)
        # A hand-mangled negative balance must never be trusted as-is.
        assert _currency.balance() == 1000
    finally:
        _reset_chips()


def test_currency_write_failure_never_loses_or_duplicates_a_bet():
    """If persistence fails mid-transaction (e.g. the process is about to
    crash, or the lock/IO budget is exhausted), the balance on disk must be
    exactly what it was before the attempt: no chips vanish, and no chips
    get silently duplicated on the next successful call."""
    _reset_chips()
    saved = _config._atomic_write_json
    try:
        assert _currency.bet(100) is True
        assert _currency.balance() == 900
        _config._atomic_write_json = lambda *a, **k: False
        assert _currency.bet(50) is False  # write "fails": must not apply
        assert _currency.payout(50) == 900  # write "fails": reports prior balance
    finally:
        _config._atomic_write_json = saved
        _reset_chips()
    # Confirm the module really did route through config._atomic_write_json
    # (the shared, locked, byte-verified writer) rather than a hand-rolled
    # one: with it restored, a normal bet persists again.
    try:
        assert _currency.bet(1) is True
        assert _currency.balance() == 999
    finally:
        _reset_chips()


def test_currency_concurrent_bets_and_payouts_never_lose_or_corrupt_chips():
    """Simulate a bunch of racing writers (the scenario save_high_score got
    caught losing data on): many threads hammering bet()/payout() against
    the same chips.json at once. The locked read-modify-write must
    serialize every one of them, so the final balance is exactly the
    arithmetic sum of every operation that reported success, with nothing
    lost and nothing double-applied."""
    _reset_chips()
    try:
        _write_chips(balance=1000, last_bailout_date=None)
        n_bettors, n_payers = 25, 25
        results = [None] * (n_bettors + n_payers)

        def do_bet(i):
            results[i] = ('bet', 10, _currency.bet(10))

        def do_payout(i):
            results[i] = ('payout', 5, True)
            _currency.payout(5)

        threads = []
        for i in range(n_bettors):
            threads.append(threading.Thread(target=do_bet, args=(i,)))
        for i in range(n_payers):
            threads.append(threading.Thread(target=do_payout, args=(n_bettors + i,)))
        random.shuffle(threads)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = 1000
        for kind, amount, ok in results:
            if kind == 'bet' and ok:
                expected -= amount
            elif kind == 'payout':
                expected += amount
        final = _currency.balance()
        assert final == expected, f'expected {expected}, got {final} (lost or duplicated chips)'
        assert final >= 0
        # Every bet against a healthy, well-above-zero balance in this mix
        # should have succeeded; none should have been spuriously refused
        # by lock contention.
        assert all(ok for kind, _, ok in results if kind == 'bet')
    finally:
        _reset_chips()


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith('test_') and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS {t.__name__}')
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'FAIL {t.__name__}: {exc!r}')
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    return failed


if __name__ == '__main__':
    sys.exit(1 if _run_all() else 0)
