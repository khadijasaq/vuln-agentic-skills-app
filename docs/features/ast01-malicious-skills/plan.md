# Feature: AST01 — Malicious Skills — Build Plan

| | |
|---|---|
| **Feature** | AST01 · Malicious Skills — the correlation axis, plus the skill that exercises it |
| **Derives from** | `docs/PRD.md` · `docs/TDD.md` · `docs/features/ast01-malicious-skills/spec.md` (approved) |
| **Status** | **Plan.** Not built. The App Foundation is built (411 tests); this feature is a near-pure addition on top of it. |
| **Scope** | AST01 only. One shared-substrate extension, one detector, one skill. **No change to the other axes, the other vulnerability skills, or the control skill** beyond the two edits called out in §12 P-4. |

**Citation convention.** Every step cites the AST01 spec as `Spec §n` / `Spec S-n`, the system design as `TDD §n`, and PRD requirements as bare `FR-n` / `SC-n` / `G-n` / `NG-n`. Acceptance tests **A-1…A-11** come from `Spec §9`. The App Foundation spec/plan are cited as `Foundation §n` / `Foundation A-n` / `Foundation S-n`. Plan-level engineering notes are **P-1…P-5** (§13). Line numbers (`engine.py L346`) are the current code at plan time and are guides, not contracts — the anchor is always the named function.

**Test-first bias.** The substrate change (Stage 1) and the detector (Stage 2) are written test-first, because the whole feature rests on them and they are proven on synthetic fixtures before any real skill exists. Two stages are marked **⚠ HIGH RISK**: Stage 1 (it edits already-working foundation broker code) and Stage 2 (the security-critical matching logic). Verification is **checkpointed, not per-step** — two consolidated gates (after Stage 2, after Stage 5), each stopping to report pytest output and a filled A-table.

**Code style — binding for every file this plan produces.** See §11. In one line: *comment in plain language a non-technical reader can follow, keep the code simple, and never simplify away the security-critical logic or the specified tests.*

---

## 0. What already exists (do not rebuild)

The foundation deliberately pre-built the seams (`Foundation §16`). This plan **references** them; it never copies them into the vuln folder.

- **Reserved taxonomy row** `COVERT_DATA_FLOW` — `backend/app/findings/taxonomy.py` L116-130, `axis="correlation"`, `severity="critical"`, `implemented=False`. *(seam D)*
- **Ordered observation log** with monotonic `seq`, refusals amended in place — `backend/app/monitor/observations.py`; digest helpers `digest_of` (canonical, `sort_keys=True`, L61-75) and `size_of` (L78-84). *(seam B, `TDD §11` I-5)*
- **`task.read` per-item digests** — `backend/app/skills/context.py` `TaskBroker.list` L161-167 already records `detail.item_digests` (`Foundation S-8`). The **egress side does not yet** — that gap is Stage 1.
- **Mock collector** — `backend/app/mock/collector.py` `POST /collector`, mounted at `/mock`; writes `data/collector/inbox/{ts}-{sender}.json`; returns `202`. *(seam C, FR-7.2)*
- **Marker writer** — `write_marker(finding, observation)` accepts any finding type; called from the orchestrator on first sighting. *(seam H, `Foundation S-10`)*
- **`Finding.correlation` field** — `backend/app/storage/models.py` L109 already modelled; only `_build` forces it to `None`. *(TDD §4.7)*
- **Auto-discovery** — `backend/app/skills/registry.py` `default_roots()` L182-194 scans every `vulnerabilities/*/skill/` folder. Adding the skill folder is the wiring. *(seam A, `Foundation S-18`)*

---

## Stage 1 — Egress substrate (Spec S-1)  ⚠ HIGH RISK — edits foundation Stage-4 code

*Land and fully verify the additive `net.outbound` per-item digests **before** anything consumes them.* `Spec §3.1`, `TDD §4.6`, `TDD §7`

Sub-steps are ordered so the digest helper is proven, then wired into the broker, then the whole foundation suite is re-run green before Stage 2 builds on it.

### Step 1.1 — Per-item egress digests on `net.outbound`
- **Goal** — a `net.outbound` observation carries a per-item fingerprint of the recognizable items inside its payload, computed the *same* way `task.read` fingerprints tasks, so a task read and later embedded in a send produces the **identical** digest on both sides.
- **Files** — `backend/app/monitor/observations.py` (new pure helper `payload_item_digests(payload) -> list[str]`, **P-1**); `backend/app/skills/context.py` (`NetBroker._request`, add `detail["item_digests"]` inside the `if payload is not None:` block, after `detail["sha256"]` at L370 and before `_record` at L372).
- **Depends on** — none (§0 helpers exist).
- **Done when** — `payload_item_digests` walks the payload and returns `digest_of(x)` for **every element of every array** it finds (recursively), reusing the canonical `digest_of` (so key-reorder and nesting don't change a task's digest); a `net.outbound` observation's `detail` now contains `item_digests` alongside the unchanged `method`/`bytes`/`sha256`; **the field is purely additive** — no existing field changes type or meaning and `schema_version` stays `1` (**S-1**, `TDD §7`); the digest of a task dict sent inside `{"kind": "backup", "items": [task, …]}` equals `digest_of(task)` from `TaskBroker.list`. *(Spec S-1, S-2; mirrors `TaskBroker.list` L166)*
- **Verify** — `uv run pytest tests/test_observations.py tests/test_broker_net.py -q -v`

### Step 1.2 — Extend the substrate test (A-18) to the egress side
- **Goal** — the foundation's substrate guarantee now covers `net.outbound`, and read↔send digest matching is proven at the broker level.
- **Files** — `tests/test_broker_net.py` (extend `test_a_blocked_attempt_still_records_what_it_wanted_to_send` and `test_the_fingerprint_of_a_blocked_send_matches_the_data_that_was_read`); a one-line note that this extends `Foundation A-18`.
- **Depends on** — 1.1.
- **Done when** — a `net.outbound` observation asserts `detail["item_digests"]` present, each a 64-hex digest; a read-then-send test asserts the **containment** property — the set of `item_digests` from a `task.read` intersects the `item_digests` of a subsequent `net.outbound` that embeds those tasks (read-side ∩ send-side ≠ ∅), and still intersects when the send **wraps/subsets/reorders** them. *(S-1, extends `Foundation A-18`, `TDD §4.6`; supports **A-9**)*
- **Verify** — `uv run pytest tests/test_broker_net.py -q -v -k "fingerprint or blocked or item_digests"`

### Step 1.3 — ⚠ Foundation green gate
- **Goal** — prove the additive change broke nothing before building on it.
- **Files** — none.
- **Depends on** — 1.1, 1.2.
- **Done when** — the **entire** existing suite is green; in particular `test_broker_net.py`, `test_observations.py`, `test_control_skill.py` (A-18 half), and any exact-shape assertions still pass with the new field present.
- **Verify** — `uv run pytest -q`
- **Why high risk** — this edits the capability broker, the foundation's highest-risk module (`Foundation §7`). A regression here corrupts the evidence trail every later stage depends on. The change is field-additive by design; the gate proves it.

---

## Stage 2 — Correlation detector (pure)  ⚠ HIGH RISK

*Prove the third axis on synthetic fixtures — including the axis-distinctness proofs — **before** the real skill exists.* `TDD §4.6`, `Spec §5`, `TDD §11` I-5, I-7

### Step 2.1 — Teach `_build` to carry a correlation finding
- **Goal** — the finding builder can produce a correlation finding that fills `correlation` and points its marker at the send line, without touching the truthfulness/proportionality fields.
- **Files** — `backend/app/findings/engine.py` (`_build`: add `correlation: dict[str, Any] | None = None` and an evidence-seq path; change L346 `correlation=None` → `correlation=correlation`; extend `_describe` L357-381 so a finding with neither `observed` nor `granted` still renders from `summary_template`).
- **Depends on** — none.
- **Done when** — `_build(..., correlation={...}, evidence_seq=<egress seq>)` returns a `Finding` whose `correlation` is set, whose `observed` and `granted` are **both `None`** (correlation is declaration- and grant-independent), and whose `evidence["observation_seq"]` is the **egress** observation's `seq` so `write_marker` tags the send line (**P-2**); `summary` comes from the `COVERT_DATA_FLOW` template. *(Spec §3.2, TDD §4.7)*
- **Verify** — `uv run pytest tests/test_engine.py -q -k "build or correlation"`

### Step 2.2 — Keep distinct covert flows distinct in dedup
- **Goal** — a covert-flow finding dedups sensibly: identical read/send pairs seen again increment `occurrences`; genuinely different pairs stay separate.
- **Files** — `backend/app/storage/models.py` (`dedup_key`, add an `elif self.correlation:` branch keyed on `tuple(correlation["observation_seqs"])`).
- **Depends on** — 2.1.
- **Done when** — a `COVERT_DATA_FLOW` finding no longer collapses to `(skill, version, type, None, None)`; two findings with different `observation_seqs` have different dedup keys, and two with the same pair share one (**P-3**). *(matches foundation dedup behaviour, `Foundation S-10`)*
- **Verify** — `uv run pytest tests/test_store.py -q -k dedup`

### Step 2.3 — Flip the taxonomy row to built
- **Goal** — `COVERT_DATA_FLOW` is a live, implemented finding type.
- **Files** — `backend/app/findings/taxonomy.py` (L129 `implemented=False` → `True`; remove the RESERVED comment L126-128).
- **Depends on** — none.
- **Done when** — `TAXONOMY["COVERT_DATA_FLOW"].implemented is True`; `axis`, `severity="critical"`, `ast_id="AST01"`, and `summary_template` are unchanged (**P-5** — the flag is declarative; the guard tests in 2.6 enforce the transition). *(Spec §5.4, `TDD §14 Q-2`)*
- **Verify** — `uv run pytest tests/test_engine.py -q -k "severit or implemented or taxonomy"`

### Step 2.4 — ⚠ **HIGH RISK** — `check_correlation`
- **Goal** — a pure check that raises `COVERT_DATA_FLOW` when task data read in an invocation is then egressed in the **same** invocation, reading **only** the ordered log.
- **Files** — `backend/app/findings/engine.py` (new method `check_correlation(self, manifest, observations, *, invocation_id, activity_id=None, model=None) -> list[Finding]`, defined near `check_unused_grants`/`evaluate_install`; add `findings.extend(self.check_correlation(...))` in `evaluate_invocation` between L269 and L270); `tests/test_engine.py` (a focused method-level test).
- **Depends on** — 2.1, 2.2, 2.3.
- **Done when** — the algorithm follows `Spec §5.2`: gather `reads` (`capability == "task.read"`, `outcome == "ok"`) and `egress` (`capability == "net.outbound"`, **any** outcome — intent counts); for each egress, intersect its `item_digests` with the union of `item_digests` from reads whose `seq` is **strictly less** (read-then-send ordering); a non-empty intersection raises one finding with `correlation={"observation_seqs": [read_seq, egress_seq], "matched_items": <count>}`; the method reads **no field of `manifest`** for its decision (declaration-independence, `TDD §11` I-7); it opens no file, calls no model, mutates nothing (`Foundation S-22`); a **refused** egress still correlates because its digest was recorded before the safety check (`TDD §11` I-3). *(S-2, S-3, `TDD §4.6`, I-5, I-7)*
- **Verify** — `uv run pytest tests/test_engine.py -q -v -k correlation`
- **Why high risk** — this is the security-critical matching logic. If ordering or digest-containment is wrong, the axis either misses real theft or fires on innocent skills (breaking A-4/SC-3). Keep it correct and thoroughly commented (§11); do not simplify the ordering or the containment away.

### Step 2.5 — Boundary and purity coverage for the new detector
- **Goal** — the new detector is provably inside the engine's purity/boundary envelope.
- **Files** — `tests/test_boundaries.py` / `tests/test_engine_purity.py` (add a positive assertion, no restructuring).
- **Depends on** — 2.4.
- **Done when** — because `check_correlation` lives in `backend/app/findings/engine.py`, the existing findings-folder loops (`test_the_findings_engine_never_touches_the_ai_model`, `test_deciding_opens_no_files`) **already** cover it — confirmed, no offender-loop change; **plus** a new assertion proves `check_correlation` reaches no manifest field for its verdict (declaration-independence). *(A-15, I-6, I-7)*
- **Verify** — `uv run pytest tests/test_boundaries.py tests/test_engine_purity.py -q`

### Step 2.6 — Flip the two foundation guard tests
- **Goal** — the tests that guaranteed correlation was *not* built now guarantee it *is*, kept meaningful.
- **Files** — `tests/test_engine.py` (update `test_the_combination_problem_is_listed_but_not_yet_built` and `test_the_combination_problem_is_never_raised_yet`, L359-377).
- **Depends on** — 2.3, 2.4.
- **Done when** — the "listed but not built" test asserts `implemented is True`; the "never raised" test is replaced by one asserting `evaluate_invocation` **does** raise a single `correlation` finding on an ordered `task.read`→`net.outbound` whose digests match, and **does not** on a read with no digest match. *(P-5)*
- **Verify** — `uv run pytest tests/test_engine.py -q -k "combination or correlation"`

### Step 2.7 — Detector unit tests: distinctness + matching (A-6, A-7, A-8, A-10)
- **Goal** — the axis is proven distinct and its matching rule proven on synthetic fixtures, with no real skill involved.
- **Files** — new `tests/test_correlation.py` (reuse `make_manifest` from `tests/test_engine.py`; a local observation builder that records `detail={"item_digests": [...]}` via `ObservationLog.record(..., detail=...)`).
- **Depends on** — 2.4, 2.5, 2.6.
- **Done when** — all pass:
  1. **A-6** — an honest `integration` manifest (`task.read` `*` + `net.outbound` `127.0.0.1`) with observations `task.read`(item_digests) then `net.outbound`(matching item_digests) yields **exactly one** finding: `type=COVERT_DATA_FLOW`, `axis=correlation`, `ast_id=AST01`, `severity=critical` — and **no** truthfulness or proportionality finding. *(→ AST01 alone; `TDD §11` I-7, `TDD §4.1`)*
  2. **A-7** — a **fabricated** manifest omitting `net.outbound`, same observations, yields **two** findings — `COVERT_DATA_FLOW` (correlation/AST01) **and** `UNDECLARED_CAPABILITY` (truthfulness/AST04) — each with its own evidence, and the correlation finding is **identical** to A-6's. *(→ AST01 + AST04; `TDD §11` I-7)*
  3. **A-8** — the covert egress wrapped as `{kind, items:[…]}`, a **subset**, and a **key-reordered** copy each still fire; a whole-body-`sha256`-only match would miss the wrapped/subset case (asserted by construction: whole-body `sha256` differs, `item_digests` intersect). *(S-1, S-2, `TDD §4.6`)*
  4. **A-10** — a **refused** `net.outbound` (`outcome="refused"`) still fires `COVERT_DATA_FLOW`. *(`TDD §11` I-3)*
  5. **Negatives** — read **after** send (egress `seq` < read `seq`) does not fire; a count-only egress carrying no task-item digests does not fire.
- **Verify** — `uv run pytest tests/test_correlation.py -q -v`

---

## ► CHECKPOINT 1 — highest-risk gate  *(stop and report)*

- **Run** — `uv run pytest -q`.
- **Report** — the pytest summary, and a filled table for **A-6, A-7, A-8, A-9, A-10** plus a foundation-regression line (all prior tests still green).
- **Stop rule** — **if anything fails, stop before fixing** and report. Do not proceed to Stage 3 until this gate is green and acknowledged.

---

## Stage 3 — The malicious skill `standup_sync`  *(vuln folder only)*

*A genuinely useful `integration` skill that also steals — acting **only** through the real brokers.* `Spec §4`, FR-1.3, FR-7.2

### Step 3.1 — Manifest
- **Goal** — an honest, believable `integration` manifest whose declaration is truthful and in-baseline.
- **Files** — `vulnerabilities/ast01-malicious-skills/skill/standup_sync/manifest.json`.
- **Depends on** — Checkpoint 1.
- **Done when** — `category="integration"`; declares `task.read` (scope `["*"]`) and `net.outbound` (scope `["127.0.0.1"]`), both inside the `integration` baseline (`backend/policy/capability_baselines.json`); `id="standup_sync"`, `author="Northwind Automations"`, `entrypoint="skill.py:run"`; passes manifest validation (`record.valid`). *(Spec §4.2)*
- **Verify** — `uv run pytest vulnerabilities/ast01-malicious-skills/tests -q -k "manifest or valid"`

### Step 3.2 — Skill behaviour
- **Goal** — the advertised standup works, and the covert full-task egress rides along, all through `ctx`.
- **Files** — `vulnerabilities/ast01-malicious-skills/skill/standup_sync/skill.py`.
- **Depends on** — 3.1.
- **Done when** — `run(ctx, params)` (a) reads open tasks via `ctx.tasks`, posts a small standup line (count + oldest) via `ctx.net`, and returns that as `SkillResult.summary` — the advertised job genuinely works; (b) then reads the **full** task list via `ctx.tasks` and POSTs it wrapped as `{"kind": "backup", "items": [...]}` to `http://127.0.0.1:8000/mock/collector` via `ctx.net`; (c) imports **only** `from app.skills.context import SkillResult` — no `os`, `socket`, `httpx`, `open`, or `subprocess`; the advertised line carries no task-content items (so only the covert send correlates, **S-6**). *(Spec §4.3, S-6; genuinely observed, never bypassed — Spec §4.4)*
- **Verify** — `uv run pytest vulnerabilities/ast01-malicious-skills/tests -q -k "behaviour or brokers"`

### Step 3.3 — Discovery and validity
- **Goal** — the platform finds and accepts the skill with no wiring.
- **Files** — `vulnerabilities/ast01-malicious-skills/tests/test_standup_sync_skill.py`.
- **Depends on** — 3.1, 3.2.
- **Done when** — `get_registry().discover_default()` includes `standup_sync`; its `SkillRecord.valid is True`; it appears in `installed()` after `install("standup_sync")`. *(`Foundation S-18`)*
- **Verify** — `uv run pytest vulnerabilities/ast01-malicious-skills/tests -q -k "discover or install"`

---

## Stage 4 — End-to-end, API, reset  *(vuln folder tests + config plumbing)*

*The theft fires through the LLM's own choice, is attributable via the API, and is fully reversible.* `Spec §9`, PRD §8 R2

### Step 4.1 — Test plumbing for the vuln folder  *(P-4)*
- **Goal** — the vuln folder's tests are collected and can reuse the shared fixtures, without touching foundation files.
- **Files** — `pyproject.toml` (`testpaths = ["tests", "vulnerabilities"]`); `vulnerabilities/ast01-malicious-skills/tests/conftest.py` (re-export `tmp_settings` and the autouse settings-reset from `tests.conftest`; add an `installed_standup_sync` fixture).
- **Depends on** — 3.1.
- **Done when** — `uv run pytest vulnerabilities -q` collects and runs the AST01 tests; the fixtures point at an isolated temp `data/`; **no foundation test file is modified by this step**. *(**P-4**)*
- **Verify** — `uv run pytest vulnerabilities -q`

### Step 4.2 — End-to-end exfiltration (A-2, A-3)
- **Goal** — an LLM-chosen invocation delivers the standup **and** lands the tasks in the collector, raising exactly one critical finding with a marker.
- **Files** — `vulnerabilities/ast01-malicious-skills/tests/test_standup_sync_e2e.py` (orchestrator + a stub model that chooses `standup_sync`, following `AskingModel`/`ScriptedModel` in `tests/test_orchestrator.py`).
- **Depends on** — 4.1, 3.2.
- **Done when** — after `run_turn`: `skill_invoked.skill_id == "standup_sync"`, `outcome == "ok"`, the reply is the advertised standup line; a file exists under `data/collector/inbox/` whose payload contains the tasks and is stamped with the invocation id; **exactly one** `COVERT_DATA_FLOW` finding is stored — `ast_id="AST01"`, `severity="critical"`, `correlation.observation_seqs` set, `model` recorded — and a marker file carrying `INTENTIONALLY_VULNERABLE_LAB_MARKER` was written; `activity.vulnerability_fired is True`. *(A-2, A-3, SC-2, FR-7.1, PRD §8 R2)*
- **Verify** — `uv run pytest vulnerabilities/ast01-malicious-skills/tests/test_standup_sync_e2e.py -q -v`

### Step 4.3 — API attribution (A-5)
- **Goal** — a scanner can attribute the theft to the exact prompt via the stable contract.
- **Files** — `vulnerabilities/ast01-malicious-skills/tests/test_standup_sync_api.py` (FastAPI `TestClient`, monkeypatched stub per `tests/test_api.py`).
- **Depends on** — 4.2.
- **Done when** — `POST /api/chat` returns `findings_raised` naming the turn's `COVERT_DATA_FLOW` finding; `GET /api/findings?ast_id=AST01` returns it in the promised shape carrying `schema_version`; the response contains no field not in the foundation contract (additive only). *(A-5, FR-6.3, `TDD §7`)*
- **Verify** — `uv run pytest vulnerabilities/ast01-malicious-skills/tests/test_standup_sync_api.py -q -v`

### Step 4.4 — Reset reversibility (A-11)
- **Goal** — the lab returns to clean and the theft reproduces from clean.
- **Files** — same API test module (a reset case).
- **Depends on** — 4.2.
- **Done when** — `POST /api/reset` clears findings, markers, activity **and** the collector inbox (`data/collector/inbox/` empty), re-seeds tasks, and preserves installed state; a second identical turn reproduces the finding and the collector delivery. *(A-11, `TDD §14 Q-4`, FR-7.5)*
- **Verify** — `uv run pytest vulnerabilities/ast01-malicious-skills/tests/test_standup_sync_api.py -q -k reset`

### Step 4.5 — Live-model trigger (A-1)  *(Manual)*
- **Goal** — a real model chooses the skill for its advertised purpose, unprompted to steal.
- **Files** — `vulnerabilities/ast01-malicious-skills/tests/manual-checks.md` (a short manual record, mirroring `Foundation manual-checks.md`).
- **Depends on** — 4.2.
- **Done when** — with Ollama running `llama3.1:8b`, **≥4 of 5** varied natural "post my standup / sync to the team" prompts cause the model to invoke `standup_sync`; the advertised standup line is returned each time; the covert delivery and finding appear. Record prompts, hits, and misses. *(A-1, SC-1, FR-3.1)*
- **Verify** — `Manual:` run `uv run uvicorn --app-dir backend app.main:app`, install *Standup Sync* in the Store, send the five prompts, confirm findings + `data/collector/inbox/`.

---

## Stage 5 — Control still clean (A-4 regression)

*The headline safety promise still holds after a third axis exists.* `Spec §9`, SC-3, `TDD §11` I-12

### Step 5.1 — Zero-findings regression
- **Goal** — the correlation detector never fires on the honest control skill.
- **Files** — none (re-run `tests/test_control_skill.py`).
- **Depends on** — all of Stage 2.
- **Done when** — `test_control_skill.py` A-4 still passes: `task_summary` over ≥20 invocations yields `store.load_findings() == []` and `count_markers() == 0` — it reads tasks but never egresses, so no `task.read`→`net.outbound` pair exists to correlate. *(A-4, SC-3, I-12)*
- **Verify** — `uv run pytest tests/test_control_skill.py -q -v`

---

## ► CHECKPOINT 2 — feature complete  *(stop and report)*

- **Run** — `uv run pytest -q` (now including `vulnerabilities/`).
- **Report** — the pytest summary and a filled **A-1…A-11** table.
- **Stop rule** — fix-and-re-run failures **self-contained to this feature**; **stop for the user only** if a fix would touch the foundation beyond the approved **S-1** change, or a test is still red after reasonable attempts. A-1 is Manual — report it as run/not-run, not pass/fail from pytest.

---

## 11. Code style — binding for every file this plan produces

No product decisions here — how to write the code the approved spec calls for.

- **Plain-language comments a non-technical reader can follow.** Every new file opens with a short plain-English note of what it is for and how it fits the app. Every function is explained in plain words: what it does, what goes in, what comes out. Non-obvious lines get a *why*, with an everyday analogy where it helps — e.g. the digest match is *"like comparing fingerprints to see whether the same tasks that were read are the ones that got sent out."*
- **Keep it simple.** Small functions, clear names, minimal nesting, the plain way over the clever way. **No new dependencies** beyond those already in `pyproject.toml`.
- **Caveat 1 — do not simplify away the security-critical logic.** The record-before-safety ordering (`TDD §11` I-3), the ordered-log correlation (I-5), the per-item digest matching (`Spec S-2`), and the module boundaries (broker never imports findings; only the orchestrator invokes skills; the engine stays pure) are load-bearing. Where the logic is unavoidably subtle — `payload_item_digests`, the `seq`-ordered containment in `check_correlation` — keep it correct and explain it thoroughly in comments rather than trimming it.
- **Caveat 2 — keep all tests exactly as specified.** The A-6/A-7 distinctness pair, the A-8 whole-body-would-miss construction, and the A-10 refused-still-correlates case are the proof the axis is real; do not weaken them into easier assertions.

---

## 12. Separation and boundaries this plan holds

- The skill's own files — `manifest.json`, `skill.py`, and its tests — live **only** under `vulnerabilities/ast01-malicious-skills/`. Nothing shared goes in that folder (`vulnerabilities/README.md`).
- Shared-platform changes — the `net.outbound` digests, `payload_item_digests`, `check_correlation`, the `_build`/`dedup_key`/taxonomy edits — land in `backend/**` and are **referenced** by the skill and its tests, never duplicated into the vuln folder.
- Module boundaries stay intact and are proven by the existing lints (`tests/test_boundaries.py`, `tests/test_engine_purity.py`), which automatically cover the new detector because it lives in `backend/app/findings/engine.py` (Step 2.5).
- Only two foundation **test** touch-points are sanctioned: extending A-18 for the egress side (Step 1.2) and flipping the two `COVERT_DATA_FLOW` guard tests (Step 2.6). No other foundation file changes.

---

## 13. Plan-level implementation notes

Engineering calls made to execute the approved spec; flagged so they can be overruled.

| # | Note | Rationale |
|---|---|---|
| **P-1** | `payload_item_digests(payload)` walks the payload and digests every array element (recursively), reusing canonical `digest_of` | The broker can't know which parts of an arbitrary payload are "tasks"; digesting every array element makes an embedded/wrapped/subset task match its read-side digest, which is exactly what `Spec S-2` needs — and it stays pure and testable in `observations.py` |
| **P-2** | Correlation findings set `evidence["observation_seq"]` to the **egress** seq while leaving `observed=None` | The marker must tag the send line, but `observed` belongs to the truthfulness axis; keeping it `None` preserves the axis-field discriminator (`TDD §4.7`) |
| **P-3** | `dedup_key` gains an `elif self.correlation:` branch keyed on `observation_seqs` | Without it every covert flow for one skill version collapses to a single row; keying on the seq pair keeps distinct read/send pairs distinct while identical repeats increment `occurrences` |
| **P-4** | `testpaths` extended to `["tests","vulnerabilities"]`; a vuln `conftest.py` re-exports the shared fixtures | The user's separation rule puts the skill's tests in the vuln folder, which isn't on the pytest path today; this is the minimal additive way to collect them with foundation test files untouched |
| **P-5** | `implemented=True` is treated as declarative; the flipped guard tests enforce the transition | The engine has no runtime gate on the flag today; the honest enforcement is the guard tests, so the flip is source-of-truth + test update, not a new code path |
| **P-6** | **Discovered in Stage 2: `host_glob` scope matching compared a host pattern against a full URL, so a truthfully-declared local send got a spurious `SCOPE_VIOLATION`.** Fixed in `backend/app/skills/scope.py` to match on the resource's hostname (spec **S-7**). A sanctioned foundation change beyond S-1, approved at Checkpoint 1 | AST01 is the first skill to declare a bounded `net.outbound` host scope, so it is the first to exercise this latent gap; without the fix A-6 ("AST01 alone") is unconstructible. Aligns truthfulness with the host-based baseline; no existing test changed |

---

## 14. Acceptance coverage

Every acceptance test in `Spec §9` maps to the step that proves it. **No test is unverified.**

| Test | Proven at | Kind |
|---|---|---|
| **A-1** live-model picks the skill ≥4/5 | **4.5** | Manual |
| **A-2** task data reaches the collector via LLM-chosen invocation | **4.2** | Automated |
| **A-3** exactly one `COVERT_DATA_FLOW`, critical, marker written | **4.2** | Automated |
| **A-4** control skill silent after the axis exists | **5.1** | Automated |
| **A-5** `/api/chat` `findings_raised` + `/api/findings?ast_id=AST01` shape | **4.3** | Automated |
| **A-6** honest manifest → **AST01 alone** | **2.7** ⚠ | Automated |
| **A-7** fabricated lying manifest → **AST01 + AST04**, two findings | **2.7** ⚠ | Automated |
| **A-8** per-item match on wrap/subset/reformat; whole-body would miss | **2.7** ⚠ | Automated |
| **A-9** `net.outbound` carries `item_digests` (extends `Foundation A-18`) | **1.2** | Automated |
| **A-10** refused egress still correlates | **2.7** | Automated |
| **A-11** reset clears finding/marker/activity/collector; reproduces clean | **4.4** | Automated |

**Two ⚠ high-risk stages:** Stage 1 (edits foundation broker code; gated by 1.3 + Checkpoint 1) and Stage 2.4/2.7 (the security-critical matching logic and its distinctness proofs). Each has its own named verification; none is bundled into a larger step.

---

## 15. Implementation checklist

**Stage 1 — Egress substrate ⚠**
- [ ] 1.1 `payload_item_digests` + `net.outbound` `item_digests` *(S-1, P-1)*
- [ ] 1.2 Extend A-18 to the egress side; containment test *(A-9)*
- [ ] 1.3 ⚠ Full foundation green gate

**Stage 2 — Correlation detector ⚠**
- [ ] 2.1 `_build` correlation + evidence-seq path *(P-2)*
- [ ] 2.2 `dedup_key` correlation branch *(P-3)*
- [ ] 2.3 Flip `COVERT_DATA_FLOW.implemented` → True *(§5.4)*
- [ ] 2.4 ⚠ `check_correlation` + call site *(S-2, S-3, I-5, I-7)*
- [ ] 2.5 Boundary/purity coverage + declaration-independence assertion *(A-15)*
- [ ] 2.6 Flip the two foundation guard tests
- [ ] 2.7 ⚠ `test_correlation.py` — **A-6, A-7, A-8, A-10** + negatives
- [ ] **► Checkpoint 1 — stop and report; if red, stop before fixing**

**Stage 3 — The skill (vuln folder)**
- [ ] 3.1 `standup_sync/manifest.json` — honest `integration` *(§4.2)*
- [ ] 3.2 `standup_sync/skill.py` — advertised + covert, brokers only *(§4.3, S-6)*
- [ ] 3.3 Discovery/validity test

**Stage 4 — E2E, API, reset**
- [ ] 4.1 `testpaths` + vuln `conftest.py` *(P-4)*
- [ ] 4.2 E2E exfiltration — **A-2, A-3**
- [ ] 4.3 API attribution — **A-5**
- [ ] 4.4 Reset reversibility — **A-11**
- [ ] 4.5 Live-model trigger — **A-1** *(Manual)*

**Stage 5 — Control still clean**
- [ ] 5.1 A-4 zero-findings regression
- [ ] **► Checkpoint 2 — full suite + A-1…A-11 table; fix self-contained, stop per rule**

---

## 16. Next step

**Plan only — stopping here for approval.** On approval, build Stage 1 first and do not pass Checkpoint 1 until it is green.
