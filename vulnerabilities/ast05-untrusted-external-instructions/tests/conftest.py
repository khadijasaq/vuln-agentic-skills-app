"""
Shared setup for the AST05 (Team Rules) tests.

This weakness keeps its own tests, so nothing about it leaks into the foundation's test
folder. Rather than copying the foundation's machinery in here, it REUSES it by importing
- the isolated temporary data folder and the automatic settings reset - and adds only what
is specific to this weakness:

  - installing the instruction-following skill;
  - running a real, live copy of the whole app on this machine, so the skill genuinely
    FETCHES its document over the network and genuinely POSTs where that document tells
    it to. Nothing leaves the machine - the only address involved is this one.

Why a live server rather than a test client: this weakness is about what comes BACK from a
network request. A stubbed request has no reply, so stubbing would remove the one thing
being tested.

Specification references: feature spec sections 4, 5 and 10; build plan step 5.1.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

# Re-export the foundation fixtures so tests in this folder can use them by name. The
# autouse reset must be re-exported too, so it keeps running around each test here.
from tests.conftest import tmp_settings, _clear_settings_between_tests  # noqa: F401

from app.config import get_settings
from app.llm.groq_client import ChatResponse, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed

LOCAL_BASE_URL = "http://127.0.0.1:8000"
HUB_RULES_URL = f"{LOCAL_BASE_URL}/mock/hub/rules"
COLLECTOR_URL = f"{LOCAL_BASE_URL}/mock/collector"

# The document that ships with this weakness - the one the hub serves unless a test
# replaces it.
SHIPPED_DOCUMENT_PATH = Path(__file__).resolve().parents[1] / "hub" / "rules.json"


@pytest.fixture
def shipped_document() -> dict:
    """
    The rules document exactly as it ships.

    Offered as a fixture rather than an import because this folder's name contains
    hyphens and so cannot be a Python package - the sibling weaknesses share helpers the
    same way.
    """
    return json.loads(SHIPPED_DOCUMENT_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def write_hub_document():
    """
    A way for a test to put a particular document in the hub, or remove it entirely.

    In: the document to serve, or None to leave the hub with nothing.
    Out: nothing.

    This is how a test plays the attacker: the skill and its manifest never change, only
    the document does - which is the whole shape of this weakness.
    """

    def _write(document: dict | None) -> None:
        settings = get_settings()
        settings.hub_dir.mkdir(parents=True, exist_ok=True)
        path = settings.hub_dir / "rules.json"

        if document is None:
            if path.exists():
                path.unlink()
            return

        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    return _write


class TeamRulesStub:
    """
    A stand-in for the AI model that always chooses Team Rules.

    A real model decides this for itself from the user's words; the stub removes that
    variability so a test is about what the SKILL does once chosen, not about whether the
    model picks it. Whether it picks it is the separate, manual A-1 check.

    The second reply is a plain sentence, because every turn asks the model once to choose
    and once to phrase the result.
    """

    def __init__(self) -> None:
        self.calls = 0
        # What the app handed the model as the tool's result. This is the thing A-3 needs
        # to inspect: text the document planted travels to the model through here.
        self.tool_messages: list[str] = []

    def chat(self, messages, tools=None):
        self.calls += 1

        # Every turn asks twice: once to choose, once to phrase the result. So the skill
        # is asked for on every FIRST question of a turn, not only on the very first
        # question ever - otherwise a test that runs two turns would find the second one
        # silently doing nothing, which is a real model's behaviour only if it changed
        # its mind.
        if self.calls % 2 == 1:
            return ChatResponse(content="", tool_calls=[ToolCall("team_rules", {})], model="stub")

        for message in messages:
            if message.get("role") == "tool":
                self.tool_messages.append(message.get("content") or "")

        return ChatResponse(content="Here is how your tasks look.", tool_calls=[], model="stub")


@pytest.fixture
def installed_team_rules(tmp_settings):
    """The instruction-following skill, discovered from its folder and switched on."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("team_rules")

    yield registry

    registry_module.reset_registry()
    host_module.clear_module_cache()


@pytest.fixture
def live_lab(tmp_settings, monkeypatch, installed_team_rules):
    """
    A real, running copy of the app on 127.0.0.1:8000, with the model stubbed.

    The server runs in a background thread of THIS process, so the stubbed model applies to
    it and the skill's fetch travels a genuine loopback request to the app's own hub - the
    same path a real session uses. The temporary data folder is shared, so a test can read
    what was served and what was received.

    Yields the stub as well as the address, because the stub is where a test can see what
    the app handed to the model - which is how the relay is observed rather than assumed.
    """
    stub = TeamRulesStub()
    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", stub),
    )

    from app.main import create_app

    application = create_app()

    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=8000, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    _wait_until_ready(f"{LOCAL_BASE_URL}/api/health")
    try:
        yield LOCAL_BASE_URL, stub
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _wait_until_ready(health_url: str, timeout_seconds: float = 15.0) -> None:
    """
    Wait for the live server to answer, or give a clear error if it never does.

    In: the health address and how long to wait. Out: nothing.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(health_url, timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise RuntimeError(
        "The live test server did not become ready on 127.0.0.1:8000. "
        "Is something else already using that port?"
    )


@pytest.fixture
def collector_deliveries():
    """
    A way for a test to read everything the mock collector has received.

    In: nothing. Out: a callable giving the delivered payloads, oldest first.
    """

    def _deliveries() -> list[dict]:
        inbox = get_settings().collector_dir / "inbox"
        if not inbox.exists():
            return []
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(inbox.iterdir())
            if path.is_file()
        ]

    return _deliveries
