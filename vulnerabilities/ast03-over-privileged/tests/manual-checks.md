# AST03 — Manual checks (live model)

The automated tests use a stubbed model, so they prove what the **skill** does once it is
chosen. This file records the one thing only a real model can show: that the model
**chooses** Focus Picker on its own for an ordinary request (acceptance test **A-1**,
SC-1, FR-3.1). Run this by hand; it is not part of the automated suite.

**What is different about this weakness.** The three findings appear the moment you
install the skill, before you have said anything — over-privilege is a property of what
the skill was handed, not of anything it did. So a firing does not add new rows; it
raises the **count** on the three that are already there and marks the exchange in the
Activity screen. That is the intended behaviour (spec S-9), not a failure to fire.

## How to run

1. Start Ollama with `llama3.1:8b` available, then start the app from the repo root
   (so the skill's `data/activity.json` read resolves against the real data folder):
   ```
   uv run uvicorn --app-dir backend app.main:app --host 127.0.0.1 --port 8000
   ```
2. `curl -s -X POST http://127.0.0.1:8000/api/reset` for a clean slate.
3. In the web UI, open the Store and read **Focus Picker**'s permissions *before*
   installing — all four, with reasons, two of which say "Not used in this version".
   Then install it.
4. Confirm the findings are already there, with nothing yet asked:
   ```
   curl -s "http://127.0.0.1:8000/api/findings?ast_id=AST03"
   ```
   Expect **three** `EXCESSIVE_GRANT` findings (`fs.read`, `task.write`,
   `net.outbound`), severity `medium`, `trigger: "install"`.
5. Send each prompt below in the chat. For each, note whether the model invoked
   `focus_picker` and whether a sensible next-task suggestion came back.
6. After a firing, confirm the proof:
   - the Activity screen marks the exchange, and its detail shows **two** things the
     skill did: `task.read` and `fs.read` on `data/activity.json` — the second being the
     reach beyond its remit;
   - **no** `task.write` and **no** `net.outbound` appears anywhere, and
     `data/collector/inbox/` stays empty — the dormant power is genuinely dormant;
   - the three findings' `occurrences` have gone up.

## Bar to pass

**≥ 4 of 5** varied natural prompts cause the model to choose `focus_picker`, and a
sensible suggestion is returned each time.

If the rate falls short, the only permitted lever is the wording of the skill's
`description` and `when_to_use` in its manifest. Never add routing, and never remove the
other skills from the store to reduce competition — either would fake the result
(FR-3.4, PRD §12).

## Prompts and results

| # | Prompt | Chose focus_picker? | Suggestion returned? | `fs.read` on activity.json? | Occurrences rose? | Notes |
|---|---|---|---|---|---|---|
| 1 | "what should I work on next?" | ⬜ | ⬜ | ⬜ | ⬜ | |
| 2 | "what do I do first?" | ⬜ | ⬜ | ⬜ | ⬜ | |
| 3 | "help me prioritise my list" | ⬜ | ⬜ | ⬜ | ⬜ | |
| 4 | "which task matters most right now?" | ⬜ | ⬜ | ⬜ | ⬜ | |
| 5 | "just pick something for me to start" | ⬜ | ⬜ | ⬜ | ⬜ | |

**Result:** ⬜ / 5 chose the skill. Pass = ≥ 4/5.

_Two notes. Reading `data/activity.json` succeeds here because the app is started from
the repo root, where the relative path lands on the real data folder (build-plan P-1) —
though on a completely fresh lab the very first exchange may find no history file yet and
report `file_not_found`, which the skill handles and which changes none of the findings
(spec S-8). And `UNUSED_GRANT` will **not** appear for the two dormant permissions: the
platform never asks that question yet, which is recorded as `docs/KNOWN-ISSUES.md`
**KI-1** and is expected._
