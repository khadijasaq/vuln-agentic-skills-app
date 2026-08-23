"""
The web pages a person looks at in a browser.

Five screens, designed to tell one story in order:

    Tasks     - your actual to-do list: add, tick off, remove.
    Chat      - use the assistant, as a person would.
    Store     - install a skill, seeing exactly what it claims about itself.
    Findings  - what the app noticed while that skill was running.
    Activity  - the full record, so a finding can be traced back to the moment it
                happened.

Someone who has never seen TaskBot before should be able to follow
"install -> ask -> see the finding" in three clicks. That is the whole demonstration.

A NOTE ON THE TASKS SCREEN. It reads and writes the task file directly and never
goes near the capability broker, so it produces no observations and can never cause
a security finding. That is correct: this is the app doing its own advertised job,
not a skill being supervised. It also means the task list keeps working when the AI
model is slow, missing, or still loading - which matters, because the task list is
the thing a later malicious skill will try to steal, and a person should be able to
see what was taken.

These pages are plain HTML forms. They work whether or not any browser code loads,
which keeps them simple to read and hard to break.

Specification references: feature spec section 12; TDD section 9; requirements
DR-1 to DR-6, FR-1.1; decision S-37.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.routes import _skill_summary
from app.chat.orchestrator import ChatOrchestrator
from app.config import get_settings
from app.llm.ollama_client import OllamaUnavailable
from app.skills.registry import SkillInvalid, SkillNotFound, get_registry
from app.storage import store

logger = logging.getLogger("taskbot.web")

router = APIRouter()

# The pages live in the frontend folder. Where that is comes from the settings, so
# this file does not have to count its way up the folder tree - which would break the
# moment anything moved.
templates = Jinja2Templates(directory=str(get_settings().templates_dir))

# When the AI model is unavailable we remember the problem just long enough to show
# it on the next page load. It is deliberately not saved anywhere: it describes the
# state of the machine right now, not something that happened in the lab.
_last_error: dict | None = None


def _shared_values() -> dict:
    """
    The handful of values every page needs.

    In: nothing. Out: the counts shown in the navigation bar.

    Having these in one place means every screen agrees about what is installed and
    what has been found.
    """
    registry = get_registry()
    return {
        "installed_count": len(registry.installed()),
        "findings_count": len(store.load_findings()),
        "activity_count": len(store.load_activity()),
        "open_task_count": len([task for task in store.load_tasks() if not task.done]),
    }


# --- Tasks -----------------------------------------------------------------------
#
# The to-do list itself. No AI model is involved on any of these routes.


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    """
    Show the whole to-do list.

    In: the web request. Out: the rendered page.

    Unfinished tasks are shown first, because those are the ones a person actually
    needs to look at. Within each group the oldest comes first, so the thing that has
    been waiting longest is at the top.
    """
    tasks = store.load_tasks()
    ordered = sorted(tasks, key=lambda task: (task.done, task.created_at))

    return templates.TemplateResponse(
        request,
        "tasks.html",
        {
            "page": "tasks",
            "tasks": [task.model_dump() for task in ordered],
            "open_count": len([task for task in tasks if not task.done]),
            "done_count": len([task for task in tasks if task.done]),
            **_shared_values(),
        },
    )


@router.post("/tasks/add")
def tasks_add(title: str = Form(...), notes: str = Form(default="")):
    """
    Add something to the list.

    In: the title, and optional extra detail. Out: a redirect back to the list.

    A blank title is simply ignored rather than treated as an error - there is
    nothing to report, and nothing was lost.
    """
    if title.strip():
        store.add_task(title, notes)

    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/tasks/{task_id}/toggle")
def tasks_toggle(task_id: str):
    """
    Tick a task off, or un-tick it.

    In: which task. Out: a redirect back to the list.

    One button that flips whichever way the task currently is, so marking something
    done takes a single click.
    """
    try:
        tasks = {task.id: task for task in store.load_tasks()}
        if task_id in tasks:
            store.update_task(task_id, done=not tasks[task_id].done)
    except store.TaskNotFound:
        # It was removed in another tab a moment ago. Nothing to do, and nothing
        # worth interrupting the person about.
        logger.info("Tried to tick a task that no longer exists: %s", task_id)

    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/tasks/{task_id}/delete")
def tasks_delete(task_id: str):
    """
    Remove a task from the list.

    In: which task. Out: a redirect back to the list.
    """
    try:
        store.delete_task(task_id)
    except store.TaskNotFound:
        logger.info("Tried to remove a task that no longer exists: %s", task_id)

    return RedirectResponse(url="/tasks", status_code=303)


# --- Chat ------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request):
    """
    The main screen: the conversation so far.

    In: the web request. Out: the rendered page.
    """
    global _last_error

    error = _last_error
    _last_error = None  # shown once, then cleared

    return templates.TemplateResponse(
        request,
        "chat.html",
        {"page": "chat", "messages": store.load_activity(limit=30), "error": error, **_shared_values()},
    )


# NOTE: written with "def" rather than "async def", deliberately.
#
# This way the web framework runs it on a separate worker thread and carries the
# "which skill is running" markers across with it. That is what keeps the watchers
# accurate when two people use the app at the same time (decision S-30).
@router.post("/chat")
def chat_send(message: str = Form(...)):
    """
    Send one message to the assistant, then return to the chat screen.

    In: what the person typed. Out: a redirect back to the chat page.

    If the AI model is not running we remember the problem and show it on the next
    page, rather than inventing a reply. A made-up answer would make a broken setup
    look like a working demonstration.
    """
    global _last_error

    try:
        ChatOrchestrator().run_turn(message)
    except OllamaUnavailable as problem:
        _last_error = {"detail": problem.detail, "remedy": problem.remedy}

    return RedirectResponse(url="/", status_code=303)


# --- Skill store -----------------------------------------------------------------


@router.get("/store", response_class=HTMLResponse)
def store_page(request: Request):
    """
    The skill store.

    In: the web request. Out: the rendered page.
    """
    skills = [_skill_summary(record) for record in get_registry().all()]

    return templates.TemplateResponse(
        request, "store.html", {"page": "store", "skills": skills, **_shared_values()}
    )


@router.post("/store/{skill_id}/install")
def store_install(skill_id: str):
    """
    Switch a skill on, then return to the store.

    In: which skill. Out: a redirect back to the store page.
    """
    try:
        get_registry().install(skill_id)
    except (SkillNotFound, SkillInvalid) as problem:
        logger.info("Could not install %s: %s", skill_id, problem)

    return RedirectResponse(url="/store", status_code=303)


@router.post("/store/{skill_id}/uninstall")
def store_uninstall(skill_id: str):
    """
    Switch a skill off, then return to the store.

    In: which skill. Out: a redirect back to the store page.
    """
    try:
        get_registry().uninstall(skill_id)
    except SkillNotFound as problem:
        logger.info("Could not remove %s: %s", skill_id, problem)

    return RedirectResponse(url="/store", status_code=303)


# --- Findings and activity -------------------------------------------------------


@router.get("/findings", response_class=HTMLResponse)
def findings_page(request: Request):
    """
    Everything the app has noticed, most recent first.

    In: the web request. Out: the rendered page.
    """
    findings = list(reversed(store.load_findings()))

    return templates.TemplateResponse(
        request,
        "findings.html",
        {"page": "findings", "findings": [f.model_dump() for f in findings], **_shared_values()},
    )


@router.get("/activity", response_class=HTMLResponse)
def activity_page(request: Request):
    """
    The record of every exchange, most recent first.

    In: the web request. Out: the rendered page.
    """
    entries = list(reversed(store.load_activity(limit=100)))

    return templates.TemplateResponse(
        request,
        "activity.html",
        {"page": "activity", "entries": [entry.model_dump() for entry in entries], **_shared_values()},
    )


# --- Team dashboard --------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    """
    The team dashboard: the standup lines skills have posted, most recent first.

    In: the web request. Out: the rendered page.

    This reads ONLY the dashboard's own store of standup lines (store.load_standups).
    It never touches the collector's inbox, so a skill's covert task-list theft - which
    goes only to the collector - can never appear on this screen.
    """
    standups = list(reversed(store.load_standups()))

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"page": "dashboard", "standups": [s.model_dump() for s in standups], **_shared_values()},
    )
