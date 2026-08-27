"""
Proves the AST03 findings appear the moment the skill is switched on, are attributable
through the stable machine-readable interface, and that the lab is fully reversible -
all through a real copy of the app.

THE ONE THING THAT READS DIFFERENTLY FROM THE OTHER TWO WEAKNESSES. For the lying skill
and the thieving skill, the finding APPEARS when the skill runs, because until it runs
there is nothing to compare. This weakness is a property of what the skill was HANDED, so
the answer exists the moment it is installed - before the AI model has had any chance to
choose it. When the model does choose it, the same three findings are counted again
rather than duplicated: the count goes up, the "last seen" time moves, and the exchange
that caused it is recorded.

That is deliberate and is asserted here on purpose, because it would be easy to mistake
"no new rows appeared" for "nothing fired". The findings did fire - they had already
fired, and the run confirmed them.

Specification references: feature spec sections 3, 5.1, 5.3 and 7; decisions S-9, S-11;
plan notes P-5; acceptance tests A-3, A-12, A-13; PRD FR-6.3, FR-7.5, TDD Q-4 and D-11.
"""

from __future__ import annotations

import json

from app.config import get_settings
from app.findings.markers import MARKER_PHRASE, count_markers

# What a reporting skill is allowed to do. Everything Focus Picker holds beyond this is
# what gets reported.
ALLOWED_FOR_REPORTING = ["task.read"]

EXCESS = {"fs.read", "task.write", "net.outbound"}


def _install(client):
    """Switch the skill on and hand back the parsed response."""
    response = client.post("/api/skills/focus_picker/install")
    assert response.status_code == 200, response.text
    return response.json()


def _ask(client, message="what should I work on next?"):
    """Send one natural request and hand back the parsed /api/chat response."""
    response = client.post("/api/chat", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def _findings(client, ast_id="AST03"):
    """Read the stored findings back through the stable interface."""
    response = client.get(f"/api/findings?ast_id={ast_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _marker_files():
    """Every piece of evidence currently on disk."""
    markers_dir = get_settings().markers_dir
    if not markers_dir.exists():
        return []
    return sorted(path for path in markers_dir.iterdir() if path.is_file())


# --- A-3: the findings stand from the moment it is installed ---------------------


def test_a3_installing_it_raises_three_findings_with_evidence(api_client):
    """
    ACCEPTANCE TEST A-3.

    Switching the skill on is enough. Three abilities sit outside what a reporting skill
    should have, so three findings are raised there and then - each one naming the
    ability, the reach it asked for, and the yardstick it was measured against - and the
    app writes a piece of evidence to disk for each.

    Note what the evidence looks like for this kind of problem: there is no "the skill did
    this" line to point at, because nothing has been done yet. The marker records the
    finding with no action attached, which is exactly right - the problem is the size of
    the key ring, not a door that was opened.
    """
    body = _install(api_client)
    raised = body["findings_raised"]

    assert len(raised) == 3
    assert {finding["granted"]["capability"] for finding in raised} == EXCESS

    for finding in raised:
        assert finding["type"] == "EXCESSIVE_GRANT"
        assert finding["ast_id"] == "AST03"
        assert finding["ast_name"] == "Over-Privileged Skills"
        assert finding["axis"] == "proportionality"
        assert finding["severity"] == "medium"
        assert finding["trigger"] == "install"
        assert finding["invocation_id"] is None
        assert finding["granted"]["reason"] == "capability_outside_baseline"
        assert finding["granted"]["allowed"] == ALLOWED_FOR_REPORTING
        assert finding["observed"] is None
        assert finding["correlation"] is None
        assert finding["evidence"]["observation_seq"] is None
        assert finding["evidence"]["marker"]
        assert finding["model"]
        # The full, honest description travels with the finding, so a reader can see
        # everything the skill asked for next to the one thing it was allowed.
        assert finding["declared"]["category"] == "reporting"
        assert len(finding["declared"]["capabilities"]) == 4

    # One piece of evidence per finding, each unmistakably a lab artefact.
    assert count_markers() == 3
    for path in _marker_files():
        marker = json.loads(path.read_text(encoding="utf-8"))
        assert marker["marker"] == MARKER_PHRASE
        assert marker["ast_id"] == "AST03"
        assert marker["severity"] == "medium"
        # No single action caused this, so there is none recorded.
        assert marker["observation"] is None


def test_a3_the_store_shows_the_whole_grant_before_anyone_installs_it(api_client):
    """
    The permissions are on display, in the store, with reasons - including the two that
    admit to being unused. Nothing is hidden from the person deciding.

    This is what makes the weakness land: the user was told, in plain words, and the
    grant is still far too big. An over-powered skill does not need to deceive anyone.
    """
    response = api_client.get("/api/skills/focus_picker")
    assert response.status_code == 200, response.text
    declared = response.json()["declared_capabilities"]

    assert {item["id"] for item in declared} == EXCESS | {"task.read"}
    reasons = {item["id"]: item["reason"] for item in declared}
    assert "Not used in this version" in reasons["task.write"]
    assert "Not used in this version" in reasons["net.outbound"]


# --- A-12: attributable through the stable interface -----------------------------


def test_a12_the_run_confirms_the_findings_and_is_attributable(api_client):
    """
    ACCEPTANCE TEST A-12 and plan note P-5.

    A scanning tool needs to tie the problem to the exchange that exercised it. When the
    model chooses the skill, the exchange reports the same three findings by name, the
    activity entry is flagged, and the stored findings show they have now been seen twice.

    The counts are asserted POSITIVELY, on purpose. Repeats are deliberately counted
    rather than duplicated, so the findings list stays readable after a long session. If
    somebody later "fixed" the absence of new rows by weakening that, it would change how
    the whole product records every kind of problem - so this test states the intended
    behaviour rather than working around it.
    """
    installed = _install(api_client)
    original_ids = {finding["id"] for finding in installed["findings_raised"]}
    first_seen = {
        finding["id"]: finding["first_seen"] for finding in installed["findings_raised"]
    }

    body = _ask(api_client)

    assert body["skill_invoked"]["skill_id"] == "focus_picker"
    assert body["skill_invoked"]["outcome"] == "ok"

    raised = body["findings_raised"]
    assert len(raised) == 3
    # The same three problems, not three new ones.
    assert {finding["id"] for finding in raised} == original_ids

    for finding in raised:
        assert finding["occurrences"] >= 2
        assert finding["first_seen"] == first_seen[finding["id"]]
        assert finding["last_seen"] >= finding["first_seen"]
        # It was first noticed at installation, and that origin is not rewritten.
        assert finding["trigger"] == "install"

    # The exchange itself is flagged, so the activity screen shows the story.
    # The activity list comes back oldest first, so the exchange just made is the last.
    activity = api_client.get("/api/activity").json()["activity"]
    latest = activity[-1] if activity else {}
    assert latest.get("vulnerability_fired") is True
    assert set(latest.get("findings_raised", [])) == original_ids

    # And the stable findings list agrees, with no extra evidence files written.
    stored = _findings(api_client)
    assert stored["schema_version"] == 1
    assert len(stored["findings"]) == 3
    assert all(finding["occurrences"] >= 2 for finding in stored["findings"])
    assert count_markers() == 3


def test_a12_the_other_two_weaknesses_are_not_reported_here(api_client):
    """
    Nothing about this skill should show up under the lying or thieving headings. Asking
    the interface for those specifically must come back empty.
    """
    _install(api_client)
    _ask(api_client)

    assert _findings(api_client, "AST04")["findings"] == []
    assert _findings(api_client, "AST01")["findings"] == []


# --- A-13: the lab returns to clean ----------------------------------------------


def test_a13_reset_clears_everything_and_reinstalling_reproduces_it(api_client):
    """
    ACCEPTANCE TEST A-13.

    Two different kinds of "start again", both of which must work:

      RESET forgets what the app observed - findings, evidence, the activity log - while
      leaving every skill exactly as installed and as vulnerable as before. It is a
      convenience, never a safety switch.

      UNINSTALL AND REINSTALL raises the whole thing from scratch: three fresh findings
      with fresh identities and fresh evidence, because the skill is being handed its
      oversized key ring all over again.
    """
    _install(api_client)
    _ask(api_client)
    assert len(_findings(api_client)["findings"]) == 3

    cleared = api_client.post("/api/reset")
    assert cleared.status_code == 200, cleared.text

    assert _findings(api_client)["findings"] == []
    assert count_markers() == 0
    assert api_client.get("/api/activity").json()["activity"] == []
    # The task list is put back, and the skill is still installed - a reset cannot make
    # the app less vulnerable, only make it forget.
    assert api_client.get("/api/skills/focus_picker").json()["installed"] is True
    assert api_client.get("/api/health").json()["counts"]["tasks"] > 0

    api_client.post("/api/skills/focus_picker/uninstall")
    reinstalled = _install(api_client)

    assert len(reinstalled["findings_raised"]) == 3
    assert {f["granted"]["capability"] for f in reinstalled["findings_raised"]} == EXCESS
    assert count_markers() == 3
