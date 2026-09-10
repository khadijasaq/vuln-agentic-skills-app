"""
Checks for the team Dashboard feature.

The Dashboard shows the honest standup lines a skill posts. Its whole reason for being
careful is the malicious skill next door: Standup Sync posts a short standup line AND,
separately, steals the full task list to the collector. The dashboard must show the
first and never the second.

The most important test here is the leak-proof one: a stolen-task "backup" payload
posted to the dashboard endpoint stores NOTHING and shows NOTHING. The dashboard reads
only its own store, and that store can only ever hold a short standup line - so the
theft cannot appear here, by construction rather than by a filter that could regress.

Covers: the dashboard feature and safety rule FR-7.
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
    """A test client wired to an app using a throwaway data folder."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    yield TestClient(create_app())
    registry_module.reset_registry()
    host_module.clear_module_cache()


# --- The honest path: a standup is stored and shown ------------------------------


def test_a_posted_standup_is_stored_and_appears_on_the_dashboard(client):
    """Posting a standup line stores it and shows it on the Dashboard screen."""
    posted = client.post(
        "/mock/dashboard",
        json={"message": "Standup: 2 tasks open. Longest outstanding: 'Ship it'.", "open": 2, "oldest": "Ship it"},
    )
    assert posted.status_code == 202
    assert posted.json() == {"stored": True}

    standups = store.load_standups()
    assert len(standups) == 1
    assert standups[0].message == "Standup: 2 tasks open. Longest outstanding: 'Ship it'."
    assert standups[0].open_count == 2
    assert standups[0].oldest == "Ship it"

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Standup: 2 tasks open" in page.text


def test_an_empty_dashboard_shows_a_friendly_empty_state(client):
    """With no standups posted, the screen explains itself rather than looking broken."""
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "No standups yet" in page.text


# --- The leak-proof guarantee: the theft can never reach the dashboard -----------


def test_a_stolen_task_backup_posted_here_stores_and_shows_nothing(client):
    """
    THE LEAK-PROOF TEST. A covert full-task "backup" payload - the exact shape Standup
    Sync sends to the collector - is posted straight to the dashboard endpoint. It must
    store nothing (it has no standup line) and none of the stolen titles may appear on
    the screen.
    """
    stolen = {
        "kind": "backup",
        "items": [
            {"id": "tsk_1", "title": "Acquire rival company", "notes": "strictly confidential"},
            {"id": "tsk_2", "title": "Board briefing", "notes": "do not leak"},
        ],
    }
    response = client.post("/mock/dashboard", json=stolen)
    assert response.status_code == 202
    assert response.json() == {"stored": False}

    # Nothing was stored...
    assert store.load_standups() == []

    # ...and none of the stolen task titles can appear on the screen.
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Acquire rival company" not in page.text
    assert "Board briefing" not in page.text
    assert "No standups yet" in page.text


def test_only_the_three_standup_fields_are_kept(client):
    """
    Even alongside a valid standup line, any extra fields - especially a task list - are
    dropped on the way in. The stored record has no place to hold them, so the theft has
    nowhere to hide.
    """
    client.post(
        "/mock/dashboard",
        json={
            "message": "Standup: 3 tasks open.",
            "open": 3,
            "oldest": "Write the report",
            "items": [{"title": "leak me", "notes": "secret"}],  # must be ignored
            "secret": "do not store",  # must be ignored
        },
    )

    standups = store.load_standups()
    assert len(standups) == 1
    dumped = standups[0].model_dump()

    assert dumped["message"] == "Standup: 3 tasks open."
    assert dumped["open_count"] == 3
    assert dumped["oldest"] == "Write the report"
    # There is no field that could carry the leaked task or the secret.
    assert "items" not in dumped
    assert "secret" not in dumped
    assert "leak me" not in str(dumped)


def test_a_wrong_typed_payload_is_stored_safely_without_crashing(client):
    """A payload with odd types (a list where a count was expected) falls back to safe
    defaults rather than crashing - and still never carries task contents."""
    client.post(
        "/mock/dashboard",
        json={"message": "Standup: unknown.", "open": ["not", "a", "number"], "oldest": {"nested": "object"}},
    )
    standups = store.load_standups()
    assert len(standups) == 1
    assert standups[0].open_count == 0
    assert standups[0].oldest == ""


# --- Reset clears the dashboard too ----------------------------------------------


def test_reset_clears_the_dashboard(client):
    """A reset wipes the posted standups along with everything else, and reports how
    many it cleared - so the lab returns to a clean slate."""
    client.post("/mock/dashboard", json={"message": "Standup: 1 task open.", "open": 1, "oldest": "x"})
    assert len(store.load_standups()) == 1

    summary = client.post("/api/reset").json()
    assert summary["cleared"]["standups"] == 1

    assert store.load_standups() == []
    assert "No standups yet" in client.get("/dashboard").text
