"""
What a scanning program sees, what happens when two problems land at once, and whether
the whole thing can be run again from clean.

Four things are proved here:

  A-12  Two problems at once, reported as two. A description that names its component at a
        slightly different address gets BOTH a "that is not the component you pinned" and a
        "you went somewhere you said you would not". Overlap is expressed, never collapsed.
  A-16  What a scanning program sees through the JSON API.
  A-17  That it fires every time, whatever the model happens to pass.
  A-18  That the lab can be reset and the demonstration repeated - and that the published
        components survive that reset, because they are lab setup rather than something
        the app observed.

Specification references: AST02 spec sections 10.6 and 11; acceptance tests A-12, A-16,
A-17 and A-18; build plan step 7.5.
"""

from __future__ import annotations

import httpx

from app.chat.orchestrator import ChatOrchestrator, _build_engine
from app.config import get_settings
from app.findings.markers import count_markers
from app.monitor.observations import ObservationLog
from app.skills import registry as registry_module
from app.skills.context import SkillContext
from app.storage import store

LOCAL_BASE_URL = "http://127.0.0.1:8000"
PACK_URL = f"{LOCAL_BASE_URL}/mock/registry/sizing-heuristics/2.3.1"
# The same component, at the same place, named the way a person often writes it. The app
# allows both, because both mean "this machine" - but they are not the same TEXT.
PACK_URL_VIA_LOCALHOST = "http://localhost:8000/mock/registry/sizing-heuristics/2.3.1"


def run_turn(message: str = "how long will my tasks take?"):
    """Ask the assistant one question, the way the API does."""
    return ChatOrchestrator().run_turn(message)


# --- A-12: two problems at once, reported as two ------------------------------------


def test_a_component_fetched_from_outside_the_declared_scope_raises_both(live_lab, flagged_task):
    """
    A-12 - the co-occurrence case, and a genuinely instructive demo beat.

    A fabricated description says its component comes from "localhost" while promising to
    talk only to "127.0.0.1". Both names mean this machine, so the app allows the request
    and the component really is delivered - but the two are not the same piece of text, and
    the skill said one of them.

    So the same single fetch is two different problems at once:

      the component that arrived is not the one that was pinned   (a supply-chain problem)
      the skill went somewhere it said it would not               (a truthfulness problem)

    They are reported as two distinct findings, on two distinct axes, with two distinct
    pieces of evidence. That is the rule: overlap is expressed, not collapsed.

    A fabricated description is used rather than a second shipped skill, following the
    convention every sibling weakness uses for its variant cases.
    """
    flagged_task()

    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()
    shipped = registry.get("time_budget").manifest

    # The same skill, described as fetching from "localhost" instead.
    fabricated = shipped.model_copy(deep=True)
    fabricated.dependencies[0].source = PACK_URL_VIA_LOCALHOST

    # A real fetch, through the real broker, to the real registry - by the other name.
    log = ObservationLog("inv_localhost")
    context = SkillContext("inv_localhost", log)
    context.tasks.list("open")
    response = context.net.get(PACK_URL_VIA_LOCALHOST)

    assert response.status_code == 200, "the app refused a loopback address it should allow"

    observations = log.entries()
    fetch = [o for o in observations if o.capability == "net.outbound"][0]
    assert fetch.outcome == "ok", "the fetch was refused, so there was no delivery to judge"

    findings = _build_engine().evaluate_invocation(
        fabricated, observations, invocation_id="inv_localhost", model="stub"
    )

    by_type = {finding.type: finding for finding in findings}
    assert "COMPROMISED_DEPENDENCY" in by_type, "the substituted component was not reported"
    assert "SCOPE_VIOLATION" in by_type, "going outside the declared scope was not reported"

    supply_chain = by_type["COMPROMISED_DEPENDENCY"]
    truthfulness = by_type["SCOPE_VIOLATION"]

    # Two axes, two risk ids, two different pieces of evidence.
    assert supply_chain.axis == "integrity"
    assert supply_chain.ast_id == "AST02"
    assert supply_chain.dependency is not None
    assert supply_chain.observed is None

    assert truthfulness.axis == "truthfulness"
    assert truthfulness.ast_id == "AST04"
    assert truthfulness.observed is not None
    assert truthfulness.dependency is None


# --- A-16: what a scanning program sees ---------------------------------------------


def test_the_api_reports_the_finding_in_the_promised_shape(live_lab, flagged_task):
    """
    A-16 - a scanner can attribute the problem to the exact message that caused it.

    The turn's own answer names the finding, so there is no need to compare the whole list
    before and after. And the stored finding carries the supply-chain evidence and nothing
    from the other four questions, so a consumer can tell which question it answers without
    reading any prose.
    """
    flagged_task()

    with httpx.Client(timeout=15.0) as client:
        chat = client.post(
            f"{LOCAL_BASE_URL}/api/chat", json={"message": "how long will my tasks take?"}
        )
        assert chat.status_code == 200
        body = chat.json()

        assert body["schema_version"] == 1
        assert body["skill_invoked"]["skill_id"] == "time_budget"
        assert body["skill_invoked"]["outcome"] == "ok"

        raised = body["findings_raised"]
        assert len(raised) == 1
        assert raised[0]["type"] == "COMPROMISED_DEPENDENCY"
        assert raised[0]["ast_id"] == "AST02"

        # The same finding, through the query a blue-team agent would use.
        listed = client.get(f"{LOCAL_BASE_URL}/api/findings", params={"ast_id": "AST02"})
        assert listed.status_code == 200
        payload = listed.json()

        assert payload["schema_version"] == 1
        assert payload["count"] == 1

        finding = payload["findings"][0]
        assert finding["axis"] == "integrity"
        assert finding["severity"] == "high"
        assert finding["ast_name"] == "Supply Chain Compromise"
        assert finding["dependency"]["name"] == "sizing-heuristics"
        assert finding["dependency"]["reason"] == "digest_mismatch"
        # One evidence field per question, and only this one is filled.
        assert finding["observed"] is None
        assert finding["granted"] is None
        assert finding["correlation"] is None
        assert finding["provenance"] is None

        # The exchange that caused it is marked, so the story can be followed both ways.
        activity = client.get(f"{LOCAL_BASE_URL}/api/activity").json()
        latest = activity["activity"][-1]
        assert latest["vulnerability_fired"] is True
        assert latest["skill_invoked"]["skill_id"] == "time_budget"


def test_every_other_risk_id_returns_nothing(live_lab, flagged_task):
    """
    A-16, the negative half - the scanner sees this as AST02 and nothing else.
    """
    flagged_task()
    run_turn()

    with httpx.Client(timeout=15.0) as client:
        for ast_id in ["AST01", "AST03", "AST04", "AST05"]:
            payload = client.get(
                f"{LOCAL_BASE_URL}/api/findings", params={"ast_id": ast_id}
            ).json()
            assert payload["count"] == 0, f"{ast_id} findings appeared for this skill"


# --- A-17: it fires every time ------------------------------------------------------


def test_it_fires_every_time_whatever_the_model_passes(live_lab, flagged_task):
    """
    A-17 - repeatable, not incidental.

    The component and its fingerprint are properties of the description, and the address is
    fixed in the code, so nothing about this depends on what the model happened to say. Five
    runs with different arguments, and the same problem every time.

    The count rises rather than the list growing, because it is the same problem seen again
    - which is the deduplication rule working as designed.
    """
    flagged_task()
    _, stub = live_lab

    counts = []
    for index, scope in enumerate([None, "open", "all", "open", "all"]):
        stub.params = {} if scope is None else {"scope": scope}
        turn = run_turn(f"how much work is left? ({index})")

        assert len(turn.findings_raised) == 1, (
            f"run {index} with scope={scope!r} raised {len(turn.findings_raised)} findings"
        )
        assert turn.findings_raised[0].type == "COMPROMISED_DEPENDENCY"
        counts.append(turn.findings_raised[0].occurrences)

    assert counts == sorted(counts), f"the count went backwards: {counts}"
    assert counts[-1] > counts[0], "repeat sightings were not counted"

    # One problem, seen five times - not five problems.
    stored = [f for f in store.load_findings() if f.ast_id == "AST02"]
    assert len(stored) == 1


# --- A-18: starting over -------------------------------------------------------------


def test_reset_clears_what_was_observed_and_keeps_the_published_components(
    live_lab, flagged_task
):
    """
    A-18 - the lab returns to clean, and the demonstration can be run again.

    What a reset clears is what the app OBSERVED: findings, evidence files, the exchange
    log. What it keeps is the lab's own setup - and the published components are setup, in
    exactly the same way the team hub's document is. Wiping them would mean the registry had
    nothing to serve afterwards and the demonstration could not be repeated at all.
    """
    flagged_task()
    run_turn()

    assert store.load_findings(), "nothing was found, so there is nothing to clear"
    assert count_markers() > 0

    component_path = get_settings().registry_dir / "sizing-heuristics-2.3.1.json"
    served_before = component_path.read_bytes()

    with httpx.Client(timeout=15.0) as client:
        response = client.post(f"{LOCAL_BASE_URL}/api/reset")
        assert response.status_code == 200

    assert store.load_findings() == []
    assert count_markers() == 0

    assert component_path.exists(), "the reset wiped the published component"
    assert component_path.read_bytes() == served_before


def test_the_demonstration_reproduces_from_clean(live_lab, flagged_task):
    """
    A-18, the second half - after a reset, the same question raises the same problem.
    """
    flagged_task()
    run_turn()

    with httpx.Client(timeout=15.0) as client:
        client.post(f"{LOCAL_BASE_URL}/api/reset")

    # The reset re-seeds the task list, so the flagged task has to be put back too - it was
    # something the user added, not something the lab ships.
    flagged_task()
    again = run_turn()

    assert len(again.findings_raised) == 1
    assert again.findings_raised[0].type == "COMPROMISED_DEPENDENCY"
    assert again.findings_raised[0].occurrences == 1 or again.findings_raised[0].occurrences == 2
    assert count_markers() == 1


# --- The disclosed foundation defect this feature ran into (KI-2) -------------------


def test_the_marker_pointer_is_empty_for_this_weakness_too(live_lab, flagged_task):
    """
    KI-2, pinned so it cannot silently close or silently widen.

    Every finding is meant to carry the path of its own evidence file. None does, for any
    weakness, because of a two-step save in the shared persistence code. The evidence files
    themselves are written correctly - which is what the safety promise actually requires -
    so this is a missing pointer rather than missing evidence.

    It is disclosed in docs/KNOWN-ISSUES.md and deliberately not fixed here: bundling a
    shared persistence change into the feature that had to argue for touching the platform
    would blur the one change that needed arguing.

    WHEN KI-2 IS FIXED: this test should be updated to assert the opposite - a non-null
    marker path and occurrences of 1 on a first sighting - not deleted.
    """
    flagged_task()
    run_turn()

    stored = [f for f in store.load_findings() if f.ast_id == "AST02"]
    assert len(stored) == 1

    assert stored[0].evidence.get("marker") is None, (
        "the marker pointer is now populated - KI-2 appears to be fixed. Update this test "
        "to assert the fixed behaviour rather than deleting it."
    )
    # The evidence file itself is written correctly, which is what FR-7.1 requires.
    assert count_markers() == 1
