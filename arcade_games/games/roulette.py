"""Roulette: EUROPEAN single-zero wheel (37 pockets: 0-36).

This is the fairer wheel (house edge 2.70%, vs the American double-zero
wheel's 5.26%), and using it is a deliberate choice, not an accident: the
UI states "EUROPEAN WHEEL" up front. 0 is green and loses every even-money
bet outright (no la partage / en prison rule).

The betting math (payout table, which numbers each bet type covers) lives
in module-level pure data and pure functions, kept separate from the curses
UI class, specifically so the house-edge math can be verified without a
screen. Run this file directly ("python roulette.py") to check every
single generated bet spot -- straight, split, street, corner, six line,
column, dozen, and every even-money bet -- against the exact expected
value of -1/37.
"""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game
from .. import currency

# Not every curses build/shim defines KEY_BACKSPACE (the test suite's fake
# curses among them); 127 (DEL) and 8 (^H) are what a real terminal can send
# instead. Same idiom as blackjack.py's stake-typing input.
_KEY_BACKSPACE = getattr(curses, 'KEY_BACKSPACE', 263) if curses else 263


# ---------------------------------------------------------------------------
# Wheel and payout data
# ---------------------------------------------------------------------------

REDS = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})
BLACKS = frozenset(n for n in range(1, 37) if n not in REDS)

# The real physical European single-zero wheel pocket order (not the table
# layout below). Used only to drive the spin animation, so the ball visibly
# travels around a real wheel sequence instead of a made-up one.
WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8,
               23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12,
               35, 3, 26]

# The felt table layout: 12 columns x 3 rows. TABLE_ROWS[r][c] is the number
# printed at physical row r (0 = top = multiples of 3), column c (0-indexed,
# so column c is the (c+1)-th from the zero end). This is the standard
# layout: row 0 = 3,6,...,36 ; row 1 = 2,5,...,35 ; row 2 = 1,4,...,34.
# Every inside bet (split/street/corner/six line) below is DERIVED from this
# grid by adjacency instead of hand-listed, so a copy-paste slip can't
# silently drop or duplicate a spot.
TABLE_ROWS = [[3 * (c + 1) - r for c in range(12)] for r in range(3)]

PAYOUTS = {
    'straight': 35, 'split': 17, 'street': 11, 'corner': 8, 'sixline': 5,
    'column': 2, 'dozen': 2, 'red': 1, 'black': 1, 'odd': 1, 'even': 1,
    'low': 1, 'high': 1,
}


def is_red(n):
    return n in REDS


def _straight_bets():
    return [{'type': 'straight', 'numbers': (n,), 'label': f'straight {n}'}
            for n in range(0, 37)]


def _split_bets():
    seen = set()
    out = []
    # Horizontal neighbours: same physical row, adjacent columns (differ by 3).
    for r in range(3):
        row = TABLE_ROWS[r]
        for c in range(11):
            pair = tuple(sorted((row[c], row[c + 1])))
            if pair not in seen:
                seen.add(pair)
                out.append({'type': 'split', 'numbers': pair,
                             'label': f'split {pair[0]}/{pair[1]}'})
    # Vertical neighbours: same column, adjacent rows (differ by 1).
    for c in range(12):
        for r in range(2):
            pair = tuple(sorted((TABLE_ROWS[r][c], TABLE_ROWS[r + 1][c])))
            if pair not in seen:
                seen.add(pair)
                out.append({'type': 'split', 'numbers': pair,
                             'label': f'split {pair[0]}/{pair[1]}'})
    # Zero touches the first column only: 0/1, 0/2, 0/3.
    for n in (1, 2, 3):
        pair = tuple(sorted((0, n)))
        out.append({'type': 'split', 'numbers': pair, 'label': f'split 0/{n}'})
    return out


def _street_bets():
    out = []
    for c in range(12):
        nums = tuple(sorted(TABLE_ROWS[r][c] for r in range(3)))
        out.append({'type': 'street', 'numbers': nums,
                     'label': f'street {nums[0]}-{nums[1]}-{nums[2]}'})
    return out


def _corner_bets():
    out = []
    for c in range(11):
        for r in range(2):
            nums = tuple(sorted({TABLE_ROWS[r][c], TABLE_ROWS[r][c + 1],
                                  TABLE_ROWS[r + 1][c], TABLE_ROWS[r + 1][c + 1]}))
            out.append({'type': 'corner', 'numbers': nums,
                         'label': 'corner ' + '-'.join(str(n) for n in nums)})
    return out


def _sixline_bets():
    out = []
    for c in range(11):
        nums = tuple(sorted(list(TABLE_ROWS[r][c] for r in range(3)) +
                             list(TABLE_ROWS[r][c + 1] for r in range(3))))
        out.append({'type': 'sixline', 'numbers': nums,
                     'label': f'six line {nums[0]}-{nums[-1]}'})
    return out


def _column_bets():
    out = []
    for r in range(3):
        nums = tuple(sorted(TABLE_ROWS[r]))
        out.append({'type': 'column', 'numbers': nums,
                     'label': f'column {r + 1} (2 to 1)'})
    return out


def _dozen_bets():
    out = []
    for d in range(3):
        nums = tuple(range(d * 12 + 1, d * 12 + 13))
        out.append({'type': 'dozen', 'numbers': nums,
                     'label': f'dozen {d + 1} ({nums[0]}-{nums[-1]})'})
    return out


def _outside_bets():
    # Display order matches the classic felt reading left to right:
    # Low | Even | Red | Black | Odd | High.
    return [
        {'type': 'low', 'numbers': tuple(range(1, 19)), 'label': 'Low 1-18'},
        {'type': 'even', 'numbers': tuple(n for n in range(1, 37) if n % 2 == 0),
         'label': 'Even'},
        {'type': 'red', 'numbers': tuple(sorted(REDS)), 'label': 'Red'},
        {'type': 'black', 'numbers': tuple(sorted(BLACKS)), 'label': 'Black'},
        {'type': 'odd', 'numbers': tuple(n for n in range(1, 37) if n % 2 == 1),
         'label': 'Odd'},
        {'type': 'high', 'numbers': tuple(range(19, 37)), 'label': 'High 19-36'},
    ]


# (category key, generator) in the order the player cycles through with
# Left/Right. Each generator is called once, in RouletteGame.setup(), and
# cached; calling it again anywhere always yields the identical spot list
# (pure function of the module-level data above), which is exactly what the
# house-edge self-test below relies on.
BET_CATEGORIES = [
    ('straight', _straight_bets), ('split', _split_bets),
    ('street', _street_bets), ('corner', _corner_bets),
    ('sixline', _sixline_bets), ('column', _column_bets),
    ('dozen', _dozen_bets), ('outside', _outside_bets),
]


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

class RouletteGame(Game):
    name = "roulette"
    min_h = 28
    min_w = 66
    supports_difficulty = False
    track_high_score = False  # self.score is a running session net, not a high score

    def setup(self):
        self._categories = [(cat, fn()) for cat, fn in BET_CATEGORIES]
        self.cat_idx = 0
        self.opt_idx = 0
        self.unit = 10
        self.stake_input = None  # None = not typing; str = digits typed so far
        self.bets = []
        self._wheel_pos = 0
        self.spinning = False
        self.last_number = None
        self.rounds_played = 0
        self.session_net = 0
        self.score = 0
        self.message = 'Welcome to European Roulette. Place your bets, then press F to spin.'

        saved = self._load_save(self.name)
        if saved:
            self.bets = [b for b in
                         (self._sanitize_saved_bet(b) for b in saved.get('bets', []))
                         if b is not None]
            self.unit = saved.get('unit', self.unit)
            self._wheel_pos = saved.get('wheel_pos', 0) % 37
            self.session_net = saved.get('session_net', 0)
            self.rounds_played = saved.get('rounds_played', 0)
            self.score = self.session_net
            if self.bets:
                self.message = f'Restored {len(self.bets)} pending bet(s) from last time.'
        self._check_bailout()

    @staticmethod
    def _sanitize_saved_bet(b):
        """Validate one restored bet dict, or return None to drop it.

        Game._load_save's docstring promises that a schema-incompatible
        save is safe because setup() raising while consuming it is caught
        by the run loop, which falls back to a clean re-init. That
        guarantee did NOT hold here: setup() used to accept a malformed
        bet list unconditionally, and a KeyError only fired later --
        inside _do_spin/_resolve_spin (a restored bet missing 'amount', or
        with a 'type' not in PAYOUTS) -- long after the save file had
        already been consumed and deleted, i.e. as a mid-game crash rather
        than a caught setup failure. Validating here, once, at restore
        time, closes that hole: a bet that fails any check is silently
        dropped (the same "best-effort, never crash the resume" contract
        _load_save already promises for the save file as a whole) instead
        of ever reaching betting/spin code that assumes it is well-formed.
        """
        if not isinstance(b, dict):
            return None
        btype = b.get('type')
        if btype not in PAYOUTS:
            return None
        amount = b.get('amount')
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            return None
        numbers = b.get('numbers')
        if not isinstance(numbers, (list, tuple)) or not numbers:
            return None
        clean_numbers = []
        for n in numbers:
            if not isinstance(n, int) or isinstance(n, bool) or not (0 <= n <= 36):
                return None
            clean_numbers.append(n)
        label = b.get('label')
        if not isinstance(label, str):
            label = f'{btype} bet'
        return {'type': btype, 'numbers': tuple(clean_numbers),
                'label': label, 'amount': amount}

    def get_timeout(self):
        return -1  # turn-based: blocks on getch, one action per keypress

    # -- betting engine (pure-ish; only touches currency + self.bets) -------

    def _current_options(self):
        return self._categories[self.cat_idx][1]

    def _current_bet_def(self):
        opts = self._current_options()
        self.opt_idx %= len(opts)
        return opts[self.opt_idx]

    def _check_bailout(self):
        if currency.balance() == 0:
            if currency.bailout_available():
                currency.try_bailout()
                self.message = 'Out of chips: bailout granted, +100 chips to keep playing.'
            else:
                self.message = 'Out of chips. Come back tomorrow for your daily bailout.'

    def _place_bet(self):
        if not currency.bet(self.unit):
            self.message = 'Not enough chips for that bet.'
            return
        bet_def = self._current_bet_def()
        self.bets.append({'type': bet_def['type'], 'numbers': bet_def['numbers'],
                           'label': bet_def['label'], 'amount': self.unit})
        self.message = f"Bet placed: {bet_def['label']} for {self.unit} chips."

    def _undo_last(self):
        if not self.bets:
            return
        b = self.bets.pop()
        currency.payout(b['amount'])
        self.message = f"Removed: {b['label']} (refunded {b['amount']} chips)."

    def _clear_bets(self):
        if not self.bets:
            return
        total = sum(b['amount'] for b in self.bets)
        currency.payout(total)
        self.bets = []
        self.message = f'Cleared all bets (refunded {total} chips).'

    def _resolve_spin(self, number):
        total_win = 0
        for b in self.bets:
            if number in b['numbers']:
                total_win += b['amount'] * (PAYOUTS[b['type']] + 1)
        if total_win:
            currency.payout(total_win)
        self.bets = []
        return total_win

    # Spin animation tuning: a FIXED frame count, so wall-clock duration is
    # constant (~2.1s total: sum(delays) below is 2093ms of curses.napms,
    # plus a few ms of per-frame draw overhead -- measured directly by
    # instrumenting every napms call in a real _do_spin, not eyeballed)
    # regardless of how many pockets the wheel has to visually cross to
    # reach the winning number. The wheel position at frame i is
    # interpolated as a FRACTION of the total travel (see _do_spin), not
    # "+1 pocket per frame" -- advancing by exactly one pocket per frame
    # (the previous approach) tied duration directly to the random
    # distance between the old and new resting pocket, producing spins
    # anywhere from 5.5s to 8.2s (average 6.9s, unskippable except by
    # quitting -- 20 rounds of that is over two minutes of animation
    # nobody could shorten). At ~2.1s/spin, 20 rounds is well under a
    # minute, and any key still fast-forwards straight to the result (see
    # the loop below).
    _SPIN_FRAMES = 54
    _SPIN_DELAY_BASE_MS = 22
    _SPIN_DELAY_RANGE_MS = 51

    def _do_spin(self):
        if not self.bets:
            self.message = 'Place at least one bet before spinning.'
            return
        self.spinning = True
        number = random.randint(0, 36)
        target_idx = WHEEL_ORDER.index(number)
        start_idx = self._wheel_pos
        # Total pockets travelled: always at least two full revolutions (so
        # the wheel visibly spins even when the target sits right next to
        # the start), plus however far around from there to the target.
        travel = 2 * 37 + ((target_idx - start_idx) % 37)
        n = self._SPIN_FRAMES
        # Decelerating frame delays: fast at first, slowing sharply near the
        # end, so the ball visibly settles instead of instantly revealing.
        delays = [int(self._SPIN_DELAY_BASE_MS +
                       self._SPIN_DELAY_RANGE_MS * ((i / (n - 1)) ** 2))
                  for i in range(n)]
        # Not self.animate(): that helper only lets ESC interrupt an
        # animation. Any OTHER key here instead fast-forwards straight to
        # the result -- ESC still quits exactly as it does everywhere else
        # (pushed back for the outer loop's normal handling, not consumed
        # here).
        self.stdscr.nodelay(True)
        try:
            for i, ms in enumerate(delays):
                frac = (i + 1) / n
                self._wheel_pos = (start_idx + round(travel * frac)) % 37
                self.stdscr.erase()
                self.draw()
                self.stdscr.noutrefresh()
                curses.doupdate()
                curses.napms(ms)
                k = self.stdscr.getch()
                if k == -1:
                    continue
                if k == 27:
                    try:
                        curses.ungetch(k)
                    except curses.error:
                        pass
                    break
                break  # any other key: skip the rest of the spin
        finally:
            self.stdscr.timeout(getattr(self, '_poll_ms', -1))
        self._wheel_pos = target_idx

        wagered = sum(b['amount'] for b in self.bets)
        total_win = self._resolve_spin(number)
        self.last_number = number
        self.rounds_played += 1
        self.session_net += (total_win - wagered)
        self.score = self.session_net

        color = 'Green' if number == 0 else ('Red' if is_red(number) else 'Black')
        net = total_win - wagered
        if net > 0:
            self.message = f'{number} ({color})! You won {net} net chips.'
        elif total_win > 0:
            self.message = f'{number} ({color}). Partial return of {total_win} chips.'
        else:
            self.message = f'{number} ({color}). No win this spin.'
        self.spinning = False
        self._check_bailout()

    # -- input ----------------------------------------------------------

    def handle_input(self, key):
        if self.spinning:
            return
        # Letter keys are case-insensitive: the status bar and help overlay
        # both advertise 'R:Undo  C:Clear  F:Spin' (capitalized), but only
        # the lowercase ord() was ever matched below. With CapsLock on (or
        # a shifted key), F (the only way to resolve a spin) did nothing --
        # the player could place bets and then had no way to ever spin.
        if ord('A') <= key <= ord('Z'):
            key += 32

        # Typing a stake takes over all input until it is confirmed or
        # cancelled -- same idiom as Blackjack's bet screen (digits build a
        # number, Enter confirms), applied here to the persistent per-bet
        # stake instead of a one-shot wager.
        if self.stake_input is not None:
            self._input_stake(key)
            return
        if ord('0') <= key <= ord('9'):
            self.stake_input = chr(key)
            self.message = 'Typing stake: press digits, Backspace to edit, Enter to confirm.'
            return

        if key in (curses.KEY_LEFT, ord('a')):
            self.cat_idx = (self.cat_idx - 1) % len(self._categories)
            self.opt_idx = 0
        elif key in (curses.KEY_RIGHT, ord('d')):
            self.cat_idx = (self.cat_idx + 1) % len(self._categories)
            self.opt_idx = 0
        elif key in (curses.KEY_UP, ord('w')):
            self.opt_idx = (self.opt_idx - 1) % len(self._current_options())
        elif key in (curses.KEY_DOWN, ord('s')):
            self.opt_idx = (self.opt_idx + 1) % len(self._current_options())
        elif key in (curses.KEY_ENTER, ord(' '), 10, 13):
            self._place_bet()
        elif key in (ord('+'), ord('=')):
            bal = max(10, currency.balance())
            self.unit = min(self.unit + 10, bal)
        elif key in (ord('-'), ord('_')):
            self.unit = max(10, self.unit - 10)
        elif key == ord('r'):
            self._undo_last()
        elif key == ord('c'):
            self._clear_bets()
        elif key == ord('f'):
            self._do_spin()

    def _input_stake(self, key):
        if key in (_KEY_BACKSPACE, 127, 8):
            self.stake_input = self.stake_input[:-1]
        elif ord('0') <= key <= ord('9') and len(self.stake_input) < 6:
            self.stake_input += chr(key)
        elif key in (curses.KEY_ENTER, ord(' '), 10, 13):
            self._confirm_stake()
        else:
            # Any other key (arrows, r/c/f, +/-...) cancels typing instead
            # of also being actioned -- a stray keypress while typing a
            # number should not silently undo a bet or spin the wheel.
            self.stake_input = None
            self.message = 'Stake entry cancelled; stake unchanged.'

    def _confirm_stake(self):
        typed = self.stake_input
        self.stake_input = None
        if not typed:
            self.message = 'Stake entry cancelled; stake unchanged.'
            return
        amt = int(typed)
        if amt <= 0:
            self.message = 'Stake must be more than 0 chips.'
            return
        bal = currency.balance()
        if bal <= 0:
            self.message = 'No chips to stake.'
            return
        self.unit = min(amt, bal)
        if amt > bal:
            self.message = f'Stake clamped to your balance: {self.unit} chips.'
        else:
            self.message = f'Stake set to {self.unit} chips per bet.'

    # -- drawing ----------------------------------------------------------

    def _draw_wheel_strip(self, y):
        width = 9
        half = width // 2
        cell_w = 5
        strip_w = width * cell_w
        sx = max(1, (self.w - strip_w) // 2)
        ptr_x = sx + half * cell_w + cell_w // 2
        self.safe_addstr(y, ptr_x, 'v', curses.A_BOLD | curses.color_pair(3))
        for i in range(width):
            off = i - half
            idx = (self._wheel_pos + off) % 37
            n = WHEEL_ORDER[idx]
            label = f'{n:^5}'
            if n == 0:
                attr = curses.color_pair(1) | curses.A_BOLD
            elif is_red(n):
                attr = curses.color_pair(2) | curses.A_BOLD
            else:
                attr = curses.color_pair(7) | curses.A_BOLD
            if off == 0:
                attr |= curses.A_REVERSE
            self.safe_addstr(y + 1, sx + i * cell_w, label, attr)
        if self.spinning:
            self.center_text(y + 3, 'SPINNING...', curses.A_BOLD | curses.color_pair(3))
        elif self.last_number is not None:
            color = ('Green' if self.last_number == 0
                     else 'Red' if is_red(self.last_number) else 'Black')
            self.center_text(y + 3, f'Last spin: {self.last_number} ({color})',
                              curses.A_BOLD)
        else:
            self.center_text(y + 3, 'No spins yet this session.', curses.color_pair(4))

    def _draw_table(self, y):
        cell_w = 4
        grid_w = 12 * cell_w
        sx = max(1, (self.w - grid_w) // 2)
        self.sx = sx
        cur = self._current_bet_def()
        cat_name = self._categories[self.cat_idx][0]
        sel = set(cur['numbers'])
        covered = set()
        for b in self.bets:
            covered.update(b['numbers'])

        zattr = curses.color_pair(1) | curses.A_BOLD
        if 0 in sel:
            zattr |= curses.A_REVERSE
        if 0 in covered:
            zattr |= curses.A_UNDERLINE
        self.safe_addstr(y, sx, f'{"0":^4}', zattr)

        for r in range(3):
            yy = y + 1 + r
            for c in range(12):
                n = TABLE_ROWS[r][c]
                x = sx + c * cell_w
                attr = ((curses.color_pair(2) if is_red(n) else curses.color_pair(7))
                        | curses.A_BOLD)
                if n in sel:
                    attr |= curses.A_REVERSE
                if n in covered:
                    attr |= curses.A_UNDERLINE
                self.safe_addstr(yy, x, f'{n:^4}', attr)
            col_attr = curses.color_pair(4)
            if cat_name == 'column' and self.opt_idx == r:
                col_attr |= curses.A_REVERSE
            self.safe_addstr(yy, sx + grid_w + 1, '2:1', col_attr)
        return y + 4  # next free row

    def _draw_dozens(self, y):
        cell_w = 4
        grid_w = 12 * cell_w
        sx = self.sx
        cat_name = self._categories[self.cat_idx][0]
        seg_w = grid_w // 3
        labels = ['1st 12 (1-12)', '2nd 12 (13-24)', '3rd 12 (25-36)']
        for d in range(3):
            x = sx + d * seg_w
            attr = curses.color_pair(4)
            if cat_name == 'dozen' and self.opt_idx == d:
                attr |= curses.A_REVERSE
            self.safe_addstr(y, x, f'{labels[d]:^{seg_w}}', attr)
        return y + 1

    def _draw_outside(self, y):
        cell_w = 4
        grid_w = 12 * cell_w
        sx = self.sx
        cat_name = self._categories[self.cat_idx][0]
        opts = self._categories[[c for c, _ in self._categories].index('outside')][1]
        seg_w = grid_w // 6
        for i, opt in enumerate(opts):
            x = sx + i * seg_w
            attr = curses.color_pair(4)
            if cat_name == 'outside' and self.opt_idx == i:
                attr |= curses.A_REVERSE
            self.safe_addstr(y, x, f'{opt["label"]:^{seg_w}}', attr)
        return y + 1

    def _draw_info(self, y):
        cur = self._current_bet_def()
        ratio = PAYOUTS[cur['type']]
        covers = len(cur['numbers'])
        # Indent from the table's own box, not the raw screen edge: the box
        # is centered within self.w and does not start at column 0, so
        # clamping/positioning against self.w (instead of the box) ran text
        # through the box's left border and past its right border at every
        # terminal width (roulette border bug).
        bx = self.box_x
        bw = self.box_w
        left = bx + 2
        indent = bx + 4
        inner_w = bw - 4
        # Clamp everything below to the box's own last interior row: its
        # bottom border is drawn at box_y + box_h - 1, so this is the last
        # row that is still inside the box. Both a long bet list and a short
        # terminal (down to min_h) can otherwise push the trailing "Session
        # net" / message rows onto or past that border -- this is what
        # keeps the panel from ever overlapping or spilling past the box,
        # at any width or height (the other half of the roulette render bug).
        bottom = self.box_y + self.box_h - 2

        self.safe_addstr(y, left, (f"Selected: {cur['label']}  pays {ratio}:1  "
                                 f"covers {covers} number{'s' if covers != 1 else ''}")[:inner_w],
                          curses.color_pair(3))
        if self.stake_input is not None:
            shown = self.stake_input if self.stake_input else '0'
            stake_line = f'Stake per bet: {shown}_ (typing... Enter to confirm)'
        else:
            stake_line = f'Stake per bet: {self.unit} chips   (+/- adjusts, or type digits)'
        self.safe_addstr(y + 1, left, stake_line[:inner_w], curses.color_pair(4))
        wagered = sum(b['amount'] for b in self.bets)
        self.safe_addstr(y + 2, left,
                          f'Bets placed: {len(self.bets)}   Wagered: {wagered}'[:inner_w],
                          curses.color_pair(4))

        # The trailing "Session net" and message lines (the live wager
        # total and the latest result) matter more than the scrolling
        # per-bet list, so they always get their 2 rows reserved first; the
        # bet list is what shrinks when the terminal is short on room.
        list_start = y + 3
        budget = max(0, bottom - list_start - 1)
        max_lines = min(4, budget)
        if max_lines <= 0:
            shown = []
        elif len(self.bets) <= max_lines:
            shown = self.bets
        elif max_lines == 1:
            shown = []
        else:
            shown = self.bets[-(max_lines - 1):]
        extra = len(self.bets) - len(shown)
        show_extra = extra > 0 and max_lines > 0

        line = list_start
        for b in shown:
            self.safe_addstr(line, indent, f"- {b['label']} : {b['amount']}"[:bw - 6])
            line += 1
        if show_extra:
            self.safe_addstr(line, indent, f'...and {extra} more')
            line += 1

        net_row = min(line, bottom - 1)
        self.safe_addstr(net_row, left,
                          (f'Session net: {self.session_net:+d} chips   '
                           f'Rounds played: {self.rounds_played}')[:inner_w],
                          curses.A_BOLD)
        self.safe_addstr(min(net_row + 1, bottom), left,
                          self.message[:max(0, inner_w)],
                          curses.color_pair(3) | curses.A_BOLD)

    def draw(self):
        self.center_text(0, ' ROULETTE - EUROPEAN WHEEL (0-36, single zero) ',
                          curses.A_BOLD | curses.A_REVERSE)
        box_w = min(self.w - 2, 62)
        box_h = max(20, self.h - 3)
        box_x = max(1, (self.w - box_w) // 2)
        self.box_x = box_x
        self.box_w = box_w
        self.box_y = 1
        self.box_h = box_h
        self.draw_box(1, box_x, box_h, box_w, curses.color_pair(1) | curses.A_BOLD)
        self._draw_wheel_strip(2)
        y = self._draw_table(7)
        y = self._draw_dozens(y + 1)
        y = self._draw_outside(y)
        self._draw_info(y + 2)
        if self.stake_input is not None:
            self.draw_status_bar(
                [f'Chips:{currency.balance()}', '0-9:Digit', 'Backspace:Edit',
                 'Enter:Confirm stake', 'Esc:Quit'])
        else:
            # render.status_bar keeps the escape hatches (Esc/Help) first no
            # matter where they sit in this list, then fills the rest
            # GREEDILY IN THIS LIST'S ORDER until the terminal width runs
            # out -- so whatever is listed LAST is the first thing dropped
            # on a narrow terminal. F:Spin is the only key that resolves a
            # round; it (and R:Undo/C:Clear) must come before the
            # lower-value selection/stake hints, not after them, or a
            # normal 66-100 column terminal shows a betting screen with no
            # visible way to ever spin (roulette-13).
            self.draw_status_bar(
                [f'Chips:{currency.balance()}', 'F:Spin', 'Enter:Bet',
                 'R:Undo', 'C:Clear', 'Arrows:Select', '+/-:Stake',
                 '0-9:Type stake', '?:Help', 'Esc:Quit'])

    def get_controls(self):
        return [
            ('Left/Right', 'Change bet category'),
            ('Up/Down', 'Change bet selection'),
            ('Enter/Space', 'Place the selected bet'),
            ('+/-', 'Adjust stake per bet by 10'),
            ('0-9', 'Type an exact stake, then Enter to confirm'),
            ('R', 'Undo last bet (refund)'),
            ('C', 'Clear all bets (refund)'),
            ('F', 'Spin the wheel (any key skips the animation)'),
            ('ESC', 'Quit (pending bets are saved)'),
        ]

    def get_stats(self):
        return [('Rounds played', self.rounds_played),
                ('Session net chips', self.session_net),
                ('Chip balance', currency.balance())]

    def get_save_data(self):
        # Bets already debit chips at placement time (see _place_bet), so a
        # bet still pending at quit time represents chips already taken from
        # the balance and not yet returned to it: preserve it so relaunching
        # restores those chips to play instead of them silently vanishing
        # from the ledger. (Chips are virtual points with no worth outside
        # this process; nothing here is a stake of real value.) Nothing to
        # save (return None) once there are no pending bets, so a clean
        # session leaves no stale save file.
        if not self.bets:
            return None
        return {'bets': [dict(b) for b in self.bets], 'unit': self.unit,
                'wheel_pos': self._wheel_pos, 'session_net': self.session_net,
                'rounds_played': self.rounds_played, 'score': self.score}


# ---------------------------------------------------------------------------
# House-edge self-test: pure math, no curses required. Every single bet spot
# generated above (all 37 straights, all 60 splits, all 12 streets, all 22
# corners, all 11 six lines, all 3 columns, all 3 dozens, and all 6
# even-money bets) is checked against the exact expected value of -1/37. If
# any payout in PAYOUTS is wrong, or if a generator over/under-covers a bet
# spot, this catches it.
# ---------------------------------------------------------------------------

def _expected_value(bet, amount=1):
    """Exact EV of net profit for one spin of `amount` chips on `bet`,
    computed by enumerating all 37 equally likely pockets (not simulated)."""
    ratio = PAYOUTS[bet['type']]
    covers = len(bet['numbers'])
    wins = covers
    losses = 37 - covers
    return amount * (wins * ratio - losses) / 37.0


def _all_bets():
    out = []
    for _cat, fn in BET_CATEGORIES:
        out.extend(fn())
    return out


def _run_house_edge_test(verbose=False):
    expected = -1.0 / 37.0
    bets = _all_bets()
    counts = {}
    for bet in bets:
        # Every number in a bet's coverage must be a real pocket, 0-36,
        # with no duplicates (a duplicate would silently inflate coverage
        # and skew the EV without necessarily failing the numeric check).
        nums = bet['numbers']
        assert len(nums) == len(set(nums)), bet
        assert all(0 <= n <= 36 for n in nums), bet
        ev = _expected_value(bet, amount=1)
        assert abs(ev - expected) < 1e-9, (bet, ev, expected)
        counts[bet['type']] = counts.get(bet['type'], 0) + 1

    expected_counts = {
        'straight': 37, 'split': 60, 'street': 12, 'corner': 22,
        'sixline': 11, 'column': 3, 'dozen': 3,
        'low': 1, 'high': 1, 'red': 1, 'black': 1, 'odd': 1, 'even': 1,
    }
    assert counts == expected_counts, (counts, expected_counts)

    # Sanity checks on the color/parity data itself.
    assert len(REDS) == 18 and len(BLACKS) == 18
    assert REDS.isdisjoint(BLACKS)
    assert REDS | BLACKS | {0} == set(range(37))

    if verbose:
        print(f'OK: {len(bets)} distinct bet spots, all -1/37 EV.')
        for t, n in sorted(counts.items()):
            print(f'  {t:>9}: {n} spots, pays {PAYOUTS[t]}:1')
    return len(bets)


if __name__ == '__main__':
    _run_house_edge_test(verbose=True)
