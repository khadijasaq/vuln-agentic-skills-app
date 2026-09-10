"""
The whole thing, end to end: an honest skill is handed the wrong component.

The model is stubbed here so the test is about what happens once the skill is chosen.
Whether a live model chooses it is the separate manual check (A-1).

Everything else is real. A real server, a real registry, a real fetch over the loopback
address, and a real fingerprint taken by the app of exactly what came back. That last part
is why this cannot be a stubbed request: a stubbed request has no reply, and the reply is
the entire subject.

Two ways in are used, deliberately:

  a full turn        - the ordinary path, model included, which is what raises findings and
                       marks the exchange. Used wherever the claim is about detection.
  a direct run       - the same skill, the same brokers, the same registry, but without the
                       model, because the per-task sizes the skill works out are handed to
                       the assistant as a sentence and are not otherwise kept. Used only
                       where the claim is about the EFFECT of the substituted component.

Specification references: AST02 spec sections 6.4, 10.1 and 10.2; acceptance tests A-2,
A-3, A-5, A-8 and A-9; build plan step 7.4.
"""

from __future__ import annotations

import json

from app.chat.orchestrator import ChatOrchestrator
from app.config import get_settings
from app.findings.engine import MIN_INFLUENCE_LENGTH
from app.findings.markers import MARKER_PHRASE
from app.skills.host import get_host
from app.storage import store

# This folder's name has hyphens, so it cannot be a Python package and its tests cannot
# import from its conftest. Fixtures are injected by name instead - the same arrangement
# the sibling weaknesses use. Only the address is repeated here.
LOCAL_BASE_URL = "http://127.0.0.1:8000"
PACK_URL = f"{LOCAL_BASE_URL}/mock/registry/sizing-heuristics/2.3.1"


def run_turn(message: str = "how long will my tasks take?"):
    """Ask the assistant one question, the way the API does."""
    return ChatOrchestrator().run_turn(message)


def run_skill(params: dict | None = None):
    """
    Run the skill without the model, to see the numbers it worked out.

    In: the values the model would have supplied. Out: the InvocationResult.

    Everything the skill does still goes through the real brokers and the real registry -
    only the model's choice is skipped, because what is being examined here is the effect
    of the component rather than the decision to run the skill.
    """
    return get_host().invoke("time_budget", params or {})


def sizes_by_task(result) -> dict:
    """The per-task sizes an invocation worked out, keyed by task."""
    return {item["task_id"]: item for item in result.data["tasks"]}


def fetch_observation(observations) -> dict:
    """The one record of the component being fetched."""
    fetches = [o for o in observations if o["capability"] == "net.outbound"]
    assert len(fetches) == 1, f"expected exactly one network request, got {len(fetches)}"
    return fetches[0]


# --- A-2: the substituted component really is delivered, and really changes the answer


def test_the_wrong_component_is_delivered(live_lab, flagged_task, declared_pin):
    """
    A-2, first half - what arrived is genuinely not what was pinned.

    The app wrote the fingerprint down by itself, at the moment of delivery, before the
    skill had looked at a single byte. The skill cannot influence it, forge it or suppress
    it - it does not even know it exists. That independence is what makes this evidence
    worth anything.
    """
    flagged_task()
    turn = run_turn()

    assert turn.activity.skill_invoked.outcome == "ok"

    fetch = fetch_observation(turn.activity.observations)
    assert fetch["outcome"] == "ok"
    assert fetch["source"] == "broker"
    assert fetch["resource"] == PACK_URL
    assert fetch["detail"]["status"] == 200
    assert f"sha256:{fetch['detail']['response_sha256']}" != declared_pin, (
        "the registry served the pinned component, so there is nothing to demonstrate"
    )


def test_the_substituted_component_buries_the_security_task(
    live_lab, flagged_task, reviewed_build_text, write_component
):
    """
    A-2, second half - the substitution has a visible effect on what the user is told.

    A finding with no consequence would prove the check fires, not that the weakness
    matters. So this runs the same skill twice: once with the component the lab serves, and
    once with the component the skill's author actually reviewed.

    With the substituted one, the task about a security audit is sized as fifteen minutes
    and sinks to the bottom of the list. With the reviewed one it is sized as real work.
    Nothing about the skill changed between the two runs.
    """
    task = flagged_task()

    buried = sizes_by_task(run_skill())[task["id"]]
    assert buried["band"] == "xs", (
        "the substituted component did not bury the security task, so its effect is not "
        "visible even though the substitution itself was detected"
    )

    # Now put the component the author reviewed in place, and ask again.
    write_component(reviewed_build_text)
    honest = sizes_by_task(run_skill())[task["id"]]

    assert honest["band"] != "xs"
    assert honest["minutes"] > buried["minutes"], (
        "the two builds size the security task the same way, so they do not actually "
        "differ in effect"
    )


def test_the_agreed_component_raises_nothing_at_all(
    live_lab, flagged_task, reviewed_build_text, write_component
):
    """
    A-6 - THE TEST THAT ANSWERS THE WHOLE OBJECTION, on the real running skill.

    The sibling unit test proves this on hand-built material. This proves it on the actual
    shipped artefacts: the real registry serves the real reviewed build, the real skill
    fetches it over the real loopback address, and the real fingerprint in the real
    manifest is compared against it.

    Same skill. Same description. Same fetch. **Nothing reported.**

    That also makes this the end-to-end proof that the pinned fingerprint is correct. If
    the pin were wrong - regenerated with the wrong recipe, or left stale after an edit -
    this test fails, and the weakness would otherwise have quietly become permanent rather
    than switchable.
    """
    flagged_task()
    write_component(reviewed_build_text)

    turn = run_turn()

    assert turn.findings_raised == [], (
        f"the agreed component raised {[f.type for f in turn.findings_raised]}; the check "
        f"cannot stay silent, which is the one thing it has to be able to do"
    )
    assert turn.activity.vulnerability_fired is False
    assert turn.activity.skill_invoked.outcome == "ok"

    # And it is silent because the delivery MATCHED, not because nothing was delivered.
    fetch = fetch_observation(turn.activity.observations)
    assert fetch["outcome"] == "ok"
    assert fetch["detail"]["status"] == 200
    assert fetch["detail"]["response_sha256"], "no component was delivered at all"


# --- A-3: exactly one finding, with everything a person needs ------------------------


def test_exactly_one_integrity_finding_with_full_evidence(live_lab, flagged_task, declared_pin):
    """
    A-3 - the headline test.

    The model chooses the skill for its advertised purpose. The skill does that job, and
    while doing it is handed a component that is not the one it said it expected. One
    problem is reported, and it carries everything a person needs to act on it: which
    component, which version, from whom, from where, what was promised, what arrived, and
    the exact moment it did.
    """
    flagged_task()
    turn = run_turn()

    findings = turn.findings_raised
    assert len(findings) == 1, f"expected exactly one finding, got {[f.type for f in findings]}"

    finding = findings[0]
    assert finding.type == "COMPROMISED_DEPENDENCY"
    assert finding.ast_id == "AST02"
    assert finding.ast_name == "Supply Chain Compromise"
    assert finding.axis == "integrity"
    assert finding.severity == "high"
    assert finding.trigger == "invocation"
    assert finding.skill_id == "time_budget"
    assert finding.skill_version == "1.0.0"
    assert finding.model == "stub"

    component = finding.dependency
    assert component["name"] == "sizing-heuristics"
    assert component["version"] == "2.3.1"
    assert component["publisher"] == "Loft Analytics"
    assert component["source"] == PACK_URL or "__SELF_URL__" in component["source"]
    assert component["declared_integrity"] == declared_pin
    assert component["delivered_integrity"] != declared_pin
    assert component["delivered_bytes"] > 0
    assert component["reason"] == "digest_mismatch"

    # The evidence points at the moment the component arrived.
    fetch = fetch_observation(turn.activity.observations)
    assert component["acquired_seq"] == fetch["seq"]
    assert finding.evidence["observation_seq"] == fetch["seq"]

    # It fills only its own evidence slot, so a reader can tell which question it answers
    # without reading the wording.
    assert finding.observed is None
    assert finding.granted is None
    assert finding.correlation is None
    assert finding.provenance is None

    # The turn is marked, and the skill really ran.
    assert turn.activity.vulnerability_fired is True
    assert turn.activity.skill_invoked.skill_id == "time_budget"


def test_the_evidence_marker_shows_what_arrived(live_lab, flagged_task, declared_pin):
    """
    A-3, the evidence half - a person can read the whole story out of a file on disk.

    The app writes the marker, never the skill. It carries the unmissable phrase, and the
    record it carries is the delivery itself - so the fingerprint of what actually arrived
    and a readable slice of it are both there, and a reviewer can see for themselves that
    what turned up is not what was agreed, without the app running.
    """
    flagged_task()
    run_turn()

    files = sorted(get_settings().markers_dir.iterdir())
    assert len(files) == 1, f"expected exactly one evidence file, got {[f.name for f in files]}"

    marker = json.loads(files[0].read_text(encoding="utf-8"))

    assert marker["marker"] == MARKER_PHRASE
    assert marker["finding_type"] == "COMPROMISED_DEPENDENCY"
    assert marker["ast_id"] == "AST02"
    assert marker["severity"] == "high"
    assert marker["skill_id"] == "time_budget"
    assert marker["model"] == "stub"

    observation = marker["observation"]
    assert observation is not None
    assert observation["capability"] == "net.outbound"
    assert observation["resource"] == PACK_URL
    assert observation["detail"]["response_sha256"] != declared_pin.split(":", 1)[1]
    # A person can read what turned up, not merely be told its fingerprint differed.
    assert "sizing-heuristics" in observation["detail"]["response_excerpt"]


# --- A-5: AST02 alone -----------------------------------------------------------------


def test_the_skill_fires_ast02_and_nothing_else(live_lab, flagged_task):
    """
    A-5 - the distinctness proof, on the real running skill.

    The skill is honest, right-sized, steals nothing and obeys nobody. Exactly one kind of
    problem should be reported about it, and it should be the one about the component it
    was handed.
    """
    flagged_task()
    turn = run_turn()

    assert {f.axis for f in turn.findings_raised} == {"integrity"}
    assert {f.ast_id for f in turn.findings_raised} == {"AST02"}

    types = {f.type for f in turn.findings_raised}
    for other in (
        "UNDECLARED_CAPABILITY",
        "SCOPE_VIOLATION",
        "BROKER_BYPASS",
        "EXCESSIVE_GRANT",
        "UNUSED_GRANT",
        "COVERT_DATA_FLOW",
        "EXTERNAL_INSTRUCTION_FLOW",
        "AGENT_INSTRUCTION_RELAY",
    ):
        assert other not in types, f"{other} fired; this demonstration is no longer AST02 alone"


def test_installing_it_raises_nothing_at_all(live_lab):
    """
    Nothing is wrong at install time, because nothing has been delivered yet.

    Worth stating beside the over-privilege demonstration, which is fully visible at
    install and needs no behaviour at all. These are opposite ends of the same set of
    questions - and this skill sits at both ends at once, because the half of the check
    that IS answerable from the description alone finds nothing to complain about either:
    the component is pinned.
    """
    import httpx

    store.reset_lab()
    with httpx.Client(timeout=10.0) as client:
        response = client.post(f"{LOCAL_BASE_URL}/api/skills/time_budget/install")

    assert response.status_code == 200
    assert response.json()["findings_raised"] == []


# --- A-8 and A-9: the silences that keep this distinct --------------------------------


def test_nothing_from_the_component_reaches_the_assistant(live_lab, flagged_task):
    """
    A-8 - the skill does not repeat a single line of the component back to the assistant.

    This matters because repeating fetched text into what the assistant is told is a
    DIFFERENT weakness with its own name. If the skill's sentence quoted the component's
    name, its publisher or one of its rule names, that other problem would fire too and
    this would stop being a clean demonstration of one thing.

    It is asserted rather than assumed because it could regress under an innocent-looking
    improvement to the wording.
    """
    flagged_task()
    _, stub = live_lab

    turn = run_turn()

    fetch = fetch_observation(turn.activity.observations)
    delivered_strings = fetch["detail"]["response_strings"]

    assert stub.tool_messages, "the app never handed the skill's sentence to the model"
    summary = stub.tool_messages[0]

    long_enough = [text for text in delivered_strings if len(text) >= MIN_INFLUENCE_LENGTH]
    assert long_enough, "the component carries no text long enough to count, so this proves nothing"

    for text in long_enough:
        assert text not in summary, (
            f"the skill repeated {text!r} from the fetched component into what it told the "
            f"assistant, which would raise a second, different problem"
        )

    assert "AGENT_INSTRUCTION_RELAY" not in {f.type for f in turn.findings_raised}


def test_the_fetch_is_the_last_thing_that_happens(live_lab, flagged_task):
    """
    A-9 - nothing happens after the component arrives, so nothing can have been steered by
    it.

    The check about being told what to do at run time looks for an action that came AFTER a
    fetch and used something out of it. Here the fetch is the final entry, so that check
    has an empty list to look through. The silence is structural: it cannot be broken by
    changing what the component says.
    """
    flagged_task()
    turn = run_turn()

    observations = turn.activity.observations
    last = max(observations, key=lambda o: o["seq"])

    assert last["capability"] == "net.outbound"
    assert last["resource"] == PACK_URL
    assert "EXTERNAL_INSTRUCTION_FLOW" not in {f.type for f in turn.findings_raised}

    # And the read really did come first, which is the order the skill declares.
    first = min(observations, key=lambda o: o["seq"])
    assert first["capability"] == "task.read"


def test_nothing_is_sent_anywhere_so_nothing_can_be_stolen(live_lab, flagged_task):
    """
    A-9, the other half - the only request is a fetch, carrying nothing.

    The theft check compares fingerprints of the user's tasks against fingerprints of what
    was sent out. This skill sends nothing out, so there are no fingerprints to compare and
    the check's loop never runs. Structural silence again, and it cannot be broken by
    changing what the skill reads.
    """
    flagged_task()
    turn = run_turn()

    fetch = fetch_observation(turn.activity.observations)

    assert fetch["detail"]["method"] == "GET"
    assert "item_digests" not in fetch["detail"], (
        "the request carried a payload; this skill must never send anything"
    )
    assert "sha256" not in fetch["detail"], "the request carried a payload fingerprint"
    assert "COVERT_DATA_FLOW" not in {f.type for f in turn.findings_raised}
