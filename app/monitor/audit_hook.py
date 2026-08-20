"""
The process-wide watcher: catching a skill that goes around the official channels.

TaskBot gives skills a polite, supervised way to do things - ask the app, and the
app records the request and decides. But nothing physically stops a skill from
ignoring that and opening a file directly. This file is the safety net for exactly
that case.

Python offers a feature (added in version 3.8) where you can register a function
that gets told about low-level events: a file being opened, a network connection
being made, another program being started. Once registered, it CANNOT be removed
for the lifetime of the program - which is precisely what we want, because a skill
must not be able to switch off the thing watching it.

An analogy: the official channel is the reception desk where visitors sign in. This
watcher is the CCTV in the corridor. Most people sign in properly; the camera is
there for the person who climbs in through a window.

TWO THINGS THIS FILE MUST GET RIGHT, or the whole product breaks:

  1. It must ignore activity that is not a skill. The app opens files constantly -
     loading web pages, saving records, talking to the AI model. If any of that were
     blamed on a skill, the findings list would be meaningless noise.

  2. It must ignore the app's OWN work done on a skill's behalf. When a skill
     politely asks to read the task list, the app opens the task file to answer.
     Without care, the watcher sees that file being opened during a skill run and
     reports the skill for secretly reading files - even though the skill did
     exactly the right thing. This would make the honest control skill accuse
     itself, which would destroy the clean baseline the whole exercise depends on.

Specification references: feature spec sections 5.8 and 7.4-7.6; TDD sections
3.2-3.5; decision D-8.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("taskbot.monitor")


# --- The three markers -----------------------------------------------------------
#
# A "context variable" is a note that travels with whatever the app is currently
# doing. If two people use TaskBot at the same time, each request carries its own
# copy of these notes, so their activity never gets mixed up.

# Which skill run (if any) is happening right now. Empty means "no skill is running",
# and the watcher then ignores everything - that is how ordinary app activity stays
# out of the records.
CURRENT_INVOCATION: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "taskbot_current_invocation", default=None
)

# The notebook to write observations into during the current skill run.
CURRENT_LOG: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "taskbot_current_log", default=None
)

# True while the app's own official channel is doing its work on a skill's behalf.
# See point 2 in the file description above - this is the marker that stops the
# honest control skill accusing itself.
IN_BROKER: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "taskbot_in_broker", default=False
)


# --- Which low-level events we care about ----------------------------------------
#
# Python announces many events; these are the ones that correspond to something a
# skill could meaningfully do. Anything not listed here is ignored.
#
# Specification reference: feature spec section 7.4.

# Events that mean "a program was started".
PROCESS_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
    }
)

# Events that mean "a network connection was attempted".
NETWORK_EVENTS = frozenset({"socket.connect", "socket.getaddrinfo"})


@contextmanager
def broker_frame() -> Iterator[None]:
    """
    Mark the code inside as "this is the app doing its own housekeeping".

    In: nothing. Out: nothing (used with a "with" block).

    Anything that happens inside this block is invisible to the watcher. Every
    official-channel method runs inside one of these.

    The old value is always put back afterwards, even if something goes wrong in the
    middle, so an error can never leave the app permanently blind.
    """
    token = IN_BROKER.set(True)
    try:
        yield
    finally:
        IN_BROKER.reset(token)


@contextmanager
def invocation_scope(invocation_id: str, log: Any = None) -> Iterator[None]:
    """
    Mark the code inside as "a skill is running, and this is which one".

    In: the identifier for this run, and the notebook to record into.
    Out: nothing (used with a "with" block).

    Everything the watcher sees inside this block is attributed to this skill run.
    The markers are always cleared afterwards - if they were left set, ordinary app
    activity happening after the skill finished would be wrongly blamed on it.
    """
    invocation_token = CURRENT_INVOCATION.set(invocation_id)
    log_token = CURRENT_LOG.set(log)
    try:
        yield
    finally:
        CURRENT_INVOCATION.reset(invocation_token)
        CURRENT_LOG.reset(log_token)


def _capability_for_open(arguments: tuple) -> str:
    """
    Work out whether a file was being opened to read or to write.

    In: the details Python gives us about the open. Out: "fs.read" or "fs.write".

    The second value is the mode ("r", "w", "a" and so on). Anything that can change
    the file counts as a write; everything else is a read.
    """
    mode = ""
    if len(arguments) > 1 and isinstance(arguments[1], str):
        mode = arguments[1]

    writing_characters = {"w", "a", "x", "+"}
    if any(character in mode for character in writing_characters):
        return "fs.write"
    return "fs.read"


def _describe(event: str, arguments: tuple) -> tuple[str, str] | None:
    """
    Turn one low-level Python event into "what capability, on what thing".

    In: the event name and its details.
    Out: a (capability, resource) pair, or None if this event is not interesting.
    """
    if event == "open":
        if not arguments:
            return None
        return _capability_for_open(arguments), str(arguments[0])

    if event in NETWORK_EVENTS:
        if not arguments:
            return None
        target = arguments[0]
        # For an actual connection the target is a (host, port) pair; for a name
        # lookup it is just the host.
        if isinstance(target, tuple) and target:
            return "net.outbound", f"{target[0]}:{target[1] if len(target) > 1 else ''}"
        return "net.outbound", str(target)

    # Process events come in several spellings, so we match on the start of the name.
    for prefix in PROCESS_EVENTS:
        if event.startswith(prefix):
            return "proc.spawn", str(arguments[0]) if arguments else "unknown"

    return None


def _audit_hook(event: str, arguments: tuple) -> None:
    """
    The watcher itself. Python calls this for every low-level event in the program.

    In: the event name and its details. Out: nothing.

    This function has to be both careful and fast, because it runs on EVERY file
    opened anywhere in the program - including inside Python's own machinery.

    The order of the checks below is deliberate: the two cheapest tests come first,
    so that in the overwhelmingly common case (no skill running) we do almost no
    work at all before returning.

    It also never raises. A watcher that could throw an error would crash the app
    from inside completely unrelated code, so any problem is logged and swallowed.
    """
    try:
        # CHECK 1 (cheapest): is a skill even running? Almost always the answer is
        # no, and we stop here. This is what keeps ordinary app activity - web pages,
        # saving records, talking to the AI model - out of the records entirely.
        invocation_id = CURRENT_INVOCATION.get()
        if invocation_id is None:
            return

        # CHECK 2: is this the app doing its own work on the skill's behalf? If so it
        # is not the skill going around us, and must not be recorded. Without this
        # check the honest control skill would accuse itself of secretly reading
        # files, because answering its polite request means opening the task file.
        if IN_BROKER.get():
            return

        # CHECK 3: is this an event we care about at all?
        described = _describe(event, arguments)
        if described is None:
            return

        log = CURRENT_LOG.get()
        if log is None:
            return

        capability, resource = described

        # Record it as coming from the watcher rather than the official channel.
        # That distinction matters: going around the app is a deliberate act and is
        # reported as its own kind of problem.
        log.record(
            capability=capability,
            resource=resource,
            detail={"audit_event": event},
            outcome="ok",
            source="audit_hook",
        )
    except Exception:
        # Never let a problem here escape. This runs inside unrelated code all over
        # the program, so raising would break things that have nothing to do with us.
        logger.debug("Audit hook ignored an internal problem.", exc_info=True)


# Python does not allow a hook to be removed once added, so we remember whether we
# have already installed ours and never install it twice.
_hook_installed = False


def install_audit_hook() -> None:
    """
    Switch on the watcher.

    In: nothing. Out: nothing.

    Called once, early in startup, before anything could load a skill. Calling it
    again is harmless and does nothing.

    Note the one-way nature of this: Python provides no way to remove an audit hook.
    That is a feature here, not a limitation - a skill cannot uninstall the thing
    that is watching it.
    """
    global _hook_installed
    if _hook_installed:
        return

    sys.addaudithook(_audit_hook)
    _hook_installed = True
    logger.debug("Audit hook installed.")
