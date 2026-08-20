"""
Checks for the assistant's own built-in abilities (app/chat/builtins.py).

The behaviour checks are straightforward. The important ones are at the bottom: the
built-ins must never look like skills and must never produce anything the security
machinery would record. If they did, the findings list would fill with noise about
the app reporting itself.

Covers: build plan O-1 (approved), requirements FR-1.1 and FR-1.4, non-goal NG4,
acceptance tests A-2 and A-7 (amended wording).
"""

from __future__ import annotations

import pytest

from app.chat import builtins
from app.storage import store


# --- The tool descriptions -------------------------------------------------------


def test_exactly_two_built_in_abilities_are_offered():
    """Adding and listing. Nothing else is built in."""
    schemas = builtins.build_builtin_tool_schemas()
    names = [schema["function"]["name"] for schema in schemas]

    assert sorted(names) == ["add_task", "list_tasks"]


def test_tool_descriptions_have_the_shape_the_model_expects():
    """
    Each description needs a name, wording explaining when to use it, and a
    parameter description whose outermost type is "object".
    """
    for schema in builtins.build_builtin_tool_schemas():
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["name"]
        assert "Use when:" in function["description"]
        assert function["parameters"]["type"] == "object"


def test_the_app_can_tell_built_ins_from_skills():
    """This is how the conversation code decides which path to take."""
    assert builtins.is_builtin("add_task") is True
    assert builtins.is_builtin("list_tasks") is True
    assert builtins.is_builtin("task_summary") is False
    assert builtins.is_builtin("anything_else") is False


# --- Behaviour -------------------------------------------------------------------


def test_adding_a_task_actually_adds_it(tmp_settings):
    """The ability does the thing it says it does."""
    result = builtins.run_builtin("add_task", {"title": "Buy milk"})

    assert result.data["added"] is True
    assert [task.title for task in store.load_tasks()] == ["Buy milk"]
    assert "Buy milk" in result.summary


def test_adding_a_task_keeps_the_notes(tmp_settings):
    """Optional extra detail is stored alongside the title."""
    builtins.run_builtin("add_task", {"title": "Call bank", "notes": "ask about fees"})

    assert store.load_tasks()[0].notes == "ask about fees"


def test_adding_without_a_title_is_reported_not_crashed(tmp_settings):
    """
    A missing title comes back as a plain "did not do it" answer, so the assistant
    can just ask the user for one. Raising an error here would end the conversation.
    """
    result = builtins.run_builtin("add_task", {})

    assert result.data["added"] is False
    assert store.load_tasks() == []


def test_listing_tasks_returns_them(tmp_settings):
    """Listing gives back the tasks and a readable one-line summary."""
    builtins.run_builtin("add_task", {"title": "First"})
    builtins.run_builtin("add_task", {"title": "Second"})

    result = builtins.run_builtin("list_tasks", {"scope": "all"})

    assert result.data["count"] == 2
    assert "First" in result.summary and "Second" in result.summary


def test_listing_respects_open_and_done(tmp_settings):
    """The three scopes narrow the list as expected."""
    first = store.add_task("Still open")
    second = store.add_task("Finished")
    store.update_task(second.id, done=True)

    assert builtins.run_builtin("list_tasks", {"scope": "open"}).data["count"] == 1
    assert builtins.run_builtin("list_tasks", {"scope": "done"}).data["count"] == 1
    assert builtins.run_builtin("list_tasks", {"scope": "all"}).data["count"] == 2
    assert builtins.run_builtin("list_tasks", {"scope": "open"}).data["tasks"][0]["id"] == first.id


def test_listing_an_empty_list_reads_naturally(tmp_settings):
    """An empty list is a normal answer, not an error."""
    result = builtins.run_builtin("list_tasks", {})
    assert result.data["count"] == 0
    assert "empty" in result.summary.lower()


def test_asking_for_something_that_is_not_built_in_is_an_error(tmp_settings):
    """The conversation code should have checked first; this is the safety net."""
    with pytest.raises(ValueError):
        builtins.run_builtin("task_summary", {})


# --- The part that matters for security ------------------------------------------


def test_built_ins_record_no_observations_and_raise_no_findings(tmp_settings):
    """
    THE KEY CHECK (build plan O-1, non-goal NG4).

    Built-in abilities are the app doing its own job, not a skill under supervision.
    After using both of them, nothing may have been recorded and no security finding
    may exist. Otherwise a brand new lab would look like it had already found
    problems, and the "clean baseline" the whole exercise rests on would be gone.
    """
    builtins.run_builtin("add_task", {"title": "Something"})
    builtins.run_builtin("list_tasks", {"scope": "all"})

    assert store.load_findings() == []
    # No skill ran, so there is nothing in the activity log either.
    assert store.load_activity() == []


def test_built_ins_do_not_use_the_capability_broker(tmp_settings):
    """
    The built-ins must reach storage directly, never through the broker.

    We prove it by checking that no invocation is marked as being in progress while
    a built-in runs. The broker and the watcher both key off that marker, so if it
    is never set, neither of them is involved.
    """
    from app.monitor import audit_hook

    assert audit_hook.CURRENT_INVOCATION.get() is None

    builtins.run_builtin("add_task", {"title": "Check the markers"})

    # Still nothing in progress: the built-in did not open a supervised skill run.
    assert audit_hook.CURRENT_INVOCATION.get() is None
    assert audit_hook.IN_BROKER.get() is False


def test_built_ins_are_not_discoverable_as_skills(tmp_settings, repo_root):
    """
    A built-in must never show up in the skill store. If it did, someone could
    "uninstall" the app's own ability to manage tasks.
    """
    skills_folder = repo_root / "skills" / "catalogue"
    if not skills_folder.exists():
        pytest.skip("No skills folder yet at this stage of the build.")

    installed_names = {path.name for path in skills_folder.iterdir() if path.is_dir()}
    assert "add_task" not in installed_names
    assert "list_tasks" not in installed_names
