"""The plain-text CLI front-end for turn-based games with no terminal/curses
needed (play.py 3979-4624): snake, 2048, minesweeper, connect4.

ConnectFourGame (arcade_games/games/connect4.py) lazily imports
_cli_c4_check_win and _cli_c4_ai_move from this module to avoid a circular
import (games -> cli -> games).
"""
import json
import random

from . import config

# ─── CLI: Snake ──────────────────────────────────────────────────────────────

def _cli_place_food(h, w, snake):
    snake_set = {tuple(p) for p in snake}
    empty = [(y, x) for y in range(1, h - 1) for x in range(1, w - 1)
             if (y, x) not in snake_set]
    return list(random.choice(empty)) if empty else [1, 1]


def _cli_snake_init():
    h, w = 12, 20
    my, mx = h // 2, w // 2
    snake = [[my, mx], [my, mx - 1], [my, mx - 2]]
    return {'game': 'snake', 'h': h, 'w': w, 'snake': snake,
            'dir': [0, 1], 'food': _cli_place_food(h, w, snake),
            'score': 0, 'over': False}


def _cli_snake_move(s, action):
    dirs = {'up': [-1, 0], 'down': [1, 0], 'left': [0, -1], 'right': [0, 1]}
    if action not in dirs:
        return s
    nd = dirs[action]
    od = s['dir']
    if nd[0] != -od[0] or nd[1] != -od[1]:
        s['dir'] = nd
    hy, hx = s['snake'][0]
    dy, dx = s['dir']
    nh = [hy + dy, hx + dx]
    if nh[0] <= 0 or nh[0] >= s['h'] - 1 or nh[1] <= 0 or nh[1] >= s['w'] - 1:
        s['over'] = True
        return s
    grow = (nh == s['food'])
    # The tail moves out of its cell unless we eat, so following the tail is
    # legal: exclude the last segment when not growing.
    body = s['snake'] if grow else s['snake'][:-1]
    if nh in body:
        s['over'] = True
        return s
    s['snake'].insert(0, nh)
    if grow:
        s['score'] += 1
        s['food'] = _cli_place_food(s['h'], s['w'], s['snake'])
    else:
        s['snake'].pop()
    return s


def _cli_snake_render(s):
    lines = [f"SNAKE   Score: {s['score']}"]
    lines.append('┌' + '─' * (s['w'] - 2) + '┐')
    snake_set = {tuple(p) for p in s['snake']}
    head = tuple(s['snake'][0])
    food = tuple(s['food'])
    for y in range(1, s['h'] - 1):
        row = '│'
        for x in range(1, s['w'] - 1):
            if (y, x) == head:
                row += '@'
            elif (y, x) in snake_set:
                row += 'o'
            elif (y, x) == food:
                row += '*'
            else:
                row += '·'
        row += '│'
        lines.append(row)
    lines.append('└' + '─' * (s['w'] - 2) + '┘')
    if s['over']:
        lines.append(f"GAME OVER!  Final score: {s['score']}")
    else:
        lines.append('Move: up / down / left / right')
    return '\n'.join(lines)


# ─── CLI: 2048 ───────────────────────────────────────────────────────────────

def _cli_2048_add_tile(grid):
    empty = [(r, c) for r in range(4) for c in range(4) if grid[r][c] == 0]
    if empty:
        r, c = random.choice(empty)
        grid[r][c] = 4 if random.random() < 0.1 else 2


def _cli_2048_slide(row):
    tiles = [x for x in row if x]
    merged, pts, i = [], 0, 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            v = tiles[i] * 2
            merged.append(v)
            pts += v
            i += 2
        else:
            merged.append(tiles[i])
            i += 1
    return merged + [0] * (4 - len(merged)), pts


def _cli_2048_init():
    grid = [[0] * 4 for _ in range(4)]
    _cli_2048_add_tile(grid)
    _cli_2048_add_tile(grid)
    return {'game': '2048', 'grid': grid, 'score': 0, 'over': False, 'won': False}


def _cli_2048_can_move(g):
    for r in range(4):
        for c in range(4):
            if g[r][c] == 0:
                return True
            if c + 1 < 4 and g[r][c] == g[r][c + 1]:
                return True
            if r + 1 < 4 and g[r][c] == g[r + 1][c]:
                return True
    return False


def _cli_2048_move(s, action):
    if action not in ('up', 'down', 'left', 'right'):
        return s
    old = [row[:] for row in s['grid']]
    g, pts = s['grid'], 0
    if action == 'left':
        for r in range(4):
            g[r], p = _cli_2048_slide(g[r])
            pts += p
    elif action == 'right':
        for r in range(4):
            rev, p = _cli_2048_slide(g[r][::-1])
            g[r] = rev[::-1]
            pts += p
    elif action == 'up':
        for c in range(4):
            col, p = _cli_2048_slide([g[r][c] for r in range(4)])
            pts += p
            for r in range(4):
                g[r][c] = col[r]
    elif action == 'down':
        for c in range(4):
            col, p = _cli_2048_slide([g[r][c] for r in range(4)][::-1])
            pts += p
            col = col[::-1]
            for r in range(4):
                g[r][c] = col[r]
    if g != old:
        s['score'] += pts
        _cli_2048_add_tile(g)
        if not s['won'] and any(g[r][c] == 2048 for r in range(4) for c in range(4)):
            s['won'] = True
    if not _cli_2048_can_move(g):
        s['over'] = True
    return s


def _cli_2048_render(s):
    g = s['grid']
    cw = 6
    lines = [f"2048   Score: {s['score']}"]
    top = '┌' + ('─' * cw + '┬') * 3 + '─' * cw + '┐'
    sep = '├' + ('─' * cw + '┼') * 3 + '─' * cw + '┤'
    bot = '└' + ('─' * cw + '┴') * 3 + '─' * cw + '┘'
    lines.append(top)
    for r in range(4):
        row = '│'
        for c in range(4):
            v = g[r][c]
            row += (str(v).center(cw) if v else ' ' * cw) + '│'
        lines.append(row)
        lines.append(sep if r < 3 else bot)
    if s['won']:
        lines.append('You reached 2048! Keep going!')
    if s['over']:
        lines.append(f"GAME OVER!  Final score: {s['score']}")
    else:
        lines.append('Move: up / down / left / right')
    return '\n'.join(lines)


# ─── CLI: Minesweeper ────────────────────────────────────────────────────────

def _cli_ms_place_mines(s, safe_r, safe_c):
    """Place mines after the first reveal, keeping that cell and its neighbors
    mine-free so the first click is always safe (matches the interactive game)."""
    size = s['size']
    forbidden = {(safe_r + dr, safe_c + dc)
                 for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
    cells = [(r, c) for r in range(size) for c in range(size)
             if (r, c) not in forbidden]
    mines = set(random.sample(cells, min(s['num_mines'], len(cells))))
    nums = [[0] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if (r, c) in mines:
                nums[r][c] = -1
                continue
            nums[r][c] = sum(
                1 for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                if 0 <= r + dr < size and 0 <= c + dc < size
                and (r + dr, c + dc) in mines)
    s['mines'] = [list(m) for m in mines]
    s['nums'] = nums
    s['placed'] = True


def _cli_ms_init(size=9, num_mines=10):
    # Mines are placed lazily on the first reveal so it is always safe.
    return {'game': 'minesweeper', 'size': size, 'num_mines': num_mines,
            'mines': [], 'nums': [[0] * size for _ in range(size)],
            'placed': False, 'revealed': [], 'flagged': [],
            'over': False, 'won': False, 'score': 0}


def _cli_ms_move(s, action):
    parts = action.split()
    if len(parts) < 3 or parts[0] not in ('reveal', 'flag'):
        return s
    try:
        r, c = int(parts[1]) - 1, int(parts[2]) - 1
    except (ValueError, IndexError):
        return s
    sz = s['size']
    if r < 0 or r >= sz or c < 0 or c >= sz:
        return s

    mines_set = {tuple(m) for m in s['mines']}
    revealed = {tuple(p) for p in s['revealed']}
    flagged = {tuple(p) for p in s['flagged']}

    if parts[0] == 'flag':
        if (r, c) in revealed:
            pass
        elif (r, c) in flagged:
            flagged.discard((r, c))
        else:
            flagged.add((r, c))
    elif parts[0] == 'reveal':
        if (r, c) in flagged or (r, c) in revealed:
            pass
        else:
            if not s.get('placed', len(s.get('mines', [])) > 0):
                _cli_ms_place_mines(s, r, c)
                mines_set = {tuple(m) for m in s['mines']}
            if (r, c) in mines_set:
                s['over'] = True
                revealed |= mines_set
            else:
                stack = [(r, c)]
                while stack:
                    cr, cc = stack.pop()
                    if (cr, cc) in revealed or (cr, cc) in flagged:
                        continue  # never auto-reveal a flagged cell
                    revealed.add((cr, cc))
                    if s['nums'][cr][cc] == 0:
                        for dr in (-1, 0, 1):
                            for dc in (-1, 0, 1):
                                nr, nc = cr + dr, cc + dc
                                if 0 <= nr < sz and 0 <= nc < sz and (nr, nc) not in revealed:
                                    stack.append((nr, nc))

    s['revealed'] = [list(p) for p in revealed]
    s['flagged'] = [list(p) for p in flagged]

    safe_total = sz * sz - len(mines_set)
    revealed_safe = len(revealed - mines_set)
    if revealed_safe == safe_total and not s['over']:
        s['won'] = True
        s['over'] = True
        s['score'] = safe_total
    return s


def _cli_ms_render(s):
    sz = s['size']
    mines_set = {tuple(m) for m in s['mines']}
    revealed = {tuple(p) for p in s['revealed']}
    flagged = {tuple(p) for p in s['flagged']}
    total_mines = s.get('num_mines', len(mines_set))
    lines = [f"MINESWEEPER   Mines left: ~{total_mines - len(flagged)}"]
    hdr = '     ' + ''.join(f'{c + 1:>3}' for c in range(sz))
    lines.append(hdr)
    lines.append('    ┌' + '───' * sz + '┐')
    for r in range(sz):
        row = f' {r + 1:>2} │'
        for c in range(sz):
            if (r, c) in flagged and not s['over']:
                row += ' F '
            elif (r, c) not in revealed:
                row += ' . '
            elif (r, c) in mines_set:
                row += ' X '
            elif s['nums'][r][c] == 0:
                row += '   '
            else:
                row += f' {s["nums"][r][c]} '
        row += '│'
        lines.append(row)
    lines.append('    └' + '───' * sz + '┘')
    if s['won']:
        lines.append('YOU WIN! All safe cells revealed!')
    elif s['over']:
        lines.append('BOOM! You hit a mine!')
    else:
        lines.append('Commands: reveal <row> <col>  |  flag <row> <col>')
    return '\n'.join(lines)


# ─── CLI: Connect4 ───────────────────────────────────────────────────────────

def _cli_c4_init():
    return {
        'game': 'connect4',
        'board': [[0] * 7 for _ in range(6)],
        'score': 0,
        'over': False,
        'won': False,
        'turn': 1,
        'last_col': None,
    }


def _cli_c4_check_win(board, player):
    rows, cols = 6, 7
    # Horizontal
    for r in range(rows):
        for c in range(cols - 3):
            if all(board[r][c + i] == player for i in range(4)):
                return True
    # Vertical
    for r in range(rows - 3):
        for c in range(cols):
            if all(board[r + i][c] == player for i in range(4)):
                return True
    # Diagonal down-right
    for r in range(rows - 3):
        for c in range(cols - 3):
            if all(board[r + i][c + i] == player for i in range(4)):
                return True
    # Diagonal down-left
    for r in range(rows - 3):
        for c in range(3, cols):
            if all(board[r + i][c - i] == player for i in range(4)):
                return True
    return False


def _cli_c4_drop(board, col, player):
    """Drop piece into col (0-indexed). Returns row placed, or -1 if full."""
    for r in range(5, -1, -1):
        if board[r][col] == 0:
            board[r][col] = player
            return r
    return -1


def _cli_c4_is_full(board):
    return all(board[0][c] != 0 for c in range(7))


_C4_AI_DEPTH = 5  # depth 6 could freeze the UI ~1s; 5 is ~0.3s worst-case and still strong


def _c4_valid_cols(board):
    return [c for c in range(7) if board[0][c] == 0]


def _c4_drop_row(board, col):
    for r in range(5, -1, -1):
        if board[r][col] == 0:
            return r
    return -1


def _c4_window_score(cells, me, opp):
    m = cells.count(me)
    o = cells.count(opp)
    if m and o:
        return 0            # blocked window, worthless to either side
    if m == 3:
        return 60
    if m == 2:
        return 8
    if o == 3:
        return -75          # blocking an opponent threat is worth a bit more
    if o == 2:
        return -6
    return 0


def _c4_evaluate(board, me):
    opp = 3 - me
    score = sum(6 for r in range(6) if board[r][3] == me)  # center control
    score -= sum(6 for r in range(6) if board[r][3] == opp)
    for r in range(6):
        for c in range(4):
            score += _c4_window_score([board[r][c + i] for i in range(4)], me, opp)
    for c in range(7):
        for r in range(3):
            score += _c4_window_score([board[r + i][c] for i in range(4)], me, opp)
    for r in range(3):
        for c in range(4):
            score += _c4_window_score([board[r + i][c + i] for i in range(4)], me, opp)
        for c in range(3, 7):
            score += _c4_window_score([board[r + i][c - i] for i in range(4)], me, opp)
    return score


def _c4_minimax(board, depth, alpha, beta, maximizing, me):
    opp = 3 - me
    if _cli_c4_check_win(board, me):
        return None, 100000 + depth        # prefer faster wins
    if _cli_c4_check_win(board, opp):
        return None, -100000 - depth
    valid = _c4_valid_cols(board)
    if not valid:
        return None, 0                     # draw
    if depth == 0:
        return None, _c4_evaluate(board, me)
    order = sorted(valid, key=lambda c: abs(c - 3))  # center-first for pruning
    best_col = order[0]
    if maximizing:
        best = -10 ** 9
        for col in order:
            r = _c4_drop_row(board, col)
            board[r][col] = me
            _, val = _c4_minimax(board, depth - 1, alpha, beta, False, me)
            board[r][col] = 0
            if val > best:
                best, best_col = val, col
            alpha = max(alpha, best)
            if alpha >= beta:
                break
    else:
        best = 10 ** 9
        for col in order:
            r = _c4_drop_row(board, col)
            board[r][col] = opp
            _, val = _c4_minimax(board, depth - 1, alpha, beta, True, me)
            board[r][col] = 0
            if val < best:
                best, best_col = val, col
            beta = min(beta, best)
            if alpha >= beta:
                break
    return best_col, best


def _cli_c4_ai_move(board):
    """Best column (0-indexed) for the AI (player 2) via alpha-beta minimax."""
    valid = _c4_valid_cols(board)
    if not valid:
        return -1
    col, _ = _c4_minimax([row[:] for row in board], _C4_AI_DEPTH,
                         -10 ** 9, 10 ** 9, True, 2)
    return col if col in valid else valid[0]


def _cli_c4_move(s, action):
    if s.get('over'):
        return s
    action = action.strip()
    try:
        col = int(action) - 1
    except ValueError:
        return s
    if col < 0 or col > 6:
        return s
    if s['board'][0][col] != 0:
        return s

    # Player move
    _cli_c4_drop(s['board'], col, 1)
    s['last_col'] = col
    if _cli_c4_check_win(s['board'], 1):
        s['over'] = True
        s['won'] = True
        s['score'] = 1
        return s
    if _cli_c4_is_full(s['board']):
        s['over'] = True
        return s

    # AI move
    ai_col = _cli_c4_ai_move(s['board'])
    if ai_col >= 0:
        _cli_c4_drop(s['board'], ai_col, 2)
        s['last_col'] = ai_col
        if _cli_c4_check_win(s['board'], 2):
            s['over'] = True
            s['won'] = False
            s['score'] = 0
            return s
        if _cli_c4_is_full(s['board']):
            s['over'] = True
    return s


def _cli_c4_render(s):
    lines = [f"CONNECT 4   Score: {s['score']}"]
    lines.append('  1 2 3 4 5 6 7')
    lines.append(' ┌─────────────┐')
    glyphs = {0: '.', 1: 'X', 2: 'O'}
    for r in range(6):
        row = ' │'
        for c in range(7):
            row += glyphs[s['board'][r][c]] + ' '
        row = row.rstrip(' ') + '│'
        lines.append(row)
    lines.append(' └─────────────┘')
    if s['won']:
        lines.append('You win!')
    elif s.get('over'):
        if not s['won'] and _cli_c4_is_full(s['board']) and not _cli_c4_check_win(s['board'], 2):
            lines.append("It's a draw!")
        else:
            lines.append('AI wins!')
    else:
        lines.append('Your turn (1-7):')
    return '\n'.join(lines)


# ─── CLI Dispatcher ──────────────────────────────────────────────────────────

_CLI_GAMES = {
    'snake': (_cli_snake_init, _cli_snake_move, _cli_snake_render),
    '2048': (_cli_2048_init, _cli_2048_move, _cli_2048_render),
    'minesweeper': (_cli_ms_init, _cli_ms_move, _cli_ms_render),
    'connect4': (_cli_c4_init, _cli_c4_move, _cli_c4_render),
}


def _load_game_state():
    # GAME_STATE_FILE holds a small pointer to whichever CLI game is
    # currently active; the actual state lives in a per-game file (see
    # config.game_state_file) so starting a different game never destroys
    # an in-progress one.
    try:
        ptr = json.loads(config.GAME_STATE_FILE.read_text())
        name = ptr.get('game')
        if not name:
            return None
        return json.loads(config.game_state_file(name).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        return None


def _save_game_state(state):
    config._atomic_write_json(config.game_state_file(state['game']), state)
    config._atomic_write_json(config.GAME_STATE_FILE, {'game': state['game']})


def _cli_render(state):
    renderers = {'snake': _cli_snake_render, '2048': _cli_2048_render,
                 'minesweeper': _cli_ms_render, 'connect4': _cli_c4_render}
    return renderers.get(state['game'], lambda s: 'Unknown game')(state)


def _cli_mode(args):
    if not args:
        state = _load_game_state()
        if state and not state.get('over'):
            print(_cli_render(state))
        else:
            print('ARCADE GAMES')
            print('────────────')
            print('  snake        Classic snake, turn by turn')
            print('  2048         Slide and merge number tiles')
            print('  minesweeper  Uncover cells, avoid mines')
            print('  connect4     Drop pieces, get four in a row')
            print()
            print('Start a game:  arcade cli start <game>')
            print('Interactive:   ! arcade  (full-screen curses games)')
        return

    cmd = args[0].lower()

    if cmd == 'start':
        name = args[1].lower() if len(args) > 1 else ''
        if name in ('ms', 'mines'):
            name = 'minesweeper'
        if name in ('c4',):
            name = 'connect4'
        if name not in _CLI_GAMES:
            print(f'Unknown game: {name}')
            print('Available: snake, 2048, minesweeper, connect4')
            return
        # Per-game state files (config.game_state_file) already meant
        # switching to a different game no longer overwrote this one's save
        # on disk, but nothing could ever read it back: 'start' always
        # re-initialized and clobbered it, so progress survived on disk but
        # was still unreachable, with no separate resume/switch verb to get
        # it back (INFRA-13). 'start' on a game with an unfinished save now
        # resumes it, the same way the curses games resume from save.
        state = None
        f = config.game_state_file(name)
        if f.exists():
            try:
                existing = json.loads(f.read_text())
                if not existing.get('over'):
                    state = existing
            except (json.JSONDecodeError, OSError):
                state = None
        if state is None:
            init_fn = _CLI_GAMES[name][0]
            state = init_fn()
        _save_game_state(state)
        print(_cli_render(state))

    elif cmd == 'show':
        state = _load_game_state()
        if state:
            print(_cli_render(state))
        else:
            print('No active game. Run: arcade cli start <game>')

    elif cmd == 'quit':
        state = _load_game_state()
        if state:
            config.save_high_score(state['game'], state.get('score', 0))
            config.game_state_file(state['game']).unlink(missing_ok=True)
            config.GAME_STATE_FILE.unlink(missing_ok=True)
            print(f"Game ended. Final score: {state.get('score', 0)}")
        else:
            print('No active game.')

    elif cmd in ('up', 'down', 'left', 'right'):
        state = _load_game_state()
        if not state:
            print('No active game. Run: arcade cli start <game>')
            return
        if state.get('over'):
            print(_cli_render(state))
            return
        move_fn = _CLI_GAMES[state['game']][1]
        state = move_fn(state, cmd)
        _save_game_state(state)
        if state.get('over'):
            config.save_high_score(state['game'], state.get('score', 0))
        print(_cli_render(state))

    elif cmd in ('reveal', 'flag'):
        state = _load_game_state()
        if not state or state.get('game') != 'minesweeper':
            print('No active minesweeper game.')
            return
        if state.get('over'):
            print(_cli_render(state))
            return
        action = ' '.join(args)
        state = _cli_ms_move(state, action)
        _save_game_state(state)
        if state.get('over'):
            config.save_high_score(state['game'], state.get('score', 0))
        print(_cli_render(state))

    elif cmd.isdigit():
        # Connect4 column move
        state = _load_game_state()
        if not state or state.get('game') != 'connect4':
            print('No active connect4 game.')
            return
        if state.get('over'):
            print(_cli_render(state))
            return
        state = _cli_c4_move(state, cmd)
        _save_game_state(state)
        if state.get('over'):
            config.save_high_score(state['game'], state.get('score', 0))
        print(_cli_render(state))

    else:
        print(f'Unknown: {cmd}')
        print('Commands: start <game> | up/down/left/right | 1-7 (connect4) | reveal/flag <r> <c> | show | quit')
