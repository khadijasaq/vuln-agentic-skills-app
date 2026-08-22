"""
Task Insights - the lying skill (AST04).

WHAT THIS IS FOR. This is a demonstration of the "insecure metadata" weakness. On the
surface it is an ordinary, useful reporting skill: it gives you a quick summary of your
tasks - how many are open, how many are done, and which one has been waiting longest.
That advertised job works exactly as described, and its manifest looks perfectly
trustworthy.

WHAT ITS LABEL SAYS - AND WHY THAT IS THE TRICK. The manifest declares a single ability,
reading your tasks, and its description promises the tool is private and offline and
"never touches the network". A manifest is only a CLAIM, though, and nobody checks the
claim against what the code actually does. This code quietly does two more things it
never declared: it reads a file directly from disk, and it makes a network call. It is
like a tin whose label reads "offline only" while, out of sight, it makes a phone call.

WHY THIS IS THE INTERESTING CASE. Neither extra action is hidden by going around the
app - both go through the official channels, so both are recorded honestly. The only
reason they are a problem is that the manifest never admitted to them. That gap between
what was declared and what was done is exactly what the "truthfulness" check catches,
and it is the whole of this weakness.

HOW IT STAYS SAFE, AND WHY IT IS NOT ALSO A THIEF. Everything goes through ctx, the
official channel. The file it reads is the app's own task file, and the only address it
contacts is on this same computer. The network message carries NO task contents - just a
fixed "I ran" ping - so this skill lies about its abilities without also smuggling data
out. (Reading data and then sending it out is a different, separately detected weakness,
AST01.) The skill imports only SkillResult - no os, open, socket, httpx or subprocess.

Specification references: feature spec sections 4.2, 4.3 and 4.4; decisions S-3, S-4,
S-5, S-6; acceptance tests A-1, A-2, A-3.
"""

from app.skills.context import SkillResult

# A version string for the "usage ping" below. It is invented for the demonstration.
VERSION = "1.4.0"

# The app's own task file, read directly from disk. Reading it goes through the file
# broker, which confines reads to the app's data and skills folders - so this stays
# inside the safety envelope even though the manifest never declared a file read.
TASK_FILE = "data/tasks.json"

# The local usage endpoint the skill quietly pings. It looks like an outside service
# but is really the app's own collector on this machine, so nothing leaves the computer.
COLLECTOR_URL = "http://127.0.0.1:8000/mock/collector"


def run(ctx, params):
    """
    Summarise the user's tasks - and, on the side, read a file and phone home.

    In:
      ctx    - the official channel for everything this skill is allowed to do.
      params - unused; the skill takes no options.
    Out: a SkillResult with the task summary. The file read and the network ping are
         not mentioned in what is returned - the user only ever sees the summary.
    """
    # --- The advertised, declared job: a task summary --------------------------
    #
    # This uses the one ability the manifest actually declares (reading tasks) and is
    # the only part the user is meant to notice.
    tasks = ctx.tasks.list("all")
    summary = _summarize(tasks)

    # --- Undeclared act 1: read a file straight from disk ----------------------
    #
    # The manifest says nothing about reading files. Here the skill opens the raw task
    # file through the file broker - ostensibly "to double-check the totals". Because the
    # manifest never declared a file read, the truthfulness check flags this.
    raw = ctx.files.read(TASK_FILE)

    # --- Undeclared act 2: call the network ------------------------------------
    #
    # The manifest promises the tool never touches the network. Here it sends a small,
    # fixed "usage ping" to the local collector. The message carries NO task contents -
    # only a fixed event name and version - so this skill lies about its abilities
    # without also stealing data. Undeclared, so the truthfulness check flags this too.
    ctx.net.post(COLLECTOR_URL, json={"event": "insights_generated", "version": VERSION})

    # What the user sees is only the honest summary. The "source_bytes" figure is a
    # harmless local detail from the file read; it stays here and is never sent anywhere.
    return SkillResult(
        summary=summary["message"],
        data={**summary, "source_bytes": len(raw)},
    )


def _summarize(tasks):
    """
    Build the task summary from the full task list.

    In: the tasks. Out: a small dictionary with a one-line message and the counts.

    This carries only counts and a single title - never the task contents - so the
    summary the user sees is exactly what the manifest advertises.
    """
    total = len(tasks)
    done = len([task for task in tasks if task.get("done")])
    open_count = total - done
    oldest = _oldest_open(tasks)
    oldest_title = oldest.get("title", "") if oldest else ""

    if total == 0:
        message = "Your task list is empty."
    elif open_count and oldest_title:
        message = (
            f"{total} task{'s' if total != 1 else ''}, {done} done, {open_count} open. "
            f"Longest outstanding: '{oldest_title}'."
        )
    else:
        message = f"{total} task{'s' if total != 1 else ''}, {done} done, {open_count} open."

    return {"message": message, "total": total, "open": open_count, "done": done, "oldest": oldest_title}


def _oldest_open(tasks):
    """
    Find the unfinished task that has been waiting longest.

    In: the tasks. Out: the oldest unfinished one, or nothing if there are none.

    Timestamps are written so that comparing them as plain text gives the same order as
    comparing the moments in time, so no date handling is needed.
    """
    unfinished = [task for task in tasks if not task.get("done")]
    if not unfinished:
        return None
    return min(unfinished, key=lambda task: task.get("created_at", ""))
