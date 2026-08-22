"""
Safely reading and writing the JSON files that hold everything TaskBot remembers.

Two problems this file solves.

1. HALF-WRITTEN FILES. If the computer lost power midway through saving, an
   ordinary write would leave a broken file. Instead we always write to a temporary
   file first and then *rename* it over the real one. A rename is all-or-nothing:
   the file is either the complete old version or the complete new version, never a
   mangled mix. It is like writing a fresh copy of a letter and swapping it for the
   old one, rather than scribbling corrections onto the original.

2. TWO WRITERS AT ONCE. If two things try to update the same file at the same
   moment, one change can be lost. We use a "lock" per file - like a key to a room
   that only one person can hold at a time - so updates happen one after another.

There is also a recovery rule: if a file is missing or unreadable, we move the
damaged one aside, log a warning, and carry on with a fresh empty one. A practice
lab that refuses to start because of a corrupted file is far more annoying than one
that quietly resets itself and tells you it did.

Specification references: feature spec section 4.1, decisions S-11, S-12, S-13.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("taskbot.storage")


# --- Locks -----------------------------------------------------------------------
#
# One lock per file. _locks_guard protects the dictionary itself, because building
# the dictionary entry is also something two threads could do at the same time.

_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    """
    Find (or create) the lock belonging to one file.

    In: the path of the file. Out: the lock that guards it.

    We use an "RLock" (a re-entrant lock) rather than a plain one, because the same
    thread sometimes needs to take the same lock twice while nested inside itself. A
    plain lock would freeze forever in that situation; an RLock allows it.
    """
    key = Path(path).resolve()
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.RLock()
        return _locks[key]


# --- Reading and writing ---------------------------------------------------------


def _timestamp_for_filename() -> str:
    """
    Build a timestamp safe to put in a filename.

    In: nothing. Out: text like "2026-08-21T14-03-11-482Z".

    Colons are not allowed in Windows filenames, so they are replaced with dashes.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"


def _quarantine_unreadable_file(path: Path) -> None:
    """
    Move a damaged file out of the way so a fresh one can take its place.

    In: the path of the damaged file. Out: nothing.

    We keep the damaged copy rather than deleting it, in case someone wants to look
    at what went wrong.
    """
    ruined = path.with_name(f"{path.name}.corrupt.{_timestamp_for_filename()}")
    try:
        path.replace(ruined)
        logger.warning("Unreadable file %s moved aside to %s.", path, ruined.name)
    except OSError:
        # If even moving it fails there is nothing sensible left to try. We log and
        # carry on with the default value, because the lab must always start.
        logger.warning("Could not move aside unreadable file %s.", path, exc_info=True)


def read_json(path: Path, default: Any) -> Any:
    """
    Read one JSON file, recovering automatically if it is missing or damaged.

    In: the file path, and the value to fall back to.
    Out: whatever was stored in the file, or a fresh copy of the fallback value.

    This never raises an error for a missing or broken file. That is deliberate: see
    the recovery rule at the top of this file.
    """
    path = Path(path)

    if not path.exists():
        return default

    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Could not read %s; starting from a fresh copy.", path)
        _quarantine_unreadable_file(path)
        return default


def write_json_atomic(path: Path, value: Any) -> None:
    """
    Save a value as JSON, all at once or not at all.

    In: the destination path and the value to save. Out: nothing.

    The steps are: write a temporary file next to the destination, force it fully
    onto the disk, then rename it over the destination. The temporary file must sit
    in the SAME folder, because renaming across drives is not guaranteed to be
    all-or-nothing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # The temporary name must be unique for EVERY call, not just for every program.
    # An earlier version used only the process id, which meant twenty threads inside
    # one program all picked the same temporary filename and overwrote each other
    # mid-save. The random ending makes every save independent.
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")

    text = json.dumps(value, indent=2, ensure_ascii=False, default=str)

    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        # flush pushes our text out of the program, fsync pushes it from the
        # operating system onto the physical disk. Without both, a power cut could
        # leave an apparently-renamed but actually empty file.
        handle.flush()
        os.fsync(handle.fileno())

    # The all-or-nothing moment. os.replace overwrites the destination in a single
    # step and works the same way on Windows and on Linux/macOS.
    _replace_with_retry(temporary, path)


# How many times to retry the final rename, and how long to wait between attempts.
# See _replace_with_retry for why retrying is needed at all.
_REPLACE_ATTEMPTS = 10
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(temporary: Path, destination: Path) -> None:
    """
    Rename the finished temporary file over the real one, retrying briefly.

    In: the temporary file and where it should end up. Out: nothing.

    Why retry at all? On Windows another program can hold a file open for a moment
    without warning - antivirus scanning it, or the search indexer reading it - and
    while that lasts the rename is refused with "access denied". It is nobody's
    fault and it clears in a few milliseconds.

    This does NOT weaken the all-or-nothing promise. Each attempt is still a single
    complete rename; we are simply waiting for the other program to let go. If it
    never does, the error is raised as normal rather than being swallowed.

    Think of it as trying a door that someone is briefly standing behind: you wait a
    moment and try again, rather than giving up or forcing it.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            # The last attempt re-raises, so a genuine permissions problem is still
            # reported clearly instead of disappearing.
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            # Wait a little longer each time, which lets a slow scanner finish.
            time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))


@contextmanager
def mutate_json(path: Path, default: Any) -> Iterator[list | dict]:
    """
    Read a JSON file, let the caller change it, then save it - with nobody else
    allowed to touch that file in between.

    In: the file path and the fallback value if the file is missing.
    Out: the loaded value, which the caller edits in place inside a "with" block.

    Example in plain terms: this is like taking the only copy of a ledger off the
    shelf, writing in it, and putting it back before anyone else can read it. That
    prevents the classic mistake where two people copy the ledger, each add one
    line, and the second one to write back erases the first person's line.
    """
    path = Path(path)
    with _lock_for(path):
        current = read_json(path, default)
        yield current
        write_json_atomic(path, current)
