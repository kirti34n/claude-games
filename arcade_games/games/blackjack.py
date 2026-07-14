"""Blackjack. 6-deck shoe, dealer stands on all 17 (including soft 17),
blackjack pays 3:2, insurance pays 2:1, split up to 3 times (4 hands), and
split aces get exactly one card each with a 21 on a split ace paying 1:1
(NOT a blackjack) -- the rule most implementations botch.

Chips are the shared virtual currency (arcade_games.currency); nothing here
adds a purchase, deposit, withdrawal, or cash-out path. See SPEC4.md
sections 0 and 7.
"""
import random

try:
    import curses
except ImportError:
    curses = None

from ..game import Game
from .. import render
from .. import currency

# Not every curses build/shim defines KEY_BACKSPACE (the test suite's fake
# curses module does not), so fall back to the standard ncurses code (263)
# rather than raising AttributeError the first time the bet screen reads a
# key. 127/8 (DEL/^H) are also checked directly wherever this is used, since
# a real terminal can send either instead of KEY_BACKSPACE.
_KEY_BACKSPACE = getattr(curses, 'KEY_BACKSPACE', 263) if curses else 263

RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
# (unicode symbol, ascii fallback, is_red). Suit symbols are not part of the
# shared render.GLYPHS table (that table only covers box-drawing/block
# glyphs), so the ascii fallback is handled locally here, gated on the same
# render.ascii_mode flag every other game's glyph fallback ultimately
# resolves to.
_SUITS = [('♥', 'H', True), ('♦', 'D', True),
          ('♣', 'C', False), ('♠', 'S', False)]
NUM_DECKS = 6
# Reshuffle once the shoe has been dealt down to 25% of its starting size,
# i.e. after ~75% penetration. Checked between rounds, never mid-hand.
_PENETRATION_RESHUFFLE_FRACTION = 0.25
MAX_SPLITS = 3  # up to 3 splits -> 4 hands


def _base_value(rank):
    if rank == 'A':
        return 11
    if rank in ('J', 'Q', 'K'):
        return 10
    return int(rank)


def hand_value(cards):
    """(total, is_soft). is_soft is True while an Ace is still being
    counted as 11 in the returned total (i.e. counting it as 1 instead
    would lower the total)."""
    total = sum(_base_value(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == 'A')
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total, aces > 0


def _is_blackjack(hand):
    """A natural blackjack: the ORIGINAL two-card hand (never a hand that
    resulted from a split, including a split-ace hand) totalling 21. This is
    the rule most implementations botch: a 21 reached on any split hand,
    aces included, is an ordinary 21 that pays 1:1, not a blackjack."""
    return (len(hand.cards) == 2 and not hand.from_split
            and hand_value(hand.cards)[0] == 21)


class PlayerHand:
    def __init__(self, cards, bet, from_split=False, split_aces=False):
        self.cards = list(cards)
        self.bet = bet
        self.from_split = from_split
        self.split_aces = split_aces
        self.doubled = False
        self.stood = False
        self.busted = False
        self.result = None  # None, 'blackjack', 'win', 'push', 'lose'


class Shoe:
    def __init__(self, num_decks=NUM_DECKS, rng=None):
        self.num_decks = num_decks
        self._rng = rng or random
        self.cards = []
        self.total = 0
        self._build()

    def _build(self):
        self.cards = [(r, s) for _ in range(self.num_decks)
                      for r in RANKS for s in range(4)]
        self._rng.shuffle(self.cards)
        self.total = len(self.cards)

    def needs_reshuffle(self):
        return len(self.cards) <= self.total * _PENETRATION_RESHUFFLE_FRACTION

    def draw(self):
        if not self.cards:
            self._build()  # shoe exhausted mid-hand: reshuffle rather than crash
        return self.cards.pop()


class BlackjackGame(Game):
    name = "blackjack"
    min_h = 24
    min_w = 60
    supports_difficulty = False
    # Chip balance is tracked durably by currency.py, not by self.score /
    # config.save_high_score's single-number high-score file; a "high score"
    # comparison across sessions on top of that would just be a second,
    # redundant, and easily desynced ledger. self.score is still set (to
    # this session's net chip change) because _game_over_screen always shows
    # a "Score:" line regardless of this flag.
    track_high_score = False

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self._load_saved(saved)
            return
        self.shoe = Shoe()
        self._session_start_balance = currency.balance()
        self.stat_rounds = 0
        self.stat_wins = 0
        self.stat_losses = 0
        self.stat_pushes = 0
        self.hands = []
        self.dealer_cards = []
        self.dealer_hole_hidden = True
        self.cur_hand_idx = 0
        self.insurance_bet = 0
        self._dealing = False
        self._deal_reveal = 4
        self.message = ''
        self._start_bet_phase()

    def get_timeout(self):
        return -1  # turn-based: block until a key is pressed

    # -- bookkeeping -----------------------------------------------------

    def _record(self, hand):
        if hand.result in ('blackjack', 'win'):
            self.stat_wins += 1
        elif hand.result == 'push':
            self.stat_pushes += 1
        else:
            self.stat_losses += 1

    def _start_bet_phase(self):
        self.phase = 'bet'
        self.bet_input = ''
        self.hands = []
        self.dealer_cards = []
        self.dealer_hole_hidden = True
        self.cur_hand_idx = 0
        self.insurance_bet = 0
        self._dealing = False
        self.score = currency.balance() - self._session_start_balance
        if currency.balance() == 0:
            if currency.bailout_available():
                self.message = "You're out of chips. Press B for a one-time 100-chip bailout."
            else:
                self.message = "You're out of chips. Come back tomorrow for a bailout."
                self.game_over = True
                self.won = False
        else:
            self.message = 'Type a wager and press Enter.'

    # -- input -------------------------------------------------------------

    def handle_input(self, key):
        if self.game_over:
            return
        if self.phase == 'bet':
            self._input_bet(key)
        elif self.phase == 'insurance':
            self._input_insurance(key)
        elif self.phase == 'player':
            self._input_player(key)
        elif self.phase == 'result':
            self._next_round()

    def _input_bet(self, key):
        if key in (_KEY_BACKSPACE, 127, 8):
            self.bet_input = self.bet_input[:-1]
        elif ord('0') <= key <= ord('9') and len(self.bet_input) < 7:
            self.bet_input += chr(key)
        elif key in (ord('c'), ord('C')):
            self.bet_input = ''
        elif key in (ord('a'), ord('A')):
            self.bet_input = str(currency.balance())
        elif key in (ord('b'), ord('B')):
            if currency.bailout_available() and currency.try_bailout():
                self._start_bet_phase()  # refreshes message/balance too
                self.message = f'Bailout granted: +{currency.BAILOUT_AMOUNT} chips.'
        elif key in (curses.KEY_ENTER, 10, 13, ord(' ')):
            self._confirm_bet()

    def _confirm_bet(self):
        amt = int(self.bet_input) if self.bet_input else 0
        if amt <= 0:
            self.message = 'Bet must be more than 0 chips.'
            return
        if amt > currency.balance():
            self.message = 'Not enough chips for that bet.'
            return
        if not currency.bet(amt):
            self.message = 'That bet was refused. Try a smaller amount.'
            return
        self._deal_round(amt)

    def _input_insurance(self, key):
        if key in (ord('y'), ord('Y')):
            hand = self.hands[0]
            ins_amt = hand.bet // 2
            if ins_amt > 0 and currency.bet(ins_amt):
                self.insurance_bet = ins_amt
            else:
                self.insurance_bet = 0
                self.message = 'Insurance unavailable for that bet.'
            self._resolve_peek()
        elif key in (ord('n'), ord('N'), curses.KEY_ENTER, 10, 13, ord(' ')):
            self.insurance_bet = 0
            self._resolve_peek()

    def _input_player(self, key):
        if not self.hands or not (0 <= self.cur_hand_idx < len(self.hands)):
            return
        if key in (ord('h'), ord('H')):
            self._hit()
        elif key in (ord('s'), ord('S')):
            self._stand()
        elif key in (ord('d'), ord('D')):
            self._double()
        elif key in (ord('x'), ord('X')):
            self._split()

    # -- dealing -------------------------------------------------------------

    def _deal_round(self, amt):
        if self.shoe.needs_reshuffle():
            self.shoe = Shoe()
            self.message = 'Shoe reshuffled (75% penetration).'
        else:
            self.message = ''
        p1, d1, p2, d2 = (self.shoe.draw() for _ in range(4))
        hand = PlayerHand([p1, p2], amt)
        self.hands = [hand]
        self.dealer_cards = [d1, d2]
        self.dealer_hole_hidden = True
        self.cur_hand_idx = 0
        self.insurance_bet = 0
        self.stat_rounds += 1
        self._dealing = True
        self._deal_reveal = 0
        for _ in self.animate((150, 150, 150, 150)):
            self._deal_reveal = min(4, self._deal_reveal + 1)
            self.stdscr.erase()
            self.draw()
        self._deal_reveal = 4
        self._dealing = False
        self._after_deal()

    def _dealer_shows_ace(self):
        return self.dealer_cards[0][0] == 'A'

    def _dealer_shows_ten(self):
        return _base_value(self.dealer_cards[0][0]) == 10

    def _after_deal(self):
        if self._dealer_shows_ace():
            self.phase = 'insurance'
            self.message = 'Dealer shows an Ace. Insurance? (Y/N, pays 2:1)'
            return
        self._resolve_peek()

    def _resolve_peek(self):
        """Check the dealer's hole card for a natural blackjack whenever the
        up card makes one possible (Ace or a ten-value card); a dealer
        blackjack is structurally impossible with any other up card, so no
        peek is needed there."""
        if self._dealer_shows_ace() or self._dealer_shows_ten():
            if hand_value(self.dealer_cards)[0] == 21:
                self._settle_dealer_blackjack()
                return
        self._begin_player_turn()

    def _settle_dealer_blackjack(self):
        self.dealer_hole_hidden = False
        if self.insurance_bet:
            currency.payout(self.insurance_bet * 3)  # stake back + 2:1 profit
            self.message = 'Dealer has Blackjack. Insurance pays 2:1.'
        else:
            self.message = 'Dealer has Blackjack.'
        hand = self.hands[0]
        if _is_blackjack(hand):
            currency.payout(hand.bet)  # push: stake returned, no profit either side
            hand.result = 'push'
        else:
            hand.result = 'lose'
        hand.stood = True
        self._record(hand)
        self.phase = 'result'

    def _begin_player_turn(self):
        self.phase = 'player'
        self.cur_hand_idx = 0
        hand = self.hands[0]
        if _is_blackjack(hand):
            # Dealer has already been confirmed (or is structurally unable)
            # to hold a blackjack, so a player natural wins outright at 3:2
            # without the hand ever being "played".
            # Ceiling division so an odd bet rounds in the player's favor
            # (a half chip cannot be paid, and the house should not keep it).
            profit = -(-(hand.bet * 3) // 2)
            currency.payout(hand.bet + profit)
            hand.result = 'blackjack'
            hand.stood = True
            self._record(hand)
            self.dealer_hole_hidden = False
            self.message = 'Blackjack! You win 3:2.'
            self.phase = 'result'
        else:
            self._announce_turn()

    def _announce_turn(self):
        n = len(self.hands)
        label = f'Hand {self.cur_hand_idx + 1}' if n > 1 else 'Your hand'
        self.message = f'{label}: H)it  S)tand  D)ouble' + \
            ('  X)split' if self._can_split() else '')

    # -- player actions -------------------------------------------------

    def _current_hand(self):
        return self.hands[self.cur_hand_idx]

    def _can_split(self):
        # len(self.hands) <= MAX_SPLITS means fewer than MAX_SPLITS + 1 (4)
        # hands exist yet, i.e. the 4-hand cap has not been reached.
        hand = self._current_hand()
        return (len(self.hands) <= MAX_SPLITS and len(hand.cards) == 2
                and not hand.split_aces
                and hand.cards[0][0] == hand.cards[1][0]
                and currency.balance() >= hand.bet)

    def _deal_one(self, hand, pause=True):
        hand.cards.append(self.shoe.draw())
        if pause:
            for _ in self.animate((150,)):
                self.stdscr.erase()
                self.draw()

    def _hit(self):
        hand = self._current_hand()
        self._deal_one(hand)
        total, _ = hand_value(hand.cards)
        if total > 21:
            hand.busted = True
            hand.result = 'lose'
            self._record(hand)
            self._advance_hand()
        else:
            self._announce_turn()

    def _stand(self):
        hand = self._current_hand()
        hand.stood = True
        self._advance_hand()

    def _double(self):
        hand = self._current_hand()
        if len(hand.cards) != 2 or hand.doubled or hand.split_aces:
            self.message = 'Cannot double this hand.'
            return
        if not currency.bet(hand.bet):
            self.message = 'Not enough chips to double.'
            return
        hand.bet *= 2
        hand.doubled = True
        self._deal_one(hand)
        total, _ = hand_value(hand.cards)
        if total > 21:
            hand.busted = True
            hand.result = 'lose'
            self._record(hand)
        hand.stood = True
        self._advance_hand()

    def _split(self):
        if not self._can_split():
            self.message = 'Cannot split this hand.'
            return
        hand = self._current_hand()
        if not currency.bet(hand.bet):
            self.message = 'Not enough chips to split.'
            return
        is_aces = hand.cards[0][0] == 'A'
        c1, c2 = hand.cards
        h1 = PlayerHand([c1], hand.bet, from_split=True, split_aces=is_aces)
        h2 = PlayerHand([c2], hand.bet, from_split=True, split_aces=is_aces)
        self.hands[self.cur_hand_idx:self.cur_hand_idx + 1] = [h1, h2]
        self._deal_one(h1)
        self._deal_one(h2)
        for h in (h1, h2):
            total, _ = hand_value(h.cards)
            if total > 21:  # not reachable with 2 cards, kept for safety
                h.busted = True
                h.result = 'lose'
                self._record(h)
                h.stood = True
        if is_aces:
            # Split aces get exactly one card each and cannot act further.
            h1.stood = True
            h2.stood = True
            self.message = 'Split aces: one card each, no further action.'
            self._advance_hand()
        else:
            self.message = f'Split into {len(self.hands)} hands.'
            self._announce_turn()

    def _advance_hand(self):
        self.cur_hand_idx += 1
        while (self.cur_hand_idx < len(self.hands)
               and (self.hands[self.cur_hand_idx].stood
                    or self.hands[self.cur_hand_idx].busted)):
            self.cur_hand_idx += 1
        if self.cur_hand_idx >= len(self.hands):
            self._dealer_turn()
        else:
            self._announce_turn()

    # -- dealer / settlement ----------------------------------------------

    def _dealer_turn(self):
        self.phase = 'dealer'
        self.dealer_hole_hidden = False
        self.message = 'Dealer reveals...'
        for _ in self.animate((300,)):
            self.stdscr.erase()
            self.draw()
        if any(not h.busted for h in self.hands):
            total, _ = hand_value(self.dealer_cards)
            while total < 17:  # stands on all 17, soft or hard
                self.dealer_cards.append(self.shoe.draw())
                total, _ = hand_value(self.dealer_cards)
                for _ in self.animate((350,)):
                    self.stdscr.erase()
                    self.draw()
        self._settle_hands()

    def _settle_hands(self):
        dealer_total, _ = hand_value(self.dealer_cards)
        dealer_bust = dealer_total > 21
        for hand in self.hands:
            if hand.result is not None:
                continue
            if hand.busted:
                hand.result = 'lose'
            else:
                p_total, _ = hand_value(hand.cards)
                if _is_blackjack(hand):
                    # Ceiling division: round odd-bet 3:2 payouts in the
                    # player's favor rather than the house's.
                    profit = -(-(hand.bet * 3) // 2)
                    currency.payout(hand.bet + profit)
                    hand.result = 'blackjack'
                elif dealer_bust or p_total > dealer_total:
                    currency.payout(hand.bet * 2)
                    hand.result = 'win'
                elif p_total == dealer_total:
                    currency.payout(hand.bet)
                    hand.result = 'push'
                else:
                    hand.result = 'lose'
            self._record(hand)
        self.message = self._summary_line(dealer_total, dealer_bust)
        self.phase = 'result'

    def _summary_line(self, dealer_total, dealer_bust):
        if len(self.hands) == 1:
            h = self.hands[0]
            tag = {'blackjack': 'Blackjack! You win.', 'win': 'You win!',
                   'push': 'Push.', 'lose': 'You lose.'}[h.result]
            dealer_desc = 'busts' if dealer_bust else f'has {dealer_total}'
            return f'Dealer {dealer_desc}. {tag}'
        parts = []
        for i, h in enumerate(self.hands):
            tag = {'blackjack': 'WIN', 'win': 'WIN', 'push': 'PUSH',
                   'lose': 'LOSE'}[h.result]
            parts.append(f'H{i + 1}:{tag}')
        return 'Dealer ' + ('busts. ' if dealer_bust else f'has {dealer_total}. ') \
            + '  '.join(parts)

    def _next_round(self):
        self._start_bet_phase()

    # -- rendering -----------------------------------------------------

    def _suit_symbol(self, suit_idx):
        sym, ascii_sym, _ = _SUITS[suit_idx]
        return ascii_sym if render.ascii_mode else sym

    def _card_attr(self, card):
        is_red = _SUITS[card[1]][2]
        return curses.color_pair(2) | curses.A_BOLD if is_red \
            else curses.color_pair(7) | curses.A_BOLD

    def _draw_card(self, y, x, card, hidden=False):
        self.safe_addstr(y, x, '┌──┐')
        if hidden:
            back = curses.color_pair(6) | curses.A_BOLD
            self.safe_addstr(y + 1, x, '│▓▓│', back)
            self.safe_addstr(y + 2, x, '│▓▓│', back)
        else:
            rank, suit_idx = card
            attr = self._card_attr(card)
            rtxt = rank if len(rank) == 2 else rank + ' '
            stxt = ' ' + self._suit_symbol(suit_idx)
            self.safe_addstr(y + 1, x, '│' + rtxt + '│', attr)
            self.safe_addstr(y + 2, x, '│' + stxt + '│', attr)
        self.safe_addstr(y + 3, x, '└──┘')

    def _draw_cards_row(self, y, x, cards, hidden_last=False):
        cx = x
        n = len(cards)
        for i, card in enumerate(cards):
            hidden = hidden_last and i == n - 1
            self._draw_card(y, cx, card, hidden=hidden)
            cx += 5
        return cx

    def _visible_deal_counts(self):
        r = self._deal_reveal
        p = 2 if r >= 3 else (1 if r >= 1 else 0)
        d = 2 if r >= 4 else (1 if r >= 2 else 0)
        return p, d

    def draw(self):
        title = ' BLACKJACK '
        self.safe_addstr(0, max(0, (self.w - len(title)) // 2), title,
                         curses.A_BOLD | curses.A_REVERSE)
        info = f'Chips: {currency.balance()}   Shoe: {len(self.shoe.cards)}/{self.shoe.total}'
        self.safe_addstr(1, max(0, (self.w - len(info)) // 2), info,
                         curses.color_pair(4) | curses.A_BOLD)

        if self.phase == 'bet' and not self._dealing:
            self._draw_bet_screen()
        else:
            self._draw_table()

        self.safe_addstr(self.h - 3, max(0, (self.w - len(self.message)) // 2),
                         self.message[:max(0, self.w - 2)], curses.color_pair(3))
        self.draw_status_bar(self._status_hints())

    def _status_hints(self):
        bal = f'Chips:{currency.balance()}'
        if self.phase == 'bet':
            return [bal, 'Digits:Bet', 'Enter:Deal', 'Esc:Quit', '?:Help']
        if self.phase == 'insurance':
            return [bal, 'Y:Insure', 'N:Decline', 'Esc:Quit', '?:Help']
        if self.phase == 'player':
            hints = [bal, 'H:Hit', 'S:Stand', 'D:Double']
            if self._can_split():
                hints.append('X:Split')
            hints += ['Esc:Quit', '?:Help']
            return hints
        if self.phase == 'result':
            return [bal, 'Any key:Next hand', 'Esc:Quit', '?:Help']
        return [bal, 'Esc:Quit', '?:Help']

    def _draw_bet_screen(self):
        cy = max(4, self.h // 2 - 3)
        shown = str(int(self.bet_input)) if self.bet_input else '0'
        lines = ['PLACE YOUR BET', f'Bet: {shown}', f'Balance: {currency.balance()}']
        # Size the box to its own content (like the base class's game-over
        # banner does) rather than a flat width: keeps it tight on a small
        # terminal and avoids an oversized box on a wide one.
        box_w = min(self.w - 2, max(len(t) for t in lines) + 6)
        self.draw_box(cy - 1, max(0, (self.w - box_w) // 2), 6, box_w, curses.A_BOLD)
        self.center_text(cy, lines[0], curses.A_BOLD)
        self.center_text(cy + 2, lines[1], curses.color_pair(3) | curses.A_BOLD)
        self.center_text(cy + 3, lines[2], curses.color_pair(4))

    def _draw_table(self):
        sx = max(1, (self.w - 40) // 2)
        y = 3
        dealer_cards = self.dealer_cards
        p_show, d_show = (self._visible_deal_counts() if self._dealing
                          else (len(self.hands[0].cards) if self.hands else 0,
                                len(dealer_cards)))
        d_cards = dealer_cards[:d_show]

        label = 'DEALER'
        if not self.dealer_hole_hidden and len(dealer_cards) == d_show:
            dt, soft = hand_value(dealer_cards)
            bust = ' BUST' if dt > 21 else ''
            label += f'  ({"Soft " if soft else ""}{dt}{bust})'
        self.safe_addstr(y, sx, label, curses.A_BOLD)
        hide_last = self.dealer_hole_hidden and d_show >= 2
        self._draw_cards_row(y + 1, sx, d_cards, hidden_last=hide_last)

        y += 6
        n = len(self.hands)
        # A split (X, up to MAX_SPLITS=3 -> 4 hands) used to render every
        # hand at full card-art height (6 rows each). That only ever fit 2
        # hands at the game's own declared min_h=24 (3 at 120x30): the
        # `if y > self.h - 6: break` below silently dropped every hand past
        # that, including the one the player was actively being asked to
        # act on (H/S/D/X still applied to a hand with no cards drawn
        # anywhere on screen). Below, fall back to a compact one-line-per-
        # hand form (no card-art boxes, just rank+suit text) whenever full
        # art for every hand would not fit in the room actually available
        # between the dealer block and the message/status rows -- this is
        # what keeps all 4 hands visible (and playable) at 60x24.
        # Full art draws hand blocks of 6 rows each (label + 4-row card box
        # + 1 spacer) starting at y; the LAST row actually inked is the
        # final hand's bottom card-box row, y + 6*(n-1) + 4. That must
        # leave at least one blank row above the message line (h-3).
        full_art_last_row = y + 6 * (n - 1) + 4 if n else y
        compact = n > 1 and full_art_last_row > self.h - 4
        for i, hand in enumerate(self.hands):
            cards = hand.cards
            if self._dealing and i == 0:
                cards = hand.cards[:p_show]
            active = self.phase == 'player' and i == self.cur_hand_idx
            total, soft = hand_value(cards) if cards else (0, False)
            label = f'HAND {i + 1}' if n > 1 else 'YOUR HAND'
            label += f'  Bet:{hand.bet}'
            if cards:
                bust = ' BUST' if total > 21 else ''
                label += f'  ({"Soft " if soft else ""}{total}{bust})'
            if hand.result:
                tag = {'blackjack': 'BLACKJACK!', 'win': 'WIN', 'push': 'PUSH',
                       'lose': 'LOSE'}[hand.result]
                label += f'  [{tag}]'
            attr = (curses.A_REVERSE | curses.A_BOLD) if active else curses.A_BOLD
            if compact:
                marker = '> ' if active else '  '
                self.safe_addstr(y, sx, marker + label, attr)
                cards_txt = ' '.join(
                    f'{r}{self._suit_symbol(s)}' for r, s in cards) if cards else '--'
                self.safe_addstr(y + 1, sx + 2, cards_txt[:max(0, self.w - sx - 3)])
                y += 2
            else:
                self.safe_addstr(y, sx, label, attr)
                self._draw_cards_row(y + 1, sx, cards)
                y += 6
            if y > self.h - 4:
                # Should be unreachable given MAX_SPLITS=3 and min_h=24 (4
                # compact hands need 8 rows; up to 12 are available), but
                # never silently drop a hand -- say plainly that more exist
                # rather than hiding one the player might still be playing.
                remaining = n - (i + 1)
                if remaining > 0:
                    self.safe_addstr(y, sx, f'+{remaining} more hand'
                                      f'{"s" if remaining > 1 else ""}...',
                                      curses.A_DIM)
                break

    def get_controls(self):
        return [('0-9', 'Type a bet'), ('Backspace', 'Edit bet'),
                ('A', 'Bet all chips'), ('Enter', 'Confirm bet / deal'),
                ('H', 'Hit'), ('S', 'Stand'), ('D', 'Double down'),
                ('X', 'Split a pair'), ('Y / N', 'Insurance yes/no'),
                ('B', 'Claim daily bailout when broke'),
                ('ESC', 'Quit / save')]

    def get_stats(self):
        net = currency.balance() - self._session_start_balance
        return [('Rounds played', self.stat_rounds), ('Hands won', self.stat_wins),
                ('Hands lost', self.stat_losses), ('Hands pushed', self.stat_pushes),
                ('Chip balance', currency.balance()), ('Net chips', net)]

    def get_save_data(self):
        # A round with chips already staked (bet() already debited) must
        # survive an ESC-quit, or those chips would simply vanish with
        # nothing played out -- currency.py went to great lengths to make
        # sure a chip is never lost or duplicated; losing a live wager to a
        # missing save would undo that at the game layer instead.
        if self.phase == 'bet' and not self.hands:
            return None  # nothing staked yet: a fresh bet screen is fine
        return {
            'shoe_cards': [[r, s] for r, s in self.shoe.cards],
            'shoe_total': self.shoe.total,
            'phase': self.phase,
            'hands': [{'cards': [[r, s] for r, s in h.cards], 'bet': h.bet,
                       'from_split': h.from_split, 'split_aces': h.split_aces,
                       'doubled': h.doubled, 'stood': h.stood,
                       'busted': h.busted, 'result': h.result}
                      for h in self.hands],
            'dealer_cards': [[r, s] for r, s in self.dealer_cards],
            'dealer_hole_hidden': self.dealer_hole_hidden,
            'cur_hand_idx': self.cur_hand_idx,
            'insurance_bet': self.insurance_bet,
            'message': self.message,
            'stat_rounds': self.stat_rounds, 'stat_wins': self.stat_wins,
            'stat_losses': self.stat_losses, 'stat_pushes': self.stat_pushes,
            'session_start_balance': self._session_start_balance,
            'score': self.score,
        }

    def _load_saved(self, saved):
        self.shoe = Shoe()
        self.shoe.cards = [(r, s) for r, s in saved['shoe_cards']]
        self.shoe.total = saved['shoe_total']
        self.phase = saved['phase']
        self.hands = []
        for hd in saved['hands']:
            h = PlayerHand([(r, s) for r, s in hd['cards']], hd['bet'],
                           from_split=hd['from_split'], split_aces=hd['split_aces'])
            h.doubled = hd['doubled']
            h.stood = hd['stood']
            h.busted = hd['busted']
            h.result = hd['result']
            self.hands.append(h)
        self.dealer_cards = [(r, s) for r, s in saved['dealer_cards']]
        self.dealer_hole_hidden = saved['dealer_hole_hidden']
        self.cur_hand_idx = saved['cur_hand_idx']
        self.insurance_bet = saved['insurance_bet']
        self.message = saved['message']
        self.stat_rounds = saved['stat_rounds']
        self.stat_wins = saved['stat_wins']
        self.stat_losses = saved['stat_losses']
        self.stat_pushes = saved['stat_pushes']
        self._session_start_balance = saved['session_start_balance']
        self.score = saved['score']
        self.bet_input = ''
        self._dealing = False
        self._deal_reveal = 4
