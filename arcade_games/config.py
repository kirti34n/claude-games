"""Config directory, save files, and high score persistence.

NOTE: consumers must do 'from . import config' and reference
config.CONFIG_DIR / config.SCORES_FILE / config.GAME_STATE_FILE at call
time, never 'from .config import CONFIG_DIR'. The test suite monkeypatches
these three names on the module (see tests/test_games.py) to redirect all
save/score I/O into a temp directory; binding the bare names at import time
in another module would make that monkeypatch a silent no-op and cause
writes to the user's real ~/.config/arcade-games/.
"""
import json
import os
import tempfile
import time
from pathlib import Path

_CONFIG_BASE = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
CONFIG_DIR = _CONFIG_BASE / 'arcade-games'
SCORES_FILE = CONFIG_DIR / 'scores.json'
GAME_STATE_FILE = CONFIG_DIR / 'current_game.json'

# Every config-directory name this project has shipped under before the
# current one, ordered newest-first. The project was originally
# "claude-games", then renamed to "terminal-games", and is now
# "arcade-games". _migrate_config() below walks this whole chain so a player
# who last ran ANY prior version -- not just the immediately preceding one --
# still finds their saves and high scores after upgrading.
_LEGACY_CONFIG_NAMES = ('terminal-games', 'claude-games')


def _atomic_copy_file(src: Path, dest: Path) -> bool:
    """Copy src to dest via temp-file + os.replace (same crash/race safety as
    _atomic_write_json), then re-reads dest and compares it to what was
    read from src. Only a verified, byte-for-byte-identical copy returns
    True; the caller must not delete src unless this returns True, so a
    copy that failed or landed corrupted never costs the player their
    data -- worst case a legacy file is merely left behind for the next
    run to retry."""
    try:
        data = src.read_bytes()
    except OSError:
        return False
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent),
                                         prefix=f'.{dest.name}.', suffix='.tmp')
    except OSError:
        return False
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp_name, dest)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return False
    try:
        return dest.read_bytes() == data
    except OSError:
        return False


def _migrate_one_legacy_dir(old: Path):
    """Merge one legacy config directory into CONFIG_DIR, file by file.

    Deliberately not a single directory rename: CONFIG_DIR may already hold
    real current files (this version has run before, or an earlier legacy
    directory in the chain already landed some), so a rename could either
    fail outright or, worse, silently clobber current data. Merging instead:
    every legacy file that does not already exist at the new location is
    copied over (an existing new-location file is NEVER overwritten -- it
    always wins), and a legacy file is only ever deleted after
    _atomic_copy_file has verified it landed intact at the destination, so a
    failed or partial copy never loses data. Sub-directories (e.g. a stray
    nested folder) and lock files (stale mutexes from an old process, never
    meaningful data) are left untouched. The legacy directory itself is only
    removed once nothing is left inside it; if anything could not be copied,
    it stays behind for the next run to retry.
    """
    try:
        if not old.is_dir():
            return
        entries = list(old.iterdir())
    except OSError:
        return
    _ensure_config()
    for entry in entries:
        try:
            if not entry.is_file() or entry.name.endswith(_LOCK_SUFFIX):
                continue
        except OSError:
            continue
        dest = CONFIG_DIR / entry.name
        if dest.exists():
            continue  # a real file already at the new location always wins
        if _atomic_copy_file(entry, dest):
            try:
                entry.unlink()
            except OSError:
                pass  # copy is verified either way; a leftover source is harmless
    try:
        next(old.iterdir())  # anything left (uncopyable file, subdir)?
    except StopIteration:
        try:
            old.rmdir()
        except OSError:
            pass
    except OSError:
        pass


def _migrate_config():
    """One-time move of saves/scores from every pre-rename config directory
    into CONFIG_DIR, newest legacy name first. Safe to call on every
    startup: already-migrated data is a no-op (every destination file
    already exists), and a legacy directory that no longer exists is
    skipped instantly."""
    for legacy_name in _LEGACY_CONFIG_NAMES:
        old = _CONFIG_BASE / legacy_name
        if old != CONFIG_DIR:
            _migrate_one_legacy_dir(old)


def _ensure_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path, data, _retries=5, _delay=0.001) -> bool:
    """Write JSON via a temp file in the same directory + os.replace, so a
    crash mid-write (or a second `play` process racing this one) never
    leaves a truncated or half-written save/score file. Every JSON writer
    in the package routes through this.

    On Windows, os.replace (MoveFileExW under the hood) can fail with
    PermissionError (WinError 5) when another handle merely has the
    destination file open for reading (CPython's open() does not request
    FILE_SHARE_DELETE) -- this happens routinely here: two `play` processes
    racing this writer, or even just a concurrent config.load_high_score()
    reading the file at the wrong instant. That is a transient contention
    error, not a real failure.

    This used to escape uncaught and crash the whole game (e.g. out of
    Game._game_over_screen the instant a player finished a run), and the
    retry loop that was added to catch it used a 40 x 10 ms budget (up to
    400 ms) that instead turned every save into a synchronous UI stall.
    Persisting a high score or a save file is best-effort, never a
    correctness requirement: losing one write is acceptable, blocking the
    player's game (or worse, crashing it) at the moment they finish it is
    not. So this function never raises. The retry budget is now just long
    enough to ride out the common transient case -- a concurrent reader
    that has the destination open for the few microseconds around its own
    open/read/close -- a handful of milliseconds at most, then it gives up
    quietly and the write is simply lost.

    Callers for whom a lost write IS a correctness problem (save_high_score:
    dropping the replace there loses the player's high score outright) pass a
    bigger _retries/_delay budget. They can afford it because they are not on
    a per-frame path, and they check the returned bool. Returns True if the
    data actually landed at `path`."""
    path = Path(path)
    try:
        _ensure_config()
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=f'.{path.name}.', suffix='.tmp')
    except OSError:
        return False  # can't even create the temp file (e.g. read-only fs): give up quietly
    replaced = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        for attempt in range(_retries):
            try:
                os.replace(tmp_name, path)
                replaced = True
                break
            except OSError:
                if attempt < _retries - 1:
                    time.sleep(_delay)
    except OSError:
        pass
    finally:
        if not replaced:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return replaced


def game_state_file(name: str) -> Path:
    """Per-game CLI state file. GAME_STATE_FILE itself now holds only a
    small pointer ({'game': name}) to whichever CLI game is currently
    active, so `play cli start 2048` no longer clobbers an in-progress CLI
    snake: each game gets its own file, keyed off GAME_STATE_FILE's own
    (possibly test-monkeypatched) directory."""
    return GAME_STATE_FILE.parent / f'cli_state_{name}.json'


def _is_score(value) -> bool:
    """A stored high score is an int and nothing else. bool is an int
    subclass in Python, so exclude it explicitly; a JSON string/float/list/
    null in a score slot is corrupt data, and feeding it to max() (writer) or
    to `hi > 0` (menu.py) raises TypeError."""
    return isinstance(value, int) and not isinstance(value, bool)


def load_high_score(name: str) -> int:
    """Never raises: a missing, unreadable, malformed, or hand-mangled
    scores.json reads back as "no high score", it does not take down the
    menu (which calls this once per game per redraw) or a game's setup()."""
    try:
        data = json.loads(SCORES_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):  # missing / unreadable / not JSON
        return 0
    if not isinstance(data, dict):  # e.g. a JSON list, string, number, or null
        return 0
    value = data.get(name, 0)
    return value if _is_score(value) else 0


# --- save_high_score locking -------------------------------------------
#
# save_high_score is an unlocked read-modify-write: read scores.json,
# bump one game's entry, write the whole dict back. Two `play` processes
# finishing a game at the same instant (which _open_in_terminal actively
# encourages -- players routinely have several games running at once)
# race that read-modify-write. Without serialization, whichever process
# writes second overwrites whichever the first one wrote, silently
# dropping the other game's update.
#
# _FileLock below closes that window with a tiny cross-process mutex
# built on O_CREAT|O_EXCL (atomic on every platform, unlike a portalocker
# dependency this project doesn't have). It is deliberately best-effort:
# if the lock can't be acquired within its short retry budget, the caller
# gives up and skips the write rather than proceeding unsynchronized --
# losing one high score update is acceptable (DEFECT 1's own framing);
# corrupting another game's score is not.
_LOCK_SUFFIX = '.lock'
# A save that gives up because it lost the lock race is a LOST HIGH SCORE --
# the very thing this lock exists to prevent -- so the acquire budget has to
# be big enough to actually ride out contention, not just glance at it. The
# old 80ms budget was not: with several `play` processes finishing games at
# once (plus the menu hammering scores.json with reads), writers routinely
# blew past it and silently dropped the player's score.
#
# These numbers are worst-case-under-contention, not typical: an uncontended
# acquire is a single O_EXCL create (microseconds), and a contended one only
# waits as long as the holder's critical section, which is a read plus an
# atomic write. save_high_score runs at game over and in `play cli`, never on
# a frame path, so even the pathological end of this budget cannot read as a
# stall in gameplay.
_LOCK_TIMEOUT = 3.0
_LOCK_DELAY = 0.002
# A holder can legitimately sit in its critical section for as long as its
# os.replace retry budget (_SCORES_WRITE_RETRIES * _SCORES_WRITE_DELAY below,
# ~0.5s) while a concurrent reader keeps the destination open. The stale
# threshold must therefore stay comfortably ABOVE that, or one slow-but-alive
# writer's lock gets broken out from under it and two writers end up in the
# read-modify-write at once -- which is exactly the clobber this lock exists
# to prevent. It must also stay BELOW _LOCK_TIMEOUT so a lock left behind by
# a crashed process is always broken inside a waiter's own budget instead of
# wedging high-score saving until the next reboot.
_LOCK_STALE_SECONDS = 1.0
# Neither half of the read-modify-write may lose the player's score to a
# transient Windows sharing violation (a concurrent reader or writer holding
# scores.json open across our read / our os.replace), so both retry far
# longer than the default best-effort budget: ~80 * 3ms = up to ~0.24s each,
# and in practice a fraction of one millisecond. Aborting the save on the
# first transient read error (which is all the previous fix did) protected
# the OTHER games' scores but still threw THIS game's score away -- a
# transient error means "try again in a moment", not "give up".
#
# read + write worst case (~0.5s) stays under _LOCK_STALE_SECONDS so a slow
# holder is never mistaken for a dead one and broken out from under.
_SCORES_IO_RETRIES = 80
_SCORES_IO_DELAY = 0.003


class _FileLock:
    """Tiny cross-process mutual-exclusion lock guarding the
    read-modify-write in save_high_score. Never raises: acquire() returns
    False on any failure (lock held elsewhere, can't create the lock
    file, ...) instead of throwing, so a save that can't be safely
    serialized is simply skipped rather than crashing the game."""

    def __init__(self, target_path):
        self._lock_path = Path(str(target_path) + _LOCK_SUFFIX)
        self._fd = None

    def acquire(self, timeout=_LOCK_TIMEOUT, delay=_LOCK_DELAY) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._fd = os.open(str(self._lock_path),
                                    os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return True
            except FileExistsError:
                self._break_if_stale()
            except OSError:
                pass  # e.g. read-only fs: no lock file possible, keep retrying the budget out
            if time.monotonic() >= deadline:
                return False
            time.sleep(delay)

    def _break_if_stale(self):
        try:
            age = time.time() - self._lock_path.stat().st_mtime
        except OSError:
            return  # already gone (another process cleared it): nothing to break
        if age > _LOCK_STALE_SECONDS:
            try:
                os.unlink(str(self._lock_path))
            except OSError:
                pass  # lost the race to remove it, or it's already gone: either is fine

    def release(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            os.unlink(str(self._lock_path))
        except OSError:
            pass


# "The read failed, the data is still there" -- a sentinel distinct from
# EVERY possible JSON value. None is not: `null` is valid JSON, so a
# scores.json containing exactly `null` used to parse to None and be
# mistaken for a transient read failure forever, permanently wedging
# high-score saving (and crashing every reader with AttributeError).
_READ_FAILED = object()


def _quarantine_scores() -> bool:
    """Move a genuinely corrupt scores.json aside instead of overwriting it,
    so whatever it held is recoverable. Never clobbers an earlier quarantine.
    Returns False if it could not be moved -- in which case the caller must
    NOT write over it: an unreadable file we failed to preserve is the one
    thing we are not allowed to destroy."""
    dest = Path(str(SCORES_FILE) + '.bad')
    if dest.exists():
        dest = Path(f'{SCORES_FILE}.bad.{int(time.time() * 1000)}')
    try:
        os.replace(str(SCORES_FILE), str(dest))
        return True
    except OSError:
        return False


def _read_scores_for_update():
    """Read scores.json for the read-modify-write in save_high_score.

    Returns {} when there is legitimately no file yet -- FileNotFoundError
    is the ONLY condition that means "no scores saved yet, start empty".
    Returns _READ_FAILED when the read failed for any other reason: a
    transient OSError (e.g. the Windows PermissionError a concurrent
    writer's os.replace can cause while it's mid-rename) means the data is
    there but momentarily unreadable, not that it doesn't exist. Callers
    must treat _READ_FAILED as "abort the write, touch nothing" -- treating
    it as empty was DEFECT 1: it silently wiped every other game's high
    score on every transient read failure.

    Anything that parses but is not a {name: int} object is genuinely
    corrupt (hand-edited, disk fault, truncated by a pre-atomic-write
    version): invalid JSON, and equally a JSON list/string/number/null,
    which parse fine and then blow up with AttributeError/TypeError in the
    caller. This function only ever runs while save_high_score holds the
    cross-process lock, and every writer writes atomically (temp file +
    os.replace), so a torn write from a cooperating process is impossible
    here -- corrupt means corrupt. Quarantine the file instead of silently
    overwriting it, and if the quarantine itself fails, abort the write
    rather than destroy the data.

    A single junk VALUE inside an otherwise good object ({"snake": "abc"})
    is not grounds for throwing the whole file away: drop that one entry and
    keep every other game's real score.
    """
    text = _READ_FAILED
    for attempt in range(_SCORES_IO_RETRIES):
        try:
            text = SCORES_FILE.read_text(encoding='utf-8')
            break
        except FileNotFoundError:
            return {}
        except OSError:
            # Transient (sharing violation / EBUSY): the data is there, it is
            # just momentarily unreadable. Ride it out instead of dropping
            # this game's score on the floor.
            if attempt < _SCORES_IO_RETRIES - 1:
                time.sleep(_SCORES_IO_DELAY)
    if text is _READ_FAILED:
        return _READ_FAILED
    try:
        data = json.loads(text)
    except ValueError:
        data = None  # not JSON at all
        if not _quarantine_scores():
            return _READ_FAILED
        return {}
    if not isinstance(data, dict):
        if not _quarantine_scores():
            return _READ_FAILED
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and _is_score(v)}


def save_high_score(name: str, score: int):
    if not _is_score(score):
        try:
            score = int(score)  # e.g. a score field restored from a save file
        except (TypeError, ValueError):
            return
    _ensure_config()
    lock = _FileLock(SCORES_FILE)
    if not lock.acquire():
        return  # another process holds it past our budget: skip this save, don't race it
    try:
        scores = _read_scores_for_update()
        if scores is _READ_FAILED:
            return  # transient read failure: preserve the file, do not clobber it
        scores[name] = max(score, scores.get(name, 0))
        _atomic_write_json(SCORES_FILE, scores,
                            _retries=_SCORES_IO_RETRIES,
                            _delay=_SCORES_IO_DELAY)
    finally:
        lock.release()
