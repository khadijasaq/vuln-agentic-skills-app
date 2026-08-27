# Feature: AST03 — Over-Privileged Skills — Build Plan

| | |
|---|---|
| **Feature** | AST03 · Over-Privileged Skills — an honest skill granted far more than its job needs, plus the tests that prove it |
| **Derives from** | `docs/PRD.md` · `docs/TDD.md` · `docs/features/ast03-over-privileged/spec.md` (approved) |
| **Status** | **Built.** Full suite green at 474 tests (was 449; 25 added). Zero change under `backend/**`, confirmed by `git diff --stat`. A-1 (live model) is left for manual running. |
| **Scope** | AST03 only. **No change to `backend/**` at all, and no change to `backend/policy/**` either** — the skill folder and its tests, under `vulnerabilities/ast03-over-privileged/`, per **S-11** / `TDD §12`. No change to the axes, the baselines, the other vulnerability skills, or the control skill. |

**Citation convention.** Every step cites the AST03 spec as `Spec §n` / `Spec S-n`, the system design as `TDD §n`, and PRD requirements as bare `FR-n` / `SC-n` / `G-n`. Acceptance tests **A-1…A-13** come from `Spec §9`. The App Foundation spec/plan are cited as `Foundation §n` / `Foundation A-n` / `Foundation S-n`; the sibling specs as `AST01 §n` / `AST04 §n`. Plan-level engineering notes are **P-1…P-6** (§13). Line numbers are the code at plan time and are guides, not contracts — the anchor is always the named function.

**Test-first bias.** The axis-distinctness proofs (Stage 2) are written on **synthetic fixtures** — the shipped manifest plus hand-built observations and hand-built variant manifests, fed straight to `FindingsEngine` — **before** the skill is wired end-to-end, because they are the proof the skill fires **AST03 alone** and that the finding tracks the **grant**, not the behaviour and not the declaration gap. Because this feature touches **no foundation code**, there is no high-risk foundation edit and no early gate: verification is a **single checkpoint at the end** (`Foundation §15` method legend applies).

**Code style — binding for every file this plan produces.** See §11. In one line: *comment in plain language a non-technical reader can follow, keep the code simple, and never simplify away the honest-declaration shape or the specified distinctness tests.*

**One disclosed defect is carried, not fixed.** `UNUSED_GRANT` is implemented in the engine and never called by the application (`Spec §5.2`, `docs/KNOWN-ISSUES.md` **KI-1**). This plan **does not wire it**. Step 2.2 pins it with a test instead, so the gap cannot silently close or silently widen.

---

## 0. What already exists (do not rebuild)

The entire proportionality axis, its two call sites, and the policy it measures against are already implemented in the foundation. This plan **references** them; it never copies them into the vuln folder, and it adds **nothing** to `backend/**`.

- **Proportionality detector** — `check_proportionality` in `backend/app/findings/engine.py` raises `EXCESSIVE_GRANT` with `reason="capability_outside_baseline"` for a capability absent from the category's `allowed` list, and with `reason="scope_broader_than_baseline"` for an in-baseline capability declared wider than `max_scope`. It reads **only the manifest and the policy** — never the observation log. **No edit here.** *(Spec §5.1, `TDD §4.5`)*
- **Both call sites are already wired.** `evaluate_install(manifest)` is called from `backend/app/api/routes.py` on `POST /api/skills/{id}/install` (which also writes each marker via `write_marker(stored, None)` and returns them in `findings_raised`); `evaluate_invocation(...)` runs the same check on every skill run from `backend/app/chat/orchestrator.py`. **AST03 needs no new call site.** *(Spec §5.1)*
- **Taxonomy rows** — `EXCESSIVE_GRANT` (AST03, proportionality, **medium**) and `UNUSED_GRANT` (AST03, proportionality, **low**) in `backend/app/findings/taxonomy.py`, both already implemented. *(`TDD §14 Q-2`, `Foundation §9.1`)*
- **The yardstick** — `backend/policy/capability_baselines.json` defines `reporting` as `{"allowed": ["task.read"], "max_scope": {"task.read": ["*"]}}`. **Verified at spec time to produce all three findings for the shipped manifest with no edit** (`Spec §5.4`, **S-11**). **No policy change.**
- **Scope comparison** — `ScopeMatcher.is_broader_than` / `is_unbounded` / `matches` in `backend/app/skills/scope.py`; an unbounded yardstick (`["*"]`) short-circuits, which is why the honest `task.read` declaration stays silent. *(Spec §5.1, §6.1)*
- **Task broker** — `TaskBroker.list` records one `task.read` observation with `sha256` and `item_digests` (`backend/app/skills/context.py`). *(`Foundation §7.3`)*
- **File broker** — `FileBroker.read` records `fs.read` **before** the safety check (I-3); allowed roots `[data_dir, skills_dir]`; refusals `path_outside_allowed_roots` / `file_not_found`, the latter raising `CapabilityRefused`. *(`Foundation §7.3`; relevant to **S-8**)*
- **Dedup** — `Finding.dedup_key()` in `backend/app/storage/models.py` falls through to `granted["capability"]` when `observed` is `None`, so the three findings stay distinct and the install/invocation pair collapses into one row each. *(Spec §5.3, **S-9**, `TDD` D-11)*
- **Marker writer** — `write_marker(finding, observation=None)` in `backend/app/findings/markers.py` already accepts a null observation, which is the correct shape for a proportionality finding. *(seam H, `Foundation S-10`)*
- **Auto-discovery** — `backend/app/skills/registry.py` `default_roots()` scans every `vulnerabilities/*/skill/` folder. Adding the skill folder is the wiring. *(seam A, `Foundation S-18`)*
- **Test collection** — `pyproject.toml` `testpaths=["tests","vulnerabilities"]` is **already set** (by AST01). **No config change.**
- **Correlation stays silent structurally** — `check_correlation` builds its egress set from `net.outbound` observations. This skill never makes one, so the set is empty and `COVERT_DATA_FLOW` is unreachable regardless of what was read. *(Spec §6.1)*
- **Known gap, deliberately untouched** — `check_unused_grants` exists in `backend/app/findings/engine.py` and is unit-tested, but **no application code calls it** (`docs/KNOWN-ISSUES.md` KI-1). Pinned by Step 2.2; **not wired by this plan**.

---

## Stage 1 — The over-privileged skill `focus_picker`  *(vuln folder only)*

*A believable, useful `reporting` skill that honestly declares four capabilities where one would do, genuinely exercises one of the excess three, and leaves the other two dormant — acting **only** through the real brokers.* `Spec §4`, S-2…S-8

### Step 1.1 — Manifest
- **Goal** — a believable `reporting` manifest whose declaration is **completely truthful and plainly excessive**: it lists `task.read` (needed) plus `fs.read`, `task.write` and `net.outbound` (not needed), with honest reasons, two of which openly say the capability is unused.
- **Files** — `vulnerabilities/ast03-over-privileged/skill/focus_picker/manifest.json`.
- **Depends on** — none (§0 discovery exists).
- **Done when** — `id="focus_picker"`, `name="Focus Picker"`, `author="Northbeam Labs"`, `version="1.0.0"`, `category="reporting"`, `entrypoint="skill.py:run"`; `capabilities` is exactly the four of `Spec §4.3` with scopes `["*"]` / `["data/**"]` / `["*"]` / `["127.0.0.1"]`; the two dormant reasons contain the words *"Not used in this version"* (**S-5**); `description` and `when_to_use` describe a next-task picker and mention nothing about files or the network; `parameters` declares the optional `horizon` enum with `required: []`; it passes manifest validation (`record.valid is True`) — an over-declared manifest is **shape-valid**, which is the vulnerability. *(Spec §4.2, §4.3, S-2, S-3, S-5)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests -q -k "manifest or valid"`

### Step 1.2 — Skill behaviour
- **Goal** — the advertised suggestion genuinely works using only `task.read`; the skill additionally reaches beyond its remit with a real `fs.read`; and it never touches its two dormant grants.
- **Files** — `vulnerabilities/ast03-over-privileged/skill/focus_picker/skill.py`.
- **Depends on** — 1.1.
- **Done when** — `run(ctx, params)`: (a) reads the tasks via `ctx.tasks.list("all")`, ranks the unfinished ones by age (honouring `params.get("horizon")` if present), and returns the "work on this next, because…" sentence as `SkillResult.summary` — the advertised job genuinely works and needs nothing else; (b) performs the **excess but declared** `ctx.files.read("data/activity.json")` (`fs.read`), the reach beyond its remit (**S-7**); (c) **wraps that read in a try/except for `CapabilityRefused`** and continues with "no history yet" when the file is absent, so the advertised job never fails (**S-8**); (d) **never calls `ctx.tasks.add/update/delete` and never calls `ctx.net`** — the two dormant grants stay dormant (**S-6**); (e) imports **only** `from app.skills.context import SkillResult, CapabilityRefused` — no `os`, `socket`, `httpx`, `open`, or `subprocess`, so every act is on the sanctioned channel (`source="broker"`). *(Spec §4.4, S-6, S-7, S-8)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests -q -k "behaviour or brokers or dormant"`

### Step 1.3 — Discovery, validity, dormancy and sanctioned-channel inspection
- **Goal** — the platform finds and accepts the skill with no wiring; its source proves it never reaches around the app; and the dormant grants are proved dormant at source level, not just at runtime.
- **Files** — `vulnerabilities/ast03-over-privileged/tests/test_focus_picker_skill.py` (reuse `imported_modules` / `called_function_names` from `tests/source_tools.py`).
- **Depends on** — 1.1, 1.2.
- **Done when** — `get_registry().discover_default()` includes `focus_picker`; its `SkillRecord.valid is True`; it appears in `installed()` after `install("focus_picker")`; source inspection asserts imported top-level modules `== {"app"}` and that `open`/`eval`/`exec` are never called; and a source assertion confirms the strings `ctx.net`, `tasks.add`, `tasks.update` and `tasks.delete` **do not appear** — the dormant grants are unreachable by construction, not merely unused on one path (**S-6**, supports A-11). *(`Foundation S-18`)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_skill.py -q -v`

---

## Stage 2 — Distinctness and the disclosed gap, on synthetic fixtures  *(vuln folder unit tests)*

*Prove the skill fires **AST03 alone**, that the finding tracks the **grant**, and that the `UNUSED_GRANT` gap is exactly where the spec says it is — before wiring anything end-to-end.* `Spec §6`, `TDD §11` I-7, `TDD §4.1`

### Step 2.1 — Distinctness unit tests (A-5, A-6, A-8, A-10)
- **Goal** — the proportionality axis is proven distinct, and its grant-keyed matching proven, on synthetic fixtures with no running skill involved.
- **Files** — new `vulnerabilities/ast03-over-privileged/tests/test_focus_picker_distinctness.py` (reuse the `engine` fixture and `make_manifest` from `tests/test_engine.py`; build observations via `ObservationLog.record(...)`); feed `FindingsEngine.evaluate_invocation(manifest, observations, ...)` and `check_proportionality(...)` directly.
- **Depends on** — 1.1 (uses the **shipped** manifest, loaded from disk, for A-5).
- **Done when** — all pass:
  1. **A-5 — AST03 alone.** The shipped `focus_picker` manifest with observations `task.read`(ok) → `fs.read`(`data/activity.json`, ok) yields findings whose `axis` set is exactly `{"proportionality"}` and `ast_id` set exactly `{"AST03"}`: **three** `EXCESSIVE_GRANT` (`fs.read`, `task.write`, `net.outbound`), each `severity="medium"`, `reason="capability_outside_baseline"`, `granted["allowed"] == ["task.read"]`, `observed is None`, `correlation is None` — and **zero** `UNDECLARED_CAPABILITY`, `SCOPE_VIOLATION`, `BROKER_BYPASS`, `COVERT_DATA_FLOW`. *(`TDD §11` I-7, `TDD §4.1`, PRD §7.3, the live half of `Foundation A-9`)*
  2. **A-6 — the two remedies are opposites.** Over the **same** observations: (a) a fabricated manifest declaring the shipped four **plus `fs.write`** yields **four** `EXCESSIVE_GRANT` — declaring more makes AST03 worse; (b) a fabricated manifest declaring **only `task.read`** yields **zero** `EXCESSIVE_GRANT` and **one** `UNDECLARED_CAPABILITY` (AST04, `fs.read`). Assert the pair together in one test so the opposition is the thing being proved. *(PRD §7.3 distinction, `TDD §11` I-7)*
  3. **A-8 — the second `EXCESSIVE_GRANT` branch.** A fabricated `integration`-category manifest declaring `net.outbound` with scope `["*"]` yields `EXCESSIVE_GRANT` with `reason="scope_broader_than_baseline"` and `limit == ["127.0.0.1"]` — the branch the shipped skill does not exercise, and the same two capabilities that are *proportionate* for AST01's `integration` skill (`AST01 §6.1`). *(Spec §6.3, `Foundation §9.3`)*
  4. **A-10 — behaviour is not an input.** The shipped manifest evaluated against (i) the normal two observations, (ii) a **refused** `fs.read` (`outcome="error"`, `file_not_found`), and (iii) an **empty** observation list yields the **identical three findings** every time — because `check_proportionality` never reads the log. *(Spec §5.1, §6.1, **S-8**)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_distinctness.py -q -v`

### Step 2.2 — The `UNUSED_GRANT` position, pinned (A-7)  *(P-4)*
- **Goal** — prove the shipped manifest is `UNUSED_GRANT`-eligible, and pin the disclosed platform gap so it cannot drift in either direction unnoticed.
- **Files** — new `vulnerabilities/ast03-over-privileged/tests/test_focus_picker_unused_grant.py`.
- **Depends on** — 1.1.
- **Done when** — both pass:
  1. **Eligibility.** `engine.check_unused_grants(shipped_manifest, {"task.read", "fs.read"}, invocation_count=5, window=5)` returns **exactly two** `UNUSED_GRANT` findings — `task.write` and `net.outbound` — each `ast_id="AST03"`, `axis="proportionality"`, `severity="low"`, `granted["capability"]` naming the dormant capability; and the same call at `invocation_count=2` returns **none** (the window guard, `TDD` D-10). *(Spec §5.2, **S-6**)*
  2. **The gap is where the spec says it is.** A source scan asserts that no file under `backend/` calls `check_unused_grants` — the only references being its own definition — with a comment naming `docs/KNOWN-ISSUES.md` **KI-1** and stating that when the wiring lands this test should be **updated, not deleted**, and A-3/A-12's expected counts revised. *(Spec §5.2, §12; KI-1)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_unused_grant.py -q -v`

---

## Stage 3 — Install-time, end-to-end, API, reset, repeatability, control-clean  *(vuln folder tests only)*

*The over-privilege stands from the moment of install, is confirmed by the LLM's own choice to run the skill, is attributable through the API, repeatable, and fully reversible; the control skill stays clean.* `Spec §9`, PRD §8 R3

### Step 3.1 — Test plumbing for the vuln folder  *(P-1, P-2, P-3)*
- **Goal** — the folder's tests reuse the shared fixtures and can drive the app end to end, without touching any foundation file.
- **Files** — `vulnerabilities/ast03-over-privileged/tests/conftest.py` (re-export `tmp_settings` and the autouse settings-reset from `tests.conftest`; add an `installed_focus_picker` fixture; a `FocusPickerStub` model that always chooses `focus_picker`; an `api_client` fixture returning a FastAPI `TestClient` over `create_app()` with the stub installed and the cwd aligned).
- **Depends on** — 1.1, 1.2.
- **Done when** — `uv run pytest vulnerabilities/ast03-over-privileged -q` collects and runs against an isolated temp `data/`; the fixture **sets the process cwd to the parent of `settings.data_dir`** so the skill's relative `"data/activity.json"` resolves into the isolated data root (**P-1**); **no uvicorn thread and no live loopback server is used** — unlike AST01/AST04 this skill makes no network call, so `TestClient` is sufficient and simpler (**P-3**); **no `pyproject.toml` and no foundation test file is modified** (`testpaths` already includes `vulnerabilities`). *(P-1, P-2, P-3)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged -q`

### Step 3.2 — Install-time firing (A-3)
- **Goal** — the three findings stand against the skill before it has ever run, each with a marker, exactly as `TDD §4.5` says over-privilege should behave.
- **Files** — `vulnerabilities/ast03-over-privileged/tests/test_focus_picker_api.py` (an install case).
- **Depends on** — 3.1.
- **Done when** — `POST /api/skills/focus_picker/install` returns `findings_raised` containing **exactly three** `EXCESSIVE_GRANT` entries — `fs.read`, `task.write`, `net.outbound` — each `ast_id="AST03"`, `axis="proportionality"`, `severity="medium"`, `trigger="install"`, `invocation_id is None`, `granted.reason="capability_outside_baseline"`, `granted.allowed == ["task.read"]`, `observed is None`, `correlation is None`, `model` recorded; `count_markers() == 3`, and each marker file contains the literal `INTENTIONALLY_VULNERABLE_LAB_MARKER` and `"observation": null`; `evidence.observation_seq is None`. *(A-3, SC-2, FR-4.3, FR-4.4, `TDD §14 Q-2`, Spec §3)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_api.py -q -k install`

### Step 3.3 — End-to-end: the over-reach is real on an LLM-chosen invocation (A-2)
- **Goal** — the model chooses the skill for its advertised purpose; the skill does that job **and** genuinely reaches beyond its remit through the broker.
- **Files** — `vulnerabilities/ast03-over-privileged/tests/test_focus_picker_e2e.py`.
- **Depends on** — 3.1, 3.2.
- **Done when** — after a natural "what should I work on next?" request through `POST /api/chat` with the stub model: `skill_invoked.skill_id == "focus_picker"`, `outcome == "ok"`, and the reply names a real task from the seeded list; the invocation's observations are exactly a `task.read` (`ok`) **and** an `fs.read` on `data/activity.json` (`ok`, `source="broker"`) — an observed capability set materially exceeding the job's need — with **no** `task.write` and **no** `net.outbound` observation anywhere (the dormant grants, **S-6**); the user's task list is byte-identical before and after (nothing written, FR-7.4). *(A-2, PRD §7.3, FR-4.1, FR-7.3)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_e2e.py -q -v`

### Step 3.4 — Repeatable, not incidental (A-9)
- **Goal** — the over-privilege is a manifest property plus hardcoded behaviour, firing every run regardless of what the model passes.
- **Files** — same e2e module (a repetition case), or a focused host-level test invoking the skill with varied `params`.
- **Depends on** — 3.3.
- **Done when** — across **≥5** invocations passing different `params` (`{"horizon": "today"}`, `{"horizon": "week"}`, `{}`, and junk keys the schema does not declare), all three findings are present every time and `occurrences` increments monotonically with each run; the advertised suggestion is returned every time. *(A-9, **S-10**, SC-1)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests -q -k "repeat or every_time or horizon"`

### Step 3.5 — API attribution and the dedup semantics (A-12)  *(P-5)*
- **Goal** — a scanner can attribute the over-privilege to the run that confirmed it, and the install/invocation collapse reads as intended rather than as a failure to fire.
- **Files** — same API test module.
- **Depends on** — 3.2, 3.3.
- **Done when** — `POST /api/chat` returns `findings_raised` naming **all three** AST03 findings with the **same ids** returned at install; the turn's activity entry carries `vulnerability_fired: true` and those three ids in its `findings_raised`; `GET /api/findings?ast_id=AST03` returns exactly three findings in the promised shape with `schema_version`, each `occurrences >= 2`, `first_seen` unchanged from install, `last_seen` advanced to the turn, `trigger` still `"install"`, and `count_markers()` still `3` (no second marker) — the **S-9** behaviour asserted positively, not worked around. *(A-12, FR-6.3, FR-5.2, `TDD §7`, D-11, Spec §5.3)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_api.py -q -k "attribution or dedup or occurrences"`

### Step 3.6 — Reset and reinstall reversibility (A-13)
- **Goal** — the lab returns to clean, and the over-privilege reproduces from clean.
- **Files** — same API test module (a reset case).
- **Depends on** — 3.2, 3.3.
- **Done when** — `POST /api/reset` clears the three findings, their markers and the activity entry, re-seeds tasks and preserves installed state (`TDD §14 Q-4`); a subsequent `POST /api/skills/focus_picker/uninstall` + `install` reproduces **all three** install-time findings with **fresh ids and fresh markers**. *(A-13, FR-7.5)*
- **Verify** — `uv run pytest vulnerabilities/ast03-over-privileged/tests/test_focus_picker_api.py -q -k reset`

### Step 3.7 — Live-model trigger (A-1)  *(Manual)*
- **Goal** — a real model chooses the skill for its advertised purpose, unprompted to read any file.
- **Files** — `vulnerabilities/ast03-over-privileged/tests/manual-checks.md` (a short manual record, mirroring AST04's).
- **Depends on** — 3.3.
- **Done when** — with Ollama running `llama3.1:8b`, **≥4 of 5** varied natural "what should I work on next / what do I do first / help me prioritise / what matters most today / pick something for me" prompts cause the model to invoke `focus_picker`; the advertised suggestion is returned each time; the three AST03 findings show `occurrences` rising. Record prompts, hits and misses. **If the rate falls short, the only lever is the `description` / `when_to_use` wording** — never hardcoded routing (FR-3.4), and never removing the sibling summarisers from the store. *(A-1, SC-1, FR-3.1)*
- **Verify** — `Manual:` run `uv run uvicorn --app-dir backend app.main:app`, install *Focus Picker* in the Store, confirm the three findings appear **at install**, send the five prompts, confirm `occurrences` rises and the Activity screen marks each turn.

### Step 3.8 — Control still clean (A-4 regression)
- **Goal** — the proportionality axis, unchanged by this feature, still never fires on the honest control skill.
- **Files** — none (re-run `tests/test_control_skill.py` **unmodified**).
- **Depends on** — 1.1, 1.2 (the new skill exists on disk).
- **Done when** — `test_control_skill.py` A-4 still passes: `task_summary` over ≥20 invocations yields `store.load_findings() == []` and `count_markers() == 0` — it declares exactly `task.read`, which the `reporting` baseline permits with an unbounded limit, and it exercises it. Because AST03 changed no platform code **and no policy file**, this is a pure regression check; a failure here would mean the baselines were edited after all. *(A-4, SC-3, `TDD §11` I-12)*
- **Verify** — `uv run pytest tests/test_control_skill.py -q -v`

---

## ► CHECKPOINT — feature complete  *(single gate; stop and report)*

- **Run** — `uv run pytest -q` (includes `vulnerabilities/`).
- **Confirm** —
  1. the three AST03 `EXCESSIVE_GRANT` findings fire at install and are confirmed by the LLM-chosen invocation (A-3, A-2, A-12);
  2. the skill fires **AST03 alone** — no AST04, no AST01 (A-5);
  3. the control skill stays clean (A-4);
  4. **`git status` + `git diff --stat` show no change under `backend/**`** — including **`backend/policy/**`** (the **S-11** / G2 zero-platform-change guard, stricter than AST04's, because AST03 is the feature `TDD §12` said might need a policy edit and does not).
- **Report** — the pytest summary and a filled **A-1…A-13** table. A-1 is Manual — report it as run/not-run, not pass/fail from pytest. State explicitly that `UNUSED_GRANT` did **not** fire at runtime and that this is KI-1 behaving as disclosed.
- **Stop rule** — fix-and-re-run failures **self-contained to `vulnerabilities/ast03-over-privileged/`**; **stop for the user** if any fix would need to touch `backend/**` or another foundation file. For this feature specifically, three temptations are all **stop-and-flag**, not fix:
  - *"just widen/narrow a category in `capability_baselines.json` so the findings come out right"* — the over-privilege would then be defined into existence rather than found (**S-11**);
  - *"just add the `check_unused_grants` call so both AST03 types fire"* — that is KI-1's fix, sequenced separately after all three vulnerabilities (`Spec §12`);
  - *"just add a field to the finding so the demo reads better"* — a schema change contradicts `TDD §12` and I-11.

  Any of these means the exploit is being faked rather than exercised (G2). Report it; do not make the edit.

---

## 11. Code style — binding for every file this plan produces

No product decisions here — how to write the code the approved spec calls for.

- **Plain-language comments a non-technical reader can follow.** Every new file opens with a short plain-English note of what it is for and how it fits the app. Every function is explained in plain words: what it does, what goes in, what comes out. Non-obvious lines get a *why*, with an everyday analogy where it helps — e.g. *"this skill is like a house-sitter given the keys to every room, the safe and the car, when all they were asked to do is water one plant. Nobody lied to anyone; the key ring is simply far too big — and it stays on the hook whether or not it is used."*
- **Keep it simple.** Small functions, clear names, minimal nesting, the plain way over the clever way. **No new dependencies** beyond those already in `pyproject.toml`.
- **Caveat 1 — do not simplify away the honest-declaration shape.** The skill must declare **every** capability it uses, in a scope that covers what it touches, and act **only** through `ctx`. If a later tidy-up removed the `fs.read` declaration, or narrowed its scope below `data/activity.json`, the skill would start firing AST04 and the demonstration would stop being AST03 alone (`Spec §6.1`). Comment this at the declaration, not just in the docs.
- **Caveat 2 — the dormant grants must stay dormant.** `task.write` and `net.outbound` are declared and never used on purpose (**S-6**). Do not "make use of them" for realism, and do not delete them for tidiness — the first turns the skill into a different vulnerability, the second deletes the latent-damage point and A-7's fixture.
- **Caveat 3 — keep all tests exactly as specified.** The A-5/A-6 distinctness pair (fires as AST03 alone; the two remedies are opposites) is the proof the axis is real; A-10 (behaviour is not an input) is the proof it is the *proportionality* axis and not a behavioural threshold. Do not weaken any of them into an easier assertion.

---

## 12. Separation and boundaries this plan holds

- The skill's own files — `manifest.json`, `skill.py`, and its tests — live **only** under `vulnerabilities/ast03-over-privileged/`. Nothing shared goes in that folder (`vulnerabilities/README.md`).
- **No `backend/**` file changes at all, and no `backend/policy/**` changes either.** This is stronger than AST04's guard, because `TDD §12` explicitly anticipated a baseline edit for AST03 and `Spec §5.4` verified that none is needed. Confirmed at the checkpoint by `git diff --stat`.
- The only cross-folder move is **importing** shared helpers — `tests.conftest` (fixtures), `tests.test_engine` (`engine`, `make_manifest`), `tests.source_tools` (source inspection) — never duplicating them into the vuln folder.
- Module boundaries are unaffected: this feature adds no engine, broker, or orchestrator code, so the existing boundary/purity lints continue to hold unchanged.
- `docs/KNOWN-ISSUES.md` KI-1 is documentation of an existing foundation gap; this plan reads and cites it, and changes nothing it describes.

---

## 13. Plan-level implementation notes

Engineering calls made to execute the approved spec; flagged so they can be overruled.

| # | Note | Rationale |
|---|---|---|
| **P-1** | The skill reads the relative path `"data/activity.json"`; the `FileBroker` resolves it against `Path.cwd()` and confines it to `data_dir`/`skills_dir`. In production (run from the repo root, `data_dir=./data`) it resolves correctly. The vuln-folder fixture sets the process cwd to the parent of the isolated `data_dir`, reproducing that condition | Same constraint AST04 hit (`AST04` P-1): the broker offers no way to learn the data-dir path, so a relative path is the only portable choice. **Lower stakes here** — a missing or refused read changes nothing about the findings (`Spec §5.1`), which is precisely what A-10 proves; only A-2's "outcome ok" assertion depends on the alignment |
| **P-2** | All AST03 tests live in `vulnerabilities/ast03-over-privileged/tests/`; shared fixtures and helpers are reused by import; no foundation test file is modified and no `pyproject` change is needed | `testpaths` already includes `vulnerabilities` (AST01); the separation rule keeps the weakness self-contained while the platform stays untouched |
| **P-3** | AST03's tests use FastAPI `TestClient`, **not** the in-process uvicorn `live_lab` fixture AST01 and AST04 need | Those two need a genuine loopback server because their skills really send to the mock collector. *Focus Picker* makes **no network call at all** (**S-6**) — there is nothing to serve, so a live server would be ceremony. Simpler, faster, and it makes the "no egress" property visible in the test setup itself |
| **P-4** | A-7 asserts both the `UNUSED_GRANT` eligibility **and** the absence of any platform caller, with the test naming `docs/KNOWN-ISSUES.md` KI-1 and saying it should be updated rather than deleted when the wiring lands | Turns a disclosed gap into a pinned one. Without the second half, wiring KI-1 later would silently change AST03's expected finding counts (A-3, A-12) and nobody would be pointed at the tests that need revising |
| **P-5** | The e2e and API tests assert the **dedup** outcome (same three ids, `occurrences >= 2`, `last_seen` advanced, `count_markers()` still 3) rather than expecting new rows per invocation | `Spec §5.3` / **S-9**: this is `TDD` D-11 working as designed. Asserting it positively stops a future reader — or a future test — from "fixing" the absence of new findings, which would mean weakening dedup for the whole product |
| **P-6** | Zero `backend/**` **and** `backend/policy/**` change is a hard contract, verified by `git diff --stat` at the checkpoint | **S-11** / `TDD §12`. AST03 is the one feature whose TDD row allowed a JSON edit; `Spec §5.4` verified against the real engine that the shipped `reporting` yardstick already produces all three findings. Any required edit is a faked-exploit signal (G2) and must be surfaced, not made silently |

---

## 14. Acceptance coverage

Every acceptance test in `Spec §9` maps to the step that proves it. **No test is unverified.**

| Test | Proven at | Kind |
|---|---|---|
| **A-1** live-model picks the skill ≥4/5 | **3.7** | Manual |
| **A-2** the over-reach is real on an LLM-chosen invocation (`fs.read` observed, no `task.write`/`net.outbound`) | **3.3** | Automated |
| **A-3** install raises exactly three `EXCESSIVE_GRANT` (AST03, medium), markers written with null observation | **3.2** | Automated |
| **A-4** control skill silent (axis and policy unchanged) | **3.8** | Automated |
| **A-5** shipped manifest → **AST03 alone** (no AST04, no AST01) | **2.1** | Automated |
| **A-6** the two remedies are opposites (declare more ⇒ worse; declare less ⇒ AST04) | **2.1** | Automated |
| **A-7** `UNUSED_GRANT` eligibility + no platform caller (KI-1 pinned) | **2.2** | Automated |
| **A-8** `scope_broader_than_baseline` branch on a fabricated `integration` manifest | **2.1** | Automated |
| **A-9** repeatable across varied `horizon` arguments, not incidental | **3.4** | Automated |
| **A-10** behaviour is not an input (refused / empty log ⇒ identical findings) | **2.1** | Automated |
| **A-11** through the broker, not around it (source scan; dormant grants unreachable) | **1.3** | Automated |
| **A-12** `/api/chat` `findings_raised` + `/api/findings?ast_id=AST03`, `occurrences >= 2`, dedup semantics | **3.5** | Automated |
| **A-13** reset clears; uninstall + reinstall reproduces from clean | **3.6** | Automated |

A-5 and A-6 are the load-bearing pair: together they prove the proportionality axis is genuinely distinct — it fires as AST03 alone on an honest, broad skill (A-5, the live half of `Foundation A-9` that has never had a shipped skill behind it), and the finding tracks the **grant**, so the AST04 remedy and the AST03 remedy point in opposite directions (A-6). A-10 is what separates this axis from a behavioural threshold; A-7 keeps the disclosed gap honest.

---

## 15. Implementation checklist

**Stage 1 — The skill (vuln folder)**
- [x] 1.1 `focus_picker/manifest.json` — `reporting`, four honest capabilities, two marked unused *(§4.3, S-2, S-3, S-5)*
- [x] 1.2 `focus_picker/skill.py` — suggestion + declared excess `fs.read` (+ missing-file tolerance), dormant grants untouched, brokers only *(§4.4, S-6, S-7, S-8)*
- [x] 1.3 Discovery/validity + dormancy + sanctioned-channel source inspection — **A-11**

**Stage 2 — Distinctness and the disclosed gap, on synthetic fixtures**
- [x] 2.1 `test_focus_picker_distinctness.py` — **A-5, A-6, A-8, A-10**
- [x] 2.2 `test_focus_picker_unused_grant.py` — **A-7** *(pins KI-1, P-4)*

**Stage 3 — Install-time, E2E, API, reset, repeatability, control-clean**
- [x] 3.1 Vuln `conftest.py` — fixtures + cwd alignment, `TestClient` not uvicorn *(P-1, P-2, P-3)*
- [x] 3.2 Install-time firing — **A-3**
- [x] 3.3 E2E over-reach on an LLM-chosen invocation — **A-2**
- [x] 3.4 Repeatable, not incidental — **A-9**
- [x] 3.5 API attribution + dedup semantics — **A-12** *(P-5)*
- [x] 3.6 Reset and reinstall reversibility — **A-13**
- [x] 3.7 Live-model trigger — **A-1** *(Manual)*
- [x] 3.8 Control-clean regression — **A-4**
- [x] **► Checkpoint — full suite + A-1…A-13 table; confirm no `backend/**` and no `backend/policy/**` change; state KI-1 behaved as disclosed; fix self-contained, stop per rule**

---

## 16. Next step

**Plan only — stopping here for approval.** On approval, build Stage 1 first, then the synthetic-fixture proofs and the KI-1 pin (Stage 2), then wire it end-to-end (Stage 3), and stop at the single checkpoint to report.
