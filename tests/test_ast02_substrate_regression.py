"""
Proof that adding the AST02 integrity axis changed nothing that was already there.

WHY THIS FILE EXISTS.

AST02 is the second weakness to change the shared platform. AST05 was the first, and it
had to argue for itself because it made the capability broker start RECORDING something
new. This one is different, and the difference is the whole justification: it records
nothing new at all. Every piece of evidence it reads - the fingerprint of what came back
from a request - has been written down for every skill, on every fetch, since AST05
landed. What AST02 adds is somewhere for a skill to say WHICH artifact it expected, and a
check that compares the two.

That still deserves a measurement rather than an argument, and this file is it:

  1. Do the four weaknesses that already existed, plus the honest control skill, still
     produce EXACTLY the findings they produced before? (If the new axis nudged any of
     them, it is not the inert comparison it claims to be.)
  2. Does the new check stay SILENT on all five? (A check that fires on everything is not
     a check, it is a rubber stamp.)
  3. Did the records of what skills did stay EXACTLY as they were? (AST05 was allowed to
     add fields to a network record. AST02 is allowed to add nothing whatsoever, which is
     a stricter promise and an easier one to test.)

The numbers those questions are measured against were recorded BEFORE any of this was
built, and live in tests/fixtures/pre_ast02_findings.json.

THIS FILE ONLY EVER READS THAT SNAPSHOT. It cannot write it and must never be given the
ability to. A regression test that can regenerate its own expectations proves nothing at
all - it would simply agree with whatever the code does today. If the snapshot is missing,
these tests fail loudly rather than helpfully rebuilding it.

If one of these tests fails, the answer is NOT to update the snapshot. It is to stop and
work out what moved.

Specification references: AST02 spec sections 9.8 and 11 (A-4, A-10); build plan steps 0.1
and 0.2; TDD section 12 (the carve-out test: a platform change that leaves the detector
able to stay silent is substrate, one that does not is a prop).
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
from app.llm.groq_client import ChatResponse, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed, store

# The four weaknesses that existed before AST02, plus the honest control skill. All five
# must be unmoved by it - and the control skill matters most, because it is the proof the
# whole detector can stay silent (G5, SC-3).
SHIPPED_SKILLS = ["task_insights", "standup_sync", "focus_picker", "team_rules", "task_summary"]

LOCAL_BASE_URL = "http://127.0.0.1:8000"

SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "pre_ast02_findings.json"

# The two files AST02 promised never to touch. They are where evidence is RECORDED; the
# whole claim of this feature is that it only READS what they already wrote.
UNTOUCHED_RECORDING_FILES = [
    Path(__file__).resolve().parents[1] / "backend" / "app" / "skills" / "context.py",
    Path(__file__).resolve().parents[1] / "backend" / "app" / "monitor" / "observations.py",
]


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
    comparing them would make this test fail for reasons that have nothing to do with the
    thing it is guarding.
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
        "provenance_influence": (d.get("provenance") or {}).get("influence"),
        "dependency": d.get("dependency"),
        "summary": d["summary"],
    }


def _sort_key(finding: dict):
    """A stable ordering, so two runs of the same findings compare equal."""
    return (
        finding["type"],
        str(finding["granted_capability"]),
        str(finding["observed_resource"]),
        str(finding["provenance_influence"]),
    )


def _wait_until_ready(health_url: str, timeout_seconds: float = 20.0) -> None:
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
    The finding sets recorded before the AST02 integrity axis was built.

    Read only. If it is absent the tests fail rather than rebuild it - see the note at the
    top of this file.
    """
    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"The pre-AST02 baseline snapshot is missing: {SNAPSHOT_PATH}. "
            "It is recorded once, before the platform change, and must not be "
            "regenerated afterwards - a regression test that rebuilds its own "
            "expectations proves nothing."
        )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual(tmp_path_factory) -> dict:
    """
    Run all five shipped skills today, the same way the baseline was captured.

    In: nothing. Out: the same shape as the snapshot, measured against today's code.

    A real loopback server is used because three of these skills genuinely make network
    requests, and the response fingerprint those requests produce is precisely what the
    new axis reads. Running them against a stub would test everything except the thing at
    risk.
    """
    import os

    from app import config

    tmp = tmp_path_factory.mktemp("ast02_regression")
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
    # way; without it the reads are refused and this test would compare today's degraded
    # run against yesterday's healthy one.
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

            with httpx.Client(timeout=15.0) as client:
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
                "observations": [
                    {
                        "seq": o["seq"],
                        "capability": o["capability"],
                        "resource": o["resource"],
                        "outcome": o["outcome"],
                        "source": o["source"],
                        "detail_keys": sorted(o.get("detail") or {}),
                    }
                    for o in turn.activity.observations
                ],
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


# --- A-10: the four shipped weaknesses and the control skill are unmoved ------------


@pytest.mark.parametrize("skill_id", SHIPPED_SKILLS)
def test_shipped_skill_findings_are_unchanged(skill_id, snapshot, actual):
    """
    A-10 - each skill that existed before AST02 still produces exactly what it did.

    This is the heart of the file. If adding a fifth axis had nudged any of these - one
    extra finding, one different severity, one changed summary - the claim that it is a
    self-contained comparison would fall over, and with it the justification for touching
    the shared platform at all.
    """
    expected = snapshot[skill_id]
    measured = actual[skill_id]

    assert measured["invocation_finding_count"] == expected["invocation_finding_count"], (
        f"{skill_id} now raises {measured['invocation_finding_count']} finding(s) on an "
        f"invocation; before the AST02 integrity axis it raised "
        f"{expected['invocation_finding_count']}. Do not update the snapshot - find out "
        f"what moved."
    )
    assert measured["invocation_findings"] == expected["invocation_findings"], (
        f"{skill_id}'s findings differ from the pre-AST02 baseline."
    )
    assert measured["install_finding_count"] == expected["install_finding_count"]
    assert measured["install_finding_types"] == expected["install_finding_types"]
    assert measured["skill_outcome"] == expected["skill_outcome"]
    assert measured["vulnerability_fired"] == expected["vulnerability_fired"]


@pytest.mark.parametrize("skill_id", SHIPPED_SKILLS)
def test_no_shipped_skill_gains_an_integrity_finding(skill_id, actual):
    """
    A-10 - none of the five is now also reported as an AST02.

    The sharp cases are standup_sync and team_rules. Both make real network requests, so
    both have exactly the material the new check reads - a fingerprint of what came back.
    They must still be reported as a theft and as an instruction problem respectively, and
    as nothing else. If either picked up an integrity finding, the new check would be
    firing on the mere presence of a network reply rather than on a skill having promised
    which artifact it expected.
    """
    axes = {finding["axis"] for finding in actual[skill_id]["invocation_findings"]}
    ast_ids = {finding["ast_id"] for finding in actual[skill_id]["invocation_findings"]}

    assert "integrity" not in axes, (
        f"{skill_id} picked up an integrity finding. The new check is firing on something "
        f"it should not - most likely on the presence of a network reply rather than on a "
        f"declared dependency."
    )
    assert "AST02" not in ast_ids


def test_the_control_skill_is_still_completely_silent(actual):
    """
    A-4 - the honest skill produces nothing at all, which is what makes any finding mean
    something (G5, SC-3, invariant I-12).
    """
    control = actual["task_summary"]

    assert control["invocation_finding_count"] == 0
    assert control["install_finding_count"] == 0
    assert control["invocation_findings"] == []
    assert control["vulnerability_fired"] is False


# --- The records of what skills did did not change at all --------------------------


@pytest.mark.parametrize("skill_id", SHIPPED_SKILLS)
def test_the_record_of_what_each_skill_did_is_byte_for_byte_identical(skill_id, snapshot, actual):
    """
    AST02 added NOTHING to what is written down about a skill's actions.

    AST05 was permitted to add fields to a network record, and its own regression test
    allows for exactly that. AST02 made a stricter promise: it reads what is already
    there and writes nothing. So this asserts equality, not growth - the strongest form
    of the claim, and the easiest to check.
    """
    expected_observations = snapshot[skill_id]["observations"]
    measured_observations = actual[skill_id]["observations"]

    assert len(measured_observations) == len(expected_observations), (
        f"{skill_id} now records a different number of actions."
    )

    for expected, measured in zip(expected_observations, measured_observations):
        assert measured["seq"] == expected["seq"]
        assert measured["capability"] == expected["capability"]
        assert measured["resource"] == expected["resource"]
        assert measured["outcome"] == expected["outcome"]
        assert measured["source"] == expected["source"]
        assert measured["detail_keys"] == expected["detail_keys"], (
            f"{skill_id} seq {expected['seq']} records different detail than it did "
            f"before AST02. This feature must add no recording of any kind: "
            f"gained {set(measured['detail_keys']) - set(expected['detail_keys'])}, "
            f"lost {set(expected['detail_keys']) - set(measured['detail_keys'])}."
        )


def test_the_recording_files_know_nothing_about_dependencies():
    """
    The broker and the notebook were not taught anything about this weakness.

    This is the single strongest fact in the argument for changing the platform at all: the
    place where evidence is RECORDED is untouched, and only the place where evidence is
    JUDGED gained anything. If either of these files had to learn what a dependency is, the
    evidence would have been shaped to fit the finding rather than the other way round.
    """
    from tests.source_tools import executable_source

    for path in UNTOUCHED_RECORDING_FILES:
        source = executable_source(path)
        for forbidden in ["dependency", "dependencies", "integrity", "AST02", "check_integrity"]:
            assert forbidden not in source, (
                f"{path.name} mentions {forbidden!r}. The recording side must know nothing "
                f"about the integrity axis - it only writes down what happened."
            )


def test_the_new_check_runs_at_install_as_well_as_on_a_run():
    """
    Integrity asks two questions, and only one of them needs the skill to have run.

    "You declared a dependency and pinned nothing" is answerable from the description
    alone, so it is asked at install - like the over-privilege check. "What arrived is not
    what you pinned" cannot be asked before anything arrived, so it can only be answered
    on a run.

    That is the exact opposite of the instruction check, which can never run at install,
    and asserting both here keeps the difference from being quietly lost.
    """
    import inspect

    from app.findings.engine import FindingsEngine

    invocation_source = inspect.getsource(FindingsEngine.evaluate_invocation)
    install_source = inspect.getsource(FindingsEngine.evaluate_install)

    assert "check_integrity" in invocation_source
    assert "check_integrity" in install_source

    # And the sibling axis still behaves the other way round, unchanged.
    assert "check_provenance" in invocation_source
    assert "check_provenance" not in install_source
