"""
Proof that adding the AST05 substrate changed nothing that was already there.

WHY THIS FILE EXISTS, AND WHY IT LIVES HERE RATHER THAN IN THE AST05 FOLDER.

AST05 is the only weakness that changed the shared platform. Every other weakness is a
folder of its own that plugs into machinery it did not touch; this one made the capability
broker start recording something it never recorded before - what came BACK from a network
request.

That raises a fair objection, and this file is the answer to it. The objection is: *if you
had to change the detector to make your vulnerability visible, did you find a vulnerability
or did you build one?* The honest test is not an argument, it is a measurement:

  1. Do the three weaknesses that already existed still produce EXACTLY the findings they
     produced before the change? (If the substrate change nudged them even slightly, it was
     not the inert recording it claims to be.)
  2. Does the new check stay SILENT on all three of them? (A check that fires on everything
     is not a check, it is a rubber stamp.)
  3. Is the outbound fingerprinting - which the theft detection depends on - untouched?

The numbers those questions are measured against were recorded BEFORE any of this was
built, and live in tests/fixtures/pre_ast05_findings.json.

THIS FILE ONLY EVER READS THAT SNAPSHOT. It cannot write it and must never be given the
ability to. A regression test that can regenerate its own expectations proves nothing at
all - it would simply agree with whatever the code does today. If the snapshot is missing,
these tests fail loudly rather than helpfully rebuilding it.

If one of these tests fails, the answer is NOT to update the snapshot. It is to stop and
work out what moved.

Specification references: AST05 spec sections 8.6 and 10 (A-15, A-10, A-4); TDD section 12
(the carve-out test: a platform change that leaves the detector able to stay silent is
substrate, one that does not is a prop).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.chat.orchestrator import ChatOrchestrator
from app.llm.ollama_client import ChatResponse, ToolCall
from app.monitor.observations import payload_item_digests
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed, store

# The three weaknesses that existed before AST05, and must be unmoved by it.
SHIPPED_SKILLS = ["task_insights", "standup_sync", "focus_picker"]

LOCAL_BASE_URL = "http://127.0.0.1:8000"

SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "pre_ast05_findings.json"

# Only these keys may be new on an observation, and only on a network one. Anything else
# appearing is the substrate change reaching further than it was supposed to.
ALLOWED_NEW_DETAIL_KEYS = {
    "response_bytes",
    "response_sha256",
    "response_item_digests",
    "response_strings",
    "response_excerpt",
}


class _Stub:
    """A stand-in model that always asks for one named skill, so the test is about the skill."""

    def __init__(self, skill_id: str) -> None:
        self.skill_id = skill_id
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(content="", tool_calls=[ToolCall(self.skill_id, {})], model="stub")
        return ChatResponse(content="Done.", tool_calls=[], model="stub")


def _normalise(finding) -> dict:
    """
    The stable, comparable shape of one finding.

    In: a Finding. Out: a plain dictionary with the parts that must not change.

    Identifiers and timestamps are left out on purpose - they differ on every run and
    comparing them would make this test fail for reasons that have nothing to do with
    the thing it is guarding.
    """
    d = finding.model_dump()
    return {
        "type": d["type"],
        "ast_id": d["ast_id"],
        "ast_name": d["ast_name"],
        "axis": d["axis"],
        "severity": d["severity"],
        "skill_id": d["skill_id"],
        "skill_version": d["skill_version"],
        "trigger": d["trigger"],
        "observed_capability": (d.get("observed") or {}).get("capability"),
        "observed_resource": (d.get("observed") or {}).get("resource"),
        "granted_capability": (d.get("granted") or {}).get("capability"),
        "granted_reason": (d.get("granted") or {}).get("reason"),
        "correlation": d.get("correlation"),
        "summary": d["summary"],
    }


def _sort_key(finding: dict):
    """A stable ordering, so two runs of the same findings compare equal."""
    return (
        finding["type"],
        str(finding["granted_capability"]),
        str(finding["observed_resource"]),
    )


def _wait_until_ready(health_url: str, timeout_seconds: float = 15.0) -> None:
    """Wait for the live server to answer, or say clearly that it never did."""
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


@pytest.fixture(scope="module")
def snapshot() -> dict:
    """
    The finding sets recorded before the AST05 substrate change.

    Read only. If it is absent the tests fail rather than rebuild it - see the note at
    the top of this file.
    """
    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"The pre-AST05 baseline snapshot is missing: {SNAPSHOT_PATH}. "
            "It is recorded once, before the substrate change, and must not be "
            "regenerated afterwards - a regression test that rebuilds its own "
            "expectations proves nothing."
        )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual(tmp_path_factory) -> dict:
    """
    Run all three shipped weaknesses today, the same way the baseline was captured.

    In: nothing. Out: the same shape as the snapshot, measured against today's code.

    A real loopback server is used because two of these skills genuinely make network
    requests, and it is precisely those requests the substrate change touched. Running
    them against a stub would test everything except the thing at risk.
    """
    import os

    from app import config

    tmp = tmp_path_factory.mktemp("ast05_regression")
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[1]
    previous_cwd = Path.cwd()
    previous_env = {
        key: os.environ.get(key)
        for key in ("TASKBOT_DATA_DIR", "TASKBOT_HOST", "TASKBOT_SKILLS_DIR", "TASKBOT_POLICY_DIR")
    }

    os.environ["TASKBOT_DATA_DIR"] = str(data_dir)
    os.environ["TASKBOT_HOST"] = "127.0.0.1"
    os.environ["TASKBOT_SKILLS_DIR"] = str(repo_root / "backend" / "skills")
    os.environ["TASKBOT_POLICY_DIR"] = str(repo_root / "backend" / "policy")

    config.reset_settings()
    config.set_settings(config.load_settings())

    # Skills use relative paths like "data/tasks.json", which the file broker resolves
    # against the current folder. The baseline was captured with the folder aligned this
    # way, and the AST01/AST04 fixtures do the same; without it the reads are refused and
    # this test would compare today's degraded run against yesterday's healthy one.
    os.chdir(data_dir.parent)

    from app.main import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=8000, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_until_ready(f"{LOCAL_BASE_URL}/api/health")

    results: dict = {}
    try:
        for skill_id in SHIPPED_SKILLS:
            store.reset_lab()
            registry_module.reset_registry()
            host_module.clear_module_cache()
            seed.seed_tasks_if_absent()

            registry = registry_module.get_registry()
            registry.discover_default()
            for other in SHIPPED_SKILLS:
                if other != skill_id:
                    try:
                        registry.uninstall(other)
                    except Exception:
                        pass

            with httpx.Client(timeout=10.0) as client:
                response = client.post(f"{LOCAL_BASE_URL}/api/skills/{skill_id}/install")
                response.raise_for_status()
                install_findings = response.json().get("findings_raised", [])

            turn = ChatOrchestrator(client=_Stub(skill_id)).run_turn("please do your thing")

            results[skill_id] = {
                "install_finding_count": len(install_findings),
                "install_finding_types": sorted(f["type"] for f in install_findings),
                "invocation_findings": sorted(
                    (_normalise(f) for f in turn.findings_raised), key=_sort_key
                ),
                "invocation_finding_count": len(turn.findings_raised),
                "observations": list(turn.activity.observations),
                "skill_outcome": (
                    turn.activity.skill_invoked.outcome if turn.activity.skill_invoked else None
                ),
                "vulnerability_fired": turn.activity.vulnerability_fired,
            }
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        os.chdir(previous_cwd)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_settings()

    return results


# --- A-15: the three shipped weaknesses are unmoved -------------------------------


@pytest.mark.parametrize("skill_id", SHIPPED_SKILLS)
def test_shipped_vulnerability_findings_are_unchanged(skill_id, snapshot, actual):
    """
    A-15 - each weakness that existed before AST05 still produces exactly what it did.

    This is the heart of the file. If the substrate change had nudged any of these - one
    extra finding, one different severity, one changed summary - it would not be the inert
    recording it claims to be, and the whole justification for changing the platform would
    fall over.
    """
    expected = snapshot[skill_id]
    measured = actual[skill_id]

    assert measured["invocation_finding_count"] == expected["invocation_finding_count"], (
        f"{skill_id} now raises {measured['invocation_finding_count']} finding(s) on an "
        f"invocation; before the AST05 substrate change it raised "
        f"{expected['invocation_finding_count']}. Do not update the snapshot - find out "
        f"what moved."
    )
    assert measured["invocation_findings"] == expected["invocation_findings"], (
        f"{skill_id}'s findings differ from the pre-AST05 baseline."
    )
    assert measured["install_finding_count"] == expected["install_finding_count"]
    assert measured["install_finding_types"] == expected["install_finding_types"]
    assert measured["skill_outcome"] == expected["skill_outcome"]
    assert measured["vulnerability_fired"] == expected["vulnerability_fired"]


# --- A-10: the new check stays silent on all of them ------------------------------


@pytest.mark.parametrize("skill_id", SHIPPED_SKILLS)
def test_no_shipped_vulnerability_gains_a_provenance_finding(skill_id, actual):
    """
    A-10 - none of the three older weaknesses is now also reported as an AST05.

    The sharp case is standup_sync. It makes two network requests, so after the change
    both of its records carry the reply that came back - exactly the material the new
    check reads. It must still be reported as a theft and nothing else. If it picked up a
    provenance finding too, the new check would be firing on the mere presence of a
    network reply rather than on a skill acting on one.
    """
    axes = {finding["axis"] for finding in actual[skill_id]["invocation_findings"]}
    ast_ids = {finding["ast_id"] for finding in actual[skill_id]["invocation_findings"]}

    assert "provenance" not in axes, (
        f"{skill_id} picked up a provenance finding. The new check is firing on something "
        f"it should not - most likely on the presence of a reply rather than on the skill "
        f"acting on one."
    )
    assert "AST05" not in ast_ids


# --- The substrate change was additive, and only where it was meant to be ---------


@pytest.mark.parametrize("skill_id", SHIPPED_SKILLS)
def test_observations_only_gained_the_expected_response_fields(skill_id, snapshot, actual):
    """
    The recording change added what it said it would, where it said it would, and nothing else.

    Records may only GROW, never shrink - anything that used to be written down still is.
    New parts are allowed only on network records, and only the ones listed at the top of
    this file. A new part appearing on a task read or a file read would mean the change
    reached somewhere it was never meant to touch.
    """
    expected_observations = snapshot[skill_id]["observations"]
    measured_observations = actual[skill_id]["observations"]

    assert len(measured_observations) == len(expected_observations), (
        f"{skill_id} now records a different number of actions."
    )

    for expected, measured in zip(expected_observations, measured_observations):
        # The shape of what happened must be identical.
        assert measured["seq"] == expected["seq"]
        assert measured["capability"] == expected["capability"]
        assert measured["resource"] == expected["resource"]
        assert measured["outcome"] == expected["outcome"]
        assert measured["source"] == expected["source"]

        was = set(expected["detail_keys"])
        now = set(measured.get("detail") or {})

        assert was <= now, (
            f"{skill_id} seq {expected['seq']} lost detail it used to record: {was - now}"
        )

        gained = now - was
        if gained:
            assert measured["capability"] == "net.outbound", (
                f"{skill_id} seq {expected['seq']} is a {measured['capability']} action and "
                f"gained {gained}. The response recording must only touch network actions."
            )
            assert gained <= ALLOWED_NEW_DETAIL_KEYS, (
                f"{skill_id} seq {expected['seq']} gained unexpected detail: "
                f"{gained - ALLOWED_NEW_DETAIL_KEYS}"
            )


def test_outbound_fingerprinting_is_untouched():
    """
    The fingerprinting the theft detection depends on behaves exactly as it always did.

    AST05 needed a DIFFERENT way of fingerprinting - one that looks at pieces of text
    anywhere inside fetched content, not at items in a list. It was added as a separate
    function on purpose. This checks the original was left alone, because quietly widening
    it would change what counts as stolen data for AST01 without anyone noticing.
    """
    # A list's elements are fingerprinted; a bare string value is not.
    assert payload_item_digests({"items": ["a", "b"]}) != []
    assert payload_item_digests({"report_to": "http://127.0.0.1:8000/mock/collector"}) == []
    assert payload_item_digests({"acknowledged": True, "open": 4}) == []


def test_the_new_check_is_wired_but_does_not_run_at_install():
    """
    Provenance is a question about behaviour, so it cannot be asked before a skill runs.

    Over-privilege is visible from the manifest alone and is checked at install. This one
    is the opposite: the instructions arrive at run time, so there is nothing to look at
    yet (TDD D-16). Asserted so nobody "helpfully" adds it to the install path, where it
    could only ever return nothing.
    """
    import inspect

    from app.findings.engine import FindingsEngine

    invocation_source = inspect.getsource(FindingsEngine.evaluate_invocation)
    install_source = inspect.getsource(FindingsEngine.evaluate_install)

    assert "check_provenance" in invocation_source
    assert "check_provenance" not in install_source
