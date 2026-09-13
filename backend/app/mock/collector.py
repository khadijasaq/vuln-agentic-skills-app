"""
A pretend "somewhere else" that never leaves this computer.

Some of the security problems this app demonstrates involve a skill quietly sending
your private information away. Actually sending it anywhere would be genuinely
harmful, so instead there is this: an address that looks like an outside service from
a skill's point of view, but is really just a folder on this machine.

Combined with the rule that skills may only contact this computer, that gives the
best of both: an attempted theft can be observed in complete detail - what was taken,
where it was headed, when - while not a single byte actually leaves.

This is a passive letterbox. It accepts whatever it is given, writes it down, and
says nothing more. It does no checking and reports no problems - noticing the theft
is the job of the watchers and the findings engine, not of the letterbox.

A companion read-only view is provided so a person can see what has been collected,
without needing shell access to the machine.

NOTHING IN THE CURRENT WORK SENDS ANYTHING HERE. It is built and tested now so that
the safety promise is real and proven before anything relies on it.

Specification references: feature spec section 13.2; TDD section 8; requirement
FR-7.2.
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.monitor.audit_hook import CURRENT_INVOCATION
from app.storage import atomic
from app.storage.store import now_iso

logger = logging.getLogger("taskbot.collector")

router = APIRouter()


def _safe_for_filename(text: str) -> str:
    """
    Make a piece of text safe to use in a filename.

    In: any text. Out: the same text with awkward characters replaced by dashes.
    """
    return re.sub(r"[^A-Za-z0-9_.-]", "-", text)


@router.post("/collector")
def receive(payload: dict | None = None) -> JSONResponse:
    """
    Accept whatever a skill tried to send away, and file it.

    In: any JSON. Out: a short acknowledgement.

    Each delivery is written to its own file under data/collector/inbox/, stamped
    with the time and with which skill run sent it. Deleting that folder throws away
    everything a pretend theft ever "took".
    """
    settings = get_settings()
    inbox = settings.collector_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    # If a skill sent this while it was running, note which run it came from, so the
    # delivery can be matched to the exact moment in the activity log.
    sender = CURRENT_INVOCATION.get() or "unknown"

    filename = f"{_safe_for_filename(now_iso())}-{_safe_for_filename(sender)}.json"

    atomic.write_json_atomic(
        inbox / filename,
        {
            "schema_version": 1,
            "received_at": now_iso(),
            "sender_invocation_id": sender,
            "payload": payload,
        },
    )

    logger.info("Mock collector received a delivery from %s.", sender)
    return JSONResponse(status_code=202, content={"received": True})


@router.get("/view")
def view(limit: int = 100) -> JSONResponse:
    """
    List what the letterbox has received, newest first.

    In: an optional `limit` query param capping how many entries to return
    (default 100). Out: a JSON array of the stored deliveries.

    This is read-only and does no interpretation of the payloads - it exists so a
    person can see what an attempted theft would have taken, without needing shell
    access to the machine the app is deployed on.
    """
    settings = get_settings()
    inbox = settings.collector_dir / "inbox"

    if not inbox.exists():
        return JSONResponse(content={"count": 0, "entries": []})

    files = sorted(
        inbox.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    entries = []
    for f in files[:limit]:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                entries.append(json.load(fh))
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt or half-written file shouldn't break the whole view -
            # note it and move on.
            logger.warning("Could not read collector entry %s: %s", f.name, exc)
            entries.append({"error": f"could not read {f.name}", "detail": str(exc)})

    return JSONResponse(content={"count": len(files), "entries": entries})


@router.post("/clear")
def clear() -> JSONResponse:
    """
    Empty the letterbox.

    In: nothing. Out: how many entries were removed.

    Deletes every stored delivery under data/collector/inbox/. Useful between demo
    runs so old captures don't clutter a fresh walkthrough.
    """
    settings = get_settings()
    inbox = settings.collector_dir / "inbox"

    if not inbox.exists():
        return JSONResponse(content={"cleared": 0})

    removed = 0
    for f in inbox.glob("*.json"):
        try:
            f.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("Could not remove collector entry %s: %s", f.name, exc)

    logger.info("Mock collector inbox cleared (%d entries removed).", removed)
    return JSONResponse(content={"cleared": removed})