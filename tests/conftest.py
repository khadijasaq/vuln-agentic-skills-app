"""
Shared setup for all the automated tests.

Pytest (the tool that runs our tests) automatically reads this file and makes
anything defined here available to every test. Think of it as the stage crew: it
sets up a clean, temporary workspace before each test and clears it away after.

The most important job here is making sure tests NEVER touch the real ./data
folder. Each test gets its own throwaway folder, so tests cannot interfere with
each other or with a real lab session.

Specification reference: build plan step 0.2.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import config


@pytest.fixture
def tmp_settings(tmp_path: pytest.TempPathFactory, monkeypatch) -> config.Settings:
    """
    Give one test a complete, isolated set of settings.

    In: pytest's built-in "tmp_path" (a brand new empty folder just for this test).
    Out: a Settings object whose data folder points at that empty folder.

    After the test finishes, the shared settings are cleared so the next test starts
    from scratch.
    """
    data_dir = Path(tmp_path) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Point every folder-related setting at the throwaway location. monkeypatch
    # undoes these environment changes automatically when the test ends.
    monkeypatch.setenv("TASKBOT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TASKBOT_HOST", "127.0.0.1")

    # The skills and policy folders stay pointed at the real repository copies,
    # because tests want to read the genuine capability list and the genuine
    # control skill, not invented ones.
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("TASKBOT_SKILLS_DIR", str(repo_root / "backend" / "skills"))
    monkeypatch.setenv("TASKBOT_POLICY_DIR", str(repo_root / "backend" / "policy"))

    config.reset_settings()
    settings = config.load_settings()
    config.set_settings(settings)

    yield settings

    # Clean up: forget these settings so a later test cannot accidentally inherit
    # a folder that has already been deleted.
    config.reset_settings()


@pytest.fixture
def repo_root() -> Path:
    """
    The top folder of this project.

    In: nothing. Out: a Path pointing at the repository root, so tests can find
    files like the skills folder without guessing relative paths.
    """
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_settings_between_tests():
    """
    Run automatically before and after EVERY test.

    It clears the shared settings so no test can leak its configuration into the
    next one. "autouse" means tests do not have to ask for it - it just happens.
    """
    config.reset_settings()
    yield
    config.reset_settings()
