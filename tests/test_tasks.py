"""
Checks for the to-do baseline: adding, listing and completing tasks against the
real seeded data.

This is the app working as an ordinary, non-vulnerable assistant. It is worth
testing on its own because it is the baseline everything else is measured against -
if the plain to-do app were broken, no security conclusion drawn on top of it would
mean anything.

Covers: feature spec section 2.1 of the build plan, requirements FR-1.1 and FR-1.4.
"""

from __future__ import annotations

from app.storage import seed, store


def test_the_full_task_lifecycle_works(tmp_settings):
    """Add, read back, complete, and remove - the whole ordinary journey."""
    created = store.add_task("Book the venue", notes="needs to seat 40")

    fetched = [task for task in store.load_tasks() if task.id == created.id]
    assert len(fetched) == 1
    assert fetched[0].done is False

    store.update_task(created.id, done=True)
    assert [t for t in store.load_tasks() if t.id == created.id][0].done is True

    store.delete_task(created.id)
    assert [t for t in store.load_tasks() if t.id == created.id] == []


def test_tasks_work_on_top_of_the_seeded_list(tmp_settings):
    """
    Adding to a freshly seeded lab leaves the starter items intact. Someone trying
    the app for the first time should not lose the example data by using it.
    """
    seed.seed_tasks_if_absent()
    before = len(store.load_tasks())

    store.add_task("A brand new thing")

    assert len(store.load_tasks()) == before + 1


def test_open_and_done_counts_add_up(tmp_settings):
    """
    Every task is either open or done, never both and never neither. The control
    skill reports these counts, so they must be trustworthy.
    """
    seed.seed_tasks_if_absent()
    tasks = store.load_tasks()

    open_tasks = store.filter_tasks(tasks, "open")
    done_tasks = store.filter_tasks(tasks, "done")

    assert len(open_tasks) + len(done_tasks) == len(tasks)


def test_the_oldest_open_task_can_be_identified(tmp_settings):
    """
    "What have I been putting off longest?" needs a single clear answer, which
    requires the creation dates to be distinct and sortable.
    """
    seed.seed_tasks_if_absent()
    open_tasks = store.filter_tasks(store.load_tasks(), "open")

    oldest = min(open_tasks, key=lambda task: task.created_at)
    same_age = [task for task in open_tasks if task.created_at == oldest.created_at]

    assert len(same_age) == 1


def test_the_app_works_with_no_skills_installed(tmp_settings):
    """
    THE NON-VULNERABLE BASELINE (FR-1.4).

    With nothing installed the app is a complete, working to-do assistant, and there
    is nothing for the security machinery to report.
    """
    seed.seed_tasks_if_absent()

    assert store.load_installed().installed == []

    store.add_task("Works without any skills")
    assert len(store.load_tasks()) == 9

    # Nothing was watched, so nothing was found.
    assert store.load_findings() == []
