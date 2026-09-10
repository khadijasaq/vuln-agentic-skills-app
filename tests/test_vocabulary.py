"""
Checks for the shared capability list (policy/capability_vocabulary.json).

This file is the shared vocabulary: skills use these words to say what they need,
and the watchers use the same words to record what actually happened. If the two
sides ever stopped using identical words, the comparison at the heart of the
security checks would silently compare nothing.

Covers: feature spec section 3.3, TDD section 2.3, decision D-4.
"""

from __future__ import annotations

from app.skills.manifest import load_vocabulary


def test_all_seven_capabilities_are_present(tmp_settings):
    """The documented vocabulary, no more and no less."""
    vocabulary = load_vocabulary(
        tmp_settings.policy_dir / "capability_vocabulary.json"
    )

    assert vocabulary.ids() == {
        "task.read",
        "task.write",
        "fs.read",
        "fs.write",
        "net.outbound",
        "env.read",
        "proc.spawn",
    }


def test_each_capability_says_what_shape_its_limits_take(tmp_settings):
    """
    The "scope kind" decides how limits are compared - a file path is matched
    differently from a website address, and getting that wrong would widen
    permissions.
    """
    vocabulary = load_vocabulary(
        tmp_settings.policy_dir / "capability_vocabulary.json"
    )

    expected = {
        "task.read": "task_glob",
        "task.write": "task_glob",
        "fs.read": "path_glob",
        "fs.write": "path_glob",
        "net.outbound": "host_glob",
        "env.read": "key_glob",
        "proc.spawn": "none",
    }
    for capability_id, scope_kind in expected.items():
        assert vocabulary.scope_kind(capability_id) == scope_kind


def test_starting_another_program_has_no_official_channel(tmp_settings):
    """
    DECISION D-4.

    There is deliberately no supported way for a skill to start another program. The
    capability exists in the vocabulary only so that doing it anyway has a name to be
    reported under - a skill that starts a program has, by definition, gone around
    the app.
    """
    vocabulary = load_vocabulary(
        tmp_settings.policy_dir / "capability_vocabulary.json"
    )

    assert vocabulary.get("proc.spawn").brokered is False
    # Everything else does have an official channel.
    for capability_id in vocabulary.ids() - {"proc.spawn"}:
        assert vocabulary.get(capability_id).brokered is True


def test_every_capability_is_explained_in_plain_words(tmp_settings):
    """
    These descriptions are shown to people deciding whether to install a skill, so
    each one has to be a real sentence rather than a placeholder.
    """
    vocabulary = load_vocabulary(
        tmp_settings.policy_dir / "capability_vocabulary.json"
    )

    for capability_id in vocabulary.ids():
        description = vocabulary.get(capability_id).description
        assert len(description) > 10


def test_an_unknown_capability_is_reported_as_unknown(tmp_settings):
    """
    Looking up something that is not in the list gives back nothing, and its limit
    shape is "none" - which never matches anything. That is the safe answer when we
    do not understand what we are looking at.
    """
    vocabulary = load_vocabulary(
        tmp_settings.policy_dir / "capability_vocabulary.json"
    )

    assert vocabulary.get("made.up.capability") is None
    assert vocabulary.scope_kind("made.up.capability") == "none"
