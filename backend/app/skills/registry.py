"""
Keeping track of every skill: finding them on disk, checking them, and remembering
which ones the user switched on.

This is the "shop floor" of the skill store. It knows what exists, what is valid,
and what is installed - but it never runs anything. Running a skill happens in one
place only, app/skills/host.py, which is what makes it possible to prove that a
skill can only start because the AI model asked for it.

A note on the shape of discover(): it takes a LIST of places to look, even though
today there is only one. Letting users upload their own skills was deliberately put
off, and when it comes back it becomes one more place in that list rather than a
rewrite of everything that calls this.

Specification references: feature spec sections 5.4 and 3.5; TDD sections 2.1 and
14 (Q-1); decision S-18; requirements FR-2.1, FR-2.2, FR-2.6.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from app.config import get_settings
from app.skills.digest import canonical_digest
from app.skills.manifest import (
    Manifest,
    Vocabulary,
    load_category_names,
    load_vocabulary,
    parse_manifest,
)
from app.storage import store

logger = logging.getLogger("taskbot.skills")


class SkillNotFound(Exception):
    """Someone asked about a skill that does not exist on disk."""


class SkillInvalid(Exception):
    """Someone tried to install a skill whose description failed its checks."""


class SkillSource(StrEnum):
    """
    Where a skill came from.

    Only one source exists today. It is written as a list of options because user
    uploads are expected to return later as a second source (TDD section 14, Q-1).
    """

    CATALOGUE = "catalogue"


@dataclass(frozen=True)
class SkillRecord:
    """
    Everything the app knows about one skill on disk.

    Note that invalid skills are kept, not discarded. The store shows them, greyed
    out, with the list of what is wrong - far more useful to a skill author than
    silently vanishing.
    """

    skill_id: str
    manifest: Manifest | None
    source: SkillSource
    root: Path
    valid: bool
    errors: list[str]
    installed: bool
    entry_file: Path | None
    entry_attr: str | None
    mtime_ns: int


class SkillRegistry:
    """
    The list of skills the app knows about.

    Built once at startup and refreshed whenever something installs or uninstalls.
    """

    def __init__(self) -> None:
        self._records: dict[str, SkillRecord] = {}
        self._vocabulary: Vocabulary | None = None
        self._categories: set[str] = set()

    # --- loading the policy files ---

    def _load_policy(self) -> tuple[Vocabulary, set[str]]:
        """
        Load the capability list and the category names.

        In: nothing. Out: the vocabulary and the set of known category names.

        These are cached after the first load because they never change while the
        app is running.
        """
        if self._vocabulary is None:
            settings = get_settings()
            self._vocabulary = load_vocabulary(
                settings.policy_dir / "capability_vocabulary.json"
            )
            # Only the category NAMES are needed here. Reading them via the
            # skills package keeps this side of the app from importing the findings
            # side, which is a deliberate boundary rule (TDD section 10).
            self._categories = load_category_names(
                settings.policy_dir / "capability_baselines.json"
            )
        return self._vocabulary, self._categories

    # --- finding skills ---

    def discover(self, roots: Sequence[tuple[SkillSource, Path]]) -> list[SkillRecord]:
        """
        Look in the given places for skills and read each one's description.

        In: a list of (where it came from, folder to look in) pairs.
        Out: every skill found, valid or not.

        If two skills claim the same identifier, the first one wins and the second
        is marked invalid. Two skills answering to the same name would make it
        genuinely ambiguous which one the AI model had asked for.
        """
        vocabulary, categories = self._load_policy()
        found: dict[str, SkillRecord] = {}
        installed_ids = set(store.load_installed().installed)

        for source, root in roots:
            root = Path(root)
            if not root.exists():
                continue

            # Sorted so the order is the same on every machine and every run.
            for folder in sorted(path for path in root.iterdir() if path.is_dir()):
                record = self._read_one_skill(
                    folder, source, vocabulary, categories, installed_ids, found
                )
                # If a valid skill already claimed this identifier, keep it. The
                # later copy has already been marked invalid above; storing it here
                # would replace the working skill with the rejected one, which is
                # the opposite of "first one wins".
                if record.skill_id in found and found[record.skill_id].valid:
                    logger.warning(
                        "Ignoring %s: the id %r is already used by %s.",
                        folder,
                        record.skill_id,
                        found[record.skill_id].root,
                    )
                    continue
                found[record.skill_id] = record

        self._records = found
        return list(found.values())

    def default_roots(self) -> list[tuple[SkillSource, Path]]:
        """
        Every place the app looks for skills.

        In: nothing. Out: the (where it came from, folder) pairs to search.

        There are two kinds of place:

          backend/skills/catalogue/    the shared, honest skills that belong to the
                                       platform itself.
          vulnerabilities/<name>/skill/  one folder per deliberate weakness, each
                                       completely separate from the others.

        Keeping each weakness in its own folder means one can be added, examined or
        removed without touching any other, and none of them can quietly rely on
        another's code. What they must NOT contain is any part of the shared platform
        - the watchers, the findings engine and the rest stay in one place, and a
        weakness plugs into them rather than carrying its own copy.

        User-supplied skills are deliberately still not included (TDD section 14, Q-1).
        """
        settings = get_settings()

        roots: list[tuple[SkillSource, Path]] = [
            (SkillSource.CATALOGUE, settings.skills_dir / "catalogue")
        ]

        # Each weakness folder contributes its own skill folder, if it has one. The
        # folders are sorted so the search order is identical on every machine.
        if settings.vulnerabilities_dir.exists():
            for folder in sorted(settings.vulnerabilities_dir.iterdir()):
                skill_folder = folder / "skill"
                if skill_folder.is_dir():
                    roots.append((SkillSource.CATALOGUE, skill_folder))

        return roots

    def discover_default(self) -> list[SkillRecord]:
        """
        Look everywhere skills live and read each one's description.

        In: nothing. Out: every skill found.
        """
        return self.discover(self.default_roots())

    def _read_one_skill(
        self,
        folder: Path,
        source: SkillSource,
        vocabulary: Vocabulary,
        categories: set[str],
        installed_ids: set[str],
        already_found: dict[str, SkillRecord],
    ) -> SkillRecord:
        """
        Read and check a single skill folder.

        In: the folder, where it came from, the policy data, which skills are
        switched on, and what has been found so far.
        Out: one SkillRecord, valid or invalid.
        """
        manifest_path = folder / "manifest.json"
        manifest, errors = parse_manifest(manifest_path, vocabulary, categories)

        # If the manifest could not be read we still record the skill, using the
        # folder name as a stand-in identifier so the store can list the problem.
        skill_id = manifest.id if manifest else folder.name

        entry_file: Path | None = None
        entry_attr: str | None = None
        mtime_ns = 0

        if manifest:
            filename, _, attribute = manifest.entrypoint.partition(":")
            entry_file = folder / filename
            entry_attr = attribute
            if entry_file.exists():
                # Remembered so a changed file can be noticed and reloaded during
                # development without restarting the app.
                mtime_ns = entry_file.stat().st_mtime_ns

        if skill_id in already_found:
            errors = list(errors) + [
                f"Another skill already uses the id {skill_id!r}; this copy is ignored."
            ]
            manifest = None

        valid = manifest is not None and not errors

        return SkillRecord(
            skill_id=skill_id,
            manifest=manifest,
            source=source,
            root=folder,
            valid=valid,
            errors=list(errors),
            installed=skill_id in installed_ids,
            entry_file=entry_file,
            entry_attr=entry_attr,
            mtime_ns=mtime_ns,
        )

    # --- looking things up ---

    def all(self) -> list[SkillRecord]:
        """
        Every skill found on disk, in a stable order.

        The "is it switched on?" flag is re-read from saved state rather than trusted
        from the snapshot taken at startup. Installing happens long after discovery,
        so a stale flag here would leave the store showing an Install button for a
        skill that is already installed.
        """
        return [self._refresh_installed_flag(self._records[key]) for key in sorted(self._records)]

    def get(self, skill_id: str) -> SkillRecord:
        """
        One skill by identifier.

        In: the identifier. Out: its record. Raises SkillNotFound if unknown.
        """
        if skill_id not in self._records:
            raise SkillNotFound(f"No skill with id {skill_id!r}.")
        return self._refresh_installed_flag(self._records[skill_id])

    def installed(self) -> list[SkillRecord]:
        """
        The skills that are switched on AND passed their checks.

        In: nothing. Out: the records.

        This is the ONLY list the AI model is ever shown (requirement FR-2.6). A
        broken or switched-off skill is invisible to it.
        """
        installed_ids = set(store.load_installed().installed)
        return [
            self._refresh_installed_flag(record)
            for record in self.all()
            if record.valid and record.skill_id in installed_ids
        ]

    def _refresh_installed_flag(self, record: SkillRecord) -> SkillRecord:
        """
        Return the record with its "installed" flag brought up to date.

        In: a record. Out: the same record, or a copy with the flag corrected.

        The records are built at startup, but installing happens later, so the flag
        is re-read from saved state rather than trusted from the snapshot.
        """
        from dataclasses import replace

        currently_installed = store.is_installed(record.skill_id)
        if record.installed == currently_installed:
            return record
        return replace(record, installed=currently_installed)

    # --- switching skills on and off ---

    def install(self, skill_id: str) -> SkillRecord:
        """
        Switch a skill on.

        In: the identifier. Out: the updated record.

        Raises SkillNotFound if it does not exist, or SkillInvalid if its
        description failed its checks - a skill that cannot be trusted to describe
        itself correctly should not be offered to the AI model at all.
        """
        record = self.get(skill_id)

        if not record.valid:
            raise SkillInvalid(
                f"Skill {skill_id!r} cannot be installed because its manifest has "
                f"problems: {'; '.join(record.errors)}"
            )

        # Verify the skill's content against the digest its manifest declares (REQ-02).
        # The manifest object is bound through its canonical JSON; the raw-byte resource
        # set is the entrypoint file. If the on-disk content has been altered since the
        # manifest was written, the hashes differ and installation is refused.
        if record.manifest is not None:
            resources = [record.entry_file] if record.entry_file else []
            computed = canonical_digest(record.manifest.model_dump(), resources)
            if computed != record.manifest.digest:
                raise SkillInvalid(
                    f"Skill {skill_id!r} cannot be installed because its content does "
                    f"not match the digest in its manifest: the manifest declares "
                    f"{record.manifest.digest} but the on-disk content hashes to "
                    f"{computed}. Its files may have been tampered with after it was "
                    f"vetted; re-verify before trusting it."
                )
            # Record the verified digest as the trusted baseline for run-time checks.
            store.set_installed_digest(skill_id, computed)

        store.set_installed(skill_id, True)
        return self._refresh_installed_flag(record)

    def uninstall(self, skill_id: str) -> SkillRecord:
        """
        Switch a skill off.

        In: the identifier. Out: the updated record. Doing it twice is harmless.
        """
        record = self.get(skill_id)
        store.set_installed(skill_id, False)
        store.remove_installed_digest(skill_id)
        return self._refresh_installed_flag(record)


# The app shares one registry. It is created the first time it is asked for, so
# simply importing this file does no work.
_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """The shared registry everyone in the app should use."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def reset_registry() -> None:
    """
    Throw away the shared registry so the next request builds a fresh one.

    Used by tests, and after settings change, so one test cannot inherit another
    test's view of what exists on disk.
    """
    global _registry
    _registry = None
