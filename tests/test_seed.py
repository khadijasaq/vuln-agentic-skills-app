"""
Checks for the starter to-do list (app/storage/seed.py).

Covers: feature spec section 4.3, decision S-14, requirement FR-1.3, and the rule
that seeding never switches on a skill (TDD section 14, Q-6).
"""

from __future__ import annotations

from app.storage import seed, store


def test_a_fresh_lab_gets_eight_starter_tasks(tmp_settings):
    """A brand new lab is not empty - it looks like someone has been using it."""
    created = seed.seed_tasks_if_absent()

    assert created == 8
    assert len(store.load_tasks()) == 8


def test_three_starter_tasks_are_already_finished(tmp_settings):
    """
    A believable list has some things ticked off. An all-unfinished list looks
    artificial, which would undermine the realism the exercise depends on.
    """
    seed.seed_tasks_if_absent()
    tasks = store.load_tasks()

    assert sum(1 for task in tasks if task.done) == 3


def test_finished_tasks_record_when_they_were_finished(tmp_settings):
    """A task marked done must say when, or the record contradicts itself."""
    seed.seed_tasks_if_absent()

    for task in store.load_tasks():
        if task.done:
            assert task.completed_at is not None
        else:
            assert task.completed_at is None


def test_starter_tasks_are_spread_over_time(tmp_settings):
    """
    The creation dates must differ, so "your oldest unfinished task" is a real
    answer rather than a tie between eight identical timestamps.
    """
    seed.seed_tasks_if_absent()
    created_dates = [task.created_at for task in store.load_tasks()]

    assert len(set(created_dates)) == 8
    # And they are stored oldest first.
    assert created_dates == sorted(created_dates)


def test_seeding_does_not_run_twice(tmp_settings):
    """
    Restarting the app must never wipe out real work (decision S-14). Deleting the
    data folder is the deliberate way to start over.
    """
    seed.seed_tasks_if_absent()
    store.add_task("Something the user added themselves")

    created_second_time = seed.seed_tasks_if_absent()

    assert created_second_time == 0
    titles = [task.title for task in store.load_tasks()]
    assert "Something the user added themselves" in titles
    assert len(titles) == 9


def test_seeding_never_installs_a_skill(tmp_settings):
    """
    Seeding sets up to-do items only. The lab must still start with zero skills
    switched on, so the safe baseline is visible first (TDD section 14, Q-6).
    """
    seed.seed_tasks_if_absent()
    assert store.load_installed().installed == []


def test_starter_tasks_look_like_real_admin(tmp_settings):
    """
    The content must read as genuine personal admin (FR-1.3). If it said "test 1,
    test 2", watching it get stolen later would feel like a toy demonstration.
    """
    seed.seed_tasks_if_absent()
    titles = " ".join(task.title.lower() for task in store.load_tasks())

    assert "test" not in titles
    assert "foo" not in titles
    # Every starter task has a title and a real explanatory note.
    for task in store.load_tasks():
        assert len(task.title) > 5
        assert len(task.notes) > 5
