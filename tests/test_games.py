"""Dependency-free tests for play.py.

Runs with plain ``python tests/test_games.py`` (no pytest required) and is also
pytest-compatible. A fake ``curses`` module is injected before importing ``play``
so the whole suite is deterministic and runs on any platform, with or without a
real curses build installed.
"""
import json
import random
import sys
import tempfile
import types
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

# Redirect config to a temp dir so tests never touch the user's real saves.
_TMP = Path(tempfile.mkdtemp())
play.CONFIG_DIR = _TMP
play.SCORES_FILE = _TMP / 'scores.json'
play.GAME_STATE_FILE = _TMP / 'current_game.json'

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
        (play.CONFIG_DIR / f'save_{cls.name}.json').write_text(json.dumps(data))
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
    g = play.DinoGame(MockScreen(40, 110))
    g.setup()
    g.speed = 3.0
    g.dino_y = 0.0
    g.on_ground = True
    g.obstacles = [{'x': 8.0, 'art': play._CACTUS_SM}]
    g.update()
    assert g.game_over


def test_pong_ai_speeds_are_distinct():
    def step(diff):
        g = play.PongGame(MockScreen())
        g.difficulty = diff
        g.setup()
        return max(1, round(g.ai_speed * 2))
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
    g.handle_input(RIGHT)   # push box onto target in level 1
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


def test_dino_clears_cactus_on_landing():
    """Regression: landing beside a small cactus after clearing it must not kill."""
    g = play.DinoGame(MockScreen(40, 110))
    g.setup()
    g.score = 200                      # -> speed 3.0
    g.on_ground = False
    g.dino_y = -2.0
    g.velocity = 2.0                   # lands to 0 this tick
    g.spawn_timer = 999
    g.obstacles = [{'x': 10.0, 'art': play._CACTUS_SM}]  # ends at 7 (left of dino)
    g.update()
    assert not g.game_over


def test_dino_grounded_fast_obstacle_still_blocks_tunnel():
    g = play.DinoGame(MockScreen(40, 110))
    g.setup()
    g.score = 200                      # speed 3.0
    g.on_ground = True
    g.dino_y = 0.0
    g.velocity = 0.0
    g.spawn_timer = 999
    g.obstacles = [{'x': 11.0, 'art': play._CACTUS_SM}]  # sweeps across cols 9-10
    g.update()
    assert g.game_over


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
