"""
Checks for the settings file (app/config.py).

The single most important check here is the safety catch: TaskBot is deliberately
insecure, so it must refuse to listen on a network address that other computers can
reach. If that check ever stops working, a practice target could be exposed to a
real network - so we test it from several angles.

Covers: feature spec section 2.2, decision S-2, acceptance test A-11 (first half),
requirement FR-7.6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config


def test_defaults_are_the_documented_ones(monkeypatch):
    """With no environment variables set, every dial falls back to its documented default."""
    for name in [
        "TASKBOT_MODEL",
        "GROQ_API_KEY",
        "GROQ_BASE_URL",
        "TASKBOT_HOST",
        "TASKBOT_PORT",
        "TASKBOT_DATA_DIR",
        "TASKBOT_SKILLS_DIR",
        "TASKBOT_POLICY_DIR",
        "TASKBOT_HISTORY_TURNS",
        "TASKBOT_UNUSED_GRANT_WINDOW",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = config.load_settings()

    assert settings.model == "openai/gpt-oss-120b"
    assert settings.groq_api_key == ""
    assert settings.groq_base_url == "https://api.groq.com/openai/v1"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.history_turns == 10
    assert settings.unused_grant_window == 5


def test_environment_variables_override_defaults(monkeypatch, tmp_path):
    """Anything set in the environment wins over the default."""
    monkeypatch.setenv("TASKBOT_MODEL", "some-other-model")
    monkeypatch.setenv("TASKBOT_PORT", "9001")
    monkeypatch.setenv("TASKBOT_DATA_DIR", str(tmp_path / "somewhere"))
    monkeypatch.setenv("TASKBOT_HISTORY_TURNS", "3")

    settings = config.load_settings()

    assert settings.model == "some-other-model"
    assert settings.port == 9001
    assert settings.history_turns == 3
    assert settings.data_dir == (tmp_path / "somewhere").resolve()


@pytest.mark.parametrize("safe_host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_addresses_are_accepted(monkeypatch, safe_host):
    """All three ways of saying "this machine only" are allowed."""
    monkeypatch.setenv("TASKBOT_HOST", safe_host)
    assert config.load_settings().host == safe_host


@pytest.mark.parametrize(
    "unsafe_host",
    ["0.0.0.0", "192.168.1.10", "10.0.0.5", "example.com", "::"],
)
def test_non_loopback_addresses_are_refused(monkeypatch, unsafe_host):
    """
    THE SAFETY CATCH (S-2, FR-7.6).

    Any address that another computer could reach must stop the app dead. This is
    the difference between a private practice target and an insecure app on a real
    network.
    """
    monkeypatch.setenv("TASKBOT_HOST", unsafe_host)

    with pytest.raises(config.ConfigError) as failure:
        config.load_settings()

    # The message must actually name the offending value, so whoever hit it knows
    # what to change.
    assert unsafe_host in str(failure.value)


def test_a_non_numeric_port_is_rejected_clearly(monkeypatch):
    """A typo in a number setting stops the app instead of being silently ignored."""
    monkeypatch.setenv("TASKBOT_PORT", "not-a-number")

    with pytest.raises(config.ConfigError) as failure:
        config.load_settings()

    assert "TASKBOT_PORT" in str(failure.value)


def test_derived_file_paths_all_sit_inside_the_data_folder(monkeypatch, tmp_path):
    """
    Every saved file is worked out from the data folder, so pointing the app at a
    different folder moves ALL of its state, with nothing left behind.
    """
    monkeypatch.setenv("TASKBOT_DATA_DIR", str(tmp_path / "lab"))
    settings = config.load_settings()

    for path in [
        settings.tasks_file,
        settings.installed_file,
        settings.findings_file,
        settings.activity_file,
        settings.markers_dir,
        settings.collector_dir,
        settings.hub_dir,
        settings.registry_dir,
    ]:
        assert Path(path).is_relative_to(settings.data_dir)


def test_settings_are_shared_and_resettable():
    """
    get_settings hands everyone the same copy, and reset_settings clears it.
    Tests rely on this to stay independent of one another.
    """
    first = config.get_settings()
    second = config.get_settings()
    assert first is second

    config.reset_settings()
    third = config.get_settings()
    assert third is not first


def test_blank_environment_variable_is_treated_as_unset(monkeypatch):
    """An empty value is almost always a mistake, so we fall back to the default."""
    monkeypatch.setenv("TASKBOT_MODEL", "   ")
    assert config.load_settings().model == "openai/gpt-oss-120b"
