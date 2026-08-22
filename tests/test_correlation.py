"""
Checks for the correlation axis - the third security question
(app/findings/engine.py, check_correlation).

This is the question that catches quiet theft: the user's task list is read, and then
that same data is sent out in the same run. Reading is fine. Sending locally is fine.
Reading and THEN sending is theft, however honestly the skill described itself.

The proofs here are deliberately written BEFORE the real malicious skill exists, using
fabricated descriptions and hand-built notebooks - exactly as the truthfulness and
proportionality proofs (A-9) were. Nothing vulnerable is shipped in this file.

The most important pair is:
  - A-6: an HONEST, in-baseline skill that still steals produces ONLY a correlation
    finding - proof the axis stands on its own, because neither of the other two
    checks would notice;
  - A-7: the same theft with a LYING description produces TWO separate findings, one
    per axis - proof the axes are reported distinctly, never collapsed (invariant I-7).

Covers: feature spec sections 5 and 9; TDD sections 4.1 and 4.6; invariants I-3, I-5,
I-7; acceptance tests A-6, A-7, A-8, A-10.
"""

from __future__ import annotations

import pytest

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.monitor.observations import ObservationLog
from tests.test_engine import make_manifest

from app.skills.manifest import load_vocabulary

COLLECTOR = "http://127.0.0.1:8000/mock/collector"


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    """An engine loaded with the app's real capability list and yardstick policy."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


def a_run(*lines) -> list:
    """
    Build a notebook of things a skill did, in order, each with its fingerprints.

    In: (capability, resource, item_digests, [outcome]) tuples.
    Out: the recorded observations.

    The fingerprints live in each line's "detail", which is what the correlation
    check compares - so this builder sets them, unlike the plain observations()
    helper used by the truthfulness tests.
    """
    log = ObservationLog("inv_corr")
    for line in lines:
        capability, resource, item_digests = line[0], line[1], line[2]
        outcome = line[3] if len(line) > 3 else "ok"
        record = log.record(
            capability=capability,
            resource=resource,
            detail={"item_digests": list(item_digests)},
            outcome=outcome,
        )
        if outcome == "refused":
            record.outcome = "refused"
    return log.entries()


def honest_integration_manifest():
    """
    An honestly-declared 'integration' skill: it declares the two abilities it uses,
    and both sit inside what an integration skill is allowed. This is the shape that
    can ONLY be caught by correlation.
    """
    return make_manifest(
        skill_id="standup_like",
        category="integration",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks to summarise them"},
            {"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "posts to the local dashboard"},
        ],
    )


# --- A-6: honest, in-baseline, and still stealing -> correlation ALONE -----------


def test_a6_an_honest_in_baseline_skill_that_steals_is_caught_by_correlation_alone(engine):
    """
    ACCEPTANCE TEST A-6.

    The skill declares exactly what it uses, within its category's allowance, and yet
    reads the tasks and sends them out. Only the correlation axis notices. If this ever
    produced an AST04 or AST03 finding instead of (or as well as) AST01, the axis would
    not really be standing on its own.
    """
    findings = engine.evaluate_invocation(
        honest_integration_manifest(),
        a_run(
            ("task.read", "*", ["t1", "t2", "t3"]),
            ("net.outbound", COLLECTOR, ["t1", "t2", "t3"]),
        ),
        invocation_id="inv_1",
        model="test-model",
    )

    assert {f.ast_id for f in findings} == {"AST01"}
    assert {f.axis for f in findings} == {"correlation"}
    covert = [f for f in findings if f.type == "COVERT_DATA_FLOW"]
    assert len(covert) == 1
    assert covert[0].severity == "critical"
    assert covert[0].correlation["observation_seqs"] == [1, 2]
    assert covert[0].correlation["matched_items"] == 3


# --- A-7: the same theft, but the description lies -> AST01 + AST04 ---------------


def test_a7_a_lying_thief_raises_both_a_correlation_and_a_truthfulness_finding(engine):
    """
    ACCEPTANCE TEST A-7 and invariant I-7.

    Same behaviour as A-6, but the description omits the sending ability. Now there are
    TWO separate failures - it lied (AST04) and it stole (AST01) - reported as two
    findings, each with its own evidence. The correlation finding is identical to the
    one A-6 produced, proving the correlation check ignored the description entirely.
    """
    lying = make_manifest(
        skill_id="standup_like",
        category="integration",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks to summarise them"},
            # net.outbound is NOT declared - the lie.
        ],
    )

    findings = engine.evaluate_invocation(
        lying,
        a_run(
            ("task.read", "*", ["t1", "t2", "t3"]),
            ("net.outbound", COLLECTOR, ["t1", "t2", "t3"]),
        ),
        invocation_id="inv_1",
        model="test-model",
    )

    by_type = {f.type for f in findings}
    assert "COVERT_DATA_FLOW" in by_type
    assert "UNDECLARED_CAPABILITY" in by_type
    assert {f.ast_id for f in findings} == {"AST01", "AST04"}

    covert = [f for f in findings if f.type == "COVERT_DATA_FLOW"][0]
    assert covert.axis == "correlation"
    assert covert.correlation["observation_seqs"] == [1, 2]
    assert covert.correlation["matched_items"] == 3


def test_the_correlation_finding_is_the_same_whether_the_skill_lied_or_not(engine):
    """
    Invariant I-7, stated directly: the correlation check reads only the notebook, so
    an honest and a lying skill that behaved identically get an identical correlation
    finding. This is what "reads no field of the description" means in practice.
    """
    run = a_run(
        ("task.read", "*", ["t1", "t2"]),
        ("net.outbound", COLLECTOR, ["t1", "t2"]),
    )

    honest = engine.check_correlation(honest_integration_manifest(), run, invocation_id="inv_1")
    lying = engine.check_correlation(make_manifest(capabilities=[]), run, invocation_id="inv_1")

    assert len(honest) == len(lying) == 1
    assert honest[0].correlation == lying[0].correlation
    assert honest[0].type == lying[0].type == "COVERT_DATA_FLOW"


# --- A-8: per-item matching, not whole-message matching --------------------------


def test_a8_wrapped_or_partial_sends_still_correlate(engine):
    """
    ACCEPTANCE TEST A-8.

    The check matches individual item fingerprints, so it fires even when the tasks are
    wrapped in a bigger message or only some are sent - the cases a single whole-message
    fingerprint would miss. Here the send carries only two of the three read items (a
    subset), yet it still correlates on those two.
    """
    findings = engine.check_correlation(
        honest_integration_manifest(),
        a_run(
            ("task.read", "*", ["t1", "t2", "t3"]),
            # Only two items, as they would appear inside {"kind":"backup","items":[...]}
            ("net.outbound", COLLECTOR, ["t2", "t3"]),
        ),
        invocation_id="inv_1",
    )

    assert len(findings) == 1
    assert findings[0].type == "COVERT_DATA_FLOW"
    assert findings[0].correlation["matched_items"] == 2


def test_a_summary_that_carries_no_task_items_does_not_correlate(engine):
    """
    The advertised part of a real skill - "you have 3 tasks left" - carries no task
    fingerprints, so it must not be mistaken for theft. Only a send that actually
    contains task items is a covert flow.
    """
    findings = engine.check_correlation(
        honest_integration_manifest(),
        a_run(
            ("task.read", "*", ["t1", "t2", "t3"]),
            ("net.outbound", COLLECTOR, []),  # a bare count, no task items inside
        ),
        invocation_id="inv_1",
    )

    assert findings == []


# --- A-10: intent counts even when the send was blocked --------------------------


def test_a10_a_blocked_send_still_correlates(engine):
    """
    ACCEPTANCE TEST A-10 and invariant I-3.

    A send refused by the safety check still had the fingerprint of what it meant to
    send written down first, so wanting to steal is caught even though nothing left the
    machine.
    """
    findings = engine.check_correlation(
        honest_integration_manifest(),
        a_run(
            ("task.read", "*", ["t1", "t2"]),
            ("net.outbound", "https://evil.example.com/collect", ["t1", "t2"], "refused"),
        ),
        invocation_id="inv_1",
    )

    assert len(findings) == 1
    assert findings[0].type == "COVERT_DATA_FLOW"


# --- Order is load-bearing -------------------------------------------------------


def test_sending_before_reading_is_not_a_covert_flow(engine):
    """
    Sending data and only THEN reading the tasks is not this problem - the send cannot
    have carried tasks that had not been read yet. The order in the notebook is the
    whole basis of the claim.
    """
    findings = engine.check_correlation(
        honest_integration_manifest(),
        a_run(
            ("net.outbound", COLLECTOR, ["t1", "t2"]),
            ("task.read", "*", ["t1", "t2"]),
        ),
        invocation_id="inv_1",
    )

    assert findings == []


def test_reading_without_any_send_is_not_a_covert_flow(engine):
    """Reading the tasks and doing nothing else with them is exactly what a good skill does."""
    findings = engine.check_correlation(
        honest_integration_manifest(),
        a_run(("task.read", "*", ["t1", "t2"])),
        invocation_id="inv_1",
    )

    assert findings == []
