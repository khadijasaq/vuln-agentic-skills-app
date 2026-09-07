"""
Checks for the connection to the AI model via Groq API (app/llm/groq_client.py).

No real API calls are made here: a pretend server stands in for Groq, so these checks
run anywhere and always give the same answer.

The important behaviour is what happens when things go wrong. TaskBot must fail
loudly and helpfully rather than quietly carrying on, because a demonstration that
appears to work with no model running would make every claim about what the agent
chose to do worthless.

Covers: feature spec section 5.2; TDD section 5.4; decisions D-13, S-16, S-17.
"""

from __future__ import annotations

import httpx
import pytest

from app.llm.groq_client import GroqClient, LlmUnavailable


def client_with_pretend_server(handler, tmp_settings) -> GroqClient:
    """
    Build a client wired to a pretend Groq server.

    In: a function that decides what the pretend server answers.
    Out: a client that talks to it instead of the real thing.
    """
    client = GroqClient()
    transport = httpx.MockTransport(handler)

    original = httpx.Client

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.Client = PatchedClient
    client._restore = lambda: setattr(httpx, "Client", original)
    return client


@pytest.fixture
def restore_httpx():
    """Put the real HTTP client back after each test."""
    original = httpx.Client
    yield
    httpx.Client = original


# --- Ordinary answers ------------------------------------------------------------


def test_a_plain_reply_comes_back_as_text(tmp_settings, restore_httpx):
    """The simplest case: the model replies with a sentence."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "choices": [{"message": {"content": "Hello there."}}],
            },
        )

    client = client_with_pretend_server(handler, tmp_settings)
    answer = client.chat([{"role": "user", "content": "hi"}])

    assert answer.content == "Hello there."
    assert answer.tool_calls == []


def test_a_tool_request_is_understood(tmp_settings, restore_httpx):
    """When the model asks to use a tool, we get the name and the values."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "task_summary",
                                        "arguments": {"scope": "all"},
                                    }
                                }
                            ],
                        }
                    }
                ],
            },
        )

    client = client_with_pretend_server(handler, tmp_settings)
    answer = client.chat([{"role": "user", "content": "summarise"}], tools=[])

    assert len(answer.tool_calls) == 1
    assert answer.tool_calls[0].name == "task_summary"
    assert answer.tool_calls[0].arguments == {"scope": "all"}


def test_values_sent_as_text_are_still_understood(tmp_settings, restore_httpx):
    """Some models send the values as text rather than structured data."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "task_summary",
                                        "arguments": '{"scope": "open"}',
                                    }
                                }
                            ]
                        }
                    }
                ],
            },
        )

    client = client_with_pretend_server(handler, tmp_settings)
    answer = client.chat([], tools=[])

    assert answer.tool_calls[0].arguments == {"scope": "open"}


def test_the_model_the_server_actually_used_is_recorded(tmp_settings, restore_httpx):
    """
    We record what the server says it used, not what we asked for. They can differ,
    and the evidence should say what really happened.
    """

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "some-other-model",
                "choices": [{"message": {"content": "hi"}}],
            },
        )

    client = client_with_pretend_server(handler, tmp_settings)

    assert client.chat([]).model == "some-other-model"


# --- When things go wrong --------------------------------------------------------


def test_an_unreachable_model_is_reported_with_a_fix(tmp_settings, restore_httpx):
    """
    The error names the problem AND the command that fixes it, so whoever hits it can
    act without going hunting.
    """

    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = client_with_pretend_server(handler, tmp_settings)

    with pytest.raises(LlmUnavailable) as failure:
        client.chat([])

    assert failure.value.reason == "unreachable"
    assert "Groq" in failure.value.remedy or "connection" in failure.value.remedy.lower()


def test_an_auth_failure_is_reported_clearly(tmp_settings, restore_httpx):
    """A bad API key is a distinct problem from a missing model."""

    def handler(request):
        return httpx.Response(401, json={"error": "invalid api key"})

    client = client_with_pretend_server(handler, tmp_settings)

    with pytest.raises(LlmUnavailable) as failure:
        client.chat([])

    assert failure.value.reason == "auth"
    assert "GROQ_API_KEY" in failure.value.remedy


def test_a_missing_model_names_the_model(tmp_settings, restore_httpx):
    """"Not available" is a different problem from "not running"."""

    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})

    client = client_with_pretend_server(handler, tmp_settings)

    with pytest.raises(LlmUnavailable) as failure:
        client.chat([])

    assert failure.value.reason == "model_missing"
    assert "Groq" in failure.value.remedy or "model" in failure.value.remedy.lower()


def test_a_slow_model_is_reported_as_a_timeout(tmp_settings, restore_httpx):
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    client = client_with_pretend_server(handler, tmp_settings)

    with pytest.raises(LlmUnavailable) as failure:
        client.chat([])

    assert failure.value.reason == "timeout"


def test_a_model_that_cannot_use_tools_is_named_clearly(tmp_settings, restore_httpx):
    """
    DECISION S-17.

    If we silently ignored a malformed tool request, it would look exactly like "the
    model never chose a skill" - sending someone hunting for a bug in completely the
    wrong place. Instead we say plainly that the model does not support tools.
    """

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "choices": [
                    {"message": {"tool_calls": [{"function": {"arguments": {}}}]}}
                ],
            },
        )

    client = client_with_pretend_server(handler, tmp_settings)

    with pytest.raises(LlmUnavailable) as failure:
        client.chat([], tools=[])

    assert failure.value.reason == "protocol"
    assert "tool calling" in failure.value.remedy


def test_a_failed_request_is_never_retried(tmp_settings, restore_httpx):
    """
    DECISION S-16.

    A retry would re-run a whole exchange that may already have run a skill and
    recorded what it did. That would corrupt the evidence trail, so one attempt only.
    """
    attempts = []

    def handler(request):
        attempts.append(1)
        raise httpx.ConnectError("connection refused")

    client = client_with_pretend_server(handler, tmp_settings)

    with pytest.raises(LlmUnavailable):
        client.chat([])

    assert len(attempts) == 1


# --- Checking whether the model is ready -----------------------------------------


def test_health_reports_a_running_model(tmp_settings, restore_httpx):
    def handler(request):
        return httpx.Response(
            200, json={"data": [{"id": "openai/gpt-oss-120b"}]}
        )

    client = client_with_pretend_server(handler, tmp_settings)
    health = client.health()

    assert health.reachable is True
    assert health.model_present is True


def test_health_says_when_the_model_is_not_running(tmp_settings, restore_httpx):
    """Being unreachable is a normal answer to this question, not an error."""

    def handler(request):
        raise httpx.ConnectError("nothing listening")

    client = client_with_pretend_server(handler, tmp_settings)
    health = client.health()

    assert health.reachable is False
    assert health.model_present is False


def test_health_says_when_the_model_is_not_installed(tmp_settings, restore_httpx):
    def handler(request):
        return httpx.Response(
            200, json={"data": [{"id": "some-other-model"}]}
        )

    client = client_with_pretend_server(handler, tmp_settings)
    health = client.health()

    assert health.reachable is True
    assert health.model_present is False


def test_health_reports_missing_api_key(tmp_settings, restore_httpx):
    """Without an API key, health should report unreachable."""

    from app.config import Settings

    settings = Settings(
        model="openai/gpt-oss-120b",
        groq_api_key="",
        groq_base_url="https://api.groq.com/openai/v1",
        host="127.0.0.1",
        port=8000,
        data_dir=tmp_settings.data_dir,
        skills_dir=tmp_settings.skills_dir,
        policy_dir=tmp_settings.policy_dir,
        vulnerabilities_dir=tmp_settings.vulnerabilities_dir,
        templates_dir=tmp_settings.templates_dir,
        static_dir=tmp_settings.static_dir,
        history_turns=10,
        unused_grant_window=5,
        response_excerpt_bytes=4096,
        tasks_file=tmp_settings.tasks_file,
        installed_file=tmp_settings.installed_file,
        findings_file=tmp_settings.findings_file,
        activity_file=tmp_settings.activity_file,
        markers_dir=tmp_settings.markers_dir,
        collector_dir=tmp_settings.collector_dir,
        dashboard_file=tmp_settings.dashboard_file,
        hub_dir=tmp_settings.hub_dir,
        registry_dir=tmp_settings.registry_dir,
    )

    from app.config import set_settings

    set_settings(settings)

    def handler(request):
        return httpx.Response(200, json={"data": []})

    client = client_with_pretend_server(handler, tmp_settings)
    health = client.health()

    assert health.reachable is False
    assert health.model_present is False
