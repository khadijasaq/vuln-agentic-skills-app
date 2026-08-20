"""
Checks for scope matching (app/skills/scope.py).

Scopes are the fine print on a permission. Getting these rules wrong would quietly
widen every permission in the app, so they are tested closely - especially the
difference between "*" (within one folder) and "**" (across folders).

Covers: feature spec section 6, decisions S-24, S-25 and S-35.
"""

from __future__ import annotations

import pytest

from app.skills.scope import ScopeMatcher


# --- Task names, setting names: exact comparison ---------------------------------


def test_a_task_scope_of_star_matches_anything():
    assert ScopeMatcher.matches(["*"], "tsk_123", "task_glob") is True
    assert ScopeMatcher.matches(["*"], "*", "task_glob") is True


def test_a_specific_task_scope_matches_only_that_task():
    assert ScopeMatcher.matches(["tsk_123"], "tsk_123", "task_glob") is True
    assert ScopeMatcher.matches(["tsk_123"], "tsk_999", "task_glob") is False


def test_setting_names_are_case_sensitive():
    """TASKBOT_MODEL and taskbot_model are different settings."""
    assert ScopeMatcher.matches(["TASKBOT_*"], "TASKBOT_MODEL", "key_glob") is True
    assert ScopeMatcher.matches(["TASKBOT_*"], "taskbot_model", "key_glob") is False


# --- Website addresses: case does not matter -------------------------------------


def test_host_matching_ignores_capitals():
    assert ScopeMatcher.matches(["127.0.0.1"], "127.0.0.1", "host_glob") is True
    assert ScopeMatcher.matches(["Example.COM"], "example.com", "host_glob") is True


def test_host_matching_rejects_a_different_host():
    assert ScopeMatcher.matches(["127.0.0.1"], "evil.example.com", "host_glob") is False


# --- File paths: the two star forms differ ---------------------------------------


def test_single_star_stays_inside_one_folder():
    """
    THE RULE THAT MATTERS MOST HERE.

    "data/*.txt" means text files directly inside data, NOT files in sub-folders.
    If a single star crossed folders, every narrow permission would silently become
    a sweeping one.
    """
    assert ScopeMatcher.matches(["data/*.txt"], "data/notes.txt", "path_glob") is True
    assert ScopeMatcher.matches(["data/*.txt"], "data/deep/notes.txt", "path_glob") is False


def test_double_star_crosses_folders():
    """"data/**" covers everything underneath data, however deeply nested."""
    assert ScopeMatcher.matches(["data/**"], "data/notes.txt", "path_glob") is True
    assert ScopeMatcher.matches(["data/**"], "data/a/b/c/notes.txt", "path_glob") is True


def test_double_star_also_covers_the_folder_itself():
    """
    DECISION S-35.

    "data/**" covers the folder itself as well as everything inside it. This is how
    gitignore and most other glob tools behave, and it is what someone writing
    "data/**" plainly means. The rule matters because it decides whether a path
    counts as "inside what the skill declared" - which changes whether a finding is
    raised.
    """
    assert ScopeMatcher.matches(["data/**"], "data", "path_glob") is True


def test_a_path_outside_the_scope_does_not_match():
    assert ScopeMatcher.matches(["data/**"], "skills/catalogue/x.py", "path_glob") is False
    assert ScopeMatcher.matches(["data/notes/**"], "data/secrets.txt", "path_glob") is False


def test_windows_style_backslashes_are_understood():
    """Paths written with backslashes must compare the same as forward slashes."""
    assert ScopeMatcher.matches(["data/**"], "data\\notes.txt", "path_glob") is True


def test_dots_in_patterns_are_literal():
    """
    A dot must mean a dot. If it were treated as pattern syntax, "notes.txt" would
    also match "notesXtxt" and permissions would be wider than they look.
    """
    assert ScopeMatcher.matches(["data/notes.txt"], "data/notesXtxt", "path_glob") is False


# --- Special cases ---------------------------------------------------------------


def test_empty_limits_allow_nothing():
    """
    Declaring no limits at all grants nothing. That is the safe reading: it must
    never be mistaken for "unlimited".
    """
    assert ScopeMatcher.matches([], "anything", "path_glob") is False


def test_capabilities_with_no_official_channel_never_match():
    """
    "proc.spawn" has no official way to do it, so there is no such thing as being
    inside its limits - doing it at all is what gets reported.
    """
    assert ScopeMatcher.matches(["*"], "cmd.exe", "none") is False


def test_several_patterns_match_if_any_one_does():
    assert ScopeMatcher.matches(["data/a/**", "data/b/**"], "data/b/x.txt", "path_glob") is True
    assert ScopeMatcher.matches(["data/a/**", "data/b/**"], "data/c/x.txt", "path_glob") is False


# --- "No limit at all" recognition -----------------------------------------------


@pytest.mark.parametrize("unbounded", [["*"], ["**"]])
def test_unbounded_scopes_are_recognised(unbounded):
    """Spotting these is how the over-powered check finds a skill with the keys to everything."""
    assert ScopeMatcher.is_unbounded(unbounded) is True


@pytest.mark.parametrize("bounded", [["data/**"], ["*", "data/**"], [], ["tsk_1"]])
def test_narrower_scopes_are_not_unbounded(bounded):
    """A list with a real limit in it is not "anywhere at all", even if it also contains a star."""
    assert ScopeMatcher.is_unbounded(bounded) is False


# --- Comparing against the yardstick ---------------------------------------------


def test_anything_is_within_an_unlimited_yardstick():
    """If a kind of skill may reach anywhere, nothing it declares can exceed that."""
    assert ScopeMatcher.is_broader_than(["data/**"], ["*"], "path_glob") is False
    assert ScopeMatcher.is_broader_than(["*"], ["*"], "path_glob") is False


def test_asking_for_everything_when_the_yardstick_is_narrow_is_broader():
    """
    The clearest over-reach: the skill wants everywhere, its category says one folder.
    """
    assert ScopeMatcher.is_broader_than(["*"], ["data/skills/**"], "path_glob") is True


def test_a_scope_inside_the_yardstick_is_not_broader():
    assert (
        ScopeMatcher.is_broader_than(["data/skills/mine/**"], ["data/skills/**"], "path_glob")
        is False
    )


def test_a_scope_reaching_outside_the_yardstick_is_broader():
    assert ScopeMatcher.is_broader_than(["data/**"], ["data/skills/**"], "path_glob") is True


def test_a_different_host_than_the_yardstick_allows_is_broader():
    assert ScopeMatcher.is_broader_than(["evil.example.com"], ["127.0.0.1"], "host_glob") is True
    assert ScopeMatcher.is_broader_than(["127.0.0.1"], ["127.0.0.1"], "host_glob") is False


def test_declaring_nothing_is_never_broader():
    """No declared limits means no reach at all, which cannot exceed anything."""
    assert ScopeMatcher.is_broader_than([], ["data/**"], "path_glob") is False
