"""
Checks for the task channel, and for the ordering rule every channel follows.

This file contains acceptance test A-5, which is one of the most important checks in
the project. When a skill politely asks to read its task list, the app opens the
tasks file to answer. A-5 proves that opening is NOT blamed on the skill.

If A-5 ever fails, the honest control skill starts accusing itself of secretly
reading files, no clean baseline exists, and every later claim about false positives
becomes worthless.

Covers: feature spec sections 5.5, 7.1, 7.3 and 7.5; TDD section 3.1; decisions
S-8, S-19 and S-26; invariants I-3 and I-4; acceptance tests A-5 and A-18 (in part).
"""

from __future__ import annotations

import pytest

from app.monitor import audit_hook
from app.monitor.observations import ObservationLog
from app.skills.context import CapabilityRefused, SkillContext
from app.storage import seed, store


@pytest.fixture(autouse=True)
def _watcher_installed():
    audit_hook.install_audit_hook()
    yield


@pytest.fixture
def running_skill(tmp_settings):
    """
    Set the stage as if a skill were running: a fresh notebook, and the markers set
    so the process-wide watcher is paying attention.
    """
    seed.seed_tasks_if_absent()
    notebook = ObservationLog("inv_test")
    context = SkillContext("inv_test", notebook)

    with audit_hook.invocation_scope("inv_test", notebook):
        yield context, notebook


# --- ACCEPTANCE TEST A-5 ---------------------------------------------------------


def test_a5_reading_tasks_records_one_task_read_and_no_file_read(running_skill):
    """
    ACCEPTANCE TEST A-5 - the one that keeps the control skill honest-looking.

    Asking politely for the task list must produce EXACTLY ONE record saying "read
    the tasks", and NOTHING saying "read a file" - even though answering the request
    really does open the tasks file on disk.

    Without this, the app would report every honest skill for secretly reading files.
    """
    context, notebook = running_skill

    context.tasks.list("all")

    entries = notebook.entries()
    task_reads = [entry for entry in entries if entry.capability == "task.read"]
    file_reads = [entry for entry in entries if entry.capability == "fs.read"]

    assert len(task_reads) == 1, f"expected exactly one task read, got {entries}"
    assert file_reads == [], f"the app's own file access leaked into the record: {file_reads}"


def test_a5_holds_for_every_task_operation(running_skill):
    """
    A-5 extended: no task operation may leak the app's own file activity, otherwise
    a skill that adds a task would be reported for secretly writing files.
    """
    context, notebook = running_skill

    tasks = context.tasks.list("all")
    created = context.tasks.add("A new item")
    context.tasks.get(created["id"])
    context.tasks.update(created["id"], done=True)
    context.tasks.delete(created["id"])

    leaked = [
        entry
        for entry in notebook.entries()
        if entry.capability in {"fs.read", "fs.write"}
    ]
    assert leaked == [], f"the app's own file access leaked into the record: {leaked}"


# --- The ordering rule -----------------------------------------------------------


def test_the_request_is_written_down_before_it_is_carried_out(running_skill):
    """
    INVARIANT I-3.

    The note exists even for a request that then fails. We prove it by asking for a
    task that does not exist: the attempt is still on the record.
    """
    context, notebook = running_skill

    with pytest.raises(CapabilityRefused):
        context.tasks.get("tsk_does_not_exist")

    entries = notebook.entries()
    assert len(entries) == 1
    assert entries[0].capability == "task.read"
    assert entries[0].resource == "tsk_does_not_exist"
    # It did not succeed, and the record says so honestly.
    assert entries[0].outcome == "error"


def test_records_are_numbered_in_the_order_they_happened(running_skill):
    """
    INVARIANT I-5.

    The numbering is evidence. Some security problems are about the SEQUENCE of two
    innocent actions, so the order must be exact.
    """
    context, notebook = running_skill

    context.tasks.list("all")
    context.tasks.add("Second thing")
    context.tasks.list("done")

    entries = notebook.entries()
    assert [entry.seq for entry in entries] == [1, 2, 3]
    assert [entry.capability for entry in entries] == [
        "task.read",
        "task.write",
        "task.read",
    ]


def test_the_notebook_cannot_be_edited_from_outside(running_skill):
    """
    Handing out a copy means nobody can quietly add, remove or reorder records. The
    order is evidence, and evidence must not be editable.
    """
    context, notebook = running_skill
    context.tasks.list("all")

    borrowed = notebook.entries()
    borrowed.clear()

    assert len(notebook.entries()) == 1


# --- The fingerprints that make later proof possible -----------------------------


def test_a18_reading_tasks_records_fingerprints(running_skill):
    """
    ACCEPTANCE TEST A-18 (first half) - decision S-8.

    Reading the task list records a fingerprint of the whole set AND of each
    individual item. Those fingerprints are what make it possible later to prove
    that a specific piece of information was sent somewhere, without keeping a
    second copy of the user's private data in the security records.
    """
    context, notebook = running_skill

    tasks = context.tasks.list("all")
    record = notebook.entries()[0]

    assert record.detail["count"] == len(tasks)
    assert len(record.detail["sha256"]) == 64
    assert len(record.detail["item_digests"]) == len(tasks)
    assert all(len(digest) == 64 for digest in record.detail["item_digests"])


def test_fingerprints_of_the_same_data_match(running_skill):
    """
    Reading the same information twice gives the same fingerprint. Without that, no
    later comparison could ever prove two things were the same data.
    """
    context, notebook = running_skill

    context.tasks.list("all")
    context.tasks.list("all")

    first, second = notebook.entries()
    assert first.detail["sha256"] == second.detail["sha256"]


# --- Normal behaviour ------------------------------------------------------------


def test_the_channel_actually_reads_the_tasks(running_skill):
    """The channel is not just bookkeeping - it really does the work."""
    context, _ = running_skill

    tasks = context.tasks.list("all")

    assert len(tasks) == 8
    assert all("title" in task for task in tasks)


def test_scopes_narrow_the_result(running_skill):
    """"open" and "done" work through the channel just as they do elsewhere."""
    context, _ = running_skill

    everything = context.tasks.list("all")
    open_only = context.tasks.list("open")
    done_only = context.tasks.list("done")

    assert len(open_only) + len(done_only) == len(everything)


def test_adding_a_task_through_the_channel_records_the_new_id(running_skill):
    """
    The record starts out saying "some task" and is updated to name the actual item
    once it exists, so the report points at a real thing.
    """
    context, notebook = running_skill

    created = context.tasks.add("Written through the channel")

    assert notebook.entries()[0].resource == created["id"]
    assert any(task.title == "Written through the channel" for task in store.load_tasks())


def test_changing_a_missing_task_is_recorded_as_an_error(running_skill):
    """Asking to change something that is not there is a mistake, not an attack."""
    context, notebook = running_skill

    with pytest.raises(CapabilityRefused):
        context.tasks.update("tsk_missing", done=True)

    assert notebook.entries()[0].outcome == "error"


def test_leaving_a_note_needs_no_permission(running_skill):
    """
    A skill leaving a message for a human costs no permission and records nothing -
    a message cannot reach anything.
    """
    context, notebook = running_skill

    context.log.info("just saying hello")

    assert len(notebook) == 0
    assert context.log.messages == ["just saying hello"]
