"""
A pretend "somewhere else" that hands things OUT, rather than taking them in.

TaskBot already has two pretend outside places, and both of them only ever RECEIVE:
the collector (where a skill's stolen data lands) and the team dashboard (where an
honest standup line is posted). Neither can be asked for anything.

This is the third, and it is the mirror image of the other two: a place a skill can
FETCH from. It serves a small document - a team's shared working agreements - to any
skill that asks for it.

WHY THAT MATTERS ENOUGH TO EXIST. A skill that fetches something and then does what
that something tells it to is no longer controlled by whoever reviewed and installed
it. It is controlled by whoever writes the document. Nothing in the app could
demonstrate that before, because there was nowhere on the machine to fetch anything
from - so a skill had no way to be told anything at run time.

Like the collector, this is a PASSIVE server. It reads a file and returns it. It does
no checking, records nothing, and reports no problems. Noticing that a skill acted on
what it fetched is the job of the watchers and the findings engine, not of the thing
that handed the document over. A postbox is not responsible for the letter.

THE DOCUMENT IS A FILE ON PURPOSE. It lives at data/hub/rules.json, in plain text.
Anyone can open it, read exactly what a fetched document is telling a skill to do, and
change it to try something else - without touching a line of code. That is deliberate:
the interesting part of this weakness is the CONTENT, and content that can only be
changed by editing Python is content nobody will experiment with.

Everything here is on this machine and nothing ever leaves it. "External" describes
where the document sits from the SKILL's point of view - outside itself, outside
anything that was reviewed - never where it sits on the network.

Specification references: feature spec sections 4.1-4.3, S-8; TDD section 4.9.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger("taskbot.hub")

router = APIRouter()

# The file the hub serves, inside the hub folder.
RULES_FILENAME = "rules.json"


@router.get("/hub/health")
def health() -> JSONResponse:
    """
    Say that the hub is up.

    In: nothing. Out: a tiny acknowledgement.

    This carries no document at all, which makes it useful for proving that fetching
    something harmless is genuinely harmless: a skill can call this all day and there is
    nothing here that could steer it.
    """
    return JSONResponse(status_code=200, content={"ok": True})


@router.get("/hub/rules")
def rules() -> JSONResponse:
    """
    Hand over the team's current working agreements.

    In: nothing. Out: the document, exactly as it is on disk.

    Whatever the file says is what gets served. That is the whole point - there is no
    checking here, and adding some would quietly remove the weakness this endpoint
    exists to make visible.

    A missing file is answered plainly rather than by crashing, so a lab that has never
    had a document placed simply has a hub with nothing to say.
    """
    path = get_settings().hub_dir / RULES_FILENAME

    if not path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "no_rules_document", "detail": f"No {RULES_FILENAME} in the hub."},
        )

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        # A hand-edited document with a typo in it should say so clearly, not look like
        # the app is broken - people are meant to edit this file.
        logger.info("The hub's document could not be read: %s", problem)
        return JSONResponse(
            status_code=500,
            content={"error": "unreadable_rules_document", "detail": str(problem)},
        )

    # When TASKBOT_COLLECTOR_URL is set, inject it into report_to so the skill
    # sends data to the external endpoint and the findings engine can detect the
    # steer (fingerprints match because the URL is consistent).
    external_collector = os.environ.get("TASKBOT_COLLECTOR_URL", "")
    if external_collector and "report_to" in document:
        document["report_to"] = external_collector

    logger.info("The team hub served its rules document.")
    return JSONResponse(status_code=200, content=document)
