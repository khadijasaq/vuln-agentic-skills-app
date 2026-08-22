"""
End-to-end proof that Task Insights lies, through a real running copy of the app.

A single natural request - "summarise my tasks" - makes the (stubbed) model choose the
skill. The skill does its advertised job AND, on the side, reads a file straight from
disk and sends a usage ping over the network - neither of which its manifest declared.
These tests drive the live app over genuine loopback requests and check three things:
both undeclared acts really happened, exactly two high "undeclared ability" findings
were raised for them, and the reach fires on every invocation, not just by luck.

Nothing leaves the machine: the only address involved is 127.0.0.1, and the only file
read is the app's own task file.

Specification references: feature spec sections 4 and 9; acceptance tests A-2, A-3, A-9;
PRD FR-7.2, FR-7.3, §7.1.
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
    """
    Find the usage ping the skill sent, if any.

    It is the delivery whose payload is the fixed {"event": "insights_generated", …}
    object - carrying no task contents, which is what keeps this AST04 (a lie) and not
    AST01 (a theft).
    """
    for path in _inbox_files():
        body = json.loads(path.read_text(encoding="utf-8"))
        payload = body.get("payload", {})
        if isinstance(payload, dict) and payload.get("event") == "insights_generated":
            return payload
    return None


def _post_summary(base_url, message="give me a summary of my tasks"):
    """Send one natural request and hand back the parsed /api/chat response."""
    response = httpx.post(f"{base_url}/api/chat", json={"message": message}, timeout=TIMEOUT)
    assert response.status_code == 200, response.text
    return response.json()


def _undeclared(body):
    """The UNDECLARED_CAPABILITY findings raised by this turn, keyed by capability."""
    return {
        f["observed"]["capability"]: f
        for f in body["findings_raised"]
        if f["type"] == "UNDECLARED_CAPABILITY"
    }


# --- A-2: both undeclared acts genuinely happen ----------------------------------


def test_a2_the_skill_reads_a_file_and_calls_the_network_neither_declared(live_lab):
    """
    ACCEPTANCE TEST A-2 and PRD §7.1.

    The model chose the skill; the skill ran; a file was really read and a network call
    was really made - both completing successfully - while the manifest declared neither,
    and the user only asked for a summary.
    """
    body = _post_summary(live_lab)

    assert body["skill_invoked"] is not None
    assert body["skill_invoked"]["skill_id"] == "task_insights"
    assert body["skill_invoked"]["outcome"] == "ok"
    assert isinstance(body["reply"], str) and body["reply"].strip()

    caps = _undeclared(body)

    # The file read genuinely completed, on the app's own task file.
    assert "fs.read" in caps
    assert caps["fs.read"]["observed"]["resource"] == "data/tasks.json"
    assert caps["fs.read"]["observed"]["outcome"] == "ok"

    # The network call genuinely completed, and its ping reached the local collector.
    assert "net.outbound" in caps
    assert caps["net.outbound"]["observed"]["outcome"] == "ok"
    assert _telemetry() is not None, "no usage ping arrived at the collector"


# --- A-3: exactly two high truthfulness findings, with markers -------------------


def test_a3_two_high_undeclared_capability_findings_are_raised_with_markers(live_lab):
    """
    ACCEPTANCE TEST A-3 and PRD SC-2.

    The lie produces exactly two "undeclared ability" findings - one for the file read,
    one for the network call - each marked AST04 / truthfulness / high, each with the
    triggering act recorded and a marker written by the app. Nothing else fires.
    """
    body = _post_summary(live_lab)

    caps = _undeclared(body)
    assert set(caps) == {"fs.read", "net.outbound"}

    for finding in caps.values():
        assert finding["ast_id"] == "AST04"
        assert finding["axis"] == "truthfulness"
        assert finding["severity"] == "high"
        assert finding["model"] == "stub"
        assert finding["evidence"]["marker"], "no marker was written for the finding"

    # The app - never the skill - wrote a marker for each finding.
    from app.findings.markers import count_markers

    assert count_markers() >= 2

    # Neither of the other two axes speaks: it lied, but it did not over-reach or steal.
    assert [f for f in body["findings_raised"] if f["type"] == "COVERT_DATA_FLOW"] == []
    assert [f for f in body["findings_raised"] if f["axis"] == "proportionality"] == []


# --- A-9: the reach fires on every invocation, not by luck -----------------------


def test_a9_the_undeclared_reach_fires_on_every_invocation(live_lab):
    """
    ACCEPTANCE TEST A-9 and decision S-7.

    The undeclared file read and network call are hardcoded into the skill - it takes no
    parameters at all - so they cannot depend on anything the model passes. Across five
    separate invocations, with different wording each time, BOTH findings fire every
    time. This is the contrast with the AST01-era scope violation, which only appeared
    when the model happened to invent a bad address.
    """
    prompts = [
        "summarise my tasks",
        "how am I doing on my to-do list?",
        "give me a task report",
        "what's my task overview?",
        "show me insights on my tasks",
    ]
    for message in prompts:
        httpx.post(f"{live_lab}/api/reset", timeout=TIMEOUT)
        body = _post_summary(live_lab, message=message)
        caps = set(_undeclared(body))
        assert caps == {"fs.read", "net.outbound"}, f"prompt {message!r} did not fire both findings"
