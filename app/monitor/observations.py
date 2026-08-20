"""
The notebook the app writes in while a skill is running.

Every single thing a skill touches gets one line in this notebook: what it did, what
it did it to, and whether it was allowed. Nothing is ever removed or reordered.

WHY THE ORDER IS KEPT SO CAREFULLY. Some security problems are not about any single
action but about the *sequence* of two innocent-looking ones. Reading the user's
task list is fine. Sending a message to a local address is fine. Reading the task
list and THEN sending it somewhere is theft. Proving that requires knowing which
happened first, so the notebook is a numbered list, never a jumbled bag.

Specification references: feature spec sections 3.7 and 5.7; TDD section 3.1;
decisions D-7 and S-8; invariant I-5.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.storage.store import now_iso

# What happened when a skill asked to do something.
#   ok       - it was allowed and it worked
#   refused  - the app said no (but it still counts: wanting to do it is the story)
#   error    - it was allowed but something went wrong
Outcome = Literal["ok", "refused", "error"]

# Who noticed.
#   broker      - the skill asked properly, through the official channel
#   audit_hook  - the skill went around the official channel and was caught anyway
Source = Literal["broker", "audit_hook"]


class Observation(BaseModel):
    """
    One line in the notebook: a single thing a skill did or tried to do.

    These are deliberately NOT frozen. When the app refuses a request it goes back
    and updates the line it already wrote, rather than writing a new one at the
    bottom. That keeps the request in its true position in the sequence - which the
    order-based security checks depend on (decision S-26).
    """

    seq: int
    invocation_id: str
    capability: str
    resource: str
    detail: dict[str, Any] = Field(default_factory=dict)
    outcome: Outcome = "ok"
    refusal_reason: str | None = None
    source: Source = "broker"
    ts: str = ""


def digest_of(value: Any) -> str:
    """
    Make a short fingerprint of some data.

    In: anything that can be written as JSON. Out: a 64-character fingerprint.

    We record fingerprints instead of the data itself. That is enough to later prove
    "the thing that was sent is the same thing that was read" without keeping a
    second copy of the user's private information inside the security records.

    It is like noting a parcel's weight and shape rather than opening it: enough to
    recognise the same parcel later, without reading what is inside.
    """
    text = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def size_of(value: Any) -> int:
    """
    How big a piece of data is, in bytes, once written as JSON.

    In: anything JSON-friendly. Out: a byte count.
    """
    return len(json.dumps(value, default=str).encode("utf-8"))


class ObservationLog:
    """
    The notebook for ONE run of ONE skill.

    A fresh notebook is started every time a skill runs, so two skills running at
    the same time can never get their records mixed up.
    """

    def __init__(self, invocation_id: str) -> None:
        self.invocation_id = invocation_id
        self._entries: list[Observation] = []
        # Two watchers can write here at once (the official channel and the
        # process-wide one), so adding a line is protected.
        self._guard = threading.Lock()

    def record(
        self,
        *,
        capability: str,
        resource: str,
        detail: dict[str, Any] | None = None,
        outcome: Outcome = "ok",
        source: Source = "broker",
        refusal_reason: str | None = None,
    ) -> Observation:
        """
        Write one line in the notebook.

        In: what was done, what it was done to, any extra detail, how it turned out,
        and who noticed.
        Out: the line that was written, so the caller can update it later if the
        request ends up being refused.

        Line numbers start at 1 and only ever go up.
        """
        with self._guard:
            observation = Observation(
                seq=len(self._entries) + 1,
                invocation_id=self.invocation_id,
                capability=capability,
                resource=resource,
                detail=dict(detail or {}),
                outcome=outcome,
                source=source,
                refusal_reason=refusal_reason,
                ts=now_iso(),
            )
            self._entries.append(observation)
            return observation

    def mark_refused(self, observation: Observation, reason: str) -> Observation:
        """
        Update a line that has already been written, to say the request was refused.

        In: the line, and why it was refused. Out: the same line, updated.

        This deliberately edits the existing line instead of adding a new one. If a
        refusal were written at the bottom, a refused attempt would appear to have
        happened later than it really did, and any check that reads the order of
        events would be looking at a false story (decision S-26).
        """
        observation.outcome = "refused"
        observation.refusal_reason = reason
        return observation

    def mark_error(self, observation: Observation, reason: str) -> Observation:
        """
        Update a line to say the request was allowed but went wrong.

        In: the line and what went wrong. Out: the same line, updated.
        """
        observation.outcome = "error"
        observation.refusal_reason = reason
        return observation

    def entries(self) -> list[Observation]:
        """
        The whole notebook, in the order it was written.

        In: nothing. Out: the lines, first to last.

        A copy of the list is returned so nobody outside can add, remove or reorder
        lines. The order is evidence, and evidence must not be editable.
        """
        with self._guard:
            return list(self._entries)

    def as_dicts(self) -> list[dict[str, Any]]:
        """The notebook in plain dictionary form, ready to be saved as JSON."""
        return [observation.model_dump() for observation in self.entries()]

    def __len__(self) -> int:
        """How many lines are in the notebook."""
        return len(self._entries)
