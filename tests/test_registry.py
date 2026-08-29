"""
Checks for the skill registry (app/skills/registry.py).

The registry knows what skills exist, which are valid, and which are switched on.
It never runs anything - that happens in one place only, which is what lets the app
prove a skill can only start because the AI model asked for it.

Covers: feature spec sections 5.4 and 3.5; TDD sections 2.1 and 14 (Q-1);
decision S-18; requirements FR-2.1, FR-2.2, FR-2.6.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from app import config
from app.skills import registry as registry_module
from app.skills.registry import SkillInvalid, SkillNotFound, SkillRegistry, SkillSource
from app.storage import store

from tests.test_manifest import GOOD_MANIFEST, write_skill


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Every test gets a registry that knows nothing yet."""
    registry_module.reset_registry()
    yield
    registry_module.reset_registry()


@pytest.fixture
def catalogue(tmp_path: Path) -> Path:
    """An empty skills folder for a test to fill however it likes."""
    folder = tmp_path / "catalogue"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def discover_from(catalogue: Path) -> SkillRegistry:
    """Build a registry that has looked in one folder."""
    registry = SkillRegistry()
    registry.discover([(SkillSource.CATALOGUE, catalogue)])
    return registry


# --- Finding skills --------------------------------------------------------------


def test_a_valid_skill_is_found(tmp_settings, catalogue):
    """The basic case: a well-formed skill folder is discovered and marked valid."""
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)

    registry = discover_from(catalogue)
    records = registry.all()

    assert len(records) == 1
    assert records[0].skill_id == "example_skill"
    assert records[0].valid is True
    assert records[0].errors == []


def test_an_invalid_skill_is_kept_and_explained(tmp_settings, catalogue):
    """
    Broken skills are NOT hidden. The store shows them with the list of problems,
    which is far more useful to an author than silently vanishing.
    """
    write_skill(catalogue / "broken_skill", {**GOOD_MANIFEST, "category": "nonsense"})

    registry = discover_from(catalogue)
    records = registry.all()

    assert len(records) == 1
    assert records[0].valid is False
    assert records[0].errors


def test_an_empty_folder_finds_nothing(tmp_settings, catalogue):
    """No skills is a normal state, not an error - it is how a fresh lab starts."""
    assert discover_from(catalogue).all() == []


def test_a_missing_folder_is_not_an_error(tmp_settings, tmp_path):
    """Pointing at a folder that does not exist yet simply finds nothing."""
    registry = SkillRegistry()
    registry.discover([(SkillSource.CATALOGUE, tmp_path / "not-created")])
    assert registry.all() == []


def test_two_skills_claiming_the_same_name_the_first_one_wins(tmp_settings, catalogue):
    """
    Two skills answering to one name would make it genuinely ambiguous which one the
    AI model had asked for, so the second copy is refused.
    """
    write_skill(catalogue / "a_copy", GOOD_MANIFEST)
    write_skill(catalogue / "b_copy", GOOD_MANIFEST)

    registry = discover_from(catalogue)
    records = registry.all()

    assert len(records) == 1
    assert records[0].valid is True


def test_discovery_takes_a_list_of_places_to_look(tmp_settings, tmp_path):
    """
    DECISION S-18 - the shape that leaves room for user uploads to return later.

    discover() accepts several places, even though the app passes only one today.
    Adding a second source later becomes one more entry in that list rather than a
    rewrite of everything that calls it.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_skill(first / "example_skill", GOOD_MANIFEST)
    write_skill(second / "other_skill", {**GOOD_MANIFEST, "id": "other_skill"})

    registry = SkillRegistry()
    registry.discover(
        [(SkillSource.CATALOGUE, first), (SkillSource.CATALOGUE, second)]
    )

    assert {record.skill_id for record in registry.all()} == {
        "example_skill",
        "other_skill",
    }


def test_only_the_catalogue_source_exists_today(tmp_settings):
    """
    User uploads were deliberately deferred (TDD section 14, Q-1), so there is
    exactly one source for now.
    """
    assert [source.value for source in SkillSource] == ["catalogue"]


# --- Looking skills up -----------------------------------------------------------


def test_asking_for_an_unknown_skill_is_a_clear_error(tmp_settings, catalogue):
    """Unknown means unknown - a clear failure, not a silent empty answer."""
    registry = discover_from(catalogue)

    with pytest.raises(SkillNotFound):
        registry.get("no_such_skill")


def test_skills_are_listed_in_a_stable_order(tmp_settings, catalogue):
    """
    The same order on every machine and every run, so the store does not shuffle
    itself between page loads.
    """
    for name in ["zebra_skill", "alpha_skill", "middle_skill"]:
        write_skill(catalogue / name, {**GOOD_MANIFEST, "id": name})

    registry = discover_from(catalogue)
    ids = [record.skill_id for record in registry.all()]

    assert ids == sorted(ids)


# --- Switching skills on and off -------------------------------------------------


def test_installing_and_uninstalling(tmp_settings, catalogue):
    """Installing is remembered, and uninstalling undoes it."""
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    registry = discover_from(catalogue)

    assert registry.get("example_skill").installed is False

    registry.install("example_skill")
    assert registry.get("example_skill").installed is True
    assert store.load_installed().installed == ["example_skill"]

    registry.uninstall("example_skill")
    assert registry.get("example_skill").installed is False


def test_installing_twice_is_harmless(tmp_settings, catalogue):
    """Doing the same thing twice changes nothing (the operation is idempotent)."""
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    registry = discover_from(catalogue)

    registry.install("example_skill")
    registry.install("example_skill")

    assert store.load_installed().installed == ["example_skill"]


def test_uninstalling_something_never_installed_is_harmless(tmp_settings, catalogue):
    """No error, no change - the end state is what was asked for either way."""
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    registry = discover_from(catalogue)

    registry.uninstall("example_skill")

    assert store.load_installed().installed == []


def test_a_broken_skill_cannot_be_installed(tmp_settings, catalogue):
    """
    A skill that cannot describe itself correctly must not be offered to the AI
    model. The refusal names the problems so it can be fixed.
    """
    write_skill(catalogue / "broken_skill", {**GOOD_MANIFEST, "category": "nonsense"})
    registry = discover_from(catalogue)

    with pytest.raises(SkillInvalid):
        registry.install("broken_skill")

    assert store.load_installed().installed == []


def test_installing_an_unknown_skill_is_a_clear_error(tmp_settings, catalogue):
    registry = discover_from(catalogue)

    with pytest.raises(SkillNotFound):
        registry.install("no_such_skill")


# --- Content-digest verification at install (AST02 T-05) ---------------------------


def test_install_fails_when_manifest_digest_mismatch(tmp_settings, catalogue):
    """
    REQ-02: a skill whose on-disk content no longer matches the digest its manifest
    declares cannot be installed. This is how a tampered skill is refused at install.
    """
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    # Tamper with the code AFTER the manifest's digest was computed over it.
    (catalogue / "example_skill" / "skill.py").write_text(
        "def run(ctx, params):\n    return 'tampered'\n", encoding="utf-8"
    )
    registry = discover_from(catalogue)

    with pytest.raises(SkillInvalid) as exc_info:
        registry.install("example_skill")

    assert "digest" in str(exc_info.value)
    assert store.load_installed().installed == []


def test_install_records_verified_digest(tmp_settings, catalogue):
    """
    REQ-02: a successfully installed skill has its verified content digest recorded as
    the trusted baseline, for later run-time comparison (AST02 T-06).
    """
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    registry = discover_from(catalogue)
    declared = registry.get("example_skill").manifest.digest

    registry.install("example_skill")

    assert store.load_installed_digests()["example_skill"] == declared
    assert store.get_installed_digest("example_skill") == declared


def test_uninstalling_drops_the_recorded_digest(tmp_settings, catalogue):
    """Uninstalling a skill forgets its verified digest, so a re-install re-verifies."""
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    registry = discover_from(catalogue)
    registry.install("example_skill")
    assert "example_skill" in store.load_installed_digests()

    registry.uninstall("example_skill")

    assert "example_skill" not in store.load_installed_digests()


# --- The skill allowlist (AST02 T-07, REQ-06) --------------------------------------


def _managed_registry(tmp_settings, tmp_path, skill_id: str, manifest: dict) -> SkillRegistry:
    """
    Point the app at a scratch skills channel holding one skill, with the REAL policy
    folder (so the real allowlist applies), and return a registry that has looked
    there. The skill is therefore "in the managed channel" the allowlist gates.
    """
    channel = tmp_path / "skills" / "catalogue"
    write_skill(channel / skill_id, manifest)

    scratch = dataclasses.replace(
        tmp_settings,
        skills_dir=tmp_path / "skills",
        vulnerabilities_dir=tmp_path / "no-vulns",
    )
    config.set_settings(scratch)
    registry_module.reset_registry()

    registry = SkillRegistry()
    registry.discover_default()
    return registry


def test_skill_absent_from_allowlist_is_invalid(tmp_settings, tmp_path):
    """
    REQ-06: a skill discovered from the app's own skill channel whose id is not on
    the allowlist is invalid, so it can never be installed or shown to the model -
    even though it is a perfectly well-formed skill on disk.
    """
    registry = _managed_registry(
        tmp_settings, tmp_path, "rogue_skill", {**GOOD_MANIFEST, "id": "rogue_skill"}
    )

    record = registry.get("rogue_skill")

    assert record.valid is False
    assert any("allowed skills list" in error for error in record.errors)
    assert "rogue_skill" not in [item.skill_id for item in registry.installed()]


def test_skill_in_allowlist_requires_valid_digest(tmp_settings, tmp_path):
    """
    REQ-06 + REQ-02: being on the allowlist is necessary but not sufficient - the
    skill must still carry a valid content digest. An allowlisted skill with a broken
    digest is still invalid.
    """
    registry = _managed_registry(
        tmp_settings,
        tmp_path,
        "task_summary",
        {**GOOD_MANIFEST, "id": "task_summary", "digest": "not-a-digest"},
    )

    record = registry.get("task_summary")

    assert record.valid is False
    assert any("digest" in error for error in record.errors)


# --- What the AI model is allowed to see -----------------------------------------


def test_the_model_only_ever_sees_installed_valid_skills(tmp_settings, catalogue):
    """
    REQUIREMENT FR-2.6.

    The installed list is the ONLY list the AI model is shown. A skill that is
    switched off, or broken, is completely invisible to it - which is what makes
    "with nothing installed, nothing can run" true.
    """
    write_skill(catalogue / "good_skill", {**GOOD_MANIFEST, "id": "good_skill"})
    write_skill(
        catalogue / "broken_skill",
        {**GOOD_MANIFEST, "id": "broken_skill", "category": "nonsense"},
    )
    write_skill(catalogue / "off_skill", {**GOOD_MANIFEST, "id": "off_skill"})

    registry = discover_from(catalogue)
    registry.install("good_skill")
    # broken_skill cannot be installed at all; off_skill is simply left switched off.

    visible = [record.skill_id for record in registry.installed()]
    assert visible == ["good_skill"]


def test_nothing_is_visible_on_a_fresh_lab(tmp_settings, catalogue):
    """
    A brand new lab shows the AI model nothing, so no skill can run (TDD section 14,
    Q-6; requirement FR-1.4).
    """
    write_skill(catalogue / "example_skill", GOOD_MANIFEST)
    registry = discover_from(catalogue)

    assert registry.installed() == []


# --- The real skills folder ------------------------------------------------------


def test_the_real_catalogue_contains_only_valid_skills(tmp_settings):
    """
    Whatever is actually shipped in this repository must pass its own checks. A
    broken skill in the real catalogue would be a defect in the product.
    """
    registry = SkillRegistry()
    records = registry.discover_default()

    for record in records:
        assert record.valid, f"{record.skill_id} is invalid: {record.errors}"
