"""
Focus Picker - the over-privileged skill (AST03).

WHAT THIS IS FOR. This is a demonstration of the "over-privileged skill" weakness. On the
surface it is a small, genuinely useful helper: you ask what to work on next, and it
looks at your list and names one thing, with a sentence saying why. That advertised job
works exactly as described.

WHAT MAKES IT THE INTERESTING CASE. Unlike the lying skill (AST04), this one tells the
absolute truth. Its manifest lists every single thing it can do, in plain words, and its
code never does anything the manifest did not admit to. Nothing is hidden and nothing is
misrepresented. It is also not a thief (AST01): it never sends anything anywhere, so
there is nothing to steal your data with.

The problem is the SIZE of what it was given. Naming the next thing on a to-do list needs
one ability: reading the list. This skill was handed four - reading your tasks, reading
files from the app's data folder, changing your tasks, and contacting the network. It is
like a house-sitter given the keys to every room, the safe and the car, when all they were
asked to do is water one plant. Nobody lied to anyone; the key ring is simply far too big.

THE TWO HALVES OF THE WEAKNESS, BOTH SHOWN HERE:

  USED EXCESS      It really does reach beyond its remit. To "learn which kinds of task
                   you actually finish" it reads the app's activity file - which holds
                   every message you have ever sent the assistant and every reply. A
                   task-picker has no business reading your conversation history. It is
                   declared, it is permitted, and it is wildly out of proportion.

  DORMANT EXCESS   It never changes a task and never touches the network, even though it
                   holds permission for both. That power just sits there. It is not
                   harmless: reading your tasks plus sending things out is exactly the
                   pair the thieving skill (AST01) combines. Focus Picker holds the whole
                   recipe and simply never cooks it - which is what "excess privilege is
                   damage waiting for a bug" actually means.

HOW IT STAYS SAFE. Everything goes through ctx, the official channel. The only file it
reads is one the app itself wrote, inside the app's own data folder. It writes nothing,
deletes nothing and sends nothing. The skill imports only what it needs from the app - no
os, open, socket, httpx or subprocess.

DO NOT "TIDY" THIS FILE. Two things here look like they could be improved and must not
be. Declaring less would turn this into a different weakness (a lie, AST04). Making use
of the unused permissions - or deleting them - would destroy the dormant half of the
demonstration. Both are deliberate.

Specification references: feature spec sections 4.2, 4.3 and 4.4; decisions S-2, S-5,
S-6, S-7, S-8; acceptance tests A-2, A-9, A-11.
"""

from app.skills.context import CapabilityRefused, SkillResult

# The app's own record of past conversations. Reading it is the skill's reach beyond its
# remit: perfectly declared, perfectly permitted, and far more than picking a task needs.
HISTORY_FILE = "data/activity.json"

# How many characters of that history to look at. A small cap so the skill stays quick;
# nothing here is sent anywhere - it never leaves this function.
HISTORY_SAMPLE = 4000


def run(ctx, params):
    """
    Suggest the one task worth starting now.

    In:
      ctx    - the official channel for everything this skill is allowed to do.
      params - may carry "horizon": "today" or "week". Optional; ignored if missing.
    Out: a SkillResult naming the suggested task and saying why.

    The order matters for the demonstration: the honest, necessary work happens first,
    and the over-reach happens after it, so the activity screen shows a skill doing its
    job and then quietly reaching further.
    """
    horizon = str(params.get("horizon") or "week")

    # --- The advertised job: read the list and pick one --------------------------
    #
    # This is the ONLY ability the job actually requires. Everything below this point is
    # power the skill was given but does not need.
    tasks = ctx.tasks.list("all")
    choice = _pick(tasks, horizon)

    # --- The reach beyond its remit: read the assistant's history ----------------
    #
    # Declared honestly in the manifest, permitted by the app, and hopelessly out of
    # proportion to naming a to-do item: this file holds every message the user has ever
    # sent. The cover story is "learning which kinds of task you finish", and the skill
    # really does count the entries - the point is that it should never have been able to
    # look at all.
    history_entries = _count_history(ctx)

    # --- The power it holds and never uses ---------------------------------------
    #
    # There is deliberately NO ctx.tasks.add/update/delete and NO ctx.net call anywhere in
    # this file, even though the manifest grants both. That silence is the dormant half of
    # the weakness, and removing the permissions would delete it.

    return SkillResult(
        summary=choice["message"],
        data={
            "suggested": choice["title"],
            "reason": choice["reason"],
            "open_tasks": choice["open_tasks"],
            "horizon": horizon,
            # A harmless local count from the history read. It stays here and is never
            # sent anywhere - this skill has no way to send anything.
            "history_entries_considered": history_entries,
        },
    )


def _count_history(ctx):
    """
    Read the app's conversation history and count how many exchanges it holds.

    In: the official channel. Out: how many past exchanges were found (0 if none).

    A brand new lab has no history file yet, because the app writes it only after the
    first exchange finishes. That is not a failure of the skill's real job, so a refusal
    is caught here and treated as "no history yet". The over-sized permission is a fact
    about the manifest either way - whether the read succeeds changes nothing about it.
    """
    try:
        raw = ctx.files.read(HISTORY_FILE)
    except CapabilityRefused:
        return 0

    # A rough count is all the cover story needs: each stored exchange carries one "id"
    # field, so counting those is enough without unpacking the whole file.
    return raw[:HISTORY_SAMPLE].count('"id"')


def _pick(tasks, horizon):
    """
    Choose the one task worth starting now.

    In: every task, and how far ahead to look. Out: a small dictionary with the sentence
    to show, the chosen title, the reason, and how many tasks are still open.

    The rule is deliberately simple and explainable: the unfinished task that has been
    waiting longest wins, because a thing that has sat untouched the longest is the thing
    most likely to keep sitting there. Timestamps are written so that comparing them as
    plain text gives the same order as comparing the moments in time.
    """
    unfinished = [task for task in tasks if not task.get("done")]

    if not unfinished:
        return {
            "message": "Nothing is waiting - every task on your list is done.",
            "title": "",
            "reason": "no open tasks",
            "open_tasks": 0,
        }

    oldest = min(unfinished, key=lambda task: task.get("created_at", ""))
    title = oldest.get("title", "an untitled task")
    span = "today" if horizon == "today" else "this week"

    return {
        "message": (
            f"Start with '{title}'. It has been waiting longer than anything else "
            f"on your list, and you have {len(unfinished)} open "
            f"task{'s' if len(unfinished) != 1 else ''} {span}."
        ),
        "title": title,
        "reason": "waiting longest",
        "open_tasks": len(unfinished),
    }
