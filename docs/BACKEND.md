# TaskBot — Backend Walkthrough

A plain-words tour of the `backend/` folder: every folder, every file, and what it's
for. Think of the backend as the **brain and rulebook** of TaskBot — the browser pages
are the face, this is everything happening behind them.

The top level splits into two things:

- **`app/`** — all the running code (grouped into folders by job)
- **`policy/`** and **`skills/`** — data files the code reads (the rules, and the one
  honest built-in skill)

---

## `app/` — the two loose files at the top

| File | What it's for |
|---|---|
| `main.py` | **The front door.** Builds the whole app and wires every piece together — the API, the web pages, the mock endpoints. When you run the server, this is what starts. |
| `config.py` | **The settings sheet.** Says where everything lives on disk — the data folder, the skills folder, the collector inbox, the dashboard file. One place to look up "where does X go?" |

---

## `app/api/` — the machine-readable interface

The stable JSON endpoints a program (or your tests) talk to.

| File | What it's for |
|---|---|
| `routes.py` | Defines the API endpoints — `/api/chat` (send a message to the assistant), `/api/findings` (list what got flagged), `/api/reset` (wipe the lab clean). |
| `schemas.py` | The exact **shapes** of the data going in and out (what a request looks like, what a finding looks like). Keeps the format predictable. |

---

## `app/web/` — the human-facing pages

| File | What it's for |
|---|---|
| `routes.py` | Serves the actual **screens** you click through in the browser — Tasks, Store, Findings, and the **Dashboard**. It reads the data and hands it to the HTML templates. |

---

## `app/chat/` — the assistant's conversation loop

This is where a user message becomes an action.

| File | What it's for |
|---|---|
| `orchestrator.py` | **The conductor.** Takes your message, asks the model which skill (if any) to use, runs that skill safely, and returns the reply. The heart of "you type something, something happens." |
| `prompts.py` | The instructions given to the AI model — how to decide which skill fits your request. |
| `builtins.py` | Simple built-in replies the assistant can give without needing a skill. |

---

## `app/llm/` — talking to the AI model

| File | What it's for |
|---|---|
| `ollama_client.py` | The connector to **Ollama** (the local AI model, `llama3.1:8b`). Sends it the prompt, gets back its choice. In tests this gets swapped for a fake "stub" so results are predictable. |

---

## `app/skills/` — how skills are loaded and safely run ⭐ core of the project

The most important folder — it's the safety cage the malicious skills run inside.

| File | What it's for |
|---|---|
| `registry.py` | **Finds skills.** Auto-scans folders and discovers every installed skill — including the two malicious ones under `vulnerabilities/`. |
| `manifest.py` | Reads a skill's **manifest** (its "ingredients label"). Checks the *shape* is valid — but deliberately does **not** check whether the label is honest. That gap is exactly what AST04 exploits. |
| `context.py` | **The official channel (`ctx`).** The single doorway a skill must use to read tasks, read files, or send network requests. These are the "brokers." Every action is **recorded here before** it's allowed. Skills can't go around this. |
| `scope.py` | The rules for *where* a skill is allowed to reach — e.g. file reads only inside allowed folders, network only to your own machine. |
| `host.py` | **Runs the skill's code** in a controlled way and hands it the `ctx` channel. |

> If asked "how are the vulnerabilities kept safe?" — the answer lives here: skills only
> act through `context.py`, and everything is logged before the safety decision.

---

## `app/monitor/` — the watcher

| File | What it's for |
|---|---|
| `observations.py` | **The logbook.** Records every action a skill took (read this, sent that) as it happens. |
| `audit_hook.py` | A separate watch point. If a skill tried to sneak around the official channel, that shows up as a special "bypass" observation. |

The key design rule: the monitor writes down **what happened** and never peeks at the
skill's manifest — so a lying label can't fool it.

---

## `app/findings/` — the detective that catches the vulnerabilities ⭐

Where the three checks live and where findings are born.

| File | What it's for |
|---|---|
| `engine.py` | **The brain of detection.** Compares what the skill *did* (from the monitor) against what it *declared* and what's *normal*. Runs the three checks and raises findings: **AST04** (lied), AST03 (too much power), **AST01** (read-then-send theft). |
| `taxonomy.py` | The **catalogue of finding types** — each one's name, which check it belongs to, and how severe it is (AST01 = critical, AST04 = high). |
| `baselines.py` | Loads the "what's normal for this kind of skill" rules used by the proportionality check. |
| `markers.py` | Writes a small **marker file** every time a finding is raised — proof, written by the *app* (never the skill), that carries a fixed lab phrase. Cleared on reset. |

---

## `app/storage/` — where the data lives

| File | What it's for |
|---|---|
| `models.py` | The **data shapes** — what a Task looks like, what a Standup looks like. (The Standup shape has no room to hold a task list — that's part of why the dashboard can't leak the theft.) |
| `store.py` | **Read and write the data** — load tasks, save standups, and `reset_lab()` which wipes everything back to clean. |
| `atomic.py` | Saves JSON files **safely** so a crash mid-write can't corrupt them. |
| `seed.py` | The **starter data** — the 8 sample tasks the lab begins with. |

---

## `app/mock/` — the fake outside world

| File | What it's for |
|---|---|
| `collector.py` | The **hidden exfil sink.** `POST /mock/collector` catches whatever a skill "sends out" and drops it in `data/collector/inbox/`. This is where AST01's stolen task list lands — a local folder pretending to be an attacker's server. |
| `dashboard.py` | The **visible standup sink.** `POST /mock/dashboard` accepts only a short standup line (message, count, oldest) and **throws away anything else** — so the theft physically cannot show up on the Dashboard screen. |

---

## `policy/` — the rulebook (data, not code)

| File | What it's for |
|---|---|
| `capability_baselines.json` | For each category of skill, what powers are **normal**. A `reporting` skill is expected to read tasks — nothing more. Used by the proportionality check. |
| `capability_vocabulary.json` | The official **list of power names** (`task.read`, `fs.read`, `net.outbound`, etc.) so everyone uses the same words. |

---

## `skills/catalogue/` — the honest control skill

| File | What it's for |
|---|---|
| `task_summary/manifest.json` | The label for the honest **Task Summary** skill. |
| `task_summary/skill.py` | A completely well-behaved skill — declares what it does and does exactly that, nothing hidden. It's the **baseline**: it must always come back with **zero findings**, proving the detector doesn't flag innocent skills. |

> Note: the two *malicious* skills don't live here — they live outside `backend/`, under
> `vulnerabilities/ast01-malicious-skills/` and `vulnerabilities/ast04-insecure-metadata/`.
> That separation keeps the dangerous stuff clearly walled off from the foundation.

---

## The 30-second version to say out loud

> "The backend has one folder per job. **`chat`** turns your message into an action.
> **`skills`** is the safety cage every skill runs inside — one official channel,
> everything logged. **`monitor`** writes down what each skill actually did. **`findings`**
> is the detective that compares what a skill *did* against what it *said* and *should* do,
> and raises AST01 or AST04. **`storage`** holds the tasks, **`mock`** is the fake outside
> world where stolen data lands, and **`policy`** is the rulebook. The malicious skills live
> outside the backend entirely, so the trustworthy part and the dangerous part never mix."
