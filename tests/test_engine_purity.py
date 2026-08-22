"""
Checks that the findings engine is predictable and self-contained.

WHY THIS MATTERS MORE THAN IT LOOKS.

The headline promise of this whole project is "the honest skill produces no
findings". That is only a guarantee if the engine gives the same answer every time
for the same evidence. If it consulted the AI model, or depended on files, or on the
time of day, then a clean run would only ever be a lucky run - and every measurement
of false positives built on top of it would be worthless.

So this file checks the engine:
  - gives identical answers for identical input,
  - opens no files and makes no network calls while deciding,
  - never consults the AI model.

Covers: feature spec section 9; TDD section 4.8; invariant I-6; decision S-22.
"""

from __future__ import annotations

import pytest

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.monitor import audit_hook
from app.monitor.observations import ObservationLog
from app.skills.manifest import load_vocabulary

from tests.test_engine import make_manifest, observations


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


def test_the_same_evidence_always_gives_the_same_answer(engine):
    """
    Run the identical check twenty times and get the identical verdict every time.

    Identifiers and timestamps differ between runs, of course - what must not differ
    is WHAT was found.
    """
    manifest = make_manifest(
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}]
    )
    evidence = observations(("task.read", "*"), ("fs.read", "data/x.txt"))

    verdicts = []
    for _ in range(20):
        findings = engine.evaluate_invocation(manifest, evidence, invocation_id="inv_1")
        verdicts.append(
            sorted((f.type, f.axis, f.severity, str(f.observed)) for f in findings)
        )

    assert all(verdict == verdicts[0] for verdict in verdicts)


def test_an_honest_skill_is_silent_every_single_time(engine):
    """
    The promise that matters, repeated. Fifty runs, fifty silences.
    """
    manifest = make_manifest(
        capabilities=[{"id": "task.read", "scope": ["*"], "reason": "reads tasks"}]
    )
    evidence = observations(("task.read", "*"))

    for _ in range(50):
        assert engine.evaluate_invocation(manifest, evidence, invocation_id="inv_1") == []


def test_deciding_opens_no_files(engine, tmp_settings):
    """
    The engine works only from what it is handed. We prove it using the app's own
    watcher: if the engine opened anything while deciding, it would be recorded.
    """
    audit_hook.install_audit_hook()

    manifest = make_manifest(capabilities=[])
    evidence = observations(("fs.read", "data/x.txt"))

    watching = ObservationLog("inv_watch")
    with audit_hook.invocation_scope("inv_watch", watching):
        engine.evaluate_invocation(manifest, evidence, invocation_id="inv_1")

    file_activity = [
        entry
        for entry in watching.entries()
        if entry.capability in {"fs.read", "fs.write", "net.outbound"}
    ]
    assert file_activity == [], f"the engine touched something while deciding: {file_activity}"


def test_deciding_changes_nothing_on_disk(engine, tmp_settings):
    """
    The engine works out an answer and hands it back. Saving it, and writing evidence
    files, is somebody else's job - which keeps the deciding part easy to test and
    impossible to get subtly wrong.
    """
    manifest = make_manifest(capabilities=[])
    before = sorted(path.name for path in tmp_settings.data_dir.rglob("*"))

    engine.evaluate_invocation(
        manifest, observations(("fs.read", "x")), invocation_id="inv_1"
    )

    after = sorted(path.name for path in tmp_settings.data_dir.rglob("*"))
    assert before == after


def test_the_engine_does_not_import_the_ai_model_or_the_conversation():
    """
    Checked by reading the source. If the engine could ask the model for an opinion,
    the same evidence could produce different verdicts on different days.
    """
    from pathlib import Path

    findings_folder = Path(__file__).resolve().parents[1] / "backend" / "app" / "findings"
    for path in findings_folder.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "app.llm" not in text, f"{path.name} reaches into the AI model layer"
        assert "app.chat" not in text, f"{path.name} reaches into the conversation layer"


def test_the_order_of_findings_is_stable(engine):
    """
    A stable order means two runs can be compared directly, which matters for anyone
    diffing results between versions.
    """
    manifest = make_manifest(capabilities=[])
    evidence = observations(
        ("fs.read", "a.txt"), ("net.outbound", "http://127.0.0.1/x"), ("fs.write", "b.txt")
    )

    first = [f.type for f in engine.check_truthfulness(manifest, evidence, invocation_id="i")]
    second = [f.type for f in engine.check_truthfulness(manifest, evidence, invocation_id="i")]

    assert first == second
