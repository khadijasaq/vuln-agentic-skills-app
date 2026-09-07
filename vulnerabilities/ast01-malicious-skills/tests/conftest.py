"""
Shared setup for the AST01 (Standup Sync) tests.

This weakness keeps its own tests, so nothing about it leaks into the foundation's
test folder. To avoid copying the foundation's test machinery in here, it REUSES the
foundation fixtures by importing them - the isolated temporary data folder and the
automatic settings reset - and adds only what is specific to this weakness:

  - installing the malicious skill;
  - running a real, live copy of the whole app on this machine, so the skill's theft
    travels the genuine network path to the mock collector, exactly as it would in a
    real session. Nothing leaves the machine - the only address involved is this one.

Specification references: feature spec sections 4 and 9; build plan step 4.1.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest
import uvicorn

# Re-export the foundation fixtures so tests in this folder can use them by name. The
# autouse reset must be re-exported too, so it keeps running before and after each
# test here just as it does for the foundation tests.
from tests.conftest import tmp_settings, _clear_settings_between_tests  # noqa: F401

from app.llm.groq_client import ChatResponse, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed

LOCAL_BASE_URL = "http://127.0.0.1:8000"


class StandupStub:
    """
    A stand-in for the AI model that always chooses Standup Sync.

    A real model would decide this for itself from the user's words; the stub removes
    that variability so the test is about what the SKILL does once chosen, not about
    whether the model picks it (that is the separate, manual A-1 check).

    First reply: "run standup_sync". Second reply: an ordinary sentence, since every
    turn asks the model once to choose and once to phrase the result.
    """

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(content="", tool_calls=[ToolCall("standup_sync", {})], model="stub")
        return ChatResponse(content="Posted your standup update.", tool_calls=[], model="stub")


@pytest.fixture
def installed_standup_sync(tmp_settings):
    """The malicious skill, discovered from its folder and switched on."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("standup_sync")

    yield registry

    registry_module.reset_registry()
    host_module.clear_module_cache()


@pytest.fixture
def live_lab(tmp_settings, monkeypatch, installed_standup_sync):
    """
    A real, running copy of the app on 127.0.0.1:8000, with the model stubbed.

    The server runs in a background thread of THIS process, so two things hold at once:
    the stubbed model applies to it (no real AI model is needed), and the skill's
    network send travels a genuine loopback request to the app's own collector - the
    same path a real session uses. The temporary data folder is shared, so the stolen
    copy lands where the test can find it.
    """
    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", StandupStub()),
    )

    from app.main import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=8000, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    _wait_until_ready(f"{LOCAL_BASE_URL}/api/health")
    try:
        yield LOCAL_BASE_URL
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _wait_until_ready(health_url: str, timeout_seconds: float = 10.0) -> None:
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
