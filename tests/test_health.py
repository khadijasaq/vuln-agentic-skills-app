"""
Checks for the health endpoint and that the app starts at all.

The health endpoint is how a person or a script asks "is TaskBot up, and what is it?".
One of its fields is permanent and deliberate: intentionally_vulnerable is always
true. It is one of the ways this app announces that it is a practice target, so
nobody can mistake it for an ordinary application.

Covers: feature spec section 11.3, acceptance test A-1 (in part), requirement FR-7.6.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_settings):
    """A test client wired to an app using the throwaway data folder."""
    return TestClient(create_app())


def test_the_app_starts_and_health_responds(client):
    """The most basic check there is: the app boots and answers."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_always_says_the_app_is_intentionally_vulnerable(client):
    """
    REQUIREMENT FR-7.6.

    This field is permanent. Anything reading TaskBot automatically can use it to
    confirm what it is talking to before doing anything else.
    """
    assert client.get("/api/health").json()["intentionally_vulnerable"] is True


def test_health_carries_a_schema_version(client):
    """
    Every API answer says which format it is in, so programs reading TaskBot can
    tell whether they understand it (requirement FR-6.3).
    """
    assert client.get("/api/health").json()["schema_version"] == 1


def test_health_reports_the_configured_model(client, tmp_settings):
    """
    Which AI model is in charge is part of the evidence trail, so it is visible from
    the very first endpoint.
    """
    assert client.get("/api/health").json()["model"] == tmp_settings.model


def test_health_includes_the_blocks_the_specification_promises(client):
    """
    The shape is a promise to the tools that read it. The values inside the ollama
    and counts blocks are filled in properly later in the build; the shape must be
    right from the start.
    """
    payload = client.get("/api/health").json()

    assert set(payload["llm"]) == {"reachable", "model_present", "url"}
    assert set(payload["counts"]) == {
        "skills",
        "installed",
        "tasks",
        "findings",
        "activity",
    }
