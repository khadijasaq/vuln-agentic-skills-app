"""
The official channel: the only supported way for a skill to touch anything.

A skill never opens a file, calls a website, or reads a task directly. It asks this
code to do it. Every request follows the same four steps, in this exact order:

    1. WRITE DOWN WHAT WAS ASKED FOR      (always, before anything else)
    2. DECIDE WHETHER IT IS SAFE          (never: "did the skill declare it?")
    3. DO IT, or REFUSE and update the note
    4. HAND BACK THE ANSWER

TWO THINGS ABOUT THAT ORDER ARE ESSENTIAL, and neither may be "simplified" away.

FIRST: the request is written down BEFORE we decide whether to allow it. A skill
trying to send your private task list to some outside address gets refused - nothing
leaves this computer - but the attempt is already recorded, so the security report
still shows exactly what it tried to do. Safety and detection never compete: we get
both. This is like a security guard writing every visitor in the book as they walk
up to the desk, and only then deciding whether to let them through. The refused
visitor is still in the book.

SECOND: this code never looks at what the skill CLAIMED it would do. It genuinely
does not know. Comparing promises against behaviour happens later, somewhere else
entirely. If this code checked declarations, a lying skill would simply be blocked -
and then there would be nothing to catch it doing, which defeats the entire purpose
of the exercise. This is why nothing in this file imports anything about manifests.

Specification references: feature spec sections 5.5 and 7.1-7.3; TDD sections 3.1
and 8; decisions S-19, S-26, S-27, S-28; invariants I-2 and I-3.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.monitor.audit_hook import broker_frame
from app.monitor.observations import ObservationLog, digest_of, size_of
from app.storage import store

logger = logging.getLogger("taskbot.broker")


# Only these addresses may be contacted. All three mean "this same computer", so a
# simulated data theft can be observed in full without a single byte leaving the
# machine (requirement FR-7.2).
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# The only two ways of talking to a website that we understand.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Files holding the app's own records. A skill must never be able to overwrite these
# - a skill that could erase the activity log or the findings file could erase the
# evidence of its own behaviour (decision S-27, requirement FR-7.4).
PROTECTED_FILENAMES = frozenset(
    {"tasks.json", "installed.json", "findings.json", "activity.json"}
)

# Settings a skill may read. Everything else is refused, so real secrets that happen
# to be in the environment are out of reach through this channel (decision S-28).
# The AI model address is excluded because it is a network target, not a setting.
ALLOWED_ENV_PREFIX = "TASKBOT_"
BLOCKED_ENV_KEYS = frozenset({"TASKBOT_OLLAMA_URL"})


class CapabilityRefused(Exception):
    """
    Raised when the app refuses a skill's request.

    We raise rather than quietly handing back an empty answer, because a skill
    continuing on with made-up data would hide the refusal and produce confusing
    behaviour. The request has already been written down before this is raised.
    """

    def __init__(self, capability: str, resource: str, reason: str) -> None:
        super().__init__(f"{capability} on {resource!r} was refused: {reason}")
        self.capability = capability
        self.resource = resource
        self.reason = reason


class BrokeredResponse:
    """The simplified answer a skill gets back from a network request."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _BaseBroker:
    """
    Shared machinery for all the official channels.

    Every channel writes into the same notebook and follows the same four steps.
    """

    def __init__(self, log: ObservationLog) -> None:
        self._log = log

    def _record(
        self,
        capability: str,
        resource: str,
        detail: dict[str, Any] | None = None,
    ):
        """
        STEP 1 - write down what was asked for, before deciding anything.

        In: what is being asked, on what, plus any useful detail.
        Out: the written line, so it can be updated if the request is refused.
        """
        return self._log.record(
            capability=capability,
            resource=resource,
            detail=detail or {},
            outcome="ok",
            source="broker",
        )

    def _refuse(self, observation, reason: str) -> None:
        """
        STEP 3 (the refusing branch) - update the existing note and stop.

        In: the line written in step 1, and why the answer is no. Out: never returns.

        The note written in step 1 is UPDATED, not replaced by a new one at the
        bottom. That keeps the request in its true position in the sequence of
        events, which the order-based checks rely on (decision S-26).
        """
        self._log.mark_refused(observation, reason)
        raise CapabilityRefused(observation.capability, observation.resource, reason)


class TaskBroker(_BaseBroker):
    """The official channel for reading and changing the user's to-do items."""

    def list(self, scope: str = "all") -> list[dict]:
        """
        Read the user's to-do items.

        In: which ones - "all", "open" or "done". Out: the matching items.

        Along with the answer we record a fingerprint of the data and a fingerprint
        of each individual item. Those fingerprints are what make it possible, later,
        to prove that a particular piece of information was sent somewhere - without
        keeping a second copy of the user's private data in the security records.
        """
        observation = self._record("task.read", "*", {"scope": scope})

        # Everything inside this block is the app doing its own work, so the
        # process-wide watcher ignores it. Without this, reading the tasks file to
        # answer a polite request would look like the skill secretly reading files.
        with broker_frame():
            tasks = [task.model_dump() for task in store.filter_tasks(store.load_tasks(), scope)]

        observation.detail.update(
            {
                "count": len(tasks),
                "bytes": size_of(tasks),
                "sha256": digest_of(tasks),
                "item_digests": [digest_of(task) for task in tasks],
            }
        )
        return tasks

    def get(self, task_id: str) -> dict:
        """
        Read one to-do item.

        In: which item. Out: the item.

        Asking for something that does not exist is recorded as an error rather than
        a refusal - the skill did nothing wrong, it just asked for a missing thing.
        """
        observation = self._record("task.read", task_id)

        with broker_frame():
            matches = [task for task in store.load_tasks() if task.id == task_id]

        if not matches:
            self._log.mark_error(observation, "task_not_found")
            raise CapabilityRefused("task.read", task_id, "task_not_found")

        task = matches[0].model_dump()
        observation.detail.update({"bytes": size_of(task), "sha256": digest_of(task)})
        return task

    def add(self, title: str, notes: str = "") -> dict:
        """
        Add a to-do item.

        In: the title and optional notes. Out: the item that was created.
        """
        observation = self._record("task.write", "*", {"action": "add", "title": title})

        with broker_frame():
            task = store.add_task(title, notes)

        observation.resource = task.id
        return task.model_dump()

    def update(self, task_id: str, **fields: Any) -> dict:
        """
        Change a to-do item.

        In: which item, and the fields to change. Out: the updated item.
        """
        observation = self._record(
            "task.write", task_id, {"action": "update", "fields": sorted(fields)}
        )

        with broker_frame():
            try:
                task = store.update_task(task_id, **fields)
            except store.TaskNotFound:
                self._log.mark_error(observation, "task_not_found")
                raise CapabilityRefused("task.write", task_id, "task_not_found")

        return task.model_dump()

    def delete(self, task_id: str) -> None:
        """
        Remove a to-do item.

        In: which item. Out: nothing.
        """
        observation = self._record("task.write", task_id, {"action": "delete"})

        with broker_frame():
            try:
                store.delete_task(task_id)
            except store.TaskNotFound:
                self._log.mark_error(observation, "task_not_found")
                raise CapabilityRefused("task.write", task_id, "task_not_found")


class FileBroker(_BaseBroker):
    """
    The official channel for reading and writing files.

    Only two areas of the disk are reachable: the app's own data folder and the
    skills folder. Everything else is refused - and the attempt is recorded.
    """

    def _allowed_roots(self) -> list[Path]:
        """The only two folders a skill may reach through this channel."""
        settings = get_settings()
        return [settings.data_dir, settings.skills_dir]

    def _resolve_and_check(self, observation, raw_path: str) -> Path:
        """
        Work out the real location of a path and check it is somewhere allowed.

        In: the written note, and the path the skill asked for.
        Out: the resolved location, if it is allowed.

        The order here matters. We work out where the path REALLY points before
        checking it, because a path like "data/../../../secrets.txt" looks harmless
        until you follow it. Shortcuts that point elsewhere (symbolic links) are
        followed for the same reason.

        The note keeps the path the skill ASKED for, not where it turned out to lead,
        so a security report shows the skill's actual request.
        """
        with broker_frame():
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            resolved = candidate.resolve()

            roots = [root.resolve() for root in self._allowed_roots()]
            inside_allowed_area = any(
                resolved == root or resolved.is_relative_to(root) for root in roots
            )

        if not inside_allowed_area:
            self._refuse(observation, "path_outside_allowed_roots")

        return resolved

    def read(self, path: str) -> str:
        """
        Read a file.

        In: the path. Out: the file's text.
        """
        observation = self._record("fs.read", str(path))
        resolved = self._resolve_and_check(observation, str(path))

        with broker_frame():
            if not resolved.exists():
                self._log.mark_error(observation, "file_not_found")
                raise CapabilityRefused("fs.read", str(path), "file_not_found")
            content = resolved.read_text(encoding="utf-8", errors="replace")

        observation.detail.update({"bytes": size_of(content), "sha256": digest_of(content)})
        return content

    def write(self, path: str, content: str) -> None:
        """
        Write a file.

        In: the path and the text to write. Out: nothing.

        Two things are refused: writing outside the allowed folders, and overwriting
        any of the app's own record files. A skill that could overwrite the activity
        log or the findings file could erase the evidence of its own behaviour.
        """
        observation = self._record(
            "fs.write", str(path), {"bytes": size_of(content), "sha256": digest_of(content)}
        )
        resolved = self._resolve_and_check(observation, str(path))

        # Protect the app's own records (decision S-27).
        settings = get_settings()
        if resolved.name in PROTECTED_FILENAMES or resolved.is_relative_to(
            settings.markers_dir.resolve()
        ):
            self._refuse(observation, "protected_state_file")

        with broker_frame():
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")


class NetBroker(_BaseBroker):
    """
    The official channel for network requests.

    Only addresses on this same computer are allowed. That is what lets a simulated
    data theft be observed in complete detail while nothing actually leaves the
    machine - the exploit succeeds from the attacker's point of view and from the
    detector's point of view, and stops at the very last inch.
    """

    def get(self, url: str) -> BrokeredResponse:
        """
        Fetch a web address.

        In: the address. Out: the response.
        """
        return self._request("GET", url, None)

    def post(self, url: str, json: dict | None = None) -> BrokeredResponse:
        """
        Send data to a web address.

        In: the address and the data. Out: the response.
        """
        return self._request("POST", url, json)

    def _request(self, method: str, url: str, payload: dict | None) -> BrokeredResponse:
        """
        Make one network request, recording it first.

        In: the method, the address, and any data being sent. Out: the response.

        Note that the fingerprint of the data being sent is recorded BEFORE we decide
        whether to allow the request. That is what makes a blocked attempt still
        useful as evidence: we know exactly what the skill was trying to send.
        """
        detail: dict[str, Any] = {"method": method}
        if payload is not None:
            detail["bytes"] = size_of(payload)
            detail["sha256"] = digest_of(payload)

        observation = self._record("net.outbound", url, detail)

        parsed = urlparse(url)

        if parsed.scheme not in ALLOWED_SCHEMES:
            self._refuse(observation, "unsupported_scheme")

        hostname = (parsed.hostname or "").lower()
        if hostname not in LOCAL_HOSTS:
            # THE MOMENT THAT KEEPS THIS SAFE. The attempt is already written down
            # above, so the security report is complete - but no request is made and
            # nothing leaves this computer.
            self._refuse(observation, "non_local_host")

        with broker_frame():
            try:
                with httpx.Client(timeout=5.0) as client:
                    if method == "POST":
                        response = client.post(url, json=payload)
                    else:
                        response = client.get(url)
                result = BrokeredResponse(response.status_code, response.text)
            except Exception as error:
                self._log.mark_error(observation, f"request_failed: {error}")
                raise CapabilityRefused("net.outbound", url, "request_failed")

        observation.detail["status"] = result.status_code
        return result


class EnvBroker(_BaseBroker):
    """
    The official channel for reading configuration settings.

    Only TaskBot's own settings are reachable. Real secrets that happen to live in
    the environment - cloud keys, passwords - are refused, and the attempt recorded.
    """

    def get(self, key: str) -> str | None:
        """
        Read one setting.

        In: the setting name. Out: its value, or nothing if it is not set.
        """
        import os

        observation = self._record("env.read", key)

        if not key.startswith(ALLOWED_ENV_PREFIX) or key in BLOCKED_ENV_KEYS:
            self._refuse(observation, "key_not_exposed")

        with broker_frame():
            value = os.environ.get(key)

        observation.detail["present"] = value is not None
        return value


class SkillLogger:
    """
    A way for a skill to leave a note for a human reading the activity screen.

    This needs no permission and records no observation - it is just a message, and
    a message cannot reach anything.
    """

    def __init__(self, log: ObservationLog) -> None:
        self._log = log
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        """
        Leave a note.

        In: the message. Out: nothing.
        """
        self.messages.append(str(message))
        logger.debug("Skill note during %s: %s", self._log.invocation_id, message)


class SkillContext:
    """
    Everything a skill is handed when it runs.

    A skill receives one of these and does everything through it. There is
    deliberately no way to delete or move files, and no way to start another program
    - those are simply not offered, so a skill that wants them has to go around the
    app, which is exactly what the process-wide watcher is there to catch.
    """

    def __init__(self, invocation_id: str, log: ObservationLog) -> None:
        self.invocation_id = invocation_id
        self.tasks = TaskBroker(log)
        self.files = FileBroker(log)
        self.net = NetBroker(log)
        self.env = EnvBroker(log)
        self.log = SkillLogger(log)


class SkillResult:
    """
    What a skill hands back when it finishes.

    summary - a plain sentence the AI model turns into a natural reply.
    data    - the structured details, shown on the activity screen.
    """

    def __init__(self, summary: str, data: dict | None = None) -> None:
        self.summary = summary
        self.data = data
