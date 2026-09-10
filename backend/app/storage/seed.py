"""
The starter to-do list for a brand new lab.

Why bother making these believable? Because the user's task list is the thing the
deliberately-malicious skills will later try to steal. If the list held "test 1,
test 2, test 3", watching it get stolen would feel like a toy demonstration. Real-
looking personal admin makes the theft land as a real loss - which is the point.

The dates are spread over the past few weeks so that "your oldest unfinished task"
is a meaningful thing for the assistant to tell you.

Specification references: feature spec section 4.3, decision S-14, requirement
FR-1.3. Seeding never installs a skill (TDD section 14, Q-6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.storage import atomic
from app.storage.models import Task
from app.storage.store import new_id


# Each entry is: (title, notes, already finished?, how many days ago it was created).
STARTER_TASKS: list[tuple[str, str, bool, int]] = [
    ("Renew passport", "Expires in March - book the photo appointment first.", False, 21),
    ("Send Q3 budget numbers to Priya", "She needs the travel line split out.", True, 19),
    ("Book dentist check-up", "Overdue by about four months.", False, 17),
    ("Cancel the unused cloud storage plan", "Billing on the 3rd each month.", False, 14),
    ("Draft the team offsite agenda", "Half a day, needs a decision slot.", False, 9),
    ("Reply to the landlord about the boiler", "They asked twice now.", True, 6),
    ("Back up the photo library", "External drive is in the desk drawer.", False, 3),
    ("Order a birthday present for Dad", "Something for the garden.", True, 1),
]


def _timestamp_days_ago(days: int) -> str:
    """
    Work out a timestamp for a moment some days in the past.

    In: how many days ago. Out: that moment, written the standard way.
    """
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def build_starter_tasks() -> list[Task]:
    """
    Build the starter to-do items.

    In: nothing. Out: a list of Task records, oldest first.
    """
    tasks: list[Task] = []
    for title, notes, done, days_ago in STARTER_TASKS:
        created = _timestamp_days_ago(days_ago)
        tasks.append(
            Task(
                id=new_id("tsk"),
                title=title,
                notes=notes,
                done=done,
                created_at=created,
                # A finished task is recorded as having been finished a day after it
                # was created, which is enough to look plausible.
                completed_at=_timestamp_days_ago(max(days_ago - 1, 0)) if done else None,
            )
        )
    # Oldest first, matching how the rest of the app expects to read them.
    tasks.sort(key=lambda task: task.created_at)
    return tasks


def seed_tasks_if_absent() -> int:
    """
    Put the starter list in place, but only on a brand new lab.

    In: nothing. Out: how many tasks were created (0 if the file already existed).

    The "only if absent" rule matters: restarting the app must never wipe out work
    someone has done. Deleting the data folder is the deliberate way to start over.
    """
    tasks_file = get_settings().tasks_file

    if tasks_file.exists():
        return 0

    tasks = build_starter_tasks()
    atomic.write_json_atomic(tasks_file, [task.model_dump() for task in tasks])
    return len(tasks)
