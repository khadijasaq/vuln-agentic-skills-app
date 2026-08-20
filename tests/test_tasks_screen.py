"""
Checks for the task list screen.

This screen is the thing TaskBot is actually for: seeing your to-do list, adding to
it, ticking things off, removing them.

The security-relevant checks are at the bottom. Managing your own tasks is the app
doing its own advertised job, not a skill being supervised - so it must produce no
observations and no findings. If it did, a brand new lab would look like it had
already found problems, and the clean baseline the whole exercise depends on would
be gone.

It also has to keep working when the AI model is missing or still loading. That
matters beyond convenience: the task list is what a later malicious skill will try
to steal, and a person needs to be able to see what was taken.

Covers: feature spec section 12; requirement FR-1.1; non-goal NG4; decision S-37.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import store


@pytest.fixture
def client(tmp_settings):
    registry_module.reset_registry()
    host_module.clear_module_cache()
    yield TestClient(create_app())
    registry_module.reset_registry()
    host_module.clear_module_cache()


# --- Seeing the list -------------------------------------------------------------


def test_the_task_screen_shows_every_task(client):
    """The starter list appears in full."""
    page = client.get("/tasks")

    assert page.status_code == 200
    for task in store.load_tasks():
        assert task.title in page.text


def test_the_task_screen_counts_what_is_left(client):
    """A person should see at a glance how much is outstanding."""
    text = client.get("/tasks").text

    assert "5 still to do" in text
    assert "3 finished" in text


def test_unfinished_tasks_come_first(client):
    """
    The outstanding items are what a person needs to look at, so they go at the top.
    Within each group the oldest is first, so the longest-waiting thing leads.
    """
    text = client.get("/tasks").text

    tasks = store.load_tasks()
    first_open = min(
        (task for task in tasks if not task.done), key=lambda task: task.created_at
    )
    a_finished_one = next(task for task in tasks if task.done)

    assert text.index(first_open.title) < text.index(a_finished_one.title)


def test_the_task_screen_is_reachable_from_every_page(client):
    """It is part of the main navigation, not hidden away."""
    for path in ["/", "/store", "/findings", "/activity", "/tasks"]:
        assert 'href="/tasks"' in client.get(path).text


def test_an_empty_list_says_so_kindly(client):
    """An empty list is a normal state, and the screen suggests what to do next."""
    store.save_tasks([])

    text = client.get("/tasks").text

    assert "Your list is empty" in text


# --- Adding ----------------------------------------------------------------------


def test_adding_a_task(client):
    """The add box does what it says."""
    page = client.post("/tasks/add", data={"title": "Buy milk"}, follow_redirects=True)

    assert "Buy milk" in page.text
    assert any(task.title == "Buy milk" for task in store.load_tasks())


def test_adding_a_task_with_notes(client):
    """Optional extra detail is kept and shown."""
    client.post(
        "/tasks/add",
        data={"title": "Call the bank", "notes": "ask about the fee"},
        follow_redirects=True,
    )

    saved = [task for task in store.load_tasks() if task.title == "Call the bank"]
    assert saved[0].notes == "ask about the fee"


def test_adding_a_blank_task_is_quietly_ignored(client):
    """
    Nothing was lost and nothing is wrong, so there is nothing to interrupt the
    person about.
    """
    before = len(store.load_tasks())

    client.post("/tasks/add", data={"title": "   "}, follow_redirects=True)

    assert len(store.load_tasks()) == before


# --- Ticking off -----------------------------------------------------------------


def test_ticking_a_task_marks_it_done(client):
    """One click, and it records when it was finished."""
    task = [t for t in store.load_tasks() if not t.done][0]

    client.post(f"/tasks/{task.id}/toggle", follow_redirects=True)

    updated = [t for t in store.load_tasks() if t.id == task.id][0]
    assert updated.done is True
    assert updated.completed_at is not None


def test_ticking_a_finished_task_un_finishes_it(client):
    """
    The same button flips it back, so a mistake takes one click to undo. The
    completion time is cleared too - the record must not claim a finish that was
    undone.
    """
    task = [t for t in store.load_tasks() if t.done][0]

    client.post(f"/tasks/{task.id}/toggle", follow_redirects=True)

    updated = [t for t in store.load_tasks() if t.id == task.id][0]
    assert updated.done is False
    assert updated.completed_at is None


def test_ticking_a_task_that_has_gone_is_harmless(client):
    """
    Someone may have removed it in another tab. Nothing to do, and nothing worth
    showing an error about.
    """
    page = client.post("/tasks/tsk_does_not_exist/toggle", follow_redirects=True)

    assert page.status_code == 200


# --- Removing --------------------------------------------------------------------


def test_removing_a_task(client):
    """It goes, and the rest are untouched."""
    task = store.load_tasks()[0]
    before = len(store.load_tasks())

    page = client.post(f"/tasks/{task.id}/delete", follow_redirects=True)

    assert task.title not in page.text
    assert len(store.load_tasks()) == before - 1


def test_removing_a_task_that_has_gone_is_harmless(client):
    page = client.post("/tasks/tsk_does_not_exist/delete", follow_redirects=True)

    assert page.status_code == 200


# --- The part that matters for security ------------------------------------------


def test_managing_tasks_records_nothing_and_reports_nothing(client):
    """
    THE KEY CHECK (non-goal NG4).

    Adding, ticking and removing your own tasks is the app doing its own advertised
    job, not a skill under supervision. After doing all three there must be no
    findings and no activity recorded.

    If this ever failed, a brand new lab would appear to have already found security
    problems, and the clean baseline the whole exercise rests on would be gone.
    """
    client.post("/tasks/add", data={"title": "Something new"}, follow_redirects=True)
    task = [t for t in store.load_tasks() if t.title == "Something new"][0]
    client.post(f"/tasks/{task.id}/toggle", follow_redirects=True)
    client.post(f"/tasks/{task.id}/delete", follow_redirects=True)

    assert store.load_findings() == []
    assert store.load_activity() == []


def test_the_task_screen_works_without_the_ai_model(client):
    """
    No model is involved on this screen at all.

    That matters beyond convenience: the task list is what a later malicious skill
    will try to steal, and a person needs to be able to see what was taken - even
    while the model is missing or still loading.
    """
    # The lab has no working model in these tests, yet all of this works.
    assert client.get("/tasks").status_code == 200
    assert client.post("/tasks/add", data={"title": "No model needed"}, follow_redirects=True).status_code == 200
    assert any(task.title == "No model needed" for task in store.load_tasks())


def test_the_task_routes_never_touch_the_capability_broker():
    """
    Checked by reading the source. These routes reach storage directly, exactly as
    the built-in abilities do.
    """
    from pathlib import Path

    from tests.source_tools import executable_source

    code = executable_source(
        Path(__file__).resolve().parents[1] / "app" / "web" / "routes.py"
    )

    assert "SkillContext" not in code
    assert "ObservationLog" not in code
    assert "invocation_scope" not in code
