"""
Proves the Task Insights skill fires the truthfulness axis ALONE, and that the finding
tracks the DECLARATION, not the behaviour - on hand-built fixtures, before the skill is
wired end to end.

These are the load-bearing proofs of this weakness:

  - A-6: the real, shipped manifest (which declares only "reads tasks") together with a
    run that also reads a file and calls the network produces ONLY "did not tell the
    truth" findings - no "too much power" (AST03), no "quiet theft" (AST01). This is the
    proof the truthfulness axis stands on its own.
  - A-7: give the SAME behaviour an honest description that declares the file read and
    the network call, and the truthfulness findings vanish - proof the finding is the
    gap between word and deed, not the deed itself (invariant I-7).

A-8 shows a blocked act is judged the same as a successful one (intent is the event),
and A-10 shows that acting through the official channel is "undeclared", while going
around it would be the separate "bypass" problem.

The manifests and notebooks below are fabricated test material fed straight to the
engine; nothing here runs the real skill (that is proved in test_task_insights_e2e.py).

Covers: feature spec sections 4, 5 and 6; TDD sections 4.1 and 4.4; invariants I-3, I-7;
acceptance tests A-6, A-7, A-8, A-10.
"""

from __future__ import annotations

import pytest

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.monitor.observations import ObservationLog
from app.skills.manifest import load_vocabulary
from app.skills import host as host_module
from app.skills import registry as registry_module

from tests.test_engine import make_manifest

COLLECTOR = "http://127.0.0.1:8000/mock/collector"
TASK_FILE = "data/tasks.json"


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    """An engine loaded with the app's real capability list and yardstick policy."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


@pytest.fixture
def shipped_manifest(tmp_settings):
    """
    The REAL Task Insights manifest, read from disk exactly as the app would load it.

    Using the shipped manifest (not a stand-in) is what makes A-6 a proof about this
    skill: it declares only task.read, so the file read and network call it performs are
    genuinely undeclared.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()
    registry = registry_module.get_registry()
    registry.discover_default()
    return registry.get("task_insights").manifest


def did(*lines) -> list:
    """
    Build the ordered notebook of what a skill did.

    In: (capability, resource[, outcome[, source]]) tuples. Out: the observations.

    The truthfulness check reads a line's capability, resource, outcome and source -
    not its detail - so this simple builder is all these proofs need.
    """
    log = ObservationLog("inv_ast04")
    for line in lines:
        capability, resource = line[0], line[1]
        outcome = line[2] if len(line) > 2 else "ok"
        source = line[3] if len(line) > 3 else "broker"
        log.record(capability=capability, resource=resource, outcome=outcome, source=source)
    return log.entries()


# --- A-6: the shipped skill fires AST04 alone ------------------------------------


def test_a6_task_insights_fires_ast04_alone(engine, shipped_manifest):
    """
    ACCEPTANCE TEST A-6.

    The shipped manifest declares only task.read. A run that also reads a file and calls
    the network must produce ONLY the truthfulness axis - two "undeclared ability"
    findings - and NOT a proportionality (AST03) or correlation (AST01) finding. If it
    ever produced one of those instead of, or as well as, AST04, the axis would not
    really stand on its own.
    """
    findings = engine.evaluate_invocation(
        shipped_manifest,
        did(
            ("task.read", "*"),
            ("fs.read", TASK_FILE),
            ("net.outbound", COLLECTOR),
        ),
        invocation_id="inv_1",
        model="test-model",
    )

    assert {f.axis for f in findings} == {"truthfulness"}
    assert {f.ast_id for f in findings} == {"AST04"}

    undeclared = [f for f in findings if f.type == "UNDECLARED_CAPABILITY"]
    assert len(undeclared) == 2
    assert {f.observed["capability"] for f in undeclared} == {"fs.read", "net.outbound"}
    assert all(f.severity == "high" for f in undeclared)

    # Explicitly: neither of the other two axes speaks.
    assert [f for f in findings if f.axis == "proportionality"] == []
    assert [f for f in findings if f.axis == "correlation"] == []


# --- A-7: declaring the abilities makes the finding vanish -----------------------


def test_a7_declaring_the_abilities_removes_the_truthfulness_finding(engine):
    """
    ACCEPTANCE TEST A-7 and invariant I-7.

    Same behaviour, but now an honest description declares the file read and the network
    call, both in scope. The truthfulness findings disappear entirely - proof the finding
    is the gap between what was declared and what was done, not the doing itself. (This
    honest-but-broad description over-reaches its category, so a DIFFERENT axis -
    proportionality - may speak; that is expected and is not this test's concern.)
    """
    honest = make_manifest(
        skill_id="task_insights_honest",
        category="reporting",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks to summarise them"},
            {"id": "fs.read", "scope": ["*"], "reason": "honestly declared file read"},
            {"id": "net.outbound", "scope": ["*"], "reason": "honestly declared usage ping"},
        ],
    )

    findings = engine.evaluate_invocation(
        honest,
        did(
            ("task.read", "*"),
            ("fs.read", TASK_FILE),
            ("net.outbound", COLLECTOR),
        ),
        invocation_id="inv_1",
        model="test-model",
    )

    assert [f for f in findings if f.type == "UNDECLARED_CAPABILITY"] == []
    assert [f for f in findings if f.axis == "truthfulness"] == []


# --- A-8: a blocked act is still a lie -------------------------------------------


def test_a8_a_refused_undeclared_act_still_fires(engine, shipped_manifest):
    """
    ACCEPTANCE TEST A-8 and invariant I-3.

    Wanting to do the undeclared thing is the security event. Both an undeclared network
    call refused for pointing off-machine and an undeclared file read refused for
    reaching outside the allowed folders were written down before being refused, so both
    still raise "undeclared ability".
    """
    findings = engine.check_truthfulness(
        shipped_manifest,
        did(
            ("task.read", "*"),
            ("net.outbound", "https://telemetry.example.com/ping", "refused"),
            ("fs.read", "C:/Windows/System32/config/SAM", "refused"),
        ),
        invocation_id="inv_1",
    )

    undeclared = [f for f in findings if f.type == "UNDECLARED_CAPABILITY"]
    assert {f.observed["capability"] for f in undeclared} == {"net.outbound", "fs.read"}


# --- A-10: through the channel is "undeclared", around it is "bypass" -------------


def test_a10_through_the_broker_is_undeclared_not_bypass(engine, shipped_manifest):
    """
    ACCEPTANCE TEST A-10.

    The real skill acts through the official channel, so its undeclared file read is
    recorded as coming from the broker - which the truthfulness check names
    "undeclared ability". Had the skill gone AROUND the app instead, the same act would
    be recorded as coming from the watcher and named "bypass" - a different failure. This
    proves the two are told apart by where the act was seen.
    """
    through_the_channel = engine.check_truthfulness(
        shipped_manifest,
        did(("fs.read", TASK_FILE)),  # source defaults to "broker"
        invocation_id="inv_1",
    )
    assert {f.type for f in through_the_channel} == {"UNDECLARED_CAPABILITY"}

    around_the_app = engine.check_truthfulness(
        shipped_manifest,
        did(("fs.read", TASK_FILE, "ok", "audit_hook")),
        invocation_id="inv_1",
    )
    assert "BROKER_BYPASS" in {f.type for f in around_the_app}
