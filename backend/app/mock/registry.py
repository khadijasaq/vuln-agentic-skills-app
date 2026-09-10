"""
A pretend component registry: the place a skill's building blocks are published.

TaskBot now has four pretend outside places. Two only ever RECEIVE - the collector
(where stolen data lands) and the team dashboard (where an honest standup line is
posted). Two hand something OUT - the team hub, which serves a document a skill reads,
and this one, which serves a COMPONENT a skill is built on.

WHY A FOURTH MOCK, AND WHY IT IS NOT THE HUB. The hub serves one document at one fixed
address. A registry has to be asked for something by NAME and by VERSION, because the
whole weakness this exists to demonstrate is "same name, same version, different
contents". Without those two coordinates in the address there is no way to say it.

WHAT THE WEAKNESS IS. Real software is built on parts published by other people. You
write down which part you want, which version, and often a fingerprint of the exact
build you reviewed. Then you trust that what turns up is what you asked for. This
endpoint is where that trust is placed - and where it is quietly broken, by serving a
build that carries the right name and the right version number and different contents.

Like the collector and the hub, this is a PASSIVE server. It reads a file and returns
it. It checks nothing, records nothing, and reports no problems. Noticing that what it
served is not what a skill expected is the job of the findings engine, not of the thing
that handed the parcel over. A courier does not open the box.

ONE DETAIL THAT LOOKS FUSSY AND IS NOT: this returns the file's exact bytes, rather than
reading the file as JSON and writing it out again. The whole point of a fingerprint is
that it is a fingerprint of something specific. If the app re-typed the contents on the
way out, the fingerprint would describe the app's typing rather than the file, and it
would change whenever anything about that typing changed. Serving the bytes untouched
means the fingerprint of what arrives is a fact about what is on disk, and stays true on
every machine.

THE COMPONENTS ARE FILES ON PURPOSE. They live in data/registry/, in plain text. Anyone
can open one, read what it does, and swap it for another to see the weakness appear or
disappear - without touching a line of code.

Everything here is on this machine and nothing ever leaves it. "Published by somebody
else" describes where the component sits from the SKILL's point of view - outside itself,
outside anything that was reviewed - never where it sits on the network.

Specification references: AST02 spec sections 5.1-5.3, decisions S-4 and S-10; build plan
step 4.2.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger("taskbot.registry")

router = APIRouter()

# What a component may be called, and which versions may be asked for.
#
# These are deliberately narrow. They are the same shapes a skill's description is
# allowed to use, and because neither can contain a dot-dot or a slash, no request can
# ask for a file outside the registry folder. That is the only checking this endpoint
# does, and it is about where files live, never about what they contain.
COMPONENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
COMPONENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


@router.get("/registry/health")
def health() -> JSONResponse:
    """
    Say that the registry is up.

    In: nothing. Out: a tiny acknowledgement.

    This carries no component at all, which makes it useful for proving that the
    fetching path itself works without anything being delivered.
    """
    return JSONResponse(status_code=200, content={"ok": True})


@router.get("/registry/{name}/{version}")
def component(name: str, version: str) -> Response:
    """
    Hand over one published component.

    In: which component, and which version. Out: the file, exactly as it is on disk.

    Whatever the file says is what gets served. That is the whole point - there is no
    checking here, and adding some would quietly remove the weakness this endpoint exists
    to make visible.

    A missing component is answered plainly rather than by crashing, so a lab that has
    never had one placed simply has a registry with nothing to offer.
    """
    if not COMPONENT_NAME_PATTERN.match(name) or not COMPONENT_VERSION_PATTERN.match(version):
        return JSONResponse(
            status_code=404,
            content={"error": "no_such_component", "detail": "Not a component name and version."},
        )

    path = get_settings().registry_dir / f"{name}-{version}.json"

    if not path.is_file():
        return JSONResponse(
            status_code=404,
            content={
                "error": "no_such_component",
                "detail": f"The registry has no {name} at version {version}.",
            },
        )

    try:
        body = path.read_bytes()
    except OSError as problem:
        logger.info("A published component could not be read: %s", problem)
        return JSONResponse(
            status_code=500,
            content={"error": "unreadable_component", "detail": str(problem)},
        )

    logger.info("The component registry served %s %s.", name, version)
    # The bytes, untouched - see the note at the top of this file about why this must
    # not go out through the JSON encoder.
    return Response(status_code=200, content=body, media_type="application/json")
