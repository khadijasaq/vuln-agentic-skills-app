"""
Talking to the AI model running on this computer.

TaskBot uses Ollama, a program that runs a language model locally. Nothing is sent
to any outside service - the model, the conversation and the task data all stay on
this machine.

The model is given a list of "tools" it may ask for, each one described in plain
words. It replies either with an ordinary sentence, or with a request to use one of
those tools. That request is the ONLY way a skill ever gets run.

WHAT HAPPENS WHEN THE MODEL IS NOT AVAILABLE. We stop and say so, loudly and with
the exact command to fix it. We deliberately do NOT fall back to a canned reply or
to guessing what the user wanted. Two reasons:

  1. Guessing from the user's words is exactly the "decide things in code rather
     than letting the agent decide" that this project forbids.
  2. A fallback would let a demonstration appear to work with no model running at
     all - which would make every claim about what the agent chose to do worthless.

Being visibly broken is much better than being quietly wrong.

Specification references: feature spec sections 5.2 and 8.4; TDD section 5;
decisions D-13, D-14, S-16, S-36.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.config import get_settings

logger = logging.getLogger("taskbot.llm")


# How long to wait for the model to answer, in seconds.
#
# This is generous on purpose. A mid-sized model with no graphics card has to be
# read into memory - several gigabytes - before it produces a single word, and every
# message here costs TWO model calls: one to decide whether a skill applies, and one
# to turn the result into a natural sentence. An impatient limit would report a
# perfectly healthy model as broken (decision S-36).
READ_TIMEOUT_SECONDS = 300.0

# Ask Ollama to keep the model in memory between messages.
#
# By default it unloads after a few minutes of quiet, so the next message pays the
# whole several-minute reload again. To someone using the app that is indistinguishable
# from it having crashed. Keeping it resident makes the first message slow and every
# message after that quick (decision S-36).
KEEP_MODEL_LOADED = "30m"


class OllamaUnavailable(Exception):
    """
    Raised when the local AI model cannot be used.

    reason - a short code saying what kind of problem it is.
    detail - a human-readable explanation.
    remedy - the exact command that usually fixes it.
    """

    def __init__(
        self,
        reason: Literal["unreachable", "model_missing", "timeout", "protocol"],
        detail: str,
        remedy: str,
    ) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.remedy = remedy


@dataclass(frozen=True)
class ToolCall:
    """The model asking to use one of the tools it was offered."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    """
    What came back from the model.

    content    - an ordinary sentence, if it just wants to reply.
    tool_calls - tools it is asking to use, if any.
    model      - the model the server says it actually used. We record THIS rather
                 than what we asked for, because they can differ and the evidence
                 should say what really happened.
    """

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""


@dataclass(frozen=True)
class HealthInfo:
    """Whether the model is reachable and ready."""

    reachable: bool
    model_present: bool
    url: str
    models: list[str] = field(default_factory=list)


class OllamaClient:
    """A small, direct client for the local Ollama server."""

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.ollama_url).rstrip("/")
        self._model = model or settings.model

    @property
    def model(self) -> str:
        """Which model this client is configured to use."""
        return self._model

    def health(self) -> HealthInfo:
        """
        Check whether the model is running and installed.

        In: nothing. Out: a HealthInfo. Never raises - being unreachable is a normal
        answer to this question, not an error.
        """
        try:
            with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)) as client:
                response = client.get(f"{self._base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return HealthInfo(reachable=False, model_present=False, url=self._base_url)

        names = [entry.get("name", "") for entry in payload.get("models", [])]
        # Ollama sometimes reports "llama3.1:8b" and sometimes just "llama3.1", so we
        # accept either spelling rather than reporting a missing model unnecessarily.
        present = any(
            name == self._model or name.split(":")[0] == self._model.split(":")[0]
            for name in names
        )
        return HealthInfo(
            reachable=True, model_present=present, url=self._base_url, models=names
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse:
        """
        Send the conversation to the model and get its answer.

        In: the conversation so far, and the tools the model may ask for.
        Out: a ChatResponse.

        Raises OllamaUnavailable if the model cannot be reached, is not installed, is
        too slow, or answers in a shape we do not understand.

        There is deliberately NO retrying. A retry would re-run a whole exchange that
        may already have run a skill and recorded observations, which would corrupt
        the evidence trail (decision S-16).
        """
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            # Keep the model in memory so only the first message pays the load cost.
            "keep_alive": KEEP_MODEL_LOADED,
        }
        if tools:
            body["tools"] = tools

        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    connect=5.0, read=READ_TIMEOUT_SECONDS, write=30.0, pool=5.0
                )
            ) as client:
                response = client.post(f"{self._base_url}/api/chat", json=body)
        except httpx.TimeoutException as error:
            raise OllamaUnavailable(
                "timeout",
                f"The model did not answer within {int(READ_TIMEOUT_SECONDS)} seconds: {error}",
                "The model may still be loading. Try again - the first message after "
                "starting up is always the slowest.",
            ) from error
        except httpx.HTTPError as error:
            raise OllamaUnavailable(
                "unreachable",
                f"Could not reach the AI model at {self._base_url}: {error}",
                "Start it with: ollama serve",
            ) from error

        if response.status_code == 404:
            raise OllamaUnavailable(
                "model_missing",
                f"The model {self._model!r} is not installed.",
                f"Install it with: ollama pull {self._model}",
            )

        if response.status_code >= 400:
            raise OllamaUnavailable(
                "unreachable",
                f"The AI model returned an error ({response.status_code}): {response.text[:200]}",
                "Check the Ollama server logs.",
            )

        try:
            payload = response.json()
            message = payload.get("message", {})
        except Exception as error:
            raise OllamaUnavailable(
                "protocol",
                f"The AI model answered in a shape we do not understand: {error}",
                f"Check that {self._model} supports tool calling.",
            ) from error

        return ChatResponse(
            content=message.get("content", "") or "",
            tool_calls=self._parse_tool_calls(message),
            model=payload.get("model", self._model),
        )

    def _parse_tool_calls(self, message: dict) -> list[ToolCall]:
        """
        Pull out any tool requests from the model's answer.

        In: the message part of the answer. Out: the tool requests.

        If the model offers something that does not look like a tool request at all,
        we say so clearly rather than silently ignoring it. Silently ignoring it
        would look exactly like "the model never chose a skill", which would send
        someone hunting for a bug in completely the wrong place (decision S-17).
        """
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise OllamaUnavailable(
                "protocol",
                "The AI model sent tool requests in an unexpected shape.",
                f"Check that {self._model} supports tool calling.",
            )

        calls: list[ToolCall] = []
        for entry in raw_calls:
            function = (entry or {}).get("function") or {}
            name = function.get("name")
            if not name:
                raise OllamaUnavailable(
                    "protocol",
                    "The AI model asked to use a tool but did not say which one.",
                    f"Check that {self._model} supports tool calling.",
                )
            arguments = function.get("arguments") or {}
            if not isinstance(arguments, dict):
                # Some models send the values as text rather than structured data.
                import json

                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}
            calls.append(ToolCall(name=name, arguments=arguments))

        return calls
