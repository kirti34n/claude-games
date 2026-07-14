"""The Game base class that every game subclasses, including the fixed
timestep run loop and the game-over screen."""
import json
import time

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None

from . import config
from . import render


class Game:
    name = "game"
    min_h = 20
    min_w = 40
    supports_difficulty = False
    # High scores are a saturating "biggest self.score ever" compare, which
    # only makes sense for games where self.score is a single comparable
    # progress metric. Minesweeper's self.score is a revealed-cell count
    # that saturates across difficulties (mines-5); it tracks its own
    # per-difficulty best-time instead and opts out here.
    track_high_score = True
    # Real-time games may catch up at most this many ticks in one outer
    # loop iteration after a stall (see _run_loop). The default (3) is fine
    # for games where a few blind ticks are harmless; a game whose avatar
    # is steered tick-by-tick (Snake) should lower this so a stall never
    # advances it multiple cells with no chance to react and no frame drawn
    # in between (snake-3).
    max_catchup_ticks = 3
    # --- help-overlay toggle: reconstructing key-down edges ('?'/'H') -----
    # curses delivers no key-up event, so a HELD key is indistinguishable
    # from a fast series of taps except by timing: the OS emits one event on
    # the press, waits out its repeat DELAY (~0.25-1.0s), then autorepeats at
    # its repeat RATE (~25-30/sec). Toggling on every event strobed the
    # overlay at that rate; debouncing on the last TOGGLE only slowed the
    # strobe down (one flip per debounce window, forever, for as long as the
    # key was held). Neither is a key-down edge.
    #
    # So: a '?' arriving within _HELP_REPEAT_GAP of the previous '?' is
    # autorepeat, not a new press. And a toggle is not committed on the spot
    # -- it is held for _HELP_CONFIRM first. If autorepeat follows inside
    # that window, the press is revealed as a repeat and the pending toggle
    # is cancelled; if nothing follows, it was a real press and it commits.
    # That single short deferral is what disambiguates the FIRST repeat after
    # the OS repeat delay (which looks exactly like a fresh press) from an
    # actual fresh press, and it is what makes a held key produce exactly ONE
    # flip no matter how long it is held. _HELP_CONFIRM must exceed the
    # autorepeat interval (40ms at 25/sec) and stay short enough to be
    # imperceptible on a real press.
    _HELP_REPEAT_GAP = 0.20
    _HELP_CONFIRM = 0.08

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.score = 0
        self.paused = False
        self.game_over = False
        self.won = False
        # A draw is neither a win nor a loss; games that can end in one
        # (Reversi, Connect Four) set this so _game_over_screen can present
        # it as a neutral result instead of the red "GAME OVER" defeat
        # banner (reversi-9).
        self.tied = False
        self._show_help = False
        # See _HELP_REPEAT_GAP / _HELP_CONFIRM above. _last_help_key is the
        # time of the last '?'/'H' EVENT (repeat or not); _help_pending is the
        # time of a press whose toggle has not been committed yet, or None.
        self._last_help_key = float('-inf')
        self._help_pending = None
        self.difficulty = 'medium'
        self.h, self.w = stdscr.getmaxyx()
        # Keys received since the last update() call; the run loop appends
        # to this and clears it right after each update(). Continuous
        # movement (paddle/ship/frog/snake steering) reads it in update();
        # never mutate position from inside handle_input().
        self.keys = []
        self.ticks = 0

    def safe_addstr(self, y, x, text, attr=0):
        render.safe_addstr(self.stdscr, y, x, text, attr)

    def center_text(self, y, text, attr=0):
        render.center_text(self.stdscr, self.w, y, text, attr)

    def draw_box(self, y, x, h, w, attr=0):
        render.draw_box(self.stdscr, y, x, h, w, attr)

    def draw_status_bar(self, text, attr=None):
        render.status_bar(self.stdscr, self.h, self.w, text, attr)

    def held(self, *codes):
        """True if any of the given key codes was received since the last
        update(). Use for continuous movement inside update(); never in
        handle_input()."""
        return any(c in self.keys for c in codes)

    def setup(self):
        pass

    def handle_input(self, key):
        """Edge-triggered discrete actions only (rotate, hard drop, fire,
        flap, reveal, place, ...). Called once per keypress, immediately,
        for crispness. Never move a continuously-steerable avatar here;
        that belongs in update(), gated on self.held(...)."""
        pass

    def update(self):
        pass

    def draw(self):
        pass

    def on_resize(self):
        """Called after a KEY_RESIZE (and curses.resize_term) once self.h
        / self.w reflect the new size. Override to re-run board-fitting
        (_fit_bounds() and friends) so collision bounds do not desync from
        the drawn board. Default no-op."""
        pass

    def net_pump(self):
        """Called once per run-loop iteration whenever self.net is set, in
        addition to update() when the game is active. Pausing is already
        disabled for net games, but the help overlay, a too-small-terminal
        gate, and a resize all otherwise stop update() (and therefore the
        socket) from running; override this to keep reading/writing the
        link during those windows so opening `?` or resizing never freezes
        the game for the other player. Must be cheap and must not block.
        Default no-op."""
        pass

    def animate(self, frames_ms):
        """Drive a short real-time animation (a falling disc, a flipping
        row) outside the tick clock. frames_ms is an iterable of per-frame
        delays in milliseconds. The caller mutates state and draws each
        frame; this generator handles the flip (noutrefresh + doupdate)
        and the delay, and lets ESC abort early:

            for _ in self.animate((40, 40, 40, 60)):
                self.stdscr.erase()
                self.drop_row += 1
                self.draw()

        No-op pacing (single instant pass, zero delay) when self.net is
        set: a receiving peer must never be blocked waiting on the local
        side's animation.
        """
        is_net = getattr(self, 'net', None) is not None
        self.stdscr.nodelay(True)
        try:
            for ms in frames_ms:
                yield
                self.stdscr.noutrefresh()
                curses.doupdate()
                if is_net:
                    continue
                curses.napms(ms)
                k = self.stdscr.getch()
                if k == -1:
                    continue
                # A key read here used to be silently discarded unless it was
                # ESC, dropping any move a fast player queued during a slide/
                # flip/think-pause animation. Push it back into curses' own
                # input queue instead: it stays there (this same peek-and-
                # push repeats harmlessly every frame) until the animation
                # finishes and the run loop's own getch() picks it up for
                # real. ESC still aborts the animation immediately, same as
                # before, but is pushed back too so the outer loop's normal
                # 27-means-quit handling still fires instead of this method
                # swallowing the quit keystroke.
                try:
                    curses.ungetch(k)
                except curses.error:
                    pass
                if k == 27:
                    break
        finally:
            # Restore the run loop's own poll timeout instead of leaving the
            # window in nodelay(True)'s timeout(0), and instead of the old
            # nodelay(False) (== timeout(-1), permanently blocking): either
            # one destroys the tick-rate timeout _run_loop set with
            # self.stdscr.timeout(poll_ms) the moment a turn-based net game
            # (Reversi, Connect Four) used its first animation, so the very
            # next getch() blocked forever and froze update()/net_pump() for
            # both players.
            self.stdscr.timeout(getattr(self, '_poll_ms', -1))

    def get_controls(self):
        """Override to return list of (key, description) tuples for help overlay."""
        return []

    def get_stats(self):
        """Override to return list of (label, value) strings for game over screen."""
        return []

    def _draw_help_overlay(self):
        controls = self.get_controls()
        if not controls:
            return
        box_w = max(len(k) + len(d) + 6 for k, d in controls) + 4
        box_w = max(box_w, 20)
        box_h = len(controls) + 4
        sy = max(0, (self.h - box_h) // 2)
        sx = max(0, (self.w - box_w) // 2)
        for i in range(box_h):
            self.safe_addstr(sy + i, sx, ' ' * box_w)
        self.draw_box(sy, sx, box_h, box_w, curses.A_BOLD)
        self.center_text(sy, ' CONTROLS ', curses.A_BOLD | curses.A_REVERSE)
        for i, (key, desc) in enumerate(controls):
            self.safe_addstr(sy + 2 + i, sx + 2, f'{key:<8} {desc}')
        self.center_text(sy + box_h - 1, ' ? to close ', curses.color_pair(4))

    @staticmethod
    def _select_difficulty(stdscr):
        options = ['Easy', 'Medium', 'Hard']
        sel = 1
        while True:
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            mid_y = h // 2
            render._safe(stdscr, mid_y - 3, max(0, (w - 20) // 2),
                  'SELECT DIFFICULTY', curses.A_BOLD)
            for i, opt in enumerate(options):
                y = mid_y - 1 + i
                if i == sel:
                    render._safe(stdscr, y, max(0, (w - 14) // 2),
                          f'  > {opt} <  ',
                          curses.A_BOLD | curses.A_REVERSE)
                else:
                    render._safe(stdscr, y, max(0, (w - 14) // 2),
                          f'    {opt}    ')
            render._safe(stdscr, mid_y + 3, max(0, (w - 26) // 2),
                  'Up/Down: Select  Enter: OK', curses.color_pair(4))
            stdscr.noutrefresh()
            curses.doupdate()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('w'), ord('k')):
                sel = (sel - 1) % 3
            elif key in (curses.KEY_DOWN, ord('s'), ord('j')):
                sel = (sel + 1) % 3
            elif key in (curses.KEY_ENTER, 10, 13):
                return options[sel].lower()
            elif key in (27, ord('q')):
                return 'medium'

    def get_timeout(self):
        return 100

    def get_save_data(self):
        """Override to return serializable state dict. None = no save."""
        return None

    def _auto_save(self):
        data = self.get_save_data()
        if data is None:
            return
        try:
            config._atomic_write_json(
                config.CONFIG_DIR / f'save_{self.name}.json', data)
        except OSError:
            # Best-effort: losing this save is acceptable, crashing the
            # player's ESC-quit is not (DEFECT 1). config._atomic_write_json
            # itself no longer raises OSError, but this stays as a second
            # line of defense in case a future writer does.
            pass

    def _load_save(self, name):
        """Read and consume a pending save for `name`. The file is deleted
        as soon as it has been successfully decoded (not merely because it
        exists), so a save that fails to parse is left in place for
        nothing and a save that does parse is claimed exactly once. If the
        decoded dict turns out to be schema-incompatible, setup() raising
        while consuming it is handled by the run loop (_run_loop), which
        falls back to a clean re-init rather than crashing."""
        f = config.CONFIG_DIR / f'save_{name}.json'
        if f.exists():
            try:
                data = json.loads(f.read_text())
                f.unlink()
                return data
            except Exception:
                f.unlink(missing_ok=True)
        return None

    @staticmethod
    def has_save(name):
        f = config.CONFIG_DIR / f'save_{name}.json'
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text()).get('score', 0)
        except Exception:
            return None

    def run(self):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            return self._run_loop()
        finally:
            # Cursor visibility is process-global curses state; nothing
            # else restores it once this game's loop exits (retry, quit,
            # or an exception unwinding through curses.wrapper's own
            # finally, which only handles echo/cbreak/endwin).
            try:
                curses.curs_set(1)
            except curses.error:
                pass

    def _run_loop(self):
        try:
            self.setup()
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            # Save was valid JSON but an incompatible schema (older/newer
            # version, truncation) or another init-time data bug.
            # _load_save() already consumed (deleted) it on the way in, so
            # a clean re-init starts a fresh game instead of retrying the
            # same bad data forever or crashing on resume. Narrower than a
            # bare `except Exception` so unrelated bugs elsewhere in
            # setup() still surface instead of silently restarting.
            diff = self.difficulty
            self.__init__(self.stdscr)
            self.difficulty = diff  # keep the caller-selected difficulty
            self.setup()
        self.h, self.w = self.stdscr.getmaxyx()

        # Real-time games advance on a wall-clock cadence, decoupled from input:
        # curses getch() returns early on any buffered key, so calling update()
        # once per getch would let holding/mashing a key add extra ticks (the
        # snake "accelerates"). Instead we poll input often but only step the
        # simulation when the tick deadline is reached. Turn-based games
        # (get_timeout() == -1) block on getch and step once per key.
        realtime = self.get_timeout() > 0
        interval = (self.get_timeout() / 1000.0) if realtime else 0.0
        # The poll must never be coarser than the tick: a 20 ms poll would
        # starve a 16 ms tick (Pong, Tetris). Recomputed below whenever
        # get_timeout() changes (Snake's speed ramp).
        poll_ms = max(4, min(20, int(interval * 1000))) if realtime else -1
        self.stdscr.timeout(poll_ms)
        self._poll_ms = poll_ms  # animate() restores this, see its docstring
        applied_ms = poll_ms     # what getch's timeout is actually set to
        next_tick = time.monotonic() + interval

        first = True
        while True:
            key = -1 if first else self.stdscr.getch()
            first = False
            self.h, self.w = self.stdscr.getmaxyx()

            if key == curses.KEY_RESIZE:
                try:
                    curses.resize_term(0, 0)
                except curses.error:
                    pass
                self.h, self.w = self.stdscr.getmaxyx()
                self.on_resize()
                # Never a game move, never a free turn-based turn: fall
                # through to the normal per-iteration redraw below as if no
                # key had been read (key = -1), instead of `continue`-ing
                # straight back to getch(). The old `continue` skipped
                # erase()/draw() entirely, so the five blocking/turn-based
                # games (2048, minesweeper, sokoban, reversi, connect4) sat
                # on a stale, mis-centred frame until the player's NEXT
                # keypress (INFRA-2 regression).
                key = -1

            if key == 27 or key == ord('q'):
                if not self.game_over:
                    self._auto_save()
                self.stdscr.nodelay(False)
                return 'quit'

            # The keypress that dismisses help (or toggles pause) must be
            # swallowed here, not delivered as a game move: previously the
            # same keystroke that closed the help overlay also reached
            # handle_input(), which could commit an irreversible move
            # (Reversi) or slide the board (2048).
            consumed = False
            if key == ord('p') and not self.game_over and not getattr(self, 'net', None):
                self.paused = not self.paused  # no pausing a live network game
                consumed = True
            elif key == ord('?') or key == ord('H'):
                # Key-down-edge reconstruction, not a rate limiter: see
                # _HELP_REPEAT_GAP / _HELP_CONFIRM. A held '?'/'H' must toggle
                # the overlay exactly once, however long it is held, instead
                # of strobing at the OS autorepeat rate (help-strobe).
                now_key = time.monotonic()
                if now_key - self._last_help_key < self._HELP_REPEAT_GAP:
                    # Autorepeat: the key never came up. If we were about to
                    # commit a toggle for the event that started this repeat
                    # run, that event was a repeat too -- drop it.
                    self._help_pending = None
                elif self._help_pending is None:
                    self._help_pending = now_key  # a real press, pending confirmation
                self._last_help_key = now_key
                consumed = True
            elif key != -1 and self._show_help:
                self._show_help = False  # any other key closes help
                self._help_pending = None
                consumed = True

            # Commit a pending help toggle once no autorepeat has contradicted
            # it for _HELP_CONFIRM. Runs every iteration (not just on a key),
            # so the deferral resolves on its own; the getch timeout below is
            # shortened while one is pending so even a turn-based game, which
            # otherwise blocks in getch() forever, still wakes up to commit it.
            if self._help_pending is not None and \
                    time.monotonic() - self._help_pending >= self._HELP_CONFIRM:
                self._show_help = not self._show_help
                self._help_pending = None

            # A turn-based game (poll_ms == -1) blocks in getch() until the
            # next keypress, which would leave a pending help toggle hanging
            # until the player pressed something else. Shorten the wait to the
            # confirmation window while one is pending, then restore it.
            want_ms = poll_ms
            if self._help_pending is not None and not realtime:
                want_ms = int(self._HELP_CONFIRM * 1000)
            if want_ms != applied_ms:
                self.stdscr.timeout(want_ms)
                applied_ms = want_ms

            is_net = getattr(self, 'net', None) is not None
            active = not self.paused and not self._show_help and not self.game_over
            # NET-2: a net game's simulation (and the socket state riding on
            # it, e.g. Pong's ball physics and _apply_state) must never stop
            # for a LOCAL UI state on this side. Pausing is already refused
            # above for a net game, so the only two things that could still
            # gate `active` off for one are the help overlay and (below) the
            # too-small-terminal gate; neither is something the peer agreed
            # to, so neither may freeze the peer's game. game_over is the
            # only legitimate reason a net game's sim stops.
            sim_active = active if not is_net else not self.game_over
            if not active:
                # self.keys is only ever drained by the tick loop below,
                # which is itself gated on `active`. A steering key
                # appended while active (this same iteration or an earlier
                # poll still waiting on the tick deadline) survives
                # untouched for as long as the game then stays paused/
                # help-open/over, and gets replayed as one phantom step the
                # moment update() runs again after resuming. Clearing here,
                # the instant the game goes inactive, closes that window
                # instead of only bounding it (residual of REG-9/REG-30).
                self.keys.clear()

            if is_net:
                # Keep the socket alive even while the sim isn't stepping
                # (help open, too-small terminal): update() is the only
                # other place the link is touched, and it's gated on
                # `active`, so without this a `?` or a shrink would freeze
                # the game for both players.
                self.net_pump()

            self.stdscr.erase()
            # Size gate runs BEFORE advancing state, so a shrunk terminal pauses
            # a LOCAL game (visibly) instead of playing on invisibly. A net
            # game must not pause at all just because THIS side's window is
            # too small: the peer is still playing, so the sim below still
            # steps for it; only the draw is skipped, because there is
            # nowhere to legibly put it.
            too_small = self.h < self.min_h or self.w < self.min_w

            # Steering/actions register immediately on the keypress (crisp), but
            # they never directly advance the simulation. Only collected while
            # `active`: update() (the only thing that reads self.keys or
            # clears it) does not run while paused/help-open/game-over/too-
            # small, so appending here unconditionally used to grow self.keys
            # without bound for as long as that lasted (held keys, OS auto-
            # repeat, a long pause) and then dump the whole backlog onto the
            # first update() after resuming as a phantom held-key step.
            process_key = key != -1 and not consumed
            if process_key and active and not too_small:
                self.keys.append(key)
                self.handle_input(key)

            # A too-small terminal must still pause a LOCAL game's clock (so
            # no burst of banked ticks fires once it's resized back up), but
            # must never pause a NET game's clock: the peer's game keeps
            # running in real time regardless of what this side can draw.
            can_step = sim_active and not (too_small and not is_net)
            if realtime:
                interval = max(0.01, self.get_timeout() / 1000.0)  # e.g. snake ramp
                new_poll_ms = max(4, min(20, int(interval * 1000)))
                if new_poll_ms != poll_ms:
                    poll_ms = new_poll_ms
                    self.stdscr.timeout(poll_ms)
                    self._poll_ms = poll_ms
                    applied_ms = poll_ms
                now = time.monotonic()
                steps = 0
                while can_step and now >= next_tick and steps < self.max_catchup_ticks:
                    self.update()
                    self.ticks += 1
                    self.keys.clear()
                    next_tick += interval
                    steps += 1
                    if self.game_over:
                        break
                if too_small and not is_net:
                    next_tick = now + interval  # local game: don't bank paused time
                elif next_tick < now - interval:  # big stall: resync, no burst
                    next_tick = now + interval
            elif can_step and process_key:
                self.update()  # turn-based: exactly one step per keypress
                self.ticks += 1
                self.keys.clear()

            if too_small:
                self.center_text(self.h // 2,
                                 f'Terminal too small ({self.w}x{self.h})')
                self.center_text(self.h // 2 + 1,
                                 f'Need at least {self.min_w}x{self.min_h}')
                self.stdscr.noutrefresh()
                curses.doupdate()
                continue

            self.draw()
            if self.game_over and not self._show_help:
                return self._game_over_screen()
            if self._show_help:
                self._draw_help_overlay()
            elif self.paused:
                self.center_text(self.h // 2,
                                 '  PAUSED  -  Press P to resume  ',
                                 curses.A_REVERSE | curses.A_BOLD)
            self.stdscr.noutrefresh()
            curses.doupdate()

    def _game_over_box_pos(self, box_h, box_w):
        """Where to draw the game-over banner. Default: dead center.
        Override when centering would blank out gameplay state the player
        still needs to see (c4-2: Connect Four's winning four)."""
        return (max(0, (self.h - box_h) // 2), max(0, (self.w - box_w) // 2))

    def _protected_cells(self):
        """Screen (row, col) cells the game-over banner must never paint
        over, even where its box footprint covers them. Default: nothing is
        protected, so the banner is a normal opaque box. Override when the
        banner can land on top of gameplay state the player still needs to
        see (c4-2: Connect Four's winning four); relocating the box via
        _game_over_box_pos alone only helps when the terminal is wide
        enough to fit the box beside the board, not at every size."""
        return frozenset()

    def _blit_protected(self, y, x, text, attr, protect):
        """Like safe_addstr, but skips any column in `protect` entirely,
        leaving whatever was already drawn there untouched instead of
        painting over it. `protect` is a set of (row, col) screen cells,
        as returned by _protected_cells()."""
        if not protect:
            self.safe_addstr(y, x, text, attr)
            return
        n = len(text)
        i = 0
        while i < n:
            if (y, x + i) in protect:
                i += 1
                continue
            j = i
            while j < n and (y, x + j) not in protect:
                j += 1
            self.safe_addstr(y, x + i, text[i:j], attr)
            i = j

    def _draw_box_protected(self, y, x, h, w, attr, protect):
        """Like draw_box, but routes every edge through _blit_protected so
        protected cells (see _protected_cells()) are never overwritten."""
        self._blit_protected(y, x, '┌' + '─' * (w - 2) + '┐', attr, protect)
        for i in range(1, h - 1):
            self._blit_protected(y + i, x, '│', attr, protect)
            self._blit_protected(y + i, x + w - 1, '│', attr, protect)
        self._blit_protected(y + h - 1, x, '└' + '─' * (w - 2) + '┘', attr, protect)

    def _game_over_screen(self):
        is_net = bool(getattr(self, 'net', None))
        # NET-4: beating a friend over LAN must not count as a single-player
        # high score.
        try:
            high = config.load_high_score(self.name) if self.track_high_score else 0
        except OSError:
            high = 0
        is_new_high = self.track_high_score and (not is_net) and self.score > high
        if is_new_high:
            # DEFECT 1: a failed persistence write must never crash a game,
            # least of all right here, the instant the player finishes it.
            # config.save_high_score no longer raises OSError itself, but
            # this stays as a second line of defense in case a future
            # writer does.
            try:
                config.save_high_score(self.name, self.score)
            except OSError:
                pass
            high = self.score
        stats = self.get_stats()

        def redraw():
            self.h, self.w = self.stdscr.getmaxyx()
            self.stdscr.erase()
            self.draw()  # last live frame, so the board is never blank/stale

            protect = self._protected_cells()

            if self.tied:
                title = '  DRAW  '
                title_attr = curses.color_pair(3) | curses.A_BOLD  # neutral, not red
            elif self.won:
                title = '  YOU WIN!  '
                title_attr = curses.color_pair(1) | curses.A_BOLD
            else:
                title = '  GAME OVER  '
                title_attr = curses.color_pair(2) | curses.A_BOLD
            body = [(title, title_attr), ('', 0),
                    (f'Score: {self.score}', curses.A_BOLD)]
            if self.track_high_score:
                high_line = 'NEW HIGH SCORE!' if is_new_high else f'High Score: {high}'
                high_attr = ((curses.A_REVERSE | curses.A_BOLD) if is_new_high
                            else curses.color_pair(3))
                body.append((high_line, high_attr))
            body.append(('', 0))
            body += [(f'{label}: {value}', curses.color_pair(4))
                     for label, value in stats]
            body += [('', 0), ('[R] Retry   [Q] Quit', curses.color_pair(4))]

            box_w = max(6, max(len(t) for t, _ in body)) + 6
            box_h = len(body) + 4
            sy, sx = self._game_over_box_pos(box_h, box_w)
            # Blank the box's footprint first (bordered, filled box), so the
            # banner never bleeds into the redrawn board behind it. Routed
            # through _blit_protected so any cells a game has claimed via
            # _protected_cells() (c4-2: Connect Four's winning four) survive
            # even where the box footprint covers them; protect is empty for
            # every game that doesn't override the hook, so this behaves
            # exactly like a plain safe_addstr/draw_box for them.
            for i in range(box_h):
                self._blit_protected(sy + i, sx, ' ' * box_w, 0, protect)
            self._draw_box_protected(sy, sx, box_h, box_w, curses.A_BOLD, protect)
            for i, (text, attr) in enumerate(body):
                # Center each line INSIDE the box at (sy, sx), not on the
                # screen: self.center_text() centers on self.w, which is
                # correct only when the box itself is screen-centered. Once
                # a game overrides _game_over_box_pos (c4-2: Connect Four
                # moves the box beside the board instead of on top of it),
                # centering the text on the screen paints it at the box's
                # OLD dead-center location while the box is drawn elsewhere,
                # leaving an empty box and text overlapping the playfield.
                tx = sx + max(0, (box_w - len(text)) // 2)
                self._blit_protected(sy + 2 + i, tx, text, attr, protect)
            self.stdscr.noutrefresh()
            curses.doupdate()

        redraw()
        if is_new_high:
            curses.beep()
        # A net game must keep servicing the socket while this banner is up
        # (NET-8): with nodelay(False) (a blocking getch), neither player's
        # link was ever pumped again after the game ended, so heartbeats
        # stopped and the OTHER side's _PEER_TIMEOUT (8s) fired while both
        # players were just reading the banner, turning "read the score" into
        # "get disconnected". A short poll timeout keeps net_pump() running
        # without changing the blocking feel for a solo game (timeout(-1) is
        # nodelay(False)).
        self.stdscr.timeout(150 if is_net else -1)
        while True:
            key = self.stdscr.getch()
            if is_net:
                if not (self.net and self.net.alive):
                    is_net = False  # peer is gone; stop polling, block normally
                    self.stdscr.timeout(-1)
                else:
                    self.net_pump()
            if key == -1:
                continue
            if key == curses.KEY_RESIZE:
                try:
                    curses.resize_term(0, 0)
                except curses.error:
                    pass
                self.on_resize()
                redraw()
                continue
            if key == ord('r'):
                try:
                    (config.CONFIG_DIR / f'save_{self.name}.json').unlink(missing_ok=True)
                except OSError:
                    pass  # best-effort cleanup; a stale save is harmless
                return 'retry'
            if key == ord('q') or key == 27:
                return 'quit'
