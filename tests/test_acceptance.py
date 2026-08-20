"""
The acceptance checks: does the finished foundation do what was promised?

Every other test file checks one piece in isolation. This one walks the whole
product the way a reviewer would, end to end, and confirms the promises that were
agreed before any code was written.

The single most important promise is the quiet one: with an honest skill installed,
the app finds nothing. A security tool that cannot stay silent cannot be trusted when
it speaks.

Covers: feature spec section 15 (acceptance tests A-1 to A-18).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm.ollama_client import ChatResponse, ToolCall
from app.main import create_app
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import store

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def lab(tmp_settings, monkeypatch):
    """
    A complete running lab with a scripted AI model.

    In: nothing. Out: a pair - the web client, and a function to script what the
    model will say next.
    """
    registry_module.reset_registry()
    host_module.clear_module_cache()

    answers: list[ChatResponse] = []

    class Stub:
        def chat(self, messages, tools=None):
            return answers.pop(0) if answers else ChatResponse(content="Right you are.", model="llama3.1:8b")

    monkeypatch.setattr(
        "app.chat.orchestrator.ChatOrchestrator.__init__",
        lambda self, client=None: setattr(self, "_client", Stub()),
    )

    client = TestClient(create_app())

    def script(*responses):
        answers.clear()
        answers.extend(responses)

    yield client, script

    registry_module.reset_registry()
    host_module.clear_module_cache()


# --- A-1: it runs ----------------------------------------------------------------


def test_a1_the_app_starts_and_reports_itself(lab):
    """ACCEPTANCE TEST A-1: a clean checkout starts and answers."""
    client, _ = lab

    assert client.get("/").status_code == 200

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["intentionally_vulnerable"] is True


# --- A-2 and A-7: the safe baseline ----------------------------------------------


def test_a2_the_assistant_works_with_nothing_installed(lab):
    """
    ACCEPTANCE TEST A-2.

    Before any skill exists, TaskBot is already a complete, working to-do assistant.
    That is the non-vulnerable baseline everything else is measured against.
    """
    client, script = lab
    assert client.get("/api/health").json()["counts"]["installed"] == 0

    script(
        ChatResponse(content="", tool_calls=[ToolCall("add_task", {"title": "Book the dentist"})], model="llama3.1:8b"),
        ChatResponse(content="Added it.", model="llama3.1:8b"),
    )
    client.post("/api/chat", json={"message": "remind me to book the dentist"})

    assert any(task.title == "Book the dentist" for task in store.load_tasks())


def test_a7_nothing_can_be_exercised_with_nothing_installed(lab):
    """
    ACCEPTANCE TEST A-7 (amended wording, build plan O-1).

    With nothing installed, the only things offered are the app's own two built-in
    abilities. No skill runs, nothing is watched, and no problem can be reported.
    """
    from app.chat.orchestrator import build_tool_list

    client, script = lab

    assert sorted(tool["function"]["name"] for tool in build_tool_list()) == [
        "add_task",
        "list_tasks",
    ]

    script(ChatResponse(content="Nothing to do.", model="llama3.1:8b"))
    payload = client.post("/api/chat", json={"message": "run every skill you have"}).json()

    assert payload["skill_invoked"] is None
    assert payload["findings_raised"] == []
    assert client.get("/api/findings").json()["count"] == 0


# --- A-4: the honest skill is met with silence -----------------------------------


def test_a4_an_honest_skill_produces_no_findings_over_many_runs(lab):
    """
    ACCEPTANCE TEST A-4 - the headline promise.

    Twenty full exchanges through the real path. Nothing found, nothing recorded as
    evidence, no exchange flagged.
    """
    client, script = lab
    client.post("/api/skills/task_summary/install")

    for _ in range(20):
        script(
            ChatResponse(content="", tool_calls=[ToolCall("task_summary", {"scope": "all"})], model="llama3.1:8b"),
            ChatResponse(content="Steady progress.", model="llama3.1:8b"),
        )
        payload = client.post("/api/chat", json={"message": "how am I doing?"}).json()
        assert payload["skill_invoked"]["outcome"] == "ok"
        assert payload["findings_raised"] == []

    assert client.get("/api/findings").json()["count"] == 0

    from app.findings.markers import count_markers

    assert count_markers() == 0


# --- A-13: the whole story, followable -------------------------------------------


def test_a13_install_ask_and_see_the_record(lab):
    """
    ACCEPTANCE TEST A-13.

    The demonstration a reviewer follows unaided: install a skill, ask something
    ordinary, watch the assistant choose it, and find the record of what it touched.
    """
    client, script = lab

    # 1. The store shows the skill and what it claims about itself.
    store_page = client.get("/store").text
    assert "Task Summary" in store_page
    assert "Declared by the publisher" in store_page

    # 2. Install it.
    client.post("/store/task_summary/install", follow_redirects=True)

    # 3. Ask something completely ordinary.
    script(
        ChatResponse(content="", tool_calls=[ToolCall("task_summary", {"scope": "all"})], model="llama3.1:8b"),
        ChatResponse(content="You have eight things, three done.", model="llama3.1:8b"),
    )
    client.post("/chat", data={"message": "how am I doing?"}, follow_redirects=True)

    # 4. The activity screen shows which skill handled it and everything it touched.
    activity = client.get("/activity").text
    assert "how am I doing?" in activity
    assert "task_summary" in activity
    assert "task.read" in activity

    # 5. And the findings screen is properly, meaningfully empty.
    assert "behaved exactly as declared" in client.get("/findings").text


# --- A-11: the safety catches ----------------------------------------------------


def test_a11_the_app_refuses_to_listen_beyond_this_machine():
    """
    ACCEPTANCE TEST A-11, first half.

    A knowingly insecure app must be incapable of being exposed to a network by a
    configuration mistake. It refuses to start rather than allow it.
    """
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import load_settings; load_settings()"],
        cwd=REPO_ROOT,
        env={"TASKBOT_HOST": "0.0.0.0", "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "0.0.0.0" in result.stderr


def test_a11_deleting_the_data_folder_resets_everything(lab, tmp_settings):
    """
    ACCEPTANCE TEST A-11, second half.

    Everything the lab remembers lives in one folder. Deleting it starts over
    completely, which is the simplest possible reset.
    """
    import shutil

    client, script = lab
    script(ChatResponse(content="noted", model="llama3.1:8b"))
    client.post("/api/chat", json={"message": "hello"})
    client.post("/api/skills/task_summary/install")

    assert tmp_settings.data_dir.exists()
    shutil.rmtree(tmp_settings.data_dir)

    # A fresh app starts cleanly from nothing.
    registry_module.reset_registry()
    fresh = TestClient(create_app())
    health = fresh.get("/api/health").json()

    assert health["status"] == "ok"
    assert health["counts"]["activity"] == 0
    assert health["counts"]["installed"] == 0
    assert health["counts"]["tasks"] == 8


# --- The safety envelope holds ---------------------------------------------------


def test_a5_nothing_escapes_the_boundaries(lab, tmp_settings, tmp_path):
    """
    ACCEPTANCE TEST A-8, gathered in one place.

    A skill cannot reach outside the app's folders, cannot contact anywhere but this
    machine, and cannot erase the records of what it did. Every refused attempt is
    still written down.
    """
    from app.monitor import audit_hook
    from app.monitor.observations import ObservationLog
    from app.skills.context import CapabilityRefused, SkillContext

    notebook = ObservationLog("inv_acceptance")
    context = SkillContext("inv_acceptance", notebook)

    attempts = [
        (context.files.read, (str(tmp_path / "outside.txt"),), "path_outside_allowed_roots"),
        (context.net.post, ("https://evil.example.com/steal",), "non_local_host"),
        (context.files.write, (str(tmp_settings.findings_file), "erased"), "protected_state_file"),
        (context.env.get, ("AWS_SECRET_ACCESS_KEY",), "key_not_exposed"),
    ]

    with audit_hook.invocation_scope("inv_acceptance", notebook):
        for call, arguments, expected_reason in attempts:
            with pytest.raises(CapabilityRefused) as refusal:
                call(*arguments)
            assert refusal.value.reason == expected_reason

    # All four were blocked - and all four are on the record.
    assert len(notebook.entries()) == 4
    assert all(entry.outcome == "refused" for entry in notebook.entries())


def test_no_setting_anywhere_can_make_the_app_less_vulnerable(lab):
    """
    NON-GOAL NG3.

    There is deliberately no difficulty switch, no safe mode and no patched version.
    Reset is the only control that touches the lab's state, and it only makes the app
    forget - it changes nothing about how the app behaves.
    """
    client, _ = lab

    note = client.post("/api/reset").json()["note"]
    assert "cannot make the app less vulnerable" in note

    # And there is no other endpoint offering anything of the kind. Not every entry
    # in the route list is a plain address, so anything without one is skipped.
    paths = [getattr(route, "path", "") for route in create_app().routes]
    for suspicious in ["/api/safe-mode", "/api/difficulty", "/api/disable", "/api/patch"]:
        assert suspicious not in paths


# --- The evidence trail ----------------------------------------------------------


def test_a17_every_record_names_the_model_that_was_in_charge(lab):
    """
    ACCEPTANCE TEST A-17.

    "The assistant chose to run this" only means something if you know which
    assistant. The model is part of every record.
    """
    client, script = lab
    script(ChatResponse(content="Fine.", model="llama3.1:8b"))
    client.post("/api/chat", json={"message": "hello"})

    entries = client.get("/api/activity").json()["activity"]
    assert entries[-1]["model"] == "llama3.1:8b"


def test_the_project_ships_no_vulnerable_skill_yet():
    """
    This piece of work is the foundation only. The three deliberately flawed skills
    belong to separate pieces of work, and none of them exists yet.
    """
    catalogue = REPO_ROOT / "skills" / "catalogue"
    shipped = sorted(path.name for path in catalogue.iterdir() if path.is_dir())

    assert shipped == ["task_summary"]


def test_the_readme_warns_what_this_is():
    """
    REQUIREMENT FR-7.6.

    Anyone who opens the repository should learn immediately what they are looking
    at, before they run anything.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()

    assert "intentionally vulnerable" in readme
    assert "local" in readme
