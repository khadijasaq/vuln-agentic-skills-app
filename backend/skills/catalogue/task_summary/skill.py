"""
Task Summary - the honest skill.

WHAT THIS IS FOR. Every other skill in this project is deliberately flawed in some
way, to demonstrate a particular security problem. This one is the opposite: it is
completely, boringly honest. It declares exactly one ability - reading your tasks -
and that is exactly and only what it does.

Why does an app about vulnerabilities need an honest skill? Because "the scanner
found three problems" means nothing unless something proves the scanner can also
stay quiet. This skill is the control: if the app ever reports a problem with THIS
one, the app itself is wrong, and every other result it produces becomes suspect.

It is also genuinely useful, on purpose. A believable product needs at least one
skill that earns its place, rather than an obvious test fixture.

WHAT IT DELIBERATELY DOES NOT DO. It never reads a file, never contacts the network,
never reads a setting, and never starts another program. It does not import os, open,
socket, httpx or subprocess. Everything it needs comes through ctx, the official
channel.

Specification references: feature spec section 10; requirement FR-4.6; goal G5;
success criterion SC-3.
"""

from app.skills.context import SkillResult


def run(ctx, params):
    """
    Summarise the user's to-do list.

    In:
      ctx    - the official channel for everything this skill is allowed to do.
      params - may contain "scope": "all", "open" or "done".
    Out: a SkillResult with a readable sentence and the underlying numbers.

    This asks for the task list exactly once, through the official channel, and does
    nothing else at all.
    """
    scope = params.get("scope", "all")

    # The one and only thing this skill does. It matches, precisely, the single
    # ability declared in manifest.json.
    tasks = ctx.tasks.list(scope)

    total = len(tasks)
    done = len([task for task in tasks if task.get("done")])
    still_open = total - done

    # Guard against dividing by zero when the list is empty.
    completion_rate = round((done / total) * 100, 1) if total else 0.0

    oldest_open = _find_oldest_unfinished(tasks)

    return SkillResult(
        summary=_describe(total, done, still_open, completion_rate, oldest_open, scope),
        data={
            "scope": scope,
            "total": total,
            "open": still_open,
            "done": done,
            "completion_rate": completion_rate,
            "oldest_open": oldest_open,
        },
    )


def _find_oldest_unfinished(tasks):
    """
    Find the unfinished task that has been waiting longest.

    In: the list of tasks. Out: that task, or nothing if there are none.

    Because timestamps are written in a format where comparing them as ordinary text
    gives the same answer as comparing the moments in time, this needs no date
    handling at all.
    """
    unfinished = [task for task in tasks if not task.get("done")]
    if not unfinished:
        return None
    return min(unfinished, key=lambda task: task.get("created_at", ""))


def _describe(total, done, still_open, completion_rate, oldest_open, scope):
    """
    Turn the numbers into one readable sentence.

    In: the counts, the rate, the longest-waiting task, and which scope was asked for.
    Out: a sentence for the assistant to work from.
    """
    if total == 0:
        return f"There are no {scope} tasks." if scope != "all" else "The task list is empty."

    sentence = f"{total} task{'s' if total != 1 else ''}, {done} done ({completion_rate}%)."

    if still_open and oldest_open:
        title = oldest_open.get("title", "an untitled task")
        created = str(oldest_open.get("created_at", ""))[:10]
        sentence += f" Longest outstanding: '{title}', added {created}."

    return sentence
