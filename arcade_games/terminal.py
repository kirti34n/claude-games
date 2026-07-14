"""Launching the game in a real terminal window/pane, and the curses wrapper
that falls back to opening one when there is no TTY (e.g. piped environments
like Claude Code)."""
import os
import sys

try:
    import curses
except ImportError:
    # curses is not bundled with CPython on Windows. The interactive games need
    # it (install `windows-curses`), but the turn-based `play cli` mode and all
    # text commands must still work without it, so we degrade gracefully.
    curses = None

from . import render

_HAS_CURSES = curses is not None


def _has_display():
    """Best-effort check for a usable X11/Wayland display, so the GUI
    terminal-emulator fallbacks below don't Popen a process that will just
    fail to connect and silently do nothing (INFRA-11)."""
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def _open_in_terminal(game_args: str = ''):
    """Launch the game in a split pane or new window (for piped environments like Claude Code)."""
    import shutil
    import subprocess
    # "arcade" is the primary console script; "play" is kept as a second
    # entry point for existing installs (and because "play" collides with
    # `sox` on some systems), so look for the new name first and fall back
    # to the old one before finally falling back to argv[0] itself.
    play_bin = shutil.which('arcade') or shutil.which('play') or sys.argv[0]
    game_argv = game_args.split()

    # Every non-Windows branch below ultimately runs the command through
    # `bash -lc` (needed to get the user's PATH/aliases/rc file in a fresh
    # pane), but interpolating play_bin/game_args into a single shell
    # STRING means bash re-parses it as shell syntax: a play_bin containing
    # a space still splits into two words, and a '"'/'$'/backtick in it is
    # live shell syntax, not a literal path character (INFRA-11). Passing
    # play_bin and each argument as separate argv elements to a fixed,
    # literal wrapper script instead means bash never re-interprets any of
    # them: "$0" and "$@" are substituted, not parsed.
    bash_argv = ['bash', '-lc', 'exec "$0" "$@"', play_bin] + game_argv

    # Native Windows: open the game in its own new console window. Use an argv
    # list + CREATE_NEW_CONSOLE so subprocess quotes paths that contain spaces
    # (e.g. C:\Program Files\...) correctly, instead of a shell string.
    if os.name == 'nt':
        try:
            if play_bin.endswith('.py'):
                argv = [sys.executable, play_bin]
            else:
                argv = [play_bin]
            argv += game_argv
            subprocess.Popen(argv, creationflags=subprocess.CREATE_NEW_CONSOLE)
            return True
        except Exception:
            return False

    # Prefer tmux split pane: game runs alongside Claude in the same terminal
    tmux = shutil.which('tmux')
    if tmux and os.environ.get('TMUX'):
        subprocess.Popen(
            [tmux, 'split-window', '-h', '-l', '50%'] + bash_argv,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # WSL2: use Windows Terminal tab
    wt = shutil.which('wt.exe')
    if wt:
        subprocess.Popen([wt, 'wsl.exe', '--'] + bash_argv,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # tmux available but not in a session: start one with the game
    if tmux:
        subprocess.Popen(
            [tmux, 'new-session', '-d', '-s', 'play'] + bash_argv,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # Fallback: try common Linux terminals. These all need a real X11/Wayland
    # display; without one the emulator process exits immediately and we'd
    # otherwise report "Opened in a new terminal window" for nothing
    # (INFRA-11).
    if not _has_display():
        return False
    for term in ('gnome-terminal', 'xterm', 'konsole', 'xfce4-terminal'):
        t = shutil.which(term)
        if t:
            if term == 'gnome-terminal':
                subprocess.Popen([t, '--'] + bash_argv,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen([t, '-e'] + bash_argv,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


def _curses_wrapper(func, game_name: str = ''):
    """Like curses.wrapper but opens a new terminal window when no TTY is available."""
    if not _HAS_CURSES:
        print("The interactive games need Python's curses module, which isn't "
              "available here.", file=sys.stderr)
        if os.name == 'nt':
            print("On Windows, install it with:  pip install windows-curses",
                  file=sys.stderr)
        print("Or play the turn-based versions with no terminal needed:\n"
              "  play cli start snake   (also: 2048, minesweeper, connect4)",
              file=sys.stderr)
        sys.exit(1)
    render.probe_ascii_mode()
    if sys.stdin.isatty() and sys.stdout.isatty():
        return curses.wrapper(func)

    # No TTY: try to open in a split pane or new window
    if _open_in_terminal(game_name):
        name = game_name or 'game menu'
        if os.environ.get('TMUX'):
            print(f'Opened {name} in a tmux split pane. Switch with Ctrl-B + arrow keys.')
        else:
            print(f'Opened {name} in a new terminal window.')
        return
    print("No terminal available. Run 'play' directly in your terminal.", file=sys.stderr)
    sys.exit(1)
