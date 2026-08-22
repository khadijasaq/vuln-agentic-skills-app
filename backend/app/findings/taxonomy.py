"""
The catalogue of security problems this app can report.

This is a plain table, not clever code. Adding a new kind of problem later means
adding a row here and a check that produces it - never rewriting the engine.

THE THREE QUESTIONS. Every problem type belongs to exactly one of three questions,
and they are deliberately different questions asked of different information:

  TRUTHFULNESS   "Did the skill do what it said it would?"
                 Looks at: what it declared, and what it actually did.

  PROPORTIONALITY "Did the skill need that much power in the first place?"
                 Looks at: what it asked for, and what its kind of skill should need.
                 A skill can be completely honest and still fail this.

  CORRELATION    "Did the skill combine two harmless abilities into a harmful one?"
                 Looks at: the ORDER of what it did. Nothing else.
                 A skill can be honest AND appropriately powered and still fail this.

That third one is why the three can never collapse into each other. A skill could
declare "I read tasks" and "I send local messages", be entirely truthful, stay well
within what its category allows - and still steal your task list by doing the first
and then the second. No amount of comparing promises to behaviour would catch it.

Specification references: feature spec section 9.1; TDD sections 4.1 and 4.3;
severities fixed by TDD section 14 (Q-2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FindingType(BaseModel):
    """
    One kind of security problem.

    implemented - whether this app actually looks for it yet. Types that are planned
                  but not built are listed here anyway, so their severity and meaning
                  are settled in advance and the engine can simply skip them.
    """

    id: str
    ast_id: str
    ast_name: str
    axis: Literal["truthfulness", "proportionality", "correlation"]
    severity: Literal["critical", "high", "medium", "low", "info"]
    summary_template: str
    implemented: bool = True


# The complete catalogue. Severities are fixed by the design and are not decided
# per-skill or per-situation.
TAXONOMY: dict[str, FindingType] = {
    # --- Truthfulness: did it do what it said? ---
    "UNDECLARED_CAPABILITY": FindingType(
        id="UNDECLARED_CAPABILITY",
        ast_id="AST04",
        ast_name="Insecure Metadata",
        axis="truthfulness",
        severity="high",
        summary_template=(
            "The skill did something it never declared: {capability} on {resource}. "
            "Its description does not mention this ability at all."
        ),
    ),
    "SCOPE_VIOLATION": FindingType(
        id="SCOPE_VIOLATION",
        ast_id="AST04",
        ast_name="Insecure Metadata",
        axis="truthfulness",
        severity="high",
        summary_template=(
            "The skill declared {capability} limited to {declared_scope}, but used it "
            "on {resource}, which is outside those limits."
        ),
    ),
    "BROKER_BYPASS": FindingType(
        id="BROKER_BYPASS",
        ast_id="AST04",
        ast_name="Insecure Metadata",
        axis="truthfulness",
        severity="high",
        summary_template=(
            "The skill went around the official channel and did {capability} on "
            "{resource} directly. Going around the app is a deliberate act."
        ),
    ),
    # --- Proportionality: did it need that much? ---
    "EXCESSIVE_GRANT": FindingType(
        id="EXCESSIVE_GRANT",
        ast_id="AST03",
        ast_name="Over-Privileged Skills",
        axis="proportionality",
        severity="medium",
        summary_template=(
            "The skill holds more power than its kind of skill needs: {capability} "
            "({reason}). This may be honestly declared and still be too much."
        ),
    ),
    "UNUSED_GRANT": FindingType(
        id="UNUSED_GRANT",
        ast_id="AST03",
        ast_name="Over-Privileged Skills",
        axis="proportionality",
        severity="low",
        summary_template=(
            "The skill holds {capability} but has never used it. Power held and "
            "never exercised is damage waiting for a bug or a compromise."
        ),
    ),
    # --- Correlation: did it combine things? ---
    "COVERT_DATA_FLOW": FindingType(
        id="COVERT_DATA_FLOW",
        ast_id="AST01",
        ast_name="Malicious Skills",
        axis="correlation",
        severity="critical",
        summary_template=(
            "The skill read the user's private information and then sent it "
            "elsewhere in the same run."
        ),
        # Built by the AST01 feature. The engine's correlation check looks for a task
        # read followed by a send of that same data in one run (see engine.py).
        implemented=True,
    ),
}


def get_type(type_id: str) -> FindingType:
    """
    Look up one problem type.

    In: its identifier. Out: the type. Raises KeyError if it is not in the catalogue.
    """
    return TAXONOMY[type_id]
