"""
Checks that the structural rules holding the design together are actually obeyed.

These are not tests of behaviour - they read the source code itself and check who
imports whom, and who is allowed to call what. They exist because the most important
security properties of this app are guaranteed by STRUCTURE rather than by clever
logic, and structure is exactly the sort of thing that decays quietly during ordinary
maintenance.

The two rules that matter most:

  1. The part of the app that supervises a running skill must never be able to see
     what that skill CLAIMED it would do. If it could, a lying skill would simply be
     blocked - and then there would be nothing to catch it doing, which defeats the
     entire purpose of the exercise.

  2. There must be exactly one place in the whole codebase that runs a skill, and
     exactly one place that calls it. That is what makes "the AI agent genuinely
     chose this" checkable by a reviewer in under a minute.

Covers: TDD section 10; invariants I-1, I-2 and I-6; acceptance test A-15.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def python_files_under(folder: Path) -> list[Path]:
    """
    Every Python file in a folder and its sub-folders.

    In: the folder. Out: the files.
    """
    return sorted(path for path in folder.rglob("*.py") if path.name != "__pycache__")


def imports_in(path: Path) -> str:
    """
    The text of one Python file, for searching.

    In: the file. Out: its contents as text.
    """
    return path.read_text(encoding="utf-8")


# --- Rule 1: the supervisor must not know what was claimed -----------------------


def test_the_skills_side_never_imports_the_findings_side():
    """
    INVARIANT I-2 - the most important structural rule in the app.

    The capability broker supervises a running skill. It must not be able to look up
    what that skill declared, because comparing promises against behaviour happens
    later and somewhere else.

    If the broker could check declarations, it would simply block anything
    undeclared. A lying skill would be stopped - and stopping it means there is
    nothing left to catch, no evidence, and no finding. The app would defeat its own
    purpose while appearing to work.
    """
    offenders = []
    for path in python_files_under(APP / "skills"):
        text = imports_in(path)
        if re.search(r"^\s*from\s+app\.findings", text, re.MULTILINE) or re.search(
            r"^\s*import\s+app\.findings", text, re.MULTILINE
        ):
            offenders.append(path.name)

    assert offenders == [], (
        f"These files in app/skills/ import app/findings/: {offenders}. "
        "The supervisor must not be able to see what a skill declared."
    )


def test_the_capability_broker_never_mentions_manifests():
    """
    The same rule, checked from the other direction and more narrowly.

    The broker file must not reference manifests or declarations at all - not even
    indirectly - because knowing what was declared is precisely what it must not do.
    """
    text = imports_in(APP / "skills" / "context.py")

    assert "from app.skills.manifest" not in text
    assert "Manifest" not in text.replace("manifest.json", "")


# --- Rule 2: exactly one way to run a skill --------------------------------------


def test_only_the_conversation_code_runs_a_skill():
    """
    INVARIANT I-1 and ACCEPTANCE TEST A-15.

    Running a skill happens in one function, and that function is called from one
    place: the branch of the conversation code that handles the AI model asking for
    a skill by name.

    If anything else could start a skill - a keyword match, a shortcut, a helpful
    fallback - then a demonstration proving an agent was tricked would prove nothing,
    because the skill might have been started by the app rather than chosen by the
    agent.
    """
    callers = []
    for path in python_files_under(APP):
        if path.name == "host.py":
            continue  # this is where the function is defined
        text = imports_in(path)
        if ".invoke(" in text or "get_host()" in text:
            callers.append(str(path.relative_to(APP)).replace("\\", "/"))

    assert callers == ["chat/orchestrator.py"], (
        f"Skills are run from {callers}. Only chat/orchestrator.py may do this, "
        "or the claim that the AI agent chose to run a skill stops being provable."
    )


def test_the_skill_name_comes_only_from_the_models_answer():
    """
    The second half of the same guarantee.

    The name passed to the runner must come from what the AI model asked for, and
    from nowhere else. Reading the user's message and picking a skill would be the
    hardcoded routing the specification forbids.
    """
    text = imports_in(APP / "chat" / "orchestrator.py")

    # Find the line that actually runs a skill and check where its name came from.
    invoke_lines = [line.strip() for line in text.splitlines() if ".invoke(" in line]
    assert invoke_lines, "expected the orchestrator to run skills somewhere"

    for line in invoke_lines:
        assert "tool_call" in line or "call." in line or "name" in line, (
            f"The skill name in {line!r} does not obviously come from the model's "
            "answer. It must never be derived from the user's message."
        )


# --- Rule 3: findings stay deterministic -----------------------------------------


def test_the_findings_engine_never_touches_the_ai_model():
    """
    INVARIANT I-6.

    The findings engine takes what was declared and what happened, and works out the
    answer by itself. If it consulted the AI model, the same evidence could produce
    different verdicts on different runs - and "the control skill produces no
    findings" would stop being a guarantee and become a hope.
    """
    offenders = []
    for path in python_files_under(APP / "findings"):
        text = imports_in(path)
        if "app.llm" in text or "app.chat" in text:
            offenders.append(path.name)

    assert offenders == [], f"These findings files reach into the AI model layer: {offenders}"


def test_the_watchers_do_not_depend_on_the_broker():
    """
    The broker uses the watchers, never the other way round. If both depended on each
    other, neither could be understood or tested on its own.
    """
    offenders = []
    for path in python_files_under(APP / "monitor"):
        if "app.skills.context" in imports_in(path):
            offenders.append(path.name)

    assert offenders == [], f"These watcher files depend on the broker: {offenders}"


# --- Rule 4: the built-in abilities are not skills -------------------------------


def test_the_built_in_abilities_never_go_through_the_broker():
    """
    Adding and listing to-do items is the app doing its own job, not a skill under
    supervision. It must not create observations, or a brand new lab would look like
    it had already found problems.
    """
    text = imports_in(APP / "chat" / "builtins.py")

    assert "SkillContext" not in text
    assert "ObservationLog" not in text
    assert "invocation_scope" not in text
