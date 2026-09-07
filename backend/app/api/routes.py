"""
The JSON API: the addresses that other PROGRAMS talk to.

A person uses the web pages. A scanning tool, a script, or another piece of software
uses these. They can list the skills, read what each one claims about itself, install
one, hold a conversation with the assistant, and read back every problem the app has
noticed.

TWO PROMISES THESE ENDPOINTS MAKE:

  1. Every answer carries a "schema_version". Within version 1 we may ADD fields, but
     we will never rename, retype or remove one. Anything reading TaskBot can rely on
     that, and should simply ignore fields it does not recognise.

  2. Failures always look the same: a short stable code plus a human sentence.
     Programs should branch on the code, never on the wording.

There is deliberately no login. This is a practice target that only ever listens on
this computer, and adding accounts would suggest it was safe to expose.

Specification references: feature spec section 11; TDD section 7; requirement FR-6.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api import schemas
from app.chat.orchestrator import ChatOrchestrator
from app.config import get_settings
from app.llm.groq_client import GroqClient, LlmUnavailable
from app.skills.registry import SkillInvalid, SkillNotFound, SkillRecord, get_registry
from app.storage import store

logger = logging.getLogger("taskbot.api")

router = APIRouter()


def _error(code: str, detail: str, **extra) -> JSONResponse:
    """
    Build one failure answer.

    In: the short stable code, a human sentence, and any extra fields.
    Out: the response to send back, with the right HTTP status number.
    """
    status = schemas.ERROR_STATUS.get(code, 500)
    return JSONResponse(status_code=status, content=schemas.error_payload(code, detail, **extra))


def _skill_summary(record: SkillRecord) -> dict:
    """
    Describe one skill for the API.

    In: the skill's record. Out: a plain dictionary.

    Note that the capabilities listed here are what the skill CLAIMS about itself.
    They are shown exactly as written, with no checking - which is the honest
    representation, because a claim is all a manifest ever is.
    """
    manifest = record.manifest

    return {
        "id": record.skill_id,
        "name": manifest.name if manifest else record.skill_id,
        "version": manifest.version if manifest else "",
        "author": manifest.author if manifest else "",
        "category": manifest.category if manifest else "",
        "description": manifest.description if manifest else "",
        "source": record.source.value,
        "installed": record.installed,
        "valid": record.valid,
        "errors": list(record.errors),
        "declared_capabilities": (
            [declaration.model_dump() for declaration in manifest.capabilities]
            if manifest
            else []
        ),
    }


# --- Is it up? -------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    """
    Report whether the app is up, what state the lab is in, and whether the AI model
    is reachable.

    In: nothing. Out: the health summary.
    """
    settings = get_settings()
    registry = get_registry()

    model_health = GroqClient().health()

    all_skills = registry.all()

    return schemas.HealthResponse(
        status="ok",
        # Permanent and deliberate: this is how TaskBot announces what it is.
        intentionally_vulnerable=True,
        model=settings.model,
        llm=schemas.LlmHealth(
            reachable=model_health.reachable,
            model_present=model_health.model_present,
            url=model_health.url,
        ),
        counts=schemas.HealthCounts(
            skills=len(all_skills),
            installed=len([record for record in all_skills if record.installed]),
            tasks=len(store.load_tasks()),
            findings=len(store.load_findings()),
            activity=len(store.load_activity()),
        ),
    ).model_dump()


# --- The skill store -------------------------------------------------------------


@router.get("/skills")
def list_skills() -> dict:
    """
    List every skill on disk, with whether it is switched on.

    In: nothing. Out: the catalogue.
    """
    registry = get_registry()
    return {
        "schema_version": schemas.SCHEMA_VERSION,
        "skills": [_skill_summary(record) for record in registry.all()],
    }


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str):
    """
    Everything one skill claims about itself, exactly as written.

    In: the skill identifier. Out: its full description.
    """
    try:
        record = get_registry().get(skill_id)
    except SkillNotFound:
        return _error("skill_not_found", f"No skill with id {skill_id!r}.")

    payload = _skill_summary(record)
    payload["schema_version"] = schemas.SCHEMA_VERSION
    payload["manifest"] = record.manifest.model_dump() if record.manifest else None
    return payload


@router.post("/skills/{skill_id}/install")
def install_skill(skill_id: str):
    """
    Switch a skill on.

    In: the skill identifier. Out: the updated skill, plus any problems visible from
    its description alone.

    Some problems can be spotted before a skill has ever run - a skill asking for far
    more power than its kind of skill needs, for instance. Those are reported here.
    """
    registry = get_registry()

    try:
        record = registry.install(skill_id)
    except SkillNotFound:
        return _error("skill_not_found", f"No skill with id {skill_id!r}.")
    except SkillInvalid as problem:
        return _error("skill_invalid", str(problem))

    findings = []
    if record.manifest is not None:
        from app.chat.orchestrator import _build_engine

        raised = _build_engine().evaluate_install(record.manifest, model=get_settings().model)
        for finding in raised:
            stored, is_new = store.upsert_finding(finding)
            if is_new:
                from app.findings.markers import write_marker

                stored.evidence["marker"] = str(write_marker(stored, None))
                store.upsert_finding(stored)
            findings.append(stored.model_dump())

    payload = _skill_summary(registry.get(skill_id))
    payload["schema_version"] = schemas.SCHEMA_VERSION
    payload["findings_raised"] = findings
    return payload


@router.post("/skills/{skill_id}/uninstall")
def uninstall_skill(skill_id: str):
    """
    Switch a skill off.

    In: the skill identifier. Out: the updated skill.
    """
    registry = get_registry()

    try:
        registry.uninstall(skill_id)
    except SkillNotFound:
        return _error("skill_not_found", f"No skill with id {skill_id!r}.")

    payload = _skill_summary(registry.get(skill_id))
    payload["schema_version"] = schemas.SCHEMA_VERSION
    payload["findings_raised"] = []
    return payload


# --- Talking to the assistant ----------------------------------------------------
#
# NOTE: this is declared with "def" and not "async def", deliberately.
#
# Written this way, the web framework runs it on a separate worker thread and copies
# the "which skill is running" markers into that thread. That is what keeps the
# watchers accurate when two people use the app at once. Written as "async def" it
# would run on the shared event loop and two overlapping conversations could have
# their records mixed together (decision S-30).


@router.post("/chat")
def chat(request: Request, body: dict):
    """
    Hold one exchange with the assistant.

    In: {"message": "..."}.
    Out: the reply, which skill ran if any, and any problems raised by THIS exchange.

    The "findings_raised" list is deliberately per-exchange. A scanning tool can then
    attribute a problem to the exact message that caused it, without having to
    compare the whole findings list before and after.
    """
    message = (body or {}).get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("validation_error", "Send a JSON object with a non-empty 'message'.")

    try:
        result = ChatOrchestrator().run_turn(message)
    except LlmUnavailable as problem:
        # Loudly broken rather than quietly wrong. See decision D-13.
        return _error(
            "llm_unavailable",
            problem.detail,
            reason=problem.reason,
            remedy=problem.remedy,
        )

    invoked = result.activity.skill_invoked

    return {
        "schema_version": schemas.SCHEMA_VERSION,
        "reply": result.activity.reply,
        "activity_id": result.activity.id,
        "skill_invoked": (
            {
                "skill_id": invoked.skill_id,
                "invocation_id": invoked.invocation_id,
                "outcome": invoked.outcome,
            }
            if invoked
            else None
        ),
        "findings_raised": [finding.model_dump() for finding in result.findings_raised],
        "llm": {"model": result.model, "tool_call": result.tool_call_made},
    }


# --- Reading what happened -------------------------------------------------------


@router.get("/findings")
def list_findings(
    skill_id: str | None = Query(default=None),
    ast_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    since: str | None = Query(default=None),
) -> dict:
    """
    Every security problem noticed so far, newest last.

    In: optional filters by skill, risk identifier, severity, or time.
    Out: the matching problems.
    """
    findings = store.load_findings()

    if skill_id:
        findings = [finding for finding in findings if finding.skill_id == skill_id]
    if ast_id:
        findings = [finding for finding in findings if finding.ast_id == ast_id]
    if severity:
        findings = [finding for finding in findings if finding.severity == severity]
    if since:
        findings = [finding for finding in findings if finding.last_seen >= since]

    return {
        "schema_version": schemas.SCHEMA_VERSION,
        "findings": [finding.model_dump() for finding in findings],
        "count": len(findings),
    }


@router.get("/activity")
def list_activity(
    limit: int = Query(default=50, ge=0, le=500),
    skill_id: str | None = Query(default=None),
    since: str | None = Query(default=None),
) -> dict:
    """
    The record of every exchange, oldest first.

    In: optional filters. Out: the matching exchanges.
    """
    entries = store.load_activity(limit=limit, skill_id=skill_id, since=since)

    return {
        "schema_version": schemas.SCHEMA_VERSION,
        "activity": [entry.model_dump() for entry in entries],
        "count": len(entries),
    }


# --- Starting over ---------------------------------------------------------------


@router.post("/reset")
def reset() -> dict:
    """
    Clear what the app has observed and put a fresh task list back.

    In: nothing. Out: a summary of what was cleared.

    IMPORTANT, AND WORTH BEING BLUNT ABOUT: this is a convenience for running
    demonstrations repeatedly. It is NOT a security switch.

    It changes no skill, no declared permission, no policy and no part of how the app
    behaves. Every weakness present before a reset is still present afterwards. All it
    does is make the app forget what it saw. There is no setting anywhere in TaskBot,
    reachable by any route, that makes it less vulnerable.
    """
    summary = store.reset_lab()
    summary["schema_version"] = schemas.SCHEMA_VERSION
    return summary
