# App Foundation — manual acceptance record

Run on **2026-08-21**, Windows 11, Python 3.12, against a real server started with
`uvicorn --app-dir backend app.main:app --host 127.0.0.1`.

Automated checks live in the test suite (`uv run pytest`). This file records the
checks a person has to look at, plus anything the environment prevented.

---

## A-1 — Runs from a clean checkout ✅

`rm -rf data/`, then start the server.

```
GET /api/health
{
  "schema_version": 1,
  "status": "ok",
  "intentionally_vulnerable": true,
  "model": "llama3.1:8b",
  "ollama": { "reachable": true, "model_present": false, ... },
  "counts": { "skills": 1, "installed": 0, "tasks": 8, "findings": 0, "activity": 0 }
}
```

A brand new lab: one skill on disk, none installed, eight believable starter tasks,
nothing found.

---

## A-11 — Safety catches ✅

**Refuses a non-loopback bind.** `TASKBOT_HOST=0.0.0.0 uv run python -m app.main` (run from `backend/`):

```
app.config.ConfigError: TASKBOT_HOST is set to '0.0.0.0', but TaskBot is
intentionally vulnerable and may only listen on this machine.
Allowed values: 127.0.0.1, ::1, localhost.
```

**Deleting `data/` resets everything.** Confirmed: the app restarts cleanly and
re-seeds, with no activity, no findings and nothing installed.

---

## A-12 — Behaviour with no usable model ✅

`POST /api/chat` returns **503** with the problem and the command that fixes it:

```json
{
  "error": "llm_unavailable",
  "detail": "The model 'llama3.1:8b' is not installed.",
  "reason": "model_missing",
  "remedy": "Install it with: ollama pull llama3.1:8b"
}
```

The read-only screens are unaffected — `/`, `/store`, `/findings`, `/activity` all
return 200. No invented reply appeared anywhere.

---

## A-13 — The story is followable ✅ (partial)

Verified against the live server:

- **Store** shows *Task Summary*, its description, its claimed `task.read`
  permission, and the caption **"Declared by the publisher"**.
- **Findings** shows the deliberate empty state: *"the installed skills have behaved
  exactly as declared"*.
- Every page carries the **"Intentionally vulnerable — local lab use only"** notice.
- All four screens are one click from each other.
- Every asset is served from this machine: `tokens.css` (2.4 KB), `app.css` (10.7 KB),
  `raleway.woff2` (43 KB), `app.js` (1 KB). Nothing is fetched from the internet.

The chat leg of the walkthrough is covered end to end by the automated test
`test_a13_install_ask_and_see_the_record`, using a scripted model. The live-model leg
is blocked — see below.

---

## A-3 — Live model picks the skill ⚠️ 3/5, NEEDS RE-RUNNING

**Updated 2026-08-21: `llama3.1:8b` is now installed.** It was pulled after the first
attempt, so the "blocked, no reference model" state below is resolved. A-3 has since
been run against it and scored **3 of 5** — under its bar of 4 — but the measurement
is not trustworthy, for the reason given at the end of this section.

### Result against the reference model

| Prompt | Outcome |
|---|---|
| "how am I doing on my tasks?" | timed out |
| "give me an overview of my to-do list" | timed out |
| "what is my task status?" | ✅ invoked `task_summary` |
| "how many things do I still have outstanding?" | ✅ invoked `task_summary` |
| "what have I been putting off longest?" | ✅ invoked `task_summary` |

**The two misses were cold-start timeouts, not the model declining.** Re-running the
first prompt on its own immediately afterwards invoked `task_summary` correctly and
returned HTTP 200. The activity log confirms it: the two failures wrote no entry at
all, which is what a failed turn does by design.

Cause: the 120-second read timeout in force at the time was too short for an 8B model
loading from cold on CPU, where each turn costs two model calls. **Decision S-36** has
since widened it to 300 seconds and added `keep_alive: 30m` so the model stays
resident. A-3 needs re-running under those settings before it can be called.

### Original finding (now superseded)

**The reference model was not installed when this was first attempted.**

`llama3.1:8b` (the model fixed by TDD §14 Q-5 / D-14) is absent. Ollama is running
with `mistral:latest`, `qwen2.5-coder:7b` and `qwen2.5-coder:3b`.

Both alternatives were tried and **neither uses Ollama's structured tool-calling
protocol**:

| Model | Behaviour |
|---|---|
| `qwen2.5-coder:3b` | Wrote the tool call as **plain text in the reply**: `{"name": "task_summary", "arguments": {}}` — no `tool_calls` field |
| `mistral:latest` | Replied in prose about what it *would* do: *"To give you an overview of your task list, I…"* — no tool call at all |

TaskBot behaved correctly throughout: it offered the tools, the model did not use the
protocol, so no skill ran. That is exactly the unsupported-model case D-14 anticipates
("native tool-calling support is the hard requirement; a model lacking it is
unsupported"). It is a property of these models, not a defect in the app.

**To complete A-3:**

```bash
ollama pull llama3.1:8b
uv run uvicorn --app-dir backend app.main:app --host 127.0.0.1 --port 8000
```

then send these five prompts to `POST /api/chat` and confirm that at least four cause
the model to invoke `task_summary`:

1. "how am I doing on my tasks?"
2. "give me an overview of my to-do list"
3. "what is my task status?"
4. "how many things do I still have outstanding?"
5. "what have I been putting off longest?"

If fewer than four succeed, the fix is a more compelling `description` and
`when_to_use` in `skills/catalogue/task_summary/manifest.json` — **never** a change to
the dispatcher (FR-3.4).

---

## Note

`main.py` at the repository root is the leftover stub from the initial commit. The
real entry point is `app/main.py`. It is harmless but redundant, and could be deleted.
