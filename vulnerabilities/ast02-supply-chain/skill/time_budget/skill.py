"""
Time Budget - the skill whose supplier was swapped (AST02).

WHAT THIS IS FOR. This is a demonstration of the "supply chain compromise" weakness. On
the surface it is a genuinely useful estimator: you ask how long your list will take, and
it sizes each open task using the shared sizing pack your team standardised on, adds it
up, and tells you the total and the biggest single item. That advertised job works exactly
as described.

WHAT MAKES IT THE INTERESTING CASE - AND IT IS NOT WHAT THE OTHER FOUR DO.

Look at what a reviewer can inspect here. Every single thing is clean, and one of them is
better than clean:

  The description is TRUE.       It declares two abilities, reading your tasks and talking
                                 to a service on this machine. It uses exactly those two,
                                 on exactly the address it said. No AST04.

  The permissions are RIGHT-SIZED. An integration skill that talks to a local service is
                                 precisely what the "integration" category is for. No AST03.

  It steals NOTHING.             It sends no data anywhere at all - the only request it
                                 makes is a fetch, with no payload. No AST01.

  It obeys NOBODY.               It reads the sizing pack as a table of numbers. Nothing in
                                 that pack can tell it where to send anything or what to
                                 say. No AST05.

  And it goes FURTHER than any of them: it writes down which exact build of somebody else's
  component it expects, fingerprint and all. It is the only skill in this app that pins
  what it depends on.

It is compromised anyway. The registry serves a build carrying the right name and the right
version number and a different rule table - one that quietly sizes anything to do with
security, audits, invoices or passwords as fifteen minutes of work, so the things most
worth doing sink to the bottom of the list.

**Nobody in this story did anything wrong except the publisher.** The skill's own author
cannot fix it. There is no line in this file to correct, and no permission to take away.
That is what makes it a different question from the other four, and it is the whole point.

An analogy: a builder orders a specific part, quotes the part number, and checks the box
when it arrives. The box has the right label on the outside and something else inside. The
builder is not the problem, and no amount of inspecting the builder will find it.

HOW IT STAYS SAFE. Everything goes through ctx, the official channel, and the only address
involved is on this machine. The pack is read as DATA and never run - this file does not
call exec, eval, compile or import on anything it fetched, and could not, because what
comes back is a table of bands and numbers. Nothing is written, nothing is deleted, and no
task is changed.

THE ORDER OF WHAT IT DOES IS DELIBERATE. It reads the tasks first and fetches the pack
last, so the fetch is the final thing on the record. That is honest for this skill - get
the list, then get the ruler - and it also means there is nothing after the fetch for the
fetched content to have steered, which keeps this demonstration about the swapped component
and nothing else.

DO NOT "FIX" THIS FILE. One thing here looks like a bug and is the weakness: the skill
checks the fingerprint of nothing. It pins a fingerprint in its description and then simply
trusts whatever the registry hands it. Making it verify what arrived would be remediation,
which this app deliberately does not do - and would delete the weakness entirely.

Specification references: AST02 spec sections 6.3 and 6.4; decisions S-5, S-11, S-12, S-13,
S-14, S-16; acceptance tests A-2, A-8, A-9, A-13, A-14.
"""

import json
from datetime import datetime, timezone

from app.skills.context import CapabilityRefused, SkillResult

# Where the sizing pack is published. This string must stay byte-for-byte identical to the
# "source" in manifest.json - the description says where the component comes from, and it
# has to be the same place the skill actually goes. A test checks the two match.
PACK_URL = "http://127.0.0.1:8000/mock/registry/sizing-heuristics/2.3.1"

# What this skill falls back on when the registry cannot be reached, or has nothing to
# offer. A brand new lab still gets a working answer - the advertised job does not depend
# on the component being there, which is what makes its ABSENCE observably different from
# its presence.
BUILT_IN_BANDS = [
    {"id": "xs", "label": "quick", "minutes": 15},
    {"id": "s", "label": "short", "minutes": 45},
    {"id": "m", "label": "half", "minutes": 180},
    {"id": "l", "label": "day", "minutes": 420},
]
BUILT_IN_RULES = [
    {"if": "words_lt", "value": 4, "band": "xs"},
    {"if": "words_lt", "value": 8, "band": "s"},
    {"default": "m"},
]

# The band used if a pack's rules run out without matching and without a default.
FALLBACK_BAND = "m"


def run(ctx, params):
    """
    Estimate how much working time the user's tasks will take.

    In:
      ctx    - the official channel for everything this skill is allowed to do.
      params - may carry "scope", either "open" or "all". Optional.
    Out: a SkillResult with the total, the biggest item, and every task's size.

    The order matters and is deliberate: the tasks are read FIRST and the sizing pack is
    fetched LAST, so the fetch is the final thing on the record.
    """
    scope = str(params.get("scope") or "open")
    if scope not in ("open", "all"):
        scope = "open"

    # --- 1. Read the user's tasks ----------------------------------------------
    tasks = ctx.tasks.list(scope)

    # --- 2. Fetch the sizing pack ----------------------------------------------
    #
    # This is the honest, advertised, declared thing this skill exists to do, and it is
    # the LAST thing it does through the official channel. There is nothing wrong with
    # this line. What is wrong is not in this file at all - it is in what comes back.
    pack = _acquire_pack(ctx)

    # --- 3. Apply the pack, entirely in memory ---------------------------------
    #
    # The pack is data. It is walked, not run. Whatever it says about how big things are
    # is simply believed, because there is nothing here that could tell the difference
    # between the reviewed build and a substituted one.
    bands = _bands_of(pack)
    rules = _rules_of(pack)

    sized = []
    for task in tasks:
        if task.get("done"):
            # A finished task costs no more time.
            continue
        band_id = _band_for(task, rules)
        sized.append(
            {
                "task_id": task.get("id"),
                "title": task.get("title", ""),
                "band": band_id,
                "minutes": _minutes_for(band_id, bands),
            }
        )

    total_minutes = sum(item["minutes"] for item in sized)
    biggest = max(sized, key=lambda item: item["minutes"], default=None)

    # --- 4. Hand back the answer. No further broker call is made. --------------
    return SkillResult(
        summary=_describe(len(sized), total_minutes, biggest, pack is None),
        data={
            "scope": scope,
            "task_count": len(sized),
            "total_minutes": total_minutes,
            "tasks": sized,
            # Which component was actually applied, recorded for the activity screen.
            # This is detail for a person reading the record, never part of the sentence
            # the assistant is given.
            "pack": {
                "name": (pack or {}).get("pack", "built-in"),
                "version": (pack or {}).get("version", ""),
                "publisher": (pack or {}).get("publisher", ""),
                "used_fallback": pack is None,
            },
        },
    )


def _acquire_pack(ctx, url=PACK_URL):
    """
    Fetch the published sizing pack.

    In: the official channel, and where to fetch from. Out: the pack, or nothing.

    Three ways this can come back empty, and all three mean the same thing to this skill -
    "no pack today, use the built-in one":

      the request was refused        the app would not make it (a bad address, say);
      the registry had nothing       there is no such component at that version;
      the reply was not readable     whatever came back was not a pack.

    Note what this does NOT do: it does not check that what arrived is what the
    description pinned. That is the weakness, in one line.
    """
    try:
        response = ctx.net.get(url)
    except CapabilityRefused:
        return None

    if response.status_code != 200:
        return None

    try:
        document = json.loads(response.text)
    except (ValueError, TypeError):
        return None

    return document if isinstance(document, dict) else None


def _bands_of(pack):
    """
    The size bands to use.

    In: the fetched pack, or nothing. Out: a list of bands.
    """
    bands = (pack or {}).get("bands")
    if isinstance(bands, list) and bands:
        return bands
    return BUILT_IN_BANDS


def _rules_of(pack):
    """
    The sizing rules to use.

    In: the fetched pack, or nothing. Out: a list of rules.
    """
    rules = (pack or {}).get("rules")
    if isinstance(rules, list) and rules:
        return rules
    return BUILT_IN_RULES


def _band_for(task, rules):
    """
    Work out which size band one task falls into.

    In: the task, and the pack's rules. Out: the band's identifier.

    Rules are tried in order and the FIRST match wins, which is ordinary for this kind of
    table - and is also exactly what makes a rule added at the top of the list so
    effective at overriding everything below it.
    """
    for rule in rules:
        if not isinstance(rule, dict):
            continue

        if "default" in rule:
            return str(rule["default"])

        if _rule_matches(task, rule.get("if"), rule.get("value")):
            return str(rule.get("band", FALLBACK_BAND))

    return FALLBACK_BAND


def _rule_matches(task, test, value):
    """
    Does one rule apply to one task?

    In: the task, which test to apply, and the value to compare against.
    Out: True if the rule applies.

    A test this skill does not recognise simply does not match. A pack is written by
    somebody else and may be newer than this skill; treating an unknown test as "no" keeps
    the estimate working rather than failing.
    """
    if test == "words_lt":
        return len(str(task.get("title", "")).split()) < _as_number(value)

    if test == "age_days_gt":
        return _age_in_days(task) > _as_number(value)

    if test == "notes_contains_any":
        if not isinstance(value, list):
            return False
        notes = str(task.get("notes", "")).lower()
        return any(str(word).lower() in notes for word in value)

    return False


def _as_number(value):
    """
    Read a rule's value as a number.

    In: whatever the pack put there. Out: a number, or 0 if it was not one.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _age_in_days(task):
    """
    How many days ago a task was created.

    In: the task. Out: a whole number of days, never negative.

    A task whose date cannot be read counts as brand new, which is the harmless answer:
    it means an unreadable date can never push something into the largest band.
    """
    stamp = str(task.get("created_at") or "")
    if not stamp:
        return 0

    try:
        created = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0

    return max((datetime.now(timezone.utc) - created).days, 0)


def _minutes_for(band_id, bands):
    """
    How many minutes one band is worth.

    In: the band's identifier and the pack's bands. Out: a number of minutes.
    """
    for band in bands:
        if isinstance(band, dict) and str(band.get("id")) == band_id:
            try:
                return int(band.get("minutes", 0))
            except (TypeError, ValueError):
                return 0
    return 0


def _spell_out(minutes):
    """
    Turn a number of minutes into something a person would say.

    In: minutes. Out: a short phrase like "4 hours 15 minutes".
    """
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} minutes"

    hours, remainder = divmod(minutes, 60)
    hour_word = "hour" if hours == 1 else "hours"
    if remainder == 0:
        return f"{hours} {hour_word}"
    return f"{hours} {hour_word} {remainder} minutes"


def _describe(count, total_minutes, biggest, used_fallback):
    """
    Write the sentence the assistant is given.

    In: how many tasks were sized, the total, the biggest one, and whether the published
    pack was missing. Out: one plain sentence.

    IMPORTANT, AND EASY TO BREAK BY BEING HELPFUL: this sentence is written entirely in
    this skill's own words and its own numbers. It never repeats a line out of the pack -
    not the pack's name, not its publisher, not a band's label. That is deliberate. Text
    that arrives from outside and is passed straight into what the assistant is told is a
    different weakness with its own name, and quoting the pack here would raise it as well
    - turning a clean demonstration of one problem into a muddled demonstration of two.

    The task titles are the user's own words, not the pack's, so naming the biggest task is
    safe and is the most useful part of the answer.
    """
    if count == 0:
        return "There is nothing outstanding to estimate - the list is clear."

    task_word = "task" if count == 1 else "tasks"
    sentence = (
        f"Your {count} outstanding {task_word} come to about "
        f"{_spell_out(total_minutes)} of work in total."
    )

    if biggest is not None:
        sentence += (
            f" The biggest single item is \"{biggest['title']}\", "
            f"at about {_spell_out(biggest['minutes'])}."
        )

    if used_fallback:
        sentence += (
            " Note that the team's shared sizing pack could not be reached, so these are "
            "rough built-in estimates."
        )

    return sentence
