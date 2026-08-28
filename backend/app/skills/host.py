"""
The one and only place where a skill's code is actually run.

THIS IS THE MOST IMPORTANT STRUCTURAL RULE IN THE APPLICATION.

Nothing anywhere else in TaskBot may run a skill. There is exactly one function
below that does it, and exactly one place in the whole codebase that calls it: the
conversation code, in the branch that handles the AI model asking for a skill by
name. An automated check enforces this.

Why so strict? Because the central claim of this whole project is "the AI agent
genuinely chose to do this". If any other part of the app could quietly start a
skill - a keyword match, a shortcut, a helpful fallback - then a demonstration
proving that an agent was tricked would prove nothing at all. Keeping a single
entrance is what makes that claim checkable in under a minute by a reviewer.

What this function does, in order:

  1. Refuse to run anything that is not installed and valid.
  2. Check the values the AI model supplied against what the skill said it accepts.
  3. Open a fresh notebook for this run.
  4. Load the skill's code.
  5. Mark "a skill is running" so the watchers pay attention.
  6. Run it, catching anything that goes wrong.
  7. ALWAYS unmark, even if it crashed.
  8. Hand back what happened.

Specification references: feature spec sections 5.6 and 8.3; TDD sections 3.2 and
5.3; decisions S-20 and S-21; invariant I-1.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import jsonschema

from app.monitor.audit_hook import broker_frame, invocation_scope
from app.monitor.observations import Observation, ObservationLog
from app.skills.context import SkillContext, SkillResult
from app.skills.registry import SkillRecord, get_registry
from app.storage.store import new_id

logger = logging.getLogger("taskbot.host")


@dataclass(frozen=True)
class InvocationResult:
    """
    Everything that happened during one run of one skill.

    outcome      - "ok" if the skill finished, "error" if anything went wrong.
    summary      - the sentence handed back to the AI model.
    data         - structured details for the activity screen.
    observations - the complete, ordered notebook of what the skill touched.
    """

    invocation_id: str
    skill_id: str
    outcome: Literal["ok", "error"]
    summary: str = ""
    data: dict[str, Any] | None = None
    error: str | None = None
    observations: list[Observation] = field(default_factory=list)
    duration_ms: int = 0


# Skills are loaded once and kept, so running one repeatedly does not re-read it from
# disk every time. The remembered key includes when the file was last changed, so
# editing a skill while developing picks up the new version automatically.
_loaded_modules: dict[tuple[str, str, int], Any] = {}

# Integrity / reputation checks that must all pass before a skill may run. Each is a
# callable that takes the skill's record and the run identifier and returns None to
# allow the run, or a human-readable reason string to refuse it. The list starts
# empty; the supply-chain tasks (T-06 digest, and via the same registry the T-08/09
# revocations and signatures) register their predicates here. Keeping the gate in ONE
# place means a failure is always reported the same way and always happens before any
# skill code is loaded, so exec() (below) is never reached for a refused skill.
INTEGRITY_CHECKS: list[Callable[[SkillRecord, str], str | None]] = []


def _load_skill_module(record: SkillRecord):
    """
    Load a skill's code, or hand back the copy already loaded.

    In: the skill's record. Out: the loaded code.

    IMPORTANT: this is called from INSIDE the "a skill is running" marker, on
    purpose. Python runs a file's top-level code the moment it is loaded, so a skill
    could try to do something the instant it is imported, before its main function is
    ever called. Loading inside the marker means even that is watched (decision S-21).
    """
    assert record.manifest is not None
    assert record.entry_file is not None

    key = (record.skill_id, record.manifest.version, record.mtime_ns)
    if key in _loaded_modules:
        return _loaded_modules[key]

    module_name = f"taskbot_skill_{record.skill_id}"
    spec = importlib.util.spec_from_file_location(module_name, record.entry_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {record.entry_file}.")

    # Loading a skill happens in two distinct parts, and only the second one is the
    # skill doing anything:
    #
    #   1. Python reads the skill file from disk and turns it into runnable code.
    #      That is the APP opening a file, not the skill - so it is marked as the
    #      app's own housekeeping and stays out of the record. Without this, every
    #      skill would appear to secretly read files simply by being loaded.
    #
    #   2. Python then runs whatever sits at the top level of that file. That IS the
    #      skill acting, and it happens outside the housekeeping marker so it is
    #      watched. This matters because a skill could try to do something the
    #      instant it is loaded, before its main function is ever called
    #      (decision S-21).
    with broker_frame():
        code = spec.loader.get_code(module_name)
    if code is None:
        raise ImportError(f"Could not read any code from {record.entry_file}.")

    module = importlib.util.module_from_spec(spec)
    # Registering it before running it lets the skill import itself if it wants to,
    # which is how ordinary Python modules behave.
    sys.modules[module_name] = module

    # The skill's own top-level code runs here, in full view of the watchers.
    exec(code, module.__dict__)

    _loaded_modules[key] = module
    return module


def clear_module_cache() -> None:
    """
    Forget every loaded skill.

    In: nothing. Out: nothing. Used by tests so one test cannot inherit another
    test's loaded code.
    """
    _loaded_modules.clear()


def _validate_params(record: SkillRecord, params: dict) -> tuple[dict, str | None]:
    """
    Check the values the AI model supplied against what the skill said it accepts.

    In: the skill's record and the supplied values.
    Out: a pair - the cleaned values, and a problem message if there was one.

    Anything the skill did not ask for is dropped rather than passed along, so a
    model inventing extra values cannot smuggle anything in.
    """
    assert record.manifest is not None
    schema = record.manifest.invocation.parameters

    allowed_names = set(schema.get("properties", {}))
    cleaned = {name: value for name, value in params.items() if name in allowed_names}

    try:
        jsonschema.Draft202012Validator(schema).validate(cleaned)
    except jsonschema.ValidationError as error:
        return cleaned, f"The values supplied do not match what this skill accepts: {error.message}"

    return cleaned, None


class SkillHost:
    """The single entrance through which skills are run."""

    def invoke(self, skill_id: str, params: dict | None = None) -> InvocationResult:
        """
        Run one skill.

        In: which skill, and the values the AI model supplied.
        Out: an InvocationResult describing everything that happened.

        This never raises because a skill misbehaved. A crashing skill produces an
        "error" result which the conversation carries on with - one broken skill must
        not take down the whole exchange.
        """
        params = dict(params or {})
        invocation_id = new_id("inv")
        started_at = time.monotonic()

        registry = get_registry()
        record = registry.get(skill_id)

        # STEP 1: only installed, valid skills may run. This is what makes "with
        # nothing installed, nothing can happen" true.
        if not record.valid:
            return self._failure(invocation_id, skill_id, "This skill is not valid.", started_at)
        if not record.installed:
            return self._failure(
                invocation_id, skill_id, "This skill is not installed.", started_at
            )

        # STEP 1.5: integrity / reputation gate. Every registered check must pass
        # before any skill code is loaded, so a refused skill never reaches exec().
        # The checks are predicates that return None to allow or a reason to refuse.
        for check in INTEGRITY_CHECKS:
            reason = check(record, invocation_id)
            if reason is not None:
                return self._integrity_failure(
                    invocation_id, skill_id, reason, started_at
                )

        # STEP 2: check the supplied values.
        cleaned_params, problem = _validate_params(record, params)
        if problem:
            return self._failure(invocation_id, skill_id, problem, started_at)

        # STEP 3: a fresh notebook for this run.
        notebook = ObservationLog(invocation_id)
        context = SkillContext(invocation_id, notebook)

        outcome: Literal["ok", "error"] = "ok"
        summary = ""
        data: dict[str, Any] | None = None
        error_message: str | None = None

        # STEP 5 and 7: mark "a skill is running" while it runs, and ALWAYS unmark
        # afterwards. The "with" block guarantees the unmarking even if the skill
        # crashes - if the marker were left set, everything the app did afterwards
        # would be wrongly blamed on this skill.
        with invocation_scope(invocation_id, notebook):
            try:
                # STEP 4, deliberately inside the marker - see _load_skill_module.
                module = _load_skill_module(record)
                entrypoint = getattr(module, record.entry_attr or "run", None)
                if entrypoint is None:
                    raise AttributeError(
                        f"{record.entry_file} has no function called {record.entry_attr!r}."
                    )

                # STEP 6: run the skill.
                result = entrypoint(context, cleaned_params)

                if isinstance(result, SkillResult):
                    summary = result.summary
                    data = result.data
                else:
                    # A skill that returns something unexpected is not treated as an
                    # attack, just as a badly written skill.
                    summary = str(result) if result is not None else ""
                    data = None

            except Exception as failure:
                outcome = "error"
                error_message = f"{type(failure).__name__}: {failure}"
                logger.info("Skill %s failed: %s", skill_id, error_message)

        duration_ms = int((time.monotonic() - started_at) * 1000)

        return InvocationResult(
            invocation_id=invocation_id,
            skill_id=skill_id,
            outcome=outcome,
            summary=summary,
            data=data,
            error=error_message,
            # The notebook is kept even when the skill crashed. What it managed to
            # touch before failing is still evidence.
            observations=notebook.entries(),
            duration_ms=duration_ms,
        )

    def _failure(
        self, invocation_id: str, skill_id: str, message: str, started_at: float
    ) -> InvocationResult:
        """
        Build a result for something that stopped before the skill ran at all.

        In: the run identifier, the skill, what went wrong, and when we started.
        Out: an InvocationResult marked as an error, with an empty notebook.
        """
        return InvocationResult(
            invocation_id=invocation_id,
            skill_id=skill_id,
            outcome="error",
            summary="",
            error=message,
            observations=[],
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )

    def _integrity_failure(
        self, invocation_id: str, skill_id: str, reason: str, started_at: float
    ) -> InvocationResult:
        """
        Build the fail-closed result for a refused run.

        In: the run identifier, the skill, the reason it was refused, and when we
        started. Out: an InvocationResult marked as an error, with an empty notebook.

        This mirrors `_failure` but is the dedicated shape for an integrity or
        reputation refusal (digest, revocation, signature) - a skill that fails its
        checks is never executed, and the reason travels back as the error so the
        activity screen can show why.
        """
        return self._failure(invocation_id, skill_id, reason, started_at)


# The app shares one host.
_host: SkillHost | None = None


def get_host() -> SkillHost:
    """The shared skill host."""
    global _host
    if _host is None:
        _host = SkillHost()
    return _host
