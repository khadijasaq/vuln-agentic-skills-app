"""
Settings for TaskBot.

This file answers one question: "what are the app's dials set to right now?"
Things like which AI model to use, which network address to listen on, and where
on disk to keep the saved information.

All the dials can be changed by setting environment variables before starting the
app (an environment variable is just a named value the operating system hands to a
program when it starts). If a dial is not set, we use a sensible default.

One of these dials is a safety catch. TaskBot is *deliberately* insecure - it is a
practice target - so it must never be reachable from another machine. This file
refuses to start the app if someone points it at a public network address.

Specification references: feature spec section 2.2, decision S-2, requirement FR-7.6.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """
    Raised when the settings are wrong in a way that makes it unsafe or impossible
    to start. We deliberately stop the whole app rather than carry on with a bad
    setting, because a half-configured security lab is worse than one that will not
    start at all.
    """


# The only network addresses we allow the app to listen on. Every one of these
# means "this computer only" - a different machine on the network cannot reach them.
# "127.0.0.1" and "::1" are the numeric names for "myself"; "localhost" is the
# friendly word for the same thing.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class Settings:
    """
    A single bundle holding every setting the app uses.

    "frozen" means once it is created nobody can quietly change a value later, so
    the settings you see at startup are the settings in force for the whole run.
    """

    # --- how we talk to the local AI model ---
    model: str
    ollama_url: str

    # --- where the web server listens ---
    host: str
    port: int

    # --- important folders ---
    data_dir: Path
    skills_dir: Path
    policy_dir: Path

    # --- behaviour dials ---
    history_turns: int
    unused_grant_window: int

    # --- specific files and folders worked out from data_dir, so the rest of the
    #     app never has to build these paths by hand and risk getting one wrong ---
    tasks_file: Path
    installed_file: Path
    findings_file: Path
    activity_file: Path
    markers_dir: Path
    collector_dir: Path


def _read_text(name: str, default: str) -> str:
    """
    Read one environment variable as text.

    In: the variable name, and the value to use if it is missing or blank.
    Out: the value to use.

    We treat a blank value the same as a missing one, because an empty setting is
    almost always a mistake rather than a deliberate choice.
    """
    value = os.environ.get(name, "").strip()
    return value if value else default


def _read_int(name: str, default: int) -> int:
    """
    Read one environment variable as a whole number.

    In: the variable name and a fallback number.
    Out: the number to use.

    If someone types something that is not a number, we stop with a clear message
    rather than silently falling back, because silently ignoring a setting someone
    deliberately typed is confusing.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number, but it was {raw!r}.") from exc


def load_settings() -> Settings:
    """
    Build the settings bundle by reading the environment.

    In: nothing (it reads the environment variables itself).
    Out: a finished Settings object.

    Raises ConfigError if anything is set to a value we cannot safely accept.
    """
    host = _read_text("TASKBOT_HOST", "127.0.0.1")

    # THE SAFETY CATCH. This app is intentionally vulnerable, so it must only ever
    # be reachable from the computer it is running on. "0.0.0.0" means "let anyone
    # on the network connect", which would expose a knowingly insecure app to other
    # machines. We refuse to start rather than allow that by accident.
    if host not in LOOPBACK_ADDRESSES:
        raise ConfigError(
            f"TASKBOT_HOST is set to {host!r}, but TaskBot is intentionally vulnerable "
            f"and may only listen on this machine. Allowed values: "
            f"{', '.join(sorted(LOOPBACK_ADDRESSES))}."
        )

    data_dir = Path(_read_text("TASKBOT_DATA_DIR", "./data")).resolve()
    skills_dir = Path(_read_text("TASKBOT_SKILLS_DIR", "./skills")).resolve()
    policy_dir = Path(_read_text("TASKBOT_POLICY_DIR", "./policy")).resolve()

    return Settings(
        model=_read_text("TASKBOT_MODEL", "llama3.1:8b"),
        ollama_url=_read_text("TASKBOT_OLLAMA_URL", "http://127.0.0.1:11434"),
        host=host,
        port=_read_int("TASKBOT_PORT", 8000),
        data_dir=data_dir,
        skills_dir=skills_dir,
        policy_dir=policy_dir,
        history_turns=_read_int("TASKBOT_HISTORY_TURNS", 10),
        unused_grant_window=_read_int("TASKBOT_UNUSED_GRANT_WINDOW", 5),
        # These are all worked out from data_dir so every part of the app agrees on
        # where things live.
        tasks_file=data_dir / "tasks.json",
        installed_file=data_dir / "installed.json",
        findings_file=data_dir / "findings.json",
        activity_file=data_dir / "activity.json",
        markers_dir=data_dir / "markers",
        collector_dir=data_dir / "collector",
    )


# The app loads its settings once and then everyone shares that same copy. We keep
# it in this variable. It starts empty and is filled in the first time it is asked
# for, so importing this file never does any work on its own.
_active_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Hand back the settings everyone in the app should use.

    In: nothing.
    Out: the shared Settings object, loading it the first time it is asked for.
    """
    global _active_settings
    if _active_settings is None:
        _active_settings = load_settings()
    return _active_settings


def set_settings(settings: Settings) -> None:
    """
    Replace the shared settings.

    In: a Settings object.
    Out: nothing.

    This exists so the automated tests can point the app at a scratch folder instead
    of the real data folder. Normal running never calls it.
    """
    global _active_settings
    _active_settings = settings


def reset_settings() -> None:
    """
    Forget the shared settings so the next request reloads them from the environment.

    In: nothing. Out: nothing. Used only by tests, to keep them independent.
    """
    global _active_settings
    _active_settings = None
