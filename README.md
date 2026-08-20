# TaskBot

> ## ⚠️ INTENTIONALLY VULNERABLE — LOCAL LAB USE ONLY
>
> This application contains **deliberate security weaknesses**. It exists so that
> security tools built for AI agents have something realistic to be tested against,
> in the same way DVWA and WebGoat exist for web applications.
>
> **Do not deploy it. Do not expose it to a network. Do not put real data in it.**
>
> It refuses to listen on anything except this computer, and it says "intentionally
> vulnerable" on every screen and in its health check. Those are safety measures, not
> decoration.

---

## What it is

TaskBot is a small to-do assistant. You talk to it, and it keeps track of things you
need to do.

Its extra abilities come as **skills** — self-contained bundles that you install from
a store. Each skill comes with a description saying what it does and what permissions
it needs. A local AI model reads those descriptions and decides, on its own, whether
one of them fits what you asked for.

That is where the security exercise lives. A description is only ever a *claim*. The
interesting question is what happens when a skill's claim and its behaviour disagree —
and whether anything notices.

While a skill runs, TaskBot writes down everything it touches, then compares that
against what the skill said it would do. Anything that does not match becomes a
**finding**.

## Current state

This is the **foundation**: the assistant, the skill store, the watchers, the findings
engine, the web pages, and one deliberately honest skill.

That honest skill is the point of this stage. It is the control: if TaskBot ever
reports a problem with a skill that has done nothing wrong, then TaskBot itself is
broken, and nothing else it reports can be trusted. "The scanner found three problems"
only means something once something has proved the scanner can also stay quiet.

The three deliberately flawed skills are separate pieces of work and are **not here
yet**.

## Running it

You need [Ollama](https://ollama.com) running locally with a model that supports tool
calling.

```bash
ollama serve
ollama pull llama3.1:8b

uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>.

Without a model, the chat screen will tell you exactly what is missing and the command
that fixes it. It will never invent a reply — a demonstration that appeared to work
with no model running would be worthless.

## Trying it out

1. Open **Store** and look at *Task Summary*. Note that its permissions are shown
   under "Declared by the publisher" — that wording is deliberate.
2. Install it.
3. Go to **Chat** and ask something ordinary, like *"how am I doing on my tasks?"*
4. Open **Activity** and expand the row. You will see which skill the model chose and
   every single thing that skill touched, in order.
5. Open **Findings**. It is empty — and that is the correct result.

## For tools and scripts

Everything a person can do, a program can do too:

| | |
|---|---|
| `GET /api/health` | Is it up, is the model reachable, what is in the lab |
| `GET /api/skills` | Every skill and what it claims about itself |
| `POST /api/skills/{id}/install` | Switch a skill on |
| `POST /api/chat` | `{"message": "..."}` — hold one exchange |
| `GET /api/findings` | Every problem noticed so far |
| `GET /api/activity` | The full record of every exchange |
| `POST /api/reset` | Clear what was observed and re-seed the tasks |

Every response carries a `schema_version`. Within version 1, fields may be **added**
but never renamed, retyped or removed.

`POST /api/chat` returns `findings_raised` for **that exchange only**, so a scanner can
attribute a problem to the exact message that caused it.

**`/api/reset` is not a security switch.** It changes no skill, no permission and no
policy — every weakness present before a reset is present after it. All it does is make
the app forget what it saw. There is no setting anywhere in TaskBot, reachable by any
route, that makes it less vulnerable.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `TASKBOT_MODEL` | `llama3.1:8b` | Which Ollama model to use (must support tool calling) |
| `TASKBOT_OLLAMA_URL` | `http://127.0.0.1:11434` | Where Ollama is |
| `TASKBOT_HOST` | `127.0.0.1` | **Loopback only — the app refuses to start otherwise** |
| `TASKBOT_PORT` | `8000` | Which port |
| `TASKBOT_DATA_DIR` | `./data` | Where the lab keeps its state |

## Starting over

Everything TaskBot remembers lives in `data/`. Delete that folder and it starts
completely fresh:

```bash
rm -rf data/
```

Simulated attacks leave evidence files behind. Every one of them contains the phrase
`INTENTIONALLY_VULNERABLE_LAB_MARKER`, so you can find them all at once:

```bash
grep -rl INTENTIONALLY_VULNERABLE_LAB_MARKER data/markers/
```

## Safety

Nothing TaskBot demonstrates can hurt anything real:

- **Nothing leaves this computer.** Skills may only contact addresses on this machine.
  An attempt to send anywhere else is refused — and still recorded in full, so a
  simulated theft can be examined completely without a single byte going anywhere.
- **Files are fenced in.** Skills can only reach the app's own folders. Attempts to
  climb out are refused, and recorded.
- **Nothing is destroyed.** There is no way for a skill to delete or move a file, and
  it cannot overwrite the app's own records — so it cannot erase the evidence of what
  it did.
- **It stays on this machine.** The app refuses to start on any address another
  computer could reach.

One honest limit, stated plainly: the supervision is a *cooperative boundary, not a
sandbox*. A skill that ignores the official channels and reaches for a file directly
**is detected, but not prevented**. That is acceptable here because every skill in this
repository is written by us and deliberately confined. It would not be acceptable for
skills from strangers, which is exactly why uploading your own skill is not supported.

## Documentation

| | |
|---|---|
| `docs/PRD.md` | What this product is for and why |
| `docs/TDD.md` | How the whole system is designed |
| `docs/features/app-foundation/` | The specification and build plan for this stage |

## Tests

```bash
uv run pytest
```

The suite is where the security promises are actually pinned down. The ones worth
knowing about:

- **A-4** — an honest skill produces no findings across twenty full exchanges.
- **A-5** — the app's own work on a skill's behalf is never blamed on the skill.
- **A-6** — with a stand-in model that never asks for anything, no skill runs for
  *any* message, including ones quoting a skill's own description word for word.
- **A-9** — the two kinds of security problem stay distinguishable from each other.
