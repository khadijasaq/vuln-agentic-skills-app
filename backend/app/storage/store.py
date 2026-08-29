"""
The app's memory: everything it can save and load.

Every other part of TaskBot goes through this file to read or change saved
information. Nothing else opens the data files directly. That keeps the rules in
one place - for example, "a finding seen twice becomes one finding with a count of
two" is written here once, rather than repeated everywhere.

Specification references: feature spec sections 4.2 and 4.3, TDD section 6.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.storage import atomic
from app.storage.models import (
    ActivityEntry,
    Finding,
    InstalledState,
    Standup,
    Task,
)


# --- Errors ----------------------------------------------------------------------


class StorageError(Exception):
    """Something went wrong saving or loading. Turned into a clear API message."""


class TaskNotFound(StorageError):
    """Someone asked for a to-do item that does not exist."""


# --- Time and identifiers --------------------------------------------------------


def now_iso() -> str:
    """
    The current time, written the one way the whole app agrees on.

    In: nothing. Out: text like "2026-08-21T14:03:11.482Z".

    Everything is recorded in UTC (world standard time) rather than local time, so
    timestamps from different machines can be compared directly. The "Z" on the end
    is the standard way of saying "this is UTC".
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id(prefix: str) -> str:
    """
    Make a fresh, unique identifier.

    In: a short prefix saying what kind of thing it is ("tsk", "act", "inv", "fnd").
    Out: text like "tsk_1755702191482a1b2c3".

    The middle is the current time in milliseconds, which makes the identifiers sort
    into the order they were created - handy when reading raw files. The random
    ending makes collisions effectively impossible even if many are created in the
    same millisecond.

    On the length of the random ending: it is six bytes, not three. Three bytes is
    only about 17 million possibilities, which sounds like plenty but is not - when
    thousands of identifiers are created inside the same millisecond, two of them
    picking the same number stops being unlikely (the same reason two people in a
    room of thirty often share a birthday). Six bytes removes the problem entirely
    at no real cost.
    """
    milliseconds = int(time.time() * 1000)
    return f"{prefix}_{milliseconds:013d}{secrets.token_hex(6)}"


# --- Tasks -----------------------------------------------------------------------


def _tasks_path() -> Path:
    return get_settings().tasks_file


def load_tasks() -> list[Task]:
    """
    Read every to-do item.

    In: nothing. Out: a list of Task records, oldest first.
    """
    raw = atomic.read_json(_tasks_path(), default=[])
    tasks: list[Task] = []
    for item in raw:
        try:
            tasks.append(Task(**item))
        except Exception:
            # One malformed entry should not hide all the healthy ones, so we skip
            # it rather than failing the whole read.
            continue
    return tasks


def save_tasks(tasks: list[Task]) -> None:
    """
    Replace the whole to-do list.

    In: the complete list of tasks. Out: nothing.
    """
    atomic.write_json_atomic(_tasks_path(), [task.model_dump() for task in tasks])


def add_task(title: str, notes: str = "") -> Task:
    """
    Add a new to-do item.

    In: the title, and optional extra notes. Out: the task that was created.
    """
    task = Task(
        id=new_id("tsk"),
        title=title.strip(),
        notes=notes,
        done=False,
        created_at=now_iso(),
        completed_at=None,
    )
    with atomic.mutate_json(_tasks_path(), default=[]) as items:
        items.append(task.model_dump())
    return task


def update_task(
    task_id: str,
    *,
    title: str | None = None,
    notes: str | None = None,
    done: bool | None = None,
) -> Task:
    """
    Change an existing to-do item.

    In: which task, plus whichever fields should change (leave the rest alone).
    Out: the updated task.

    Raises TaskNotFound if there is no task with that identifier.

    Marking a task as done also stamps the time it was completed; un-marking it
    clears that stamp, so the record never claims a completion that was undone.
    """
    with atomic.mutate_json(_tasks_path(), default=[]) as items:
        for item in items:
            if item.get("id") != task_id:
                continue

            if title is not None:
                item["title"] = title.strip()
            if notes is not None:
                item["notes"] = notes
            if done is not None:
                item["done"] = done
                item["completed_at"] = now_iso() if done else None

            return Task(**item)

    raise TaskNotFound(f"No task with id {task_id!r}.")


def delete_task(task_id: str) -> None:
    """
    Remove a to-do item.

    In: which task. Out: nothing. Raises TaskNotFound if it was not there.
    """
    with atomic.mutate_json(_tasks_path(), default=[]) as items:
        remaining = [item for item in items if item.get("id") != task_id]
        if len(remaining) == len(items):
            raise TaskNotFound(f"No task with id {task_id!r}.")
        # Replace the contents in place: the "with" block saves whatever this list
        # holds when it finishes, so we must edit this same list object.
        items[:] = remaining


def filter_tasks(tasks: list[Task], scope: str = "all") -> list[Task]:
    """
    Narrow a list of tasks to the ones asked for.

    In: the tasks, and one of "all", "open" or "done".
    Out: the matching tasks. An unrecognised scope is treated as "all".
    """
    if scope == "open":
        return [task for task in tasks if not task.done]
    if scope == "done":
        return [task for task in tasks if task.done]
    return list(tasks)


# --- Installed skills ------------------------------------------------------------


def load_installed() -> InstalledState:
    """
    Read which skills are switched on.

    In: nothing. Out: the installed-state record.
    """
    raw = atomic.read_json(
        get_settings().installed_file,
        default={"schema_version": 1, "installed": [], "updated_at": now_iso()},
    )
    try:
        return InstalledState(**raw)
    except Exception:
        # A damaged file means we cannot tell what was installed. Starting from
        # "nothing installed" is the safe choice: it can only ever make the app less
        # capable, never more.
        return InstalledState(installed=[], updated_at=now_iso())


def set_installed(skill_id: str, installed: bool) -> InstalledState:
    """
    Switch one skill on or off.

    In: the skill identifier, and True to install or False to remove.
    Out: the updated installed-state record.

    Doing the same thing twice is harmless - installing an already-installed skill
    changes nothing.
    """
    with atomic.mutate_json(
        get_settings().installed_file,
        default={"schema_version": 1, "installed": [], "updated_at": now_iso()},
    ) as state:
        current = list(state.get("installed", []))

        if installed and skill_id not in current:
            current.append(skill_id)
        elif not installed and skill_id in current:
            current = [existing for existing in current if existing != skill_id]

        state["schema_version"] = 1
        state["installed"] = current
        state["updated_at"] = now_iso()
        result = InstalledState(**state)

    return result


def is_installed(skill_id: str) -> bool:
    """True if that skill is currently switched on."""
    return skill_id in load_installed().installed


# --- Installed content digests ---------------------------------------------------


def _installed_digests_path() -> Path:
    """Where the verified per-skill content digests are kept."""
    return get_settings().data_dir / "installed_digests.json"


def load_installed_digests() -> dict[str, str]:
    """
    Read the verified content digest recorded for each installed skill.

    In: nothing. Out: a dict of skill id -> canonical digest.

    This is the trusted baseline an installed skill was verified against at install
    time. The manifest's own 'digest' field is what a skill *claims*; this store is
    what the app *recorded after checking*. Run-time verification (AST02 T-06)
    compares the on-disk content against THIS, so a tampered skill can be detected
    even if its manifest was edited to claim a matching digest.
    """
    raw = atomic.read_json(_installed_digests_path(), default={})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if isinstance(value, str) and value}


def get_installed_digest(skill_id: str) -> str | None:
    """The verified digest recorded for one skill, or None if not installed."""
    return load_installed_digests().get(skill_id)


def set_installed_digest(skill_id: str, digest: str) -> None:
    """
    Record the canonical digest that an installed skill was verified against.

    In: the skill identifier and the verified digest. Out: nothing.
    """
    with atomic.mutate_json(_installed_digests_path(), default={}) as digests:
        digests[skill_id] = digest


def remove_installed_digest(skill_id: str) -> None:
    """
    Forget the verified digest for a skill (used when it is uninstalled).

    In: the skill identifier. Out: nothing. Doing it for a skill with no recorded
    digest is harmless.
    """
    with atomic.mutate_json(_installed_digests_path(), default={}) as digests:
        digests.pop(skill_id, None)


# --- Activity log ----------------------------------------------------------------


def append_activity(entry: ActivityEntry) -> ActivityEntry:
    """
    Record one completed exchange with the assistant.

    In: the activity entry. Out: the same entry.

    Entries are added to the end, so the file reads oldest-first.
    """
    with atomic.mutate_json(get_settings().activity_file, default=[]) as entries:
        entries.append(entry.model_dump())
    return entry


def load_activity(
    limit: int | None = None,
    *,
    skill_id: str | None = None,
    since: str | None = None,
) -> list[ActivityEntry]:
    """
    Read the activity log, optionally narrowed down.

    In:
      limit    - keep only the most recent N entries (None means all);
      skill_id - keep only exchanges where that skill ran;
      since    - keep only entries stamped at or after this time.
    Out: matching entries, oldest first.
    """
    raw = atomic.read_json(get_settings().activity_file, default=[])

    entries: list[ActivityEntry] = []
    for item in raw:
        try:
            entries.append(ActivityEntry(**item))
        except Exception:
            continue

    if skill_id is not None:
        entries = [
            entry
            for entry in entries
            if entry.skill_invoked is not None
            and entry.skill_invoked.skill_id == skill_id
        ]

    if since is not None:
        # Timestamps are written in a format where comparing the text alphabetically
        # gives the same answer as comparing the moments in time, so a plain string
        # comparison is correct here and needs no date parsing.
        entries = [entry for entry in entries if entry.ts >= since]

    if limit is not None and limit >= 0:
        entries = entries[-limit:] if limit else []

    return entries


# --- Team dashboard --------------------------------------------------------------


def _dashboard_path() -> Path:
    return get_settings().dashboard_file


def append_standup(standup: Standup) -> Standup:
    """
    Store one standup line posted to the team dashboard.

    In: the standup record. Out: the same record.

    Entries are added to the end, so the file reads oldest-first. Only standup lines are
    ever written here; the stolen-task backups a malicious skill sends go to the
    collector's inbox, never to this file - which is what keeps the theft off the
    dashboard.
    """
    with atomic.mutate_json(_dashboard_path(), default=[]) as entries:
        entries.append(standup.model_dump())
    return standup


def load_standups() -> list[Standup]:
    """
    Read every standup posted to the dashboard.

    In: nothing. Out: a list of standup records, oldest first.
    """
    raw = atomic.read_json(_dashboard_path(), default=[])
    standups: list[Standup] = []
    for item in raw:
        try:
            standups.append(Standup(**item))
        except Exception:
            # A malformed row should not hide the healthy ones.
            continue
    return standups


# --- Findings --------------------------------------------------------------------


def load_findings() -> list[Finding]:
    """
    Read every security finding recorded so far.

    In: nothing. Out: a list of findings, oldest first.
    """
    raw = atomic.read_json(get_settings().findings_file, default=[])
    findings: list[Finding] = []
    for item in raw:
        try:
            findings.append(Finding(**item))
        except Exception:
            continue
    return findings


def upsert_finding(finding: Finding) -> tuple[Finding, bool]:
    """
    Record a finding, merging it with an identical earlier one if there is one.

    In: the finding to record.
    Out: a pair - the stored finding, and True if this was the first time we have
    seen this exact problem.

    "The same problem" means the same skill, same version, same type, same
    capability and same resource. When we see a repeat we bump the count and the
    "last seen" time instead of adding another entry, so the findings list stays
    short enough to read. The original identifier and first-seen time are never
    changed, because anything already referring to this finding must keep working.
    """
    key = finding.dedup_key()

    with atomic.mutate_json(get_settings().findings_file, default=[]) as stored:
        for item in stored:
            try:
                existing = Finding(**item)
            except Exception:
                continue

            if existing.dedup_key() != key:
                continue

            # Seen before: count it and move on.
            item["occurrences"] = int(item.get("occurrences", 1)) + 1
            item["last_seen"] = finding.last_seen
            return Finding(**item), False

        # Brand new problem: store it as-is.
        stored.append(finding.model_dump())
        return finding, True


def save_findings(findings: list[Finding]) -> None:
    """Replace the whole findings list. Used by the lab reset."""
    atomic.write_json_atomic(
        get_settings().findings_file, [finding.model_dump() for finding in findings]
    )


# --- Lab reset -------------------------------------------------------------------


def reset_lab() -> dict[str, Any]:
    """
    Clear what the app has observed, and put fresh to-do items back.

    In: nothing. Out: a summary of what was cleared.

    IMPORTANT: this is a convenience for running demonstrations repeatedly. It is
    NOT a security switch. It changes no skill, no declared permission and no
    policy - every weakness present before a reset is still present afterwards. All
    it does is make the app forget what it saw.
    """
    from app.storage import seed

    settings = get_settings()

    cleared = {
        "findings": len(load_findings()),
        "activity": len(atomic.read_json(settings.activity_file, default=[])),
        "standups": len(atomic.read_json(settings.dashboard_file, default=[])),
        "markers": 0,
        "collector": 0,
    }

    atomic.write_json_atomic(settings.findings_file, [])
    atomic.write_json_atomic(settings.activity_file, [])
    # Wipe the team dashboard too, so a reset clears the visible standups along with
    # everything else and the lab returns to a genuinely clean slate.
    atomic.write_json_atomic(settings.dashboard_file, [])

    # Delete the evidence files and the pretend stolen-data inbox.
    for folder, key in [
        (settings.markers_dir, "markers"),
        (settings.collector_dir / "inbox", "collector"),
    ]:
        if folder.exists():
            files = [path for path in folder.iterdir() if path.is_file()]
            cleared[key] = len(files)
            for path in files:
                path.unlink()

    # Note what stays: the list of installed skills is deliberately preserved, so a
    # demonstration does not have to reinstall everything after each reset.
    installed_before = load_installed().installed

    if settings.tasks_file.exists():
        settings.tasks_file.unlink()
    seeded = seed.seed_tasks_if_absent()

    return {
        "cleared": cleared,
        "tasks_reseeded": seeded,
        "installed_preserved": installed_before,
        "note": "Lab convenience only. Reset cannot make the app less vulnerable.",
    }
