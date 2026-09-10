"""
Talking to the AI model via Groq cloud API.

This replaces the local Ollama setup with Groq's hosted LLM service.
The interface is kept identical to OllamaClient so the rest of the app
needs minimal changes.

The model is given a list of "tools" it may ask for, each one described in plain
words. It replies either with an ordinary sentence, or with a request to use one of
those tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.config import get_settings

logger = logging.getLogger("taskbot.llm")

READ_TIMEOUT_SECONDS = 120.0


class LlmUnavailable(Exception):
    """
    Raised when the AI model cannot be used.

    reason - a short code saying what kind of problem it is.
    detail - a human-readable explanation.
    remedy - what to do to fix it.
    """

    def __init__(
        self,
        reason: Literal["unreachable", "model_missing", "timeout", "protocol", "auth"],
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
    model      - the model the server says it actually used.
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
    remedy: str = ""


class GroqClient:
    """A client for the Groq cloud LLM API (OpenAI-compatible)."""

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.groq_base_url).rstrip("/")
        self._model = model or settings.model
        self._api_key = settings.groq_api_key

    @property
    def model(self) -> str:
        return self._model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def health(self) -> HealthInfo:
        """
        Check whether Groq is reachable and the model is available.
        Never raises - being unreachable is a normal answer.
        """
        if not self._api_key:
            return HealthInfo(
                reachable=False,
                model_present=False,
                url=self._base_url,
                remedy="Set the GROQ_API_KEY environment variable.",
            )

        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
            ) as client:
                response = client.get(
                    f"{self._base_url}/models", headers=self._headers()
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return HealthInfo(reachable=False, model_present=False, url=self._base_url)

        models = [m.get("id", "") for m in payload.get("data", [])]
        present = any(self._model in model_id for model_id in models)
        return HealthInfo(
            reachable=True, model_present=present, url=self._base_url, models=models
        )

    def chat(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> ChatResponse:
        """
        Send the conversation to the model and get its answer.

        Raises LlmUnavailable if the model cannot be reached or answers
        in a shape we do not understand.
        """
        if not self._api_key:
            raise LlmUnavailable(
                "auth",
                "No Groq API key configured. Set the GROQ_API_KEY environment variable.",
                "Set GROQ_API_KEY to your Groq API key (gsk_...).",
            )

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools

        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    connect=5.0, read=READ_TIMEOUT_SECONDS, write=30.0, pool=5.0
                )
            ) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as error:
            raise LlmUnavailable(
                "timeout",
                f"The model did not answer within {int(READ_TIMEOUT_SECONDS)} seconds: {error}",
                "Try again - Groq is usually fast but may be under load.",
            ) from error
        except httpx.HTTPError as error:
            raise LlmUnavailable(
                "unreachable",
                f"Could not reach Groq API at {self._base_url}: {error}",
                "Check your internet connection and the GROQ_BASE_URL setting.",
            ) from error

        if response.status_code == 401:
            raise LlmUnavailable(
                "auth",
                "Groq rejected the API key (HTTP 401).",
                "Check that GROQ_API_KEY is a valid key starting with gsk_.",
            )

        if response.status_code == 404:
            raise LlmUnavailable(
                "model_missing",
                f"The model {self._model!r} is not available on Groq.",
                f"Check the model name. Popular Groq models: llama-3.1-8b-instant, mixtral-8x7b-32768.",
            )

        if response.status_code >= 400:
            raise LlmUnavailable(
                "unreachable",
                f"Groq returned an error ({response.status_code}): {response.text[:200]}",
                "Check the Groq API status or your request parameters.",
            )

        try:
            payload = response.json()
            choice = payload.get("choices", [{}])[0]
            message = choice.get("message", {})
        except Exception as error:
            raise LlmUnavailable(
                "protocol",
                f"Groq answered in a shape we do not understand: {error}",
                "Check that the model supports tool calling.",
            ) from error

        return ChatResponse(
            content=message.get("content") or "",
            tool_calls=self._parse_tool_calls(message),
            model=payload.get("model", self._model),
        )

    def _parse_tool_calls(self, message: dict) -> list[ToolCall]:
        """
        Pull out any tool requests from the model's answer.
        Groq uses OpenAI format: tool_calls is a list of objects with
        function.name and function.arguments.
        """
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise LlmUnavailable(
                "protocol",
                "The AI model sent tool requests in an unexpected shape.",
                f"Check that {self._model} supports tool calling.",
            )

        calls: list[ToolCall] = []
        for entry in raw_calls:
            function = (entry or {}).get("function") or {}
            name = function.get("name")
            if not name:
                raise LlmUnavailable(
                    "protocol",
                    "The AI model asked to use a tool but did not say which one.",
                    f"Check that {self._model} supports tool calling.",
                )
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                import json

                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}
            calls.append(ToolCall(name=name, arguments=arguments))

        return calls
