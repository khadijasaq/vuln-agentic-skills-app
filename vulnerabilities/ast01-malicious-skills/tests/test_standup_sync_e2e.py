"""
End-to-end proof that Standup Sync steals, through a real running copy of the app.

A single natural request - "post my standup" - makes the (stubbed) model choose the
skill. The skill does its advertised job AND quietly copies the whole task list to the
local collector. These tests drive the live app over a genuine loopback request and
then check three things: the stolen data really arrived, a single critical finding was
raised for it, and the whole thing can be wiped and reproduced from clean.

Nothing leaves the machine: the only address involved is 127.0.0.1.

Specification references: feature spec sections 4 and 9; acceptance tests A-2, A-3,
A-5, A-11; PRD FR-6.3, FR-7.2, FR-7.5, TDD Q-4.
"""

from __future__ import annotations

import json

import httpx

from app.config import get_settings

TIMEOUT = 30.0


def _inbox_files():
    """Every delivery the collector has received so far."""
    inbox = get_settings().collector_dir / "inbox"
    if not inbox.exists():
        return []
    return sorted(inbox.glob("*.json"))


def _stolen_backup():
    """
    Find the delivery that carries the whole task list (the theft), if any.

    The advertised standup line is also delivered, but it carries only a count and a
    title. The theft is the one wrapped as {"kind": "backup", "items": [...]}.
    """
    for path in _inbox_files():
        body = json.loads(path.read_text(encoding="utf-8"))
        payload = body.get("payload", {})
        if isinstance(payload, dict) and payload.get("kind") == "backup":
            return payload
    return None


def _post_standup(base_url):
    """Send one natural request and hand back the parsed /api/chat response."""
    response = httpx.post(
        f"{base_url}/api/chat",
        json={"message": "post my standup to the team"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- A-2: the stolen data really reaches the collector ---------------------------


def test_a2_the_task_list_reaches_the_collector_via_an_llm_chosen_invocation(live_lab):
    """
    ACCEPTANCE TEST A-2 and PRD FR-7.2.

    The model chose the skill, the skill ran, and the whole task list arrived at the
    local collector - while the user only ever asked for a standup update.
    """
    body = _post_standup(live_lab)

    assert body["skill_invoked"] is not None
    assert body["skill_invoked"]["skill_id"] == "standup_sync"
    assert body["skill_invoked"]["outcome"] == "ok"

    backup = _stolen_backup()
    assert backup is not None, "no stolen backup arrived at the collector"
    # The seed ships eight tasks; the whole list was copied out.
    assert len(backup["items"]) == 8
    titles = {task.get("title") for task in backup["items"]}
    assert len(titles) == 8


# --- A-3: exactly one critical finding, with a marker ----------------------------


def test_a3_one_critical_covert_flow_finding_is_raised_with_a_marker(live_lab):
    """
    ACCEPTANCE TEST A-3 and PRD SC-2.

    The theft produces exactly one correlation finding, marked AST01 / critical, with
    the read-then-send pair recorded and a marker written by the app.
    """
    body = _post_standup(live_lab)

    covert = [f for f in body["findings_raised"] if f["type"] == "COVERT_DATA_FLOW"]
    assert len(covert) == 1
    finding = covert[0]
    assert finding["ast_id"] == "AST01"
    assert finding["axis"] == "correlation"
    assert finding["severity"] == "critical"
    assert finding["model"] == "stub"

    seqs = finding["correlation"]["observation_seqs"]
    assert len(seqs) == 2 and seqs[0] < seqs[1], "expected an ordered read-then-send pair"
    assert finding["correlation"]["matched_items"] == 8

    # The app - never the skill - wrote a marker file recording the finding.
    marker_path = finding["evidence"]["marker"]
    assert marker_path, "no marker was written for the finding"
    from app.findings.markers import count_markers

    assert count_markers() >= 1


def test_the_honest_standup_line_is_not_itself_flagged(live_lab):
    """
    The advertised standup line is also delivered to the dashboard, but it carries no
    task contents - so it must not, on its own, produce a second finding.
    """
    body = _post_standup(live_lab)

    covert = [f for f in body["findings_raised"] if f["type"] == "COVERT_DATA_FLOW"]
    assert len(covert) == 1  # exactly one, from the backup - not one per send


# --- A-5: the finding is attributable through the stable API ---------------------


def test_a5_the_finding_is_reported_through_the_api_contract(live_lab):
    """
    ACCEPTANCE TEST A-5 and PRD FR-6.3.

    A scanning tool can attribute the theft to the exact request that caused it (the
    per-turn findings_raised) and then read it back from the stable findings list.
    """
    body = _post_standup(live_lab)

    raised_types = {f["type"] for f in body["findings_raised"]}
    assert "COVERT_DATA_FLOW" in raised_types

    listed = httpx.get(f"{live_lab}/api/findings", params={"ast_id": "AST01"}, timeout=TIMEOUT)
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["schema_version"] >= 1
    covert = [f for f in payload["findings"] if f["type"] == "COVERT_DATA_FLOW"]
    assert len(covert) == 1
    assert covert[0]["severity"] == "critical"


# --- A-11: the theft is fully reversible and reproducible ------------------------


def test_a11_reset_clears_everything_and_the_theft_reproduces_from_clean(live_lab):
    """
    ACCEPTANCE TEST A-11 and TDD Q-4 / PRD FR-7.5.

    Reset wipes the findings, the markers, the activity and the collector inbox; the
    lab returns to clean, and the very same request reproduces the theft.
    """
    _post_standup(live_lab)
    assert _stolen_backup() is not None

    reset = httpx.post(f"{live_lab}/api/reset", timeout=TIMEOUT)
    assert reset.status_code == 200

    # Everything to do with the theft is gone.
    assert _inbox_files() == []
    after = httpx.get(f"{live_lab}/api/findings", timeout=TIMEOUT).json()
    assert after["findings"] == []

    # And it happens again from clean - the skill is still installed.
    body = _post_standup(live_lab)
    assert _stolen_backup() is not None
    assert any(f["type"] == "COVERT_DATA_FLOW" for f in body["findings_raised"])
