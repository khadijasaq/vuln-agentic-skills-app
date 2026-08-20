"""
Where the app is put together and started.

This file is the front door. It runs the startup steps in a very specific order,
then hands control to the web server.

THE ORDER MATTERS, and one step in particular is critical: the watcher that records
what skills do (the "audit hook") must be switched on BEFORE any skill can possibly
be loaded. Python does not allow that watcher to be removed once installed, which is
exactly what we want - a skill must not be able to switch off the thing recording
it. But it only protects what happens after it is switched on, so it goes early.

Think of it like turning on the security cameras before unlocking the building,
rather than after.

Specification references: feature spec section 5.1, decision S-15, build plan
steps 0.4 and 1.9.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import routes as api_routes
from app.mock import collector as collector_routes
from app.web import routes as web_routes
from app.config import Settings, get_settings

logger = logging.getLogger("taskbot")


# --- The individual startup steps ------------------------------------------------
#
# Each one is a small function taking the settings and doing a single job. They are
# listed in STARTUP_STEPS further down, in the order they must run.


def step_install_audit_hook(settings: Settings) -> None:
    """
    Switch on the watcher that records file and network activity from skills.

    In: the settings. Out: nothing.

    This runs second, immediately after settings load and before anything else,
    because it can only see activity that happens after it is installed. The real
    watcher is built in Stage 4 of the build plan; until then this is deliberately
    an empty placeholder holding the correct position in the running order.
    """
    from app.monitor import audit_hook

    audit_hook.install_audit_hook()


def step_prepare_data_folder(settings: Settings) -> None:
    """
    Make sure the folders where we save information exist.

    In: the settings. Out: nothing.

    Creating them up front means every later step can simply write files without
    each one having to check first.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.markers_dir.mkdir(parents=True, exist_ok=True)
    (settings.collector_dir / "inbox").mkdir(parents=True, exist_ok=True)


def step_seed_tasks(settings: Settings) -> None:
    """
    Put a starter set of believable to-do items in place on a brand new lab.

    In: the settings. Out: nothing.

    Only happens when there is no task file at all, so restarting the app never
    overwrites work. Built at build-plan step 1.8.
    """
    from app.storage import seed

    seed.seed_tasks_if_absent()


def step_load_policy(settings: Settings) -> None:
    """
    Load the two policy files: the list of capabilities and the category baselines.

    In: the settings. Out: nothing.

    If either file is broken we stop the whole app. The findings engine compares
    what skills do against these files, so a damaged policy file would mean silently
    reporting nothing - much worse than refusing to start.
    """
    from app.findings import baselines
    from app.skills import manifest

    manifest.load_vocabulary(settings.policy_dir / "capability_vocabulary.json")
    baselines.load_baselines(settings.policy_dir / "capability_baselines.json")


def step_discover_skills(settings: Settings) -> None:
    """
    Look on disk for skills and read their descriptions.

    In: the settings. Out: nothing.

    Skills that fail their checks are kept and marked invalid rather than thrown
    away, so the store can explain to a person exactly what is wrong with them.
    """
    from app.skills import registry

    found = registry.get_registry().discover_default()
    valid = [record for record in found if record.valid]
    logger.info("Discovered %d skill(s), %d valid.", len(found), len(valid))


# The startup running order. The names are used by an automated test that checks
# nobody has quietly reordered these steps - especially the audit hook, which must
# stay in position 1 (counting from 0).
STARTUP_STEPS: list[tuple[str, Callable[[Settings], None]]] = [
    ("install_audit_hook", step_install_audit_hook),
    ("prepare_data_folder", step_prepare_data_folder),
    ("seed_tasks", step_seed_tasks),
    ("load_policy", step_load_policy),
    ("discover_skills", step_discover_skills),
]


def run_startup(settings: Settings) -> None:
    """
    Run every startup step, in order.

    In: the settings. Out: nothing.

    If any step raises an error we let it travel upwards and stop the app, because
    every one of these steps is a precondition for running safely.
    """
    for name, step in STARTUP_STEPS:
        logger.debug("Startup step: %s", name)
        step(settings)


def create_app() -> FastAPI:
    """
    Build the web application object.

    In: nothing (settings are read from the environment).
    Out: a ready-to-serve FastAPI application.
    """
    settings = get_settings()

    app = FastAPI(
        title="TaskBot",
        description=(
            "A deliberately vulnerable to-do assistant used to test agentic-AI "
            "security tooling. Local lab use only."
        ),
        version="0.1.0",
    )

    run_startup(settings)

    # Attach the JSON API (for programs), the pretend outside world (for simulated
    # data theft), and the web pages (for people).
    app.include_router(api_routes.router, prefix="/api", tags=["api"])
    app.include_router(collector_routes.router, prefix="/mock", tags=["mock"])
    app.include_router(web_routes.router, tags=["web"])

    # The stylesheet, font and small script the web pages use. Everything is served
    # from this machine - the pages work with no internet connection at all.
    static_dir = Path(__file__).resolve().parents[1] / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


# The application object the web server looks for when you run:
#   uvicorn app.main:app
app = create_app()


def main() -> None:
    """
    Start the web server from the command line.

    In: nothing. Out: nothing (runs until stopped).

    The address comes from the settings, which refuse anything except this machine
    - see app/config.py for why that safety catch exists.
    """
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
