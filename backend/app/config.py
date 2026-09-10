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


# The only network addresses we allow the app to listen on by default. Every one
# of these means "this computer only" - a different machine on the network cannot
# reach them. "127.0.0.1" and "::1" are the numeric names for "myself"; "localhost"
# is the friendly word for the same thing.
#
# On Render (or other platforms) the app must bind to "0.0.0.0" so the platform's
# reverse proxy can reach it. Setting TASKBOT_ALLOW_PUBLIC_BIND=true enables this.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})
PUBLIC_BIND_ADDRESS = "0.0.0.0"


# Where each part of the project lives, worked out from this file's own location.
#
# The repository is split into three top-level areas:
#
#   backend/         the Python, plus the policy files and the shared control skill
#   frontend/        the web pages and their styling, served BY the backend
#   vulnerabilities/ one isolated folder per deliberate weakness
#
# Working these out from this file rather than from wherever the app happens to be
# started means the app finds its own files regardless of the current directory.
# Every one can still be overridden by an environment variable.
_REPO_ROOT = Path(__file__).resolve().parents[2]

BACKEND_DEFAULTS = {
    # Runtime state stays at the top level: it is the lab's memory, not source code,
    # and every instruction for resetting the lab says "delete the data folder".
    "data": _REPO_ROOT / "data",
    "skills": _REPO_ROOT / "backend" / "skills",
    "policy": _REPO_ROOT / "backend" / "policy",
    "vulnerabilities": _REPO_ROOT / "vulnerabilities",
    "frontend": _REPO_ROOT / "frontend",
}


@dataclass(frozen=True)
class Settings:
    """
    A single bundle holding every setting the app uses.

    "frozen" means once it is created nobody can quietly change a value later, so
    the settings you see at startup are the settings in force for the whole run.
    """

    # --- how we talk to the AI model ---
    model: str
    groq_api_key: str
    groq_base_url: str

    # --- where the web server listens ---
    host: str
    port: int

    # --- important folders ---
    data_dir: Path
    skills_dir: Path
    policy_dir: Path
    vulnerabilities_dir: Path

    # --- the web pages and their styling ---
    #
    # The pages a person looks at live in their own top-level folder, separate from
    # the Python. The backend still serves them - they are not a separate program -
    # so the app needs to know where they are.
    templates_dir: Path
    static_dir: Path

    # --- self-referencing URL (for skills calling back to this app) ---
    self_url: str

    # --- external collector URL (for real data exfiltration demo on Render) ---
    # When set, skills send stolen data to this URL instead of the local mock collector.
    # Locally this is empty (data stays on your PC). On Render, set it to a public
    # endpoint (ngrok, webhook.site, etc.) so data actually reaches your machine.
    collector_url: str

    # --- behaviour dials ---
    history_turns: int
    unused_grant_window: int
    # How much of a network reply to keep, as readable text, on the record of the
    # request. This is evidence for a person, not the thing the checks compare - see
    # NetBroker._request in app/skills/context.py.
    response_excerpt_bytes: int

    # --- specific files and folders worked out from data_dir, so the rest of the
    #     app never has to build these paths by hand and risk getting one wrong ---
    tasks_file: Path
    installed_file: Path
    findings_file: Path
    activity_file: Path
    markers_dir: Path
    collector_dir: Path
    dashboard_file: Path
    hub_dir: Path
    registry_dir: Path


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
    allow_public = _read_text("TASKBOT_ALLOW_PUBLIC_BIND", "").lower() in ("true", "1", "yes")

    # THE SAFETY CATCH. This app is intentionally vulnerable, so it must only ever
    # be reachable from the computer it is running on. "0.0.0.0" means "let anyone
    # on the network connect", which would expose a knowingly insecure app to other
    # machines. We refuse to start rather than allow that by accident.
    #
    # On Render (and similar platforms) the app MUST bind to 0.0.0.0 so the
    # platform's reverse proxy can route traffic to it. Setting
    # TASKBOT_ALLOW_PUBLIC_BIND=true explicitly opts into this, acknowledging
    # the safety trade-off for deployment purposes.
    if host not in LOOPBACK_ADDRESSES:
        if not allow_public or host != PUBLIC_BIND_ADDRESS:
            raise ConfigError(
                f"TASKBOT_HOST is set to {host!r}, but TaskBot is intentionally vulnerable "
                f"and may only listen on this machine. Allowed values: "
                f"{', '.join(sorted(LOOPBACK_ADDRESSES))}. "
                f"To bind to 0.0.0.0 for platform deployment, set "
                f"TASKBOT_ALLOW_PUBLIC_BIND=true."
            )

    # The self-referencing URL is how skills call back to this app's mock services.
    # Locally it is always http://127.0.0.1:<port>. On Render (or similar) it can
    # be overridden via TASKBOT_SELF_URL so skills reach the deployed service.
    port = _read_int("TASKBOT_PORT", 8000)
    self_url = _read_text("TASKBOT_SELF_URL", "")
    if not self_url:
        self_url = f"http://127.0.0.1:{port}"

    # External collector URL for real data exfiltration demo. When set, skills
    # send stolen data to this URL instead of the local mock collector.
    collector_url = _read_text("TASKBOT_COLLECTOR_URL", "")

    data_dir = Path(_read_text("TASKBOT_DATA_DIR", str(BACKEND_DEFAULTS["data"]))).resolve()
    skills_dir = Path(_read_text("TASKBOT_SKILLS_DIR", str(BACKEND_DEFAULTS["skills"]))).resolve()
    policy_dir = Path(_read_text("TASKBOT_POLICY_DIR", str(BACKEND_DEFAULTS["policy"]))).resolve()
    vulnerabilities_dir = Path(
        _read_text("TASKBOT_VULNERABILITIES_DIR", str(BACKEND_DEFAULTS["vulnerabilities"]))
    ).resolve()
    frontend_dir = Path(
        _read_text("TASKBOT_FRONTEND_DIR", str(BACKEND_DEFAULTS["frontend"]))
    ).resolve()

    return Settings(
        model=_read_text("TASKBOT_MODEL", "openai/gpt-oss-120b"),
        groq_api_key=_read_text("GROQ_API_KEY", ""),
        groq_base_url=_read_text("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        host=host,
        port=port,
        self_url=self_url,
        collector_url=collector_url,
        data_dir=data_dir,
        skills_dir=skills_dir,
        policy_dir=policy_dir,
        vulnerabilities_dir=vulnerabilities_dir,
        templates_dir=frontend_dir / "templates",
        static_dir=frontend_dir / "static",
        history_turns=_read_int("TASKBOT_HISTORY_TURNS", 10),
        unused_grant_window=_read_int("TASKBOT_UNUSED_GRANT_WINDOW", 5),
        response_excerpt_bytes=_read_int("TASKBOT_RESPONSE_EXCERPT_BYTES", 4096),
        # These are all worked out from data_dir so every part of the app agrees on
        # where things live.
        tasks_file=data_dir / "tasks.json",
        installed_file=data_dir / "installed.json",
        findings_file=data_dir / "findings.json",
        activity_file=data_dir / "activity.json",
        markers_dir=data_dir / "markers",
        collector_dir=data_dir / "collector",
        # The team dashboard's own store: the honest standup lines a skill posts, kept
        # completely separate from the collector's stolen-data inbox above.
        dashboard_file=data_dir / "dashboard.json",
        # The mock team hub's document store. A skill can FETCH from here, which no
        # other mock allows - the collector and the dashboard only ever receive. Kept
        # in the data folder so it is editable by hand and obvious where it lives.
        hub_dir=data_dir / "hub",
        # The mock component registry's store: the published components a skill can be
        # built on. Like the hub, a skill FETCHES from here. Kept in the data folder so
        # a reviewer can swap one build for another by copying a file, which is exactly
        # how the supply-chain weakness is turned on and off.
        registry_dir=data_dir / "registry",
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
