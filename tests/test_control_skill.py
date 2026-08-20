"""
Checks for the honest skill, and the proof that the app stays quiet about it.

ACCEPTANCE TEST A-4 IS THE MOST IMPORTANT CHECK IN THIS PROJECT.

Every other skill in this product is deliberately flawed, to demonstrate a
particular security problem. This one is completely honest. If the app ever reports
a problem with THIS skill, then the app itself is wrong - and every other result it
produces becomes suspect.

"The scanner found three problems" only means something if something also proves the
scanner can stay quiet. That proof is here.

Covers: feature spec section 10; requirement FR-4.6; goal G5; success criterion
SC-3; invariant I-12; acceptance tests A-4 and A-18.
"""

from __future__ import annotations

import pytest

from app.chat.orchestrator import ChatOrchestrator
from app.findings.markers import count_markers
from app.llm.ollama_client import ChatResponse, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.skills.host import SkillHost
from app.storage import seed, store


class ModelThatAsksForTheSummary:
    """A stand-in model that always asks for the honest skill, then replies."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls % 2 == 1:
            return ChatResponse(
                content="", tool_calls=[ToolCall("task_summary", {"scope": "all"})], model="stub"
            )
        return ChatResponse(content="You are making steady progress.", tool_calls=[], model="stub")


@pytest.fixture
def installed_control_skill(tmp_settings):
    """The real shipped control skill, discovered and switched on."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("task_summary")

    yield registry

    registry_module.reset_registry()
    host_module.clear_module_cache()


# --- The skill does its job ------------------------------------------------------


def test_it_summarises_the_task_list(installed_control_skill, tmp_settings):
    """It is genuinely useful, not a token test fixture."""
    result = SkillHost().invoke("task_summary", {"scope": "all"})

    assert result.outcome == "ok"
    assert result.data["total"] == 8
    assert result.data["done"] == 3
    assert result.data["open"] == 5
    assert "8 tasks" in result.summary


def test_it_names_the_longest_outstanding_task(installed_control_skill, tmp_settings):
    """The genuinely useful part - what have I been putting off?"""
    result = SkillHost().invoke("task_summary", {"scope": "all"})

    assert result.data["oldest_open"] is not None
    assert "Longest outstanding" in result.summary


def test_it_handles_the_scopes(installed_control_skill, tmp_settings):
    open_only = SkillHost().invoke("task_summary", {"scope": "open"})
    done_only = SkillHost().invoke("task_summary", {"scope": "done"})

    assert open_only.data["total"] == 5
    assert done_only.data["total"] == 3


def test_an_empty_list_is_a_normal_answer(tmp_settings):
    """An empty list is a valid summary, not an error."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    store.save_tasks([])

    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("task_summary")

    result = SkillHost().invoke("task_summary", {})

    assert result.outcome == "ok"
    assert result.data["total"] == 0
    assert "empty" in result.summary.lower()


# --- ACCEPTANCE TEST A-4: the app stays quiet ------------------------------------


def test_a4_twenty_runs_produce_no_findings_at_all(installed_control_skill, tmp_settings):
    """
    ACCEPTANCE TEST A-4 - the headline promise of this whole feature.

    Twenty complete exchanges, each one running the honest skill for real, through
    the same path a live model would use. Afterwards there must be NO findings and NO
    evidence files.

    If this fails, the most likely cause is that the app has started blaming a skill
    for the app's own work - the failure mode the whole monitor design exists to
    prevent.
    """
    orchestrator = ChatOrchestrator(client=ModelThatAsksForTheSummary())

    for _ in range(20):
        result = orchestrator.run_turn("how am I doing?")
        assert result.activity.skill_invoked is not None
        assert result.activity.skill_invoked.outcome == "ok"

    assert store.load_findings() == [], "the honest skill was reported for something"
    assert count_markers() == 0, "evidence was written for a skill that did nothing wrong"


def test_a4_no_exchange_is_ever_flagged(installed_control_skill, tmp_settings):
    """The activity screen must show twenty clean rows, none highlighted."""
    orchestrator = ChatOrchestrator(client=ModelThatAsksForTheSummary())

    for _ in range(20):
        orchestrator.run_turn("how am I doing?")

    assert all(entry.vulnerability_fired is False for entry in store.load_activity())


def test_a4_each_reason_it_could_have_been_flagged_is_closed(installed_control_skill, tmp_settings):
    """
    The six ways this skill could have been reported, checked one at a time - so a
    future failure names its own cause instead of just saying "something changed".
    """
    result = SkillHost().invoke("task_summary", {"scope": "all"})
    observations = result.observations

    # 1. It did exactly one thing, and that thing is what it declared.
    assert len(observations) == 1
    assert observations[0].capability == "task.read"

    # 2. It used the official channel, so there is nothing to report as going around it.
    assert observations[0].source == "broker"

    # 3. The app's own file access while answering was not blamed on the skill.
    assert not any(entry.capability.startswith("fs.") for entry in observations)

    # 4. It never touched the network.
    assert not any(entry.capability == "net.outbound" for entry in observations)

    # 5. Its one ability is within what a reporting skill is allowed.
    from app.findings.baselines import load_baselines

    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    assert "task.read" in baselines["reporting"].allowed

    # 6. It actually uses the ability it holds, so nothing is held unused.
    declared = {
        declaration.id
        for declaration in registry_module.get_registry().get("task_summary").manifest.capabilities
    }
    used = {entry.capability for entry in observations}
    assert declared == used


# --- ACCEPTANCE TEST A-18: the groundwork for later checks -----------------------


def test_a18_the_record_is_ordered_and_fingerprinted(installed_control_skill, tmp_settings):
    """
    ACCEPTANCE TEST A-18.

    A later piece of work needs to prove "this exact information was read, and THEN
    sent somewhere". That needs two things which must be in place now: an exact order,
    and a fingerprint of what was read. Both are checked here so they cannot quietly
    stop working before anything depends on them.
    """
    result = SkillHost().invoke("task_summary", {"scope": "all"})
    record = result.observations[0]

    assert record.seq == 1
    assert len(record.detail["sha256"]) == 64
    assert len(record.detail["item_digests"]) == 8
    assert all(len(digest) == 64 for digest in record.detail["item_digests"])


# --- It is not switched on by default --------------------------------------------


def test_no_skill_is_switched_on_when_the_lab_is_new(tmp_settings):
    """
    A brand new lab starts with nothing installed, so a reviewer sees a complete,
    safe assistant BEFORE anything is added (TDD section 14, Q-6).
    """
    registry_module.reset_registry()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    found = registry.discover_default()

    assert any(record.skill_id == "task_summary" for record in found)
    assert registry.installed() == []


def test_the_shipped_skill_passes_its_own_checks(tmp_settings):
    """
    Whatever is actually shipped must be valid. A broken skill in the real catalogue
    would be a defect in the product itself.
    """
    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()

    record = registry.get("task_summary")
    assert record.valid, record.errors
    assert record.manifest.category == "reporting"
    assert [c.id for c in record.manifest.capabilities] == ["task.read"]


def test_the_skill_imports_nothing_dangerous():
    """
    Confirm the honest skill reaches for nothing outside the official channel.

    This looks at the STRUCTURE of the file rather than searching its text. The
    skill's own description quite reasonably mentions the things it avoids, and a
    plain text search would be fooled by that explanation.
    """
    from pathlib import Path

    from tests.source_tools import called_function_names, imported_modules

    source = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "catalogue"
        / "task_summary"
        / "skill.py"
    )

    # The only thing it brings in is the official channel it is handed anyway.
    assert imported_modules(source) == {"app"}

    # And it never reaches for a file directly.
    assert "open" not in called_function_names(source)
