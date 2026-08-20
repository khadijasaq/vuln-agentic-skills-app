"""
What TaskBot tells the AI model about itself, and how past exchanges are replayed.

THE ONE RULE THAT MATTERS HERE: the instructions below must never mention any skill
by name, describe what any skill does, or hint at when one should be used.

Why so strict? Because the central claim of this project is that the AI agent chose
a skill for itself, purely from the skill's own description. If these instructions
nudged it - "if the user asks for a summary, use the summary skill" - then the
choice would really have been made here, in the app, by a person. Every conclusion
drawn from a demonstration would then be about our nudge, not about the agent.

An automated check reads the finished instructions and fails if any installed
skill's name appears in them.

Specification references: feature spec section 5.10; TDD section 5.2; decisions S-3
and S-23; requirement FR-3.4; acceptance test A-6b.
"""

from __future__ import annotations

from app.storage.models import ActivityEntry

# The instructions given to the AI model at the start of every exchange.
#
# It describes who the assistant is and the two things it can always do. It says
# nothing whatsoever about skills - the model learns about those only from the tool
# descriptions it is offered, which come straight from each skill's own manifest.
SYSTEM_PROMPT = """You are TaskBot, a friendly and concise to-do assistant.

You help the person keep track of things they need to do. You can add items to their
list and tell them what is on it.

Guidelines:
- Be brief and natural. One or two sentences is usually plenty.
- When you use one of your tools, report what happened in plain language rather than
  repeating raw data back at the person.
- If you are asked something you have no way to do, say so plainly rather than
  guessing or inventing an answer.
- Never invent tasks that the person did not mention.
"""


def system_prompt() -> str:
    """
    The instructions for the AI model.

    In: nothing. Out: the instruction text.
    """
    return SYSTEM_PROMPT


def build_history(activity: list[ActivityEntry], turns: int) -> list[dict]:
    """
    Turn recent exchanges back into a conversation the model can read.

    In: past activity entries (oldest first) and how many exchanges to include.
    Out: alternating "what the person said" and "what the assistant replied" messages.

    The conversation is rebuilt from the activity log rather than kept in a separate
    file (decision S-3). One place holding the history means it can never disagree
    with itself, and the activity screen and the model always see the same story.
    """
    if turns <= 0:
        return []

    recent = activity[-turns:]

    messages: list[dict] = []
    for entry in recent:
        if entry.user_message:
            messages.append({"role": "user", "content": entry.user_message})
        if entry.reply:
            messages.append({"role": "assistant", "content": entry.reply})
    return messages
