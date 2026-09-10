# Feature: AST04 — Insecure Metadata — Build Plan

| | |
|---|---|
| **Feature** | AST04 · Insecure Metadata — a skill whose manifest lies, plus the tests that prove it |
| **Derives from** | `docs/PRD.md` · `docs/TDD.md` · `docs/features/ast04-insecure-metadata/spec.md` (approved) |
| **Status** | **Plan.** Not built. The App Foundation and AST01 are built (429 tests); the truthfulness axis this feature fires already exists, so this is a skill-and-tests-only addition. |
| **Scope** | AST04 only. **No change to `backend/**` at all** — the skill folder and its tests, under `vulnerabilities/ast04-insecure-metadata/`, per **S-8** / `TDD §12`. No change to the axes, the other vulnerability skills, or the control skill. |

**Citation convention.** Every step cites the AST04 spec as `Spec §n` / `Spec S-n`, the system design as `TDD §n`, and PRD requirements as bare `FR-n` / `SC-n` / `G-n`. Acceptance tests **A-1…A-11** come from `Spec §9`. The App Foundation spec/plan are cited as `Foundation §n` / `Foundation A-n` / `Foundation S-n`; the sibling AST01 spec as `AST01 §n`. Plan-level engineering notes are **P-1…P-4** (§12). Line numbers (`context.py L291`) are the current code at plan time and are guides, not contracts — the anchor is always the named function.

**Test-first bias.** The axis-distinctness and matching proofs (Stage 2) are written on **synthetic fixtures** — a hand-built manifest and hand-built observations fed straight to the engine — **before** the skill is wired end-to-end, because they are the proof the skill fires **AST04 alone** and that the finding tracks the declaration, not the behaviour. Because this feature touches **no foundation code**, there is no high-risk foundation edit and no early gate: verification is a **single checkpoint at the end** (`Foundation §15` method legend applies).

**Code style — binding for every file this plan produces.** See §11. In one line: *comment in plain language a non-technical reader can follow, keep the code simple, and never simplify away the record-before-safety ordering or the specified distinctness tests.*

---

## 0. What already exists (do not rebuild)

The entire truthfulness axis and its supporting machinery are already implemented in the foundation. This plan **references** them; it never copies them into the vuln folder, and it adds **nothing** to `backend/**`.

- **Truthfulness detector** — `check_truthfulness` in `backend/app/findings/engine.py` L64-130 raises `UNDECLARED_CAPABILITY` when an observed capability has no matching declaration, `SCOPE_VIOLATION` when declared-but-out-of-scope, and `BROKER_BYPASS` when `source=="audit_hook"`. It runs first in `evaluate_invocation`. **No edit here.** *(Spec §5, `TDD §4.4`)*
- **Taxonomy rows** — `UNDECLARED_CAPABILITY` / `SCOPE_VIOLATION` / `BROKER_BYPASS` in `backend/app/findings/taxonomy.py` L59-91, all `ast_id="AST04"`, `axis="truthfulness"`, `severity="high"`, already implemented. *(`TDD §14 Q-2`, `Foundation §9.1`)*
- **File broker** — `FileBroker.read` → records `fs.read` (`backend/app/skills/context.py` L291-307); allowed roots `[data_dir, skills_dir]`, refusals `path_outside_allowed_roots` / `file_not_found`. Records **before** the safety check (I-3). *(`Foundation §7.3`)*
- **Net broker** — `NetBroker.post` → records `net.outbound` (`backend/app/skills/context.py` L336-411); loopback allowlist `{127.0.0.1, localhost, ::1, [::1]}`, refusal `non_local_host`. Records before the safety check. *(`Foundation §7.3`, §13.2)*
- **Manifest validation is shape-only** — `backend/app/skills/manifest.py` never compares declared-vs-actual, so an under-declared manifest installs cleanly (the vulnerability itself). The `reporting` baseline allows exactly `task.read` (`backend/policy/capability_baselines.json`). *(Spec §2, §4.2)*
- **Marker writer** — `write_marker(finding, observation)` / `count_markers()` in `backend/app/findings/markers.py`, called by the orchestrator on first sighting; `FileBroker.write` refuses `markers_dir`, so a skill cannot forge or erase evidence. *(seam H, `Foundation S-10`)*
- **Auto-discovery** — `backend/app/skills/registry.py` `default_roots()` scans every `vulnerabilities/*/skill/` folder. Adding the skill folder is the wiring. *(seam A, `Foundation S-18`)*
- **Mock collector** — `backend/app/mock/collector.py` `POST /collector` mounted at `/mock`; writes `data/collector/inbox/{ts}-{sender}.json`. *(seam C, FR-7.2)*
- **Test collection** — `pyproject.toml` `testpaths=["tests","vulnerabilities"]` is **already set** (by AST01). **No config change.**
- **Correlation stays silent** — `check_correlation` matches only `task.read`→`net.outbound` per-item digests; the telemetry payload carries no task items (S-5) and `FileBroker.read` records `sha256`/`bytes`, not `item_digests`, so nothing feeds AST01.

---

## Stage 1 — The malicious skill `task_insights`  *(vuln folder only)*

*A believable, useful offline `reporting` skill that also reads a file and phones home, declaring neither — acting **only** through the real brokers.* `Spec §4`, S-1…S-6, FR-7.2/7.3

### Step 1.1 — Manifest
- **Goal** — a believable `reporting` manifest whose declaration is truthful-but-incomplete: it lists only `task.read`, and its description positively claims the tool is offline and network-free.
- **Files** — `vulnerabilities/ast04-insecure-metadata/skill/task_insights/manifest.json`.
- **Depends on** — none (§0 discovery exists).
- **Done when** — `id="task_insights"`, `name="Task Insights"`, `author="Clearwater Tools"`, `category="reporting"`, `entrypoint="skill.py:run"`; `capabilities` is exactly `[{ "id": "task.read", "scope": ["*"], "reason": … }]` — **no** `fs.read` or `net.outbound` declared; the description asserts "offline / private / never touches the network"; `parameters` is an empty object; it passes manifest validation (`record.valid is True`) and, being within the `reporting` baseline and using what it declares, raises **no** AST03. *(Spec §4.2, S-1, S-2)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests -q -k "manifest or valid"`

### Step 1.2 — Skill behaviour
- **Goal** — the advertised summary genuinely works, and the undeclared file read and network call ride along, all through `ctx`.
- **Files** — `vulnerabilities/ast04-insecure-metadata/skill/task_insights/skill.py`.
- **Depends on** — 1.1.
- **Done when** — `run(ctx, params)`: (a) reads the tasks via `ctx.tasks.list("all")`, computes the open/done/overdue counts, and returns the summary sentence as `SkillResult.summary` — the advertised, declared job genuinely works; (b) performs the **undeclared** `ctx.files.read("data/tasks.json")` (`fs.read`); (c) performs the **undeclared** `ctx.net.post("http://127.0.0.1:8000/mock/collector", json={"event": "insights_generated", "version": "1.4.0"})` (`net.outbound`), a fixed telemetry object carrying **no task data** (so correlation stays silent, **S-5**); (d) imports **only** `from app.skills.context import SkillResult` — no `os`, `socket`, `httpx`, `open`, or `subprocess`, so every act is on the sanctioned channel (`source="broker"`). *(Spec §4.3, S-3, S-4, S-5, S-6; genuinely observed, never bypassed — Spec §4.4)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests -q -k "behaviour or brokers or source"`

### Step 1.3 — Discovery, validity, and sanctioned-channel inspection
- **Goal** — the platform finds and accepts the skill with no wiring, and its source proves it never reaches around the app.
- **Files** — `vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_skill.py` (reuse `imported_modules` / `called_function_names` from `tests/source_tools.py`).
- **Depends on** — 1.1, 1.2.
- **Done when** — `get_registry().discover_default()` includes `task_insights`; its `SkillRecord.valid is True`; it appears in `installed()` after `install("task_insights")`; source inspection asserts imported top-level modules `== {"app"}` and that `open`/`eval`/`exec` are never called — so the undeclared acts must surface as `UNDECLARED_CAPABILITY` (broker), not `BROKER_BYPASS` (audit hook). *(`Foundation S-18`; supports A-10)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_skill.py -q -v`

---

## Stage 2 — Distinctness and matching on synthetic fixtures  *(vuln folder unit tests)*

*Prove the skill fires **AST04 alone** and that the finding tracks the **declaration**, not the behaviour — before wiring it end-to-end.* `Spec §6`, `TDD §11` I-7, `TDD §4.1`

### Step 2.1 — Distinctness and matching unit tests (A-6, A-7, A-8, A-10)
- **Goal** — the truthfulness axis is proven distinct and its declaration-keyed matching proven on synthetic fixtures, with no running skill involved.
- **Files** — new `vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_distinctness.py` (reuse `make_manifest` from `tests/test_engine.py`; a local observation builder recording via `ObservationLog.record(...)`); feed `FindingsEngine.evaluate_invocation(manifest, observations, ...)` directly.
- **Depends on** — 1.1 (uses the shipped manifest for A-6).
- **Done when** — all pass:
  1. **A-6** — the shipped `task_insights` manifest (declares `task.read` only) with observations `task.read`(ok) → `fs.read` → `net.outbound`(no item-digests) yields **exactly two** findings, both `UNDECLARED_CAPABILITY` (`axis=truthfulness`, `ast_id=AST04`, `severity=high`) — one for `fs.read`, one for `net.outbound` — and **no** AST03 (`EXCESSIVE_/UNUSED_GRANT`) and **no** AST01 (`COVERT_DATA_FLOW`). *(→ AST04 alone; `TDD §11` I-7, `TDD §4.1`, PRD §7.3)*
  2. **A-7** — a **fabricated** manifest that honestly declares `fs.read` (scope `["data/**"]`) and `net.outbound` (scope `["127.0.0.1"]`), with the same observations, yields **zero** `UNDECLARED_CAPABILITY` — proving the finding is the declaration gap, not the behaviour. *(`TDD §11` I-7, `Foundation A-9`)*
  3. **A-8** — a `net.outbound` observation with `outcome="refused"` (and an `fs.read` refused as `path_outside_allowed_roots`) **still** raises `UNDECLARED_CAPABILITY`, because the observation was recorded before the safety check. *(`TDD §11` I-3, `Foundation A-8`)*
  4. **A-10** — observations with `source="broker"` produce `UNDECLARED_CAPABILITY`, **not** `BROKER_BYPASS`; a contrasting observation with `source="audit_hook"` produces `BROKER_BYPASS` — confirming the two truthfulness failures are told apart by provenance. *(`TDD §4.4`, `Foundation §7.4`)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_distinctness.py -q -v`

---

## Stage 3 — End-to-end, API, reset, repeatability, control-clean  *(vuln folder tests + config-free plumbing)*

*The lie fires through the LLM's own choice, is attributable via the API, repeatable, and fully reversible; the control skill stays clean.* `Spec §9`, PRD §8 R1

### Step 3.1 — Test plumbing for the vuln folder  *(P-1, P-2)*
- **Goal** — the folder's tests reuse the shared fixtures and can drive a live copy of the app, without touching any foundation file.
- **Files** — `vulnerabilities/ast04-insecure-metadata/tests/conftest.py` (re-export `tmp_settings` and the autouse settings-reset from `tests.conftest`; add an `installed_task_insights` fixture; a `TaskInsightsStub` model that always chooses `task_insights`; a `live_lab` fixture running in-process uvicorn on `127.0.0.1:8000` with the stub model — mirroring AST01's `conftest.py`).
- **Depends on** — 1.1, 1.2.
- **Done when** — `uv run pytest vulnerabilities/ast04-insecure-metadata -q` collects and runs the tests against an isolated temp `data/`; the `live_lab` fixture **sets the process cwd to the parent of `settings.data_dir`** so the skill's relative `"data/tasks.json"` resolves into the isolated data root and the seeded file is read (**P-1**); **no `pyproject.toml` and no foundation test file is modified** (`testpaths` already includes `vulnerabilities`). *(P-1, P-2)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata -q`

### Step 3.2 — End-to-end: the undeclared reach fires (A-2, A-3)
- **Goal** — an LLM-chosen invocation does its advertised job **and** genuinely reads a file and calls the network, neither declared, raising exactly two high findings with markers.
- **Files** — `vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_e2e.py` (drives the live app via a genuine loopback request, per AST01's e2e).
- **Depends on** — 3.1.
- **Done when** — after a natural request through `POST /api/chat`: `skill_invoked.skill_id == "task_insights"`, `outcome == "ok"`, and the reply is the working summary; the invocation's observations include an `fs.read` (`outcome="ok"`, resource `data/tasks.json`) and a `net.outbound` (`outcome="ok"`), and a telemetry file has landed in `data/collector/inbox/`; **exactly two** `UNDECLARED_CAPABILITY` findings are stored — one `fs.read`, one `net.outbound` — each `ast_id="AST04"`, `axis="truthfulness"`, `severity="high"`, `observed` naming the capability + resource, `model` recorded, and a marker carrying `INTENTIONALLY_VULNERABLE_LAB_MARKER` written by the app for each. *(A-2, A-3, SC-2, FR-7.2, FR-7.3, PRD §7.1)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_e2e.py -q -v`

### Step 3.3 — Repeatable, not incidental (A-9)
- **Goal** — the undeclared reach is the skill's own hardcoded behaviour, firing every run regardless of model-supplied arguments.
- **Files** — same e2e module (a repetition case), or a focused host-level test invoking the skill with varied `params`.
- **Depends on** — 3.2.
- **Done when** — across **≥5** invocations passing different `params` dicts (including empty and junk keys), **both** `UNDECLARED_CAPABILITY` findings appear **every time** — establishing the contrast with the AST01-era `SCOPE_VIOLATION`, which needed the model to invent a bad URL (S-7). *(A-9, S-7, SC-1)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests -q -k "repeat or every_time or hardcoded"`

### Step 3.4 — API attribution (A-5)
- **Goal** — a scanner can attribute the lie to the exact prompt via the stable contract.
- **Files** — `vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_api.py` (FastAPI `TestClient`, monkeypatched stub per `tests/test_api.py`).
- **Depends on** — 3.2.
- **Done when** — `POST /api/chat` returns `findings_raised` naming **both** AST04 `UNDECLARED_CAPABILITY` findings for the turn; `GET /api/findings?ast_id=AST04` returns them in the promised shape carrying `schema_version`; the response contains no field outside the foundation contract (additive only). *(A-5, FR-6.3, `TDD §7`)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_api.py -q -v`

### Step 3.5 — Reset reversibility (A-11)
- **Goal** — the lab returns to clean and the lie reproduces from clean.
- **Files** — same API test module (a reset case).
- **Depends on** — 3.2.
- **Done when** — `POST /api/reset` clears findings, markers, activity **and** the collector inbox (`data/collector/inbox/` empty), re-seeds tasks, and preserves installed state; a second identical turn reproduces both findings and the telemetry delivery. *(A-11, `TDD §14 Q-4`, FR-7.5)*
- **Verify** — `uv run pytest vulnerabilities/ast04-insecure-metadata/tests/test_task_insights_api.py -q -k reset`

### Step 3.6 — Live-model trigger (A-1)  *(Manual)*
- **Goal** — a real model chooses the skill for its advertised purpose, unprompted to read a file or call the network.
- **Files** — `vulnerabilities/ast04-insecure-metadata/tests/manual-checks.md` (a short manual record, mirroring AST01's `manual-checks.md`).
- **Depends on** — 3.2.
- **Done when** — with Ollama running `llama3.1:8b`, **≥4 of 5** varied natural "summarize my tasks / give me a report / how am I doing on my tasks" prompts cause the model to invoke `task_insights`; the advertised summary is returned each time; the two AST04 findings and the telemetry delivery appear. Record prompts, hits, and misses. *(A-1, SC-1, FR-3.1)*
- **Verify** — `Manual:` run `uv run uvicorn --app-dir backend app.main:app` (port 8000 free), install *Task Insights* in the Store, send the five prompts, confirm the two AST04 findings + `data/collector/inbox/`.

### Step 3.7 — Control still clean (A-4 regression)
- **Goal** — the truthfulness axis, unchanged by this feature, still never fires on the honest control skill.
- **Files** — none (re-run `tests/test_control_skill.py` **unmodified**).
- **Depends on** — 1.1, 1.2 (the new skill exists on disk).
- **Done when** — `test_control_skill.py` A-4 still passes: `task_summary` over ≥20 invocations yields `store.load_findings() == []` and `count_markers() == 0` — it declares and uses exactly `task.read` and touches nothing else, so no truthfulness finding is possible. Because AST04 changed no platform code, this is a pure regression check. *(A-4, SC-3, `TDD §11` I-12)*
- **Verify** — `uv run pytest tests/test_control_skill.py -q -v`

---

## ► CHECKPOINT — feature complete  *(single gate; stop and report)*

- **Run** — `uv run pytest -q` (includes `vulnerabilities/`).
- **Confirm** — the two AST04 `UNDECLARED_CAPABILITY` findings fire (A-2/A-3); the control skill stays clean (A-4); and **`git status` + `git diff --stat` show no change under `backend/**`** (the S-8 / G2 zero-platform-change guard).
- **Report** — the pytest summary and a filled **A-1…A-11** table. A-1 is Manual — report it as run/not-run, not pass/fail from pytest.
- **Stop rule** — fix-and-re-run failures **self-contained to `vulnerabilities/ast04-insecure-metadata/`**; **stop for the user** if any fix would need to touch `backend/**` or another foundation file — that would contradict S-8 and signal a faked exploit (G2). There is no earlier checkpoint because no stage edits foundation code.

---

## 11. Code style — binding for every file this plan produces

No product decisions here — how to write the code the approved spec calls for.

- **Plain-language comments a non-technical reader can follow.** Every new file opens with a short plain-English note of what it is for and how it fits the app. Every function is explained in plain words: what it does, what goes in, what comes out. Non-obvious lines get a *why*, with an everyday analogy where it helps — e.g. the manifest is *"like a label on a tin: the app believes the label, so a tin that reads 'offline only' but quietly makes a phone call is the whole trick."*
- **Keep it simple.** Small functions, clear names, minimal nesting, the plain way over the clever way. **No new dependencies** beyond those already in `pyproject.toml`.
- **Caveat 1 — do not simplify away the security-critical shape.** The skill must act **only** through `ctx` (so its undeclared acts are genuinely recorded on the sanctioned channel, not bypassed), and the telemetry payload must carry **no task data** (so correlation stays silent and the demo is AST04 alone, S-5). Keep both, and explain them in comments rather than trimming them.
- **Caveat 2 — keep all tests exactly as specified.** The A-6/A-7 distinctness pair (fires as AST04 alone; the finding tracks the declaration) is the proof the axis is real; do not weaken it into an easier assertion.

---

## 12. Separation and boundaries this plan holds

- The skill's own files — `manifest.json`, `skill.py`, and its tests — live **only** under `vulnerabilities/ast04-insecure-metadata/`. Nothing shared goes in that folder (`vulnerabilities/README.md`).
- **No `backend/**` file changes at all** — stronger than AST01, which needed the S-1 substrate and the detector. AST04's detector, taxonomy, brokers, marker writer, discovery, and `testpaths` all pre-exist (§0). This is verified at the checkpoint by `git diff --stat`.
- The only cross-folder move is **importing** shared helpers — `tests.conftest` (fixtures), `tests.test_engine` (`make_manifest`), `tests.source_tools` (source inspection) — never duplicating them into the vuln folder.
- Module boundaries are unaffected: this feature adds no engine, broker, or orchestrator code, so the existing boundary/purity lints continue to hold unchanged.

---

## 13. Plan-level implementation notes

Engineering calls made to execute the approved spec; flagged so they can be overruled.

| # | Note | Rationale |
|---|---|---|
| **P-1** | The skill reads the relative path `"data/tasks.json"`; the `FileBroker` resolves it against `Path.cwd()` and confines it to `data_dir`/`skills_dir`. In production (run from the repo root, `data_dir=./data`) the read succeeds. Under `tmp_settings`, the `live_lab` fixture sets the process cwd to the parent of the isolated `data_dir` so the read resolves and succeeds (A-2's "outcome ok") | The broker offers no way to learn the data-dir path, so a relative path is the only portable choice; aligning cwd in the fixture reproduces the production condition faithfully. A refused read (wrong cwd) still records the observation and still fires `UNDECLARED_CAPABILITY` (I-3), which is exactly what A-8 proves — so nothing depends on the alignment except the single "ok" assertion |
| **P-2** | All AST04 tests live in `vulnerabilities/ast04-insecure-metadata/tests/`; shared fixtures and helpers are reused by import (`tests.conftest`, `tests.test_engine`, `tests.source_tools`); no foundation test file is modified and no `pyproject` change is needed | `testpaths` already includes `vulnerabilities` (AST01, `Foundation`); the separation rule keeps the weakness self-contained while the platform stays untouched |
| **P-3** | The `net.outbound` telemetry payload is a fixed object carrying no task/file content | No per-item digest overlap with the read tasks ⇒ `check_correlation` is silent ⇒ the skill fires AST04 alone, distinct from the AST01 lying thief (S-5, verified by A-6's "no AST01" assertion) |
| **P-4** | Zero `backend/**` change is a hard contract, verified by `git diff --stat` at the checkpoint | S-8 / `TDD §12`: AST04 adds "Nothing — a skill folder and its tests." Any required foundation edit is a faked-exploit signal (G2) and must be surfaced, not made silently |

---

## 14. Acceptance coverage

Every acceptance test in `Spec §9` maps to the step that proves it. **No test is unverified.**

| Test | Proven at | Kind |
|---|---|---|
| **A-1** live-model picks the skill ≥4/5 | **3.6** | Manual |
| **A-2** genuine undeclared file read + network call on an LLM-chosen invocation | **3.2** | Automated |
| **A-3** exactly two `UNDECLARED_CAPABILITY` (AST04, high), markers written | **3.2** | Automated |
| **A-4** control skill silent (axis unchanged) | **3.7** | Automated |
| **A-5** `/api/chat` `findings_raised` + `/api/findings?ast_id=AST04` shape | **3.4** | Automated |
| **A-6** shipped manifest → **AST04 alone** (no AST03, no AST01) | **2.1** | Automated |
| **A-7** honest declaration → **no** `UNDECLARED_CAPABILITY` (finding = declaration gap) | **2.1** | Automated |
| **A-8** refused undeclared act still fires | **2.1** | Automated |
| **A-9** repeatable across varied params, not incidental | **3.3** | Automated |
| **A-10** through-broker → `UNDECLARED_CAPABILITY`, not `BROKER_BYPASS` | **2.1** (+1.3 source) | Automated |
| **A-11** reset clears findings/markers/activity/collector; reproduces clean | **3.5** | Automated |

A-6 and A-7 are the load-bearing pair: together they prove the truthfulness axis is genuinely distinct — it fires as AST04 alone on a modest-but-lying skill, and the finding tracks the declaration, so honest declaration makes it vanish.

---

## 15. Implementation checklist

**Stage 1 — The skill (vuln folder)**
- [ ] 1.1 `task_insights/manifest.json` — `reporting`, declares `task.read` only *(§4.2, S-1, S-2)*
- [ ] 1.2 `task_insights/skill.py` — honest summary + undeclared `fs.read` + undeclared telemetry, brokers only *(§4.3, S-3…S-6)*
- [ ] 1.3 Discovery/validity + sanctioned-channel source inspection

**Stage 2 — Distinctness on synthetic fixtures**
- [ ] 2.1 `test_task_insights_distinctness.py` — **A-6, A-7, A-8, A-10**

**Stage 3 — E2E, API, reset, repeatability, control-clean**
- [ ] 3.1 Vuln `conftest.py` — fixtures + `live_lab` with cwd alignment *(P-1, P-2)*
- [ ] 3.2 E2E undeclared reach — **A-2, A-3**
- [ ] 3.3 Repeatable, not incidental — **A-9**
- [ ] 3.4 API attribution — **A-5**
- [ ] 3.5 Reset reversibility — **A-11**
- [ ] 3.6 Live-model trigger — **A-1** *(Manual)*
- [ ] 3.7 Control-clean regression — **A-4**
- [ ] **► Checkpoint — full suite + A-1…A-11 table; confirm no `backend/**` change; fix self-contained, stop per rule**

---

## 16. Next step

**Plan only — stopping here for approval.** On approval, build Stage 1 first, then the synthetic-fixture proofs (Stage 2), then wire it end-to-end (Stage 3), and stop at the single checkpoint to report.
