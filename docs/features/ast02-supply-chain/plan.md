# Feature: AST02 — Supply Chain Compromise — Build Plan

| | |
|---|---|
| **Feature** | AST02 · Supply Chain Compromise — an honest, correctly-pinned skill whose third-party component was swapped upstream, plus the axis and the tests that prove it |
| **Derives from** | `docs/PRD.md` · `docs/TDD.md` · `docs/features/ast02-supply-chain/spec.md` (**not yet approved** — see §0.1) |
| **Status** | **Plan. Not built, and not startable.** Four blocking approvals stand ahead of Stage 0 (§0.1), including a PRD amendment. Two spec↔code inconsistencies found while verifying this plan need decisions (§0.2). |
| **Scope** | AST02 only. **Platform change: REQUIRED** — six `backend/**` files plus one new mock, per `Spec §9` / `Spec §14`, argued against `TDD §12`'s replacement test in `Spec §9.8`. **Zero policy change** (`backend/policy/**` untouched). No change to the four sibling skills or the control skill, and their finding sets must be provably unmoved. |

**Citation convention.** Every step cites the AST02 spec as `Spec §n` / `Spec S-n`, the system design as `TDD §n`, and PRD requirements as bare `FR-n` / `SC-n` / `G-n`. Acceptance tests **A-1…A-18** come from `Spec §11`. The App Foundation spec is cited as `Foundation §n` / `Foundation A-n` / `Foundation S-n`; sibling specs as `AST01 §n`, `AST03 §n`, `AST04 §n`, `AST05 §n`. Plan-level engineering notes are **P-1…P-8** (§13); blockers are **B-1…B-4**, spec↔code inconsistencies **I-1…I-2**, and ledger gaps **G-1…G-6** (§0). Line numbers are the code at plan time and are guides, not contracts — the anchor is always the named function.

**Baseline-first bias.** This plan's first stage writes **no product code at all**. A-10 claims the other four vulnerabilities and the control skill are byte-for-byte unmoved, and the only honest way to prove that is a snapshot captured *before* the first platform edit — the discipline `tests/test_ast05_substrate_regression.py` already established and states in its own header: *"a regression test that can regenerate its own expectations proves nothing at all."* Stage 0 captures it; every later gate measures against it.

**Risk shape.** Unlike AST04 and AST03 (skill-and-tests only), this feature edits the shared engine, the shared manifest parser and the shared finding model. Stages 1–3 are therefore ⚠ HIGH RISK with a hard gate before the skill exists, mirroring how AST01 and AST05 sequenced their substrate work.

**Code style — binding for every file this plan produces.** See §11. In one line: *comment in plain language a non-technical reader can follow, keep the code simple, and never simplify away the observation order, the AST02-alone silences, or the read-only baseline snapshot.*

---

## 0. Before anything is built

### 0.1 Blocking approvals — no code may be written until these are answered

`TDD §12` grants AST05 a carve-out and then binds any successor: *"This is a carve-out, not a precedent. Any fifth vulnerability proposing platform change must argue the replacement test explicitly, in its own spec, and be reviewed on it."* That review has not happened.

| # | Decision | Spec | Recommended |
|---|---|---|---|
| **B-1** | **PRD §5 NG1 rules AST02 out of scope** — *"not authentically demonstrable by this architecture — AST02 (no acquisition path to poison)"*. PRD v1.1 must be amended to v1.2 before this feature exists. | `Spec §1.5` X-2, `Spec §16` Q-1 | **Amend.** If rejected, this plan is void and `Spec §3` remains the useful artifact. |
| **B-2** | Is a **skill-level** acquisition path an authentic supply chain, or staging (G2)? | `Spec §16` Q-2 | **Authentic** — the platform gains a *verifier*, not an installer. The skill does the acquiring as part of its own advertised job, as *Team Rules* does. |
| **B-3** | **The second `TDD §12` carve-out** must be reviewed on the replacement test, not assumed. | `Spec §9.8` | **Approve** — the argument is stronger than AST05's: AST05 changed what the broker *records*; AST02 changes nothing about recording at all. |
| **B-4** | Severity of `COMPROMISED_DEPENDENCY`. | `Spec §8`, `Spec §16` Q-3 | **`high`**, keeping `critical` unique to AST01. One word in the taxonomy row; nothing else moves. |

### 0.2 Spec ↔ code inconsistencies found while verifying this plan

Both were established by reading the code, not by inference. Neither may be applied silently.

| # | Finding | Evidence | Recommended resolution |
|---|---|---|---|
| **I-1** | **A-14 contradicts the `Spec §7.2` algorithm on a 404.** `Spec §6.4` S-16 says an absent artifact arrives as `CapabilityRefused`, and A-14 requires *"registry artifact absent (404) … no finding is raised"*. But `NetBroker._request` (`backend/app/skills/context.py`) raises `CapabilityRefused` **only** on an unsupported scheme, a non-local host, or a transport exception. A **404 returns normally**, `_record_response` runs, and `detail.response_sha256` becomes the digest of the *error body* — which mismatches the pin. `Spec §7.2` as literally written would therefore fire `COMPROMISED_DEPENDENCY` **on an empty registry**: a false positive that directly undermines A-6's silence argument and `Spec §9.8` argument 2. | `context.py` `_request` → `_record_response`; `backend/app/mock/hub.py` returns `404` for a missing document, so the registry will too | **Narrow the axis: an acquisition counts only when `detail.get("status") == 200`.** One added condition, strictly narrowing, and principled — *only a successful delivery can be compared to a pin*. It makes A-14 true as written. **This is a deviation from `Spec §7.2`'s pseudo-code and must be approved and back-annotated into `Spec §7.2`, `Spec §7.4` limit 2 and `S-16`.** Carried in this plan as **P-1**. |
| **I-2** | **The sabotage keyword list matches nothing in the seeded lab.** `STARTER_TASKS` in `backend/app/storage/seed.py` holds eight rows; none has **notes** mentioning `security`, `audit`, `invoice`, `access review` or `password`. A-2 requires the compromised build to visibly bury such a task, so on a default lab there is a finding but nothing visibly buried. | `seed.py` STARTER_TASKS, read in full | **Do not touch `seed.py`.** It is absent from `Spec §14`, it is FR-1.3 crown-jewel data, and changing it would alter task digests and risk the immutable AST01 rows inside `tests/fixtures/pre_ast05_findings.json`. Instead the AST02 fixture adds one task via `store.add_task(...)`, and `manual-checks.md` tells the demo operator to add the same task first. **Cost: the live demo gains a setup step, so DR-6's one-story flow is slightly weakened.** Carried as **P-2**. |

### 0.3 Ledger gaps — required by the spec's own text, missing from its `§14` table

| # | Gap | Why it is unavoidable |
|---|---|---|
| **G-1** | `tests/test_startup.py` → **Modify** | `test_the_startup_steps_are_in_the_documented_order` asserts the exact six-name list. Adding `seed_registry_components` (`Spec §5.3`, `§9.5`) breaks it. |
| **G-2** | `step_prepare_data_folder` must also create `registry_dir` | It creates `hub_dir` today; without the same treatment the seed step and the endpoint meet a missing directory. |
| **G-3** | `tests/fixtures/pre_ast02_findings.json` + `tests/test_ast02_substrate_regression.py` → **New** | A-10 claims unchanged finding sets for **five** skills. `pre_ast05_findings.json` covers only three and is explicitly read-only and never regenerated. A new snapshot is the only honest proof — **and it must be captured before the first backend edit** (Stage 0). |
| **G-4** | AST02 test module basenames must be **globally unique** | There is no `__init__.py` under any `vulnerabilities/*/tests/`, so pytest imports by basename. `test_registry.py`, `test_manifest.py` and `test_engine.py` already exist in `tests/`. Hence `test_component_registry.py`, not `test_registry.py`. |
| **G-5** | `check_integrity` must be callable from `evaluate_install` | `evaluate_install(manifest, *, model)` has no observations, so the signature takes `observations: list[Observation] \| None = None`. The unpinned half then runs at install (`Spec §7.3`) and the delivered half is structurally skipped. |
| **G-6** | The pin is a bootstrap | `manifest.json`'s `integrity` cannot be written until the registry serves the reviewed build and the broker records its digest. Stage 5 has an explicit generate-then-freeze step. |

### 0.4 What already exists (do not rebuild)

Everything AST02's evidence needs is already in the platform. This plan **references** it and adds **no recording of any kind**.

- **The delivered-artifact digest** — `_record_response` in `backend/app/skills/context.py` already writes `response_bytes`, `response_sha256`, `response_item_digests`, `response_strings` and `response_excerpt` onto every `net.outbound` observation that received a reply (`TDD` D-15). **`response_sha256` is the whole evidentiary basis of this feature. No edit here — ever.** *(`Spec §2`, `§4.2`, **S-1**)*
- **The shared digest recipe** — `digest_of` in `backend/app/monitor/observations.py`: `sha256(json.dumps(value, sort_keys=True, default=str))`. **No new walker**, unlike `AST05 §8.2`. **No edit here.**
- **Ordered causal log** — `ObservationLog`, monotonic `seq`, never re-sorted (`TDD` D-7, I-5).
- **Refuse-and-record ordering** — `_BaseBroker._record` → safety check → `_refuse` (`TDD §3.1`, I-3).
- **Install-time evaluation** — `install_skill` in `backend/app/api/routes.py` already calls `evaluate_install`, returns `findings_raised`, and writes markers via `write_marker(stored, None)`. **No edit.**
- **Per-invocation evaluation** — `evaluate_invocation` is called from exactly one place, `backend/app/chat/orchestrator.py` (~L273), which then runs `_save_findings` → `write_marker`. **No edit** — the new check goes inside the engine.
- **Marker writer** — `write_marker(finding, observation=None)` and `MARKER_PHRASE = "INTENTIONALLY_VULNERABLE_LAB_MARKER"` in `backend/app/findings/markers.py`; accepts any finding type. **No edit.**
- **Reset semantics** — `store.reset_lab()` clears findings, activity, dashboard, markers, collector inbox and tasks, and **already leaves `data/hub/` alone**. `data/registry/` therefore survives a reset for free (A-18). **No edit.**
- **Auto-discovery** — `SkillRegistry.default_roots()` scans every `vulnerabilities/*/skill/` folder. Adding the folder is the wiring. *(`Foundation S-18`)*
- **Host-glob scope matching** — `ScopeMatcher._one_pattern_matches` compares a resource's *hostname* against a host pattern (`AST01 S-7`). This is what makes the §10.6 co-occurrence case work: `localhost` ≠ `127.0.0.1`.
- **Zero policy change** — `integration` in `backend/policy/capability_baselines.json` already permits `task.read` + `net.outbound → 127.0.0.1`, and `task.read` has no `max_scope` entry so its limit is unbounded. This is the **identical declaration** *Standup Sync* carries, already proved to raise no AST03 (`AST01 §6.1`, `AST01 A-6`). **No policy edit.**
- **Test collection** — `pyproject.toml` `testpaths = ["tests", "vulnerabilities"]`. **No config change.**
- **Shared test helpers** — `tests/conftest.py` (`tmp_settings`, the autouse reset), `tests/source_tools.py` (`imported_modules`, `called_function_names`), and the live-loopback fixture pattern in `vulnerabilities/ast05-untrusted-external-instructions/tests/conftest.py`. Reused **by import**, never copied.
- **The AST05 baseline** — `tests/test_ast05_substrate_regression.py` + `tests/fixtures/pre_ast05_findings.json` are **read-only** and must keep passing untouched. AST02 adds no observation field, so `test_observations_only_gained_the_expected_response_fields` is unaffected; `_normalise()` reads an explicit key list, so `Finding.dependency` cannot disturb it.

---

## Stage 0 — The pre-AST02 baseline  ⚠ MUST BE FIRST — no product code

*A-10's claim is unprovable unless the measurement exists before the change.* `Spec §11` A-10, **G-3**, `TDD §12`

### Step 0.1 — Capture the five-skill snapshot
- **Goal** — record, against **today's unmodified code**, exactly what each shipped skill produces, so any later drift is measurable rather than arguable.
- **Files** — `tests/fixtures/pre_ast02_findings.json` *(new; written once, then read-only forever)*.
- **Depends on** — B-1…B-4 answered.
- **Done when** — the harness from `tests/test_ast05_substrate_regression.py` is reused verbatim in shape (live loopback server on `127.0.0.1:8000`, `_Stub` model returning one tool call then plain text, `_normalise`, `_sort_key`, the `os.chdir(data_dir.parent)` alignment that lets relative broker paths resolve) with `SHIPPED_SKILLS` extended to **five**: `task_insights`, `standup_sync`, `focus_picker`, `team_rules`, `task_summary`. For each: install findings, invocation findings, observation shapes and `vulnerability_fired` are captured. The file is committed and **never regenerated**.
- **Verify** — `uv run pytest -q` (must be fully green *before* capture; a red suite makes the baseline meaningless).

### Step 0.2 — The regression test that reads it
- **Goal** — a test that can only ever *measure*, never *agree with itself*.
- **Files** — `tests/test_ast02_substrate_regression.py` *(new)*.
- **Depends on** — 0.1.
- **Done when** — it loads the snapshot read-only, fails loudly with the "do not update the snapshot — find out what moved" message if absent, and asserts per skill: identical finding counts, identical normalised findings, identical install findings, identical `skill_outcome` and `vulnerability_fired`; **no skill gains an `integrity` axis or an `AST02` id**; and a source-level assertion that `backend/app/skills/context.py` and `backend/app/monitor/observations.py` are unmodified (**S-1**). It also carries the mirrored wiring assertion: `check_integrity` appears in **both** `evaluate_invocation` and `evaluate_install` — unlike `check_provenance`, which the AST05 file asserts appears only in the former.
- **Verify** — `uv run pytest -q tests/test_ast02_substrate_regression.py -v`

---

## ► CHECKPOINT 0 — the baseline gate  *(stop and report)*

- **Run** — `uv run pytest -q`.
- **Confirm** — fully green; `tests/fixtures/pre_ast02_findings.json` exists; `tests/test_ast02_substrate_regression.py` **passes against unmodified code**.
- **Stop rule** — if the new regression file does not pass *before* a single line of product code changes, the baseline is wrong. **Stop and report; do not proceed to Stage 1.**

---

## Stage 1 — Data shapes  ⚠ HIGH RISK — edits shared finding model and taxonomy

*The fifth axis and its evidence field, with no behaviour attached.* `Spec §4.3`, `§9.2`, `§9.4`, **S-6**, **S-9**

### Step 1.1 — The fifth axis and the `dependency` field
- **Goal** — `Finding` can carry integrity evidence, preserving `TDD §4.7`'s one-field-per-axis convention at five axes rather than diluting it.
- **Files** — `backend/app/storage/models.py`.
- **Depends on** — Checkpoint 0 green.
- **Done when** — `Axis` gains `"integrity"`; `Finding` gains `dependency: dict[str, Any] | None = None` beside `observed` / `granted` / `correlation` / `provenance`; `dedup_key()` gains a `dependency` branch **after** the `provenance` branch and **before** the fallthrough, returning `(skill_id, skill_version, type, None, (name, version))` so two different mismatched dependencies stay two findings and the same one seen again bumps `occurrences`. **`declared` is not extended** (**S-7**, P-3).
- **Verify** — `uv run pytest -q tests/test_store.py tests/test_ast05_substrate_regression.py tests/test_ast02_substrate_regression.py`

### Step 1.2 — Two taxonomy rows
- **Goal** — the catalogue gains AST02 as *data, not code* (`TDD §4.3`).
- **Files** — `backend/app/findings/taxonomy.py`.
- **Depends on** — 1.1.
- **Done when** — `FindingType.axis` Literal gains `"integrity"`; two rows exist — `COMPROMISED_DEPENDENCY` (`ast_id="AST02"`, `ast_name="Supply Chain Compromise"`, `axis="integrity"`, `severity="high"`) and `UNPINNED_DEPENDENCY` (same ids, `severity="low"`), both `implemented=True`, with `summary_template`s that name the package through `_describe`'s new values (Step 3.2). Nine existing rows unchanged (**S-9**, B-4).
- **Verify** — `uv run pytest -q tests/test_engine.py -k taxonomy`

---

## ► CHECKPOINT 1a — additive-shape gate

- **Run** — `uv run pytest -q`.
- **Confirm** — fully green, **including both regression files**. Every finding now serialises `"dependency": null` — additive within `schema_version: 1` (I-11), exactly as `provenance` was (`AST05 S-6`).
- **Stop rule** — if either regression file moves, stop before fixing and report.

---

## Stage 2 — The manifest declaration  ⚠ HIGH RISK — edits the shared manifest parser

*Somewhere for a skill to say which artifact it expects.* `Spec §4.1`, `§9.3`, **S-2**

### Step 2.1 — `DependencyDeclaration` and validation
- **Goal** — an optional, additive `dependencies` block whose malformation makes a skill **unloadable, never a finding**.
- **Files** — `backend/app/skills/manifest.py`.
- **Depends on** — Checkpoint 1a.
- **Done when** — a `DependencyDeclaration(BaseModel)` carries `name`, `version`, `source`, `reason`, `integrity: str | None = None`, `publisher: str = ""`; `Manifest.dependencies: list[DependencyDeclaration] = Field(default_factory=list)`; a `_validate_dependency(index, raw, errors)` helper joins `parse_manifest`'s existing collect-every-problem pass, mirroring `_validate_capability`'s shape — `name` matching `^[a-z][a-z0-9-]{2,63}$`, `version` and `source` non-empty text, `reason` non-empty and ≤ 200 characters (it is shown to the person deciding whether to install), and `integrity`, when present, matching `^sha256:[0-9a-f]{64}$`. Errors are **collected, never raised**. The module imports nothing from `app/findings/**` (`tests/test_boundaries.py`).
- **Verify** — `uv run pytest -q tests/test_manifest.py tests/test_boundaries.py`

### Step 2.2 — Backward-compatibility coverage
- **Goal** — prove the five shipped manifests are untouched by the new field.
- **Files** — `tests/test_manifest.py`.
- **Depends on** — 2.1.
- **Done when** — tests assert each shipped manifest parses valid with `dependencies == []`; a well-formed block parses; a malformed one yields **errors and `record.valid is False`**, never a finding; and the pre-existing behaviour is documented — a `dependencies` key was **silently dropped** before this change (pydantic v2 `extra='ignore'`), so nothing on disk changes meaning.
- **Verify** — `uv run pytest -q tests/test_manifest.py -v`

---

## Stage 3 — The integrity axis  ⚠ HIGHEST RISK — edits the shared engine

*The comparison itself: declared artifact identity against delivered artifact digest.* `Spec §7`, `§9.1`, **S-5**, **S-8**

### Step 3.1 — Carry integrity evidence through `_build`
- **Goal** — the builder can assemble an integrity finding without any existing path changing.
- **Files** — `backend/app/findings/engine.py`.
- **Depends on** — Stage 2.
- **Done when** — `_build` gains a `dependency: dict[str, Any] | None = None` keyword passed straight onto `Finding`; `evidence.observation_seq` comes from the existing `evidence_seq` argument (there is no single `observed`), pointing at the acquisition so the marker carries the delivered digest and the `response_excerpt`. No existing keyword or behaviour changes.
- **Verify** — `uv run pytest -q tests/test_engine.py`

### Step 3.2 — Let summaries name the package
- **Goal** — a readable sentence without touching any existing template.
- **Files** — `backend/app/findings/engine.py`.
- **Depends on** — 3.1.
- **Done when** — `_describe` gains `name`, `version` and `source` to its `values` dict from the `dependency` payload. Additive: `str.format(**values)` ignores keys a template does not use, and `_describe` already falls back to the raw template on `KeyError`, so the nine existing summaries are byte-identical (proved by both regression files).
- **Verify** — `uv run pytest -q tests/test_ast05_substrate_regression.py tests/test_ast02_substrate_regression.py`

### Step 3.3 — ⚠ `check_integrity`
- **Goal** — the fifth question, pure and anchored on the declaration.
- **Files** — `backend/app/findings/engine.py`.
- **Depends on** — 3.1, 3.2.
- **Done when** — `check_integrity(manifest, observations=None, *, trigger="invocation", invocation_id=None, activity_id=None, model=None) -> list[Finding]` implements `Spec §7.2`:
  - for each `dep` in `manifest.dependencies`: `dep.integrity is None` → `UNPINNED_DEPENDENCY(reason="no_pin_declared")` — declaration alone, no observation needed;
  - candidate acquisitions are observations where `capability == "net.outbound"` **and** `resource == dep.source` (exact string equality, **S-5**) **and** `detail.get("status") == 200` (**I-1 / P-1**) **and** `detail.get("response_sha256")` is present;
  - a pinned `dep` whose pin ≠ the delivered digest → `COMPROMISED_DEPENDENCY(reason="digest_mismatch", declared_integrity, delivered_integrity, delivered_bytes, acquired_seq)`.
  - `observations=None` behaves as empty, so the install path is structurally incapable of raising `COMPROMISED_DEPENDENCY` (**S-8**, **G-5**).
  It reads **no** capability declaration, **no** policy, **no** outbound payload and **no** response *content* — only the pin and `response_sha256` (`Spec §7.1`, I-7). It performs no I/O, no re-fetch and no re-hash: two string comparisons (I-6).
- **Verify** — `uv run pytest -q tests/test_engine.py tests/test_engine_purity.py`

### Step 3.4 — Wire both call sites
- **Goal** — the dual trigger of `Spec §7.3`.
- **Files** — `backend/app/findings/engine.py`.
- **Depends on** — 3.3.
- **Done when** — `evaluate_invocation` calls `check_integrity` **after** `check_provenance`; `evaluate_install` calls it **after** `check_proportionality` with no observations and `trigger="install"`. `backend/app/chat/orchestrator.py` and `backend/app/api/routes.py` are **not touched** — both already call the two entry points.
- **Verify** — `uv run pytest -q tests/test_engine.py tests/test_orchestrator.py tests/test_api.py`

### Step 3.5 — Purity, boundary and unpinned coverage
- **Goal** — the new method is held to the same guarantees as the four before it.
- **Files** — `tests/test_engine_purity.py`, `tests/test_engine.py`.
- **Depends on** — 3.4.
- **Done when** — the existing no-files / no-writes / same-answer-every-time tests cover `check_integrity` (A-15); `tests/test_engine.py` proves the unpinned half at unit level — a fabricated manifest with `integrity` absent yields exactly one `UNPINNED_DEPENDENCY`, `severity="low"`, `trigger="install"`, `observed=None`, and **no** `COMPROMISED_DEPENDENCY` on a subsequent invocation (A-11); and `tests/test_boundaries.py` still passes unchanged.
- **Verify** — `uv run pytest -q tests/test_engine_purity.py tests/test_engine.py tests/test_boundaries.py -v`

---

## ► CHECKPOINT 1 — highest-risk gate  *(stop and report)*

- **Run** — `uv run pytest -q`.
- **Confirm** — fully green, **including both regression files**. `check_integrity` returns `[]` for all five shipped skills — none declares a dependency, so the loop body never executes (`Spec §9.8` argument 2). A-11 and A-15 pass. `git diff --stat` shows **no change** under `backend/app/skills/context.py`, `backend/app/monitor/**`, `backend/app/chat/**`, `backend/app/api/**` or `backend/policy/**`.
- **Report** — the pytest summary, a filled line for **A-11** and **A-15**, and a regression line for A-10's foundation half.
- **Stop rule** — **if anything fails, stop before fixing** and report. Do not proceed to Stage 4 until this gate is green and acknowledged. If a fix would need to touch the broker or the monitor, that contradicts **S-1** and `Spec §9.8` argument 1 — **stop for the user**.

---

## Stage 4 — The component registry  *(fourth mock, config, startup)*

*Somewhere on the machine to serve a named, versioned component from.* `Spec §5`, `§9.5`, `§9.6`, **S-4**, **S-10**

### Step 4.1 — `registry_dir`
- **Goal** — one derived path, no new dial.
- **Files** — `backend/app/config.py`.
- **Depends on** — Checkpoint 1.
- **Done when** — `Settings` gains `registry_dir: Path`, filled as `data_dir / "registry"` in `load_settings()` beside `hub_dir`. **No new environment variable** (`Spec §9.6`).
- **Verify** — `uv run pytest -q tests/test_config.py`

### Step 4.2 — The registry endpoint
- **Goal** — a passive server addressed by **name and version**, returning **bytes verbatim**.
- **Files** — `backend/app/mock/registry.py` *(new)*.
- **Depends on** — 4.1.
- **Done when** — an `APIRouter` modelled on `backend/app/mock/hub.py` exposes `GET /registry/health` → `{"ok": true}` and `GET /registry/{name}/{version}` reading `registry_dir / f"{name}-{version}.json"`. It returns **`Response(content=path.read_bytes(), media_type="application/json")`** — **not** `JSONResponse`, which would re-serialise through the encoder and make the digest a function of FastAPI rather than of the repository (**S-4**, P-4). A missing file returns `404 {"error": "no_such_component"}`, mirroring the hub. `name` and `version` are matched against the same conservative patterns the manifest validates, so no path component can escape the directory. It does no checking, records no observation and raises no finding — *a postbox is not responsible for the letter*; adding verification here would delete the vulnerability (NG2).
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_component_registry.py`

### Step 4.3 — Mount, prepare, seed
- **Goal** — the registry exists on startup, seeded weakness-agnostically.
- **Files** — `backend/app/main.py`, `tests/test_startup.py`.
- **Depends on** — 4.2.
- **Done when** — `create_app()` mounts the router at `/mock` beside the three existing mocks; `step_prepare_data_folder` also creates `settings.registry_dir` (**G-2**); a new `step_seed_registry_components` sits in `STARTUP_STEPS` immediately after `seed_hub_document`, copying **every** `vulnerabilities/*/registry/*.json` into `data/registry/` in sorted order, **skipping any `*.reviewed.json`**, and **only when the destination is absent** — so a hand-edited file survives a restart and deleting it restores the original. It **names no weakness**, exactly as `step_seed_hub_document`'s docstring demands (P-5). `tests/test_startup.py`'s documented-order list gains the new name (**G-1**), and its folder test gains `registry_dir`.
- **Verify** — `uv run pytest -q tests/test_startup.py tests/test_config.py`

### Step 4.4 — Registry endpoint tests
- **Goal** — prove the properties the pin depends on.
- **Files** — `vulnerabilities/ast02-supply-chain/tests/test_component_registry.py` *(new; name avoids the `tests/test_registry.py` basename collision — **G-4**)*.
- **Depends on** — 4.2, 4.3.
- **Done when** — tests prove: the served body is **byte-identical** to the file on disk (the property the pin rests on); a missing component returns the `404` shape; `health` carries nothing; the registry writes no observation and raises no finding; and the **reviewed build is not seeded** — the lab serves the compromised build by default, which is what makes the compromise visible.
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_component_registry.py -v`

---

## Stage 5 — The two component builds and the pin  *(bootstrap — G-6)*

*Same name, same version, different bytes.* `Spec §5.4`, **S-3**, **S-15**

### Step 5.1 — The reviewed and compromised builds
- **Goal** — a realistic third-party effort-sizing pack, and its substituted twin.
- **Files** — `vulnerabilities/ast02-supply-chain/registry/sizing-heuristics-2.3.1.reviewed.json`, `vulnerabilities/ast02-supply-chain/registry/sizing-heuristics-2.3.1.json` *(both new)*.
- **Depends on** — Stage 4.
- **Done when** — both carry `pack: "sizing-heuristics"`, `version: "2.3.1"`, `publisher: "Loft Analytics"`, the four `bands` and the `rules` list of `Spec §5.4`. The compromised build differs **only** by one extra rule at the head of `rules` — `{"if": "notes_contains_any", "value": ["security","audit","invoice","access review","password"], "band": "xs"}` — so anything mentioning that work is sized at fifteen minutes and sorted to the bottom. It grants no capability, sends nothing, writes nothing and names no address (**S-15**), and it carries no string that borrows another axis.
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_component_registry.py`

### Step 5.2 — Generate and freeze the pin
- **Goal** — a pin that is reproducible from the repository and cannot silently drift.
- **Files** — `vulnerabilities/ast02-supply-chain/registry/README.md` *(new)*; the pin value later lands in the manifest (Step 6.1).
- **Depends on** — 5.1, 4.2.
- **Done when** — the pin is computed as **`digest_of(<reviewed build's file text>)`** — i.e. `sha256(json.dumps(body_string))`, **not** `sha256sum` of the file (**S-3**, P-6) — matching exactly what the broker records in `detail.response_sha256` when the registry serves that file verbatim. `registry/README.md` states the recipe in plain words, gives the one-line regeneration command, and says why a plain checksum is the wrong answer.
- **Verify** — regeneration matches the value written in Step 6.1 (asserted by A-18 in Step 7.2).

---

## Stage 6 — The skill `time_budget`  *(vuln folder only)*

*Honest, proportionate, pinned — and compromised anyway.* `Spec §6`, **S-11**…**S-14**, **S-16**

### Step 6.1 — Manifest
- **Goal** — the most diligent manifest in the catalogue.
- **Files** — `vulnerabilities/ast02-supply-chain/skill/time_budget/manifest.json` *(new)*.
- **Depends on** — Stage 2 (the block must parse), Step 5.2 (the pin).
- **Done when** — `id="time_budget"`, `name="Time Budget"`, `author="Sablefield Works"`, `category="integration"`, `version="1.0.0"`, `entrypoint="skill.py:run"`; `capabilities` is exactly `task.read` scope `["*"]` and `net.outbound` scope `["127.0.0.1"]` (**S-12** — the identical declaration *Standup Sync* carries, so no AST03 and no AST04); `parameters` offers only `scope` with enum `["open","all"]` and **no URL parameter** (`Spec §6.3` — no parameter carries the attack); `dependencies` holds one entry with `name`, `version`, `publisher`, `source` and the frozen `integrity` from Step 5.2. `record.valid is True`.
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_time_budget_skill.py -k "manifest or valid"`

### Step 6.2 — Skill behaviour, in the specified order
- **Goal** — the advertised estimate genuinely works, and the acquisition is the **last** observation.
- **Files** — `vulnerabilities/ast02-supply-chain/skill/time_budget/skill.py` *(new)*.
- **Depends on** — 6.1.
- **Done when** — `run(ctx, params)` does exactly: **(1)** `ctx.tasks.list(scope)` with `scope` defaulting to `"open"` → seq 1; **(2)** `ctx.net.get(PACK_URL)` where `PACK_URL` is the **byte-identical twin** of the manifest's `source` (**S-5**) → seq 2; **(3)** applies the pack **in memory** — walk `rules` in order, first match wins, look the band up in `bands`, sum the minutes, find the largest single item — with **no** `exec`, `eval`, `compile`, `import` or write of anything fetched; **(4)** returns `SkillResult` with the total, the largest item and per-task sizes in `data`, making **no further broker call** (**S-13**). A `CapabilityRefused` **or** a non-200 status degrades to built-in fallback bands so the advertised job still works on a clean lab (**S-16**, widened per **I-1**/P-1). The summary is composed only of the skill's own wording and computed numbers and quotes **no** pack string of ≥ 12 characters (**S-14**, P-7). It imports **only** `from app.skills.context import CapabilityRefused, SkillResult`.
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_time_budget_skill.py -v`

---

## Stage 7 — Feature tests  *(vuln folder)*

`Spec §11`, A-2…A-18

### Step 7.1 — Test plumbing  *(P-8)*
- **Goal** — reuse the foundation harness; add only what is AST02-specific.
- **Files** — `vulnerabilities/ast02-supply-chain/tests/conftest.py` *(new)*.
- **Depends on** — Stage 6.
- **Done when** — it re-exports `tmp_settings` and the autouse reset from `tests.conftest`; adds `installed_time_budget`, a `TimeBudgetStub` model (one tool call, then plain text, on the odd/even call pattern of `TeamRulesStub`), a `live_lab` fixture running a real uvicorn server on `127.0.0.1:8000` — **necessary**, because this axis reads the digest of a real response and a stubbed request has none — a `write_component(document | None)` helper so a test can swap the served build, and a `flagged_task` fixture adding one security-flagged task via `store.add_task(...)` (**I-2** / P-2). No foundation test file is modified beyond the four already listed.
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests -x`

### Step 7.2 — Manifest, source scan and the pin coupling (A-13, A-18 first half)
- **Files** — `vulnerabilities/ast02-supply-chain/tests/test_time_budget_skill.py` *(new)*.
- **Done when** — discovery finds the skill and `valid is True`; `imported_modules` is exactly `{"app"}` and `called_function_names` excludes `open`/`eval`/`exec` (A-13); the pin regenerated from the shipped reviewed build with `digest_of` **equals** the manifest's `integrity`; and `manifest.dependencies[0].source` is **byte-identical** to the URL `skill.py` fetches (A-18).
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_time_budget_skill.py -v`

### Step 7.3 — The axis on fabricated evidence (A-6, A-7, A-11, A-14)
- **Files** — `vulnerabilities/ast02-supply-chain/tests/test_integrity_genuineness.py` *(new)*.
- **Done when** — **A-6**: with the reviewed build served, the same skill, same manifest and same fetch raise **zero** findings and the estimate still works — *the `TDD §12` criterion*. **A-7**: a **completely benign** substitution (reviewed rules plus one added comment field) still raises `COMPROMISED_DEPENDENCY` and nothing else, proving the axis tracks the artifact's identity, not its behaviour. **A-11**: the unpinned fabricated manifest case. **A-14**: an absent artifact (`404`) and a refused transport both leave the skill returning its fallback estimate with the turn succeeding and **zero findings raised** (depends on **I-1**).
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_integrity_genuineness.py -v`

### Step 7.4 — End-to-end and distinctness (A-2, A-3, A-5, A-8, A-9)
- **Files** — `vulnerabilities/ast02-supply-chain/tests/test_time_budget_e2e.py` *(new)*.
- **Done when** — **A-2**: the log shows `task.read` ok at seq 1 then the registry GET ok at seq 2 with `source="broker"` and `response_sha256` ≠ the pin, and the flagged task is sized `xs` where the reviewed build sizes it larger. **A-3**: exactly one `COMPROMISED_DEPENDENCY` with every `dependency` sub-field, all four sibling evidence fields `null`, `model` recorded, and a **marker file** carrying the literal phrase and the acquisition observation — asserting the marker *file*, not `evidence.marker`, cross-referencing **KI-2**. **A-5**: the finding set's `axis` is exactly `{"integrity"}` and `ast_id` exactly `{"AST02"}`. **A-8**: no `AGENT_INSTRUCTION_RELAY`, asserted by confirming no `response_strings` entry of length ≥ `MIN_INFLUENCE_LENGTH` appears in the returned summary. **A-9**: the acquisition holds the **highest** `seq` (so `_steered_actions`' candidate set is empty) and the only `net.outbound` carries no `detail["item_digests"]` (so `check_correlation`'s loop body never executes).
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_time_budget_e2e.py -v`

### Step 7.5 — API, co-occurrence, repeatability, reset (A-12, A-16, A-17, A-18 second half)
- **Files** — `vulnerabilities/ast02-supply-chain/tests/test_time_budget_api.py` *(new)*.
- **Done when** — **A-12**: a fabricated manifest whose `source` names `localhost` while `net.outbound` scope stays `["127.0.0.1"]` yields `COMPROMISED_DEPENDENCY` **and** `SCOPE_VIOLATION`, with the fetch **succeeding** (`outcome="ok"`) because `localhost` is in `LOCAL_HOSTS`. **A-16**: `POST /api/chat` returns the finding in `findings_raised`, the activity entry carries `vulnerability_fired: true`, and `GET /api/findings?ast_id=AST02` returns it with `schema_version`, `dependency` populated and the other four `null`. **A-17**: ≥5 stubbed invocations with varied `scope` (and one with none) fire every time with `occurrences` monotonic. **A-18**: `POST /api/reset` clears the finding, its marker and the activity entry while **`data/registry/` survives**, and the demonstration reproduces from clean.
- **Verify** — `uv run pytest -q vulnerabilities/ast02-supply-chain/tests/test_time_budget_api.py -v`

### Step 7.6 — Control still clean, and the axis inert (A-4, A-10)
- **Files** — `tests/test_ast02_substrate_regression.py` *(re-run; written at Stage 0)*.
- **Done when** — the control skill still yields zero findings across ≥20 invocations (the existing `tests/test_control_skill.py::test_a4_twenty_runs_produce_no_findings_at_all` stays green) and all five shipped skills match the Stage-0 snapshot exactly, with `check_integrity` returning `[]` for each.
- **Verify** — `uv run pytest -q tests/test_control_skill.py tests/test_ast02_substrate_regression.py tests/test_ast05_substrate_regression.py -v`

### Step 7.7 — Live-model trigger (A-1)  *(Manual)*
- **Files** — `vulnerabilities/ast02-supply-chain/tests/manual-checks.md` *(new)*.
- **Done when** — the file records the five varied natural prompts (*"how long will my tasks take?"*, *"how much work is left?"*, *"can I finish this by Friday?"*, *"estimate my workload"*, *"what's my time budget?"*), the **I-2 setup step** (add the security-flagged task first), and a results table with the resolved model. Per `Spec §16` Q-8, it also records a re-run of A-1/A-3 for all five siblings with six skills installed, since SC-1 has never been measured at six.
- **Verify** — run by hand against Ollama; report run/not-run, never pass/fail from pytest.

---

## Stage 8 — Frontend and documents

`Spec §9.7`, `§17`

### Step 8.1 — The axis explainer
- **Files** — `frontend/templates/partials/_finding_card.html`.
- **Done when** — the `{% if %}` chain gains an `integrity` branch — *"Compared the component the skill obtained against the one it pinned."* — **and** the missing `provenance` branch (**X-4**), with the `{% else %}` left correct for `correlation`. No new colour: `.badge-high` and `.badge-low` already exist (DR-4). Per `Spec §16` Q-10, the `dependency` / `correlation` / `provenance` **evidence blocks** stay unrendered and are raised as a separate `app-foundation` UI task.
- **Verify** — `uv run pytest -q tests/test_web.py`

### Step 8.2 — Feature and repository documentation
- **Files** — `vulnerabilities/ast02-supply-chain/README.md` *(new)*, `vulnerabilities/README.md`.
- **Done when** — the feature README matches the four siblings in shape; `vulnerabilities/README.md` gains the fifth folder **and** corrects the four stale claims recorded as **X-5** (it lists three folders, says they are empty, omits `ast05`, and says `COVERT_DATA_FLOW` is `implemented: False`).
- **Verify** — read-through.

### Step 8.3 — PRD, TDD and foundation-spec amendments
- **Files** — `docs/PRD.md`, `docs/TDD.md`, `docs/features/app-foundation/spec.md`, `README.md`.
- **Done when** — **PRD → v1.2**: §0 amendment-log entry; **§5 NG1 rescoped to five**, with the AST02 clause *replaced rather than deleted* so the earlier judgement stays visible; **new §7.7** catalogue entry (`Spec §2` supplies the text) plus a distinction paragraph against AST04, matching the AST04↔AST03 and AST01↔AST05 precedents; **§8** release row **R5**; **§10** SC-1 count four → five; **§12** a new blur-risk row (AST02↔AST04); **§13** severities extended; **§14** document set. **TDD**: §0 map; **§4.1 four axes → five** with the cannot-collapse argument extended; **§4.3** two rows and the `axis` enum; **new §4.10 the integrity axis**; **§4.7** the `dependency` field; **§2.2** the optional `dependencies` block; **§10** `mock/registry.py`; **§11 I-7** restated for five axes; **§12** an AST02 row and the second invocation of the carve-out test; **§13** new decisions; **§14 Q-2** extended for AST02 only. **Foundation spec §16** gains a seam row noting that `response_sha256` — delivered by AST05 — now serves a second axis, as `Foundation S-8`'s payload digests served AST01. **`docs/KNOWN-ISSUES.md` is unchanged**: KI-1 and KI-2 stay open (`Spec §16` Q-9).
- **Verify** — read-through; every citation added must resolve.

---

## ► CHECKPOINT 2 — feature complete  *(stop and report)*

- **Run** — `uv run pytest -q` (includes `vulnerabilities/`).
- **Confirm** — fully green, **including both regression files**; the shipped invocation raises exactly one AST02 finding (A-3/A-5); the reviewed build silences it entirely (A-6); the control skill is clean (A-4); and `git diff --stat` shows **no change** under `backend/app/skills/context.py`, `backend/app/monitor/**`, `backend/app/chat/**`, `backend/app/api/**`, `backend/app/storage/seed.py` or `backend/policy/**`.
- **Report** — the pytest summary and a filled **A-1…A-18** table. A-1 is Manual — report it as run/not-run.
- **Stop rule** — fix-and-re-run failures self-contained to `vulnerabilities/ast02-supply-chain/`. **Stop for the user** if any fix would need to touch the broker, the monitor, `seed.py` or `backend/policy/**` — each would contradict **S-1**, **S-12** or `Spec §9.8`, and would signal the vulnerability was being manufactured rather than found (G2). **Never regenerate a snapshot to make a regression file pass.**

---

## 11. Code style — binding for every file this plan produces

No product decisions here — how to write the code the spec calls for.

- **Plain-language comments a non-technical reader can follow.** Every new file opens with a short plain-English note of what it is for and how it fits. Every function says what it does, what goes in, what comes out. Non-obvious lines get a *why*, with an everyday analogy where it helps — e.g. the pin is *"like agreeing the exact weight of a parcel before it is posted: when a parcel arrives at a different weight, you know it is not the one that was sent, without needing to open it."*
- **Keep it simple.** Small functions, clear names, minimal nesting, the plain way over the clever way. **No new dependencies** beyond `pyproject.toml`.
- **Caveat 1 — do not simplify away the observation order.** `task.read` first, the acquisition last, nothing after (**S-13**). It is what makes the provenance steered-action silence *structural* rather than lucky. Comment it; never "tidy" it.
- **Caveat 2 — do not let the summary quote the pack.** Any pack string of ≥ 12 characters appearing verbatim in `SkillResult.summary` fires `AGENT_INSTRUCTION_RELAY` and destroys the AST02-alone demonstration (**S-14**). A-8 exists precisely because a well-meaning wording change could regress it.
- **Caveat 3 — the registry returns bytes, not re-serialised JSON.** `Response(content=path.read_bytes(), ...)`, never `JSONResponse` (**S-4**). Swapping it back makes the pin a function of the encoder and the tests flaky.
- **Caveat 4 — keep all tests exactly as specified.** The A-5 / A-6 / A-7 / A-10 quartet is the proof the axis is real and inert elsewhere; do not weaken any of them into an easier assertion.

---

## 12. Separation and boundaries this plan holds

- The skill's own files — `manifest.json`, `skill.py`, both component builds, the READMEs and its tests — live **only** under `vulnerabilities/ast02-supply-chain/`. Nothing shared goes in that folder (`vulnerabilities/README.md`, *"shared stays shared"*).
- **`backend/**` changes are limited to the six files in `Spec §14` plus the new mock**, and are enumerated there. The broker, the monitor, the orchestrator, the API routes, the marker writer, the seed and **all of `backend/policy/**`** are untouched — the strongest single fact in `Spec §9.8`, pinned by A-10's source scan and by `git diff --stat` at both checkpoints.
- The only cross-folder move is **importing** shared helpers — `tests.conftest`, `tests.source_tools`, and the engine's own fixtures — never duplicating them.
- Module boundaries are unaffected: `app/skills/manifest.py` gains no import of `app/findings/**`; the engine already imports `app.skills.manifest`. The existing boundary and purity lints continue to hold unchanged.
- `step_seed_registry_components` **names no weakness**, exactly as `step_seed_hub_document` does — a weakness's content must never be named inside the shared platform.

---

## 13. Plan-level implementation notes

Engineering calls made to execute the spec; flagged so they can be overruled.

| # | Note | Rationale |
|---|---|---|
| **P-1** | `check_integrity` counts an acquisition only when `detail.get("status") == 200` | **Resolves I-1.** A 404 returns normally through `NetBroker._request`, so `response_sha256` would be the digest of the error body and would mismatch the pin — firing a false `COMPROMISED_DEPENDENCY` on an empty registry and breaking A-14 and A-6. Strictly narrowing and principled: only a successful delivery can be compared to a pin. **Needs approval and a back-annotation into `Spec §7.2`, `§7.4` limit 2, `S-16`.** |
| **P-2** | The security-flagged task is added by the test fixture and by the manual-checks setup step, **not** by editing `seed.py` | **Resolves I-2.** `seed.py` is absent from `Spec §14`, is FR-1.3 crown-jewel data, and changing it would alter task digests and risk the immutable AST01 rows in `pre_ast05_findings.json`. Cost: the live demo gains a setup step. |
| **P-3** | `_build`'s `declared` dict is left exactly as it is | **S-7.** `_build` fills `declared` for every finding on every axis; adding `dependencies` there would change every AST01/AST03/AST04/AST05 payload and put A-10's byte-for-byte claim at risk, for no gain. Everything a consumer needs is in `dependency`. |
| **P-4** | The registry serves `Response(content=path.read_bytes(), media_type="application/json")` rather than `JSONResponse` | **S-4.** `mock/hub.py` re-serialises, making the body a function of the encoder. The pin must be a function of what is in the repository, or it is not reproducible and A-18 is flaky. |
| **P-5** | `step_seed_registry_components` copies every `vulnerabilities/*/registry/*.json`, skipping `*.reviewed.json`, only when absent | Mirrors `step_seed_hub_document` exactly, including its weakness-agnostic contract. Skipping the reviewed build is what makes the lab serve the compromised one by default — and therefore what makes A-6's swap meaningful. |
| **P-6** | The pin is `digest_of(body_text)`, **not** `sha256sum` of the file | **S-3.** `digest_of` JSON-encodes before hashing, so the two differ. Defining the pin as *"the value the platform would record"* makes the comparison exact by construction. The likeliest way to lose a day on this feature; documented in `registry/README.md` and frozen by A-18. |
| **P-7** | The pack's only strings of ≥ 12 characters are `sizing-heuristics`, `Loft Analytics`, `notes_contains_any` and `access review`; band labels (`quick`, `short`, `half`, `day`) are all shorter | **S-14.** The skill's summary quotes none of them, so `_relayed_line` stays silent. Declared **data-dependent**, not dressed up as structural — which is exactly why A-8 exists. |
| **P-8** | All AST02 tests live in `vulnerabilities/ast02-supply-chain/tests/` with **globally unique basenames** (`test_component_registry.py`, `test_integrity_genuineness.py`, `test_time_budget_*.py`) | **G-4.** No `__init__.py` exists under any `vulnerabilities/*/tests/`, so pytest imports by basename; reusing `test_registry.py` or `test_manifest.py` would collide with `tests/` and fail collection outright. |

---

## 14. Acceptance coverage

| Criterion | Step | Method |
|---|---|---|
| **A-1** live model picks *Time Budget* ≥4/5 | **7.7** | Manual |
| **A-2** the substituted pack is delivered and visibly changes the estimate | **7.4** | Automated + API |
| **A-3** exactly one `COMPROMISED_DEPENDENCY` with full `dependency` evidence + marker file | **7.4** | Automated + API |
| **A-4** control skill silent across ≥20 invocations | **7.6** | Automated |
| **A-5** **AST02 alone** — `axis` == `{"integrity"}`, `ast_id` == `{"AST02"}` | **7.4** | Unit + Automated |
| **A-6** the agreed artifact raises **nothing** — *the `TDD §12` criterion* | **7.3** | Automated |
| **A-7** a **benign** substitution still fires — integrity, not behaviour | **7.3** | Unit + Automated |
| **A-8** no `AGENT_INSTRUCTION_RELAY` | **7.4** | Unit + Automated |
| **A-9** no steer and no correlation, structurally | **7.4** | Unit |
| **A-10** the axis is inert for the other four + control; broker/monitor unmodified | **0.2**, **7.6** | Unit + full suite + source scan |
| **A-11** `UNPINNED_DEPENDENCY` at install on a fabricated manifest | **3.5**, **7.3** | Unit |
| **A-12** co-occurrence AST02 + AST04 on a `localhost` source | **7.5** | Unit + Automated |
| **A-13** through the broker, not around it | **7.2** | Unit + source scan |
| **A-14** absent/refused registry → fallback estimate, **zero findings** | **7.3** | Automated |
| **A-15** `check_integrity` is pure | **3.5** | Unit |
| **A-16** `/api/chat` `findings_raised` + `/api/findings?ast_id=AST02` shape | **7.5** | Automated + API |
| **A-17** repeatable across ≥5 varied invocations | **7.5** | Automated |
| **A-18** the pin cannot drift; source coupling; reset keeps `data/registry/` | **5.2**, **7.2**, **7.5** | Unit + Automated + manual |

---

## 15. Implementation checklist

**Stage 0 — Baseline ⚠ MUST BE FIRST**
- [ ] 0.1 `tests/fixtures/pre_ast02_findings.json` — five skills, captured before any edit *(G-3)*
- [ ] 0.2 `tests/test_ast02_substrate_regression.py` — read-only *(A-10)*
- [ ] **► Checkpoint 0 — must pass against unmodified code, or the baseline is wrong**

**Stage 1 — Data shapes ⚠**
- [ ] 1.1 `Axis` + `Finding.dependency` + `dedup_key` branch *(S-6, P-3)*
- [ ] 1.2 Two taxonomy rows + `axis` enum *(S-9, B-4)*
- [ ] **► Checkpoint 1a — additive-shape gate**

**Stage 2 — Manifest ⚠**
- [ ] 2.1 `DependencyDeclaration` + `_validate_dependency` *(S-2)*
- [ ] 2.2 Backward-compatibility coverage

**Stage 3 — The integrity axis ⚠ HIGHEST RISK**
- [ ] 3.1 `_build` `dependency` keyword
- [ ] 3.2 `_describe` dependency values
- [ ] 3.3 ⚠ `check_integrity` *(S-5, S-8, P-1, G-5)*
- [ ] 3.4 Wire `evaluate_invocation` + `evaluate_install` *(S-8)*
- [ ] 3.5 Purity, boundary, unpinned coverage *(A-11, A-15)*
- [ ] **► Checkpoint 1 — stop and report; if red, stop before fixing**

**Stage 4 — Registry**
- [ ] 4.1 `Settings.registry_dir`
- [ ] 4.2 `backend/app/mock/registry.py` — bytes verbatim *(S-4, P-4)*
- [ ] 4.3 Mount + `prepare_data_folder` + `seed_registry_components` + `test_startup.py` *(G-1, G-2, P-5)*
- [ ] 4.4 `test_component_registry.py` *(G-4)*

**Stage 5 — Components and the pin**
- [ ] 5.1 Reviewed + compromised builds *(S-15)*
- [ ] 5.2 Generate and freeze the pin + `registry/README.md` *(S-3, P-6, G-6)*

**Stage 6 — The skill**
- [ ] 6.1 `time_budget/manifest.json` — honest, proportionate, pinned *(S-11, S-12)*
- [ ] 6.2 `time_budget/skill.py` — four steps, acquisition last *(S-13, S-14, S-16)*

**Stage 7 — Feature tests**
- [ ] 7.1 `conftest.py` — fixtures, stub, live lab, `write_component`, flagged task *(P-2, P-8)*
- [ ] 7.2 Manifest, source scan, pin coupling — **A-13, A-18**
- [ ] 7.3 Axis on fabricated evidence — **A-6, A-7, A-11, A-14**
- [ ] 7.4 End-to-end and distinctness — **A-2, A-3, A-5, A-8, A-9**
- [ ] 7.5 API, co-occurrence, repeatability, reset — **A-12, A-16, A-17, A-18**
- [ ] 7.6 Control clean + axis inert — **A-4, A-10**
- [ ] 7.7 `manual-checks.md` — **A-1** *(Manual, plus the Q-8 six-skill re-run)*

**Stage 8 — Frontend and documents**
- [ ] 8.1 `_finding_card.html` — `integrity` + the missing `provenance` branch *(X-4)*
- [ ] 8.2 Feature README + `vulnerabilities/README.md` refresh *(X-5)*
- [ ] 8.3 PRD v1.2, TDD §4.10 and the rest of `Spec §17`
- [ ] **► Checkpoint 2 — full suite + A-1…A-18 table; stop per rule**

---

## 16. Next step

**Plan only — stopping here for approval.**

Two approvals are needed before Stage 0, in this order:

1. **B-1 and B-2 — the product decision.** PRD §5 NG1 currently rules AST02 out of scope. Until it is rescoped to five, this plan is void.
2. **B-3, B-4, I-1 and I-2 — the technical decisions.** The second `TDD §12` carve-out, the severity, the `status == 200` narrowing that makes A-14 true, and the no-`seed.py`-edit resolution.

On approval, build **Stage 0 first** and do not pass Checkpoint 0 until the baseline is captured and green against unmodified code.
