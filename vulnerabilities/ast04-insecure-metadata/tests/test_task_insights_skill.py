"""
Checks that the Task Insights skill is a well-formed skill and that it acts only
through the official channel.

These checks do not need a running app - they are about the skill's shape: that the
platform finds and accepts it with no special wiring, that its manifest declares only
the one honest ability (so the file read and network call it performs really are
undeclared), and that its code never reaches around the app to touch files, sockets or
other programs directly. (That it actually reads a file and calls the network, neither
declared, is proved end to end in test_task_insights_e2e.py.)

Specification references: feature spec sections 4.2, 4.3 and 4.4; build plan steps 1.1,
1.2 and 1.3.
"""

from __future__ import annotations

from pathlib import Path

from tests.source_tools import called_function_names, imported_modules

from app.skills import host as host_module
from app.skills import registry as registry_module

SKILL_FILE = Path(__file__).resolve().parents[1] / "skill" / "task_insights" / "skill.py"


def test_the_skill_is_discovered_and_valid(tmp_settings):
    """
    Dropping the folder in place is the only wiring needed: the registry finds it and
    accepts it, with no registration list to edit.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()

    registry = registry_module.get_registry()
    found = registry.discover_default()

    record = registry.get("task_insights")
    assert record is not None
    assert record.valid is True, f"task_insights did not validate: {record.errors}"
    assert record.manifest.category == "reporting"
    assert {"task_insights"} <= {r.skill_id for r in found}


def test_the_manifest_declares_only_reading_tasks(tmp_settings):
    """
    The heart of the lie: the manifest admits to exactly one ability - reading tasks -
    so the file read and the network call the code also performs are genuinely
    undeclared. This is what leaves the truthfulness check as the axis that catches it.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()

    registry = registry_module.get_registry()
    registry.discover_default()
    record = registry.get("task_insights")

    declared = {declaration.id for declaration in record.manifest.capabilities}
    assert declared == {"task.read"}
    assert "fs.read" not in declared
    assert "net.outbound" not in declared


def test_it_can_be_installed(installed_task_insights):
    """Once installed, it appears in the list the model is shown."""
    installed_ids = {record.skill_id for record in installed_task_insights.installed()}
    assert "task_insights" in installed_ids


def test_it_reaches_nothing_except_through_the_official_channel():
    """
    The skill must act only through ctx. It imports just SkillResult - not os, socket,
    httpx or subprocess - and never calls open() or the like. If it did, its file read
    and network call would be going AROUND the app, which is a different (and separately
    detected) problem - BROKER_BYPASS. Here we confirm both undeclared acts are done
    entirely through the sanctioned channel, so they surface as UNDECLARED_CAPABILITY.
    """
    modules = imported_modules(SKILL_FILE)
    forbidden = {"os", "sys", "socket", "httpx", "subprocess", "pathlib", "urllib"}
    assert not (modules & forbidden), f"the skill imports something it should not: {modules & forbidden}"
    # The only thing it brings in is from the app's own skill context.
    assert modules == {"app"}

    calls = called_function_names(SKILL_FILE)
    assert "open" not in calls
    assert "eval" not in calls
    assert "exec" not in calls
