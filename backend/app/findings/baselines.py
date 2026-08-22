"""
Loading the yardstick: how much power each kind of skill reasonably needs.

This answers a different question from "did the skill tell the truth?". A skill can
be completely honest about wanting sweeping access and still be over-powered for the
job it does. That is why this check reads a policy file rather than reading what the
skill did - the two checks take different inputs and can never collapse into one
another.

Specification references: feature spec section 3.6, TDD section 4.5, decisions D-9
and S-7.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class Baseline(BaseModel):
    """
    The yardstick for one category of skill.

    allowed   - the capabilities a skill of this kind may reasonably ask for.
    max_scope - how far each of those may reasonably reach. A capability that is not
                mentioned here may reach anywhere, so leaving one out is a decision,
                not an oversight.
    """

    allowed: list[str] = Field(default_factory=list)
    max_scope: dict[str, list[str]] = Field(default_factory=dict)

    def limit_for(self, capability_id: str) -> list[str]:
        """
        The widest reach allowed for one capability in this category.

        In: the capability name. Out: the limit patterns, defaulting to "anywhere"
        when the policy does not narrow it.
        """
        return self.max_scope.get(capability_id, ["*"])


def load_baselines(path: Path) -> dict[str, Baseline]:
    """
    Load the yardstick file from disk.

    In: the path to capability_baselines.json.
    Out: a lookup from category name to its Baseline.

    A problem here raises and stops the app on purpose. Without this file the
    over-powered check would silently pass everything, which looks identical to a
    clean result - the most dangerous kind of failure for a security tool.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    categories = raw.get("categories", {})
    return {name: Baseline(**value) for name, value in categories.items()}
