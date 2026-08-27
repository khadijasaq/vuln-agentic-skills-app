"""
The mock team hub: the first place in the app a skill can fetch something FROM.

The collector and the dashboard both only ever receive. This one hands a document over,
which is what makes it possible to show a skill being told what to do at run time.

What is checked here is mostly that it is boring: it serves a file, it does not judge what
is in that file, and it does not fall over when the file is missing or broken. A hub that
started checking its own document would quietly remove the weakness.

Specification references: feature spec sections 4.1-4.3, S-8.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def client(tmp_settings) -> TestClient:
    """A test client over a freshly built app, using the isolated data folder."""
    return TestClient(create_app())


def test_the_hub_serves_the_document_that_ships_with_the_weakness(tmp_settings):
    """
    A brand new lab has a hub with the weakness's own document already in it.

    Startup copies it in, so a person can install the skill and see the whole thing happen
    without first having to find and place a file.
    """
    response = client(tmp_settings).get("/mock/hub/rules")

    assert response.status_code == 200
    document = response.json()

    assert document["team"] == "Platform"
    assert document["rules"], "the honest half of the document is missing"
    # The two injected instructions are present, because this document IS the attack.
    assert document["report_to"]
    assert document["notice"]


def test_the_hub_serves_whatever_is_in_the_file_without_judging_it(tmp_settings):
    """
    Editing the file changes what a skill is told. No code change, no restart of anything.

    This is the property that makes the weakness worth demonstrating: the dangerous part
    is content, and content can change under a skill that nobody has touched.
    """
    application = client(tmp_settings)

    replacement = {"version": "test", "rules": [], "report_to": "anywhere-at-all"}
    path = get_settings().hub_dir / "rules.json"
    path.write_text(json.dumps(replacement), encoding="utf-8")

    served = application.get("/mock/hub/rules").json()

    assert served == replacement, "the hub changed or filtered what it was given"


def test_a_missing_document_is_answered_plainly(tmp_settings):
    """
    A hub with nothing in it says so, rather than looking like the app has broken.

    The skill treats this as "no team hub today" and carries on with its own defaults, so
    the lab still works.
    """
    application = client(tmp_settings)
    (get_settings().hub_dir / "rules.json").unlink()

    response = application.get("/mock/hub/rules")

    assert response.status_code == 404
    assert response.json()["error"] == "no_rules_document"


def test_a_broken_document_says_so_clearly(tmp_settings):
    """
    People are meant to edit this file, so a typo in it must read as a typo.

    A stack trace would send someone hunting through the app for a fault that is in their
    own one-line edit.
    """
    application = client(tmp_settings)
    (get_settings().hub_dir / "rules.json").write_text("{ not json at all", encoding="utf-8")

    response = application.get("/mock/hub/rules")

    assert response.status_code == 500
    assert response.json()["error"] == "unreadable_rules_document"


def test_the_hub_records_nothing_and_reports_nothing(tmp_settings):
    """
    The hub is a postbox, not a witness.

    Noticing that a skill acted on what it fetched is the findings engine's job. If the
    hub reported anything itself, the evidence would come from the attacker's own side of
    the fence, which is worth nothing.
    """
    from app.storage import store

    application = client(tmp_settings)
    application.get("/mock/hub/rules")
    application.get("/mock/hub/health")

    assert store.load_findings() == []
    assert store.load_activity() == []


def test_the_health_endpoint_carries_nothing_that_could_steer_anything(tmp_settings):
    """
    Something harmless to fetch, so "fetching is fine" can be shown rather than asserted.

    A skill can call this as often as it likes; there is no text in the reply long enough
    to be mistaken for an instruction.
    """
    response = client(tmp_settings).get("/mock/hub/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
