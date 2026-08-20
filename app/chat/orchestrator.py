"""
Running one exchange with the assistant, from the person's message to the reply.

This is where the central claim of the whole project lives: the AI model, not this
code, decides whether a skill should run.

HOW THAT IS GUARANTEED - four structural facts a reviewer can check in a minute:

  1. There is exactly one line in this file that runs a skill.
  2. The name it passes comes from one place only: the model's answer.
  3. The person's message is put into the conversation and read nowhere else. There
     is no keyword matching, no pattern matching, no "if the user said X" anywhere.
  4. An automated test proves it: with a stand-in model that only ever replies with
     plain sentences, no skill runs for ANY message - including messages that quote
     a skill's own description word for word.

If any of those broke, a demonstration showing that an agent was tricked into
running a malicious skill would prove nothing, because the app might have started
that skill itself.

WHAT AN EXCHANGE LOOKS LIKE:

  person's message
        |
        v
  gather the tools: the two built-in abilities, plus every installed skill
        |
        v
  ask the model  -->  no tool requested? its sentence is the reply. Done.
        |
        v  tool requested
  built-in ability?  -->  do it directly, nothing is watched, nothing recorded
        |
        v  a skill
  run it through the single entrance, watched and recorded
        |
        v
  compare what it did against what it declared -> any findings get saved
        |
        v
  ask the model again, so it can put the result into natural words
        |
        v
  write the whole story into the activity log

Specification references: feature spec sections 5.11 and 8; TDD section 5; decisions
S-31, D-13; requirement FR-3.4; invariant I-1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.chat import builtins, prompts
from app.config import get_settings
from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.findings.markers import write_marker
from app.llm.ollama_client import ChatResponse, OllamaClient, ToolCall
from app.skills.host import get_host
from app.skills.manifest import load_vocabulary
from app.skills.registry import get_registry
from app.storage import store
from app.storage.models import ActivityEntry, Finding, SkillInvocationRecord

logger = logging.getLogger("taskbot.chat")


@dataclass(frozen=True)
class TurnResult:
    """Everything that came out of one exchange."""

    activity: ActivityEntry
    findings_raised: list[Finding] = field(default_factory=list)
    tool_call_made: bool = False
    model: str = ""


def build_tool_list() -> list[dict]:
    """
    Gather everything the AI model is allowed to ask for.

    In: nothing. Out: the tool descriptions.

    Each installed skill becomes exactly one tool, described using ONLY what that
    skill says about itself. Nothing here reorders them by relevance, filters them,
    or adds hints - if a skill's own description is unconvincing, the model will not
    pick it, and the fix is a better description, never a nudge from this code.

    The two built-in abilities are always included, whether or not any skills are
    installed. That is what lets a brand new lab still work as an ordinary assistant.
    """
    tools = list(builtins.build_builtin_tool_schemas())

    for record in get_registry().installed():
        manifest = record.manifest
        if manifest is None:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": manifest.id,
                    # Straight from the skill's own description. This is exactly how
                    # a dishonest skill would talk its way into being chosen - and
                    # that is the point of the exercise.
                    "description": f"{manifest.description}\n\nUse when: {manifest.invocation.when_to_use}",
                    "parameters": manifest.invocation.parameters,
                },
            }
        )

    return tools


def _build_engine() -> FindingsEngine:
    """
    Build the part that decides whether a skill misbehaved.

    In: nothing. Out: a FindingsEngine loaded with the shared policy files.
    """
    settings = get_settings()
    vocabulary = load_vocabulary(settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


class ChatOrchestrator:
    """Runs one exchange from beginning to end."""

    def __init__(self, client: OllamaClient | None = None) -> None:
        # The client can be swapped for a stand-in during testing, which is how the
        # "no skill runs unless the model asks" proof is done without a real model.
        self._client = client or OllamaClient()

    def run_turn(self, user_message: str) -> TurnResult:
        """
        Handle one message from the person.

        In: what they said. Out: a TurnResult describing everything that happened.

        Raises OllamaUnavailable if the AI model cannot be reached. That is
        deliberate: no canned reply, no guessing (decision D-13).
        """
        settings = get_settings()
        tools = build_tool_list()

        history = prompts.build_history(store.load_activity(), settings.history_turns)
        messages = (
            [{"role": "system", "content": prompts.system_prompt()}]
            + history
            + [{"role": "user", "content": user_message}]
        )

        # --- ask the model what to do ---
        first_answer: ChatResponse = self._client.chat(messages, tools)

        if not first_answer.tool_calls:
            # It just wants to reply. Nothing runs, nothing is watched.
            return self._finish_turn(
                user_message=user_message,
                reply=first_answer.content,
                model=first_answer.model,
                invocation=None,
                observations=[],
                findings=[],
                tool_call_made=False,
                extra_calls_ignored=0,
            )

        # Only the first request is acted on. A model asking for several skills at
        # once would tangle two skills' records together inside one exchange, which
        # helps nobody (decision S-31).
        chosen: ToolCall = first_answer.tool_calls[0]
        ignored = len(first_answer.tool_calls) - 1
        if ignored:
            logger.info("Ignored %d extra tool request(s) in one exchange.", ignored)

        if builtins.is_builtin(chosen.name):
            return self._handle_builtin(
                user_message, chosen, messages, first_answer, ignored
            )

        return self._handle_skill(user_message, chosen, messages, first_answer, ignored)

    # --- the two kinds of tool ----------------------------------------------------

    def _handle_builtin(
        self,
        user_message: str,
        chosen: ToolCall,
        messages: list[dict],
        first_answer: ChatResponse,
        ignored: int,
    ) -> TurnResult:
        """
        Carry out one of the app's own built-in abilities.

        In: the message, the request, the conversation so far, and the model's answer.
        Out: a TurnResult.

        Nothing is watched and nothing is recorded here. This is the app doing its own
        advertised job, not a skill being supervised - see app/chat/builtins.py.
        """
        try:
            outcome = builtins.run_builtin(chosen.name, chosen.arguments)
            tool_text = outcome.summary
        except Exception as failure:
            logger.info("Built-in ability %s failed: %s", chosen.name, failure)
            tool_text = f"That did not work: {failure}"

        reply, model_name = self._ask_model_to_phrase_it(
            messages, first_answer, chosen, tool_text
        )

        return self._finish_turn(
            user_message=user_message,
            reply=reply,
            model=model_name,
            invocation=None,
            observations=[],
            findings=[],
            tool_call_made=True,
            extra_calls_ignored=ignored,
        )

    def _handle_skill(
        self,
        user_message: str,
        chosen: ToolCall,
        messages: list[dict],
        first_answer: ChatResponse,
        ignored: int,
    ) -> TurnResult:
        """
        Run an installed skill, then check whether it behaved as it promised.

        In: the message, the model's request, the conversation, and the first answer.
        Out: a TurnResult.
        """
        registry = get_registry()
        installed_names = {record.skill_id for record in registry.installed()}

        if chosen.name not in installed_names:
            # The model asked for something that is not there. Nothing runs.
            logger.info("The model asked for %r, which is not installed.", chosen.name)
            return self._finish_turn(
                user_message=user_message,
                reply=first_answer.content or "I cannot do that.",
                model=first_answer.model,
                invocation=None,
                observations=[],
                findings=[],
                tool_call_made=False,
                extra_calls_ignored=ignored,
            )

        # ==========================================================================
        # THE ONLY LINE IN THE ENTIRE APPLICATION THAT RUNS A SKILL.
        #
        # The name comes from chosen.name, which came from the model's answer. It is
        # never derived from what the person typed. This single fact is what makes
        # "the agent chose to do this" a checkable claim rather than a hope.
        # ==========================================================================
        result = get_host().invoke(chosen.name, chosen.arguments)

        record = registry.get(chosen.name)
        findings: list[Finding] = []

        if record.manifest is not None:
            engine = _build_engine()
            findings = engine.evaluate_invocation(
                record.manifest,
                result.observations,
                invocation_id=result.invocation_id,
                model=first_answer.model,
            )
            findings = self._save_findings(findings, result.observations)

        tool_text = result.summary if result.outcome == "ok" else f"That failed: {result.error}"
        reply, model_name = self._ask_model_to_phrase_it(
            messages, first_answer, chosen, tool_text
        )

        invocation = SkillInvocationRecord(
            skill_id=chosen.name,
            skill_version=record.manifest.version if record.manifest else "unknown",
            invocation_id=result.invocation_id,
            params=dict(chosen.arguments),
            outcome=result.outcome,
            error=result.error,
            duration_ms=result.duration_ms,
        )

        return self._finish_turn(
            user_message=user_message,
            reply=reply,
            model=model_name,
            invocation=invocation,
            observations=[entry.model_dump() for entry in result.observations],
            findings=findings,
            tool_call_made=True,
            extra_calls_ignored=ignored,
        )

    # --- shared steps -------------------------------------------------------------

    def _ask_model_to_phrase_it(
        self,
        messages: list[dict],
        first_answer: ChatResponse,
        chosen: ToolCall,
        tool_text: str,
    ) -> tuple[str, str]:
        """
        Ask the model to turn a tool's result into a natural sentence.

        In: the conversation, the model's first answer, what it asked for, and what
        came back.
        Out: the reply to show, and which model produced it.

        This second round is what makes TaskBot read like a product rather than a
        command line. If it fails we fall back to the raw result - a slightly blunt
        answer is far better than losing the exchange entirely.
        """
        follow_up = messages + [
            {"role": "assistant", "content": first_answer.content or ""},
            {"role": "tool", "content": tool_text, "name": chosen.name},
        ]

        try:
            second_answer = self._client.chat(follow_up, None)
            reply = second_answer.content or tool_text
            return reply, second_answer.model or first_answer.model
        except Exception as failure:
            logger.info("Could not phrase the result naturally: %s", failure)
            return tool_text, first_answer.model

    def _save_findings(self, findings: list[Finding], observations: list) -> list[Finding]:
        """
        Save any problems found, and leave evidence on disk for new ones.

        In: the problems found and everything the skill did. Out: the saved problems.

        A problem seen for the first time gets a piece of evidence written to disk. A
        problem seen again simply increases a counter - otherwise a skill misbehaving
        in a loop would bury the evidence folder in near-identical files.
        """
        saved: list[Finding] = []
        by_sequence = {entry.seq: entry for entry in observations}

        for finding in findings:
            stored, is_new = store.upsert_finding(finding)

            if is_new:
                sequence = finding.evidence.get("observation_seq")
                marker_path = write_marker(stored, by_sequence.get(sequence))
                stored.evidence["marker"] = str(marker_path)
                # Save again so the finding remembers where its evidence lives.
                store.upsert_finding(stored)

            saved.append(stored)

        return saved

    def _finish_turn(
        self,
        *,
        user_message: str,
        reply: str,
        model: str,
        invocation: SkillInvocationRecord | None,
        observations: list,
        findings: list[Finding],
        tool_call_made: bool,
        extra_calls_ignored: int,
    ) -> TurnResult:
        """
        Write the exchange into the activity log and hand back the result.

        In: everything that happened. Out: a TurnResult.
        """
        entry = ActivityEntry(
            id=store.new_id("act"),
            ts=store.now_iso(),
            user_message=user_message,
            reply=reply,
            model=model,
            skill_invoked=invocation,
            observations=observations,
            findings_raised=[finding.id for finding in findings],
            vulnerability_fired=bool(findings),
            extra_tool_calls_ignored=extra_calls_ignored,
        )
        store.append_activity(entry)

        return TurnResult(
            activity=entry,
            findings_raised=findings,
            tool_call_made=tool_call_made,
            model=model,
        )
