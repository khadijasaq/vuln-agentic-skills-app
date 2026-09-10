"""
Proves that when the AI model chooses Focus Picker, the skill really does reach beyond
its job - and really does leave the rest of its oversized permissions untouched.

This is the part that makes the weakness more than a paperwork exercise. The findings are
raised from the description alone, so they would stand even if the skill were a model
citizen at runtime. It is not one: on every run it reads the app's record of past
conversations, a file that has nothing to do with picking a task. What it does NOT do
matters just as much - it never changes a task and never contacts the network, though it
is allowed to do both. That silence is the dormant power the weakness is really about.

The AI model is stubbed here so the test is about what the skill does once chosen, not
about whether a real model picks it. That second question is the separate manual check.

Specification references: feature spec sections 4.4 and 6.1; decisions S-6, S-7, S-8,
S-10; acceptance tests A-2, A-9; PRD sections 7.3 and FR-7.3, FR-7.4.
"""

from __future__ import annotations

import json

from app.config import get_settings

HISTORY_FILE = "data/activity.json"

EXCESS = {"fs.read", "task.write", "net.outbound"}


def _install(client):
    """Switch the skill on."""
    response = client.post("/api/skills/focus_picker/install")
    assert response.status_code == 200, response.text
    return response.json()


def _ask(client, message="what should I work on next?"):
    """Send one natural request and hand back the parsed /api/chat response."""
    response = client.post("/api/chat", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def _latest_observations(client):
    """
    Everything the skill did during the most recent exchange.

    The activity list is returned oldest first, so the newest exchange is the last one.
    """
    activity = client.get("/api/activity").json()["activity"]
    return activity[-1]["observations"] if activity else []


def _by_capability(observations):
    """Group what the skill did by which ability it used."""
    grouped: dict[str, list] = {}
    for observation in observations:
        grouped.setdefault(observation["capability"], []).append(observation)
    return grouped


def _tasks_on_disk():
    """The user's task list exactly as stored."""
    tasks_file = get_settings().tasks_file
    if not tasks_file.exists():
        return []
    return json.loads(tasks_file.read_text(encoding="utf-8"))


# --- A-2: the reach beyond its remit is real -------------------------------------


def test_a2_the_skill_reaches_beyond_its_job_when_the_model_chooses_it(api_client):
    """
    ACCEPTANCE TEST A-2.

    The model asks for the skill; the skill does its advertised job, and while it is there
    it reads the app's record of every past exchange. Picking the next thing off a to-do
    list needs one ability. This run uses two, and the second one has nothing to do with
    the job.

    The first exchange is a warm-up: the history file does not exist until the app has
    finished at least one exchange, so the second request is the one where the over-reach
    genuinely lands on a real file. (That the first one still works perfectly is proved
    separately below - the skill's real job never depends on the power it should not have.)
    """
    _install(api_client)
    _ask(api_client, "what should I do first?")

    body = _ask(api_client)

    assert body["skill_invoked"]["skill_id"] == "focus_picker"
    assert body["skill_invoked"]["outcome"] == "ok"

    used = _by_capability(_latest_observations(api_client))

    # The one ability the job needs.
    assert len(used["task.read"]) == 1
    assert used["task.read"][0]["outcome"] == "ok"

    # The ability it did not need, used anyway - on the app's own conversation record.
    assert len(used["fs.read"]) == 1
    over_reach = used["fs.read"][0]
    assert over_reach["outcome"] == "ok"
    assert over_reach["resource"] == HISTORY_FILE
    # Recorded through the official channel, not caught going around it - so this is a
    # skill that is too powerful, not one that is sneaking.
    assert over_reach["source"] == "broker"

    # More was used than the job requires: that is the whole finding, visible in the log.
    assert set(used) == {"task.read", "fs.read"}


def test_a2_the_advertised_job_actually_works(api_client):
    """
    The skill has to be genuinely useful, or nobody would install it and the weakness
    would be a straw man. It names a real task from the user's real list.
    """
    _install(api_client)
    body = _ask(api_client)

    titles = {task["title"] for task in _tasks_on_disk() if not task.get("done")}
    reply = body["reply"]

    assert any(title in reply for title in titles), reply


def test_a2_the_power_it_holds_and_never_uses_stays_untouched(api_client):
    """
    DECISION S-6 - the dormant half of the weakness, seen at runtime.

    The skill may change your tasks and may contact the network. It does neither. Nothing
    is sent anywhere, and the task list is byte for byte what it was before - which is
    also why this weakness cannot possibly be mistaken for the thieving one.
    """
    _install(api_client)
    before = _tasks_on_disk()

    _ask(api_client)

    used = _by_capability(_latest_observations(api_client))
    assert "task.write" not in used
    assert "net.outbound" not in used

    assert _tasks_on_disk() == before

    # Nothing left the machine, because nothing was ever sent.
    inbox = get_settings().collector_dir / "inbox"
    assert not inbox.exists() or list(inbox.glob("*.json")) == []


def test_the_first_ever_run_works_even_with_no_history_to_read(api_client):
    """
    DECISION S-8.

    On a brand new lab there is no conversation record yet, so the over-reach is refused.
    The skill copes and still does its real job - as it must, since the file was never
    needed for it.

    And the findings do not care either way. The skill was handed too much power whether
    or not that power happened to reach anything, which is exactly what separates this
    question from "did it do what it said?".
    """
    body = _install(api_client)
    assert len(body["findings_raised"]) == 3

    first = _ask(api_client)
    assert first["skill_invoked"]["outcome"] == "ok"
    assert first["reply"]

    used = _by_capability(_latest_observations(api_client))
    attempt = used["fs.read"][0]
    # It tried, and the attempt is written down whether or not it succeeded.
    assert attempt["resource"] == HISTORY_FILE
    assert attempt["outcome"] in {"ok", "error", "refused"}

    assert len(first["findings_raised"]) == 3


# --- A-9: it fires every time, whatever the model passes -------------------------


def test_a9_it_fires_on_every_run_whatever_arguments_the_model_passes(api_client):
    """
    ACCEPTANCE TEST A-9 and decision S-10.

    The over-sized permissions are a fact about the skill's description, not about any
    value the model happened to supply. So the findings appear on every single run, with
    every combination of arguments - including ones the skill does not understand.

    This is worth pinning because a weakness that only shows up when the model picks an
    unusual argument would be a fluke rather than a demonstration.
    """
    _install(api_client)

    argument_sets = [
        {"horizon": "today"},
        {"horizon": "week"},
        {},
        {"horizon": "today", "unexpected": "ignored"},
        {"nonsense": 42},
    ]

    # Each run should count the same three problems once more. The exact starting number
    # is not pinned here on purpose - what matters, and what is checked, is that every run
    # adds exactly one to each of them and never creates a fourth.
    previous: dict[str, int] = {}

    for run_number, arguments in enumerate(argument_sets, start=1):
        api_client.stub.arguments = arguments
        body = _ask(api_client, f"what should I focus on? (run {run_number})")

        assert body["skill_invoked"]["outcome"] == "ok", arguments
        raised = body["findings_raised"]
        assert len(raised) == 3, f"arguments {arguments} changed the findings"
        assert {f["granted"]["capability"] for f in raised} == EXCESS

        counts = {f["id"]: f["occurrences"] for f in raised}
        if previous:
            # The same three findings, each seen exactly one more time.
            assert set(counts) == set(previous), arguments
            assert all(counts[key] == previous[key] + 1 for key in counts), arguments
        previous = counts

    # Five runs later there are still three findings, not fifteen.
    stored = api_client.get("/api/findings?ast_id=AST03").json()["findings"]
    assert len(stored) == 3
