"""
Checks for the yardstick file (policy/capability_baselines.json).

This file answers "how much power does this KIND of skill reasonably need?". It is
what makes the over-powered check possible, and it is deliberately a separate input
from anything the skill said about itself.

Covers: feature spec section 3.6, TDD section 4.5, decisions D-9 and S-7.
"""

from __future__ import annotations

import pytest

from app.findings.baselines import load_baselines


def test_all_four_categories_ship(tmp_settings):
    """
    DECISION S-7.

    All four ship even though only "reporting" is used right now. They are policy
    data, not code, so having them in place keeps later work to a simple file edit.
    """
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")

    assert set(baselines) == {"reporting", "formatting", "reminder", "integration"}


def test_a_reporting_skill_may_only_read_tasks(tmp_settings):
    """
    The category the control skill belongs to. It reads to-do items and nothing
    else - which is exactly why the control skill can be proved to raise no findings.
    """
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")

    assert baselines["reporting"].allowed == ["task.read"]


def test_a_capability_not_mentioned_in_max_scope_may_reach_anywhere(tmp_settings):
    """
    Leaving a capability out of the limits is a decision, not an oversight: it means
    "this one is not narrowed". Being explicit about that prevents a missing line
    from accidentally becoming a hidden restriction.
    """
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")

    assert baselines["reporting"].limit_for("task.read") == ["*"]
    assert baselines["reminder"].limit_for("task.write") == ["*"]


def test_narrow_limits_are_read_correctly(tmp_settings):
    """
    Where a category does narrow a capability, that narrowing must load exactly as
    written - it is the line the over-powered check measures against.
    """
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")

    assert baselines["integration"].limit_for("net.outbound") == ["127.0.0.1"]
    assert baselines["formatting"].limit_for("fs.read") == ["data/skills/**"]


def test_a_broken_yardstick_file_raises(tmp_path):
    """
    A damaged file must fail loudly.

    If it were quietly ignored, the over-powered check would pass everything - which
    looks exactly like a clean result. For a security tool that is the most dangerous
    possible failure, so we refuse to continue instead.
    """
    broken = tmp_path / "capability_baselines.json"
    broken.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(Exception):
        load_baselines(broken)
