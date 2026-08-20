"""
Checks for the app's memory (app/storage/store.py) and the record shapes.

Covers: feature spec sections 3.1, 3.2, 3.8, 3.9, 4.2; requirements FR-1.2, FR-2.2,
FR-4.5, FR-5.1; and the "same problem seen twice" rule (TDD decision D-11).
"""

from __future__ import annotations

import re

import pytest

from app.storage import store
from app.storage.models import ActivityEntry, Finding, SkillInvocationRecord, Task


# --- Identifiers and timestamps --------------------------------------------------


def test_identifiers_are_unique():
    """Ten thousand identifiers in a row, no repeats."""
    made = {store.new_id("tsk") for _ in range(10_000)}
    assert len(made) == 10_000


def test_identifiers_sort_into_creation_order():
    """
    Sorting identifiers alphabetically gives the order they were created, which
    makes raw data files easy to read without any extra tooling.

    The guarantee is at millisecond resolution (decision S-4). Two identifiers made
    within the same millisecond have random endings and no defined order between
    them, so this waits a moment between each one to test the real promise.
    """
    import time as _time

    first = store.new_id("act")
    _time.sleep(0.002)
    second = store.new_id("act")
    _time.sleep(0.002)
    third = store.new_id("act")

    assert sorted([third, first, second]) == [first, second, third]


def test_identifier_timestamps_never_go_backwards():
    """
    Even inside a single millisecond, the time portion of an identifier must never
    decrease - that is what keeps a whole file of them roughly in order.
    """
    times = [int(store.new_id("act").split("_")[1][:13]) for _ in range(500)]
    assert times == sorted(times)


def test_identifiers_carry_their_prefix():
    """The prefix says what kind of thing an identifier refers to."""
    assert store.new_id("fnd").startswith("fnd_")
    assert store.new_id("inv").startswith("inv_")


def test_timestamp_format_is_the_agreed_one():
    """World standard time, milliseconds, ending in Z (decision S-5)."""
    stamp = store.now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", stamp)


def test_timestamps_can_be_compared_as_plain_text():
    """
    Later timestamps must sort after earlier ones as ordinary text. Several filters
    rely on this instead of parsing dates.
    """
    earlier = "2026-08-21T14:03:11.482Z"
    later = "2026-08-21T14:03:11.483Z"
    assert earlier < later


# --- Record shapes ---------------------------------------------------------------


def test_every_record_carries_a_schema_version():
    """Consumers use this to know which format they are reading (FR-6.3)."""
    task = Task(id="tsk_1", title="x", created_at=store.now_iso())
    assert task.schema_version == 1

    entry = ActivityEntry(id="act_1", ts=store.now_iso(), user_message="a", reply="b")
    assert entry.schema_version == 1


def test_records_survive_a_round_trip_through_json():
    """Saving then loading a record must give back exactly the same thing."""
    original = Task(id="tsk_1", title="Renew passport", created_at=store.now_iso())
    revived = Task(**original.model_dump())
    assert revived == original


# --- Tasks -----------------------------------------------------------------------


def test_adding_and_reading_tasks(tmp_settings):
    """The basic promise: what you add is what you read back."""
    store.add_task("Buy milk")
    store.add_task("Call the bank", notes="ask about the fee")

    tasks = store.load_tasks()
    assert [task.title for task in tasks] == ["Buy milk", "Call the bank"]
    assert tasks[1].notes == "ask about the fee"
    assert all(task.done is False for task in tasks)


def test_tasks_survive_a_restart(tmp_settings):
    """
    Saved information must outlive the running program (FR-1.2). Reading the file
    again from scratch stands in for restarting the app.
    """
    created = store.add_task("Persisted item")
    reloaded = store.load_tasks()
    assert [task.id for task in reloaded] == [created.id]


def test_marking_a_task_done_records_when(tmp_settings):
    """Finishing a task stamps the time; un-finishing it clears the stamp again."""
    task = store.add_task("Write the report")
    assert task.completed_at is None

    finished = store.update_task(task.id, done=True)
    assert finished.done is True
    assert finished.completed_at is not None

    reopened = store.update_task(task.id, done=False)
    assert reopened.done is False
    # The record must not keep claiming a completion that was undone.
    assert reopened.completed_at is None


def test_updating_only_changes_what_you_asked_for(tmp_settings):
    """Fields you do not mention are left exactly as they were."""
    task = store.add_task("Original title", notes="original notes")
    updated = store.update_task(task.id, title="New title")

    assert updated.title == "New title"
    assert updated.notes == "original notes"


def test_updating_a_missing_task_is_a_clear_error(tmp_settings):
    """Asking for something that is not there fails loudly, not silently."""
    with pytest.raises(store.TaskNotFound):
        store.update_task("tsk_does_not_exist", title="x")


def test_deleting_a_task(tmp_settings):
    """Deleting removes exactly one task and leaves the rest alone."""
    keep = store.add_task("Keep me")
    remove = store.add_task("Remove me")

    store.delete_task(remove.id)

    remaining = [task.id for task in store.load_tasks()]
    assert remaining == [keep.id]

    with pytest.raises(store.TaskNotFound):
        store.delete_task(remove.id)


def test_filtering_tasks_by_scope(tmp_settings):
    """"open", "done" and "all" narrow the list as expected."""
    first = store.add_task("Open one")
    second = store.add_task("Done one")
    store.update_task(second.id, done=True)

    tasks = store.load_tasks()
    assert [t.id for t in store.filter_tasks(tasks, "open")] == [first.id]
    assert [t.id for t in store.filter_tasks(tasks, "done")] == [second.id]
    assert len(store.filter_tasks(tasks, "all")) == 2
    # Anything unrecognised is treated as "all" rather than returning nothing.
    assert len(store.filter_tasks(tasks, "nonsense")) == 2


# --- Installed skills ------------------------------------------------------------


def test_installing_and_removing_skills(tmp_settings):
    """Switching skills on and off is remembered, in install order."""
    store.set_installed("alpha", True)
    store.set_installed("beta", True)
    assert store.load_installed().installed == ["alpha", "beta"]

    store.set_installed("alpha", False)
    assert store.load_installed().installed == ["beta"]


def test_installing_twice_changes_nothing(tmp_settings):
    """Doing the same thing twice is harmless (the operation is idempotent)."""
    store.set_installed("alpha", True)
    store.set_installed("alpha", True)
    assert store.load_installed().installed == ["alpha"]

    store.set_installed("never-installed", False)
    assert store.load_installed().installed == ["alpha"]


def test_nothing_is_installed_on_a_fresh_lab(tmp_settings):
    """
    A brand new lab starts with zero skills switched on (TDD section 14, Q-6). This
    is what makes the safe baseline visible before anything is added.
    """
    assert store.load_installed().installed == []
    assert store.is_installed("task_summary") is False


# --- Activity log ----------------------------------------------------------------


def _activity(entry_id: str, ts: str, skill_id: str | None = None) -> ActivityEntry:
    """Small helper to build an activity entry for these tests."""
    invoked = None
    if skill_id:
        invoked = SkillInvocationRecord(
            skill_id=skill_id, skill_version="1.0.0", invocation_id="inv_1"
        )
    return ActivityEntry(
        id=entry_id, ts=ts, user_message="hello", reply="hi", skill_invoked=invoked
    )


def test_activity_is_appended_oldest_first(tmp_settings):
    """Entries read back in the order they happened."""
    store.append_activity(_activity("act_1", "2026-08-21T10:00:00.000Z"))
    store.append_activity(_activity("act_2", "2026-08-21T11:00:00.000Z"))

    assert [entry.id for entry in store.load_activity()] == ["act_1", "act_2"]


def test_activity_limit_keeps_the_most_recent(tmp_settings):
    """A limit trims from the front, keeping the newest entries."""
    for index in range(5):
        store.append_activity(_activity(f"act_{index}", f"2026-08-21T1{index}:00:00.000Z"))

    recent = store.load_activity(limit=2)
    assert [entry.id for entry in recent] == ["act_3", "act_4"]


def test_activity_filters_by_skill_and_time(tmp_settings):
    """Both filters narrow the list correctly."""
    store.append_activity(_activity("act_1", "2026-08-21T10:00:00.000Z", "alpha"))
    store.append_activity(_activity("act_2", "2026-08-21T11:00:00.000Z", "beta"))
    store.append_activity(_activity("act_3", "2026-08-21T12:00:00.000Z"))

    by_skill = store.load_activity(skill_id="beta")
    assert [entry.id for entry in by_skill] == ["act_2"]

    by_time = store.load_activity(since="2026-08-21T11:00:00.000Z")
    assert [entry.id for entry in by_time] == ["act_2", "act_3"]


# --- Findings and the "seen twice" rule ------------------------------------------


def _finding(resource: str = "data/notes.txt", skill_id: str = "demo") -> Finding:
    """Build a finding for these tests. Not tied to any real skill."""
    stamp = store.now_iso()
    return Finding(
        id=store.new_id("fnd"),
        type="UNDECLARED_CAPABILITY",
        ast_id="AST04",
        ast_name="Insecure Metadata",
        axis="truthfulness",
        severity="high",
        skill_id=skill_id,
        skill_version="1.0.0",
        observed={"capability": "fs.read", "resource": resource},
        first_seen=stamp,
        last_seen=stamp,
    )


def test_a_new_finding_is_stored(tmp_settings):
    """The first time a problem is seen, it is recorded as a new finding."""
    stored, was_created = store.upsert_finding(_finding())

    assert was_created is True
    assert len(store.load_findings()) == 1
    assert stored.occurrences == 1


def test_the_same_problem_twice_becomes_one_finding_with_a_count(tmp_settings):
    """
    THE DEDUPLICATION RULE (TDD decision D-11).

    Fifty repeats of one problem must not bury everything else in the list.
    """
    first, created_first = store.upsert_finding(_finding())
    second, created_second = store.upsert_finding(_finding())

    assert created_first is True
    assert created_second is False
    assert len(store.load_findings()) == 1
    assert second.occurrences == 2
    # The identifier and the first-seen time must never change, because anything
    # already pointing at this finding has to keep working.
    assert second.id == first.id
    assert second.first_seen == first.first_seen


def test_different_problems_stay_separate(tmp_settings):
    """A different file, or a different skill, is a genuinely different problem."""
    store.upsert_finding(_finding(resource="data/one.txt"))
    store.upsert_finding(_finding(resource="data/two.txt"))
    store.upsert_finding(_finding(resource="data/one.txt", skill_id="other"))

    assert len(store.load_findings()) == 3


def test_findings_accumulate_across_sessions(tmp_settings):
    """
    Findings build up over time rather than being wiped each run (FR-4.5).
    """
    store.upsert_finding(_finding(resource="data/one.txt"))
    reloaded = store.load_findings()
    store.upsert_finding(_finding(resource="data/two.txt"))

    assert len(reloaded) == 1
    assert len(store.load_findings()) == 2
