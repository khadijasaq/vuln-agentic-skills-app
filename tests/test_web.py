"""
Checks for the four web pages a person looks at.

The pages exist to tell one story in order: install a skill, ask something ordinary,
watch the assistant choose it, see what the app recorded. Someone who has never seen
TaskBot should be able to follow that in three clicks.

Two details here carry weight beyond appearances:

  - The store shows a skill's claimed permissions under the caption "declared by the
    publisher". The trust assumption a dishonest skill relies on belongs on screen,
    not buried in the code.
  - Every page carries the "intentionally vulnerable" notice, so no single screen can
    be mistaken for an ordinary application.

Covers: feature spec section 12; TDD section 9; requirements DR-1 to DR-6 and FR-7.6;
acceptance tests A-13 and A-16.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm.ollama_client import ChatResponse, OllamaUnavailable, ToolCall
from app.main import create_app
from app.skills import host as host_module
from app.skills import registry as registry_module

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_settings):
    registry_module.reset_registry()
    host_module.clear_module_cache()
    yield TestClient(create_app())
    registry_module.reset_registry()
    host_module.clear_module_cache()


# --- Every page ------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/store", "/findings", "/activity"])
def test_every_page_loads(client, path):
    """All four screens render."""
    response = client.get(path)

    assert response.status_code == 200
    assert "TaskBot" in response.text


@pytest.mark.parametrize("path", ["/", "/store", "/findings", "/activity"])
def test_every_page_says_this_app_is_intentionally_vulnerable(client, path):
    """
    REQUIREMENT FR-7.6.

    On every single screen, so no page seen in isolation can be mistaken for an
    ordinary application.
    """
    assert "Intentionally vulnerable" in client.get(path).text


@pytest.mark.parametrize("path", ["/", "/store", "/findings", "/activity"])
def test_every_page_offers_the_whole_story(client, path):
    """
    REQUIREMENT DR-6.

    The four screens are always one click apart, which is what makes the whole
    demonstration followable without instructions.
    """
    text = client.get(path).text

    for link in ['href="/"', 'href="/store"', 'href="/findings"', 'href="/activity"']:
        assert link in text


# --- Chat ------------------------------------------------------------------------


def test_the_chat_page_invites_a_first_message(client):
    """A brand new lab explains what to try rather than showing a blank box."""
    text = client.get("/").text

    assert "Nothing said yet" in text
    assert "book the dentist" in text


def test_sending_a_message_records_the_exchange(client, monkeypatch):
    """A message typed into the form really does reach the assistant."""

    class Stub:
        def chat(self, messages, tools=None):
            return ChatResponse(content="Noted that for you.", model="stub")

    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", Stub()),
    )

    posted = client.post("/chat", data={"message": "remember to call mum"}, follow_redirects=True)

    assert "remember to call mum" in posted.text
    assert "Noted that for you." in posted.text


def test_a_missing_model_is_explained_with_the_command_that_fixes_it(client, monkeypatch):
    """
    ACCEPTANCE TEST A-12, as a person would see it.

    A made-up reply would make a broken setup look like a working demonstration, so
    the page says plainly what is wrong and how to fix it.
    """

    class Broken:
        def chat(self, messages, tools=None):
            raise OllamaUnavailable(
                "unreachable", "Nothing is listening.", "ollama pull llama3.1:8b"
            )

    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", Broken()),
    )

    page = client.post("/chat", data={"message": "hello"}, follow_redirects=True)

    assert "The AI model is not available" in page.text
    assert "ollama pull llama3.1:8b" in page.text


# --- The skill store -------------------------------------------------------------


def test_the_store_shows_what_a_skill_claims_about_itself(client):
    """
    REQUIREMENT FR-2.1.

    Name, description and claimed permissions, exactly as the publisher wrote them.
    """
    text = client.get("/store").text

    assert "Task Summary" in text
    assert "task.read" in text
    assert "Reads your tasks" in text


def test_the_store_makes_the_trust_assumption_visible(client):
    """
    The caption is deliberate. A person installing a skill is trusting a claim, and
    the screen should say so rather than presenting it as verified fact.
    """
    assert "Declared by the publisher" in client.get("/store").text


def test_installing_from_the_store_works(client):
    """The button does what it says."""
    page = client.post("/store/task_summary/install", follow_redirects=True)
    assert "Remove" in page.text

    page = client.post("/store/task_summary/uninstall", follow_redirects=True)
    assert "Install" in page.text


# --- Findings --------------------------------------------------------------------


def test_an_empty_findings_page_explains_that_this_is_correct(client):
    """
    An empty list here is the app working, not a gap in it. The wording says so,
    because a security tool that can never stay quiet is worthless.
    """
    text = client.get("/findings").text

    assert "No findings" in text
    assert "behaved exactly as declared" in text


# --- Activity --------------------------------------------------------------------


def test_the_activity_page_shows_what_a_skill_touched(client, monkeypatch):
    """
    The demonstration screen. After a skill runs, its every action appears here in
    order, so a finding can be traced back to the exact moment it happened.
    """
    client.post("/store/task_summary/install")

    answers = [
        ChatResponse(content="", tool_calls=[ToolCall("task_summary", {"scope": "all"})], model="stub"),
        ChatResponse(content="You have eight things on your list.", model="stub"),
    ]

    class Stub:
        def chat(self, messages, tools=None):
            return answers.pop(0) if answers else ChatResponse(content="ok", model="stub")

    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", Stub()),
    )

    client.post("/chat", data={"message": "summarise my tasks"}, follow_redirects=True)
    text = client.get("/activity").text

    assert "summarise my tasks" in text
    assert "task_summary" in text
    # The ordered record of what it touched.
    assert "task.read" in text
    assert "What the skill touched, in order" in text


# --- The look --------------------------------------------------------------------


def test_a16_the_stylesheet_writes_no_colour_of_its_own():
    """
    ACCEPTANCE TEST A-16 and REQUIREMENT DR-1.

    Every colour used anywhere is one of the names copied from the design reference.
    If a colour value were written directly here, the app and the design could drift
    apart silently - so this check makes any drift a visible failure instead.
    """
    css = (REPO_ROOT / "frontend" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    # Ignore the explanatory comments, which naturally discuss colours.
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    stray_colours = re.findall(r"#[0-9a-fA-F]{3,8}\b", without_comments)
    stray_functions = re.findall(r"\b(?:rgb|rgba|hsl|hsla)\s*\(", without_comments)

    assert stray_colours == [], f"colours written directly in app.css: {stray_colours}"
    assert stray_functions == [], f"colour functions written directly in app.css: {stray_functions}"


def test_the_colours_were_copied_from_the_design_reference():
    """
    The token file is generated, not hand-written. Spot-checking a few values against
    the design confirms the copy actually happened.
    """
    tokens = (REPO_ROOT / "frontend" / "static" / "css" / "tokens.css").read_text(encoding="utf-8")

    for expected in ["--canvas:#08080D", "--sev-critical:#FF4D5E", "--p-default:#6B3B85"]:
        assert expected in tokens.replace(" ", "")


def test_the_typeface_is_served_from_this_machine():
    """
    REQUIREMENT DR-1 and the localhost-only principle. The pages must render with no
    internet connection at all, so nothing is fetched from elsewhere.
    """
    font = REPO_ROOT / "frontend" / "static" / "fonts" / "raleway.woff2"

    assert font.exists()
    assert font.read_bytes()[:4] == b"wOF2"

    css = (REPO_ROOT / "frontend" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "/static/fonts/raleway.woff2" in css


def test_no_page_fetches_anything_from_the_internet(client):
    """
    Nothing is loaded from anywhere else - no fonts, no scripts, no stylesheets. The
    app works fully offline, which matters for a tool that is only ever run locally.
    """
    for path in ["/", "/store", "/findings", "/activity"]:
        text = client.get(path).text
        assert "http://" not in text.replace("http://127.0.0.1", "")
        assert "https://" not in text


def test_severity_badges_never_rely_on_colour_alone():
    """
    REQUIREMENT DR-4.

    Every badge carries its severity word and its risk identifier, so the meaning
    survives for anyone who cannot distinguish the colours.
    """
    badge = (REPO_ROOT / "frontend" / "templates" / "partials" / "_severity_badge.html").read_text(
        encoding="utf-8"
    )

    assert "finding.severity" in badge
    assert "finding.ast_id" in badge
