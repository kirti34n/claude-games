"""LAN multiplayer: the newline-delimited-JSON socket link and the netplay
lobby.

Wire protocol, all newline-delimited JSON objects:
  - Application messages (game moves, state, the handshake) carry whatever
    keys the caller passed to send(). Anything whose 'type' is NOT one of the
    high-frequency per-tick kinds ('s', 'p': Pong's state/paddle streams) is
    treated as reliable: send() stamps it with an auto-incrementing '_seq'
    before it goes on the wire, keeps the encoded bytes around, and pump()
    re-transmits it (same seq) every _RESEND_INTERVAL until the peer acks it.
    poll() strips '_seq' back off before handing the dict to the caller, acks
    every reliable message it sees, and silently drops a duplicate delivery
    of a seq it has already returned once. This is the fix for NET-1: a
    frame that was truly dropped (rather than merely queued) gets resent
    automatically instead of deadlocking Reversi/Connect Four forever.
  - '_ack' (a bare {'type': '_ack', 'seq': N}) and '_hb' (a bare heartbeat)
    are control messages: pump()/poll() consume them internally and never
    hand them to a caller.

Imports the net-capable game classes from registry, never the reverse.
"""
import json
import socket
import sys
import time

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None

from . import render
from . import theme
from .registry import _NET_GAMES
from .games.pong import PongGame

_HAS_CURSES = curses is not None

NET_DEFAULT_PORT = 8765
NET_PROTOCOL = 1


class _NetLink:
    """Newline-delimited JSON messages over a TCP socket, non-blocking reads
    and writes, with automatic resend/ack for anything but the per-tick
    state streams, a heartbeat, and a peer-timeout.
    """

    # Pong's state ('s') and paddle ('p') messages are sent every tick; the
    # very next tick supersedes a stale one, so they are fire-and-forget, not
    # tracked for resend. Everything else (hello, place, drop, ...) is
    # reliable. '_ack'/'_hb' are internal control types and never reliable.
    _UNRELIABLE_TYPES = frozenset({'s', 'p', '_hb', '_ack'})
    # Types where only the LATEST queued instance ever matters to the
    # caller, so a newly arrived one replaces (rather than queues behind)
    # a same-type message still sitting unread in the inbox. Includes the
    # unreliable per-tick Pong frames (s/p) AND '_rematch': unlike a game
    # move, a rematch decision is a single piece of intent that can change
    # (NET-8's cancel-then-recommit), and it IS still reliable/resent -- a
    # dropped '_rematch' must still be redelivered, it just must never be
    # handed to poll() out of date once a newer one has arrived.
    _COALESCE_TYPES = frozenset({'s', 'p', '_rematch'})
    _RESEND_INTERVAL = 0.3   # seconds before an unacked reliable message is resent
    _HEARTBEAT_INTERVAL = 1.0  # seconds of send-silence before a heartbeat goes out
    _PEER_TIMEOUT = 8.0      # seconds of receive-silence before we call it dead
    _MAX_BUF = 65536         # cap on unterminated inbound bytes (a misbehaving peer)

    def __init__(self, sock, role):
        self.sock = sock
        self.role = role          # 'host' or 'guest'
        self.sock.setblocking(False)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass  # best-effort; Nagle just costs a little latency, not correctness
        self._buf = b''
        self._outbuf = bytearray()
        self.alive = True
        self._next_seq = 0
        self._last_seq_in = 0
        self._pending = {}     # seq -> [raw_bytes, last_sent_monotonic]
        self._inbox = []       # decoded application messages awaiting poll()
        self._history = {}     # type -> [(recv_time, msg), ...] (last 2)
        now = time.monotonic()
        self._last_send_time = now
        self._last_recv_time = now  # grace period from construction, not first byte

    # ── outbound ──────────────────────────────────────────────────────────

    def send(self, obj):
        """Queue a message for delivery. Never blocks. Anything other than
        Pong's per-tick 's'/'p' frames is resent automatically until acked,
        so a single dropped frame cannot desync a turn-based game."""
        if not self.alive:
            return
        msg = dict(obj)
        reliable = msg.get('type') not in self._UNRELIABLE_TYPES
        if reliable:
            self._next_seq += 1
            seq = self._next_seq
            msg['_seq'] = seq
        raw = (json.dumps(msg) + '\n').encode('utf-8')
        if reliable:
            self._pending[seq] = [raw, time.monotonic()]
        self._enqueue(raw)

    def _send_control(self, obj):
        """Fire-and-forget control message (ack/heartbeat): never wrapped in
        a sequence number, never tracked for resend."""
        if not self.alive:
            return
        self._enqueue((json.dumps(obj) + '\n').encode('utf-8'))

    def _enqueue(self, raw):
        self._last_send_time = time.monotonic()
        self._outbuf.extend(raw)
        self._flush_outbuf()

    def _flush_outbuf(self):
        # sendall() on a non-blocking socket is the bug this replaces: it can
        # write PART of a line and then raise BlockingIOError for the rest,
        # and the old code just dropped that remainder, corrupting the
        # newline framing for every message after it. Here a partial write
        # just trims the front of the buffer and the rest waits for the next
        # pump()/send() to drain; nothing is ever dropped while the peer is
        # merely slow.
        while self._outbuf:
            try:
                n = self.sock.send(self._outbuf)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                self.alive = False
                self._outbuf.clear()
                self._pending.clear()
                return
            if n <= 0:
                return
            del self._outbuf[:n]

    # ── inbound ───────────────────────────────────────────────────────────

    def _recv_available(self):
        try:
            chunk = self.sock.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self.alive = False
            return
        if chunk == b'':
            self.alive = False  # clean FIN: peer closed the socket
            return
        self._last_recv_time = time.monotonic()
        self._buf += chunk
        if len(self._buf) > self._MAX_BUF and b'\n' not in self._buf:
            # A peer that never terminates a line would otherwise grow this
            # forever; treat it as a protocol violation, not a slow line.
            self.alive = False
            self._buf = b''

    # ── maintenance ───────────────────────────────────────────────────────

    def pump(self):
        """Drain queued output, resend any unacked reliable message, send a
        heartbeat if the link has been quiet, read whatever is available,
        fully parse it (see _drain_buf), and flip `alive` off if the peer
        has been silent past the timeout. Safe and cheap to call every loop
        iteration; poll() calls this too, so a game's net_pump() override
        only needs `self.net.pump()` to keep the link alive during a help
        overlay / resize / pause that would otherwise stop update() (and
        therefore the socket) from running (NET-2/NET-3).

        Parsing (not just reading) inbound bytes here, not only in poll(),
        matters: a caller that only ever calls pump() (exactly what the
        docstring above tells a net_pump() override to do) used to never
        clear _pending, because ack parsing lived exclusively in poll() -
        every reliable message would then be resent every
        _RESEND_INTERVAL forever, even after the peer had genuinely acked
        it."""
        if not self.alive:
            return
        now = time.monotonic()
        if self._outbuf:
            self._flush_outbuf()
        for entry in self._pending.values():
            raw, last_sent = entry
            if now - last_sent >= self._RESEND_INTERVAL:
                entry[1] = now
                self._outbuf.extend(raw)
        if self._outbuf:
            self._flush_outbuf()
        if now - self._last_send_time >= self._HEARTBEAT_INTERVAL:
            self._send_control({'type': '_hb'})
        self._recv_available()
        self._drain_buf()
        if self.alive and time.monotonic() - self._last_recv_time >= self._PEER_TIMEOUT:
            self.alive = False  # pulled cable / frozen peer: surface as a clean disconnect

    def _drain_buf(self):
        """Parse every complete newline-delimited line currently buffered.
        '_ack' and '_hb' control frames are fully handled right here (so
        pump() alone keeps resend/heartbeat bookkeeping correct with no
        poll() call at all); an application message is acked, dedup-
        checked, and queued in self._inbox for poll() to hand back."""
        while b'\n' in self._buf:
            line, self._buf = self._buf.split(b'\n', 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get('type')
            if t == '_ack':
                seq = msg.get('seq')
                if isinstance(seq, int):
                    for s in [s for s in self._pending if s <= seq]:
                        del self._pending[s]
                continue
            if t == '_hb':
                continue  # only exists to keep _last_recv_time fresh
            seq = msg.pop('_seq', None)
            if seq is not None:
                if not isinstance(seq, int):
                    # A malformed/version-skewed peer (or a corrupted-but-
                    # still-valid-JSON line) can put a non-int in '_seq'.
                    # The comparison below is `seq <= self._last_seq_in`,
                    # which raises TypeError for e.g. a str or crashes the
                    # whole game the next time this runs (net_pump()/
                    # update() call poll() every loop iteration and never
                    # guard it). Mirrors the isinstance check the '_ack'
                    # branch above already has: drop the frame instead of
                    # trusting attacker/peer-controlled ordering data.
                    continue
                self._send_control({'type': '_ack', 'seq': seq})
                if seq <= self._last_seq_in:
                    continue  # already delivered once; re-ack in case ours was lost
                self._last_seq_in = seq
            self._record_history(msg)
            if t in self._COALESCE_TYPES:
                # Per-tick fire-and-forget frames (Pong's 's'/'p'): the next
                # tick's message always supersedes a stale one. If a caller
                # is only pumping the link without draining it with poll()
                # (net_pump() during a help overlay, a pause, or the
                # _game_over_screen banner), these would otherwise queue up
                # unboundedly -- Pong alone streams ~62/s, so a host sitting
                # on the banner for a few minutes could pile up tens of
                # thousands of dicts to be replayed at once on the next
                # update(). Also covers '_rematch' (NET-8): a cancel or a
                # later recommit must supersede an earlier queued decision
                # rather than queue up behind it, so poll() can never hand
                # back a stale intent. Coalesce: replace the still-queued
                # frame of the same type instead of appending another one.
                for i, queued in enumerate(self._inbox):
                    if queued.get('type') == t:
                        self._inbox[i] = msg
                        break
                else:
                    self._inbox.append(msg)
            else:
                self._inbox.append(msg)

    def poll(self):
        """Return the next new application message dict, or None if none is
        ready. Acks, heartbeats, and duplicate deliveries of an already-seen
        reliable message are absorbed in pump()/_drain_buf() and never
        returned; at most one real message comes back per call, same as
        before."""
        self.pump()
        return self._inbox.pop(0) if self._inbox else None

    def poll_type(self, types):
        """Like poll(), but only ever returns a message whose 'type' is in
        `types`; anything else already queued is left in the inbox
        untouched instead of being discarded.

        NET-8: a caller that only understands a subset of message types
        (Pong's update() drains its own 's'/'p'/'serve' frames every tick)
        used to call plain poll() in a `while msg is not None` loop and
        silently drop every message of any OTHER type it pulled off the
        front of the queue in the process -- including the peer's
        already-acked (net.py's _drain_buf acks on receipt, independent of
        whether poll() ever hands the message back) and therefore
        never-resent '_rematch' frame, permanently losing it. Scanning for
        the first matching type and popping only that entry preserves
        everything else in arrival order for whoever polls for it next
        (here, _net_await_rematch after the game loop returns)."""
        self.pump()
        for i, msg in enumerate(self._inbox):
            if msg.get('type') in types:
                return self._inbox.pop(i)
        return None

    def _record_history(self, msg):
        t = msg.get('type')
        if t is None:
            return
        hist = self._history.setdefault(t, [])
        hist.append((time.monotonic(), msg))
        if len(hist) > 2:
            del hist[0]

    def history(self, type_):
        """Return (prev_msg, prev_ts, cur_msg, cur_ts) for the last two
        messages received of the given type, or None if fewer than two have
        arrived. Lets a caller interpolate toward the latest state instead of
        snapping to it, e.g. Pong's guest lerping the ball position between
        two host 's' frames instead of jumping on every 40 ms tick:

            h = link.history('s')
            if h:
                prev, prev_t, cur, cur_t = h
                span = max(1e-6, cur_t - prev_t)
                t = min(1.0, (time.monotonic() - cur_t) / span)
                draw_x = prev['bx'] + (cur['bx'] - prev['bx']) * t
        """
        hist = self._history.get(type_)
        if not hist or len(hist) < 2:
            return None
        (t0, m0), (t1, m1) = hist
        return m0, t0, m1, t1

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        self.alive = False
        self._outbuf.clear()
        self._pending.clear()


def _local_ip():
    """Best-effort primary LAN IP (no packet is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


# ─── Multiplayer lobby ───────────────────────────────────────────────────────

def _net_status(stdscr, lines):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    top = max(0, h // 2 - len(lines) // 2)
    for i, ln in enumerate(lines):
        attr = curses.A_BOLD if i == 0 else curses.color_pair(4)
        render._safe(stdscr, top + i, max(0, (w - len(ln)) // 2), ln, attr)
    stdscr.noutrefresh()
    curses.doupdate()


def _net_select(stdscr, title, options):
    """Vertical picker; returns the chosen index, or None on ESC."""
    sel = 0
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        render._safe(stdscr, h // 2 - len(options) - 2, max(0, (w - len(title)) // 2),
              title, curses.A_BOLD)
        for i, opt in enumerate(options):
            y = h // 2 - len(options) // 2 + i
            label = f'  {opt}  '
            attr = (curses.A_REVERSE | curses.A_BOLD) if i == sel else 0
            render._safe(stdscr, y, max(0, (w - len(label)) // 2), label, attr)
        render._safe(stdscr, h // 2 + len(options) // 2 + 2, max(0, (w - 22) // 2),
              'Enter: OK    ESC: Back', curses.color_pair(4))
        stdscr.noutrefresh()
        curses.doupdate()
        k = stdscr.getch()
        if k in (curses.KEY_UP, ord('w'), ord('k')):
            sel = (sel - 1) % len(options)
        elif k in (curses.KEY_DOWN, ord('s'), ord('j')):
            sel = (sel + 1) % len(options)
        elif k in (curses.KEY_ENTER, 10, 13):
            return sel
        elif k in (27, ord('q')):
            return None


def _net_text_input(stdscr, prompt, default=''):
    """Read a short line of text; returns the string, or None on ESC."""
    buf = list(default)
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        render._safe(stdscr, h // 2 - 1, max(0, (w - len(prompt)) // 2), prompt,
              curses.A_BOLD)
        shown = '> ' + ''.join(buf)
        render._safe(stdscr, h // 2 + 1, max(0, (w - 40) // 2), shown,
              curses.color_pair(3) | curses.A_BOLD)
        render._safe(stdscr, h // 2 + 3, max(0, (w - 22) // 2),
              'Enter: OK    ESC: Back', curses.color_pair(4))
        stdscr.noutrefresh()
        curses.doupdate()
        k = stdscr.getch()
        if k in (curses.KEY_ENTER, 10, 13):
            break
        if k in (27,):
            buf = None
            break
        if k in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= k < 127 and len(buf) < 30:
            buf.append(chr(k))
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    return None if buf is None else ''.join(buf).strip()


def _net_await(link, timeout):
    """Block (briefly) for the next message, or None on timeout/disconnect."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not link.alive:
            return None
        msg = link.poll()
        if msg is not None:
            return msg
        time.sleep(0.02)
    return None


def _net_await_rematch(stdscr, link, want_rematch):
    """NET-8: run the actual rematch request/agree round trip after a net
    game ends. Each side already decided its own intent at the game-over
    screen (R = wants a rematch, Q/ESC = doesn't); that used to be applied
    unilaterally -- pressing R replayed the game on this side regardless of
    what the peer chose, which is exactly the "rematch" that wasn't one.
    Send our intent, and if we asked for a rematch, wait for the peer's
    reply; only return True when BOTH sides agreed. If we didn't ask for a
    rematch there is nothing to wait for: the send() above already tells the
    peer not to expect one.

    A cancel (ESC while waiting) sends a second '_rematch' message with
    'want': False, superseding the {'want': True} sent on entry. Both are
    reliable (ordered, acked) messages, so a later one always arrives after
    the earlier one -- but they used to still desync, because
    _NetLink._drain_buf queued every reliable message it received and
    poll() handed them back FIFO, oldest first. If both of our messages
    (True, then False) were already sitting in the peer's socket buffer by
    the time it first polled (the common case: a player hits R then ESC
    within a second or two, well under normal round-trip time), the peer's
    first poll() call returned the STALE True and committed to a rematch;
    the superseding False then sat unread in the inbox forever. Proven:
    peer presses R a second after we already sent True-then-False -> peer's
    _net_await_rematch wrongly returns True, starts a new game, and its
    first pump finds the link we already closed. _NetLink now coalesces
    '_rematch' the same way it already coalesced Pong's per-tick 's'/'p'
    frames (see _COALESCE_TYPES): a newly arrived one replaces any
    still-queued one of the same type instead of piling up behind it, so
    poll() can only ever hand back the LATEST intent, never a stale one.
    """
    link.send({'type': '_rematch', 'want': want_rematch})
    if not want_rematch:
        return False
    stdscr.nodelay(True)
    stdscr.timeout(100)
    banner = ['Waiting for opponent...', '', 'Esc: cancel']
    try:
        _net_status(stdscr, banner)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if not link.alive:
                return False
            msg = link.poll()
            if msg is not None and msg.get('type') == '_rematch':
                return bool(msg.get('want'))
            k = stdscr.getch()
            if k == curses.KEY_RESIZE:
                # _game_over_screen (game.py) redraws on KEY_RESIZE; this
                # screen used to ignore it entirely, so resizing while
                # waiting for the peer's rematch answer left a stale,
                # mis-centred banner on screen for up to the 30s deadline.
                try:
                    curses.resize_term(0, 0)
                except curses.error:
                    pass
                _net_status(stdscr, banner)
                continue
            if k in (27, ord('q')):
                link.send({'type': '_rematch', 'want': False})
                return False
    finally:
        stdscr.nodelay(False)
    return False  # peer never answered in time; treat like a decline


def _net_handshake(stdscr, link, game_key):
    link.send({'type': 'hello', 'proto': NET_PROTOCOL, 'game': game_key})
    hello = _net_await(link, 6.0)
    ok = (hello and hello.get('proto') == NET_PROTOCOL
          and hello.get('game') == game_key)
    if not ok:
        _net_status(stdscr, ['Handshake failed',
                             'The other side is on a different game or version.',
                             '', 'Press any key to go back'])
        stdscr.nodelay(False)
        stdscr.getch()
        link.close()
    return ok


def _net_host_wait(stdscr, game_key):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR on Windows permits binding a port that is ALREADY actively
    # listening (unlike POSIX, where it only affects TIME_WAIT reuse), so two
    # hosts on one box would both "succeed" and joins would land on whichever
    # one the OS felt like. SO_EXCLUSIVEADDRUSE is the Windows-correct knob;
    # elsewhere SO_REUSEADDR is still what you want (a quick restart must not
    # fail to bind while the old socket lingers in TIME_WAIT).
    if sys.platform == 'win32' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(('0.0.0.0', NET_DEFAULT_PORT))
    except OSError as e:
        _net_status(stdscr, [f'Cannot open port {NET_DEFAULT_PORT}', str(e),
                             '', 'Press any key to go back'])
        stdscr.nodelay(False)
        stdscr.getch()
        srv.close()
        return None
    srv.listen(1)
    srv.settimeout(0.25)
    ip = _local_ip()
    stdscr.nodelay(True)
    conn = None
    while True:
        _net_status(stdscr, [f'Hosting {game_key.upper()}', '',
                             f'Tell your opponent to Join at:',
                             f'    {ip} : {NET_DEFAULT_PORT}', '',
                             'Waiting for a player...   (ESC to cancel)'])
        try:
            conn, _addr = srv.accept()
            break
        except (socket.timeout, BlockingIOError):
            pass
        except OSError:
            break
        if stdscr.getch() in (27, ord('q')):
            break
    stdscr.nodelay(False)
    srv.close()
    if conn is None:
        return None
    link = _NetLink(conn, 'host')
    return link if _net_handshake(stdscr, link, game_key) else None


def _net_join_connect(stdscr, game_key):
    ip = _net_text_input(stdscr, "Host's IP address (blank = 127.0.0.1):", '')
    if ip is None:
        return None
    if not ip:
        ip = '127.0.0.1'
    _net_status(stdscr, [f'Connecting to {ip}:{NET_DEFAULT_PORT} ...'])
    try:
        sock = socket.create_connection((ip, NET_DEFAULT_PORT), timeout=6.0)
    except OSError as e:
        _net_status(stdscr, [f'Could not connect to {ip}', str(e),
                             '', 'Press any key to go back'])
        stdscr.nodelay(False)
        stdscr.getch()
        return None
    link = _NetLink(sock, 'guest')
    return link if _net_handshake(stdscr, link, game_key) else None


def _net_menu(stdscr):
    if not _HAS_CURSES:
        return
    theme.init_colors()
    gi = _net_select(stdscr, 'MULTIPLAYER (LAN)   choose a game',
                     [g[0] for g in _NET_GAMES])
    if gi is None:
        return
    name, cls, key = _NET_GAMES[gi]
    ri = _net_select(stdscr, f'{name}   host or join?',
                     ['Host  (wait for a player)', 'Join  (connect to a host)'])
    if ri is None:
        return
    is_host = (ri == 0)
    link = (_net_host_wait(stdscr, key) if is_host
            else _net_join_connect(stdscr, key))
    if link is None:
        return
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    theme.init_colors()
    stdscr.nodelay(False)
    try:
        # NET-8: replay on the same connection only if BOTH sides ask for a
        # rematch. game.run() now actually propagates its 'retry'/'quit'
        # result (previously discarded, so this side never saw its own
        # choice), and _net_await_rematch() exchanges that choice with the
        # peer over the link before either side commits to a new game --
        # pressing R no longer unilaterally replays regardless of what the
        # other player picked. If the peer disconnected instead, its socket
        # is already closed and link.alive is False, so we go straight back
        # to the lobby instead of waiting on a reply that will never come.
        while True:
            game = cls(stdscr)
            game.net = link
            if cls is PongGame:
                game.role = 'host' if is_host else 'guest'
            else:
                game.local_player = 1 if is_host else 2
            result = game.run()
            stdscr.nodelay(False)
            if not link.alive:
                break
            if not _net_await_rematch(stdscr, link, result == 'retry'):
                break
    finally:
        link.close()
        stdscr.nodelay(False)
