"""
The assistant's own built-in abilities: adding a to-do item and listing them.

WHY THESE ARE NOT SKILLS - this is the important idea in this file.

TaskBot gains extra abilities by installing "skills", which are separate bundles of
code that get watched closely because they might misbehave. But the plain ability to
add and list your own to-do items is not an extra - it is what the app *is*. A to-do
assistant that cannot touch your to-do list is not an assistant.

So these two abilities are built in to the app itself. Concretely that means they:

  - are never discovered as skills and never appear in the skill store;
  - cannot be installed or removed;
  - do NOT go through the capability broker, and therefore produce no observations;
  - can never cause a security finding.

That last point is not a loophole. The security exercise is about *skills* lying
about themselves or overreaching. The app performing its own advertised job is not
part of that exercise, and treating it as if it were would fill the findings list
with noise about the app reporting itself.

The safety promise still holds exactly as written: with no skills installed, no
skill can run, nothing is recorded, and no finding can be produced.

Specification references: build plan O-1 (approved), requirements FR-1.1 and FR-1.4,
non-goal NG4, acceptance tests A-2 and A-7 (amended wording).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.storage import store


# The names the AI model uses to ask for these abilities. Kept in one place so other
# parts of the app can reliably tell "is this a built-in, or a skill?".
ADD_TASK = "add_task"
LIST_TASKS = "list_tasks"

BUILTIN_TOOL_NAMES = frozenset({ADD_TASK, LIST_TASKS})


@dataclass(frozen=True)
class BuiltinResult:
    """
    What a built-in ability hands back.

    summary - a plain sentence the AI model turns into a natural reply.
    data    - the structured details, shown on the activity screen.
    """

    summary: str
    data: dict[str, Any]


def build_builtin_tool_schemas() -> list[dict]:
    """
    Describe the two built-in abilities in the format the AI model expects.

    In: nothing.
    Out: a list of two tool descriptions.

    These are always offered to the model, whether or not any skills are installed.
    That is what lets a brand new lab, with nothing installed, still work as an
    ordinary assistant.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": ADD_TASK,
                "description": (
                    "Add a new item to the user's to-do list.\n\n"
                    "Use when: the user wants to remember, add, capture or note "
                    "something they need to do."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short description of the task.",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional extra detail.",
                        },
                    },
                    "required": ["title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": LIST_TASKS,
                "description": (
                    "List the user's to-do items.\n\n"
                    "Use when: the user asks what is on their list, what is "
                    "outstanding, or what they have finished."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "enum": ["all", "open", "done"],
                            "description": "Which tasks to include.",
                        }
                    },
                    "required": [],
                },
            },
        },
    ]


def is_builtin(tool_name: str) -> bool:
    """
    Is this the name of a built-in ability rather than an installed skill?

    In: the name the AI model asked for. Out: True or False.

    The conversation code uses this to decide which path to take. Built-ins run
    directly; skills go through the watched, recorded path instead.
    """
    return tool_name in BUILTIN_TOOL_NAMES


def run_builtin(tool_name: str, params: dict[str, Any]) -> BuiltinResult:
    """
    Carry out one built-in ability.

    In: which ability, and the values the AI model supplied.
    Out: a BuiltinResult.

    Note what is deliberately absent here: no capability broker, no observation
    notebook, no findings check. This is the app doing its own job, not a skill being
    supervised.
    """
    if tool_name == ADD_TASK:
        return _run_add_task(params)
    if tool_name == LIST_TASKS:
        return _run_list_tasks(params)
    raise ValueError(f"{tool_name!r} is not a built-in ability.")


def _run_add_task(params: dict[str, Any]) -> BuiltinResult:
    """
    Add one to-do item.

    In: a dictionary that should contain "title" and may contain "notes".
    Out: a BuiltinResult describing what was added.

    A missing or blank title is reported back plainly rather than raising an error,
    so the assistant can simply ask the user for one.
    """
    title = str(params.get("title", "")).strip()
    notes = str(params.get("notes", "") or "")

    if not title:
        return BuiltinResult(
            summary="No task was added because no title was given.",
            data={"added": False, "reason": "missing_title"},
        )

    task = store.add_task(title, notes)
    return BuiltinResult(
        summary=f"Added the task {task.title!r} to the list.",
        data={"added": True, "task": task.model_dump()},
    )


def _run_list_tasks(params: dict[str, Any]) -> BuiltinResult:
    """
    List the to-do items.

    In: a dictionary that may contain "scope" ("all", "open" or "done").
    Out: a BuiltinResult holding the matching tasks and a short summary sentence.
    """
    scope = str(params.get("scope", "all") or "all")
    selected = store.filter_tasks(store.load_tasks(), scope)

    if not selected:
        summary = f"There are no {scope} tasks." if scope != "all" else "The list is empty."
    else:
        titles = ", ".join(task.title for task in selected[:10])
        summary = f"{len(selected)} {scope} task(s): {titles}"
        if len(selected) > 10:
            summary += ", and more."

    return BuiltinResult(
        summary=summary,
        data={
            "scope": scope,
            "count": len(selected),
            "tasks": [task.model_dump() for task in selected],
        },
    )
