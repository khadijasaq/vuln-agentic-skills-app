"""
The mock component registry: where the parts a skill is built on are published.

The collector and the dashboard only ever receive. The team hub hands over a document a
skill READS. This one hands over a component a skill is BUILT ON - and unlike the hub it
has to be asked for something by NAME and by VERSION, because "same name, same version,
different contents" is the whole of the weakness it exists to make possible.

What is checked here is mostly that it is boring: it serves a file, it does not judge what
is in that file, and it does not fall over when there is nothing to serve. A registry that
started checking its own components would quietly remove the weakness.

One check here is not boring at all, and it is the most important in the file: that the
bytes served are the bytes on disk, untouched. The whole comparison this weakness rests on
is a fingerprint, and a fingerprint of something the app re-typed on the way out would be a
fact about the app rather than about the component.

Specification references: AST02 spec sections 5.1-5.3; decisions S-4 and S-10; build plan
step 4.4.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.monitor.observations import digest_of

COMPONENT_PATH = "/mock/registry/sizing-heuristics/2.3.1"
REGISTRY_DIR = Path(__file__).resolve().parents[1] / "registry"


def client(tmp_settings) -> TestClient:
    """A test client over a freshly built app, using the isolated data folder."""
    return TestClient(create_app())


def test_the_registry_serves_the_component_that_ships_with_the_weakness(tmp_settings):
    """
    A brand new lab has the substituted build already published.

    Startup copies it in, so a person can install the skill and watch the whole thing
    happen without first having to find and place a file.
    """
    response = client(tmp_settings).get(COMPONENT_PATH)

    assert response.status_code == 200
    component = response.json()

    assert component["pack"] == "sizing-heuristics"
    assert component["version"] == "2.3.1"
    assert component["bands"], "the component has no size bands"
    assert component["rules"], "the component has no rules"


def test_the_reviewed_build_is_never_published(tmp_settings):
    """
    The honest build ships in the repository but is NOT served.

    That asymmetry is what makes the weakness the default: a lab that has never been
    touched serves the substituted build. The reviewed one sits beside it so a person can
    read what the component was supposed to be, and so a test can put it back deliberately
    to watch the finding disappear.
    """
    client(tmp_settings)

    registry_dir = get_settings().registry_dir
    published = {path.name for path in registry_dir.iterdir() if path.is_file()}

    assert "sizing-heuristics-2.3.1.json" in published
    assert not any(name.endswith(".reviewed.json") for name in published), (
        "a reviewed build was published; the lab would then serve the honest component "
        "and the weakness would never appear"
    )


def test_the_bytes_served_are_the_bytes_on_disk(tmp_settings):
    """
    THE IMPORTANT ONE. What is served is the file, character for character.

    Everything about this weakness is a comparison between a fingerprint written down in
    advance and a fingerprint taken of what arrived. If the app read the file as data and
    wrote it out again - which is what the sibling hub does, quite reasonably, because
    nothing depends on its exact bytes - the fingerprint would describe the app's
    formatting rather than the file, and would change whenever that formatting changed.

    So this asserts the property the pinned fingerprint rests on, and it asserts it as a
    fingerprint rather than as a string comparison, because that is the form the weakness
    actually uses.
    """
    application = client(tmp_settings)
    on_disk = (get_settings().registry_dir / "sizing-heuristics-2.3.1.json").read_bytes()

    response = application.get(COMPONENT_PATH)

    assert response.content == on_disk, "the registry re-encoded the component on the way out"
    assert digest_of(response.text) == digest_of(on_disk.decode("utf-8"))


def test_the_two_shipped_builds_have_different_fingerprints(tmp_settings):
    """
    Same name, same version, different contents - stated as a fact about the two files.

    If these ever became identical the weakness would silently stop existing while every
    other test carried on passing, because a delivery that matches the pin is exactly the
    clean case.
    """
    compromised = (REGISTRY_DIR / "sizing-heuristics-2.3.1.json").read_bytes().decode("utf-8")
    reviewed = (
        (REGISTRY_DIR / "sizing-heuristics-2.3.1.reviewed.json").read_bytes().decode("utf-8")
    )

    assert digest_of(compromised) != digest_of(reviewed)

    # ...and they really are the same component by name and version, which is what makes a
    # substitution invisible to anyone reading labels rather than contents.
    assert json.loads(compromised)["pack"] == json.loads(reviewed)["pack"]
    assert json.loads(compromised)["version"] == json.loads(reviewed)["version"]
    assert json.loads(compromised)["publisher"] == json.loads(reviewed)["publisher"]


def test_the_registry_serves_whatever_is_in_the_file_without_judging_it(tmp_settings):
    """
    Swapping the file changes what a skill is built on. No code change, no new version.

    This is the property that makes the weakness worth demonstrating: the dangerous part is
    a component, and a component can change under a skill nobody has touched.
    """
    application = client(tmp_settings)

    replacement = {"pack": "sizing-heuristics", "version": "2.3.1", "bands": [], "rules": []}
    path = get_settings().registry_dir / "sizing-heuristics-2.3.1.json"
    path.write_text(json.dumps(replacement), encoding="utf-8")

    response = application.get(COMPONENT_PATH)

    assert response.status_code == 200
    assert response.json() == replacement


def test_a_missing_component_is_answered_plainly(tmp_settings):
    """
    A registry with nothing to offer says so, rather than looking like a broken app.
    """
    application = client(tmp_settings)
    (get_settings().registry_dir / "sizing-heuristics-2.3.1.json").unlink()

    response = application.get(COMPONENT_PATH)

    assert response.status_code == 404
    assert response.json()["error"] == "no_such_component"


def test_an_unknown_component_is_answered_plainly(tmp_settings):
    """Asking for something that was never published is a plain 'no', not an error."""
    response = client(tmp_settings).get("/mock/registry/not-a-real-pack/9.9.9")

    assert response.status_code == 404
    assert response.json()["error"] == "no_such_component"


def test_a_request_cannot_reach_outside_the_registry_folder(tmp_settings):
    """
    The only checking this endpoint does is about WHERE files live, never about what they
    contain.

    A name or version that could contain a path would let a request ask for a file
    elsewhere on the machine. Neither pattern allows one, so such a request is simply not a
    component name and is refused as "no such component".
    """
    application = client(tmp_settings)

    for name, version in [("..", "2.3.1"), ("sizing-heuristics", "../../secrets")]:
        response = application.get(f"/mock/registry/{name}/{version}")
        assert response.status_code == 404


def test_the_health_endpoint_carries_nothing_that_could_matter(tmp_settings):
    """
    Fetching something harmless is harmless.

    Useful for proving the fetching path itself works without a component being delivered -
    and there is nothing here to compare against a fingerprint, so nothing to report.
    """
    response = client(tmp_settings).get("/mock/registry/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_the_registry_records_nothing_and_reports_nothing(tmp_settings):
    """
    A courier does not open the box.

    The registry writes no record of what it served and raises no problem about it.
    Noticing that a component is not the one that was promised is the findings engine's
    job. If the registry did it instead, the evidence would come from the same place as
    the delivery - which is exactly the arrangement that would make it worthless.
    """
    from app.findings.markers import count_markers
    from app.storage import store

    application = client(tmp_settings)
    application.get(COMPONENT_PATH)
    application.get(COMPONENT_PATH)

    assert store.load_findings() == []
    assert count_markers() == 0
