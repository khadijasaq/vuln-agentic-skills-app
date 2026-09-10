"""
Checks for one complete exchange with the assistant (app/chat/orchestrator.py).

This covers the turn protocol, the instructions given to the model, what happens
when the model is unavailable, and the safe baseline: a brand new lab with nothing
installed still works as an ordinary to-do assistant.

Covers: feature spec sections 5.10, 5.11, 8.2 and 8.4; decisions S-3, S-23, S-31,
D-13; acceptance tests A-2, A-6b, A-7 (amended wording) and A-12 (in part).
"""

from __future__ import annotations

import pytest

from app.chat import prompts
from app.chat.orchestrator import ChatOrchestrator, build_tool_list
from app.llm.groq_client import ChatResponse, LlmUnavailable, ToolCall
from app.skills import host as host_module
from app.skills import registry as registry_module
from app.storage import seed, store
from app.storage.models import ActivityEntry


class ScriptedModel:
    """
    A stand-in model that gives whatever answers it is handed, in order.

    Using a scripted stand-in rather than a real model keeps these checks fast and
    identical every time.
    """

    def __init__(self, *answers: ChatResponse) -> None:
        self.answers = list(answers)
        self.conversations: list[list[dict]] = []
        self.tools_offered: list[list[dict] | None] = []

    def chat(self, messages, tools=None):
        self.conversations.append(messages)
        self.tools_offered.append(tools)
        if self.answers:
            return self.answers.pop(0)
        return ChatResponse(content="Nothing more to say.", tool_calls=[], model="stub")


class BrokenModel:
    """A stand-in for a model that is not running at all."""

    def chat(self, messages, tools=None):
        raise LlmUnavailable(
            "unreachable",
            "Could not reach the AI model.",
            "Check your Groq API connection.",
        )


@pytest.fixture(autouse=True)
def _clean(tmp_settings):
    registry_module.reset_registry()
    host_module.clear_module_cache()
    seed.seed_tasks_if_absent()
    yield
    registry_module.reset_registry()
    host_module.clear_module_cache()


# --- The instructions given to the model -----------------------------------------


def test_a6b_the_instructions_name_no_skill():
    """
    ACCEPTANCE TEST A-6b.

    If the instructions mentioned a skill, the choice would really have been made by
    whoever wrote them, not by the agent.
    """
    text = prompts.system_prompt().lower()

    assert "skill" not in text
    assert "task_summary" not in text


def test_the_instructions_describe_the_assistant_and_its_built_in_abilities():
    """It still has to know who it is and what it can always do."""
    text = prompts.system_prompt()

    assert "TaskBot" in text
    assert "to-do" in text.lower()


def test_past_exchanges_are_replayed_to_the_model():
    """
    DECISION S-3.

    The conversation is rebuilt from the activity log rather than kept in a second
    file, so the model and the activity screen can never disagree about what was said.
    """
    entries = [
        ActivityEntry(id="act_1", ts="t1", user_message="first question", reply="first answer"),
        ActivityEntry(id="act_2", ts="t2", user_message="second question", reply="second answer"),
    ]

    history = prompts.build_history(entries, turns=10)

    assert [message["role"] for message in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["content"] == "first question"


def test_only_the_most_recent_exchanges_are_replayed():
    """Older exchanges drop off, so the conversation does not grow without limit."""
    entries = [
        ActivityEntry(id=f"act_{i}", ts=f"t{i}", user_message=f"q{i}", reply=f"a{i}")
        for i in range(20)
    ]

    history = prompts.build_history(entries, turns=3)

    assert len(history) == 6
    assert history[0]["content"] == "q17"


# --- What the model is offered ---------------------------------------------------


def test_the_built_in_abilities_are_always_offered(tmp_settings):
    """
    Whether or not any skills are installed, the assistant can always manage tasks.
    That is what makes a brand new lab a working product rather than an empty shell.
    """
    names = [tool["function"]["name"] for tool in build_tool_list()]

    assert "add_task" in names
    assert "list_tasks" in names


def test_an_installed_skill_is_described_using_only_its_own_words(tmp_settings):
    """
    The description comes straight from the skill's own manifest. Nothing is added,
    reordered by relevance, or filtered - which is exactly how a dishonest skill
    would talk its way into being chosen.
    """
    registry = registry_module.get_registry()
    registry.discover_default()
    registry.install("task_summary")

    tools = {tool["function"]["name"]: tool["function"] for tool in build_tool_list()}

    assert "task_summary" in tools
    described = tools["task_summary"]["description"]
    assert "Summarises your task list" in described
    assert "Use when:" in described


def test_a_skill_that_is_switched_off_is_never_offered(tmp_settings):
    """The model cannot ask for something it was never told about (FR-2.6)."""
    registry_module.get_registry().discover_default()

    names = [tool["function"]["name"] for tool in build_tool_list()]

    assert "task_summary" not in names


# --- The shape of one exchange ---------------------------------------------------


def test_a_plain_reply_needs_no_second_round(tmp_settings):
    """When the model just answers, that answer is the reply and nothing runs."""
    model = ScriptedModel(ChatResponse(content="You have plenty to do.", model="stub"))
    result = ChatOrchestrator(client=model).run_turn("how are things?")

    assert result.activity.reply == "You have plenty to do."
    assert result.tool_call_made is False
    assert len(model.conversations) == 1


def test_using_a_tool_takes_two_rounds(tmp_settings):
    """
    The second round is what makes TaskBot read like a product: the person sees a
    natural sentence, not raw output from a tool.
    """
    model = ScriptedModel(
        ChatResponse(content="", tool_calls=[ToolCall("list_tasks", {"scope": "all"})], model="stub"),
        ChatResponse(content="You have eight things on your list.", model="stub"),
    )

    result = ChatOrchestrator(client=model).run_turn("what's on my list?")

    assert len(model.conversations) == 2
    assert result.activity.reply == "You have eight things on your list."


def test_the_whole_exchange_is_written_to_the_activity_log(tmp_settings):
    """The activity log is the demonstration screen, so it must hold the full story."""
    model = ScriptedModel(ChatResponse(content="Noted.", model="stub"))

    ChatOrchestrator(client=model).run_turn("remember to call mum")

    entries = store.load_activity()
    assert len(entries) == 1
    assert entries[0].user_message == "remember to call mum"
    assert entries[0].reply == "Noted."
    assert entries[0].model == "stub"


def test_only_the_first_tool_request_is_acted_on(tmp_settings):
    """
    DECISION S-31.

    A model asking for several things at once would tangle two skills' records
    together inside one exchange. We act on the first and note how many we ignored.
    """
    model = ScriptedModel(
        ChatResponse(
            content="",
            tool_calls=[
                ToolCall("list_tasks", {"scope": "all"}),
                ToolCall("add_task", {"title": "should be ignored"}),
            ],
            model="stub",
        ),
        ChatResponse(content="Here you go.", model="stub"),
    )

    result = ChatOrchestrator(client=model).run_turn("do several things")

    assert result.activity.extra_tool_calls_ignored == 1
    # The ignored request really did not happen.
    assert not any(task.title == "should be ignored" for task in store.load_tasks())


# --- ACCEPTANCE TESTS A-2 and A-7: the safe baseline -----------------------------


def test_a2_the_assistant_adds_tasks_with_nothing_installed(tmp_settings):
    """
    ACCEPTANCE TEST A-2.

    With zero skills installed, the assistant is still a complete, working to-do
    app. This is the non-vulnerable baseline everything else is measured against.
    """
    model = ScriptedModel(
        ChatResponse(
            content="",
            tool_calls=[ToolCall("add_task", {"title": "Book the dentist"})],
            model="stub",
        ),
        ChatResponse(content="Added it to your list.", model="stub"),
    )

    assert store.load_installed().installed == []

    ChatOrchestrator(client=model).run_turn("remind me to book the dentist")

    assert any(task.title == "Book the dentist" for task in store.load_tasks())


def test_a2_the_assistant_lists_tasks_with_nothing_installed(tmp_settings):
    """The other half of the baseline."""
    model = ScriptedModel(
        ChatResponse(content="", tool_calls=[ToolCall("list_tasks", {"scope": "open"})], model="stub"),
        ChatResponse(content="Five things are still open.", model="stub"),
    )

    result = ChatOrchestrator(client=model).run_turn("what's still open?")

    assert result.activity.reply == "Five things are still open."


def test_a7_nothing_is_watched_or_reported_on_a_fresh_lab(tmp_settings):
    """
    ACCEPTANCE TEST A-7 (amended wording, build plan O-1).

    With nothing installed, the tools offered are exactly the two built-in abilities
    and no skill. No skill runs, nothing is recorded, and no problem can be reported.

    The built-in abilities are the app doing its own advertised job - not a skill
    under supervision - so they produce no observations by design.
    """
    names = [tool["function"]["name"] for tool in build_tool_list()]
    assert sorted(names) == ["add_task", "list_tasks"]

    model = ScriptedModel(
        ChatResponse(content="", tool_calls=[ToolCall("add_task", {"title": "Something"})], model="stub"),
        ChatResponse(content="Done.", model="stub"),
    )

    result = ChatOrchestrator(client=model).run_turn("add something")

    assert result.activity.skill_invoked is None
    assert result.activity.observations == []
    assert result.activity.vulnerability_fired is False
    assert store.load_findings() == []


# --- ACCEPTANCE TEST A-12: when the model is not running -------------------------


def test_a12_an_unavailable_model_stops_the_exchange_loudly(tmp_settings):
    """
    ACCEPTANCE TEST A-12 and DECISION D-13.

    No canned reply, no guessing from the person's words. A fallback would be exactly
    the "decide in code" this project forbids, and would let a demonstration appear
    to work with no model running at all.
    """
    with pytest.raises(LlmUnavailable) as failure:
        ChatOrchestrator(client=BrokenModel()).run_turn("hello")

    assert "Groq" in failure.value.remedy or "API" in failure.value.remedy


def test_a12_a_failed_exchange_is_not_written_to_the_log(tmp_settings):
    """There was no exchange, so there is nothing to record."""
    with pytest.raises(LlmUnavailable):
        ChatOrchestrator(client=BrokenModel()).run_turn("hello")

    assert store.load_activity() == []


def test_there_is_no_fallback_reply_anywhere_in_the_code():
    """
    Checked by reading the source. A prepared answer would quietly turn a broken
    setup into an apparently working demonstration.

    Only the lines that actually run are searched. The explanations in this codebase
    talk openly about why there is no such fallback, and a plain text search would be
    fooled by its own documentation.
    """
    from pathlib import Path

    from tests.source_tools import executable_source

    code = executable_source(
        Path(__file__).resolve().parents[1] / "backend" / "app" / "chat" / "orchestrator.py"
    )

    for phrase in ["fallback_reply", "canned", "default_response", "FALLBACK"]:
        assert phrase not in code
