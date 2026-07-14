"""Reversi / Othello."""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class ReversiGame(Game):
    name = "reversi"
    min_h = 20
    min_w = 34
    supports_difficulty = False
    N = 8
    _DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    _WEIGHTS = [
        [120, -20,  20,   5,   5,  20, -20, 120],
        [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
        [ 20,  -5,  15,   3,   3,  15,  -5,  20],
        [  5,  -5,   3,   3,   3,   3,  -5,   5],
        [  5,  -5,   3,   3,   3,   3,  -5,   5],
        [ 20,  -5,  15,   3,   3,  15,  -5,  20],
        [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
        [120, -20,  20,   5,   5,  20, -20, 120],
    ]

    def setup(self):
        # net (a _NetLink) and local_player (1=black/host, 2=white/guest) may be
        # set by the multiplayer lobby before run(); default to solo vs AI.
        self.net = getattr(self, 'net', None)
        self.local_player = getattr(self, 'local_player', 1)
        # A move that arrives over the wire while we are not actively
        # resolving turns (help open, a resize) is parked here by
        # net_pump() instead of being lost, and drained by update().
        self._net_inbox = None
        saved = self._load_save(self.name) if not self.net else None
        if saved:
            self.board = saved['board']
            self.cur_r = saved['cur_r']
            self.cur_c = saved['cur_c']
            self.turn = saved['turn']
            self.score = saved['score']
            self.message = saved.get('message', '')
            return
        n = self.N
        self.board = [[0] * n for _ in range(n)]
        m = n // 2
        self.board[m - 1][m - 1] = self.board[m][m] = 2   # white
        self.board[m - 1][m] = self.board[m][m - 1] = 1   # black (moves first)
        self.cur_r = self.cur_c = m
        self.turn = 1
        self.score = 2
        self.message = ''

    def get_timeout(self):
        return 120 if self.net else -1  # net games poll; local games block

    def _flips(self, board, r, c, player):
        if board[r][c] != 0:
            return []
        opp = 3 - player
        out = []
        for dy, dx in self._DIRS:
            line, y, x = [], r + dy, c + dx
            while 0 <= y < self.N and 0 <= x < self.N and board[y][x] == opp:
                line.append((y, x)); y += dy; x += dx
            if line and 0 <= y < self.N and 0 <= x < self.N and board[y][x] == player:
                out.extend(line)
        return out

    def _valid_moves(self, board, player):
        moves = {}
        for r in range(self.N):
            for c in range(self.N):
                if board[r][c] == 0:
                    f = self._flips(board, r, c, player)
                    if f:
                        moves[(r, c)] = f
        return moves

    def _apply(self, board, r, c, player, flips):
        board[r][c] = player
        for (y, x) in flips:
            board[y][x] = player

    def _apply_animated(self, r, c, player, flips):
        """Place a disc and reveal its flips over ~180 ms so a multi-disc
        outflank is legible instead of an instant state teleport. A no-op
        pacing pass (single frame, zero delay) when self.net is set, same
        as animate() everywhere else, so a peer is never blocked on it."""
        self.board[r][c] = player
        if not flips:
            return
        frame_ms = max(15, 180 // len(flips))
        it = iter(flips)
        for _ in self.animate([frame_ms] * len(flips)):
            y, x = next(it)
            self.board[y][x] = player
            self.stdscr.erase()
            self.draw()

    def _pause(self, ms):
        """Hold the current frame on screen for ms (AI think pause, a
        visible pass message). ESC fast-forwards past it; it never blocks
        a net peer (animate() no-ops when self.net is set)."""
        for _ in self.animate((ms,)):
            self.stdscr.erase()
            self.draw()

    def _counts(self):
        b = sum(row.count(1) for row in self.board)
        w = sum(row.count(2) for row in self.board)
        return b, w

    def _evaluate(self, board, me):
        opp = 3 - me
        pos = empties = 0
        for r in range(self.N):
            row = board[r]
            wrow = self._WEIGHTS[r]
            for c in range(self.N):
                v = row[c]
                if v == 0:
                    empties += 1
                elif v == me:
                    pos += wrow[c]
                else:
                    pos -= wrow[c]
        my_mob = len(self._valid_moves(board, me))
        opp_mob = len(self._valid_moves(board, opp))
        mob = 8 * (my_mob - opp_mob)
        if empties <= 10:  # in the endgame, actual disc count dominates
            mine = sum(row.count(me) for row in board)
            theirs = sum(row.count(opp) for row in board)
            return pos + mob + 15 * (mine - theirs)
        return pos + mob

    def _negamax(self, board, player, depth, alpha, beta):
        moves = self._valid_moves(board, player)
        opp = 3 - player
        if not moves:
            opp_moves = self._valid_moves(board, opp)
            if not opp_moves:
                # Neither side can move: the game is over. This terminal
                # check runs before any depth cutoff, at any depth,
                # including depth 0, so a true end-of-game position is
                # always scored exactly instead of by the static heuristic.
                mine = sum(row.count(player) for row in board)
                theirs = sum(row.count(opp) for row in board)
                return None, (100000 if mine > theirs
                              else -100000 if mine < theirs else 0)
            # A pass is not a real move, so it does not spend search depth:
            # burning a ply on every pass was starving the search of the
            # real plies it needs to reach the actual end of the game.
            _, val = self._negamax(board, opp, depth, -beta, -alpha)
            return None, -val
        if depth == 0:
            return None, self._evaluate(board, player)
        best_move, best_val = None, -10 ** 9
        for (r, c) in sorted(moves, key=lambda rc: -self._WEIGHTS[rc[0]][rc[1]]):
            nb = [row[:] for row in board]
            self._apply(nb, r, c, player, moves[(r, c)])
            _, val = self._negamax(nb, opp, depth - 1, -beta, -alpha)
            val = -val
            if val > best_val:
                best_val, best_move = val, (r, c)
            alpha = max(alpha, val)
            if alpha >= beta:
                break
        return best_move, best_val

    def _ai_move(self, valid):
        empties = sum(row.count(0) for row in self.board)
        # Depth must be >= empties for a genuine endgame solve: capping it
        # at 5 meant a 10-empty position still terminated on the static
        # evaluator 5 plies short of the actual end of the game (the
        # terminal-node check added for reversi-11 never got the chance to
        # fire), never seeing the true final disc count it was meant to
        # find. A 10-empty exact solve is cheap with alpha-beta.
        depth = empties if empties <= 10 else 3
        move, _ = self._negamax([row[:] for row in self.board], 2, depth,
                                -10 ** 9, 10 ** 9)
        return move if move in valid else random.choice(list(valid))

    def _finish(self):
        b, w = self._counts()
        mine = b if self.local_player == 1 else w
        theirs = w if self.local_player == 1 else b
        self.score = mine
        self.won = mine > theirs
        self.tied = mine == theirs
        self.game_over = True
        self.message = ('You win!' if mine > theirs else
                        'Draw' if mine == theirs else 'You lose')

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self.cur_r = (self.cur_r - 1) % self.N
        elif key in (curses.KEY_DOWN, ord('s')):
            self.cur_r = (self.cur_r + 1) % self.N
        elif key in (curses.KEY_LEFT, ord('a')):
            self.cur_c = (self.cur_c - 1) % self.N
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.cur_c = (self.cur_c + 1) % self.N
        elif key in (curses.KEY_ENTER, ord(' '), 10, 13):
            if self.turn != self.local_player or self.game_over:
                return
            valid = self._valid_moves(self.board, self.local_player)
            if (self.cur_r, self.cur_c) not in valid:
                return
            r, c = self.cur_r, self.cur_c
            flips = valid[(r, c)]
            if self.net:
                self.net.send({'type': 'place', 'r': r, 'c': c})
            self._apply_animated(r, c, self.local_player, flips)
            self.turn = 3 - self.local_player

    def net_pump(self):
        if not (self.net and self.net.alive):
            return
        if self.game_over:
            # Keep heartbeats/acks/resend flowing while the banner is up
            # (NET-8), WITHOUT draining the socket through poll(): poll()
            # hands back (and permanently discards) the next queued
            # application message, and the code below used to do exactly
            # that unconditionally, throwing away anything whose type
            # wasn't 'place' -- including the peer's post-game '_rematch'
            # frame. That message was already acked on arrival, so the
            # peer never resent it, and _net_await_rematch's own later
            # poll() found nothing. pump() alone parses inbound bytes into
            # the link's inbox and leaves them there for the real reader
            # (_net_await_rematch, called after this game loop returns) to
            # poll() for real.
            self.net.pump()
            return
        # Drain the socket every loop iteration, not just while update() is
        # resolving the opponent's turn: previously a peer disconnect on
        # YOUR turn (or while help was open) went undetected until the
        # opponent branch next ran. Also parks an early-arriving move
        # instead of dropping it.
        if self._net_inbox is None:
            msg = self.net.poll()
            if msg and msg.get('type') == 'place':
                self._net_inbox = msg
        else:
            # A move is already parked (waiting for update() to be able to
            # drain it, e.g. the help overlay is up). poll() must still be
            # driven from here, or heartbeat/resend/timeout bookkeeping
            # (all inside pump(), which poll() also calls) stalls for as
            # long as the overlay stays open, and the peer's own receive
            # timer expires it as a disconnect (NET-2).
            self.net.pump()

    def update(self):
        if self.game_over:
            return
        if self.net and not self.net.alive:
            b, w = self._counts()
            self.score = b if self.local_player == 1 else w
            self.game_over = True
            self.message = 'Opponent disconnected'
            return
        # Resolve turns/passes until it is the local player's move (with a legal
        # option) or the game ends. The opponent's move comes from the AI (solo)
        # or the network (multiplayer); passes are deterministic from the board.
        for _ in range(self.N * self.N + 4):
            pv = self._valid_moves(self.board, 1)
            av = self._valid_moves(self.board, 2)
            b, w = self._counts()
            self.score = b if self.local_player == 1 else w
            if not pv and not av:
                self._finish()
                return
            cur = self.turn
            curv = pv if cur == 1 else av
            if cur == self.local_player:
                if curv:
                    self.message = 'Your move'
                    return
                self.message = 'No move - you pass'
                self._pause(700)  # visible: previously overwritten before it drew
                self.turn = 3 - cur
                continue
            # opponent's turn
            if not curv:
                self.message = 'Opponent passes' if self.net else 'AI passes'
                self._pause(700)  # previously silent: the human got two turns
                self.turn = 3 - cur
                continue
            if self.net:
                msg = self._net_inbox or self.net.poll()
                self._net_inbox = None
                while msg is not None and msg.get('type') != 'place':
                    # A non-'place' message here is already a protocol
                    # anomaly (the opponent's turn should only ever
                    # produce a 'place', or nothing yet). poll() has
                    # already acked and permanently discarded it, so
                    # `return`-ing on the mismatch used to stall the whole
                    # turn until some unrelated later message arrived,
                    # even if the real 'place' was already queued right
                    # behind it. Drain forward instead of bailing on the
                    # first mismatch.
                    msg = self.net.poll()
                if not (msg and msg.get('type') == 'place'):
                    self.message = "Opponent's turn..."
                    return  # keep polling next tick
                r, c = msg.get('r'), msg.get('c')
                if (r, c) not in curv:
                    return  # ignore illegal / malformed
                self._apply_animated(r, c, cur, curv[(r, c)])
            else:
                self.message = 'AI is thinking...'
                self._pause(400)
                r, c = self._ai_move(curv)
                self._apply_animated(r, c, cur, curv[(r, c)])
                self.message = f'AI played {chr(65 + c)}{r + 1}'
            self.turn = 3 - cur

    def draw(self):
        b, w = self._counts()
        N = self.N
        gw = 2 * N + 1  # bordered grid width: '|' + N*(cell+'|')
        sx = max(0, (self.w - (gw + 3)) // 2)
        board_x = sx + 3
        sy = max(3, (self.h - (N + 6)) // 2)

        self.safe_addstr(sy - 2, max(0, (self.w - 9) // 2), ' REVERSI ',
                         curses.A_BOLD | curses.A_REVERSE)
        if self.net:
            xlab = 'You' if self.local_player == 1 else 'Opp'
            olab = 'You' if self.local_player == 2 else 'Opp'
            score = f'{xlab}(X):{b}   {olab}(O):{w}'
        else:
            score = f'You(X):{b}   AI(O):{w}'
        self.safe_addstr(sy - 1, max(0, (self.w - len(score)) // 2), score,
                         curses.color_pair(3) | curses.A_BOLD)

        for c in range(N):
            self.safe_addstr(sy, board_x + 1 + c * 2, chr(65 + c),
                             curses.color_pair(4))

        top = '┌' + '─' * (gw - 2) + '┐'
        bottom = '└' + '─' * (gw - 2) + '┘'
        self.safe_addstr(sy + 1, board_x, top, curses.color_pair(4))
        self.safe_addstr(sy + 2 + N, board_x, bottom, curses.color_pair(4))

        valid = (self._valid_moves(self.board, self.local_player)
                 if (self.turn == self.local_player and not self.game_over) else {})
        for r in range(N):
            y = sy + 2 + r
            self.safe_addstr(y, sx, f'{r + 1:>2}', curses.color_pair(4))
            for i in range(N + 1):
                self.safe_addstr(y, board_x + i * 2, '│', curses.color_pair(4))
            for c in range(N):
                v = self.board[r][c]
                is_cur = (r == self.cur_r and c == self.cur_c)
                hi = curses.A_REVERSE if is_cur else 0
                if v == 1:
                    ch, attr = 'X', curses.color_pair(1) | curses.A_BOLD | hi
                elif v == 2:
                    ch, attr = 'O', curses.color_pair(2) | curses.A_BOLD | hi
                elif (r, c) in valid:
                    ch, attr = '*', curses.color_pair(3) | hi
                else:
                    ch, attr = '.', curses.color_pair(6) | hi
                self.safe_addstr(y, board_x + 1 + c * 2, ch, attr)

        self.safe_addstr(sy + 3 + N, sx, self.message[:max(0, self.w - sx)],
                         curses.color_pair(3))
        self.draw_status_bar('WASD/Space:Play ?:Help Esc:Quit')

    def get_controls(self):
        return [('WASD/Arrows', 'Move cursor'), ('Space/Enter', 'Place disc'),
                ('ESC', 'Quit / save')]

    def get_stats(self):
        b, w = self._counts()
        if self.net:
            xlab = 'You (X)' if self.local_player == 1 else 'Opponent (X)'
            olab = 'You (O)' if self.local_player == 2 else 'Opponent (O)'
        else:
            xlab, olab = 'You (X)', 'AI (O)'
        stats = [(xlab, b), (olab, w)]
        if b == w:
            stats.append(('Result', 'Draw'))
        return stats

    def get_save_data(self):
        if self.net:
            return None  # never resume a network game
        return {'board': self.board, 'cur_r': self.cur_r, 'cur_c': self.cur_c,
                'turn': self.turn, 'score': self.score, 'message': self.message}
