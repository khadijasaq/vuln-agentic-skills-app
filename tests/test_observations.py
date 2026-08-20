"""
Checks for the notebook the app writes in while a skill runs
(app/monitor/observations.py).

The order of the records is evidence, not decoration. Some security problems are not
about any single action but about the sequence of two innocent-looking ones: reading
the task list is fine, sending a message locally is fine, doing the first and then
the second is theft. Proving that needs an exact, unalterable order.

Covers: feature spec sections 3.7 and 5.7; TDD section 3.1; decisions D-7, S-8 and
S-26; invariant I-5.
"""

from __future__ import annotations

import threading

from app.monitor.observations import ObservationLog, digest_of, size_of


def test_records_are_numbered_from_one_and_go_up():
    """Line numbers start at 1 and only ever increase."""
    notebook = ObservationLog("inv_1")

    notebook.record(capability="task.read", resource="*")
    notebook.record(capability="fs.read", resource="data/notes.txt")
    notebook.record(capability="net.outbound", resource="http://127.0.0.1/x")

    assert [entry.seq for entry in notebook.entries()] == [1, 2, 3]


def test_records_keep_the_order_they_were_written(tmp_path):
    """
    INVARIANT I-5.

    The order is never rearranged, however the records are read back.
    """
    notebook = ObservationLog("inv_1")
    for index in range(20):
        notebook.record(capability="task.read", resource=f"item-{index}")

    resources = [entry.resource for entry in notebook.entries()]
    assert resources == [f"item-{index}" for index in range(20)]


def test_every_record_belongs_to_its_own_skill_run():
    """
    Each run gets its own notebook, so two skills running at the same time can never
    have their records mixed up.
    """
    first = ObservationLog("inv_aaa")
    second = ObservationLog("inv_bbb")

    first.record(capability="task.read", resource="*")
    second.record(capability="fs.read", resource="x")

    assert first.entries()[0].invocation_id == "inv_aaa"
    assert second.entries()[0].invocation_id == "inv_bbb"
    # And each notebook starts numbering from 1 independently.
    assert first.entries()[0].seq == 1
    assert second.entries()[0].seq == 1


def test_a_refusal_updates_the_existing_record(tmp_path):
    """
    DECISION S-26 - "amend, not replace".

    When a request is refused, the note already written is UPDATED. It is not
    replaced by a new note at the bottom. If it were, a refused attempt would appear
    to have happened later than it really did, and anything reading the order of
    events would be looking at a false story.
    """
    notebook = ObservationLog("inv_1")

    first = notebook.record(capability="task.read", resource="*")
    attempt = notebook.record(capability="net.outbound", resource="https://evil.example.com")
    notebook.record(capability="task.read", resource="*")

    notebook.mark_refused(attempt, "non_local_host")

    entries = notebook.entries()
    # Still three records, not four.
    assert len(entries) == 3
    # The refused one is still second, exactly where it happened.
    assert entries[1].seq == 2
    assert entries[1].outcome == "refused"
    assert entries[1].refusal_reason == "non_local_host"
    # The others are untouched.
    assert entries[0].outcome == "ok"
    assert entries[2].outcome == "ok"


def test_an_error_is_recorded_without_reordering_either():
    """A request that was allowed but went wrong is marked in place too."""
    notebook = ObservationLog("inv_1")

    attempt = notebook.record(capability="fs.read", resource="missing.txt")
    notebook.mark_error(attempt, "file_not_found")

    assert notebook.entries()[0].outcome == "error"


def test_records_default_to_coming_from_the_official_channel():
    """
    Where a record came from matters: going around the app is a deliberate act and
    is reported as its own kind of problem.
    """
    notebook = ObservationLog("inv_1")
    notebook.record(capability="task.read", resource="*")
    assert notebook.entries()[0].source == "broker"

    notebook.record(capability="fs.read", resource="x", source="audit_hook")
    assert notebook.entries()[1].source == "audit_hook"


def test_the_notebook_cannot_be_edited_from_outside():
    """
    Reading the notebook hands out a copy. Nobody outside can add, remove or reorder
    records - the order is evidence.
    """
    notebook = ObservationLog("inv_1")
    notebook.record(capability="task.read", resource="*")

    borrowed = notebook.entries()
    borrowed.append("something invented")
    borrowed.clear()

    assert len(notebook.entries()) == 1


def test_writing_from_several_threads_loses_nothing():
    """
    Two watchers can write at the same time - the official channel and the
    process-wide one - so adding a record is protected.
    """
    notebook = ObservationLog("inv_1")

    def add_many(worker: int) -> None:
        for step in range(50):
            notebook.record(capability="task.read", resource=f"{worker}-{step}")

    threads = [threading.Thread(target=add_many, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    entries = notebook.entries()
    assert len(entries) == 8 * 50
    # Every line number is used exactly once.
    assert sorted(entry.seq for entry in entries) == list(range(1, 8 * 50 + 1))


# --- Fingerprints ----------------------------------------------------------------


def test_the_same_data_always_gives_the_same_fingerprint():
    """Without this, no later comparison could prove two things were the same data."""
    assert digest_of({"a": 1, "b": 2}) == digest_of({"b": 2, "a": 1})


def test_different_data_gives_a_different_fingerprint():
    assert digest_of({"a": 1}) != digest_of({"a": 2})


def test_a_fingerprint_does_not_contain_the_original_data():
    """
    We record fingerprints instead of the data itself, so the security records never
    become a second copy of the user's private information.
    """
    secret = {"title": "Renew passport", "notes": "passport number 123456789"}
    fingerprint = digest_of(secret)

    assert "passport" not in fingerprint
    assert "123456789" not in fingerprint
    assert len(fingerprint) == 64


def test_size_is_measured_in_bytes():
    assert size_of({"a": 1}) == len('{"a": 1}'.encode("utf-8"))


def test_the_notebook_reports_how_full_it_is():
    notebook = ObservationLog("inv_1")
    assert len(notebook) == 0

    notebook.record(capability="task.read", resource="*")
    assert len(notebook) == 1


def test_records_convert_to_plain_data_for_saving():
    """The activity log stores these as ordinary JSON, so they must convert cleanly."""
    notebook = ObservationLog("inv_1")
    notebook.record(capability="task.read", resource="*", detail={"count": 3})

    as_data = notebook.as_dicts()
    assert as_data[0]["capability"] == "task.read"
    assert as_data[0]["detail"]["count"] == 3
    assert as_data[0]["seq"] == 1
