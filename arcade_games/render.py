"""Low-level curses drawing helpers.

These are the standalone versions of the Game.safe_addstr / center_text /
draw_box methods (play.py 291-312), factored out so both the Game base
class and the plain curses menu (which has no Game instance, e.g. the
difficulty selector and the main menu) can use the same drawing logic.
_safe (play.py 3637-3643) is the menu-level twin of safe_addstr; it is a
separate function in the original source (not a call to safe_addstr) and is
kept separate here too.

Also owns the ASCII fallback for legacy consoles: probe_ascii_mode() is
called once at startup (from terminal.py, before any curses window exists),
and every draw path that can emit box-drawing or block glyphs (safe_addstr,
_safe, draw_box) runs the text through the GLYPHS table when ascii_mode is
set, so callers never need their own fallback branch.
"""
import locale
import os

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None

# Detected once at startup by probe_ascii_mode(). True means the current
# console cannot represent box-drawing / block glyphs (legacy cp437/cp850
# Windows console, a dumb terminal, LANG=C, etc); every glyph in GLYPHS is
# then rewritten to its plain-ASCII equivalent before hitting curses.
ascii_mode = False

# unicode glyph -> plain-ASCII fallback. Covers single- and double-line
# box drawing, full/half block sprites, the quadrant glyphs Dino's sprites
# use (U+2596-259F), and the shade/star glyphs a couple of games use for
# decoration. Extend this table rather than hand-rolling a per-game
# fallback branch.
GLYPHS = {
    # single-line box drawing
    '┌': '+', '┐': '+', '└': '+', '┘': '+', '─': '-', '│': '|',
    '├': '+', '┤': '+', '┬': '+', '┴': '+', '┼': '+',
    # double-line box drawing (menu title)
    '╔': '+', '╗': '+', '╚': '+', '╝': '+', '═': '=', '║': '|',
    '╠': '+', '╣': '+', '╦': '+', '╩': '+', '╬': '+',
    # full/half blocks
    '█': '#', '▀': '#', '▄': '#', '▌': '#', '▐': '#',
    # quadrant blocks (Dino sprites)
    '▖': '.', '▗': '.', '▘': '.', '▝': '.',
    '▙': '#', '▚': '#', '▛': '#', '▜': '#', '▟': '#',
    # shades and decoration
    '░': '.', '▒': ':', '▓': '#', '★': '*', '☆': '*', '⚑': 'F',
}


def probe_ascii_mode(force=None):
    """Detect whether the active locale encoding can represent the glyphs
    in GLYPHS, and set the module-level ascii_mode flag accordingly. Call
    once at startup, after locale.setlocale (main.py already does this)
    and before any curses window is created.

    `force` lets a caller (or the ARCADE_GAMES_ASCII env var) override
    the probe outright, for testing on a real unicode terminal or forcing
    ascii on a console the probe cannot correctly detect.
    """
    global ascii_mode
    if force is None:
        env = os.environ.get('ARCADE_GAMES_ASCII')
        if env is not None:
            force = env not in ('', '0', 'false', 'False')
    if force is not None:
        ascii_mode = bool(force)
        return
    # locale.getpreferredencoding() (and sys.stdout.encoding, which reports
    # the same value) name the *Python text-layer* encoding, not what the
    # curses output layer can actually put on screen. On Windows, curses
    # comes from the windows-curses package, which talks to the console
    # through the wide-character Win32 console API (WriteConsoleW)
    # directly, bypassing that encoding entirely, so it renders Unicode box
    # and block glyphs correctly even when the process' ANSI code page is
    # cp1252 or another glyph-less legacy encoding. Probing the locale here
    # produced a false positive on exactly that setup: every draw call was
    # permanently downgraded to ASCII art on a console that could render
    # Unicode fine (proof: python -c "...; render.probe_ascii_mode();
    # print(locale.getpreferredencoding(False), render.ascii_mode)" printed
    # "cp1252 True" here, yet driving the real games with ascii_mode forced
    # off and reading back the drawn glyphs with instr() showed the real
    # Unicode glyphs rendered correctly). So do not guess from the locale
    # on Windows: trust the wide-character console path and start
    # optimistic; safe_addstr/_safe's own UnicodeEncodeError handler (the
    # thing that actually talks to curses) flips ascii_mode on for us if a
    # real console genuinely cannot take a glyph, which is the only place
    # that can honestly answer "can this console render this".
    if os.name == 'nt':
        ascii_mode = False
        return
    # Elsewhere (ncurses on Linux/Mac) the locale encoding is not a guess:
    # ncursesw's own UTF-8 output depends on locale.setlocale(LC_ALL, '')
    # having been called with a UTF-8 locale, so this probe is meaningful
    # there (a LANG=C / dumb-terminal session really cannot take the
    # glyphs).
    try:
        enc = locale.getpreferredencoding(False) or 'ascii'
        ''.join(GLYPHS).encode(enc)
        ascii_mode = False
    except (LookupError, UnicodeEncodeError, TypeError):
        ascii_mode = True


def glyph(ch):
    """Translate one glyph to its ASCII fallback when ascii_mode is set."""
    return GLYPHS.get(ch, ch) if ascii_mode else ch


def gtext(s):
    """Translate every glyph in a string. Cheap no-op when not ascii_mode."""
    if not ascii_mode:
        return s
    return ''.join(GLYPHS.get(c, c) for c in s)


def safe_addstr(stdscr, y, x, text, attr=0):
    global ascii_mode
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h:
        return
    if x < 0:
        # Clip the left side instead of dropping the whole string, so a
        # sprite that is half off the left edge still draws its visible
        # half (this is why Dino obstacles used to vanish at column -1).
        text = text[-x:]
        x = 0
    if x >= w or not text:
        return
    text = text[:max(0, w - x)]
    if not text:
        return
    if y == h - 1 and x + len(text) >= w:
        # Never attempt the literal bottom-right cell: writing it forces
        # curses to advance the cursor past the end of the window, which
        # raises (classic curses ERR). Stay one column short instead of
        # relying on the try/except below to paper over it.
        text = text[:max(0, w - 1 - x)]
        if not text:
            return
    if ascii_mode:
        text = gtext(text)
    try:
        stdscr.addstr(y, x, text, attr)
    except UnicodeEncodeError:
        # The console genuinely cannot take this glyph, which is the one
        # honest, empirical answer to "can this console render Unicode"
        # (see probe_ascii_mode's docstring: the startup probe can guess
        # wrong, e.g. on Windows). Flip the flag so every subsequent draw
        # goes through GLYPHS instead of repeating this failure once per
        # frame, and retry this one line immediately so it isn't lost.
        ascii_mode = True
        try:
            stdscr.addstr(y, x, gtext(text), attr)
        except (curses.error, UnicodeEncodeError):
            pass
    except curses.error:
        pass


def center_text(stdscr, w, y, text, attr=0):
    x = max(0, (w - len(text)) // 2)
    safe_addstr(stdscr, y, x, text, attr)


def draw_box(stdscr, y, x, h, w, attr=0):
    safe_addstr(stdscr, y, x, '┌' + '─' * (w - 2) + '┐', attr)
    for i in range(1, h - 1):
        safe_addstr(stdscr, y + i, x, '│', attr)
        safe_addstr(stdscr, y + i, x + w - 1, '│', attr)
    safe_addstr(stdscr, y + h - 1, x, '└' + '─' * (w - 2) + '┘', attr)


def status_bar(stdscr, h, w, text, attr=None):
    """Full-width reverse-video row for control hints, pinned to the last
    screen row. Always spans the full width (so it is never truncated or
    invisible the way six games' single safe_addstr hint lines were).

    `text` is either a plain string (clipped character-wise by safe_addstr,
    same as always, for the common case where a game's hints already fit
    at its own declared min_w) or a list/tuple of hint segments, normally
    given in the caller's natural reading order (movement first, escape
    hatches last). In the list form, segments are added greedily while they
    still fit, but the ESCAPE HATCHES ('esc'/'quit' and 'help'/'?' segments)
    are always considered FIRST regardless of where the caller put them in
    the list, so a game that (like a caller mistake) lists them last never
    loses them just because it also has more ordinary hints than columns.
    Once the kept set is decided, the segments are re-joined in the
    caller's original order so the line still reads naturally. The first
    non-essential segment that would not fit IN FULL is dropped, along with
    everything after it in priority order, instead of being cut off
    mid-word. This is what guarantees a hint never renders as a corrupted
    fragment AND that a game is never left with no way to discover how to
    quit or get help (INFRA-7): a game with more hints than columns loses
    its lowest-priority ones cleanly rather than showing a mangled tail or
    silently dropping its escape hatches. Existing precedent for dropping a
    whole hint rather than showing a fragment: minesweeper.py already
    dropped '?:Help' by hand at min_w=40; this makes that behavior systemic
    instead of a per-game manual count."""
    if attr is None:
        attr = curses.A_REVERSE if curses else 0
    if isinstance(text, (list, tuple)):
        # Budget = full width minus the bar's own leading space minus the
        # one column safe_addstr always keeps free on the last screen row
        # (the classic curses bottom-right-cell ERR guard).
        budget = max(0, w - 2)

        def _is_escape_hatch(seg):
            low = seg.lower()
            return any(k in low for k in ('esc', 'quit', 'help', '?'))

        essential = [s for s in text if _is_escape_hatch(s)]
        rest = [s for s in text if not _is_escape_hatch(s)]
        kept = set()
        used = 0
        count = 0
        for seg in essential + rest:
            add = len(seg) + (1 if count else 0)
            if used + add > budget:
                break
            kept.add(seg)
            used += add
            count += 1
        text = ' '.join(s for s in text if s in kept)
    bar = (' ' + text).ljust(w)
    safe_addstr(stdscr, h - 1, 0, bar, attr)


def _safe(stdscr, y, x, text, attr=0):
    global ascii_mode
    h, w = stdscr.getmaxyx()
    if not (0 <= y < h and 0 <= x < w):
        return
    text = text[:max(0, w - x)]
    if y == h - 1 and x + len(text) >= w:
        text = text[:max(0, w - 1 - x)]
    if not text:
        return
    if ascii_mode:
        text = gtext(text)
    try:
        stdscr.addstr(y, x, text, attr)
    except UnicodeEncodeError:
        # Same self-healing fallback as safe_addstr (see its comment):
        # trust curses' own answer over the startup probe's guess.
        ascii_mode = True
        try:
            stdscr.addstr(y, x, gtext(text), attr)
        except (curses.error, UnicodeEncodeError):
            pass
    except curses.error:
        pass
