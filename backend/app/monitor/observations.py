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


def payload_item_digests(value: Any) -> list[str]:
    """
    Make a fingerprint of every individual item inside a piece of outgoing data.

    In: anything that can be written as JSON (usually the body of a network send).
    Out: one 64-character fingerprint for each item found inside it.

    WHY THIS EXISTS. When the task list is read, we fingerprint each task on its own
    (see TaskBroker.list). To later prove those very tasks were the thing sent out, we
    need the same per-item fingerprints on the send side too - and they must survive a
    skill that hides the tasks inside a bigger message. A thief rarely posts the list
    exactly as read; they wrap it ("here is my backup: [ ...tasks... ]"), send only
    some of it, or shuffle the order. A single fingerprint of the whole message would
    not match in any of those cases.

    So instead of fingerprinting the whole message, we look *inside* it: we walk
    through the data and take a fingerprint of every item that appears in any list,
    however deeply it is buried. A task wrapped inside an envelope still produces the
    exact same fingerprint it had when it was read, because we fingerprint the task
    itself, not the envelope around it. It is like checking every item in a parcel
    against a list of stolen goods, rather than only weighing the parcel as a whole.

    The fingerprints use the very same recipe as digest_of, so a task read and a task
    sent line up to the identical fingerprint. A skill that transforms an item beyond
    recognition first - encrypting or re-encoding it - will not match, and that limit
    is deliberate and stated in the spec (Spec S-2): a fingerprint proves data moved,
    it cannot prove data moved under disguise.
    """
    digests: list[str] = []
    _collect_item_digests(value, digests)
    return digests


def _collect_item_digests(value: Any, digests: list[str]) -> None:
    """
    Walk one piece of data and collect a fingerprint of every list item inside it.

    In: the data to look through, and the list to add fingerprints to.
    Out: nothing (it fills the list it was given).

    For every list we meet, each element gets its own fingerprint - that is the item
    a covert-flow check compares against. We then keep looking inside that element too,
    so items hidden in a list nested within another list are still found.
    """
    if isinstance(value, list):
        for element in value:
            # Fingerprint the whole element (e.g. one task), exactly as it was
            # fingerprinted when it was read, then keep looking inside it.
            digests.append(digest_of(element))
            _collect_item_digests(element, digests)
    elif isinstance(value, dict):
        # A dict is an envelope, not an item in its own right - look through its
        # values so tasks tucked under a key like "items" are still found.
        for nested in value.values():
            _collect_item_digests(nested, digests)


def content_item_digests(value: Any) -> list[str]:
    """
    Make a fingerprint of every individual piece of text inside some FETCHED content.

    In: anything that came back from a network request, already read as JSON.
    Out: one 64-character fingerprint per piece of text found inside it.

    WHY THIS EXISTS, AND WHY IT IS NOT payload_item_digests. The function above is for
    data going OUT: it fingerprints the items in a list, because the thing we want to
    recognise later is "one of the user's tasks". This one is for content coming BACK,
    where the thing we want to recognise later is completely different: a single piece
    of TEXT buried anywhere inside the reply - a web address, a file path, a line of
    instructions - which the skill might then go and act on.

    An example makes the difference obvious. A fetched document like

        {"rules": [...], "report_to": "http://127.0.0.1:8000/mock/collector"}

    contains one very interesting piece of text, and it is not in a list at all. It is
    the value of "report_to". If the skill then sends something to that exact address,
    the address it used and the address in the document produce the identical
    fingerprint - and that is how we can later prove the document chose the
    destination. payload_item_digests walks lists only, so it would never see it.

    The recipe is the same digest_of used everywhere else, so a piece of text here and
    the resource of a later action line up to the identical fingerprint.

    Deliberately NOT fingerprinted: numbers and true/false. They collide constantly -
    every document containing "5" would match every action mentioning 5 - and a
    coincidence dressed as evidence is worse than no evidence.
    """
    digests: list[str] = []
    _collect_content_digests(value, digests)
    # The same piece of text can appear more than once; one fingerprint is enough.
    return list(dict.fromkeys(digests))


def _collect_content_digests(value: Any, digests: list[str]) -> None:
    """
    Walk fetched content and collect a fingerprint of every piece of text in it.

    In: the content to look through, and the list to add fingerprints to.
    Out: nothing (it fills the list it was given).
    """
    if isinstance(value, str):
        digests.append(digest_of(value))
    elif isinstance(value, list):
        for element in value:
            # Fingerprint the whole element too, so a complete object inside a list is
            # recognisable as well as the pieces of text within it.
            digests.append(digest_of(element))
            _collect_content_digests(element, digests)
    elif isinstance(value, dict):
        for nested in value.values():
            _collect_content_digests(nested, digests)


# The longest piece of text we keep for the "was this repeated word for word?" check
# below. Anything longer is almost certainly a document body rather than a line someone
# would relay, and keeping it would bloat every record of every request.
MAX_CONTENT_STRING = 1024

# How many pieces of text we keep. A generous ceiling that a normal reply never reaches,
# there only so an enormous one cannot fill the records.
MAX_CONTENT_STRINGS = 64


def content_strings(value: Any) -> list[str]:
    """
    Collect the actual pieces of text inside some fetched content.

    In: anything that came back from a network request, already read as JSON.
    Out: the pieces of text themselves, longest first, capped.

    WHY THE TEXT ITSELF AND NOT JUST A FINGERPRINT. Fingerprints answer "is this exactly
    the same thing?" - perfect for comparing an address in a document against the address
    a skill then used. They cannot answer "does this sentence appear INSIDE that longer
    sentence?", and that is the other question worth asking: whether a line from the
    fetched document was passed along, word for word, in what the skill told the
    assistant. Answering that needs the words.

    Longest first, because a longer match is a more convincing one - a twelve-character
    coincidence is possible, a whole sentence repeated verbatim is not.
    """
    collected: list[str] = []
    _collect_content_strings(value, collected)

    unique = list(dict.fromkeys(collected))
    unique.sort(key=len, reverse=True)
    return unique[:MAX_CONTENT_STRINGS]


def _collect_content_strings(value: Any, collected: list[str]) -> None:
    """
    Walk fetched content and collect every piece of text short enough to keep.

    In: the content, and the list to fill. Out: nothing.
    """
    if isinstance(value, str):
        if value and len(value) <= MAX_CONTENT_STRING:
            collected.append(value)
    elif isinstance(value, list):
        for element in value:
            _collect_content_strings(element, collected)
    elif isinstance(value, dict):
        for nested in value.values():
            _collect_content_strings(nested, collected)


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
