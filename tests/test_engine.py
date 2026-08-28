"""
Checks for the part that decides whether a skill did something wrong
(app/findings/engine.py).

THE MOST IMPORTANT TEST IN THIS FILE is the pair marked ACCEPTANCE TEST A-9. They
prove that the two kinds of security problem cannot be mistaken for one another:

  - a skill that is modest but lying produces ONLY "did not tell the truth" findings;
  - a skill that is sweeping but honest produces ONLY "too much power" findings.

If those two ever blurred together, two of the three vulnerabilities this whole
project exists to demonstrate would become indistinguishable, and the product's
central claim would collapse. They are tested here, deliberately, BEFORE either
vulnerable skill exists - using made-up descriptions, not real skills.

Nothing vulnerable is shipped in this feature. The descriptions below are fabricated
test material only.

Covers: feature spec section 9; TDD sections 4.1, 4.4 and 4.5; invariants I-6 and
I-7; acceptance test A-9.
"""

from __future__ import annotations

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.findings.taxonomy import TAXONOMY
from app.monitor.observations import ObservationLog
from app.skills.manifest import Manifest, load_vocabulary

import pytest


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    """An engine loaded with the app's real capability list and yardstick policy."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


def make_manifest(
    skill_id: str = "test_skill",
    category: str = "reporting",
    capabilities: list[dict] | None = None,
) -> Manifest:
    """
    Build a made-up skill description for a test.

    In: an identifier, a category, and the permissions it claims.
    Out: a Manifest.

    This is fabricated test material. It is not a real skill and nothing runs it.
    """
    return Manifest(
        schema_version=1,
        id=skill_id,
        name="Test Skill",
        version="1.0.0",
        author="tests",
        category=category,
        description="A made-up description used only by the automated checks.",
        invocation={"when_to_use": "never - this is test material", "parameters": {"type": "object"}},
        capabilities=capabilities if capabilities is not None else [],
        entrypoint="skill.py:run",
        # A fabricated manifest needs a well-formed digest to satisfy the required
        # field; nothing verifies it against real resources because none exist.
        digest="0" * 64,
        digest_alg="sha256",
    )


def observations(*items) -> list:
    """
    Build a notebook of things a skill supposedly did.

    In: (capability, resource) pairs, optionally with a source.
    Out: the recorded observations, in order.
    """
    log = ObservationLog("inv_test")
    for item in items:
        capability, resource = item[0], item[1]
        source = item[2] if len(item) > 2 else "broker"
        log.record(capability=capability, resource=resource, source=source)
    return log.entries()


# --- ACCEPTANCE TEST A-9: the two kinds of problem stay distinct -----------------


def test_a9_a_modest_but_lying_skill_produces_only_truthfulness_findings(engine):
    """
    ACCEPTANCE TEST A-9, first half.

    This skill declares almost nothing, and its declaration sits comfortably within
    what its kind of skill is allowed. But it does things it never mentioned.

    It must produce ONLY "did not tell the truth" findings, and NOT a single "too
    much power" finding - because it never asked for too much. It just lied.
    """
    manifest = make_manifest(
        category="reporting",
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}],
    )
    what_it_actually_did = observations(
        ("task.read", "*"),
        ("fs.read", "data/notes/private.txt"),
        ("net.outbound", "http://127.0.0.1:9000/collect"),
    )

    findings = engine.evaluate_invocation(
        manifest, what_it_actually_did, invocation_id="inv_1", model="test-model"
    )

    kinds = {finding.axis for finding in findings}
    assert kinds == {"truthfulness"}, f"expected only truthfulness findings, got {kinds}"
    assert {finding.ast_id for finding in findings} == {"AST04"}
    # Specifically: two things it never declared.
    undeclared = [f for f in findings if f.type == "UNDECLARED_CAPABILITY"]
    assert len(undeclared) == 2


def test_a9_an_honest_but_sweeping_skill_produces_only_proportionality_findings(engine):
    """
    ACCEPTANCE TEST A-9, second half.

    This skill is scrupulously honest: it declares everything it does, and does only
    what it declared. But it is a simple reporting skill demanding the ability to
    read any file anywhere and to contact the network.

    It must produce ONLY "too much power" findings and NOT a single "did not tell the
    truth" finding - because it told the truth perfectly. It is simply over-powered.

    This is the case that proves the two questions are genuinely different. No amount
    of comparing promises against behaviour would ever catch this skill.
    """
    manifest = make_manifest(
        category="reporting",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
            {"id": "fs.read", "scope": ["*"], "reason": "honestly declared, still too much"},
            {"id": "net.outbound", "scope": ["*"], "reason": "honestly declared, still too much"},
        ],
    )
    # It does exactly and only what it declared.
    what_it_actually_did = observations(
        ("task.read", "*"),
        ("fs.read", "data/anything.txt"),
        ("net.outbound", "http://127.0.0.1:9000/x"),
    )

    findings = engine.evaluate_invocation(
        manifest, what_it_actually_did, invocation_id="inv_1", model="test-model"
    )

    kinds = {finding.axis for finding in findings}
    assert kinds == {"proportionality"}, f"expected only proportionality findings, got {kinds}"
    assert {finding.ast_id for finding in findings} == {"AST03"}


def test_a9_the_two_kinds_carry_different_evidence(engine):
    """
    The two kinds must be distinguishable by a program, not just by reading English.

    A truthfulness finding carries what the skill DID. A proportionality finding
    carries what the skill ASKED FOR. Different fields, so a scanning tool can tell
    them apart without interpreting wording.
    """
    lying = make_manifest(capabilities=[])
    truthfulness = engine.check_truthfulness(
        lying, observations(("fs.read", "data/x.txt")), invocation_id="inv_1"
    )

    sweeping = make_manifest(
        capabilities=[{"id": "net.outbound", "scope": ["*"], "reason": "honest"}]
    )
    proportionality = engine.check_proportionality(sweeping)

    assert truthfulness[0].observed is not None
    assert truthfulness[0].granted is None

    assert proportionality[0].granted is not None
    assert proportionality[0].observed is None


# --- Truthfulness in detail ------------------------------------------------------


def test_an_honest_skill_produces_nothing(engine):
    """The baseline: doing exactly what you said produces silence."""
    manifest = make_manifest(
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}]
    )

    findings = engine.evaluate_invocation(
        manifest, observations(("task.read", "*")), invocation_id="inv_1"
    )

    assert findings == []


def test_using_an_ability_that_was_never_declared_is_reported(engine):
    manifest = make_manifest(capabilities=[])

    findings = engine.check_truthfulness(
        manifest, observations(("fs.read", "data/secret.txt")), invocation_id="inv_1"
    )

    assert len(findings) == 1
    assert findings[0].type == "UNDECLARED_CAPABILITY"
    assert findings[0].severity == "high"


def test_using_a_declared_ability_outside_its_stated_limits_is_reported(engine):
    """
    Declaring "I read files in the notes folder" and then reading somewhere else is
    a different problem from not declaring at all, and is reported differently.
    """
    manifest = make_manifest(
        category="formatting",
        capabilities=[{"id": "fs.read", "scope": ["data/notes/**"], "reason": "reads notes"}],
    )

    findings = engine.check_truthfulness(
        manifest, observations(("fs.read", "data/somewhere-else.txt")), invocation_id="inv_1"
    )

    violations = [f for f in findings if f.type == "SCOPE_VIOLATION"]
    assert len(violations) == 1
    assert violations[0].ast_id == "AST04"


def test_going_around_the_official_channel_is_its_own_problem(engine):
    """
    A skill that ignores the app and opens a file itself has done something
    deliberate. It is reported separately from simply not declaring the ability.
    """
    manifest = make_manifest(capabilities=[])

    findings = engine.check_truthfulness(
        manifest,
        observations(("fs.read", "data/x.txt", "audit_hook")),
        invocation_id="inv_1",
    )

    kinds = {finding.type for finding in findings}
    # Both apply and both are reported: it went around us, AND it never declared it.
    assert kinds == {"BROKER_BYPASS", "UNDECLARED_CAPABILITY"}


def test_a_refused_attempt_is_judged_the_same_as_a_successful_one(engine):
    """
    Wanting to do something undeclared is the security event. Whether the app
    happened to stop it is a separate matter - and the report must not go quiet just
    because the safety net worked.
    """
    manifest = make_manifest(capabilities=[])
    log = ObservationLog("inv_1")
    attempt = log.record(capability="net.outbound", resource="https://evil.example.com")
    log.mark_refused(attempt, "non_local_host")

    findings = engine.check_truthfulness(manifest, log.entries(), invocation_id="inv_1")

    assert len(findings) == 1
    assert findings[0].type == "UNDECLARED_CAPABILITY"


# --- Proportionality in detail ---------------------------------------------------


def test_asking_for_an_ability_outside_your_category_is_reported(engine):
    """A reporting skill has no business sending things over the network."""
    manifest = make_manifest(
        category="reporting",
        capabilities=[{"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "honest"}],
    )

    findings = engine.check_proportionality(manifest)

    assert len(findings) == 1
    assert findings[0].type == "EXCESSIVE_GRANT"
    assert findings[0].granted["reason"] == "capability_outside_baseline"
    assert findings[0].severity == "medium"


def test_asking_for_wider_reach_than_your_category_allows_is_reported(engine):
    """
    An integration skill may contact the network - but only this computer. Asking to
    contact anywhere is more reach than the category permits.
    """
    manifest = make_manifest(
        category="integration",
        capabilities=[{"id": "net.outbound", "scope": ["*"], "reason": "honest but sweeping"}],
    )

    findings = engine.check_proportionality(manifest)

    assert len(findings) == 1
    assert findings[0].granted["reason"] == "scope_broader_than_baseline"


def test_a_skill_within_its_category_produces_nothing(engine):
    manifest = make_manifest(
        category="reporting",
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}],
    )

    assert engine.check_proportionality(manifest) == []


def test_over_powered_can_be_judged_before_a_skill_ever_runs(engine):
    """
    Too much power is too much power whether or not it has been used yet, so this can
    be answered at the moment a skill is switched on.
    """
    manifest = make_manifest(
        category="reporting",
        capabilities=[{"id": "fs.write", "scope": ["*"], "reason": "honest"}],
    )

    findings = engine.evaluate_install(manifest, model="test-model")

    assert len(findings) == 1
    assert findings[0].trigger == "install"
    # No skill run happened, so there is nothing to point at.
    assert findings[0].invocation_id is None


def test_power_held_but_never_used_is_reported_after_several_runs(engine):
    """
    Power held and never exercised is damage waiting for a bug. We wait for several
    runs first, so a new skill is not accused of not yet needing something.
    """
    manifest = make_manifest(
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "used"},
            {"id": "task.write", "scope": ["*"], "reason": "never used"},
        ]
    )

    too_early = engine.check_unused_grants(manifest, {"task.read"}, invocation_count=2, window=5)
    assert too_early == []

    later = engine.check_unused_grants(manifest, {"task.read"}, invocation_count=5, window=5)
    assert len(later) == 1
    assert later[0].type == "UNUSED_GRANT"
    assert later[0].severity == "low"


# --- The catalogue ---------------------------------------------------------------


def test_severities_are_the_ones_the_design_fixed():
    """These are settled by the design and are not decided per-skill (TDD Q-2)."""
    assert TAXONOMY["UNDECLARED_CAPABILITY"].severity == "high"
    assert TAXONOMY["SCOPE_VIOLATION"].severity == "high"
    assert TAXONOMY["BROKER_BYPASS"].severity == "high"
    assert TAXONOMY["EXCESSIVE_GRANT"].severity == "medium"
    assert TAXONOMY["UNUSED_GRANT"].severity == "low"
    assert TAXONOMY["COVERT_DATA_FLOW"].severity == "critical"


def test_the_combination_problem_is_now_built():
    """
    The AST01 feature switched this on. Its meaning and severity were settled in
    advance, so turning it on was a data edit plus the correlation check.
    """
    assert TAXONOMY["COVERT_DATA_FLOW"].implemented is True
    assert TAXONOMY["COVERT_DATA_FLOW"].axis == "correlation"


def _read_then_send(read_digests, send_digests, *, send_seq_after_read=True):
    """
    Build a two-line notebook: read the tasks, then send some data.

    In: the per-item fingerprints recorded for the read and for the send, and whether
    the send comes after the read.
    Out: the two observations, in order.

    Used to drive the correlation check directly, since the fingerprints live in each
    line's "detail" and the simple observations() helper does not set those.
    """
    log = ObservationLog("inv_corr")
    if send_seq_after_read:
        log.record(capability="task.read", resource="*", detail={"item_digests": read_digests})
        log.record(
            capability="net.outbound",
            resource="http://127.0.0.1/x",
            detail={"item_digests": send_digests},
        )
    else:
        log.record(
            capability="net.outbound",
            resource="http://127.0.0.1/x",
            detail={"item_digests": send_digests},
        )
        log.record(capability="task.read", resource="*", detail={"item_digests": read_digests})
    return log.entries()


def test_a_read_then_send_of_the_same_data_is_now_raised(engine):
    """
    The combination the correlation check exists to catch: the same fingerprints that
    were read appear in a later send.
    """
    manifest = make_manifest(capabilities=[])
    findings = engine.evaluate_invocation(
        manifest,
        _read_then_send(["abc123"], ["abc123"]),
        invocation_id="inv_1",
    )

    covert = [f for f in findings if f.type == "COVERT_DATA_FLOW"]
    assert len(covert) == 1
    assert covert[0].axis == "correlation"
    assert covert[0].severity == "critical"


def test_a_send_of_unrelated_data_is_not_a_covert_flow(engine):
    """Reading tasks and then sending something *else* is not theft of the tasks."""
    manifest = make_manifest(capabilities=[])
    findings = engine.evaluate_invocation(
        manifest,
        _read_then_send(["abc123"], ["nothing-in-common"]),
        invocation_id="inv_1",
    )

    assert all(finding.axis != "correlation" for finding in findings)


def test_every_problem_type_belongs_to_exactly_one_question():
    """Each type answers one question. Overlap would make them impossible to tell apart."""
    for entry in TAXONOMY.values():
        assert entry.axis in {
            "truthfulness",
            "proportionality",
            "correlation",
            # Added with AST05 (TDD 4.9): "where did the behaviour come from?" - the
            # mirror image of correlation, watching instructions arrive rather than
            # data leave.
            "provenance",
        }


# --- Findings carry what they need to be useful ----------------------------------


def test_a_finding_records_which_ai_model_was_in_charge(engine):
    """
    Part of the evidence: "the assistant chose to run this" only means something if
    you know which assistant it was.
    """
    manifest = make_manifest(capabilities=[])

    findings = engine.check_truthfulness(
        manifest,
        observations(("fs.read", "x")),
        invocation_id="inv_1",
        model="llama3.1:8b",
    )

    assert findings[0].model == "llama3.1:8b"


def test_a_finding_explains_itself_in_a_readable_sentence(engine):
    manifest = make_manifest(capabilities=[])

    findings = engine.check_truthfulness(
        manifest, observations(("fs.read", "data/private.txt")), invocation_id="inv_1"
    )

    assert "fs.read" in findings[0].summary
    assert "data/private.txt" in findings[0].summary


def test_a_finding_points_back_at_the_exact_thing_that_caused_it(engine):
    """So a reviewer can go from a finding to the precise moment it happened."""
    # Task reading IS declared here, so only the second thing it did is a problem -
    # which lets us check that the finding points at the right one of the two.
    manifest = make_manifest(
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}]
    )

    findings = engine.check_truthfulness(
        manifest, observations(("task.read", "*"), ("fs.read", "x")), invocation_id="inv_1"
    )

    assert len(findings) == 1
    assert findings[0].evidence["observation_seq"] == 2
