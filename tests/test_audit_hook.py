"""
Checks for the process-wide watcher (app/monitor/audit_hook.py).

THIS IS ONE OF THE MOST IMPORTANT TEST FILES IN THE PROJECT.

The watcher exists to catch a skill that ignores the official channel and touches
things directly. Four properties must hold, and each has its own test below:

  1. Activity that is not a skill is ignored entirely.
  2. A skill going around the official channel IS recorded.
  3. The app's own work done on a skill's behalf is NOT recorded.
  4. The watcher never throws an error.

Property 3 is the one that quietly breaks everything if it regresses: without it the
honest control skill would accuse itself of secretly reading files, and the clean
baseline the whole security exercise rests on would be gone.

Covers: feature spec sections 5.8 and 7.4-7.6; TDD sections 3.2-3.4; decision D-8;
acceptance test A-5 (the synthetic half - the real one is in test_broker_tasks.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.monitor import audit_hook
from app.monitor.observations import ObservationLog


@pytest.fixture(autouse=True)
def _watcher_installed():
    """The watcher is switched on for every test in this file."""
    audit_hook.install_audit_hook()
    yield


@pytest.fixture
def notebook() -> ObservationLog:
    """A fresh, empty notebook for one pretend skill run."""
    return ObservationLog("inv_test")


# --- The markers themselves ------------------------------------------------------


def test_the_markers_start_empty():
    """Outside any skill run, nothing is marked as in progress."""
    assert audit_hook.CURRENT_INVOCATION.get() is None
    assert audit_hook.CURRENT_LOG.get() is None
    assert audit_hook.IN_BROKER.get() is False


def test_broker_frame_sets_and_restores_its_marker():
    """Entering marks it, leaving unmarks it."""
    assert audit_hook.IN_BROKER.get() is False

    with audit_hook.broker_frame():
        assert audit_hook.IN_BROKER.get() is True

    assert audit_hook.IN_BROKER.get() is False


def test_broker_frame_restores_even_when_something_goes_wrong():
    """
    An error in the middle must not leave the app permanently blind. If the marker
    stayed set, the watcher would ignore everything from then on.
    """
    with pytest.raises(ValueError):
        with audit_hook.broker_frame():
            raise ValueError("something failed")

    assert audit_hook.IN_BROKER.get() is False


def test_broker_frames_can_be_nested_safely(notebook):
    """One official-channel method calling another must still end up unmarked."""
    with audit_hook.broker_frame():
        with audit_hook.broker_frame():
            assert audit_hook.IN_BROKER.get() is True
        # Still inside the outer one.
        assert audit_hook.IN_BROKER.get() is True

    assert audit_hook.IN_BROKER.get() is False


def test_invocation_scope_sets_and_clears(notebook):
    """A skill run is marked while it happens and unmarked afterwards."""
    with audit_hook.invocation_scope("inv_123", notebook):
        assert audit_hook.CURRENT_INVOCATION.get() == "inv_123"
        assert audit_hook.CURRENT_LOG.get() is notebook

    assert audit_hook.CURRENT_INVOCATION.get() is None
    assert audit_hook.CURRENT_LOG.get() is None


def test_invocation_scope_clears_even_after_an_error(notebook):
    """
    If a skill crashes, the marker must still be cleared - otherwise everything the
    app did afterwards would be blamed on the crashed skill.
    """
    with pytest.raises(RuntimeError):
        with audit_hook.invocation_scope("inv_123", notebook):
            raise RuntimeError("the skill crashed")

    assert audit_hook.CURRENT_INVOCATION.get() is None


# --- Property 1: activity that is not a skill is ignored -------------------------


def test_ordinary_app_activity_is_not_recorded(tmp_path, notebook):
    """
    PROPERTY 1.

    With no skill running, opening files records nothing. The app opens files
    constantly - web pages, saved records, the AI model connection - and if any of
    that were blamed on a skill the findings list would be meaningless noise.
    """
    target = tmp_path / "ordinary.txt"
    target.write_text("the app going about its business", encoding="utf-8")
    target.read_text(encoding="utf-8")

    assert len(notebook) == 0


# --- Property 2: going around the official channel IS caught ---------------------


def test_a_skill_opening_a_file_directly_is_recorded(tmp_path, notebook):
    """
    PROPERTY 2.

    This is the watcher earning its keep: a skill that ignores the official channel
    and opens a file itself is caught anyway.
    """
    target = tmp_path / "secret.txt"
    target.write_text("contents", encoding="utf-8")

    with audit_hook.invocation_scope("inv_123", notebook):
        target.read_text(encoding="utf-8")

    reads = [entry for entry in notebook.entries() if entry.capability == "fs.read"]
    assert len(reads) >= 1
    assert reads[0].source == "audit_hook"
    assert "secret.txt" in reads[0].resource


def test_writing_a_file_is_told_apart_from_reading_it(tmp_path, notebook):
    """Opening to write is a different capability from opening to read."""
    target = tmp_path / "written.txt"

    with audit_hook.invocation_scope("inv_123", notebook):
        target.write_text("written by a skill", encoding="utf-8")

    writes = [entry for entry in notebook.entries() if entry.capability == "fs.write"]
    assert len(writes) >= 1


def test_a_skill_looking_up_a_website_is_recorded(notebook):
    """
    Network activity is caught at the name-lookup stage, which happens before any
    connection - so an attempt is recorded even if the connection then fails.
    """
    import socket

    with audit_hook.invocation_scope("inv_123", notebook):
        try:
            socket.getaddrinfo("localhost", 80)
        except Exception:
            pass

    network = [entry for entry in notebook.entries() if entry.capability == "net.outbound"]
    assert len(network) >= 1
    assert network[0].source == "audit_hook"


def test_recorded_events_say_which_low_level_event_caused_them(tmp_path, notebook):
    """
    Keeping the original event name makes a finding traceable back to exactly what
    Python saw, rather than only our interpretation of it.
    """
    target = tmp_path / "traced.txt"
    target.write_text("x", encoding="utf-8")

    with audit_hook.invocation_scope("inv_123", notebook):
        target.read_text(encoding="utf-8")

    reads = [entry for entry in notebook.entries() if entry.capability == "fs.read"]
    assert reads[0].detail["audit_event"] == "open"


# --- Property 3: the app's own work is not blamed on the skill -------------------


def test_the_apps_own_work_for_a_skill_is_not_recorded(tmp_path, notebook):
    """
    PROPERTY 3 - THE ONE THAT QUIETLY BREAKS EVERYTHING IF IT REGRESSES.

    When a skill politely asks to read its task list, the app opens the task file to
    answer. That file opening must NOT be recorded, because the skill did exactly
    the right thing.

    Without this, the honest control skill would accuse itself of secretly reading
    files, no clean baseline would exist, and every later measurement of false
    positives would be worthless.
    """
    target = tmp_path / "app_internal.json"
    target.write_text("{}", encoding="utf-8")

    with audit_hook.invocation_scope("inv_123", notebook):
        # This stands in for the official channel fulfilling a polite request.
        with audit_hook.broker_frame():
            target.read_text(encoding="utf-8")

    assert len(notebook) == 0


def test_suppression_only_covers_the_apps_own_work(tmp_path, notebook):
    """
    The suppression must be narrow. Work done by the app is invisible; anything the
    skill does before or after is still caught.
    """
    inner = tmp_path / "inner.txt"
    outer = tmp_path / "outer.txt"
    inner.write_text("a", encoding="utf-8")
    outer.write_text("b", encoding="utf-8")

    with audit_hook.invocation_scope("inv_123", notebook):
        with audit_hook.broker_frame():
            inner.read_text(encoding="utf-8")  # invisible
        outer.read_text(encoding="utf-8")  # caught

    resources = [entry.resource for entry in notebook.entries()]
    assert not any("inner.txt" in resource for resource in resources)
    assert any("outer.txt" in resource for resource in resources)


# --- Property 4: the watcher never breaks the app --------------------------------


def test_the_watcher_never_raises_even_with_a_broken_notebook(tmp_path):
    """
    PROPERTY 4.

    The watcher runs inside completely unrelated code all over the program. If it
    could throw an error it would crash things that have nothing to do with it, so
    any problem must be swallowed.
    """

    class BrokenNotebook:
        def record(self, **kwargs):
            raise RuntimeError("this notebook is broken")

    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    # Must not raise, despite the notebook failing every time it is written to.
    with audit_hook.invocation_scope("inv_123", BrokenNotebook()):
        target.read_text(encoding="utf-8")


def test_a_skill_run_with_no_notebook_is_harmless(tmp_path):
    """A skill run with nowhere to record simply records nothing."""
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    with audit_hook.invocation_scope("inv_123", None):
        target.read_text(encoding="utf-8")  # must not raise


# --- Installing it ---------------------------------------------------------------


def test_installing_twice_is_harmless():
    """
    Python cannot remove an audit hook once added, so installing twice would leave
    two copies recording everything in duplicate.
    """
    audit_hook.install_audit_hook()
    audit_hook.install_audit_hook()

    notebook = ObservationLog("inv_dupe")
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        path = Path(handle.name)
    path.write_text("x", encoding="utf-8")

    with audit_hook.invocation_scope("inv_dupe", notebook):
        path.read_text(encoding="utf-8")

    reads = [entry for entry in notebook.entries() if entry.capability == "fs.read"]
    # Exactly one line per real file open, not two.
    assert len([entry for entry in reads if str(path) in entry.resource]) == 1
