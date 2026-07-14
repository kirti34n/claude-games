"""Shared virtual-chip currency for the casino games (Blackjack, Roulette,
Slots). Wordle does NOT use this module.

Chips are virtual and in-app only. Nothing in this module, and nothing any
game built on top of it may add, provides a purchase, deposit, withdrawal,
cash-out, or conversion of chips to anything of real-world value. See
SPEC4.md section 0 and section 7: this is a hard requirement, not a
preference.

Persistence reuses config.py's EXISTING locked, atomic, byte-verified write
path (config._FileLock and config._atomic_write_json) instead of
hand-rolling a new writer. config.save_high_score was previously caught
destroying every player's high scores with an unlocked read-modify-write
whose read-failure path reset the whole dict to empty; this module takes
the same lock-then-read-then-write shape that fixed that bug and applies it
to chips.json, plus its own read-failure handling that never treats "the
file was momentarily unreadable" as "the player has no chips".

chips.json shape: {"balance": int, "last_bailout_date": "YYYY-MM-DD" | null}

Consumers (the casino games) should only ever call the public functions
below (balance, bet, payout, bailout_available, try_bailout) -- never read
or write chips.json directly, and never cache a balance across frames
without re-calling balance().
"""
import json
import time
from datetime import date
from pathlib import Path

from . import config

# Starting balance, granted implicitly the first time the balance is ever
# queried or mutated (see _default_state / _load_state_readonly): there is
# no explicit "first run" step to remember to call, chips.json simply does
# not exist yet and every reader treats that as "1000, untouched".
STARTING_BALANCE = 1000
BAILOUT_AMOUNT = 100
CHIPS_FILENAME = 'chips.json'

# IO/lock retry budget for the chips.json read-modify-write. Mirrors
# config.py's save_high_score budget (see the long comment block on
# _LOCK_TIMEOUT / _SCORES_IO_RETRIES there for the full reasoning): a bet or
# payout is not a per-frame operation, it happens once per player action, so
# it can afford to wait out the same worst-case Windows sharing-violation
# window that save_high_score waits out, rather than dropping chips on the
# floor the first time two casino games' processes touch the file at once.
_IO_RETRIES = 80
_IO_DELAY = 0.003
_LOCK_TIMEOUT = 3.0
_LOCK_DELAY = 0.002

# A sentinel distinct from every possible JSON value (including `null`,
# which is valid JSON and must not be confused with "the read failed"). See
# config._READ_FAILED for the identical reasoning.
_READ_FAILED = object()


def _chips_path() -> Path:
    """config.CONFIG_DIR must be read here, at call time, never bound to a
    module-level constant -- the test suite monkeypatches config.CONFIG_DIR
    to redirect all I/O into a temp dir, and binding the path once at import
    time would make that monkeypatch a silent no-op, sending test writes at
    a real player's ~/.config/arcade-games/chips.json."""
    return config.CONFIG_DIR / CHIPS_FILENAME


def _today_iso() -> str:
    return date.today().isoformat()


def _default_state() -> dict:
    return {'balance': STARTING_BALANCE, 'last_bailout_date': None}


def _is_valid_state(data) -> bool:
    if not isinstance(data, dict):
        return False
    bal = data.get('balance')
    # bool is an int subclass in Python; exclude it explicitly, same reason
    # as config._is_score.
    if not isinstance(bal, int) or isinstance(bal, bool) or bal < 0:
        return False
    lbd = data.get('last_bailout_date')
    if lbd is not None and not isinstance(lbd, str):
        return False
    return True


def _quarantine_chips(path: Path) -> bool:
    """Move a genuinely corrupt chips.json aside instead of overwriting it,
    so whatever it held is recoverable -- mirrors config._quarantine_scores.
    Returns False if it could not be moved, in which case the caller must
    NOT write over it."""
    dest = Path(str(path) + '.bad')
    if dest.exists():
        dest = Path(f'{path}.bad.{int(time.time() * 1000)}')
    try:
        path.replace(dest)
        return True
    except OSError:
        return False


def _read_state_for_update(path: Path):
    """Read chips.json for the locked read-modify-write. Only ever called
    while the caller holds the cross-process lock on `path`.

    Returns a valid {'balance': int, 'last_bailout_date': str|None} dict.
    FileNotFoundError means "this player has never had a chips.json
    written yet" and returns the default starting state -- NOT an error.
    Any other read failure is transient (e.g. a concurrent writer's
    os.replace holding the destination open on Windows) and returns
    _READ_FAILED, which every caller must treat as "abort the mutation,
    touch nothing": treating a transient failure as "start over" would
    silently refill a broke player's balance for free on every hiccup, and
    treating it as "empty" the way the old save_high_score bug did would
    lose their real balance outright.

    A file that parses but holds a structurally invalid state (hand-edited,
    truncated by a pre-atomic-write version, disk fault) is genuinely
    corrupt: quarantine it (never silently overwrite it) and fall back to
    the default state. If the quarantine itself fails, abort instead of
    destroying the only copy of whatever was there.
    """
    text = _READ_FAILED
    for attempt in range(_IO_RETRIES):
        try:
            text = path.read_text(encoding='utf-8')
            break
        except FileNotFoundError:
            return _default_state()
        except OSError:
            if attempt < _IO_RETRIES - 1:
                time.sleep(_IO_DELAY)
    if text is _READ_FAILED:
        return _READ_FAILED
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not _is_valid_state(data):
        if not _quarantine_chips(path):
            return _READ_FAILED
        return _default_state()
    return data


def _load_state_readonly() -> dict:
    """Unlocked read for read-only queries (balance(), bailout_available()).
    Never raises and never writes: a missing or corrupt chips.json reads
    back as the default starting state rather than throwing out of a status
    bar draw. Only the mutating operations (bet/payout/try_bailout) need
    the cross-process lock, because only they write."""
    try:
        text = _chips_path().read_text(encoding='utf-8')
    except OSError:
        return _default_state()
    try:
        data = json.loads(text)
    except ValueError:
        return _default_state()
    return data if _is_valid_state(data) else _default_state()


def balance() -> int:
    """Current chip balance. Read-only and unlocked (never mutates or even
    creates chips.json), safe to call every frame for a status bar. A
    player who has never bet, paid out, or been bailed out simply reads
    back STARTING_BALANCE (1000) forever, with nothing persisted, until the
    first real mutation happens."""
    return _load_state_readonly()['balance']


def bet(n: int) -> bool:
    """Debit n chips from the balance. n must be a positive int.

    Returns True if the debit was applied and durably persisted. Returns
    False, with the balance left completely untouched, in every other
    case: n is not a positive int, n exceeds the current balance (the
    overdraw refusal -- callers should already clamp a bet's UI input to
    balance(), but bet() enforces the refusal unconditionally so a caller
    bug can never drive the balance negative), or the write could not be
    safely persisted (lock contention timeout, transient IO failure).
    Balance can never go negative: this is the only debit path in the
    module, and it never subtracts more than the balance it just read
    under the lock.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return False
    config._ensure_config()
    path = _chips_path()
    lock = config._FileLock(path)
    if not lock.acquire(timeout=_LOCK_TIMEOUT, delay=_LOCK_DELAY):
        return False
    try:
        state = _read_state_for_update(path)
        if state is _READ_FAILED:
            return False
        if n > state['balance']:
            return False  # refuse the overdraw: nothing changed, nothing written
        state['balance'] -= n
        return config._atomic_write_json(path, state,
                                          _retries=_IO_RETRIES, _delay=_IO_DELAY)
    finally:
        lock.release()


def payout(n: int) -> int:
    """Credit n chips to the balance. n must be a non-negative int (n == 0
    is a harmless no-op, so a "push" outcome can call payout(0) instead of
    branching). Raises ValueError for a negative or non-int n -- unlike
    bet(), a bad payout amount is always a caller bug, never a legitimate
    "insufficient" case, so it is not silently swallowed.

    Returns the resulting balance. If persistence fails after the in-memory
    credit is computed, returns the last balance actually known to be on
    disk instead (never reports chips the player was not actually granted),
    so a caller displaying this return value never shows a phantom win.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError('payout amount must be a non-negative int')
    config._ensure_config()
    path = _chips_path()
    lock = config._FileLock(path)
    if not lock.acquire(timeout=_LOCK_TIMEOUT, delay=_LOCK_DELAY):
        return _load_state_readonly()['balance']
    try:
        state = _read_state_for_update(path)
        if state is _READ_FAILED:
            return _load_state_readonly()['balance']
        if n == 0:
            return state['balance']
        credited = state['balance'] + n
        state['balance'] = credited
        if config._atomic_write_json(path, state,
                                      _retries=_IO_RETRIES, _delay=_IO_DELAY):
            return credited
        return credited - n  # write failed: report the last known-persisted balance
    finally:
        lock.release()


def bailout_available() -> bool:
    """True if the player is at 0 balance and has not already received
    today's (local calendar date) bailout. Games use this to choose between
    offering the bailout and showing a 'come back tomorrow' message. Never
    mutates or creates chips.json."""
    state = _load_state_readonly()
    return state['balance'] == 0 and state['last_bailout_date'] != _today_iso()


def try_bailout() -> bool:
    """If the balance is exactly 0 and today's bailout has not yet been
    granted, credit BAILOUT_AMOUNT (100) chips and record today's date so
    it cannot fire again until the calendar date changes (local time), then
    return True.

    Returns False, with chips.json left completely untouched, if the
    balance is not 0, if today's bailout was already granted, or if the
    grant could not be safely persisted. In particular, a persistence
    failure never marks the bailout as spent -- the date is only recorded
    in the same atomic write that credits the chips, so a player can never
    be told 'come back tomorrow' for a bailout they never actually
    received.
    """
    config._ensure_config()
    path = _chips_path()
    lock = config._FileLock(path)
    if not lock.acquire(timeout=_LOCK_TIMEOUT, delay=_LOCK_DELAY):
        return False
    try:
        state = _read_state_for_update(path)
        if state is _READ_FAILED:
            return False
        if state['balance'] != 0:
            return False
        today = _today_iso()
        if state['last_bailout_date'] == today:
            return False
        state['balance'] += BAILOUT_AMOUNT
        state['last_bailout_date'] = today
        return config._atomic_write_json(path, state,
                                          _retries=_IO_RETRIES, _delay=_IO_DELAY)
    finally:
        lock.release()
