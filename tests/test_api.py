"""
Checks for the JSON API - the addresses other programs talk to.

These are contract checks. A scanning tool built against these shapes must keep
working, so the important thing here is not just "does it answer" but "does it
answer in exactly the promised shape".

Covers: feature spec section 11; TDD section 7; requirements FR-6.1 to FR-6.4;
acceptance tests A-1, A-10, A-14 and A-17.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.llm.ollama_client import ChatResponse, OllamaUnavailable, ToolCall
from app.main import create_app
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import store


@pytest.fixture
def client(tmp_settings):
    """A test client wired to an app using a throwaway data folder."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    yield TestClient(create_app())
    registry_module.reset_registry()
    host_module.clear_module_cache()


@pytest.fixture
def scripted_model(monkeypatch):
    """
    Replace the AI model with a scripted stand-in.

    In: nothing. Out: a function a test calls to set what the model will answer.
    """

    def use(*answers):
        answers = list(answers)

        class Stub:
            def chat(self, messages, tools=None):
                return answers.pop(0) if answers else ChatResponse(content="ok", model="stub")

        monkeypatch.setattr(
            "app.chat.orchestrator.ChatOrchestrator.__init__",
            lambda self, client=None: setattr(self, "_client", Stub()),
        )

    return use


# --- Health ----------------------------------------------------------------------


def test_a1_health_answers(client):
    """ACCEPTANCE TEST A-1 (in part): the app is up."""
    payload = client.get("/api/health").json()

    assert payload["status"] == "ok"
    assert payload["schema_version"] == 1


def test_health_always_announces_what_this_app_is(client):
    """
    REQUIREMENT FR-7.6. A permanent flag, so anything reading TaskBot automatically
    can confirm what it is talking to before doing anything else.
    """
    assert client.get("/api/health").json()["intentionally_vulnerable"] is True


def test_health_counts_what_is_in_the_lab(client):
    """The counts let a tool check the state of the lab in one request."""
    counts = client.get("/api/health").json()["counts"]

    assert counts["skills"] >= 1
    assert counts["installed"] == 0
    assert counts["tasks"] == 8
    assert counts["findings"] == 0


# --- The skill store -------------------------------------------------------------


def test_listing_skills_shows_what_they_claim(client):
    """
    The permissions listed are what the skill CLAIMS. They are shown as written,
    unverified - which is the honest representation of a claim.
    """
    payload = client.get("/api/skills").json()

    assert payload["schema_version"] == 1
    skills = {skill["id"]: skill for skill in payload["skills"]}
    assert "task_summary" in skills
    assert skills["task_summary"]["installed"] is False
    assert skills["task_summary"]["declared_capabilities"][0]["id"] == "task.read"


def test_one_skill_can_be_read_in_full(client):
    """Everything a skill says about itself, verbatim."""
    payload = client.get("/api/skills/task_summary").json()

    assert payload["manifest"]["id"] == "task_summary"
    assert payload["manifest"]["invocation"]["when_to_use"]


def test_asking_for_a_missing_skill_gives_a_clear_code(client):
    """Programs branch on the short code, never on the wording."""
    response = client.get("/api/skills/no_such_skill")

    assert response.status_code == 404
    assert response.json()["error"] == "skill_not_found"


def test_installing_and_removing_a_skill(client):
    """Both work, and both report the new state."""
    installed = client.post("/api/skills/task_summary/install").json()
    assert installed["installed"] is True

    removed = client.post("/api/skills/task_summary/uninstall").json()
    assert removed["installed"] is False


def test_installing_reports_problems_visible_before_it_ever_runs(client):
    """
    Some problems can be spotted from the description alone - a skill asking for far
    more power than its kind needs, for instance. The honest control skill has none.
    """
    payload = client.post("/api/skills/task_summary/install").json()

    assert payload["findings_raised"] == []


def test_a10_there_is_no_way_to_upload_a_skill(client):
    """
    ACCEPTANCE TEST A-10.

    Letting people upload their own skills was deliberately left out for now, so
    that surface must genuinely not exist.
    """
    assert client.post("/api/skills/upload").status_code in (404, 405)


# --- Talking to the assistant ----------------------------------------------------


def test_chat_answers_in_the_promised_shape(client, scripted_model):
    """The exact shape a scanning tool is built against."""
    scripted_model(ChatResponse(content="All good.", model="stub"))

    payload = client.post("/api/chat", json={"message": "how are things?"}).json()

    assert set(payload) == {
        "schema_version",
        "reply",
        "activity_id",
        "skill_invoked",
        "findings_raised",
        "llm",
    }
    assert payload["reply"] == "All good."
    assert payload["skill_invoked"] is None


def test_chat_reports_which_skill_ran(client, scripted_model):
    """So a tool can attribute what happened to the right skill."""
    client.post("/api/skills/task_summary/install")
    scripted_model(
        ChatResponse(content="", tool_calls=[ToolCall("task_summary", {"scope": "all"})], model="stub"),
        ChatResponse(content="You have eight things.", model="stub"),
    )

    payload = client.post("/api/chat", json={"message": "summarise"}).json()

    assert payload["skill_invoked"]["skill_id"] == "task_summary"
    assert payload["skill_invoked"]["outcome"] == "ok"
    assert payload["llm"]["tool_call"] is True


def test_a17_the_model_is_recorded_as_evidence(client, scripted_model):
    """
    ACCEPTANCE TEST A-17.

    "The assistant chose to do this" only means something if you know which
    assistant, so the model is part of every record.
    """
    scripted_model(ChatResponse(content="Fine.", model="llama3.1:8b"))

    payload = client.post("/api/chat", json={"message": "hello"}).json()
    assert payload["llm"]["model"] == "llama3.1:8b"

    entries = client.get("/api/activity").json()["activity"]
    assert entries[-1]["model"] == "llama3.1:8b"


def test_findings_from_this_exchange_only(client, scripted_model):
    """
    The per-exchange list lets a tool attribute a problem to the exact message that
    caused it, without comparing the whole findings list before and after.
    """
    client.post("/api/skills/task_summary/install")
    scripted_model(
        ChatResponse(content="", tool_calls=[ToolCall("task_summary", {})], model="stub"),
        ChatResponse(content="Done.", model="stub"),
    )

    payload = client.post("/api/chat", json={"message": "summarise"}).json()

    # The honest skill raises nothing, which is the correct answer here.
    assert payload["findings_raised"] == []


def test_an_empty_message_is_refused_clearly(client):
    """A missing message is a caller mistake, reported as one."""
    response = client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_a12_an_unavailable_model_is_reported_with_the_fix(client, monkeypatch):
    """
    ACCEPTANCE TEST A-12.

    No canned reply. The caller is told exactly what is wrong and how to fix it.
    """

    class Broken:
        def chat(self, messages, tools=None):
            raise OllamaUnavailable("unreachable", "Nothing is listening.", "ollama serve")

    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", Broken()),
    )

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"] == "llm_unavailable"
    assert payload["remedy"] == "ollama serve"


def test_a12_the_read_only_pages_still_work_without_a_model(client):
    """A missing model must not take the whole lab down."""
    for path in ["/api/skills", "/api/findings", "/api/activity", "/api/health"]:
        assert client.get(path).status_code == 200


# --- Reading what happened -------------------------------------------------------


def test_findings_and_activity_start_empty(client):
    assert client.get("/api/findings").json()["count"] == 0
    assert client.get("/api/activity").json()["count"] == 0


def test_activity_can_be_filtered(client, scripted_model):
    """Filters let a tool narrow down without downloading everything."""
    scripted_model(
        ChatResponse(content="one", model="stub"),
        ChatResponse(content="two", model="stub"),
    )
    client.post("/api/chat", json={"message": "first"})
    client.post("/api/chat", json={"message": "second"})

    assert client.get("/api/activity?limit=1").json()["count"] == 1


def test_findings_can_be_filtered(client):
    """Every documented filter is accepted, even when nothing matches."""
    for query in ["skill_id=x", "ast_id=AST04", "severity=high", "since=2020-01-01T00:00:00.000Z"]:
        assert client.get(f"/api/findings?{query}").status_code == 200


# --- Starting over ---------------------------------------------------------------


def test_a14_reset_clears_what_was_observed(client, scripted_model):
    """ACCEPTANCE TEST A-14, first part."""
    scripted_model(ChatResponse(content="noted", model="stub"))
    client.post("/api/chat", json={"message": "hello"})
    assert client.get("/api/activity").json()["count"] == 1

    payload = client.post("/api/reset").json()

    assert payload["cleared"]["activity"] == 1
    assert client.get("/api/activity").json()["count"] == 0


def test_a14_reset_keeps_installed_skills(client):
    """
    ACCEPTANCE TEST A-14, second part.

    A demonstration should not have to reinstall everything after each reset.
    """
    client.post("/api/skills/task_summary/install")

    payload = client.post("/api/reset").json()

    assert payload["installed_preserved"] == ["task_summary"]
    assert client.get("/api/skills/task_summary").json()["installed"] is True


def test_a14_reset_puts_the_starter_tasks_back(client):
    """A fresh, believable task list for the next run through."""
    store.save_tasks([])

    payload = client.post("/api/reset").json()

    assert payload["tasks_reseeded"] == 8
    assert len(store.load_tasks()) == 8


def test_a14_reset_says_plainly_that_it_is_not_a_security_switch(client):
    """
    ACCEPTANCE TEST A-14 and NON-GOAL NG3.

    Reset makes the app forget what it saw. It cannot make the app less vulnerable,
    and the answer says so, so nobody can mistake it for a safety control.
    """
    payload = client.post("/api/reset").json()

    assert "cannot make the app less vulnerable" in payload["note"]


def test_a14_reset_changes_no_skill_behaviour(client, scripted_model):
    """
    The proof behind that claim: the same skill run before and after a reset behaves
    identically and produces the same result.
    """
    client.post("/api/skills/task_summary/install")

    scripted_model(
        ChatResponse(content="", tool_calls=[ToolCall("task_summary", {})], model="stub"),
        ChatResponse(content="Before.", model="stub"),
        ChatResponse(content="", tool_calls=[ToolCall("task_summary", {})], model="stub"),
        ChatResponse(content="After.", model="stub"),
    )

    before = client.post("/api/chat", json={"message": "summarise"}).json()
    client.post("/api/reset")
    after = client.post("/api/chat", json={"message": "summarise"}).json()

    assert before["skill_invoked"]["skill_id"] == after["skill_invoked"]["skill_id"]
    assert before["findings_raised"] == after["findings_raised"]


# --- The pretend outside world ---------------------------------------------------


def test_the_mock_collector_accepts_and_files_a_delivery(client, tmp_settings):
    """
    REQUIREMENT FR-7.2.

    Nothing in this feature sends anything here. It is built and tested now so the
    safety promise is real and proven before anything relies on it.
    """
    response = client.post("/mock/collector", json={"stolen": "tasks"})

    assert response.status_code == 202
    assert response.json() == {"received": True}

    delivered = list((tmp_settings.collector_dir / "inbox").iterdir())
    assert len(delivered) == 1


# --- The contract itself ---------------------------------------------------------


def test_a10_every_answer_carries_a_schema_version(client):
    """
    ACCEPTANCE TEST A-10.

    The version number is how a tool knows whether it understands the answer. It has
    to be on every single response, without exception.
    """
    for path in ["/api/health", "/api/skills", "/api/skills/task_summary", "/api/findings", "/api/activity"]:
        assert client.get(path).json()["schema_version"] == 1

    assert client.post("/api/reset").json()["schema_version"] == 1
    assert client.post("/api/skills/task_summary/install").json()["schema_version"] == 1


def test_a10_failures_all_look_the_same(client):
    """One shape for every failure, so callers need only one way of reading them."""
    response = client.get("/api/skills/does_not_exist")
    payload = response.json()

    assert set(payload) >= {"schema_version", "error", "detail"}
    assert isinstance(payload["error"], str)
    assert isinstance(payload["detail"], str)


def test_there_is_no_login(client):
    """
    A practice target that only ever listens on this computer. Adding accounts would
    wrongly suggest it was safe to expose.
    """
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/findings").status_code == 200
