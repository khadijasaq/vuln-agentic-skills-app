"""
Checks for the single entrance through which skills are run (app/skills/host.py).

The skills used here are harmless stand-ins written just for these tests. They are
NOT the deliberately vulnerable skills - those belong to separate features and
nothing vulnerable exists in this one.

Covers: feature spec section 5.6; decisions S-20 and S-21; invariant I-1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.monitor import audit_hook
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.skills.host import SkillHost
from app.skills.registry import SkillRegistry, SkillSource

from tests.test_manifest import GOOD_MANIFEST


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test starts with no remembered skills and no loaded code."""
    audit_hook.install_audit_hook()
    registry_module.reset_registry()
    host_module.clear_module_cache()
    yield
    registry_module.reset_registry()
    host_module.clear_module_cache()


def make_skill(catalogue: Path, skill_id: str, code: str, manifest_changes: dict | None = None):
    """
    Create a harmless stand-in skill for a test.

    In: where to put it, its identifier, the code to run, and any manifest changes.
    Out: nothing.
    """
    folder = catalogue / skill_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {**GOOD_MANIFEST, "id": skill_id, **(manifest_changes or {})}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "skill.py").write_text(code, encoding="utf-8")


def install_and_get_host(catalogue: Path, skill_id: str) -> SkillHost:
    """Discover the folder, switch the skill on, and hand back a host to run it."""
    registry = registry_module.get_registry()
    registry.discover([(SkillSource.CATALOGUE, catalogue)])
    registry.install(skill_id)
    return SkillHost()


SIMPLE_SKILL = '''
from app.skills.context import SkillResult

def run(ctx, params):
    tasks = ctx.tasks.list(params.get("scope", "all"))
    return SkillResult(summary=f"Found {len(tasks)} tasks.", data={"count": len(tasks)})
'''


# --- Normal running --------------------------------------------------------------


def test_a_skill_runs_and_hands_back_its_answer(tmp_settings, tmp_path):
    """The basic case: the skill runs, and its summary and data come back."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "simple_skill", SIMPLE_SKILL)
    host = install_and_get_host(catalogue, "simple_skill")

    result = host.invoke("simple_skill", {"scope": "all"})

    assert result.outcome == "ok"
    assert "tasks" in result.summary
    assert result.data["count"] >= 0
    assert result.duration_ms >= 0


def test_everything_the_skill_touched_is_recorded(tmp_settings, tmp_path):
    """The notebook comes back with the result, so nothing is lost."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "simple_skill", SIMPLE_SKILL)
    host = install_and_get_host(catalogue, "simple_skill")

    result = host.invoke("simple_skill", {})

    assert len(result.observations) == 1
    assert result.observations[0].capability == "task.read"


def test_each_run_gets_its_own_identifier(tmp_settings, tmp_path):
    """Two runs are separate events with separate records."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "simple_skill", SIMPLE_SKILL)
    host = install_and_get_host(catalogue, "simple_skill")

    first = host.invoke("simple_skill", {})
    second = host.invoke("simple_skill", {})

    assert first.invocation_id != second.invocation_id


# --- Refusing to run -------------------------------------------------------------


def test_a_skill_that_is_not_installed_does_not_run(tmp_settings, tmp_path):
    """
    THE RULE THAT MAKES THE SAFE BASELINE REAL.

    A skill sitting on disk but switched off cannot be run, whatever asks for it.
    """
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "simple_skill", SIMPLE_SKILL)
    registry = registry_module.get_registry()
    registry.discover([(SkillSource.CATALOGUE, catalogue)])
    # Deliberately NOT installed.

    result = SkillHost().invoke("simple_skill", {})

    assert result.outcome == "error"
    assert "not installed" in result.error
    assert result.observations == []


def test_a_broken_skill_does_not_run(tmp_settings, tmp_path):
    """A skill that failed its checks is never executed."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "broken_skill", SIMPLE_SKILL, {"category": "nonsense"})
    registry = registry_module.get_registry()
    registry.discover([(SkillSource.CATALOGUE, catalogue)])

    result = SkillHost().invoke("broken_skill", {})

    assert result.outcome == "error"


# --- Checking the values the AI model supplied -----------------------------------


def test_values_that_do_not_match_are_rejected_without_running(tmp_settings, tmp_path):
    """
    The model can supply anything. Values that do not match what the skill said it
    accepts stop the run before any skill code executes.
    """
    catalogue = tmp_path / "catalogue"
    make_skill(
        catalogue,
        "picky_skill",
        SIMPLE_SKILL,
        {
            "invocation": {
                "when_to_use": "whenever",
                "parameters": {
                    "type": "object",
                    "properties": {"scope": {"type": "string", "enum": ["all", "open"]}},
                    "required": ["scope"],
                },
            }
        },
    )
    host = install_and_get_host(catalogue, "picky_skill")

    result = host.invoke("picky_skill", {"scope": "not-a-valid-choice"})

    assert result.outcome == "error"
    assert result.observations == []


def test_extra_invented_values_are_dropped(tmp_settings, tmp_path):
    """
    A model inventing extra values must not be able to smuggle anything through, so
    anything the skill did not ask for is discarded.
    """
    catalogue = tmp_path / "catalogue"
    make_skill(
        catalogue,
        "echo_skill",
        '''
from app.skills.context import SkillResult

def run(ctx, params):
    return SkillResult(summary="ok", data={"received": sorted(params)})
''',
    )
    host = install_and_get_host(catalogue, "echo_skill")

    result = host.invoke("echo_skill", {"scope": "all", "sneaky": "value"})

    assert result.outcome == "ok"
    assert "sneaky" not in result.data["received"]


# --- When a skill goes wrong -----------------------------------------------------


def test_a_crashing_skill_does_not_break_the_app(tmp_settings, tmp_path):
    """
    One broken skill must not take down the whole exchange. The failure is reported
    as an error result rather than thrown upwards.
    """
    catalogue = tmp_path / "catalogue"
    make_skill(
        catalogue,
        "crashing_skill",
        '''
def run(ctx, params):
    raise RuntimeError("this skill is broken")
''',
    )
    host = install_and_get_host(catalogue, "crashing_skill")

    result = host.invoke("crashing_skill", {})

    assert result.outcome == "error"
    assert "this skill is broken" in result.error


def test_what_a_crashing_skill_touched_is_still_recorded(tmp_settings, tmp_path):
    """
    Evidence gathered before a crash is kept. A skill that reads your task list and
    then fails still read your task list.
    """
    catalogue = tmp_path / "catalogue"
    make_skill(
        catalogue,
        "half_skill",
        '''
def run(ctx, params):
    ctx.tasks.list("all")
    raise RuntimeError("failed after reading")
''',
    )
    host = install_and_get_host(catalogue, "half_skill")

    result = host.invoke("half_skill", {})

    assert result.outcome == "error"
    assert len(result.observations) == 1
    assert result.observations[0].capability == "task.read"


# --- The markers are always cleaned up -------------------------------------------


def test_the_markers_are_cleared_after_a_normal_run(tmp_settings, tmp_path):
    """
    If the "a skill is running" marker were left set, everything the app did
    afterwards would be wrongly blamed on this skill.
    """
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "simple_skill", SIMPLE_SKILL)
    host = install_and_get_host(catalogue, "simple_skill")

    host.invoke("simple_skill", {})

    assert audit_hook.CURRENT_INVOCATION.get() is None
    assert audit_hook.CURRENT_LOG.get() is None


def test_the_markers_are_cleared_after_a_crash(tmp_settings, tmp_path):
    """Same again, for the case that actually tends to leak."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "crashing_skill", 'def run(ctx, params):\n    raise RuntimeError("x")\n')
    host = install_and_get_host(catalogue, "crashing_skill")

    host.invoke("crashing_skill", {})

    assert audit_hook.CURRENT_INVOCATION.get() is None


# --- Loading a skill's code ------------------------------------------------------


def test_anything_a_skill_does_while_being_loaded_is_watched(tmp_settings, tmp_path):
    """
    DECISION S-21.

    Python runs a file's top-level code the moment it is loaded, so a skill could
    try something the instant it is imported - before its main function is ever
    called. Loading inside the "a skill is running" marker means even that is caught.
    """
    catalogue = tmp_path / "catalogue"
    sneaky_file = tmp_settings.data_dir / "read-at-import.txt"
    sneaky_file.parent.mkdir(parents=True, exist_ok=True)
    sneaky_file.write_text("contents", encoding="utf-8")

    make_skill(
        catalogue,
        "import_time_skill",
        f'''
# This runs the moment the skill is loaded, not when it is called.
with open(r"{sneaky_file}", "r", encoding="utf-8") as handle:
    handle.read()

from app.skills.context import SkillResult

def run(ctx, params):
    return SkillResult(summary="done")
''',
    )
    host = install_and_get_host(catalogue, "import_time_skill")

    result = host.invoke("import_time_skill", {})

    caught = [entry for entry in result.observations if entry.capability == "fs.read"]
    assert caught, "activity during loading was not watched"
    assert caught[0].source == "audit_hook"


def test_a_skill_is_only_loaded_once(tmp_settings, tmp_path):
    """
    Loading is remembered, so running a skill repeatedly does not re-read it from
    disk every time (decision S-20).
    """
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "simple_skill", SIMPLE_SKILL)
    host = install_and_get_host(catalogue, "simple_skill")

    host.invoke("simple_skill", {})
    loaded_after_first = len(host_module._loaded_modules)
    host.invoke("simple_skill", {})

    assert len(host_module._loaded_modules) == loaded_after_first


def test_a_skill_whose_code_cannot_be_loaded_is_an_error(tmp_settings, tmp_path):
    """Broken Python in a skill is reported, not crashed on."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "syntax_skill", "def run(ctx, params)\n    this is not python\n")
    host = install_and_get_host(catalogue, "syntax_skill")

    result = host.invoke("syntax_skill", {})

    assert result.outcome == "error"


def test_a_skill_missing_its_function_is_an_error(tmp_settings, tmp_path):
    """The manifest promised a function called run; if it is missing, say so."""
    catalogue = tmp_path / "catalogue"
    make_skill(catalogue, "no_run_skill", "def something_else(ctx, params):\n    pass\n")
    host = install_and_get_host(catalogue, "no_run_skill")

    result = host.invoke("no_run_skill", {})

    assert result.outcome == "error"
    assert "run" in result.error


# --- The integrity gate -----------------------------------------------------------


def test_a_registered_integrity_check_refusal_returns_error_without_running(tmp_settings, tmp_path):
    """
    THE FAIL-CLOSED GATE (AST02 T-03).

    Any check on the INTEGRITY_CHECKS list can refuse a run. When one refuses, the
    skill returns an "error" outcome and the skill's top-level code is never run.
    """
    catalogue = tmp_path / "catalogue"
    marker = tmp_path / "imported.txt"
    make_skill(
        catalogue,
        "guarded_skill",
        f'''
from pathlib import Path

def run(ctx, params):
    Path(r"{marker}").write_text("ran")
    return None
''',
    )
    host = install_and_get_host(catalogue, "guarded_skill")

    # Register a temporary predicate that always refuses this run.
    def refuse(record, invocation_id):
        return "refused by test"

    host_module.INTEGRITY_CHECKS.append(refuse)
    try:
        result = host.invoke("guarded_skill", {})
    finally:
        host_module.INTEGRITY_CHECKS.remove(refuse)

    assert result.outcome == "error"
    assert "refused by test" in result.error
    # The skill's code never ran, so it never wrote its marker.
    assert not marker.exists()
