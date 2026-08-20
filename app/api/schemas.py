"""
The shapes of everything the JSON API sends back.

Other programs - a security scanner, a fix-it tool, a script - read TaskBot through
its JSON API. Those programs break if the shape of an answer changes unexpectedly,
so every answer is defined here in one place rather than being built ad hoc wherever
it happens to be needed.

Every response carries a "schema_version" number. The promise attached to version 1
is: we may ADD new fields, but we will never rename, retype, or remove an existing
one. If we ever needed to break that promise we would publish a version 2 instead.

Specification references: feature spec section 11.1 and 11.2, TDD section 7,
requirement FR-6.3.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# The version number stamped on every response. See the promise described above.
SCHEMA_VERSION = 1


class ApiModel(BaseModel):
    """
    The base every API response builds on.

    Its only job is to stamp the schema version onto the answer automatically, so no
    individual endpoint can forget to include it.
    """

    schema_version: int = Field(default=SCHEMA_VERSION)


class ErrorResponse(ApiModel):
    """
    The single shape used for every failure.

    Programs reading TaskBot should branch on the short "error" code, never on the
    human sentence in "detail" - codes are stable, wording is not.
    """

    error: str
    detail: str
    # Only filled in when the AI model is unreachable: these tell the operator
    # exactly what went wrong and the command that fixes it.
    reason: str | None = None
    remedy: str | None = None


class OllamaHealth(BaseModel):
    """Whether the local AI model is running and reachable right now."""

    reachable: bool
    model_present: bool
    url: str


class HealthCounts(BaseModel):
    """A quick tally of what is currently in the lab."""

    skills: int
    installed: int
    tasks: int
    findings: int
    activity: int


class HealthResponse(ApiModel):
    """
    The answer to "is the app up, and what state is it in?".

    "intentionally_vulnerable" is always true and is deliberately permanent. It is
    one of the ways TaskBot announces what it is, so nobody mistakes it for an
    ordinary application (requirement FR-7.6).
    """

    status: Literal["ok"]
    intentionally_vulnerable: bool = True
    model: str
    ollama: OllamaHealth
    counts: HealthCounts


# --- Error codes -----------------------------------------------------------------
#
# The complete list of short codes the API can return, with the HTTP status number
# that goes with each. Keeping them together means the API can never invent a code
# that consumers have not been told about.
#
# Specification reference: feature spec section 11.2, decision S-32.

ERROR_STATUS: dict[str, int] = {
    "skill_not_found": 404,
    "skill_invalid": 409,
    "skill_not_installed": 409,
    "validation_error": 422,
    "llm_unavailable": 503,
    "storage_error": 500,
}


def error_payload(
    code: str,
    detail: str,
    *,
    reason: str | None = None,
    remedy: str | None = None,
) -> dict[str, Any]:
    """
    Build one error response.

    In: the short stable code, a human-readable explanation, and optionally the
    extra "reason"/"remedy" pair used when the AI model is unavailable.
    Out: a plain dictionary ready to be sent as JSON.
    """
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "error": code,
        "detail": detail,
    }
    # Only include the optional fields when they actually say something, so simple
    # responses stay simple to read.
    if reason is not None:
        payload["reason"] = reason
    if remedy is not None:
        payload["remedy"] = remedy
    return payload
