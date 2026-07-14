"""Connect Four (full-screen, single-player + LAN)."""
try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class ConnectFourGame(Game):
    name = "connect4"
    min_h = 18
    min_w = 34
    ROWS, COLS = 6, 7

    def setup(self):
        self.net = getattr(self, 'net', None)
        self.local_player = getattr(self, 'local_player', 1)
        # Transient fall-animation state: which column/row/player is
        # currently mid-drop, drawn by draw() but not yet committed to
        # self.board. None/-1 when nothing is animating.
        self.anim_col = None
        self.anim_row = -1
        self.anim_player = None
        saved = self._load_save(self.name) if not self.net else None
        if saved:
            self.board = saved['board']
            self.cursor = saved['cursor']
            self.turn = saved['turn']
            self.score = saved['score']
            self.message = saved.get('message', '')
            lm = saved.get('last_move')
            self.last_move = tuple(lm) if lm else None
            self.win_cells = None
            return
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.cursor = self.COLS // 2
        self.turn = 1
        self.score = 0
        self.message = ''
        self.last_move = None
        self.win_cells = None

    def get_timeout(self):
        return 120 if self.net else -1  # net games poll; local games block

    def _drop_row(self, col):
        for r in range(self.ROWS - 1, -1, -1):
            if self.board[r][col] == 0:
                return r
        return -1

    def _winning_cells(self, player):
        b, R, C = self.board, self.ROWS, self.COLS
        for r in range(R):
            for c in range(C - 3):
                if all(b[r][c + i] == player for i in range(4)):
                    return [(r, c + i) for i in range(4)]
        for r in range(R - 3):
            for c in range(C):
                if all(b[r + i][c] == player for i in range(4)):
                    return [(r + i, c) for i in range(4)]
        for r in range(R - 3):
            for c in range(C - 3):
                if all(b[r + i][c + i] == player for i in range(4)):
                    return [(r + i, c + i) for i in range(4)]
        for r in range(R - 3):
            for c in range(3, C):
                if all(b[r + i][c - i] == player for i in range(4)):
                    return [(r + i, c - i) for i in range(4)]
        return None

    def _place_with_animation(self, col, player):
        """Drop `player`'s disc into `col`: animate an accelerating fall
        (self.animate is a no-op pass over the net, so this never blocks a
        LAN peer), then commit it to the board and resolve the turn."""
        row = self._drop_row(col)
        if row < 0:
            return False
        self.anim_col = col
        self.anim_player = player
        delays = [max(25, 70 - i * 9) for i in range(row + 1)]  # accelerating fall
        i = 0
        for _ in self.animate(delays):
            self.anim_row = i
            self.stdscr.erase()
            self.draw()
            i += 1
        self.anim_col = None
        self.anim_row = -1
        self.board[row][col] = player
        self.last_move = (row, col)
        self._resolve(player)
        # The run loop erases the screen once per keypress, before
        # handle_input()/update() run, then does one final unconditional
        # draw() of its own WITHOUT erasing again. animate() above already
        # did several of its own erase+draw+doupdate cycles reflecting the
        # PRE-resolve state (mid-fall, old turn/message), so without this
        # the loop's trailing draw() would paint the new (differently
        # sized) status text straight over the stale text left on screen
        # instead of onto a blank one, leaving overlapping characters.
        self.stdscr.erase()
        self.draw()
        self.stdscr.noutrefresh()
        curses.doupdate()
        return True

    def _resolve(self, player):
        win = self._winning_cells(player)
        if win:
            self.game_over = True
            self.win_cells = win
            self.won = (player == self.local_player)
            self.score = 1 if self.won else 0
            self.message = 'You win!' if self.won else 'You lose'
        elif all(self.board[0][c] != 0 for c in range(self.COLS)):
            self.game_over = True
            self.tied = True
            self.message = "It's a draw!"
        else:
            self.turn = 3 - player
            self.message = ''

    def _attempt_drop(self, col):
        if not self._my_turn():
            return
        if self.board[0][col] != 0:
            self.message = 'Column full'
            try:
                curses.beep()
            except curses.error:
                pass
            return
        self.message = ''
        self._place_with_animation(col, self.local_player)
        if self.net:
            self.net.send({'type': 'drop', 'col': col})

    def handle_input(self, key):
        if self.game_over:
            return
        if key in (curses.KEY_LEFT, ord('a')):
            self.cursor = (self.cursor - 1) % self.COLS
            self.message = ''
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.cursor = (self.cursor + 1) % self.COLS
            self.message = ''
        elif key in (curses.KEY_ENTER, ord(' '), 10, 13):
            self._attempt_drop(self.cursor)
        elif ord('1') <= key <= ord('7') and key - ord('1') < self.COLS:
            self.cursor = key - ord('1')
            self._attempt_drop(self.cursor)

    def update(self):
        if self.net:
            self.net_pump()
            return
        if self.game_over:
            return
        opp = 3 - self.local_player
        if self.turn == opp:  # single-player AI
            for _ in self.animate((300,)):  # think pause; draw() shows "AI is thinking..."
                self.stdscr.erase()
                self.draw()
            col = self._cli_c4_ai_move(self.board)
            if col >= 0:
                self._place_with_animation(col, opp)

    def net_pump(self):
        if not self.net:
            return
        if not self.net.alive:
            if not self.game_over:
                self.game_over = True
                self.message = 'Opponent disconnected'
            return
        if self.game_over:
            self.net.pump()  # keep heartbeats flowing while the banner is up
            return
        # Poll unconditionally, every call, instead of only `if self.turn ==
        # opp`: the old gate meant NOTHING touched the socket (not even a
        # heartbeat) while it was your own turn, so the peer's receive-
        # silence timer ran out and declared you disconnected the moment
        # you took more than _PEER_TIMEOUT (8s) to pick a column (c4-8 /
        # NET-2 / NET-3). Polling every call is safe; APPLYING a 'drop' is
        # not, unless it is still actually the opponent's turn. A malicious
        # or buggy peer can send extra 'drop' frames back to back, and
        # without a turn check here each one lands, letting one side place
        # multiple discs in a row and desync the board from the peer.
        msg = self.net.poll()
        if msg and msg.get('type') == 'drop':
            opp = 3 - self.local_player
            if self.turn == opp:
                col = msg.get('col')
                if isinstance(col, int) and 0 <= col < self.COLS and self.board[0][col] == 0:
                    self._place_with_animation(col, opp)

    @staticmethod
    def _cli_c4_ai_move(board):
        from ..cli import _cli_c4_ai_move
        return _cli_c4_ai_move(board)

    def draw(self):
        gw = self.COLS * 4 + 1
        sx = max(0, (self.w - gw) // 2)
        # content_h covers title + column arrows/numbers + the grid + the
        # status line: 3 + (ROWS*2 + 1) + 1 = 2*ROWS + 5. The control hint
        # lives on its own pinned status bar row, not counted here, so
        # nothing overlaps it even at min_h (c4-9).
        content_h = self.ROWS * 2 + 5
        sy = max(0, (self.h - 1 - content_h) // 2)
        title = ' CONNECT FOUR '
        self.safe_addstr(sy, max(0, (self.w - len(title)) // 2), title,
                         curses.A_BOLD | curses.A_REVERSE)
        for c in range(self.COLS):
            cx = sx + 2 + c * 4
            full = self.board[0][c] != 0
            is_cur = c == self.cursor and not self.game_over and self._my_turn()
            if is_cur and not full:
                self.safe_addstr(sy + 1, cx, 'v',
                                 curses.color_pair(3) | curses.A_BOLD)
            elif is_cur and full:
                # A full-column cursor used to draw nothing here at all, so
                # the player had no on-screen indication of where the
                # cursor even was while it sat on a full column.
                self.safe_addstr(sy + 1, cx, 'x', curses.color_pair(2))
            self.safe_addstr(sy + 2, cx, str(c + 1), curses.color_pair(4))
        top = sy + 3
        self.safe_addstr(top, sx, '┌' + '───┬' * (self.COLS - 1) + '───┐')
        win_set = set(self.win_cells) if self.win_cells else set()
        for r in range(self.ROWS):
            ry = top + 1 + r * 2
            self.safe_addstr(ry, sx, '│' + '   │' * self.COLS)
            for c in range(self.COLS):
                cx = sx + 2 + c * 4
                if self.anim_col == c and r == self.anim_row:
                    ch = 'X' if self.anim_player == 1 else 'O'
                    attr = (curses.color_pair(2) if self.anim_player == 1
                            else curses.color_pair(3)) | curses.A_BOLD
                    self.safe_addstr(ry, cx, ch, attr)
                    continue
                v = self.board[r][c]
                if v == 0:
                    continue
                ch = 'X' if v == 1 else 'O'
                attr = (curses.color_pair(2) if v == 1 else curses.color_pair(3)) | curses.A_BOLD
                if (r, c) in win_set:
                    attr |= curses.A_REVERSE  # winning four highlighted (c4-6)
                elif self.last_move == (r, c):
                    attr |= curses.A_UNDERLINE  # most recent disc distinguished (c4-6)
                self.safe_addstr(ry, cx, ch, attr)
            mid = ('├' + '───┼' * (self.COLS - 1) + '───┤'
                   if r < self.ROWS - 1 else
                   '└' + '───┴' * (self.COLS - 1) + '───┘')
            self.safe_addstr(ry + 1, sx, mid)
        status = self._status()
        self.safe_addstr(top + self.ROWS * 2 + 1,
                         max(0, (self.w - len(status)) // 2), status,
                         curses.color_pair(3) | curses.A_BOLD)
        self.draw_status_bar('1-7:Col Spc:Drop ?:Help Esc:Quit')

    def _game_over_box_pos(self, box_h, box_w):
        # Dead center (the base class default) blanks out most of a 6-row
        # board, hiding the winning four the player just needs to see
        # (c4-2). The board itself is only gw columns wide and centered
        # independently of the banner; when the terminal has enough spare
        # width beside it, put the banner there instead of on top of it.
        gw = self.COLS * 4 + 1
        board_sx = max(0, (self.w - gw) // 2)
        board_right = board_sx + gw
        free = self.w - board_right
        if free >= box_w:
            sx = board_right + max(0, (free - box_w) // 2)
            sy = max(0, (self.h - box_h) // 2)
            return sy, sx
        return super()._game_over_box_pos(box_h, box_w)

    def _protected_cells(self):
        """Overrides Game._protected_cells(): the exact (row, col) screen
        cell of each winning disc, using the same layout math as draw().
        Below ~80 columns (and always at the game's own declared min_w=34)
        there is not enough spare width beside the board for
        _game_over_box_pos to relocate the banner clear of it (the board
        alone is 29 columns wide, leaving as little as 3 spare at min_w), so
        relocation alone cannot keep the winning four on screen. Protecting
        these exact cells so the base class's banner is drawn around them,
        instead, fixes it at every terminal size, not just the wide ones
        (c4-2, SILENCED then REJECTED before this fix)."""
        if not self.win_cells:
            return frozenset()
        gw = self.COLS * 4 + 1
        board_sx = max(0, (self.w - gw) // 2)
        content_h = self.ROWS * 2 + 5
        sy = max(0, (self.h - 1 - content_h) // 2)
        top = sy + 3
        return {(top + 1 + r * 2, board_sx + 2 + c * 4)
                for r, c in self.win_cells}

    def _my_turn(self):
        return self.turn == self.local_player

    def _my_symbol(self):
        return 'X' if self.local_player == 1 else 'O'

    def _opp_symbol(self):
        return 'O' if self.local_player == 1 else 'X'

    def _status(self):
        if self.game_over:
            return self.message or 'Game over'
        if self.message:
            return self.message
        my_sym = self._my_symbol()
        if self.net:
            return (f'Your turn ({my_sym})' if self._my_turn()
                    else f"Opponent's turn ({self._opp_symbol()})...")
        return f'Your turn ({my_sym})' if self.turn == 1 else 'AI is thinking...'

    def get_controls(self):
        return [('A/D or 1-7', 'Choose/drop column'), ('Space/Enter', 'Drop disc'),
                ('ESC', 'Quit')]

    def get_stats(self):
        return []

    def get_save_data(self):
        if self.net:
            return None  # never resume a network game
        return {'board': self.board, 'cursor': self.cursor, 'turn': self.turn,
                'score': self.score, 'message': self.message,
                'last_move': list(self.last_move) if self.last_move else None}
