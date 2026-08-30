"""
Checks that the app starts up in the right order (app/main.py).

One step here is genuinely security-critical. The watcher that records what skills
do can only see activity that happens AFTER it is switched on, and Python does not
allow it to be removed once installed. So it must run before anything that could
load a skill. This test locks that ordering in place so a future change cannot
quietly move it later.

Covers: feature spec section 5.1, decision S-15, build-plan step 1.9.
"""

from __future__ import annotations

import pytest

from app import main


def test_the_startup_steps_are_in_the_documented_order():
    """The exact running order from decision S-15."""
    names = [name for name, _ in main.STARTUP_STEPS]

    assert names == [
        "install_audit_hook",
        "prepare_data_folder",
        "seed_tasks",
        # Added with AST05: the mock team hub's document is put in place the same way
        # the starter tasks are - copied in only if it is not already there, so a
        # hand-edited document survives a restart.
        "seed_hub_document",
        # Added with AST02: the components a skill can be built on are put in the mock
        # registry the same way, and with the same "only if absent" rule - so a build
        # someone has swapped by hand to try something survives a restart.
        "seed_registry_components",
        "load_policy",
        "discover_skills",
    ]


def test_the_watcher_is_switched_on_before_any_skill_can_load():
    """
    THE ORDERING RULE THAT MATTERS.

    Installing the watcher must come before discovering or loading skills. If a
    skill were loaded first, anything it did while being imported would go
    unrecorded - and a skill can run code simply by being imported.
    """
    names = [name for name, _ in main.STARTUP_STEPS]

    assert names.index("install_audit_hook") < names.index("discover_skills")
    # It is also the very first thing after settings are read.
    assert names[0] == "install_audit_hook"


def test_policy_is_loaded_before_skills_are_discovered():
    """
    Skill descriptions are checked against the capability list and the category
    baselines, so those files must be loaded first or every skill would look invalid.
    """
    names = [name for name, _ in main.STARTUP_STEPS]
    assert names.index("load_policy") < names.index("discover_skills")


def test_running_startup_creates_the_data_folders(tmp_settings):
    """After startup the folders every later step writes into exist."""
    main.run_startup(tmp_settings)

    assert tmp_settings.data_dir.exists()
    assert tmp_settings.markers_dir.exists()
    assert (tmp_settings.collector_dir / "inbox").exists()
    assert tmp_settings.hub_dir.exists()
    assert tmp_settings.registry_dir.exists()


def test_running_startup_seeds_a_fresh_lab(tmp_settings):
    """Starting a brand new lab leaves it with the starter to-do list."""
    main.run_startup(tmp_settings)

    from app.storage import store

    assert len(store.load_tasks()) == 8


def test_a_broken_policy_file_stops_the_app(tmp_settings, tmp_path, monkeypatch):
    """
    A damaged policy file must be fatal.

    The findings engine compares skill behaviour against these files. If they were
    silently ignored the app would report no problems at all - which looks exactly
    like a clean result. Refusing to start is far safer than lying.
    """
    broken_policy = tmp_path / "broken-policy"
    broken_policy.mkdir()
    (broken_policy / "capability_vocabulary.json").write_text("{ not json", encoding="utf-8")
    (broken_policy / "capability_baselines.json").write_text("{}", encoding="utf-8")

    from dataclasses import replace

    settings = replace(tmp_settings, policy_dir=broken_policy)

    with pytest.raises(Exception):
        main.run_startup(settings)
