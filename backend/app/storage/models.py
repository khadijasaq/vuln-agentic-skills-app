"""
The shapes of everything TaskBot saves to disk.

Five kinds of record live here:

  Task          - one to-do item belonging to the user.
  InstalledState- which skills the user has switched on.
  Finding       - a security problem the app noticed about a skill.
  ActivityEntry - the full story of one exchange with the assistant.
  Standup       - one short standup line posted to the team dashboard.

Defining them in one place, next to the code that saves them, keeps the parts of
the app from having to import each other in a circle. (Build-plan note P-1.)

Every record carries a "schema_version" so that future versions of TaskBot can tell
which format they are looking at.

Specification references: feature spec sections 3.1, 3.2, 3.8, 3.9; TDD section 4.7.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

# The words we use for how serious a finding is. They are ordered from worst to
# mildest, which the user interface relies on when sorting.
Severity = Literal["critical", "high", "medium", "low", "info"]

# Which of the four questions a finding answers. Keeping these separate is the
# whole reason the different vulnerability types cannot be mistaken for each other
# (see TDD section 4.1).
Axis = Literal["truthfulness", "proportionality", "correlation", "provenance"]


class Task(BaseModel):
    """
    One item on the user's to-do list.

    This is the valuable thing in the app - the "crown jewels". The whole point of
    the security exercise is that some skills will try to steal it.
    """

    schema_version: int = Field(default=SCHEMA_VERSION)
    id: str
    title: str
    notes: str = ""
    done: bool = False
    created_at: str
    completed_at: str | None = None


class Standup(BaseModel):
    """
    One standup update posted to the team dashboard.

    This holds ONLY the short, advertised standup line - a one-line message, the count
    of open tasks, and the title of the oldest one - and never any task contents. That
    limit is deliberate and load-bearing: the dashboard shows the honest update a skill
    posts, and must never become a place the full task list could appear. There is no
    field here that could hold a task list even if something tried to store one.
    """

    schema_version: int = Field(default=SCHEMA_VERSION)
    id: str
    message: str
    open_count: int = 0
    oldest: str = ""
    posted_at: str


class InstalledState(BaseModel):
    """
    Which skills are currently switched on.

    The order is the order they were installed, which is only used for display.
    """

    schema_version: int = Field(default=SCHEMA_VERSION)
    installed: list[str] = Field(default_factory=list)
    updated_at: str


class Finding(BaseModel):
    """
    One security problem the app noticed about a skill.

    A finding is also the proof that the problem really happened: the app only
    creates one after actually watching a skill behave, never by guessing from
    reading its code.

    Which fields are filled in tells you which kind of problem it is:
      - "observed"    is filled for truthfulness problems (it did something it did
                      not declare);
      - "granted"     is filled for proportionality problems (it was given more
                      power than its job needs);
      - "correlation" is filled for combination problems (it joined two innocent
                      abilities into a harmful one);
      - "provenance"  is filled for instruction problems (something it fetched from
                      outside decided what it did next).
    """

    schema_version: int = Field(default=SCHEMA_VERSION)
    id: str
    type: str
    ast_id: str
    ast_name: str
    axis: Axis
    severity: Severity

    skill_id: str
    skill_version: str

    # "install" means we spotted it just from what the skill asked for, before it
    # ever ran. "invocation" means we spotted it while it was running.
    trigger: Literal["install", "invocation"] = "invocation"
    invocation_id: str | None = None
    activity_id: str | None = None

    # Which AI model was in charge when this happened. Recorded as part of the
    # evidence, because a claim like "the assistant chose to run this" only means
    # something if you know which assistant.
    model: str | None = None

    declared: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] | None = None
    granted: dict[str, Any] | None = None
    correlation: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    summary: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)

    first_seen: str
    last_seen: str
    occurrences: int = 1

    def dedup_key(self) -> tuple:
        """
        Work out whether two findings are really "the same problem seen again".

        In: nothing (uses this finding's own fields).
        Out: a small bundle of values that identifies the problem.

        If a skill misbehaves the same way fifty times we want one finding with a
        count of fifty, not fifty near-identical entries burying everything else.
        """
        capability = None
        resource = None
        if self.observed:
            capability = self.observed.get("capability")
            resource = self.observed.get("resource")
        elif self.granted:
            capability = self.granted.get("capability")
        elif self.correlation:
            # A combination problem has no single capability or resource - it is a
            # pair of lines (a read and a send). We identify it by that pair, so the
            # same read-then-send seen again counts as a repeat, while a genuinely
            # different pair stays its own finding.
            seqs = tuple(self.correlation.get("observation_seqs") or [])
            return (self.skill_id, self.skill_version, self.type, None, seqs)
        elif self.provenance:
            # An instruction problem is also a pair of lines - the fetch, and the thing
            # it went on to steer. Same reasoning as above: the same pair seen again is
            # a repeat, a different pair is its own finding. The kind of influence is
            # part of the key too, because one fetch steering an action and that same
            # fetch putting words in the assistant's mouth are two different problems.
            pair = (
                self.provenance.get("source_seq"),
                self.provenance.get("acted_seq"),
                self.provenance.get("influence"),
            )
            return (self.skill_id, self.skill_version, self.type, None, pair)
        return (self.skill_id, self.skill_version, self.type, capability, resource)


class SkillInvocationRecord(BaseModel):
    """The part of an activity entry describing the skill that ran, if any."""

    skill_id: str
    skill_version: str
    invocation_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    outcome: Literal["ok", "error"] = "ok"
    error: str | None = None
    duration_ms: int = 0


class ActivityEntry(BaseModel):
    """
    The complete story of one exchange: what the user said, what came back, whether
    a skill ran, everything that skill touched, and any problems noticed.

    This is the screen a person watches during a demonstration. It is deliberately
    detailed enough to follow an exploit from start to finish without reading code.
    """

    schema_version: int = Field(default=SCHEMA_VERSION)
    id: str
    ts: str
    user_message: str
    reply: str
    model: str | None = None

    skill_invoked: SkillInvocationRecord | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    findings_raised: list[str] = Field(default_factory=list)

    # A simple yes/no flag so the activity screen can highlight the interesting rows
    # without re-deriving it each time.
    vulnerability_fired: bool = False

    # If the AI model asked for several skills at once we only run the first, and
    # note here how many we ignored (decision S-31).
    extra_tool_calls_ignored: int = 0
