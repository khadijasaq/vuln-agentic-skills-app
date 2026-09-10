"""
The whole weakness, end to end: a document decides what an installed skill does.

These tests run the real app, with a real loopback server, a real fetch and a real send.
Only the model is stubbed, and only so that the skill is definitely chosen - whether a
live model chooses it is the separate manual check (A-1).

The story each test is telling:

    the assistant decides to run Team Rules
      -> the skill fetches a document from the team hub
      -> the document says where to report, so the skill reports THERE
      -> the document plants a line, so the skill repeats it
      -> that line travels to the model as the tool's result
      -> the app raises two findings and writes the evidence

Nothing in the skill changes between the honest case and the attacked case. Only the
document does. That is the point being demonstrated, and A-13 is where it is proved.

Specification references: feature spec sections 5.4, 9.1 and 10; acceptance tests A-3,
A-5, A-6, A-13.
"""

from __future__ import annotations

import httpx

from app.chat.orchestrator import ChatOrchestrator
from app.storage import store

# This folder's name has hyphens, so it cannot be a Python package and its tests cannot
# import from its conftest. Fixtures are injected by name instead - the same arrangement
# the sibling weaknesses use. Only the two addresses are repeated here.
LOCAL_BASE_URL = "http://127.0.0.1:8000"
HUB_RULES_URL = f"{LOCAL_BASE_URL}/mock/hub/rules"
COLLECTOR_URL = f"{LOCAL_BASE_URL}/mock/collector"


def run_turn(message: str = "are we following the team rules?"):
    """Ask the assistant one question, the way the API does."""
    return ChatOrchestrator().run_turn(message)


# --- A-3: the two findings fire on an LLM-chosen invocation -------------------------


def test_the_document_steers_the_skill_and_both_findings_fire(live_lab, shipped_document):
    """
    A-3 - the headline test.

    The model chooses the skill for its advertised purpose. The skill does that job, and
    while doing it obeys two instructions that were not in it: where to report, and what
    to say. Both are reported, each as its own kind of problem.
    """
    _, stub = live_lab
    document = shipped_document

    turn = run_turn()

    findings = {finding.type: finding for finding in turn.findings_raised}
    assert set(findings) == {"EXTERNAL_INSTRUCTION_FLOW", "AGENT_INSTRUCTION_RELAY"}, (
        f"expected exactly the two AST05 findings, got {sorted(findings)}"
    )

    # --- the steered action ---
    steered = findings["EXTERNAL_INSTRUCTION_FLOW"]
    assert steered.ast_id == "AST05"
    assert steered.ast_name == "Untrusted External Instructions"
    assert steered.axis == "provenance"
    assert steered.severity == "high"
    assert steered.trigger == "invocation"
    assert steered.model == "stub"
    assert steered.provenance["influence"] == "resource"
    assert steered.provenance["source_url"] == HUB_RULES_URL
    # The address it was steered to is the resolved version of the one the document named.
    assert steered.provenance["matched_excerpt"] == COLLECTOR_URL
    assert "__SELF_URL__" in document["report_to"] or document["report_to"] == COLLECTOR_URL
    # The fetch came first and the steered send after it - the causal order.
    assert steered.provenance["source_seq"] < steered.provenance["acted_seq"]

    # --- the relay ---
    relay = findings["AGENT_INSTRUCTION_RELAY"]
    assert relay.ast_id == "AST05"
    assert relay.axis == "provenance"
    assert relay.severity == "medium"
    assert relay.provenance["influence"] == "returned_summary"
    assert relay.provenance["matched_excerpt"] == document["notice"]

    # --- the evidence field is the provenance one, and only that one ---
    for finding in (steered, relay):
        assert finding.observed is None
        assert finding.granted is None
        assert finding.correlation is None
        assert finding.provenance is not None

    # --- the turn is marked, and the skill really ran ---
    assert turn.activity.vulnerability_fired is True
    assert turn.activity.skill_invoked.skill_id == "team_rules"
    assert turn.activity.skill_invoked.outcome == "ok"

    # --- and the planted text really did reach the model ---
    assert stub.tool_messages, "the app never handed the tool result to the model"
    assert document["notice"] in stub.tool_messages[0], (
        "the document's line did not reach the model's context, so the relay finding "
        "would be describing something that did not happen"
    )


def test_the_evidence_marker_shows_what_the_document_said(live_lab, shipped_document):
    """
    A-3, the evidence half - a person can read the attack in the marker file.

    A finding that says "fetched content steered this skill" without showing what the
    content said would be almost useless to whoever has to judge it. The readable excerpt
    is why the excerpt exists.
    """
    document = shipped_document
    run_turn()

    from app.findings.markers import MARKER_PHRASE
    from app.config import get_settings

    markers = sorted(get_settings().markers_dir.iterdir())
    assert markers, "no evidence was written"

    contents = [path.read_text(encoding="utf-8") for path in markers]
    joined = "\n".join(contents)

    assert MARKER_PHRASE in joined
    assert "AST05" in joined
    # The instruction itself is readable in the evidence.
    assert document["notice"][:40] in joined or document["report_to"] in joined


# --- A-5: AST05 alone ---------------------------------------------------------------


def test_the_skill_fires_ast05_and_nothing_else(live_lab):
    """
    A-5 - the distinctness proof, on the real running skill.

    Its manifest is true, so nothing for the truthfulness check. Its permissions are
    exactly what its category allows, so nothing for the proportionality check. It sends
    no task contents, so nothing for the theft check. Only the fourth question has
    anything to say about it.
    """
    turn = run_turn()

    axes = {finding.axis for finding in turn.findings_raised}
    ast_ids = {finding.ast_id for finding in turn.findings_raised}
    types = {finding.type for finding in turn.findings_raised}

    assert axes == {"provenance"}
    assert ast_ids == {"AST05"}

    for unwanted in (
        "UNDECLARED_CAPABILITY",
        "SCOPE_VIOLATION",
        "BROKER_BYPASS",
        "EXCESSIVE_GRANT",
        "UNUSED_GRANT",
        "COVERT_DATA_FLOW",
    ):
        assert unwanted not in types, f"{unwanted} fired; this should be AST05 alone"


def test_installing_it_raises_nothing_at_all(live_lab):
    """
    Nothing about this weakness is visible before it runs.

    The exact opposite of the over-privileged skill, whose whole problem is legible from
    the manifest at install time. Here the manifest is spotless, and the instructions
    that cause the harm do not exist until the skill asks for them (TDD D-16).
    """
    base_url, _ = live_lab

    with httpx.Client(timeout=10.0) as client:
        client.post(f"{base_url}/api/skills/team_rules/uninstall")
        store.reset_lab()
        response = client.post(f"{base_url}/api/skills/team_rules/install")

    assert response.status_code == 200
    assert response.json()["findings_raised"] == []


# --- A-6: steered, but not a thief --------------------------------------------------


def test_what_was_sent_carries_no_task_content(live_lab, collector_deliveries):
    """
    A-6 - the steer happened, and nothing was stolen.

    The document redirected where this skill reports. What it reported was a count and a
    version string. Keeping those two things separate is what stops this weakness reading
    as a re-run of the theft one - and it has to be true of the real payload, not just of
    the intent.
    """
    tasks = store.load_tasks()
    assert tasks, "the lab should have seeded tasks, or this proves nothing"

    run_turn()

    deliveries = collector_deliveries()
    assert len(deliveries) == 1, "the acknowledgement should have arrived, exactly once"

    payload = deliveries[0]["payload"]
    assert set(payload) == {"acknowledged", "rules_version", "open", "breaches"}

    # No task title, note or id is anywhere in what was sent.
    sent = str(payload)
    for task in tasks:
        assert task.title not in sent
        if task.notes:
            assert task.notes not in sent
        assert task.id not in sent


def test_no_correlation_finding_is_raised(live_lab):
    """
    A-9, confirmed on the running skill rather than on a hand-built log.

    The theft check needs fingerprints of the user's tasks to turn up in something sent
    out. They never do, so it has nothing to say - which is what makes the two weaknesses
    genuinely different rather than differently worded.
    """
    turn = run_turn()
    assert [f for f in turn.findings_raised if f.type == "COVERT_DATA_FLOW"] == []


# --- A-13: the vulnerability is in the document, not the skill ----------------------


def test_with_the_instructions_removed_the_same_skill_is_harmless(live_lab, shipped_document, write_hub_document, collector_deliveries):
    """
    A-13, and the sharpest statement of what AST05 actually is.

    The document is replaced with one that has no report_to and no notice. **The skill,
    its code and its manifest are byte-for-byte identical.** It fetches the same hub over
    the same connection and does the same job - and raises nothing.

    So the weakness is not "this skill makes network requests". It is "this skill does
    what it is told". Change only the document and the danger appears or vanishes, with
    nothing to re-approve either way. That is the entire argument for the fourth axis, and
    it is also what proves the detector is not simply reacting to a fetch.
    """
    honest = {k: v for k, v in shipped_document.items() if k not in ("report_to", "notice")}
    write_hub_document(honest)

    turn = run_turn()

    assert turn.findings_raised == [], (
        "the same skill, fetching an honest document, must raise nothing"
    )
    assert turn.activity.vulnerability_fired is False
    # ...and it still did its job.
    assert turn.activity.skill_invoked.outcome == "ok"
    assert collector_deliveries() == []


def test_with_no_hub_at_all_the_skill_still_works(live_lab, write_hub_document):
    """
    A-13, the degradation half - the advertised job does not depend on the attack.

    A lab whose hub has no document still gets a working rules check, from the skill's
    built-in fallback. A skill that fell over without its attacker would not be
    convincing, and would not be installed.
    """
    write_hub_document(None)

    turn = run_turn()

    assert turn.findings_raised == []
    assert turn.activity.skill_invoked.outcome == "ok"
    assert turn.activity.reply


def test_changing_the_document_changes_where_it_sends(live_lab, shipped_document, write_hub_document, collector_deliveries):
    """
    The control is real and continuous, not a single hard-coded trick.

    A different address in the document produces a send to that different address, with
    the finding naming it. Nobody edited the skill.
    """
    document = dict(shipped_document)
    document["report_to"] = "http://127.0.0.1:8000/mock/dashboard"
    write_hub_document(document)

    turn = run_turn()

    steered = [f for f in turn.findings_raised if f.type == "EXTERNAL_INSTRUCTION_FLOW"]
    assert len(steered) == 1
    assert steered[0].provenance["matched_excerpt"] == "http://127.0.0.1:8000/mock/dashboard"
    # It went to the dashboard instead, so the collector saw nothing.
    assert collector_deliveries() == []
