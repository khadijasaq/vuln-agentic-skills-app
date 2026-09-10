"""
Proves the Focus Picker skill fires the "too much power" axis ALONE, and that the finding
tracks what the skill was GRANTED - not what it did, and not any gap between its word and
its deed - on hand-built fixtures, before the skill is wired end to end.

These are the load-bearing proofs of this weakness:

  - A-5: the real, shipped description, together with a run in which the skill genuinely
    reaches beyond its job, produces ONLY "too much power" findings. No "did not tell the
    truth" (AST04), because it declared everything it did. No "quiet theft" (AST01),
    because it never sends anything at all. This is the proof the axis stands on its own.

  - A-6: the two weaknesses have OPPOSITE cures, and this is where that becomes a fact
    rather than a claim. Over exactly the same behaviour: declare MORE and the
    over-powered findings multiply; declare LESS and they vanish, replaced by a "did not
    tell the truth" finding. Adding declarations is how you fix a liar. It is the last
    thing you would do to an over-powered skill.

A-8 covers the second way a skill can be over-powered - asking for a permitted ability
but with a wider reach than its kind of skill should have. A-10 shows the thing that most
sharply separates this axis from the other two: what the skill DID is not an input at all,
so the findings are identical whether the skill reached beyond its remit, was blocked
trying, or did nothing whatsoever.

The descriptions and notebooks below are fabricated test material fed straight to the
engine, except where the REAL shipped description is used on purpose; nothing here runs
the real skill (that is proved in test_focus_picker_e2e.py).

Covers: feature spec sections 5 and 6; TDD sections 4.1 and 4.5; invariant I-7;
acceptance tests A-5, A-6, A-8, A-10.
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

HISTORY_FILE = "data/activity.json"

# What Focus Picker's job actually needs. Everything else it holds is the weakness.
NEEDED = "task.read"


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    """An engine loaded with the app's real capability list and yardstick policy."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


@pytest.fixture
def shipped_manifest(tmp_settings):
    """
    The REAL Focus Picker description, read from disk exactly as the app would load it.

    Using the shipped description (not a stand-in) is what makes A-5 a proof about this
    skill rather than about an invented one.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()
    registry = registry_module.get_registry()
    registry.discover_default()
    return registry.get("focus_picker").manifest


def did(*lines) -> list:
    """
    Build the ordered notebook of what a skill did.

    In: (capability, resource[, outcome[, source]]) tuples. Out: the observations.
    """
    log = ObservationLog("inv_ast03")
    for line in lines:
        capability, resource = line[0], line[1]
        outcome = line[2] if len(line) > 2 else "ok"
        source = line[3] if len(line) > 3 else "broker"
        log.record(capability=capability, resource=resource, outcome=outcome, source=source)
    return log.entries()


def a_normal_run() -> list:
    """What Focus Picker does on an ordinary run: reads the tasks, then over-reaches."""
    return did(("task.read", "*"), ("fs.read", HISTORY_FILE))


def granted_capabilities(findings) -> set:
    """The capabilities named by a set of "too much power" findings."""
    return {finding.granted["capability"] for finding in findings if finding.granted}


# --- A-5: the shipped skill fires AST03 alone ------------------------------------


def test_a5_focus_picker_fires_ast03_alone(engine, shipped_manifest):
    """
    ACCEPTANCE TEST A-5.

    The shipped description asks for four abilities where the job needs one, and the
    skill really does use one of the extra three. The result must be ONLY the "too much
    power" axis - three findings, one per ability outside what a reporting skill should
    have - and NOT a truthfulness (AST04) or correlation (AST01) finding.

    Why each of the other two stays silent is worth stating, because it is the whole
    point of keeping three separate questions:

      - truthfulness has nothing to say, because the skill declared every single thing it
        did, and the file it read is inside the limits it declared;
      - correlation has nothing to say STRUCTURALLY, not by luck: it looks for data being
        read and then sent out, and this skill makes no outbound call whatsoever, so
        there is nothing for it to pair a read with.

    This is the case the whole project's central claim rests on: a skill can be entirely
    honest, steal nothing, and still be a security finding.
    """
    findings = engine.evaluate_invocation(
        shipped_manifest,
        a_normal_run(),
        invocation_id="inv_1",
        model="test-model",
    )

    assert {f.axis for f in findings} == {"proportionality"}
    assert {f.ast_id for f in findings} == {"AST03"}

    excessive = [f for f in findings if f.type == "EXCESSIVE_GRANT"]
    assert len(excessive) == 3
    assert granted_capabilities(excessive) == {"fs.read", "task.write", "net.outbound"}
    assert all(f.severity == "medium" for f in excessive)
    assert all(f.granted["reason"] == "capability_outside_baseline" for f in excessive)

    # The finding carries the yardstick it was measured against, so a reader can see
    # "asked for this, was allowed only that" without opening the policy file.
    assert all(f.granted["allowed"] == [NEEDED] for f in excessive)

    # A program can tell the three kinds of finding apart by WHICH evidence field is
    # filled, without reading any English. This kind fills "granted" and nothing else.
    assert all(f.observed is None for f in excessive)
    assert all(f.correlation is None for f in excessive)
    assert all(f.evidence["observation_seq"] is None for f in excessive)

    # Explicitly: neither of the other two axes speaks.
    assert [f for f in findings if f.axis == "truthfulness"] == []
    assert [f for f in findings if f.axis == "correlation"] == []


def test_a5_the_one_ability_the_job_needs_is_never_reported(engine, shipped_manifest):
    """
    The honest, necessary ability must stay silent, or the finding would just be noise.

    Reading tasks is exactly what a reporting skill is for, and the yardstick puts no
    limit on how much of the list it may read - so the ability the job genuinely needs
    produces nothing, and all three findings are attributable to the excess alone.
    """
    findings = engine.check_proportionality(shipped_manifest)

    assert NEEDED not in granted_capabilities(findings)


# --- A-6: the two weaknesses have opposite cures ---------------------------------


def test_a6_declaring_more_makes_it_worse_and_declaring_less_makes_it_a_lie(engine):
    """
    ACCEPTANCE TEST A-6 and invariant I-7.

    The same behaviour, described two different ways, to show the two weaknesses pull in
    opposite directions:

      DECLARE MORE - add a fifth ability to the description and the over-powered findings
      go UP, from three to four. The skill did not change. Only the size of what it was
      handed did.

      DECLARE LESS - cut the description back to the one ability the job needs, and the
      over-powered findings vanish entirely - replaced by a "did not tell the truth"
      finding, because now the skill is reading a file it never admitted to.

    So the cure for a lying skill (say more) is the disease for an over-powered one. If
    the two ever collapsed into a single "mismatch" finding, this contradiction would be
    invisible, and two of this project's three weaknesses would look like one.
    """
    behaviour = a_normal_run()

    shipped_four = [
        {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
        {"id": "fs.read", "scope": ["data/**"], "reason": "reads the history"},
        {"id": "task.write", "scope": ["*"], "reason": "held, not used"},
        {"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "held, not used"},
    ]

    # --- declare MORE ---
    declares_more = make_manifest(
        skill_id="focus_picker_wider",
        category="reporting",
        capabilities=shipped_four
        + [{"id": "fs.write", "scope": ["data/**"], "reason": "honestly declared too"}],
    )
    wider = engine.evaluate_invocation(
        declares_more, behaviour, invocation_id="inv_1", model="test-model"
    )
    wider_excessive = [f for f in wider if f.type == "EXCESSIVE_GRANT"]

    assert len(wider_excessive) == 4
    assert granted_capabilities(wider_excessive) == {
        "fs.read",
        "task.write",
        "net.outbound",
        "fs.write",
    }

    # --- declare LESS ---
    declares_less = make_manifest(
        skill_id="focus_picker_modest",
        category="reporting",
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}],
    )
    modest = engine.evaluate_invocation(
        declares_less, behaviour, invocation_id="inv_1", model="test-model"
    )

    assert [f for f in modest if f.type == "EXCESSIVE_GRANT"] == []
    undeclared = [f for f in modest if f.type == "UNDECLARED_CAPABILITY"]
    assert len(undeclared) == 1
    assert undeclared[0].observed["capability"] == "fs.read"
    assert undeclared[0].ast_id == "AST04"

    # Said plainly, as one comparison: more description, more over-powered findings;
    # less description, none of them and a lie instead.
    assert len(wider_excessive) > 3 > len(
        [f for f in modest if f.type == "EXCESSIVE_GRANT"]
    )


# --- A-8: the other way of holding too much --------------------------------------


def test_a8_a_permitted_ability_with_too_wide_a_reach_is_also_too_much(engine):
    """
    ACCEPTANCE TEST A-8.

    There are two ways to hold too much power, and the shipped skill only shows one of
    them (asking for abilities its kind of skill should not have at all). This covers the
    other: asking for an ability the category DOES permit, but with a wider reach than it
    should have.

    The example is deliberately pointed. A skill that joins things up ("integration") may
    contact the network - but only this computer. Asking to contact anywhere is the same
    ability with the fence taken down. Note that the very same two abilities are
    perfectly proportionate for that kind of skill and excessive for a reporting one:
    proportion is never a property of an ability by itself, only of an ability measured
    against a job.
    """
    too_wide = make_manifest(
        skill_id="hub_sync",
        category="integration",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
            {"id": "net.outbound", "scope": ["*"], "reason": "honestly declared, too wide"},
        ],
    )

    findings = engine.check_proportionality(too_wide)

    assert len(findings) == 1
    assert findings[0].type == "EXCESSIVE_GRANT"
    assert findings[0].granted["reason"] == "scope_broader_than_baseline"
    assert findings[0].granted["limit"] == ["127.0.0.1"]
    assert findings[0].severity == "medium"

    # And with the fence in place, the same two abilities produce nothing at all.
    proportionate = make_manifest(
        skill_id="hub_sync_fenced",
        category="integration",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
            {"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "this machine only"},
        ],
    )
    assert engine.check_proportionality(proportionate) == []


# --- A-10: what the skill did is not an input ------------------------------------


def test_a10_the_findings_do_not_depend_on_what_the_skill_did(engine, shipped_manifest):
    """
    ACCEPTANCE TEST A-10.

    This is the sharpest line between this axis and the other two. Truthfulness needs to
    know what the skill did, because it compares deed against word. This question does
    not: too much power is too much power whether it has been used, blocked, or left
    untouched.

    So the same description is judged against three completely different runs - a normal
    one, one where the file read was blocked, and one where the skill did nothing at all -
    and must give the identical answer every time. It also means the answer exists before
    the skill has ever run, which is why installing it is enough to raise the findings.
    """

    def fingerprint(observations):
        """The meaningful content of the findings, ignoring ids and timestamps."""
        findings = engine.evaluate_invocation(
            shipped_manifest, observations, invocation_id="inv_1", model="test-model"
        )
        return sorted(
            (f.type, f.severity, f.granted["capability"], f.granted["reason"])
            for f in findings
        )

    normal_run = fingerprint(a_normal_run())
    blocked_run = fingerprint(
        did(("task.read", "*"), ("fs.read", HISTORY_FILE, "error"))
    )
    did_nothing = fingerprint([])

    assert normal_run == blocked_run == did_nothing
    assert len(normal_run) == 3


def test_a10_the_answer_exists_before_the_skill_has_ever_run(engine, shipped_manifest):
    """
    The moment of installation is enough. Because the question is only ever "how much was
    this skill handed?", it can be answered from the description alone - so the findings
    stand against the skill from the moment it is switched on, before the AI model has had
    any chance to choose it.
    """
    findings = engine.evaluate_install(shipped_manifest, model="test-model")

    assert len(findings) == 3
    assert all(f.trigger == "install" for f in findings)
    assert all(f.invocation_id is None for f in findings)
    assert granted_capabilities(findings) == {"fs.read", "task.write", "net.outbound"}
