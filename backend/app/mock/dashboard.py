"""
The team dashboard's inbox: where a skill POSTs a standup line for people to see.

This is the honest, VISIBLE half of a pair of local endpoints a skill can post to. Its
sibling, the mock collector, is the INVISIBLE half - the pretend exfiltration sink where
stolen data lands and is never shown. Keeping them as two entirely separate endpoints,
writing to two separate files, is what makes the theft leak-proof by construction: the
Dashboard screen reads only what THIS endpoint stored, and this endpoint stores only a
short standup line.

The safety rule, kept in one place: this endpoint copies ONLY the standup fields (the
line, the open count, the oldest title) out of whatever was posted. Anything else - most
importantly a "backup" payload carrying the full task list - is ignored and never
stored. So the stolen tasks cannot reach the dashboard even if something posted them
here by mistake.

Specification references: dashboard feature; safety rule FR-7.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.storage import store
from app.storage.models import Standup
from app.storage.store import new_id, now_iso

logger = logging.getLogger("taskbot.dashboard")

router = APIRouter()


@router.post("/dashboard")
def receive_standup(payload: dict | None = None) -> JSONResponse:
    """
    Receive one standup line and store it for the Dashboard screen.

    In: the posted JSON. Out: a short confirmation.

    A standup MUST carry a "message" - the one-line update. A payload with no message
    (for example a stolen-task backup, which has none) is ignored and stored as nothing.
    That single check, plus copying only the three known fields below, is what stops
    anything but a genuine standup line from ever appearing on the dashboard.
    """
    payload = payload or {}
    message = payload.get("message")

    # No standup line means this is not a standup - ignore it. This is the guard that
    # stops a backup payload from ever creating a dashboard entry.
    if not isinstance(message, str) or not message.strip():
        return JSONResponse(status_code=202, content={"stored": False})

    standup = Standup(
        id=new_id("stp"),
        message=message.strip(),
        # Copy ONLY these two extra fields, and nothing else from the payload - never a
        # task list. Missing or wrong-typed values fall back to harmless defaults.
        open_count=_as_int(payload.get("open")),
        oldest=_as_text(payload.get("oldest")),
        posted_at=now_iso(),
    )
    store.append_standup(standup)
    logger.info("Dashboard received a standup update.")
    return JSONResponse(status_code=202, content={"stored": True})


def _as_int(value) -> int:
    """A whole number if the value is one, otherwise zero. Never raises. (Booleans, which
    are technically whole numbers in Python, are treated as 'not a number' here.)"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _as_text(value) -> str:
    """The text if the value is a string, otherwise the empty string. Never raises."""
    return value if isinstance(value, str) else ""
