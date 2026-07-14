"""Slot machine: 3 reels, weighted symbols, a paytable, and a computed RTP.

The symbol set, per-reel weights, and paytable are all defined up front as
module-level constants, and the resulting Return To Player (RTP) is computed
EXACTLY below by enumerating all 6**3 = 216 reel outcomes and weighting each
one by its true probability -- not by simulation. A slot machine whose RTP
was not computed is a slot machine whose RTP is wrong (SPEC4.md section 5),
so the computation runs, and is asserted into the required 92%-96% band, at
import time: if a future edit ever pushes the RTP out of band, importing
this module fails loudly instead of shipping a silently-broken machine.
"""
import random

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games
    # need it (install `windows-curses`), but the turn-based `play cli` mode
    # and all text commands must still work without it, so we degrade
    # gracefully, same as every other game module.
    curses = None

from ..game import Game
from .. import currency
from .. import render

# --- Symbols, reel weights and paytable, defined up front --------------
# Every reel (all 3) draws independently from this same weighted
# distribution. Ordered rarest-last only for readability; DIAMOND (weight 1
# of 31) is the jackpot symbol.
SYMBOLS = ('CHERRY', 'LEMON', 'BELL', 'STAR', 'SEVEN', 'DIAMOND')

WEIGHTS = {
    'CHERRY': 10,
    'LEMON': 8,
    'BELL': 6,
    'STAR': 4,
    'SEVEN': 2,
    'DIAMOND': 1,
}
_TOTAL_WEIGHT = sum(WEIGHTS[s] for s in SYMBOLS)

# Payout multipliers are the TOTAL return on the wager (stake included), so
# a winning spin is `currency.payout(bet * multiplier)`; a losing spin pays
# nothing further (the bet was already debited by currency.bet() before the
# reels ever turned).
PAY3 = {
    'CHERRY': 5,
    'LEMON': 8,
    'BELL': 16,
    'STAR': 28,
    'SEVEN': 60,
    'DIAMOND': 300,   # the jackpot
}
# A small consolation for exactly two cherries landing (any two of the three
# reels, the third reel something else). This is the only partial-match
# payout: it exists to smooth the payout curve the way SPEC4.md suggests,
# not to pay every near-miss.
PAY2_CHERRY = 2

# Unicode glyph plus a plain-ASCII fallback for each symbol. These symbols
# are not entries in render.GLYPHS (this file may only touch slots.py, not
# render.py), so the fallback is chosen locally -- but it is driven by the
# exact same render.ascii_mode flag that the rest of the app's glyph
# fallback mechanism uses, set by the same startup probe / self-healing
# UnicodeEncodeError handler in render.safe_addstr. See _symbol_glyph().
_GLYPH = {
    'CHERRY':  ('♥', 'c'),   # heart (stands in for a pair of cherries)
    'LEMON':   ('●', 'o'),   # filled circle
    'BELL':    ('◈', 'B'),   # diamond-in-diamond
    'STAR':    ('★', '*'),
    'SEVEN':   ('7', '7'),
    'DIAMOND': ('♦', 'D'),
}
# color_pair id per symbol (theme.py: 1 GREEN, 2 RED, 3 YELLOW, 4 CYAN,
# 5 MAGENTA, 6 BLUE, 7 WHITE).
_COLOR = {
    'CHERRY': 2, 'LEMON': 3, 'BELL': 5, 'STAR': 4, 'SEVEN': 1, 'DIAMOND': 6,
}


def _symbol_glyph(sym):
    uni, ascii_fallback = _GLYPH[sym]
    return ascii_fallback if render.ascii_mode else uni


def payout_multiplier(combo):
    """The paytable, as a pure function of the 3 landed symbols (a, b, c).
    Module-level so both the game and compute_rtp() below call the exact
    same rule -- the RTP computed is guaranteed to be the RTP actually
    paid out."""
    a, b, c = combo
    if a == b == c:
        return PAY3[a]
    if combo.count('CHERRY') == 2:
        return PAY2_CHERRY
    return 0


def compute_rtp():
    """Exact RTP: enumerate every one of the 6**3 = 216 reel outcomes (each
    reel independent, identically weighted per WEIGHTS above), weight each
    by its true probability, and sum probability * payout multiplier. This
    walks the entire outcome space exactly; it is not a simulation and
    carries no sampling error."""
    total = 0.0
    prob_sum = 0.0
    for a in SYMBOLS:
        pa = WEIGHTS[a] / _TOTAL_WEIGHT
        for b in SYMBOLS:
            pb = WEIGHTS[b] / _TOTAL_WEIGHT
            for c in SYMBOLS:
                pc = WEIGHTS[c] / _TOTAL_WEIGHT
                p = pa * pb * pc
                prob_sum += p
                total += p * payout_multiplier((a, b, c))
    assert abs(prob_sum - 1.0) < 1e-9, \
        'reel outcome probabilities must sum to 1'
    return total


# Computed once, at import time, and asserted into the required band right
# here -- see the module docstring.
RTP = compute_rtp()
assert 0.92 <= RTP <= 0.96, \
    f'slots RTP {RTP:.4f} is out of the required 92%-96% band'


class SlotsGame(Game):
    name = 'slots'
    min_h = 18
    min_w = 44
    supports_difficulty = False
    # A slot machine has no win/loss end state the way an arcade game does
    # (you play until you choose to stop); "biggest self.score ever" has no
    # natural meaning here, so this opts out the same way Minesweeper does
    # for its own reason (see game.py's track_high_score docstring).
    track_high_score = False

    BET_STEP = 5
    BET_MIN = 5
    BET_MAX_CAP = 100  # a single bet is also always clamped to the balance

    # Per-reel stop animation: cycling delays that decelerate into the
    # landed symbol. Three reels play this in sequence, left to right, each
    # one locking before the next starts spinning -- the near-miss tension
    # of watching the third reel is the entire feel of a slot machine, so
    # there is no instant reveal anywhere in this file.
    _SPIN_DELAYS_MS = (60, 60, 70, 80, 100, 130, 170, 220)

    def setup(self):
        self.bet_amount = self.BET_MIN
        self.reels = list(random.sample(SYMBOLS, 3))
        self.spinning = False
        self.spins = 0
        self.total_wagered = 0
        self.total_won = 0
        self.best_win = 0
        self.last_result = None  # None | 'win' | 'lose'
        self.message = 'SPACE to spin. Left/Right to change your bet.'
        self._maybe_bailout()

    def get_timeout(self):
        return -1  # turn based: blocks between spins, animate() drives the reels

    def _maybe_bailout(self):
        """Auto-grant the once-a-day bailout the instant it becomes
        available (balance is 0 and today's bailout hasn't fired yet), so a
        player can never be stuck staring at a machine they cannot play.
        Returns True (and overwrites self.message) only when it actually
        granted chips."""
        if currency.balance() == 0 and currency.bailout_available():
            currency.try_bailout()
            self.message = (f'You were out of chips: bailout granted '
                             f'+{currency.BAILOUT_AMOUNT}. Spin again!')
            return True
        return False

    def _clamp_bet(self):
        bal = currency.balance()
        cap = min(self.BET_MAX_CAP, bal) if bal > 0 else self.BET_MIN
        cap = max(self.BET_MIN, cap)
        if self.bet_amount > cap:
            self.bet_amount = cap
        if self.bet_amount < self.BET_MIN:
            self.bet_amount = self.BET_MIN

    def handle_input(self, key):
        if self.spinning or self.game_over:
            return
        if key in (curses.KEY_LEFT, ord('a'), ord('-'), ord('_')):
            self.bet_amount = max(self.BET_MIN, self.bet_amount - self.BET_STEP)
        elif key in (curses.KEY_RIGHT, ord('d'), ord('+'), ord('=')):
            self.bet_amount += self.BET_STEP
            self._clamp_bet()
        elif key in (curses.KEY_ENTER, ord(' '), 10, 13):
            self._spin()

    def _spin(self):
        self._clamp_bet()
        if currency.balance() == 0:
            if not self._maybe_bailout():
                self.message = 'Out of chips. Come back tomorrow for a bailout.'
            return
        bet = min(self.bet_amount, currency.balance())
        if not currency.bet(bet):
            self.message = 'Not enough chips for that bet.'
            return

        self.spinning = True
        self.spins += 1
        self.total_wagered += bet
        self.last_result = None
        self.message = 'Spinning...'

        final = [random.choices(SYMBOLS, weights=[WEIGHTS[s] for s in SYMBOLS])[0]
                 for _ in range(3)]

        # Stop the reels one at a time, left to right. Each phase spins
        # every reel from reel_idx onward (so reels waiting their turn keep
        # visibly turning), and locks exactly reel_idx on the final frame.
        for reel_idx in range(3):
            delays = self._SPIN_DELAYS_MS
            n = len(delays)
            frame_no = 0
            for _ in self.animate(delays):
                frame_no += 1
                is_last_frame = frame_no == n
                for j in range(reel_idx, 3):
                    if j == reel_idx and is_last_frame:
                        self.reels[j] = final[reel_idx]
                    else:
                        self.reels[j] = random.choice(SYMBOLS)
                self.stdscr.erase()
                self.draw()
            self.reels[reel_idx] = final[reel_idx]

        mult = payout_multiplier(tuple(final))
        win = bet * mult
        if win > 0:
            currency.payout(win)
            self.total_won += win
            self.best_win = max(self.best_win, win)
            self.score = self.best_win
            self.last_result = 'win'
            if mult >= PAY3['DIAMOND']:
                self.message = f'JACKPOT!!! Three Diamonds pays {win} chips!'
            else:
                self.message = f'Winner! {win} chips ({mult}x your bet).'
        else:
            self.last_result = 'lose'
            if len(set(final)) == 2:
                self.message = 'So close! No win this spin.'
            else:
                self.message = 'No win. Spin again.'

        self.spinning = False
        self._maybe_bailout()  # covers "just went broke on that losing spin"

    def draw(self):
        title = ' SLOT MACHINE '
        self.safe_addstr(1, max(0, (self.w - len(title)) // 2), title,
                         curses.A_BOLD | curses.A_REVERSE)

        # Kept deliberately compact (short unicode box-drawing runs): a
        # single wide addstr call of many consecutive box-drawing
        # characters has been observed to render incompletely on some real
        # consoles once the run gets long, so the whole machine is built
        # from short per-cell borders instead of one large one.
        cell_w = 5
        gap = 1
        n = 3
        reels_w = cell_w * n + gap * (n - 1)
        machine_w = reels_w + 4  # borders + a 1-col gap + a 1-col lever
        machine_h = 7
        mx = max(0, (self.w - machine_w) // 2)
        my = 3

        self.draw_box(my, mx, machine_h, machine_w, curses.color_pair(4) | curses.A_BOLD)

        reels_x = mx + 1
        reel_y = my + 2
        flash = self.last_result == 'win' and not self.spinning
        for i in range(3):
            rx = reels_x + i * (cell_w + gap)
            box_attr = curses.color_pair(4)
            if flash:
                box_attr |= curses.A_BOLD
            self.draw_box(reel_y - 1, rx, 3, cell_w, box_attr)
            sym = self.reels[i]
            glyph = _symbol_glyph(sym)
            attr = curses.color_pair(_COLOR[sym]) | curses.A_BOLD
            if flash:
                attr |= curses.A_REVERSE
            gx = rx + (cell_w - len(glyph)) // 2
            self.safe_addstr(reel_y, gx, glyph, attr)

        # Decorative lever, purely for identity: a small handle to the right
        # of the reel bank. safe_addstr already runs '|' through the glyph
        # fallback table on its own; the ball uses a plain ASCII char so it
        # needs no fallback at all.
        lever_x = mx + machine_w - 2
        self.safe_addstr(my + 1, lever_x, '│', curses.color_pair(7))
        self.safe_addstr(my + 2, lever_x, 'O', curses.color_pair(2) | curses.A_BOLD)
        self.safe_addstr(my + 3, lever_x, '│', curses.color_pair(7))

        info_y = my + machine_h + 1
        bet_line = f'Bet: {self.bet_amount}   Balance: {currency.balance()} chips'
        self.safe_addstr(info_y, max(0, (self.w - len(bet_line)) // 2), bet_line,
                         curses.color_pair(3) | curses.A_BOLD)

        msg_attr = curses.color_pair(1) if self.last_result == 'win' else curses.color_pair(4)
        msg = self.message[:max(0, self.w - 2)]
        self.safe_addstr(info_y + 2, max(0, (self.w - len(msg)) // 2), msg, msg_attr)

        stats_line = (f'Spins: {self.spins}   Wagered: {self.total_wagered}   '
                      f'Won: {self.total_won}   Best win: {self.best_win}')
        stats_line = stats_line[:max(0, self.w - 2)]
        self.safe_addstr(info_y + 4, max(0, (self.w - len(stats_line)) // 2),
                         stats_line, curses.color_pair(6))

        # A raw f-string bypasses render.status_bar's segment-preserving
        # fit entirely (it only kicks in for a list/tuple -- see its
        # docstring), so the bar was clipped character-wise: at this
        # game's own min_w=44 it rendered chopped mid-token with BOTH
        # escape hatches ('?:Help' and 'Esc:Quit') gone and no way to quit
        # or get help. Slots was the only one of these games still passing
        # a string instead of a list.
        # Space:Spin (the key that actually resolves a round) is listed
        # before the lower-value Left/Right:Bet hint, so on a narrow
        # terminal (or a large chip balance eating into the budget) it is
        # Left/Right:Bet that gets dropped first, not the spin key --
        # matching the priority fix applied to Roulette's F:Spin.
        self.draw_status_bar([f'Chips:{currency.balance()}', 'Space:Spin',
                               'Left/Right:Bet', '?:Help', 'Esc:Quit'])

    def get_controls(self):
        pay_lines = [(f'{_symbol_glyph(s)} x3', f'pays {PAY3[s]}x bet') for s in SYMBOLS]
        pay_lines.append((f'{_symbol_glyph("CHERRY")} x2', f'pays {PAY2_CHERRY}x bet'))
        return [
            ('Left/Right', 'Change bet'),
            ('Space/Enter', 'Spin'),
            ('ESC', 'Quit'),
        ] + pay_lines

    def get_stats(self):
        return [
            ('Spins', self.spins),
            ('Total wagered', self.total_wagered),
            ('Total won', self.total_won),
            ('Best single win', self.best_win),
            ('Balance', currency.balance()),
        ]
