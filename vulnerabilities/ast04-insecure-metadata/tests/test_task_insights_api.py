"""
Proves the AST04 findings are reported through the stable API, and that the lab is
fully reversible - through a real running copy of the app.

Specification references: feature spec sections 9 and 7; acceptance tests A-5, A-11;
PRD FR-6.3, FR-7.5, TDD Q-4.
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


def _telemetry():
    """The fixed usage ping the skill sends, if it has arrived."""
    for path in _inbox_files():
        body = json.loads(path.read_text(encoding="utf-8"))
        payload = body.get("payload", {})
        if isinstance(payload, dict) and payload.get("event") == "insights_generated":
            return payload
    return None


def _post_summary(base_url):
    """Send one natural request and hand back the parsed /api/chat response."""
    response = httpx.post(
        f"{base_url}/api/chat",
        json={"message": "give me a summary of my tasks"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- A-5: the findings are attributable through the stable API -------------------


def test_a5_the_findings_are_reported_through_the_api_contract(live_lab):
    """
    ACCEPTANCE TEST A-5 and PRD FR-6.3.

    A scanning tool can attribute the lie to the exact request that caused it (the
    per-turn findings_raised) and then read both findings back from the stable findings
    list, filtered by the AST id.
    """
    body = _post_summary(live_lab)

    raised = [f["type"] for f in body["findings_raised"]]
    assert raised.count("UNDECLARED_CAPABILITY") == 2

    listed = httpx.get(f"{live_lab}/api/findings", params={"ast_id": "AST04"}, timeout=TIMEOUT)
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["schema_version"] >= 1

    undeclared = [f for f in payload["findings"] if f["type"] == "UNDECLARED_CAPABILITY"]
    assert len(undeclared) == 2
    assert all(f["severity"] == "high" for f in undeclared)
    assert {f["observed"]["capability"] for f in undeclared} == {"fs.read", "net.outbound"}


# --- A-11: the lie is fully reversible and reproducible --------------------------


def test_a11_reset_clears_everything_and_the_lie_reproduces_from_clean(live_lab):
    """
    ACCEPTANCE TEST A-11 and TDD Q-4 / PRD FR-7.5.

    Reset wipes the findings, the markers, the activity and the collector inbox; the lab
    returns to clean, and the very same request reproduces the lie.
    """
    _post_summary(live_lab)
    assert _telemetry() is not None

    reset = httpx.post(f"{live_lab}/api/reset", timeout=TIMEOUT)
    assert reset.status_code == 200

    # Everything to do with the lie is gone.
    assert _inbox_files() == []
    after = httpx.get(f"{live_lab}/api/findings", timeout=TIMEOUT).json()
    assert after["findings"] == []

    # And it happens again from clean - the skill is still installed.
    body = _post_summary(live_lab)
    assert _telemetry() is not None
    assert [f for f in body["findings_raised"] if f["type"] == "UNDECLARED_CAPABILITY"]
