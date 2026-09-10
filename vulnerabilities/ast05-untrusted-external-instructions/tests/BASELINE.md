# AST05 — Pre-change baseline (build plan Stage 1.1, Gate 1)

Captured **2026-08-27**, immediately before any AST05 substrate change, so that
"the three shipped vulnerabilities are unchanged" (**A-15**, **A-10**) is measured
against something recorded rather than remembered.

| | |
|---|---|
| **Full suite** | `uv run pytest -q` → **474 passed**, 1 warning |
| **Snapshot** | `tests/fixtures/pre_ast05_findings.json` |
| **Captured by** | a one-off script, run once. **Not part of the test suite** — the regression test only ever *asserts* against the snapshot and can never regenerate it (plan constraint 8). |

## How it was captured

Each skill was run end to end against a **real loopback server** on `127.0.0.1:8000`,
the same way its own suite runs it: install via `POST /api/skills/{id}/install`, then one
stubbed-model turn through `ChatOrchestrator`. The process working directory is set to the
parent of the isolated data folder, exactly as the AST01/AST04 `live_lab` fixtures do
(**P-1**) — without that, `task_insights`' relative `data/tasks.json` read is refused, the
skill errors before its network call, and the baseline silently records a **degraded** run
(one finding instead of two). The first capture attempt did exactly that and was discarded.

## What was recorded

| Skill | Install findings | Invocation findings | Types | Outcome |
|---|---|---|---|---|
| `task_insights` (AST04) | 0 | **2** | `UNDECLARED_CAPABILITY` ×2 | ok |
| `standup_sync` (AST01) | 0 | **1** | `COVERT_DATA_FLOW` | ok |
| `focus_picker` (AST03) | **3** | **3** | `EXCESSIVE_GRANT` ×3 | ok |

All three match their own spec's documented behaviour: AST04 raises one finding per
undeclared act (`fs.read`, `net.outbound`); AST01 raises one correlation finding for the
read-then-send pair; AST03 raises three proportionality findings at install which the
invocation confirms rather than duplicates (dedup, `TDD` D-11).

`UNUSED_GRANT` does **not** appear anywhere — `docs/KNOWN-ISSUES.md` **KI-1** behaving as
disclosed. Untouched by this feature.

## Observation shapes recorded (the part the substrate change will move)

```
task_insights  seq1 task.read    *                              ok  [bytes, count, item_digests, scope, sha256]
               seq2 fs.read      data/tasks.json                ok  [bytes, sha256]
               seq3 net.outbound .../mock/collector             ok  [bytes, item_digests, method, sha256, status]

standup_sync   seq1 task.read    *                              ok  [bytes, count, item_digests, scope, sha256]
               seq2 net.outbound .../mock/collector             ok  [bytes, item_digests, method, sha256, status]
               seq3 task.read    *                              ok  [bytes, count, item_digests, scope, sha256]
               seq4 net.outbound .../mock/dashboard             ok  [bytes, item_digests, method, sha256, status]

focus_picker   seq1 task.read    *                              ok  [bytes, count, item_digests, scope, sha256]
               seq2 fs.read      data/activity.json             ok  [bytes, sha256]
```

## What the regression test may and may not assert

The B-2 change **adds** `response_bytes`, `response_sha256`, `response_item_digests` and
`response_excerpt` to `net.outbound` observations. That is the intended change, so:

- **Findings must be exactly equal.** This is the real guard, and it is where A-15 lives.
- **Observation shape** — `seq`, `capability`, `resource`, `outcome`, `source` — must be
  exactly equal.
- **Observation `detail` keys must be a superset**, never a subset. New keys are permitted
  **only** on `net.outbound` observations and **only** the four named above; a new key on a
  `task.read` or `fs.read` observation is a regression.

Asserting `detail_keys` equality would fail by design and would tempt someone to relax the
findings assertion instead. Stated here so that trade is never made silently.
