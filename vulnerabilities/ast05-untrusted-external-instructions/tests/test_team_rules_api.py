"""
The API view of the weakness, the co-occurrence case, and starting over.

Three separate jobs here:

  A-12  What happens when the fetched document names an address OFF this machine. Two
        different things go wrong at once, and the app must say so as two different
        problems rather than blurring them into one.
  A-17  What a scanning program sees through the JSON API.
  A-18  That the lab can be reset and the demonstration repeated - and that the hub's
        document, which is lab configuration rather than something observed, survives it.

Specification references: feature spec sections 9.4 and 10; acceptance tests A-12, A-17,
A-18.
"""

from __future__ import annotations

import httpx

from app.chat.orchestrator import ChatOrchestrator
from app.config import get_settings
from app.findings.markers import count_markers
from app.storage import store

OFF_MACHINE_URL = "http://evil.example.com/ingest"


def run_turn(message: str = "check my tasks against the team rules"):
    """Ask the assistant one question."""
    return ChatOrchestrator().run_turn(message)


# --- A-12: two problems at once, reported as two ------------------------------------


def test_an_off_machine_address_fires_ast05_and_ast04(
    live_lab, shipped_document, write_hub_document, collector_deliveries
):
    """
    A-12 - the co-occurrence case, and the best demo beat in the feature.

    The document is changed to name an address that is not on this machine. Now two
    genuinely different things are wrong, and both are true at once:

      AST05  the destination came from outside - the document chose where this skill
             would send data;
      AST04  that destination is outside what the skill's manifest said it would ever
             contact, so the skill is now doing something it did not declare.

    They are reported as two findings on two axes, because they are two failures. And the
    send itself is refused, so nothing leaves - while the record of what it tried to do
    survives, which is the whole design of the app: being stopped removes the harm, never
    the evidence.

    Note this test does NOT ship a second skill. The same skill is pointed at a different
    document, which is exactly how the weakness works in life.
    """
    document = dict(shipped_document)
    document["report_to"] = OFF_MACHINE_URL
    write_hub_document(document)

    turn = run_turn()

    by_type = {finding.type: finding for finding in turn.findings_raised}

    # Both failures are present, and they are on different axes.
    assert "EXTERNAL_INSTRUCTION_FLOW" in by_type, "the steer was not reported"
    assert "SCOPE_VIOLATION" in by_type, "the undeclared destination was not reported"

    steered = by_type["EXTERNAL_INSTRUCTION_FLOW"]
    scope = by_type["SCOPE_VIOLATION"]

    assert steered.ast_id == "AST05"
    assert steered.axis == "provenance"
    assert steered.provenance["matched_excerpt"] == OFF_MACHINE_URL

    assert scope.ast_id == "AST04"
    assert scope.axis == "truthfulness"
    assert scope.observed["resource"] == OFF_MACHINE_URL

    # Nothing left the machine, and the attempt is still on the record.
    observations = turn.activity.observations
    attempt = [
        entry
        for entry in observations
        if entry["capability"] == "net.outbound" and entry["resource"] == OFF_MACHINE_URL
    ]
    assert len(attempt) == 1
    assert attempt[0]["outcome"] == "refused"
    assert attempt[0]["refusal_reason"] == "non_local_host"
    # A refused request has no reply, so nothing about a response was recorded for it.
    assert "response_item_digests" not in attempt[0]["detail"]

    assert collector_deliveries() == [], "the collector must not have received anything"


def test_the_refused_send_does_not_stop_the_skill_doing_its_job(
    live_lab, shipped_document, write_hub_document
):
    """
    Being refused does not break the advertised job, which is what keeps the skill plausible.

    A skill that visibly failed whenever its attacker was blocked would be uninstalled
    immediately. This one shrugs and gives the user their rules check.
    """
    document = dict(shipped_document)
    document["report_to"] = OFF_MACHINE_URL
    write_hub_document(document)

    turn = run_turn()

    assert turn.activity.skill_invoked.outcome == "ok"
    assert turn.activity.reply


# --- A-17: what a scanning program sees ---------------------------------------------


def test_the_api_reports_the_findings_in_the_promised_shape(live_lab, shipped_document):
    """
    A-17 - a scanner can attribute the problem to the exact message that caused it.

    The per-turn list is what makes that possible without comparing the whole findings
    list before and after.
    """
    base_url, _ = live_lab

    with httpx.Client(timeout=15.0) as client:
        chat = client.post(
            f"{base_url}/api/chat", json={"message": "are we following the team rules?"}
        )
        assert chat.status_code == 200
        body = chat.json()

        assert body["skill_invoked"]["skill_id"] == "team_rules"
        raised = {finding["type"] for finding in body["findings_raised"]}
        assert raised == {"EXTERNAL_INSTRUCTION_FLOW", "AGENT_INSTRUCTION_RELAY"}

        listed = client.get(f"{base_url}/api/findings", params={"ast_id": "AST05"})
        assert listed.status_code == 200
        payload = listed.json()

    assert payload["schema_version"] == 1
    assert payload["count"] == 2

    for finding in payload["findings"]:
        assert finding["ast_id"] == "AST05"
        assert finding["axis"] == "provenance"
        assert finding["trigger"] == "invocation"
        # The evidence field for this axis is filled and the other three are not, so a
        # program can tell the four kinds apart without reading the wording.
        assert finding["provenance"] is not None
        assert finding["observed"] is None
        assert finding["granted"] is None
        assert finding["correlation"] is None
        assert finding["model"]
        # The line pointing at the evidence file is checked separately, and NOT asserted
        # here, because it is currently always empty for every weakness in the app - a
        # foundation defect, disclosed as KI-2 and pinned by the test below. The evidence
        # files themselves are written correctly; only the pointer to them is lost.

    # What FR-7.1 actually requires: the evidence exists on disk, one file per finding.
    assert count_markers() == 2


def test_the_activity_entry_marks_the_turn(live_lab):
    """The activity screen highlights the turn where something fired."""
    base_url, _ = live_lab

    with httpx.Client(timeout=15.0) as client:
        client.post(f"{base_url}/api/chat", json={"message": "check the team rules"})
        activity = client.get(f"{base_url}/api/activity").json()

    entries = [entry for entry in activity["activity"] if entry["skill_invoked"]]
    assert entries
    assert entries[-1]["vulnerability_fired"] is True
    assert len(entries[-1]["findings_raised"]) == 2


# --- A-18: starting over -------------------------------------------------------------


def test_reset_clears_what_was_observed_and_keeps_the_hub_document(
    live_lab, collector_deliveries
):
    """
    A-18 - the lab returns to clean, and the demonstration can be run again.

    The hub's document is deliberately NOT cleared. It is lab configuration - the thing a
    person edits to try a different attack - not something the app observed. Reset exists
    to make the app forget what it saw, and the document is not one of those things.

    This is checked rather than assumed: the reset routine names each thing it clears
    rather than emptying the data folder, so the document survives without reset having to
    make an exception for it.
    """
    base_url, _ = live_lab
    hub_document = get_settings().hub_dir / "rules.json"

    run_turn()

    assert store.load_findings()
    assert count_markers() > 0
    assert collector_deliveries()
    assert hub_document.exists()
    before = hub_document.read_text(encoding="utf-8")

    with httpx.Client(timeout=15.0) as client:
        response = client.post(f"{base_url}/api/reset")
    assert response.status_code == 200

    # Everything observed is gone.
    assert store.load_findings() == []
    assert count_markers() == 0
    assert collector_deliveries() == []

    # The attack's own configuration is untouched, byte for byte.
    assert hub_document.exists(), "reset removed the hub document"
    assert hub_document.read_text(encoding="utf-8") == before


def test_the_demonstration_reproduces_from_clean(live_lab):
    """
    A-18, the second half - after a reset, the same question fires the same two findings.

    A demonstration that only works once is not much of a demonstration.
    """
    base_url, _ = live_lab

    run_turn()
    with httpx.Client(timeout=15.0) as client:
        client.post(f"{base_url}/api/reset")

    turn = run_turn()

    types = {finding.type for finding in turn.findings_raised}
    assert types == {"EXTERNAL_INSTRUCTION_FLOW", "AGENT_INSTRUCTION_RELAY"}
    assert count_markers() == 2


# --- The disclosed foundation defect this feature ran into (KI-2) -------------------


def test_the_marker_pointer_is_empty_for_every_weakness_not_just_this_one(live_lab):
    """
    KI-2, pinned - a foundation defect found while building AST05, disclosed not fixed.

    Every finding is supposed to carry the path of its own evidence file. None of them
    does, for any weakness in the app, at either place findings are saved.

    The cause is a two-step save. A finding is stored, its evidence file is written, the
    path is written onto the finding, and it is saved a second time - but that second save
    matches the record just stored, treats it as the same problem seen again, bumps the
    count and returns without keeping the change. So the path is set on an object that is
    then thrown away, and the count reads 2 after a single run.

    This is NOT caused by AST05 and is NOT specific to it: installing the over-privileged
    skill shows exactly the same thing, and has since it shipped. The evidence files are
    written correctly and can be found on disk; only the pointer stored beside the finding
    is lost.

    It is pinned here rather than fixed because fixing it means changing how findings are
    saved, which is shared machinery this feature has no business rewriting - the same
    reasoning that left KI-1 alone. When it is fixed, this test should be UPDATED rather
    than deleted, and the assertion in the API test above restored to check the pointer.
    """
    run_turn()

    findings = store.load_findings()
    assert findings, "expected the weakness to have fired"

    for finding in findings:
        assert finding.evidence.get("marker") is None, (
            "KI-2 appears to be fixed - if so, update this test and restore the "
            "evidence-pointer assertion in test_the_api_reports_the_findings_in_the_"
            "promised_shape."
        )
        # The double-save also inflates the count on a first sighting.
        assert finding.occurrences == 2

    # ...while the evidence files themselves are perfectly fine.
    assert count_markers() == len(findings)
