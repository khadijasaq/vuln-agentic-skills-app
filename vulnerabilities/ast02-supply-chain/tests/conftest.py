"""
Shared setup for the AST02 (Time Budget) tests.

This weakness keeps its own tests, so nothing about it leaks into the foundation's test
folder. Rather than copying the foundation's machinery in here, it REUSES it by importing
- the isolated temporary data folder and the automatic settings reset - and adds only what
is specific to this weakness:

  - installing the estimator skill;
  - putting a chosen build of the sizing pack into the registry, so a test can play the
    publisher and swap what gets delivered;
  - a task whose notes mention the kind of work the compromised build buries, so the
    effect is visible rather than merely detected;
  - running a real, live copy of the whole app on this machine, so the skill genuinely
    FETCHES the component over the network and the app genuinely records the fingerprint
    of what came back. Nothing leaves the machine - the only address involved is this one.

Why a live server rather than a stubbed request: this weakness is entirely about the
fingerprint of what came BACK. A stubbed request has no reply and therefore no
fingerprint, so stubbing would remove the one thing being tested.

Specification references: AST02 spec sections 5, 6 and 11; build plan step 7.1.
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
from app.llm.ollama_client import ChatResponse, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed, store

LOCAL_BASE_URL = "http://127.0.0.1:8000"
PACK_URL = f"{LOCAL_BASE_URL}/mock/registry/sizing-heuristics/2.3.1"

# The name the registry serves this component under.
COMPONENT_FILENAME = "sizing-heuristics-2.3.1.json"

_REGISTRY_DIR = Path(__file__).resolve().parents[1] / "registry"

# What the registry serves by default: the substituted build.
SHIPPED_COMPROMISED_PATH = _REGISTRY_DIR / COMPONENT_FILENAME
# What the skill's description pins: the build its author reviewed.
SHIPPED_REVIEWED_PATH = _REGISTRY_DIR / "sizing-heuristics-2.3.1.reviewed.json"

# The kind of work the compromised build buries. Deliberately short words: none of them
# reaches the length at which repeated text counts as a planted line, so this task cannot
# accidentally make a different weakness fire.
FLAGGED_TASK_TITLE = "Rotate the shared database credentials"
FLAGGED_TASK_NOTES = "Raised by the last security audit and still outstanding."


def _read_manifest() -> dict:
    """The skill's description, as it ships."""
    path = Path(__file__).resolve().parents[1] / "skill" / "time_budget" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def shipped_manifest() -> dict:
    """
    The skill's description exactly as it ships.

    Offered as a fixture rather than an import because this folder's name contains hyphens
    and so cannot be a Python package - the sibling weaknesses share helpers the same way.
    """
    return _read_manifest()


@pytest.fixture
def declared_pin(shipped_manifest) -> str:
    """The fingerprint the skill pins for the component it depends on."""
    return shipped_manifest["dependencies"][0]["integrity"]


@pytest.fixture
def reviewed_build_text() -> str:
    """
    The reviewed build, as exact text.

    Text rather than a parsed object on purpose. The fingerprint is taken over the bytes
    that are served, so putting this build in place has to reproduce those bytes exactly -
    re-encoding it through a JSON writer would change them and the pin would no longer
    match, which would silently break the one test that proves the check can stay quiet.
    """
    return SHIPPED_REVIEWED_PATH.read_bytes().decode("utf-8")


@pytest.fixture
def compromised_build_text() -> str:
    """The substituted build the registry serves by default, as exact text."""
    return SHIPPED_COMPROMISED_PATH.read_bytes().decode("utf-8")


@pytest.fixture
def write_component():
    """
    A way for a test to put a particular build in the registry, or remove it entirely.

    In: the build to serve - exact text, or an object to be written as JSON - or None to
    leave the registry with nothing.
    Out: nothing.

    This is how a test plays the publisher: the skill and its description never change,
    only what is delivered does - which is the whole shape of this weakness.

    Pass TEXT when the exact bytes matter (putting the reviewed build back, where the
    fingerprint has to match the pin). Pass an object when they do not (a fabricated build
    that only has to be different).
    """

    def _write(document: str | dict | None) -> None:
        settings = get_settings()
        settings.registry_dir.mkdir(parents=True, exist_ok=True)
        path = settings.registry_dir / COMPONENT_FILENAME

        if document is None:
            if path.exists():
                path.unlink()
            return

        if isinstance(document, str):
            path.write_bytes(document.encode("utf-8"))
        else:
            path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    return _write


@pytest.fixture
def flagged_task():
    """
    Add one task of the kind the compromised build buries.

    In: nothing. Out: the task that was created.

    The starter task list does not happen to contain anything mentioning security, audits,
    invoices or passwords, so without this the substitution would be detected but its
    effect would not be visible. Adding a task through the normal store is the honest way
    to show it: nothing about the app's own seeded data is changed.
    """

    def _add() -> dict:
        return store.add_task(FLAGGED_TASK_TITLE, FLAGGED_TASK_NOTES).model_dump()

    return _add


class TimeBudgetStub:
    """
    A stand-in for the AI model that always chooses Time Budget.

    A real model decides this for itself from the user's words; the stub removes that
    variability so a test is about what the SKILL does once chosen, not about whether the
    model picks it. Whether it picks it is the separate, manual A-1 check.

    The second reply is a plain sentence, because every turn asks the model once to choose
    and once to phrase the result.
    """

    def __init__(self, params: dict | None = None) -> None:
        self.calls = 0
        self.params = params or {}
        # What the app handed the model as the tool's result. A test can inspect this to
        # confirm that nothing from the fetched component travelled into the model's
        # context.
        self.tool_messages: list[str] = []

    def chat(self, messages, tools=None):
        self.calls += 1

        # Every turn asks twice: once to choose, once to phrase the result. So the skill is
        # asked for on every FIRST question of a turn, not only on the very first question
        # ever - otherwise a test running two turns would find the second silently doing
        # nothing.
        if self.calls % 2 == 1:
            return ChatResponse(
                content="", tool_calls=[ToolCall("time_budget", dict(self.params))], model="stub"
            )

        for message in messages:
            if message.get("role") == "tool":
                self.tool_messages.append(message.get("content") or "")

        return ChatResponse(content="Here is how long that will take.", tool_calls=[], model="stub")


@pytest.fixture
def installed_time_budget(tmp_settings):
    """The estimator skill, discovered from its folder and switched on."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("time_budget")

    yield registry

    registry_module.reset_registry()
    host_module.clear_module_cache()


@pytest.fixture
def live_lab(tmp_settings, monkeypatch, installed_time_budget):
    """
    A real, running copy of the app on 127.0.0.1:8000, with the model stubbed.

    The server runs in a background thread of THIS process, so the stubbed model applies to
    it and the skill's fetch travels a genuine loopback request to the app's own registry -
    the same path a real session uses. The temporary data folder is shared, so a test can
    swap what the registry serves and read what was recorded.

    Yields the stub as well as the address, because the stub is where a test can see what
    the app handed to the model.
    """
    stub = TimeBudgetStub()
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


def _wait_until_ready(health_url: str, timeout_seconds: float = 20.0) -> None:
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
