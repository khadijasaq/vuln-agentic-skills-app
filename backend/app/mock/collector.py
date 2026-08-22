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

NOTHING IN THE CURRENT WORK SENDS ANYTHING HERE. It is built and tested now so that
the safety promise is real and proven before anything relies on it.

Specification references: feature spec section 13.2; TDD section 8; requirement
FR-7.2.
"""

from __future__ import annotations

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
