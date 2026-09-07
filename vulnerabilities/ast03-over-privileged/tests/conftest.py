"""
Shared setup for the AST03 (Focus Picker) tests.

This weakness keeps its own tests, so nothing about it leaks into the foundation's test
folder. To avoid copying the foundation's test machinery in here, it REUSES the
foundation fixtures by importing them - the isolated temporary data folder and the
automatic settings reset - and adds only what is specific to this weakness:

  - installing the over-powered skill;
  - a stand-in for the AI model that always chooses it, so the tests are about what
    happens once it is chosen rather than about whether a real model picks it (that is
    the separate, manual check);
  - a test client that drives the real app in-process.

WHY THERE IS NO LIVE SERVER HERE. The other two weaknesses run a real copy of the app on
a real address, because their skills genuinely send something to the app's own collector
and the delivery has to travel a real network path. Focus Picker never sends anything at
all - that is one of the things being demonstrated - so there is nothing to serve, and a
plain in-process test client is enough. Fewer moving parts, and the absence of any
network setup is itself a visible fact about this weakness (decision P-3).

Specification references: feature spec sections 4 and 9; build plan step 3.1; plan notes
P-1, P-2, P-3.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Re-export the foundation fixtures so tests in this folder can use them by name. The
# autouse reset must be re-exported too, so it keeps running before and after each test
# here just as it does for the foundation tests.
from tests.conftest import tmp_settings, _clear_settings_between_tests  # noqa: F401

from app.config import get_settings
from app.llm.groq_client import ChatResponse, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed


class FocusPickerStub:
    """
    A stand-in for the AI model that always chooses Focus Picker.

    A real model would decide this for itself from the user's words; the stub removes
    that variability so the test is about what the SKILL does once chosen, not about
    whether the model picks it (that is the separate, manual A-1 check).

    Every turn asks the model twice: once to choose a skill, and once to turn whatever
    came back into a natural sentence. So this stand-in answers "run focus_picker" first,
    and then repeats what the skill handed back - which is what a real model does with a
    tool's result, and what lets a test check that the advertised answer reached the user.

    The arguments it passes can be changed between turns, which is how the "the findings
    do not depend on what the model passed" check varies them.
    """

    def __init__(self, arguments: dict | None = None) -> None:
        self.calls = 0
        self.arguments = dict(arguments or {})

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls % 2 == 1:
            return ChatResponse(
                content="",
                tool_calls=[ToolCall("focus_picker", dict(self.arguments))],
                model="stub",
            )
        return ChatResponse(content=_last_tool_message(messages), tool_calls=[], model="stub")


def _last_tool_message(messages) -> str:
    """
    Find what the skill handed back, from the conversation the model was shown.

    In: the messages. Out: the skill's own sentence, or a plain fallback.

    The app appends the skill's result to the conversation before asking the model to
    phrase it, so this is the stand-in's way of "reading" that result instead of
    inventing a reply that could hide a broken skill.
    """
    for message in reversed(list(messages or [])):
        if message.get("role") == "tool" and message.get("content"):
            return str(message["content"])
    return "Here is what to work on next."


@pytest.fixture
def installed_focus_picker(tmp_settings):
    """The over-powered skill, discovered from its folder and switched on."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("focus_picker")

    yield registry

    registry_module.reset_registry()
    host_module.clear_module_cache()


@pytest.fixture
def discovered_focus_picker(tmp_settings):
    """
    The skill discovered but NOT switched on.

    Some checks are about what happens at the moment of installation, so they need the
    skill found but not yet installed.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    registry = registry_module.get_registry()
    registry.discover_default()

    yield registry

    registry_module.reset_registry()
    host_module.clear_module_cache()


@pytest.fixture
def aligned_cwd(monkeypatch, tmp_settings):
    """
    Point the current folder at the isolated data root's parent.

    The skill reads the relative path "data/activity.json", and the file broker works out
    where a relative path lands from the folder the program is running in. In normal use
    the app is started from the top of the project, where "data" is the data folder. This
    reproduces that arrangement inside the temporary folder, so the read resolves to the
    isolated copy (plan note P-1).

    Nothing about the findings depends on this - a refused read produces exactly the same
    three findings - but it is what lets the "the read really succeeded" check be honest.
    """
    monkeypatch.chdir(get_settings().data_dir.parent)
    return get_settings().data_dir


@pytest.fixture
def api_client(tmp_settings, monkeypatch, aligned_cwd):
    """
    The real app, driven in-process, with the model stubbed out.

    The skill is NOT installed here: several checks are about installation itself.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()

    stub = FocusPickerStub()
    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", stub),
    )

    from app.main import create_app

    with TestClient(create_app()) as client:
        client.stub = stub
        yield client

    registry_module.reset_registry()
    host_module.clear_module_cache()
