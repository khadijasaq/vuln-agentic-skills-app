"""
The dormant half of this weakness, and the honest record of a gap in the platform.

Focus Picker holds two abilities it never uses: changing your tasks, and contacting the
network. Power held and never exercised has its own name in this app's catalogue -
"unused grant" - and its own, lower severity, because nothing has happened yet. It is
still worth reporting: the pair it holds (read your tasks, send things out) is exactly
what the thieving skill combines. Focus Picker holds the whole recipe and never cooks it.

THE GAP, STATED PLAINLY. The app can work this out - the check is written, and the first
test below proves it gives the right answer for the shipped skill. But nothing in the
running application ever calls that check, so an "unused grant" finding cannot currently
appear in the findings list for any skill at all. This is a defect in the platform, not
in this weakness, and it was left in place deliberately rather than fixed here: making an
over-powered skill demonstrable by editing the platform would be exactly the kind of
"help" that turns a real vulnerability into a staged one.

It is written down in docs/KNOWN-ISSUES.md as KI-1, and pinned by the second test below
so it cannot quietly change in either direction.

WHEN THE WIRING IS ADDED LATER: update the second test, do not delete it, and expect the
counts in test_focus_picker_api.py to rise by two - Focus Picker's two dormant abilities
will start being reported as well.

Covers: feature spec section 5.2 and open question 1; docs/KNOWN-ISSUES.md KI-1; TDD
section 4.5 and decision D-10; acceptance test A-7.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.skills.manifest import load_vocabulary
from app.skills import host as host_module
from app.skills import registry as registry_module

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"

# The two abilities Focus Picker holds and never uses.
DORMANT = {"task.write", "net.outbound"}

# The two it does use on every run.
EXERCISED = {"task.read", "fs.read"}

# How many runs must pass before an unused ability is held against a skill. A brand new
# skill should not be accused of not yet needing something (design decision D-10).
WINDOW = 5


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    """An engine loaded with the app's real capability list and yardstick policy."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


@pytest.fixture
def shipped_manifest(tmp_settings):
    """The REAL Focus Picker description, read from disk as the app would load it."""
    registry_module.reset_registry()
    host_module.clear_module_cache()
    registry = registry_module.get_registry()
    registry.discover_default()
    return registry.get("focus_picker").manifest


def test_a7_the_dormant_abilities_would_be_reported_as_unused(engine, shipped_manifest):
    """
    ACCEPTANCE TEST A-7, first half.

    Given what Focus Picker actually uses, the check names exactly the two abilities it
    holds and never touches - and waits for several runs first, so a skill that simply
    has not needed something yet is not accused of hoarding it.
    """
    too_early = engine.check_unused_grants(
        shipped_manifest, EXERCISED, invocation_count=2, window=WINDOW
    )
    assert too_early == [], "a skill that has barely run must not be accused yet"

    later = engine.check_unused_grants(
        shipped_manifest, EXERCISED, invocation_count=WINDOW, window=WINDOW
    )

    assert len(later) == 2
    assert {finding.granted["capability"] for finding in later} == DORMANT
    assert all(finding.type == "UNUSED_GRANT" for finding in later)
    assert all(finding.ast_id == "AST03" for finding in later)
    assert all(finding.axis == "proportionality" for finding in later)
    # Lower than "too much power", because nothing has happened yet - it is a risk being
    # carried, not an act (severities are fixed by the design, TDD Q-2).
    assert all(finding.severity == "low" for finding in later)


def test_a7_the_platform_never_asks_this_question_yet():
    """
    ACCEPTANCE TEST A-7, second half - the pin on KNOWN ISSUE KI-1.

    The check above works. Nothing in the running app calls it. This test reads the
    application's own source to confirm that, so the gap is a recorded, deliberate fact
    rather than something nobody noticed.

    Two ways this could change, and what to do about each:

      - somebody wires it up (the intended fix, after all three weaknesses are done):
        UPDATE this test to assert the call site exists, and expect two more findings in
        test_focus_picker_api.py;
      - somebody deletes the check: that would be a real regression, and the first test
        in this file would fail loudly.

    Either way the change is visible. That is the whole purpose of pinning it.
    """
    callers = sorted(
        path.relative_to(BACKEND_DIR).as_posix()
        for path in BACKEND_DIR.rglob("*.py")
        if "check_unused_grants" in path.read_text(encoding="utf-8")
    )

    # The only mention anywhere in the application is the definition itself.
    assert callers == ["app/findings/engine.py"], (
        "check_unused_grants now appears somewhere new. If it has been wired up, that is "
        "KNOWN ISSUE KI-1 being fixed: update this test and the expected finding counts "
        "in test_focus_picker_api.py."
    )

    engine_source = (BACKEND_DIR / "app" / "findings" / "engine.py").read_text(
        encoding="utf-8"
    )
    # Even inside that one file it is only defined, never called - the two passes the app
    # actually runs (one at install, one after each run) do not include it.
    assert engine_source.count("check_unused_grants") == 1
