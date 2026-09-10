"""
Checks that the Focus Picker skill is a well-formed skill, that its description is the
honest-but-oversized one the weakness needs, and that the power it never uses really is
untouchable from its code.

These checks do not need a running app - they are about the skill's shape:

  - the platform finds and accepts it with no special wiring;
  - its manifest declares FOUR abilities where the job needs one, and declares them
    truthfully (this is what leaves "too much power" as the only axis that can catch it);
  - two of those four are never reachable from the code at all - the dormant power that
    makes the weakness "damage waiting for a bug";
  - the code never reaches around the app to touch files, sockets or other programs
    directly, so everything it does is recorded on the official channel.

That it really does reach beyond its remit while running is proved end to end in
test_focus_picker_e2e.py.

Specification references: feature spec sections 4.2, 4.3 and 4.4; decisions S-2, S-5,
S-6; build plan steps 1.1, 1.2 and 1.3; acceptance test A-11.
"""

from __future__ import annotations

from pathlib import Path

from tests.source_tools import called_function_names, executable_source, imported_modules

from app.skills import host as host_module
from app.skills import registry as registry_module

SKILL_DIR = Path(__file__).resolve().parents[1] / "skill" / "focus_picker"
SKILL_FILE = SKILL_DIR / "skill.py"


def _discovered_record(skill_id: str = "focus_picker"):
    """
    Find one skill the way the app itself would.

    In: the skill's identifier. Out: the registry's record for it.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()

    registry = registry_module.get_registry()
    registry.discover_default()
    return registry.get(skill_id)


def test_the_skill_is_discovered_and_valid(tmp_settings):
    """
    Dropping the folder in place is the only wiring needed: the registry finds it and
    accepts it, with no registration list to edit.

    Note what "valid" means here. The checks on a description only look at its SHAPE -
    are the fields present, are the ability names real ones. Nothing refuses a skill for
    asking for too much. That is precisely why an over-powered skill installs as smoothly
    as an honest one, and why the weakness is worth demonstrating.
    """
    record = _discovered_record()

    assert record is not None
    assert record.valid is True, f"focus_picker did not validate: {record.errors}"
    assert record.manifest.category == "reporting"
    assert record.manifest.name == "Focus Picker"


def test_the_manifest_asks_for_four_abilities_where_the_job_needs_one(tmp_settings):
    """
    The heart of the weakness. Naming the next task on a list needs one ability: reading
    the list. This description asks for four, in the open, with reasons attached.

    The category matters too: "reporting" is the kind of skill this genuinely is, so the
    yardstick it will be measured against is the honest one. It is not shopping for a
    more generous category to hide behind.
    """
    record = _discovered_record()

    declared = {declaration.id for declaration in record.manifest.capabilities}
    assert declared == {"task.read", "fs.read", "task.write", "net.outbound"}
    assert record.manifest.category == "reporting"


def test_the_two_unused_abilities_say_so_in_plain_words(tmp_settings):
    """
    DECISION S-5.

    Two of the four abilities are admitted, in the store, to be unused. That is as honest
    as a description can possibly be - and the permission is live anyway. A person reading
    the store is told "we do not use this", installs regardless, and the power is granted.
    """
    record = _discovered_record()
    reasons = {
        declaration.id: declaration.reason for declaration in record.manifest.capabilities
    }

    assert "Not used in this version" in reasons["task.write"]
    assert "Not used in this version" in reasons["net.outbound"]


def test_the_declared_file_scope_covers_the_file_it_actually_reads(tmp_settings):
    """
    The skill must stay TRUTHFUL, or it stops being this weakness and becomes the lying
    one (AST04). Its declared file scope has to cover the history file it really reads,
    otherwise the truthfulness check would speak up and the demonstration would no longer
    be "too much power" on its own.
    """
    from app.skills.scope import ScopeMatcher

    record = _discovered_record()
    file_scope = next(
        declaration.scope
        for declaration in record.manifest.capabilities
        if declaration.id == "fs.read"
    )

    assert ScopeMatcher.matches(file_scope, "data/activity.json", "path_glob") is True


def test_it_can_be_installed(installed_focus_picker):
    """Once installed, it appears in the list the model is shown."""
    installed_ids = {record.skill_id for record in installed_focus_picker.installed()}
    assert "focus_picker" in installed_ids


def test_the_power_it_never_uses_is_unreachable_from_its_code():
    """
    DECISION S-6 - the dormant half of the weakness.

    The skill holds permission to change your tasks and to contact the network, and never
    does either. This checks that at the level of the code itself, not just on one run:
    the words simply do not appear in anything that executes.

    We compare against the code with the explanations stripped out, because this file
    talks about those very abilities at length in plain English - and an explanation
    mentioning something is not the same as doing it.
    """
    code = executable_source(SKILL_FILE)

    for forbidden in ["ctx.net", "tasks.add", "tasks.update", "tasks.delete"]:
        assert forbidden not in code, f"the dormant power {forbidden!r} is being used"

    # The one thing it does reach for beyond its job, for contrast: it really is there.
    assert "ctx.files.read" in code
    assert "ctx.tasks.list" in code


def test_it_reaches_nothing_except_through_the_official_channel():
    """
    ACCEPTANCE TEST A-11.

    The skill must act only through ctx. It imports just what it needs from the app - not
    os, socket, httpx or subprocess - and never calls open() or the like. If it went
    around the app instead, its file read would be recorded by the watcher rather than
    the official channel, and would be reported as a BYPASS - a different problem
    belonging to a different weakness. Staying on the official channel is what makes this
    an over-powered skill and nothing else.
    """
    modules = imported_modules(SKILL_FILE)
    forbidden = {"os", "sys", "socket", "httpx", "subprocess", "pathlib", "urllib"}
    assert not (modules & forbidden), f"the skill imports something it should not: {modules & forbidden}"
    assert modules == {"app"}

    calls = called_function_names(SKILL_FILE)
    assert "open" not in calls
    assert "eval" not in calls
    assert "exec" not in calls
