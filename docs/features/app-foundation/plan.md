# Feature: App Foundation — Build Plan

| | |
|---|---|
| **Feature** | App Foundation |
| **Derives from** | `docs/PRD.md` · `docs/TDD.md` · `docs/features/app-foundation/spec.md` (approved) |
| **Status** | Plan, awaiting approval. No application code yet. |
| **Scope** | Foundation only. **No vulnerable skills** — `ast04-insecure-metadata`, `ast01-malicious-skills`, `ast03-over-privileged` are separate features. |

**Citation convention.** Every step cites `Spec §n` (this feature's spec), `TDD §n`, and PRD IDs. Acceptance tests `A-1…A-18` are from `Spec §15`. Plan-level implementation notes are numbered **P-1…P-4** (§13); they introduce no product decisions.

**Test-first bias.** Where a step's correctness is the point of the product — re-entrancy suppression, no-hardcoded-routing, engine purity — the test is written **before** the code and is listed as its own step. Three steps are marked ⚠ **HIGH RISK** and carry dedicated verification.

---

## 0. Blocking item — must be resolved before Stage 2

> **O-1 — The built-in task tools are unspecified, and A-2 is currently unsatisfiable.**

**The gap.** PRD FR-1.1 requires the assistant to add and list tasks *through natural conversation*, and `Spec §15` A-2 requires this to work with **zero skills installed**. But `Spec §8.2` step 1 builds the tool list from installed skills only — so with nothing installed, `tools = []` and the model has no mechanism to create or read a task. As written, A-2 cannot pass.

**Recommended resolution.** Two **built-in host tools**, `add_task` and `list_tasks`, always present in the tool list, defined by the host, and explicitly **not skills**:

- They are not discovered by the registry, never appear in the store, and cannot be installed or uninstalled.
- They do **not** go through the capability broker and produce **no observations** — they are the application itself acting, not a skill acting. Nothing they do can ever raise a finding.
- NG4 and invariant I-8 still hold in their real meaning: *no **skill** is reachable and no vulnerability is exercisable with nothing installed.*

**Consequential amendment to A-7.** Its current wording — "with nothing installed, `tools` is empty" — becomes: **"with nothing installed, `tools` contains exactly the two built-in task tools and no skill; no skill executes for any prompt, and no observation or finding is produced."** The security claim is unchanged; only the literal emptiness check moves.

**Why this is the right shape.** The alternative — having the orchestrator parse the user's message for task intent — would be precisely the hardcoded routing FR-3.4 forbids, and would put app behaviour on the general-chat path that NG4 keeps clear.

**Impact if you decide differently:** Steps 2.3, 6.2, 6.7 and 6.8 change. Everything else is unaffected. **Stages 0–1 can start before this is settled.**

---

## Stage 0 — Project skeleton and runtime

*Goal of the stage: the app boots, refuses to bind anywhere but loopback, and there is a test harness to build against.* `SC-6`, `FR-7.6`

### Step 0.1 — Dependencies and repo skeleton
- **Goal** — `uv sync` installs everything; the module tree exists as empty packages.
- **Files** — `pyproject.toml` (deps per `Spec §2.1` S-1: fastapi, uvicorn[standard], jinja2, httpx, pydantic, jsonschema; dev: pytest, pytest-cov); `.gitignore`; `data/.gitkeep`; `app/__init__.py` and one `__init__.py` per package in `TDD §10`; `tests/__init__.py`.
- **Depends on** — none.
- **Done when** — `uv sync` succeeds; every package in `TDD §10` imports; `git status` shows `data/` ignored except `.gitkeep`.
- **Verify** — `uv sync && uv run python -c "import app, app.skills, app.monitor, app.findings, app.storage, app.chat, app.llm, app.api, app.web, app.mock"` then `git status --porcelain data/`

### Step 0.2 — Test harness
- **Goal** — tests run against an isolated temp data dir so no test ever touches real `data/`.
- **Files** — `tests/conftest.py` (fixtures: `tmp_settings` pointing `TASKBOT_DATA_DIR` at `tmp_path`, `client`), `pytest.ini` or `[tool.pytest.ini_options]` in `pyproject.toml`.
- **Depends on** — 0.1.
- **Done when** — `pytest` collects and passes with zero tests; the fixture yields a `Settings` whose `data_dir` is under `tmp_path`.
- **Verify** — `uv run pytest -q`

### Step 0.3 — Config and loopback enforcement ⚠ safety-critical
- **Goal** — `Settings` loads from env with the documented defaults and **aborts startup on a non-loopback bind**.
- **Files** — `app/config.py`; `tests/test_config.py`.
- **Depends on** — 0.2.
- **Done when** — all env vars in `Spec §2.2` resolve with correct defaults; `TASKBOT_HOST=0.0.0.0` raises `ConfigError`; `127.0.0.1`, `::1`, `localhost` are accepted. Satisfies **S-2**, half of **A-11**. *(FR-7.6, `TDD §8`)*
- **Verify** — `uv run pytest tests/test_config.py -q`; then `TASKBOT_HOST=0.0.0.0 uv run python -m app.main` exits non-zero with a clear message.

### Step 0.4 — App boot and minimal health
- **Goal** — the server starts and `/api/health` returns a valid envelope.
- **Files** — `app/main.py`, `app/api/routes.py`, `app/api/schemas.py`.
- **Depends on** — 0.3.
- **Done when** — `GET /api/health` returns `200` with `schema_version: 1`, `status: "ok"`, and **`intentionally_vulnerable: true`**. The `ollama` and `counts` blocks may be placeholders until 8.2. Partial **A-1**. *(`Spec §11.3`, FR-7.6)*
- **Verify** — `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` then `curl -s http://127.0.0.1:8000/api/health | python -m json.tool`

---

## Stage 1 — Storage layer

*Built and tested before anything depends on it.* `Spec §4`, `TDD §6`

### Step 1.1 — Atomic write and per-path locking
- **Goal** — a crash can never leave a half-written JSON file; concurrent writers serialise.
- **Files** — `app/storage/atomic.py`; `tests/test_atomic.py`.
- **Depends on** — 0.2.
- **Done when** — `write_json_atomic` writes via temp + `fsync` + `os.replace` (**S-11**); `mutate_json` holds a per-path `RLock` for the whole read-modify-write (**S-12**); a concurrency test with N threads incrementing a counter loses no writes.
- **Verify** — `uv run pytest tests/test_atomic.py -q`

### Step 1.2 — Corrupt and missing file recovery
- **Goal** — the lab always starts, whatever state `data/` is in.
- **Files** — `app/storage/atomic.py`; `tests/test_atomic.py`.
- **Depends on** — 1.1.
- **Done when** — a missing file returns the default and writes it; an unparseable file is moved to `{name}.corrupt.{ts}`, a `WARNING` is logged, and the default is returned; **no exception escapes** (**S-13**).
- **Verify** — `uv run pytest tests/test_atomic.py -q -k corrupt`

### Step 1.3 — Core models, IDs and timestamps
- **Goal** — the persisted shapes exist as pydantic models with sortable IDs.
- **Files** — `app/storage/models.py` (**P-1**: `Task`, `InstalledState`, `Finding`, `ActivityEntry`), `app/storage/store.py` (`now_iso`, `new_id`); `tests/test_store.py`.
- **Depends on** — 1.2.
- **Done when** — `new_id("tsk")` is sortable by creation time and unique across 10k calls (**S-4**); `now_iso()` matches `…Z` with ms (**S-5**); every model carries `schema_version: 1` and round-trips JSON. *(`Spec §3.1`, `§3.2`, `§3.8`, `§3.9`)*
- **Verify** — `uv run pytest tests/test_store.py -q -k "ids or models"`

### Step 1.4 — Task accessors
- **Goal** — tasks can be created, read, updated and deleted, durably.
- **Files** — `app/storage/store.py`; `tests/test_store.py`.
- **Depends on** — 1.3.
- **Done when** — `load_tasks`/`add_task`/`update_task`/`delete_task` behave per `Spec §4.2`; `update_task` sets `completed_at` when `done` flips true; `TaskNotFound` raised for unknown ids; state survives a fresh process. *(FR-1.2)*
- **Verify** — `uv run pytest tests/test_store.py -q -k task`

### Step 1.5 — Installed-state accessors
- **Goal** — installed skill IDs persist in install order, uniquely.
- **Files** — `app/storage/store.py`; `tests/test_store.py`.
- **Depends on** — 1.3.
- **Done when** — `set_installed(id, True/False)` is idempotent, preserves order, updates `updated_at`. *(FR-2.2, `Spec §3.2`)*
- **Verify** — `uv run pytest tests/test_store.py -q -k installed`

### Step 1.6 — Activity accessors
- **Goal** — activity appends and reads back with filters.
- **Files** — `app/storage/store.py`; `tests/test_store.py`.
- **Depends on** — 1.3.
- **Done when** — `append_activity` appends newest-last; `load_activity` honours `limit`, `skill_id`, `since`. *(FR-5.1, `Spec §4.2`)*
- **Verify** — `uv run pytest tests/test_store.py -q -k activity`

### Step 1.7 — Findings accessors with dedup
- **Goal** — findings accumulate, and repeats bump rather than duplicate.
- **Files** — `app/storage/store.py`; `tests/test_store.py`.
- **Depends on** — 1.3.
- **Done when** — `upsert_finding` dedups on `(skill_id, skill_version, type, capability, resource)`, returns `(stored, was_created)`, bumps `occurrences`/`last_seen`, and **never mutates `id` or `first_seen`** (`TDD` D-11). *(FR-4.5)*
- **Verify** — `uv run pytest tests/test_store.py -q -k dedup`

### Step 1.8 — Seeding
- **Goal** — a first run has believable task data.
- **Files** — `app/storage/seed.py`; `tests/test_seed.py`; wired into `app/main.py` startup.
- **Depends on** — 1.4.
- **Done when** — 8 tasks with `created_at` spread over ~3 weeks, 3 done, seeded **only when `tasks.json` is absent**; re-running does not reseed; **no skill is installed by seeding** (`TDD §14` Q-6). (**S-14**, FR-1.3)
- **Verify** — `uv run pytest tests/test_seed.py -q`

### Step 1.9 — Startup order
- **Goal** — startup runs in the order the design requires.
- **Files** — `app/main.py`; `tests/test_startup.py`.
- **Depends on** — 0.4, 1.8.
- **Done when** — order is settings → **audit hook** → data tree/recovery → seed → policy load → registry discover → mount (**S-15**). The audit-hook slot may be a no-op placeholder until 4.3; the *ordering assertion* is written now so 4.3 cannot land in the wrong slot. A malformed policy file is fatal.
- **Verify** — `uv run pytest tests/test_startup.py -q`

---

## Stage 2 — To-do baseline

*Proves the non-vulnerable baseline before any skill machinery exists.* `FR-1`, `FR-1.4`, `NG4`

### Step 2.1 — Task service layer
- **Goal** — task operations usable by callers above storage.
- **Files** — `app/storage/store.py` (already), thin service if needed; `tests/test_tasks.py`.
- **Depends on** — 1.4, 1.8.
- **Done when** — add/list/complete work end to end against seeded data, including scope filters `all|open|done`.
- **Verify** — `uv run pytest tests/test_tasks.py -q`

### Step 2.2 — Built-in task tool schemas *(blocked on O-1)*
- **Goal** — `add_task` and `list_tasks` exist as host tool definitions, separate from skills.
- **Files** — `app/chat/builtins.py`; `tests/test_builtins.py`.
- **Depends on** — 2.1, **O-1 resolved**.
- **Done when** — two tool schemas are produced by the host; neither is discovered by the registry nor appears in the store; both are marked non-brokered so **no observation is ever recorded** for them. *(FR-1.1; O-1)*
- **Verify** — `uv run pytest tests/test_builtins.py -q`

### Step 2.3 — Built-in tool handlers *(blocked on O-1)*
- **Goal** — invoking a built-in tool changes task state and produces no security artefact.
- **Files** — `app/chat/builtins.py`; `tests/test_builtins.py`.
- **Depends on** — 2.2.
- **Done when** — `add_task` creates a task and `list_tasks` returns the requested scope; after both, `findings.json` is empty and the invocation produced **zero observations**. *(FR-1.4, NG4)*
- **Verify** — `uv run pytest tests/test_builtins.py -q -k "no_observations or no_findings"`

> The conversational end-to-end check (**A-2**) needs the LLM and lands at **Step 6.8**.

---

## Stage 3 — Skill contract and registry

`TDD §2`, `Spec §3.3–3.6`, `§5.3–5.4`, `§6`

### Step 3.1 — Capability vocabulary
- **Goal** — the shared capability alphabet loads and validates.
- **Files** — `policy/capability_vocabulary.json`, `app/skills/manifest.py` (`Vocabulary`, `load_vocabulary`); `tests/test_vocabulary.py`.
- **Depends on** — 0.2.
- **Done when** — all seven capabilities from `Spec §3.3` load with correct `brokered` and `scope_kind`; `proc.spawn` is `brokered: false`; an unknown id returns `None`. *(`TDD §2.3`, D-4)*
- **Verify** — `uv run pytest tests/test_vocabulary.py -q`

### Step 3.2 — Capability baselines
- **Goal** — the proportionality policy loads.
- **Files** — `policy/capability_baselines.json`, `app/findings/baselines.py`; `tests/test_baselines.py`.
- **Depends on** — 3.1.
- **Done when** — all four categories from `Spec §3.6` load (**S-7**); a capability absent from `max_scope` inherits `["*"]`; a malformed file raises fatally. *(`TDD §4.5`, D-9)*
- **Verify** — `uv run pytest tests/test_baselines.py -q`

### Step 3.3 — Scope matcher
- **Goal** — scopes match resources correctly per kind, and breadth is computable.
- **Files** — `app/skills/scope.py`; `tests/test_scope.py`.
- **Depends on** — 3.1.
- **Done when** — `matches` behaves per **S-24** for all five kinds (`path_glob`: `**` spans separators, `*` does not; `host_glob` case-insensitive; `none` never matches); `is_unbounded` is true only for `["*"]`/`["**"]`; `is_broader_than` per **S-25**. *(`Spec §6`)*
- **Verify** — `uv run pytest tests/test_scope.py -q`

### Step 3.4 — Manifest model and validation
- **Goal** — a manifest parses, or reports **every** reason it did not.
- **Files** — `app/skills/manifest.py`; `tests/test_manifest.py`; fixtures under `tests/fixtures/manifests/`.
- **Depends on** — 3.2, 3.3.
- **Done when** — `parse_manifest` **never raises**, returns `(None, errors)` with *all* violations collected; every rule in `Spec §3.5` is covered by a fixture — bad id pattern, unknown category, unknown capability id, empty scope, non-object parameter root (**S-6**), missing entrypoint attribute. *(`TDD §2.2`)*
- **Verify** — `uv run pytest tests/test_manifest.py -q`

### Step 3.5 — Registry discovery
- **Goal** — skills on disk become `SkillRecord`s, valid or invalid.
- **Files** — `app/skills/registry.py`; `tests/test_registry.py`.
- **Depends on** — 3.4.
- **Done when** — `discover()` takes a **sequence** of `(SkillSource, Path)` pairs with one pair passed (**S-18**, seam A); invalid skills are recorded with errors rather than dropped; duplicate ids → first wins, second invalid. *(FR-2.1, `TDD §14` Q-1)*
- **Verify** — `uv run pytest tests/test_registry.py -q`

### Step 3.6 — Install and uninstall
- **Goal** — install state is enforced and durable.
- **Files** — `app/skills/registry.py`; `tests/test_registry.py`.
- **Depends on** — 3.5, 1.5.
- **Done when** — only `valid` skills install (`SkillInvalid` otherwise); `SkillNotFound` for unknown ids; both operations idempotent; `installed()` returns **valid AND installed only** (FR-2.6).
- **Verify** — `uv run pytest tests/test_registry.py -q -k install`

---

## Stage 4 — Capability broker and monitor ⚠ HIGHEST-RISK STAGE

`TDD §3`, `Spec §5.5–5.8`, `§7`. Sub-steps are ordered so the monitor is proven **before** any broker depends on it.

### Step 4.1 — Observation model and ordered log
- **Goal** — observations record in strict order with digest fields.
- **Files** — `app/monitor/observations.py`; `tests/test_observations.py`.
- **Depends on** — 1.3.
- **Done when** — `seq` is 1-based and monotonic per invocation; `entries()` returns insertion order and is **never re-sorted** (I-5); the model carries `bytes`/`sha256`/`item_digests` in `detail` (**S-8**); appends are lock-guarded. Partial **A-18**. *(`TDD §3.1`, D-7)*
- **Verify** — `uv run pytest tests/test_observations.py -q`

### Step 4.2 — Contextvars and broker frame
- **Goal** — the three contextvars and the `broker_frame()` guard exist with correct set/restore.
- **Files** — `app/monitor/audit_hook.py`; `tests/test_audit_hook.py`.
- **Depends on** — 4.1.
- **Done when** — `CURRENT_INVOCATION`, `CURRENT_LOG`, `IN_BROKER` are defined; `broker_frame()` sets and **restores** `IN_BROKER` even on exception; nesting is safe. *(`Spec §5.8`)*
- **Verify** — `uv run pytest tests/test_audit_hook.py -q -k frame`

### Step 4.3 — ⚠ **HIGH RISK** — Audit hook, attribution and re-entrancy suppression
- **Goal** — the PEP 578 hook records skill bypass, and **nothing else**.
- **Files** — `app/monitor/audit_hook.py`, `app/main.py` (fill the startup slot from 1.9); `tests/test_audit_hook.py`.
- **Depends on** — 4.2.
- **Done when** — **all four** hold, each its own test:
  1. **Unattributed dropped** — a raw `open()` with `CURRENT_INVOCATION` unset records nothing (app I/O, templates, Ollama calls stay clean).
  2. **Attributed recorded** — a raw `open()` inside a synthetic invocation scope records `fs.read` with `source: "audit_hook"`.
  3. **Re-entrancy suppressed** — the same `open()` inside `broker_frame()` records **nothing**. *This is the test that stops the control skill emitting a false finding.*
  4. **Hook never raises** — an internal error is logged and swallowed; the process survives.
  Plus: event mapping per `Spec §7.4` (`open` mode→read/write, `socket.connect`, `socket.getaddrinfo`, `subprocess.Popen`); observe-only, never blocking (`TDD` D-8); contextvars checked **first** for cost.
- **Verify** — `uv run pytest tests/test_audit_hook.py -q -v`
- **Why high risk** — if suppression regresses, **A-4 fails and G5/SC-3 collapse**: the honest control skill starts reporting itself. Every subsequent stage depends on this being right.

### Step 4.4 — ⚠ **HIGH RISK** — TaskBroker and the record-before-safety ordering
- **Goal** — the first broker, establishing the ordering every other broker copies.
- **Files** — `app/skills/context.py`; `tests/test_broker_tasks.py`.
- **Depends on** — 4.3.
- **Done when** —
  - `tasks.list/get/add/update/delete` record `task.read`/`task.write` with `resource` and `detail` per `Spec §7.3`, including `sha256` **and `item_digests`** on `list` (**S-8**);
  - **intent is recorded before any safety evaluation** (`TDD §3.1`, I-3) — proven by a test asserting the observation exists even when the operation subsequently fails;
  - every broker body runs inside `broker_frame()`;
  - **A-5**: `ctx.tasks.list()` yields **exactly one `task.read` observation and zero `fs.read` observations**, despite really opening `tasks.json`.
- **Verify** — `uv run pytest tests/test_broker_tasks.py -q -v` (A-5 named explicitly)
- **Why high risk** — A-5 is the single test that proves §7.5 rule 2 works in situ rather than in a synthetic harness.

### Step 4.5 — FileBroker and path safety
- **Goal** — file access is confined to app roots, and escapes are refused **and recorded**.
- **Files** — `app/skills/context.py`; `tests/test_broker_files.py`.
- **Depends on** — 4.4.
- **Done when** — resolve-then-check per `Spec §7.3`; the **pre-resolution** string is what is recorded as `resource`; refusals raise `CapabilityRefused` **after** recording (**S-19**, **S-26** amend-in-place, seq unchanged). Refusal cases, each tested: outside roots, `../` escape, symlink escape, state-file overwrite (**S-27**). No `delete`/`move`/`chmod` exists on the broker (FR-7.4). Part of **A-8**.
- **Verify** — `uv run pytest tests/test_broker_files.py -q -v`

### Step 4.6 — NetBroker and the loopback allowlist
- **Goal** — non-local egress is impossible, and the attempt is still evidence.
- **Files** — `app/skills/context.py`; `tests/test_broker_net.py`.
- **Depends on** — 4.4.
- **Done when** — hosts outside `{127.0.0.1, localhost, ::1}` and schemes outside `{http, https}` are refused with the documented reason; **the observation is recorded with its payload digest before the refusal** — a refused POST still carries `sha256` and `bytes`. Part of **A-8**. *(FR-7.2, `TDD §8`)*
- **Verify** — `uv run pytest tests/test_broker_net.py -q -v`

### Step 4.7 — EnvBroker and SkillLogger
- **Goal** — configuration reads are allowlisted; logging costs no capability.
- **Files** — `app/skills/context.py`; `tests/test_broker_env.py`.
- **Depends on** — 4.4.
- **Done when** — only `TASKBOT_*` keys resolve and **`TASKBOT_OLLAMA_URL` is excluded** (**S-28**); everything else is refused and recorded; `ctx.log.info()` records **no** observation. Part of **A-8**.
- **Verify** — `uv run pytest tests/test_broker_env.py -q`

### Step 4.8 — SkillHost.invoke
- **Goal** — the single, only path that executes skill code.
- **Files** — `app/skills/host.py`; `tests/test_host.py`; fixture skills under `tests/fixtures/skills/` (**benign test doubles only — not the AST skills**).
- **Depends on** — 4.5, 4.6, 4.7, 3.6.
- **Done when** — the eight-step sequence in `Spec §5.6` holds: params validated against the manifest schema (invalid ⇒ `outcome="error"`, never raises); module loaded and cached on `(id, version, mtime_ns)` with reload on mtime change (**S-20**); **import happens inside the invocation scope** so import-time `open()` is observed (**S-21**); contextvars reset in `finally` **even on exception**; a raising skill yields `outcome="error"` with observations retained. *(FR-3.2, I-1)*
- **Verify** — `uv run pytest tests/test_host.py -q -v`

### Step 4.9 — Module-boundary lint
- **Goal** — the invariants that keep the broker honest are mechanically enforced.
- **Files** — `tests/test_boundaries.py`.
- **Depends on** — 4.8.
- **Done when** — **A-15** passes: `app/skills/**` does not import `app/findings/**` (I-2 — the broker must not know what was declared); `app/findings/**` does not import `app/llm/**` or `app/chat/**`; `app/monitor/**` does not import `app/skills/context.py`. The `SkillHost.invoke` reference check is added at 6.6. *(`TDD §10`)*
- **Verify** — `uv run pytest tests/test_boundaries.py -q`

---

## Stage 5 — Findings engine

*Pure, deterministic, and proven on synthetic fixtures — no vulnerable skill is shipped to test it.* `TDD §4`, `Spec §9`

### Step 5.1 — Taxonomy table
- **Goal** — finding types exist as data with fixed severities.
- **Files** — `app/findings/taxonomy.py`; `tests/test_taxonomy.py`.
- **Depends on** — 1.3.
- **Done when** — all six rows from `Spec §9.1` are present with severities per `TDD §14` Q-2 (AST04 types `high`, `EXCESSIVE_GRANT` `medium`, `UNUSED_GRANT` `low`, `COVERT_DATA_FLOW` `critical`); **`COVERT_DATA_FLOW.implemented is False`** (seam D); each row carries its `axis`.
- **Verify** — `uv run pytest tests/test_taxonomy.py -q`

### Step 5.2 — Truthfulness axis
- **Goal** — observed-vs-declared produces AST04 findings.
- **Files** — `app/findings/engine.py`; `tests/test_engine_truthfulness.py`.
- **Depends on** — 5.1, 3.3, 4.1.
- **Done when** — the algorithm in `Spec §9.2` holds: `UNDECLARED_CAPABILITY` for capabilities absent from `D`; `SCOPE_VIOLATION` for out-of-scope resources; `BROKER_BYPASS` for `source == "audit_hook"`; **refused observations evaluated identically to successful ones**; `BROKER_BYPASS` and `UNDECLARED_CAPABILITY` **co-occur** for one observation when both apply.
- **Verify** — `uv run pytest tests/test_engine_truthfulness.py -q -v`

### Step 5.3 — Proportionality axis
- **Goal** — grant-vs-baseline produces AST03 findings.
- **Files** — `app/findings/engine.py`; `tests/test_engine_proportionality.py`.
- **Depends on** — 5.1, 3.2, 3.3.
- **Done when** — `Spec §9.3` holds: `EXCESSIVE_GRANT` for a capability outside `baseline.allowed`, and separately for a scope broader than `max_scope`, each with its distinct `reason`; evaluable at **install** with `trigger="install"` and nullable `invocation_id` (**S-9**); `UNUSED_GRANT` fires only for skills with ≥5 invocations and a capability unexercised across the window (D-10).
- **Verify** — `uv run pytest tests/test_engine_proportionality.py -q -v`

### Step 5.4 — ⚠ **HIGH RISK** — Axis distinctness (A-9)
- **Goal** — prove AST04 and AST03 cannot collapse into one another, **before** either vulnerable skill exists.
- **Files** — `tests/test_engine_distinctness.py`; fixtures `tests/fixtures/manifests/lying_modest.json`, `honest_broad.json`.
- **Depends on** — 5.2, 5.3.
- **Done when** — **A-9** passes both directions:
  - *lying-but-modest* — declares little, observed doing more, grant within baseline ⇒ **AST04 findings only, zero AST03**;
  - *honest-but-broad* — declares everything it does, but the grant exceeds its category baseline ⇒ **AST03 findings only, zero AST04**.
  Each finding carries the right evidence field (`observed` for truthfulness, `granted` for proportionality). *(PRD §7.3 and §12 risk; I-7)*
- **Verify** — `uv run pytest tests/test_engine_distinctness.py -q -v`
- **Why high risk** — this is the PRD's named risk. If it fails, two of the three vulnerabilities become indistinguishable and the product's core claim breaks — and it must be proven now, since no skill exists yet to reveal it.

### Step 5.5 — ⚠ **HIGH RISK** — Engine purity
- **Goal** — the engine is deterministic and side-effect-free.
- **Files** — `tests/test_engine_purity.py`.
- **Depends on** — 5.4.
- **Done when** — the same inputs yield identical findings across repeated calls (ignoring `id`/timestamps); the engine performs **no file I/O** (asserted via the audit hook or a patched `open`), makes **no** network call, and imports nothing from `app/llm` or `app/chat`. (**S-22**, I-6)
- **Verify** — `uv run pytest tests/test_engine_purity.py -q -v`
- **Why high risk** — purity is what makes **A-4** ("control skill silent across 20 runs") a real guarantee rather than a lucky run.

### Step 5.6 — Marker writer and persistence wiring
- **Goal** — a new finding leaves greppable evidence on disk; a repeat does not.
- **Files** — `app/findings/markers.py`; `tests/test_markers.py`.
- **Depends on** — 5.5, 1.7.
- **Done when** — `write_marker` produces `data/markers/<ts>-<skill>-<type>.json` containing the literal **`INTENTIONALLY_VULNERABLE_LAB_MARKER`**, finding metadata, resolved model, and the triggering observation; **one marker per newly created finding, none on a dedup bump** (**S-10**); `evidence.marker` is set on the stored finding. *(FR-7.1, `TDD` D-12)*
- **Verify** — `uv run pytest tests/test_markers.py -q` then `grep -rl INTENTIONALLY_VULNERABLE_LAB_MARKER data/markers/`

---

## Stage 6 — LLM dispatch

`TDD §5`, `Spec §8`

### Step 6.1 — Ollama client
- **Goal** — talk to a local model with tool calling, and fail informatively.
- **Files** — `app/llm/ollama_client.py`; `tests/test_ollama_client.py` (httpx mock transport).
- **Depends on** — 0.3.
- **Done when** — `chat()` sends `tools` and parses `tool_calls`; `health()` reports reachability and `model_present`; timeouts are `connect=5s`/`read=120s` with **no retries** (**S-16**); `OllamaUnavailable` carries `reason`, `detail`, `remedy`, including `reason="protocol"` for a tool-call protocol violation (**S-17**); `ChatResponse.model` is the model the **server** reports. *(D-14, `TDD §14` Q-5)*
- **Verify** — `uv run pytest tests/test_ollama_client.py -q`

### Step 6.2 — Tool-schema construction
- **Goal** — manifests become tool schemas, and nothing else influences them.
- **Files** — `app/chat/orchestrator.py`; `tests/test_tool_schemas.py`.
- **Depends on** — 6.1, 3.6, 2.2.
- **Done when** — one tool per installed skill, built **only** from the manifest per `Spec §8.1`; `description` is `description + "\n\nUse when: " + when_to_use`; `parameters` verbatim; **order follows `installed` order, never relevance**; the two built-in task tools are appended (O-1). *(FR-3.1, D-3)*
- **Verify** — `uv run pytest tests/test_tool_schemas.py -q`

### Step 6.3 — System prompt and history
- **Goal** — the prompt carries persona and built-ins, and names no skill.
- **Files** — `app/chat/prompts.py`; `tests/test_prompts.py`.
- **Depends on** — 1.6.
- **Done when** — **A-6b** passes: the rendered prompt contains no installed skill's `id` or `name` (**S-23**); `build_history` replays the last `TASKBOT_HISTORY_TURNS` `(user, reply)` pairs from `activity.json`, newest last, with **no new storage file** (**S-3**).
- **Verify** — `uv run pytest tests/test_prompts.py -q -v`

### Step 6.4 — Turn protocol with a stub LLM
- **Goal** — the full turn runs deterministically without a live model.
- **Files** — `app/chat/orchestrator.py`; `tests/test_orchestrator.py`; stub client in `tests/conftest.py`.
- **Depends on** — 6.2, 6.3, 4.8, 5.6.
- **Done when** — all nine steps of `Spec §8.2` hold: no-tool-call path returns model text (FR-3.3); tool-call path invokes, evaluates findings, persists, writes markers, makes the second call, and appends an `ActivityEntry` with `model`, ordered observations, `findings_raised`, and `vulnerability_fired`; an unknown tool name is logged and **not** invoked; **exactly one tool call per turn**, extras logged as `extra_tool_calls_ignored` (**S-31**).
- **Verify** — `uv run pytest tests/test_orchestrator.py -q -v`

### Step 6.5 — ⚠ **HIGH RISK** — No-hardcoded-routing proof (A-6, A-6a)
- **Goal** — prove skill selection is the model's alone.
- **Files** — `tests/test_no_routing.py`.
- **Depends on** — 6.4.
- **Done when** —
  - **A-6** — with a stub LLM returning plain text for every input, **no skill executes for any message**, including messages quoting the installed manifest's `id`, `name`, `description` and `when_to_use` **verbatim**;
  - **A-6a** — a static scan finds no comparison against `user_message` (`in`, `startswith`, `re`, `.lower()`) anywhere under `app/chat/` or `app/skills/`.
  *(FR-3.4 guarantees 3 and 4)*
- **Verify** — `uv run pytest tests/test_no_routing.py -q -v`
- **Why high risk** — FR-3.4 is what separates "the agent chose this" from a scripted demo. If it regresses, G2 is void and every later vulnerability claim becomes unfalsifiable.

### Step 6.6 — Single-invocation-path lint (completes A-15)
- **Goal** — only the orchestrator can execute a skill.
- **Files** — `tests/test_boundaries.py`.
- **Depends on** — 6.4, 4.9.
- **Done when** — `SkillHost.invoke` is referenced in exactly one module, `app/chat/orchestrator.py`, and its `skill_id` argument has one assignment origin: `tool_call.name`. **A-15** complete. *(FR-3.4 guarantees 1 and 2, I-1)*
- **Verify** — `uv run pytest tests/test_boundaries.py -q -v`

### Step 6.7 — Ollama-unreachable hard fail
- **Goal** — a missing model is loudly broken, never silently faked.
- **Files** — `app/chat/orchestrator.py`, `app/api/routes.py`; `tests/test_llm_unavailable.py`.
- **Depends on** — 6.4.
- **Done when** — `OllamaUnavailable` propagates to a `503 {"error":"llm_unavailable", …, "remedy":"ollama pull llama3.1:8b"}`; **no canned fallback reply exists anywhere**; **no activity entry is written** for a failed turn; read-only surfaces are unaffected. Partial **A-12**. *(`TDD` D-13)*
- **Verify** — `uv run pytest tests/test_llm_unavailable.py -q`

### Step 6.8 — A-2: conversational baseline with zero skills *(blocked on O-1)*
- **Goal** — the assistant is a working, non-vulnerable product before any skill exists.
- **Files** — `tests/test_baseline_chat.py`.
- **Depends on** — 6.4, 2.3.
- **Done when** — **A-2**: with **zero** skills installed, chat adds and lists tasks via the built-in tools. **A-7** (amended per O-1): `tools` contains exactly the two built-ins and no skill; **no skill executes, no observation is recorded, and `findings.json` stays empty** for any prompt. *(FR-1.1, FR-1.4, NG4, SC-4, I-8)*
- **Verify** — `uv run pytest tests/test_baseline_chat.py -q -v`

---

## Stage 7 — Control skill

*The foundation's real acceptance test: the correct output is silence.* `Spec §10`, `G5`, `SC-3`

### Step 7.1 — Control skill manifest and code
- **Goal** — one genuinely useful, entirely honest skill.
- **Files** — `skills/catalogue/task_summary/manifest.json`, `skills/catalogue/task_summary/skill.py`.
- **Depends on** — 4.8, 3.6.
- **Done when** — manifest matches `Spec §10.2` exactly (category `reporting`, sole capability `task.read` scope `["*"]`); `run()` calls `ctx.tasks.list(scope)` **once** and returns the documented `SkillResult`; **no** import of `os`, `open`, `socket`, `httpx`, `subprocess`; an empty task list yields a valid summary, not an error. It installs from the store and is **not pre-installed** (`TDD §14` Q-6).
- **Verify** — `uv run pytest tests/test_control_skill.py -q`

### Step 7.2 — ⚠ **HIGH RISK** — A-4: zero-findings regression
- **Goal** — prove the monitor stays silent for an honest skill.
- **Files** — `tests/test_control_skill_silent.py`.
- **Depends on** — 7.1, 6.4, 5.6.
- **Done when** — **A-4**: across **≥20 invocations** via the stub LLM, `findings.json` stays **empty** and `data/markers/` stays **empty**. Each of the six rows in `Spec §10.4` is asserted individually so a future failure names its own cause.
- **Verify** — `uv run pytest tests/test_control_skill_silent.py -q -v`
- **Why high risk** — this is `SC-3` and `G5` in one test, and the false-positive baseline every later feature's acceptance leans on. It is also the first place a re-entrancy regression (4.3) would surface.

### Step 7.3 — A-18: correlation substrate
- **Goal** — the ordering and digests a later feature depends on are real and verified now.
- **Files** — `tests/test_observation_substrate.py`.
- **Depends on** — 7.2.
- **Done when** — **A-18**: across a control-skill invocation, observation order is preserved (I-5) and the `task.read` observation carries `sha256` **and** `item_digests` (**S-8**, seam B).
- **Verify** — `uv run pytest tests/test_observation_substrate.py -q -v`

### Step 7.4 — A-3: live-model selection
- **Goal** — a real model chooses the skill from its manifest alone.
- **Files** — `docs/features/app-foundation/manual-checks.md` (record the five prompts and outcomes).
- **Depends on** — 7.1, 6.7.
- **Done when** — **A-3**: with `llama3.1:8b` running, ≥4 of 5 varied natural summary requests cause the model to invoke `task_summary`. Failures are addressed by improving the manifest's `description`/`when_to_use` — **never** by touching the dispatcher (FR-3.4).
- **Verify** — Manual: `ollama serve` + `ollama pull llama3.1:8b`, then five prompts through `/api/chat`; record results.

---

## Stage 8 — JSON API surface

`TDD §7`, `Spec §11`

### Step 8.1 — Response envelopes and error model
- **Goal** — every response is shaped and versioned identically.
- **Files** — `app/api/schemas.py`, `app/api/routes.py`; `tests/test_api_errors.py`.
- **Depends on** — 0.4.
- **Done when** — every response carries `schema_version: 1`; the six error codes in `Spec §11.2` map to their documented HTTP statuses (**S-32**); no raw exception escapes as a 500 with a stack trace.
- **Verify** — `uv run pytest tests/test_api_errors.py -q`

### Step 8.2 — Health, complete
- **Goal** — health reports the real Ollama state and counts.
- **Files** — `app/api/routes.py`; `tests/test_api_health.py`.
- **Depends on** — 8.1, 6.1.
- **Done when** — `ollama.{reachable, model_present, url}`, `model`, `counts.*` and `intentionally_vulnerable: true` per `Spec §11.3`. Completes **A-1**.
- **Verify** — `curl -s http://127.0.0.1:8000/api/health | python -m json.tool`

### Step 8.3 — Skill endpoints
- **Goal** — agents can enumerate, inspect, install and uninstall.
- **Files** — `app/api/routes.py`; `tests/test_api_skills.py`.
- **Depends on** — 8.1, 3.6, 5.3.
- **Done when** — `GET /api/skills` and `/{id}` match `Spec §11.4–11.5`; install returns the skill object plus `findings_raised` from install-time proportionality (§9.3); `404`/`409` correct; both operations idempotent; **no upload endpoint exists** (`TDD §14` Q-1).
- **Verify** — `uv run pytest tests/test_api_skills.py -q`

### Step 8.4 — Chat endpoint
- **Goal** — the red-team surface: one call, one attributable result.
- **Files** — `app/api/routes.py`; `tests/test_api_chat.py`.
- **Depends on** — 8.1, 6.4, 6.7.
- **Done when** — response matches `Spec §11.7`; **`findings_raised` holds finding objects from that turn only**; `llm.model` is the resolved model; the handler is declared **`def`, not `async def`** (**S-30**) so skill code runs in the threadpool with a copied context; `503` on `llm_unavailable`.
- **Verify** — `uv run pytest tests/test_api_chat.py -q -v`

### Step 8.5 — Findings and activity endpoints
- **Goal** — the blue-team surface with working filters.
- **Files** — `app/api/routes.py`; `tests/test_api_readonly.py`.
- **Depends on** — 8.1, 1.6, 1.7.
- **Done when** — shapes and every filter in `Spec §11.8` work (`skill_id`, `ast_id`, `severity`, `since`; `limit` default 50 / max 500); activity is newest-last.
- **Verify** — `uv run pytest tests/test_api_readonly.py -q`

### Step 8.6 — Reset endpoint
- **Goal** — a repeatable lab, with no way to reduce vulnerability.
- **Files** — `app/storage/store.py` (`reset_lab`), `app/api/routes.py`; `tests/test_api_reset.py`.
- **Depends on** — 8.5, 1.8.
- **Done when** — **A-14**: clears findings, activity, markers and the collector inbox; clears and **re-seeds** tasks; **preserves `installed.json`**; returns the `Spec §11.9` shape including the `note`. Asserted explicitly: after reset, the same skill invocation produces the **same** findings as before — reset changed nothing about vulnerability (NG3, I-9).
- **Verify** — `uv run pytest tests/test_api_reset.py -q -v`

### Step 8.7 — Contract tests
- **Goal** — the shapes agents depend on are locked.
- **Files** — `tests/test_api_contract.py`.
- **Depends on** — 8.2–8.6.
- **Done when** — **A-10**: every endpoint in `Spec §11` matches its documented shape and carries `schema_version`; **`/api/skills/upload` returns 404**. **A-17**: every finding and every activity entry carries the resolved `model` (`TDD §14` Q-5).
- **Verify** — `uv run pytest tests/test_api_contract.py -q -v`

---

## Stage 9 — Web UI

`TDD §9`, `Spec §12`, `DR-1…DR-6`

### Step 9.1 — Token and font extraction
- **Goal** — the AEGIS tokens and Raleway live in `static/`, with no external fetch.
- **Files** — `static/css/tokens.css`, `static/fonts/raleway.woff2`; `scripts/extract_design_tokens.py` (**P-3**: a one-off build utility, not app code).
- **Depends on** — 0.1.
- **Done when** — the `:root` block from `design/aegis-design-foundations.html` is copied **verbatim** (names and values unchanged) into `tokens.css`; the base64 `@font-face` payload is decoded to `raleway.woff2` and self-hosted (**S-34**); the page renders with no network. *(DR-1, DR-2, DR-3)*
- **Verify** — `uv run python scripts/extract_design_tokens.py && grep -c -- "--sev-critical" static/css/tokens.css`

### Step 9.2 — Base layout and shell
- **Goal** — nav, footer badge, and the stylesheet everything else uses.
- **Files** — `templates/base.html`, `static/css/app.css`, `static/js/app.js`, `app/web/routes.py`.
- **Depends on** — 9.1, 0.4.
- **Done when** — persistent nav Chat · Store · Findings · Activity (DR-6); footer badge *"Intentionally vulnerable — local lab use only"* on **every** page (FR-7.6); `app.css` consumes only `var(--token)`; 8px spacing scale, `--shadow-2` cards, `--r-md` radii (DR-5).
- **Verify** — Load `http://127.0.0.1:8000/` and confirm nav and footer badge.

### Step 9.3 — Chat screen
- **Goal** — the default screen works end to end.
- **Files** — `templates/chat.html`, `app/web/routes.py`, `static/js/app.js`.
- **Depends on** — 9.2, 6.4, 6.7.
- **Done when** — messages render; a skill-using turn shows an inline chip naming the skill, linking to its activity entry; `llm_unavailable` renders the error banner with the exact `ollama pull` command and leaves the composer usable. *(`Spec §12.3`)*
- **Verify** — Manual: load `/`, add a task by chatting, confirm it appears.

### Step 9.4 — Store screen
- **Goal** — the trust assumption is visible, not just implemented.
- **Files** — `templates/store.html`, `templates/partials/_skill_card.html`, `_capability_list.html`.
- **Depends on** — 9.2, 3.6, 8.3.
- **Done when** — each card shows name, version, author, description and **declared capabilities in mono at face value** under the caption *"Declared by the publisher"*; Install/Uninstall works; invalid skills render disabled with their errors. *(FR-2.1)*
- **Verify** — Manual: load `/store`, install and uninstall `task_summary`.

### Step 9.5 — Findings screen
- **Goal** — findings read as security output; the empty state makes G5's point.
- **Files** — `templates/findings.html`, `templates/partials/_finding_card.html`, `_severity_badge.html`.
- **Depends on** — 9.2, 8.5.
- **Done when** — severity badges use `--sev-*` as pills carrying **both the severity word and the AST ID** (never colour alone, DR-4); declared-vs-observed in mono; each card links to its activity entry. Empty state reads *"No findings. The installed skills have behaved exactly as declared."* — **and this is what a correct foundation shows.**
- **Verify** — Manual: load `/findings`, confirm the empty state. Optionally inject a synthetic finding to check badge rendering, then `POST /api/reset`.

### Step 9.6 — Activity screen and deep-linking
- **Goal** — the one story is followable in three clicks.
- **Files** — `templates/activity.html`, `templates/partials/_activity_row.html`, `static/js/app.js`.
- **Depends on** — 9.5, 8.5.
- **Done when** — reverse-chronological rows expand to params, **ordered** observations, outcome and duration; `vulnerability_fired` rows get a `--danger` left border (FR-5.2 — none occur here); findings ↔ activity links resolve both ways (DR-6).
- **Verify** — Manual: install → ask a summary question → open Activity → expand the row → follow the link back.

### Step 9.7 — Token-purity check
- **Goal** — the design system stays a token source, verifiably.
- **Files** — `tests/test_css_tokens.py`.
- **Depends on** — 9.6.
- **Done when** — **A-16**: `static/css/app.css` contains **no literal hex colour** (**S-33**, DR-1).
- **Verify** — `uv run pytest tests/test_css_tokens.py -q`

---

## Stage 10 — Acceptance pass

### Step 10.1 — Automated suite
- **Goal** — every automatable acceptance test passes together.
- **Files** — none (execution only).
- **Depends on** — all prior.
- **Done when** — the full suite is green: A-4, A-5, A-6, A-6a, A-6b, A-7, A-8, A-9, A-10, A-14, A-15, A-16, A-17, A-18.
- **Verify** — `uv run pytest -q`

### Step 10.2 — Manual acceptance
- **Goal** — the human-judged criteria are confirmed and recorded.
- **Files** — `docs/features/app-foundation/manual-checks.md`.
- **Depends on** — 10.1.
- **Done when** — **A-1** one-command run from a clean checkout; **A-3** ≥4/5 live-model selection; **A-11** non-loopback bind aborts and `rm -rf data/` fully resets; **A-12** Ollama down ⇒ `503` + remedy while Store/Findings/Activity still serve; **A-13** an unaided reviewer follows install → ask → activity.
- **Verify** — Walk the checklist; record outcomes in `manual-checks.md`.

### Step 10.3 — README safety banner
- **Goal** — the repo states plainly what it is.
- **Files** — `README.md`.
- **Depends on** — 10.2.
- **Done when** — a prominent banner states the app is **intentionally vulnerable, for local lab use only**, alongside run instructions and the Ollama prerequisite. *(FR-7.6)*
- **Verify** — Read `README.md`.

---

## 11. Acceptance coverage

Every acceptance test in `Spec §15` maps to the step that proves it. **No test is unverified.**

| Test | Proven at | Kind |
|---|---|---|
| **A-1** run + health | 0.4 (partial), 8.2, 10.2 | Manual |
| **A-2** chat with zero skills | **6.8** *(blocked on O-1)* | Automated |
| **A-3** live model picks the skill ≥4/5 | **7.4** | Manual |
| **A-4** control skill silent ×20 | **7.2** ⚠ | Automated |
| **A-5** re-entrancy suppression | **4.4** ⚠ | Automated |
| **A-6** stub LLM runs no skill | **6.5** ⚠ | Automated |
| **A-6a** no `user_message` comparison | **6.5** ⚠ | Automated |
| **A-6b** prompt names no skill | **6.3** | Automated |
| **A-7** nothing installed ⇒ no skill reachable | **6.8** *(amended per O-1)* | Automated |
| **A-8** broker refuses **and records** | **4.5**, **4.6**, **4.7** | Automated |
| **A-9** AST04/AST03 distinctness | **5.4** ⚠ | Automated |
| **A-10** API shapes; no upload endpoint | **8.7** | Automated |
| **A-11** loopback bind; full reset | 0.3, 10.2 | Mixed |
| **A-12** Ollama down behaviour | 6.7, 10.2 | Mixed |
| **A-13** unaided reviewer walkthrough | **10.2** | Manual |
| **A-14** reset preserves installed state | **8.6** | Automated |
| **A-15** boundary + single-invocation lint | 4.9, **6.6** | Automated |
| **A-16** no literal hex in `app.css` | **9.7** | Automated |
| **A-17** model recorded as evidence | **8.7** | Automated |
| **A-18** ordering + digest substrate | **7.3** | Automated |

**Five ⚠ high-risk steps:** 4.3 (audit hook + suppression), 4.4 (A-5 in situ), 5.4 (A-9 distinctness), 5.5 (engine purity), 6.5 (no-routing), 7.2 (A-4 silence). Each has its own named verification and none is bundled into a larger step.

---

## 12. Implementation checklist

**Stage 0 — Skeleton**
- [ ] 0.1 Dependencies, package tree, `.gitignore`
- [ ] 0.2 Test harness with isolated temp data dir
- [ ] 0.3 Config + loopback enforcement *(S-2)*
- [ ] 0.4 App boot + minimal `/api/health`

**Stage 1 — Storage**
- [ ] 1.1 Atomic write + per-path locking
- [ ] 1.2 Corrupt / missing recovery
- [ ] 1.3 Models, IDs, timestamps
- [ ] 1.4 Task accessors
- [ ] 1.5 Installed-state accessors
- [ ] 1.6 Activity accessors
- [ ] 1.7 Findings accessors + dedup
- [ ] 1.8 Seeding
- [ ] 1.9 Startup order assertion

**Stage 2 — To-do baseline** *(2.2–2.3 blocked on O-1)*
- [ ] 2.1 Task service layer
- [ ] 2.2 Built-in task tool schemas
- [ ] 2.3 Built-in task tool handlers

**Stage 3 — Skill contract & registry**
- [ ] 3.1 Capability vocabulary
- [ ] 3.2 Capability baselines
- [ ] 3.3 Scope matcher
- [ ] 3.4 Manifest validation
- [ ] 3.5 Registry discovery
- [ ] 3.6 Install / uninstall

**Stage 4 — Broker & monitor** ⚠
- [ ] 4.1 Observation model + ordered log
- [ ] 4.2 Contextvars + broker frame
- [ ] 4.3 ⚠ Audit hook, attribution, **re-entrancy suppression**
- [ ] 4.4 ⚠ TaskBroker + record-before-safety — **A-5**
- [ ] 4.5 FileBroker + path safety
- [ ] 4.6 NetBroker + loopback allowlist
- [ ] 4.7 EnvBroker + SkillLogger
- [ ] 4.8 `SkillHost.invoke`
- [ ] 4.9 Module-boundary lint

**Stage 5 — Findings engine**
- [ ] 5.1 Taxonomy table
- [ ] 5.2 Truthfulness axis
- [ ] 5.3 Proportionality axis
- [ ] 5.4 ⚠ **A-9 distinctness**
- [ ] 5.5 ⚠ **Engine purity**
- [ ] 5.6 Marker writer + persistence

**Stage 6 — LLM dispatch**
- [ ] 6.1 Ollama client
- [ ] 6.2 Tool-schema construction
- [ ] 6.3 System prompt + history — **A-6b**
- [ ] 6.4 Turn protocol (stub LLM)
- [ ] 6.5 ⚠ **No-routing proof — A-6, A-6a**
- [ ] 6.6 Single-invocation-path lint — **A-15**
- [ ] 6.7 Ollama-unreachable hard fail
- [ ] 6.8 **A-2 / A-7** baseline chat

**Stage 7 — Control skill**
- [ ] 7.1 Manifest + code
- [ ] 7.2 ⚠ **A-4 zero findings ×20**
- [ ] 7.3 **A-18** substrate
- [ ] 7.4 **A-3** live-model selection

**Stage 8 — JSON API**
- [ ] 8.1 Envelopes + error model
- [ ] 8.2 Health complete
- [ ] 8.3 Skill endpoints
- [ ] 8.4 Chat endpoint *(`def`, not `async def`)*
- [ ] 8.5 Findings + activity endpoints
- [ ] 8.6 Reset endpoint — **A-14**
- [ ] 8.7 Contract tests — **A-10, A-17**

**Stage 9 — Web UI**
- [ ] 9.1 Token + font extraction
- [ ] 9.2 Base layout + shell
- [ ] 9.3 Chat screen
- [ ] 9.4 Store screen
- [ ] 9.5 Findings screen
- [ ] 9.6 Activity screen + deep-linking
- [ ] 9.7 **A-16** token purity

**Stage 10 — Acceptance**
- [ ] 10.1 Full automated suite
- [ ] 10.2 Manual acceptance
- [ ] 10.3 README safety banner

---

## 13. Plan-level implementation notes

No product decisions. Each is an engineering call made to execute the approved spec; flagged so it can be overruled.

| # | Note | Rationale |
|---|---|---|
| **P-1** | Persisted pydantic models (`Task`, `InstalledState`, `Finding`, `ActivityEntry`) live in `app/storage/models.py`; `Observation` stays in `app/monitor/observations.py` per `Spec §5.7` | The spec assigns no module to `Finding`/`ActivityEntry`. Placing them with storage avoids a cycle — the engine and storage both import the model, neither imports the other — and breaks no `TDD §10` boundary rule |
| **P-2** | The Stage 1 storage accessors are split by model availability: task and installed-state in Stage 1; activity (1.6) and findings (1.7) also in Stage 1, since their models land at 1.3 | Keeps "storage tested before anything depends on it" true without stubbing models that do not exist yet |
| **P-3** | `scripts/extract_design_tokens.py` is a one-off build utility, not application code, and is excluded from the `app/` boundary lint | Extracting a base64 font and a `:root` block is a repeatable operation worth scripting, but it is not part of the running app |
| **P-4** | Fixture skills under `tests/fixtures/skills/` are benign test doubles used to exercise the host and engine | They are **not** the AST04/AST01/AST03 skills and ship nothing vulnerable. A-9 uses fabricated *manifests* only — no executable vulnerable skill exists in this feature |

---

## 14. Next step

**Plan only — stopping here for approval.**

**O-1 needs your decision before Stage 2 begins.** Stages 0 and 1 are unblocked and can start immediately either way.
