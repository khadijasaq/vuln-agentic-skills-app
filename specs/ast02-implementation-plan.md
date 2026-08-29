# AST02 — Supply Chain Compromise: Implementation Plan

Planner: opencode (planning-only; no source, dependency, config, or spec was modified)
Plan date: 2026-08-29
Target: `vuln-agentic-skills-app` (TaskBot), branch `ast02`, HEAD `143396c`
Input: `specs/ast02-supply-chain-compromise.md` (REQ-01…REQ-09, Acceptance criteria, Out of scope, Open questions)

## 1. Summary

This plan implements REQ-01…REQ-09 from the AST02 supply-chain spec. It is organised into
**4 milestones** and **17 tasks** (T-01…T-17). Of the 17 tasks, **6 are BLOCKED** pending
open-question decisions:

- **BLOCKED-on-1** (registry mirror vs. explicit-source allowlist): T-15 (REQ-05).
- **BLOCKED-on-2** (is the AST05 hub document meant to stay attacker-editable): T-17
  (REQ-03).
- **BLOCKED-on-3** (are the mock "publishers" to be signed): T-10 (the sign-the-lab-artifacts
  half of REQ-09). The *verify mechanism* itself is planned READY (T-09).
- **BLOCKED-on-4** (uv hash-lock format vs. external hashed constraints): T-11 (REQ-01),
  T-13 and T-14 (pin-check halves of REQ-04).

Everything in M1 (foundations) and most of M2 (skill-channel provenance, excluding the
OQ3-gated signing step) is READY and can proceed immediately. M3's dependency work is
largely blocked until the pinning-format and registry-policy decisions land. M4 (hub) waits
entirely on OQ2. The **critical path** is the skill-channel provenance chain
T-01 → T-04 → T-05/T-06, because every downstream skill trust control composes with the
content-digest mechanism; the dependency-channel work is blocked at its root.

## 2. Drift

**None found.** HEAD is still `143396c` — the same commit the spec audited. Every
file:line reference the spec cites matches the current tree:

- `backend/app/skills/registry.py:320` → `def install`, `:338` → `store.set_installed`; `:206` → `_read_one_skill`; `:119` → `discover`; `:161` → `default_roots`; `:146-155` → duplicate-ID handling. ✔
- `backend/app/skills/host.py:98` → `spec_from_file_location`, `:126` → `exec(code, ...)`, `:79` → `_load_skill_module`, `:166` → `SkillHost`. ✔
- `backend/app/skills/manifest.py:263` → required-fields loop; `:227` → `parse_manifest`. ✔
- `backend/app/mock/hub.py:68` → `GET /hub/rules`, `:82` → read `data/hub/rules.json`. ✔
- `backend/app/main.py:89` → `step_seed_hub_document`, `:110-128` → copy logic; startup order at `:166-172`. ✔
- `backend/app/config.py:184` → `TASKBOT_MODEL` default `"llama3.1:8b"`. ✔
- `backend/app/llm/ollama_client.py:117-121,167-172` → model-by-tag usage. ✔
- `pyproject.toml:7-21` → unpinned `>=` ranges; `:32-34` → unpinned `hatchling`. ✔
- `README.md:54-55` → `ollama pull llama3.1:8b`. ✔
- Tests referenced by the acceptance criteria exist: `tests/test_registry.py`, `tests/test_host.py`. ✔

No plan correction was required; the plan builds against the audit's facts.

## 3. Constraints

1. **Lab preservation (binding).** TaskBot is a deliberately-vulnerable lab
   (`README.md:1-13`). This plan hardens the *platform channel* around the AST01/03/04/05
   weakness skills and the fetch-and-obey hub document; it does **not** remove, weaken, or
   suppress the demonstrated attacks. Where a requirement would suppress a demonstrated
   attack, the task is routed to Open question 2 rather than planned one-way (see T-17 and
   its conflict with `vulnerabilities/ast05-untrusted-external-instructions/tests/test_hub.py:48`).
2. **Out-of-scope carry-over (binding).** Anything in the spec's Out of scope stays out and
   is not smuggled in as a prerequisite: no SBOM/attestation pipeline, no MCP trust gates, no
   container/image supply chain, no functional-testing/deployment CI (REQ-04 is a
   supply-chain-hygiene gate only), and (because this phase is planning-only) no actual
   dependency changes are executed — only planned.
3. **REQ-10 gap (binding).** The spec's Open question 5 references a "REQ-10 (project-level
   agent-permission trust gate)" that is **never defined** in the Remediation requirements
   section. This plan does **not** invent REQ-10's content. It is recorded in §9 (Deferred)
   and in the blocked-work notes for OQ5, so that whoever resolves OQ5 writes the missing
   requirement before any work under it begins. No task in this plan claims REQ-10.

## 4. Dependency graph

Shared foundations pulled out as their own early tasks, because REQ-02/REQ-09 both need a
canonical content digest, and REQ-06/08/09 all write `backend/policy/*.json` and share a
loader.

**Shared foundations**
- **F1 — Canonical content digest** over a manifest object + every declared resource file
  (at least `manifest.json` + the `entrypoint` file). Used by REQ-02 (verify at install/run)
  and REQ-09 (sign over the same canonical digest). → T-01.
- **F2 — Policy-file loader** for `backend/policy/*.json` (allowlist, revocations,
  trusted-key set), shared by REQ-06/08/09. → T-02.
- **F3 — Fail-closed refusal path** through `SkillHost.invoke` (return an explicit
  INVALID / REFUSED result rather than proceeding to `exec`). Used by REQ-02 (run-time
  verify) and composed into REQ-08/09 refusals. → T-03.

**Ordering / prerequisites (before → after)**

| Before | After | Reason |
|---|---|---|
| T-01 (digest fn) | T-04, T-05, T-06, T-09 | REQ-02 install/run verify and REQ-09 signing operate on F1's canonical digest. |
| T-02 (policy loader) | T-07, T-08, T-09 | Allowlist / revocations / trusted-keys files all load via F2. |
| T-03 (fail-closed host path) | T-06, T-08, T-09 run-time refusal | Run-time digest/revocation/signature failures surface through the same refusal. |
| T-04 (manifest digest field) | T-05, T-06 | The host cannot fail closed on a digest that the manifest does not yet carry. |
| T-05 (install verify + persist) | T-06 () | Recorded digest must exist before run-time comparison (same task series; T-06 depends on the field from T-04 and the parse/install path from T-05). |
| REQ-01 (T-11) | T-13, T-14 (pin check) | The pin check cannot pass until pinning exists; it enforces REQ-01. |
| OQ4 → pinning format | T-11, T-13, T-14 | The *form* of the hash pin and of the check depends on the OQ4 decision. |
| OQ1 → index policy | T-15 | The index/mirror choice is unresolved. |
| OQ2 → tamper policy | T-17 | Whether non-200 on changed doc is correct is unresolved (conflicts with `test_hub.py:48`). |
| OQ3 → sign-the-artifacts | T-10 | Signing lab skills with fictional-publisher keys needs the OQ3 ruling. |

**Parallel tracks**

- **Track A — Skill channel (READY):** T-01 → T-04 → T-05 → T-06, with T-07 and T-08 in
  parallel after T-02/T-04, and T-09 after T-01/T-02.
- **Track B — Dependency channel (BLOCKED at root):** T-11 (REQ-01) → T-13 → T-14 in the
  M3 milestone; T-12 (vuln-scan CI) is independently READY; T-15 (index) waits on OQ1;
  T-16 (model digest) is READY.
- **Track C — Hub (BLOCKED):** T-17 waits on OQ2.

**Critical path:** T-01 → T-04 → T-05 → T-06 (skill content provenance, which gates the
composing controls T-07/08/09). The dependency blocks are wide but their root (OQ4/OQ1) is
decision-gated, so they do not extend the human-visible critical path — they are blocked,
not just late.

## 5. Milestones

| Milestone | Entry condition | Exit condition | Acceptance criteria rows going green |
|---|---|---|---|
| **M1 — Foundations** | None (start of work). | T-01/02/03 done; digest fn, policy loader, and host fail-closed path exist with tests; **no user-visible behaviour change** (no manifest fields changed, no refusals yet wired to real digests). | (none directly — prerequisites only) |
| **M2 — Skill-channel provenance** | M1 green. | T-04…T-10 done (T-10 needs OQ3). Digests verified at install and run, allowlist and revocation enforced, signature verify + signing helper present. | REQ-02, REQ-06, REQ-08, REQ-09 |
| **M3 — Dependency channel** | OQ4 resolved (for T-11/13/14) and OQ1 resolved (for T-15); T-12/T-16 can run regardless. | T-11…T-16 done. Hash pinning enforced, index policy set, CI vuln-scan + pin-check gates run, model pinned by digest. | REQ-01, REQ-04, REQ-05, REQ-07 |
| **M4 — Hub document integrity** | OQ2 resolved. | T-17 done: hub serves digest-checked documents with a relay allowlist (or, if OQ2 rules otherwise, the demonstrated attack is preserved and the exercising test stays green — see T-17 branches). | REQ-03 |

## 6. Tasks

Execution order: T-01 … T-17 (as sequenced within milestones; blocked tasks carry their
status and wait for their decision).

| # | Title | REQ(s) | Status | Milestone | Size |
|---|---|---|---|---|---|
| T-01 | Canonical content-digest helper | REQ-02, REQ-09 | READY | M1 | S |
| T-02 | Policy-file loader | REQ-06, REQ-08, REQ-09 | READY | M1 | S |
| T-03 | Fail-closed refusal path in `SkillHost.invoke` | REQ-02 | READY | M1 | S |
| T-04 | Required `digest` field on skill manifest + validation | REQ-02 | READY | M2 | M |
| T-05 | Verify + persist content digest at install | REQ-02 | READY | M2 | M |
| T-06 | Verify content digest at run, fail closed before `exec` | REQ-02 | READY | M2 | M |
| T-07 | Skill allowlist enforced at discover/install | REQ-06 | READY | M2 | M |
| T-08 | Revocation list by digest + publisher | REQ-08 | READY | M2 | M |
| T-09 | Signature verify mechanism + signing helper | REQ-09 | READY (mechanism) | M2 | L |
| T-10 | Sign shipped lab skills; wire `trusted_keys.json` | REQ-09 | BLOCKED-on-3 | M2 | S |
| T-11 | Exact-pin + hash-bind Python dependencies | REQ-01 | BLOCKED-on-4 | M3 | M |
| T-12 | CI vulnerability-scan job (recursive) | REQ-04 | READY | M3 | S |
| T-13 | `scripts/check_dependency_pinning.py` | REQ-04 | BLOCKED-on-4 | M3 | M |
| T-14 | Wire pin-check step into CI workflow | REQ-04 | BLOCKED-on-4 | M3 | S |
| T-15 | Explicit index / mirror policy | REQ-05 | BLOCKED-on-1 | M3 | M |
| T-16 | Pin LLM model to content digest | REQ-07 | READY | M3 | S |
| T-17 | Hub document digest + relay allowlist | REQ-03 | BLOCKED-on-2 | M4 | M |

---

### T-01 — Canonical content-digest helper
**REQ:** REQ-02, REQ-09. **Status:** READY. **Milestone:** M1.
**Files created:** `backend/app/skills/digest.py`. **Files modified:** none.
**What changes:**
- New module `backend/app/skills/digest.py` exposing `resource_digest(paths: Sequence[Path]) -> str`
  computing a stable sha256 over the declared resource set, and
  `canonical_digest(manifest: dict, resource_paths: Sequence[Path]) -> str` that hashes a
  canonical JSON serialisation of the manifest object (sorted keys, `json.dumps(..., sort_keys=True,
  separators=(",", ":"))`) concatenated with the sha256 of each resource file's bytes. This is the
  single digest definition used by both REQ-02 (verify) and REQ-09 (signature target).
**Tests added:** `tests/test_digest.py` — `test_canonical_digest_is_stable_across_key_order`,
`test_canonical_digest_changes_when_a_resource_changes`, `test_resource_digest_is_sha256_form`.
**Done-when:** `uv run pytest tests/test_digest.py -q` exits 0.
**Lab risk:** none — new helper, no behaviour wired yet.
**Avails lab risk:** N/A.

### T-02 — Policy-file loader
**REQ:** REQ-06, REQ-08, REQ-09. **Status:** READY. **Milestone:** M1.
**Files created:** `backend/app/skills/policy_files.py`. **Files modified:** none.
**What changes:**
- New module `backend/app/skills/policy_files.py` with `load_json_policy(settings, filename, fallback)`
  that reads a file from `settings.policy_dir` (consistent with the existing pattern in
  `backend/app/skills/manifest.py:126-128`, `load_vocabulary`) and returns its parsed content, plus
  `load_string_set(...)` for allowlist/revocation ID sets and `load_key_set(...)` for pinned public
  keys. Handles missing file with the caller's fallback (no crash), matching how the app treats
  policy as load-or-bail (`backend/app/main.py:129-143` precedent) — but the new policy files are
  *optional* (fallback), because the allowlist/revocation lists are empty until adopted.
**Tests added:** `tests/test_policy_files.py` — `test_loader_returns_fallback_for_missing_file`,
`test_loader_reads_existing_policy_file`, `test_string_set_parse`.
**Done-when:** `uv run pytest tests/test_policy_files.py -q` exits 0.
**Lab risk:** none — loader not wired to any enforcement yet.
**Avails lab risk:** N/A.

### T-03 — Fail-closed refusal path in `SkillHost.invoke`
**REQ:** REQ-02. **Status:** READY. **Milestone:** M1.
**Files modified:** `backend/app/skills/host.py`.
**What changes:**
- In `SkillHost.invoke` (`backend/app/skills/host.py:169`) add a pre-execution gate that any
  integrity/reputation check can invoke. Introduce a new module-level refusal helper
  `_integrity_failure(invocation_id, skill_id, reason) -> InvocationResult` that reuses the
  existing `_failure(...)` shape (`backend/app/skills/host.py:256`) but with an explicit
  `outcome="error"` and a reason string, placed **before** `_load_skill_module` at
  `host.py:217`. A new module-level `INTEGRITY_CHECKS` hook list (empty at M1) lets later checks
  (digest, revocation, signature) register predicates; T-06/08/09 populate it.
**Tests added:** `tests/test_host.py` — `test_a_registered_integrity_check_refusal_returns_error_without_running`
(a temporary predicate forcing refusal; asserts `result.outcome == "error"` and that the skill's
top-level code did not execute).
**Done-when:** `uv run pytest tests/test_host.py -q` exits 0.
**Lab risk:** none at M1 — the hook list is empty, so behaviour is unchanged.
**Avails lab risk:** the refusal returns an "error" outcome, so a demo that intentionally triggers
it still records observations and remains examinable; the lab's "detected, not prevented" property
(`README.md:169-173`) is preserved because run-time failures never delete evidence.

---

### T-04 — Required `digest` field on skill manifest + validation
**REQ:** REQ-02. **Status:** READY. **Milestone:** M2.
**Files modified:** `backend/app/skills/manifest.py`, all `backend/skills/catalogue/task_summary/manifest.json`
and every `vulnerabilities/*/skill/*/manifest.json`.
**What changes:**
- Extend `Manifest` (`backend/app/skills/manifest.py:72`) with a `digest: str` field (canonical
  sha256 per T-01) and `digest_alg: str = "sha256"` default.
- In `parse_manifest` (`:227`), add the required-fields check (`:263` loop) to also require
  `digest` as non-empty text, and validate its format against
  `SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")`.
- Populate a `digest` on every committed manifest by running the T-01 helper over the folder's
  resources. These are **regenerated**, which is the audit's intent — the field is required by
  REQ-02 (spec line 135-140).
**Tests added:** `tests/test_manifest.py` — `test_manifest_requires_valid_digest_field`,
`test_manifest_rejects_malformed_digest`, plus update any existing fixture manifests (ast01/03/04/05)
in the test suite to carry a computed digest.
**Done-when:** `uv run pytest tests/test_manifest.py -q` exits 0 and every committed
`manifest.json` contains a `digest`.
**Lab risk:** **Medium** — making `digest` *required* invalidates the five current skills until their
manifests are regenerated, which in turn can change discovery counts in `tests/test_startup.py`,
`tests/test_api.py`, `tests/test_control_skill.py`, and the ast01/03/04/05 feature tests. Mitigation:
regenerate all manifests in the same change-set (T-04 ships them together) and fix expected-valid
assertions. The weakness manifests are **not** removed — they keep their malicious content; they
merely gain a truthful digest of that content, which is exactly the channel hardening desired.
**Avails lab risk:** recomputing digests keeps the weakness skills valid and observable.

### T-05 — Verify + persist content digest at install
**REQ:** REQ-02. **Status:** READY. **Milestone:** M2.
**Files modified:** `backend/app/skills/registry.py`, `backend/app/storage/store.py`.
**What changes:**
- In `SkillRegistry.install` (`backend/app/skills/registry.py:320`), before `store.set_installed`
  (`:338`), recompute the canonical digest (T-01) of the skill's `manifest.json` + entrypoint file
  and compare to `record.manifest.digest`. On mismatch raise a new `SkillInvalid(...)` (reusing the
  existing exception type at `backend/app/skills/registry.py:44`) so the API returns
  `skill_invalid` (see `backend/app/api/routes.py:175-176`).
- Add a side-store in `store.py` recording the verified digest per installed skill (a new
  `installed_digests.json` keyed by skill id, or a `digest` column on the installed record), so
  run-time comparison (T-06) has a stored baseline, not just the manifest's self-declared digest.
**Tests added:** `tests/test_registry.py` — `test_install_fails_when_manifest_digest_mismatch`,
`test_install_records_verified_digest`.
**Done-when:** `uv run pytest tests/test_registry.py -q` exits 0.
**Lab risk:** **Medium** — installing a tampered-lab skill that legitimately needs to be installed
for a demo would now fail. Mitigation: for the *intended* demo path (install the unmodified shipped
weakness), digests match, so install proceeds; tamper-detection only fires when the on-disk content
differs from the shipped manifest, which is precisely the channel hardening. Update the ast01/03/04/05
feature tests' install sequences if they replace a skill file between manifest write and install.
**Avails lab risk:** the honest *and* weakness skills install unchanged from source; only
post-shipment tampering is refused.

### T-06 — Verify content digest at run, fail closed before `exec`
**REQ:** REQ-02. **Status:** READY. **Milestone:** M2.
**Files modified:** `backend/app/skills/host.py`.
**What changes:**
- Register a digest-check predicate into the `INTEGRITY_CHECKS` hook (T-03) that, inside
  `SkillHost.invoke` before `_load_skill_module` at `host.py:217`, recomputes the canonical digest
  (T-01) of the on-disk resources and compares it to the digest recorded at install (T-05's store).
  On mismatch it returns the T-03 refusal (`outcome="error"`), so `exec` at `host.py:126` is never
  reached.
**Tests added:** `tests/test_host.py` — `test_invoke_refuses_when_skill_changed_after_install`
(mutate the skill's `skill.py` after install, call `SkillHost.invoke`, assert `outcome == "error"`
and the new payload did not run). This is exactly the REQ-02 acceptance row
(`tests/test_host.py` + "mutating a skill's skill.py after install causes SkillHost.invoke to return
an error outcome").
**Done-when:** `uv run pytest tests/test_registry.py tests/test_host.py -q` exits 0.
**Lab risk:** **Low-Medium** — a demo that edits a skill file mid-session (dev reload path at
`backend/app/skills/registry.py:236-240`, mtime reload) will now fail closed until re-installed.
The `host.py` module cache (`:76-128`) is keyed on mtime; the digest check must run even when the
module is cached, so the check happens in `invoke` (before `_load_skill_module`), not inside the
cache lookup. Mitigation: document that hand-editing a skill requires re-install for the lab; the
weakness demos are unaffected because they don't edit skill files after install.
**Avails lab risk:** run-time refusal still records the refusal as an `error` outcome with
observations, keeping evidence visible.

### T-07 — Skill allowlist enforced at discover/install
**REQ:** REQ-06. **Status:** READY. **Milestone:** M2.
**Files created:** `backend/policy/skill_allowlist.json`. **Files modified:** `backend/app/skills/registry.py`.
**What changes:**
- New `backend/policy/skill_allowlist.json` (JSON array of allowed skill IDs; initial content is the
  five shipped IDs `task_summary`, `standup_sync`, `focus_picker`, `task_insights`, `team_rules`).
- Load via T-02's loader. Enforce in `SkillRegistry._read_one_skill` (`registry.py:206`): a skill
  whose id is not in the allowlist is marked invalid (append to `errors`), so it never appears in
  `installed()` (`registry.py:286`). Also guard `SkillRegistry.install` (`:320`) and the discovery
  duplicate handling remains as-is.
**Tests added:** `tests/test_registry.py` — `test_skill_absent_from_allowlist_is_invalid`,
`test_skill_in_allowlist_requires_valid_digest` (composes REQ-02).
**Done-when:** `uv run pytest tests/test_registry.py -q` exits 0, and a skill removed from
`skill_allowlist.json` is excluded from `get_registry().installed()` while still on disk (the REQ-06
acceptance row).
**Lab risk:** **Medium** — if the allowlist omits a shipped skill, that skill becomes
un-installable and the corresponding demo breaks. Mitigation: initial allowlist includes all five
shipped IDs. The ast01/03/04/05 demos install only shipped skills, so they remain exercisable.
**Avails lab risk:** `vulnerabilities/*/skill/` discovery is preserved (they are on the allowlist);
only *unknown* skills (a registry-flood / typosquat-dropped file) are refused, which is the intended
AST02 protection and does not suppress a shipped demo.

### T-08 — Revocation list by digest + publisher
**REQ:** REQ-08. **Status:** READY. **Milestone:** M2.
**Files created:** `backend/policy/revocations.json`. **Files modified:** `backend/app/skills/registry.py`.
**What changes:**
- New `backend/policy/revocations.json` with two lists: `{"digests": [...], "publishers": [...]}`
  (empty by default).
- Load via T-02. In `SkillRegistry._read_one_skill` (`registry.py:206`) and `SkillRegistry.install`
  (`:320`), mark a skill invalid / refuse install if its canonical digest or its `manifest.author`
  is present in the revocation lists. Publisher matching uses the manifest `author` string
  (`backend/app/skills/manifest.py:263` field).
**Tests added:** `tests/test_registry.py` — `test_revoked_publisher_makes_skill_invalid`,
`test_revoked_digest_makes_skill_invalid`, `test_revoked_skill_cannot_reenter_installed`.
**Done-when:** `uv run pytest tests/test_registry.py -q` exits 0 and adding a digest/publisher to
`revocations.json` flips discovery so the affected skill is invalid (REQ-08 acceptance row).
**Lab risk:** **Low-Medium** — default revocations list is empty, so no shipped demo is affected.
If a demo depends on a skill whose *publisher string* collides with a revoked publisher, it would
break; the fictional publishers (`Northwind Automations`, `Halden Collective`, etc.) are distinct, so
no collision by default.
**Avails lab risk:** revocation is opt-in (empty list); the maintainer-takeover recovery path is
provided without pre-suppressing any demo.

### T-09 — Signature verify mechanism + signing helper
**REQ:** REQ-09 (mechanism half). **Status:** READY (mechanism). **Milestone:** M2.
**Files created:** `backend/policy/trusted_keys.json`, `scripts/sign_skill.py`.
**Files modified:** `backend/app/skills/manifest.py`, `backend/app/skills/registry.py`.
**What changes:**
- Extend `Manifest` (`manifest.py:72`) with optional `signature: str` and `sign_public_key_id: str`
  fields; validate presence/format if present (not required).
- New `scripts/sign_skill.py`: a maintainer helper that loads a skill folder, computes the canonical
  digest (T-01), signs it with an Ed25519 key (per the spec ecosystem note at line 247-248: no
  packaging store verifies skill signatures, so a pinned-key Ed25519 check is the closest control),
  and writes `signature`/`sign_public_key_id` into the manifest. Generates/updates `trusted_keys.json`.
- New `backend/policy/trusted_keys.json` (map of key id → base64 Ed25519 public key).
- In `SkillRegistry._read_one_skill` (`registry.py:206`) and `install` (`:320`), when a manifest
  carries a signature, verify it against the pinned key via T-02's loader; on failure mark invalid /
  refuse install. **Default-enforced when a signature is present** (spec: "optional-but-default");
  a manifest *without* a signature is not rejected at this stage (signing application to the shipped
  lab skills is T-10, gated on OQ3).
**Tests added:** `tests/test_registry.py` (or `tests/test_signing.py`) —
`test_signed_manifest_verifies_against_trusted_keys`, `test_signature_with_tampered_resource_fails`,
`test_unsigned_manifest_is_not_rejected_when_signature_optional`. A test signs a fresh manifest with
the helper and verifies it against `trusted_keys.json`; a tampered resource fails (REQ-09 acceptance
row).
**Done-when:** `uv run pytest tests/test_registry.py tests/test_signing.py -q` exits 0, and
`uv run python scripts/sign_skill.py backend/skills/catalogue/task_summary` produces a verifiable
signature.
**Lab risk:** **Low** — signatures are optional; no shipped weakness carries one yet, so discovery is
unchanged for them. Mechanism is proven with self-signed test keys.
**Avails lab risk:** the weakness skills are untouched until T-10 decides (with OQ3) whether to sign
them; the demonstrated attack remains live.

### T-10 — Sign shipped lab skills; wire `trusted_keys.json`
**REQ:** REQ-09 (application half). **Status:** **BLOCKED-on-3.** **Milestone:** M2.
**Files modified:** `backend/policy/trusted_keys.json`, all shipped `manifest.json` files.
**What changes:**
- Run `scripts/sign_skill.py` (T-09) over the five shipped manifests so each carries a signature by a
  per-publisher Ed25519 key, and add those keys to `trusted_keys.json`. Make signature verification
  **required** (flip the T-09 optional flag to required) so that a skill without a valid signature is
  invalid.
- This assumes OQ3's answer that the fictional/publisher-scoped signing is wanted. If OQ3 rules
  otherwise (e.g. self-sign all under one lab key, or skip signing lab artifacts), the task adapts to
  the chosen branch.
**Tests added:** update `tests/test_registry.py` and feature tests so all shipped skills verify; add
`test_all_shipped_skills_are_signed_and_valid`.
**Done-when:** `uv run pytest -q` exits 0 with signature verification required and all shipped skills
valid.
**Lab risk:** **High** if done before OQ3 decides — forcing signature-required on the weakness skills
could flip them invalid if keys aren't managed. Mitigation: this task is BLOCKED precisely to defer
that decision; once OQ3 lands, the sign-helper makes the change mechanical and test-verified.
**Avails lab risk:** the weakness *content* is unchanged; the signature binds provenance without
altering behaviour, so the observable attack is preserved.

---

### T-11 — Exact-pin + hash-bind Python dependencies
**REQ:** REQ-01. **Status:** **BLOCKED-on-4.** **Milestone:** M3.
**Files modified:** `pyproject.toml`, `uv.lock`.
**What changes:**
- Replace every `>=` range in `pyproject.toml:7-21` and the `[build-system]` `hatchling` pin
  (`pyproject.toml:32-34`) with exact versions.
- **Branch A (OQ4 → uv native hash-lock):** migrate `uv.lock` to uv's hash-enabled format so it emits
  immutable `sha256:` source pins; enforce via `uv sync --locked`.
- **Branch B (OQ4 → external hashed constraints):** keep uv lock as version pin, and add an
  independent hashed constraints set (e.g. `requirements.lock.txt` with `==` + `--hash` lines) verified
  by the CI pin-check (T-13).
- Carried from the spec ecosystem note (`spec` lines 124-129): uv lockfile v1 cannot emit
  `sources = [{type="hash",...}]`; Branch A is the native path, Branch B is the independent-verification
  path. Cost of A: lock-format migration and its lockfile churn. Cost of B: duplicate constraint file to
  keep in sync. The OQ4 choice selects the branch; both are planned here.
**Tests added:** `tests/test_dependency_pinning.py` (or the T-13 script asserts manifest invariants:
no `>=` remains; exact pins present).
**Done-when (branch-dependent):** the REQ-01 acceptance row — `grep -c 'type = "hash"' uv.lock`
non-zero *or* exact `==` + `sha256:` constraint present; `grep -cE '^\s*"[a-z0-9_-]+>=' pyproject.toml`
returns 0.
**Lab risk:** **Low** — dependency labels change, not runtime behaviour; `uv sync` reproduces the same
application. No source file changes.
**Avails lab risk:** none (skill/agent surface untouched).

### T-12 — CI vulnerability-scan job (recursive)
**REQ:** REQ-04 (recursive vuln-scan half). **Status:** READY. **Milestone:** M3.
**Files created:** `.github/workflows/supply-chain.yaml`.
**What changes:**
- New workflow with a `scan` job that runs `uv sync --locked` then `uv audit` (or `pip-audit`) over the
  full resolved tree (uv audit scans the recursive resolved set by default). A clearly-marked
  `pin-check` placeholder step is left dormant until T-13/T-14 (BLOCKED-on-4) fills it — this keeps the
  workflow committable and better-than-before now (real vuln scanning) without fabricating a pin gate
  whose format OQ4 hasn't chosen.
- Carried from the spec ecosystem note (`spec` line 172): no CI exists; this is a greenfield addition;
  use `uv audit`/`pip-audit` for known-vulnerability scanning.
**Tests added:** none (CI config; verified by CI runs). Add a local smoke check documented in the
workflow: `uv run uv audit` exits 0 on a clean tree.
**Done-when:** the workflow's `scan` job runs and passes on push; `uv run uv audit` exits 0 locally.
**Lab risk:** none.
**Avails lab risk:** n/a.

### T-13 — `scripts/check_dependency_pinning.py`
**REQ:** REQ-04 (pin-check half). **Status:** **BLOCKED-on-4.** **Milestone:** M3.
**Files created:** `scripts/check_dependency_pinning.py`.
**What changes:**
- Script that parses `pyproject.toml` and fails (exit non-zero) if any dependency is an unpinned range
  or missing a hash as required by REQ-01. Its exact checks depend on which pinning form OQ4 selects
  (Branch A: require uv native hash pins; Branch B: require the hashed constraints file to cover every
  dependency). Names a clear message per violation.
**Tests added:** exercised by the T-14 CI step and by a local check; add
`tests/test_check_dependency_pinning.py` with a compliant fixture (exit 0) and one with a reintroduced
range (exit non-zero).
**Done-when:** `uv run scripts/check_dependency_pinning.py` exits 0 on the compliant manifest and
non-zero when a range is reintroduced (REQ-04 acceptance row).
**Lab risk:** none.
**Avails lab risk:** n/a.

### T-14 — Wire pin-check step into CI workflow
**REQ:** REQ-04. **Status:** **BLOCKED-on-4.** **Milestone:** M3.
**Files modified:** `.github/workflows/supply-chain.yaml`.
**What changes:**
- Replace the dormant placeholder from T-12 with a real `pin-check` job invoking
  `uv run scripts/check_dependency_pinning.py` and `uv sync --locked` on every push. Completes the
  REQ-04 acceptance criterion (workflow "invokes both the scan and the pin check on push").
**Tests added:** none (CI config).
**Done-when:** the workflow runs both `scan` and `pin-check` on push and both pass.
**Lab risk:** none.
**Avails lab risk:** n/a.

### T-15 — Explicit index / mirror policy
**REQ:** REQ-05. **Status:** **BLOCKED-on-1.** **Milestone:** M3.
**Files created/modified:** `uv.toml` (or `[tool.uv]` in `pyproject.toml`).
**What changes:**
- **Branch A (OQ1 → private mirror):** add `[[tool.uv.index]]` pointing resolution at the internal
  mirror; if required by the mirror, an allow-insecure-host/scope policy.
- **Branch B (OQ1 → explicit-source allowlist):** add `[[tool.uv.index]]` with `explicit = true`
  (per the spec ecosystem note, lines 188-190) to prevent fallback to public PyPI for every indexed
  package.
- Both branches remove `source = { registry = "https://pypi.org/simple" }` for indexed packages in
  `uv.lock` (REQ-05 acceptance row). A mirror adds infrastructure the lab currently does not run
  (OQ1's stated concern); the explicit-source branch avoids it.
**Tests added:** `tests/test_conf.py`-style check (or extend `tests/test_config.py`) asserting the
index config prevents public-PyPI fallback for the declared packages.
**Done-when:** no `source = { registry = "https://pypi.org/simple" }` remains in `uv.lock` for indexed
packages; `[[tool.uv.index]]` (with `explicit = true` in Branch B) present.
**Lab risk:** **Low-Medium** — if the index/mirror is unreachable, local `uv sync` may fail; the
explicit-source branch is self-contained and mirrors are optional infra. No source change.
**Avails lab risk:** n/a.

### T-16 — Pin LLM model to content digest
**REQ:** REQ-07. **Status:** READY. **Milestone:** M3.
**Files modified:** `backend/app/config.py`, `README.md`.
**What changes:**
- Change the `TASKBOT_MODEL` default in `config.py:184` from `"llama3.1:8b"` (mutable tag) to a
  `sha256:<digest>` digest reference (Ollama supports digest-form refs; spec ecosystem note lines
  216-217). Keep `TASKBOT_OLLAMA_URL` default as-is (`config.py:185`).
- Update `README.md:54-55` (and `README.md:75,132` model references) to `ollama pull` by digest and
  document that the model identity is bindable by digest.
- Record the model digest as provenance alongside settings for a run (per spec line 211 "store it
  alongside the settings used for a run") — a field on the settings bundle recorded into activity.
**Tests added:** `tests/test_config.py` — `test_default_model_is_digest_reference`
(validates `Settings.model` is `sha256:<64-hex>` form). This is the REQ-07 acceptance row
("a test asserts the default Settings.model is a digest-form string").
**Done-when:** `uv run pytest tests/test_config.py -q` exits 0 and `README.md` shows `ollama pull
sha256:...`.
**Lab risk:** **Low-Medium** — the exact digest must match a model actually pullable locally; if the
digest is unavailable, health/chat may report `model_missing`. Mitigation: pin to the digest of the
currently-used `llama3.1:8b` and document re-pinning; the health path already reports a clear
`model_missing` remedy (`ollama_client.py:198-203`).
**Avails lab risk:** n/a (model identity, not skill surface).

---

### T-17 — Hub document digest + relay allowlist
**REQ:** REQ-03. **Status:** **BLOCKED-on-2.** **Milestone:** M4.
**Files modified:** `backend/app/main.py` (`step_seed_hub_document` at `:89`),
`backend/app/mock/hub.py` (`rules` at `:68`); **Files created:** `backend/policy/hub_allowlist.json`.
**What changes:**
- At seed time (`main.py:89-128`), record a sha256 of the seeded `rules.json` (the F1 digest is not
  required here since the hub document is not a skill; use a plain file sha256) into a trusted store.
- At serve time (`mock/hub.py:68-102`), recompute the sha256 of `data/hub/rules.json` and compare to
  the recorded value. **Branch A (OQ2 → protect):** on mismatch return a refusal (non-200), matching
  the REQ-03 acceptance row; reject any relay address (`report_to`) not in `backend/policy/hub_allowlist.json`.
- **Branch B (OQ2 → preserve the attack):** the hub keeps serving byte-for-byte (the demonstrated
  weakness), and instead the *platform records* the mismatch as an observation (a detection-only
  control that does not block), so the lab attack remains observable while an integrity signal is
  produced. REQ-03's non-200 acceptance row would then be adjusted accordingly — this is precisely why
  the task is BLOCKED-on-2.
- **Critical conflict to resolve under OQ2:** `vulnerabilities/ast05-untrusted-external-instructions/
  tests/test_hub.py:48` (`test_the_hub_serves_whatever_is_in_the_file_without_judging_it`) asserts the
  hub serves *anything* unchanged ("no code change, no restart"). Branch A makes that test fail; Branch
  B keeps it passing. The task cannot proceed until a human decides which property the lab must
  preserve. This is the spec's own REQ-03 vs. AST05 conflict surfaced at the code level.
**Tests added (per branch):** Branch A — extend `vulnerabilities/ast05-untrusted-external-instructions/
tests/test_hub.py` (or a new `tests/test_hub_integrity.py`) with
`test_edited_document_returns_refusal_non_200` and `test_relay_outside_allowlist_rejected`. Branch B —
`test_edited_document_detected_but_still_served` and `test_relay_outside_allowlist_recorded`.
**Done-when (Branch A):** `uv run pytest` includes a case where editing `data/hub/rules.json` to change
`report_to` yields non-200 from `GET /mock/hub/rules`, and `backend/policy/hub_allowlist.json` contains
`http://127.0.0.1:8000/mock/collector` (REQ-03 acceptance row). (Branch B: the detection-only analogue
with `test_hub.py:48` still green.)
**Lab risk:** **High** for Branch A — it would break the AST05 demonstration that changed content steers
a skill, and `test_hub.py:48`. Mitigation: this is the entire reason the task is BLOCKED-on-2. Branch A
should only be chosen if the lab intends to now *protect* the hub; Branch B preserves the lab's core
demonstration while adding detection. Under no branch is the weakness *skill* removed.
**Avails lab risk:** Branch B keeps the fetch-and-obey demonstration observable while surrounding it
with an integrity signal, satisfying "harden the channel around [the attack] so provenance controls
exist while the attack surface stays observable."

---

## 7. Traceability

Every REQ-01…REQ-09 maps to at least one task, and each maps to its acceptance-criteria row.

| REQ | Tasks completing it | Acceptance criteria row (spec table) | Status of proof |
|---|---|---|---|
| REQ-01 | T-11 | `grep -c 'type = "hash"' uv.lock` non-zero AND `grep -cE '^\s*"[a-z0-9_-]+>=' pyproject.toml` returns 0 (or exact `==` + `sha256:`). | BLOCKED-on-4 (OQ4 selects branch). |
| REQ-02 | T-01, T-03, T-04, T-05, T-06 | `uv run pytest tests/test_registry.py tests/test_host.py` passes + `test` mutating `skill.py` after install yields `outcome="error"`. | READY (T-06 test matches row verbatim). |
| REQ-03 | T-17 | Editing `data/hub/rules.json` → non-200 from `GET /mock/hub/rules`; `hub_allowlist.json` contains `mock/collector`. | BLOCKED-on-2 (Branch A row; Branch B adapts). |
| REQ-04 | T-12, T-13, T-14 | `uv run scripts/check_dependency_pinning.py` 0/1 on compliant/violating manifest; `.github/workflows/supply-chain.yaml` runs scan + pin check on push. | T-12 READY (scan); T-13/T-14 BLOCKED-on-4. |
| REQ-05 | T-15 | No `pypi.org/simple` source in `uv.lock`; `[[tool.uv.index]]` + `explicit = true` present. | BLOCKED-on-1 (branch selected by OQ1). |
| REQ-06 | T-02, T-07 | Skill absent from `skill_allowlist.json` excluded from `installed()` while on disk. | READY. |
| REQ-07 | T-16 | Test asserts default `Settings.model` is digest-form; `README.md` `ollama pull` uses digest. | READY. |
| REQ-08 | T-02, T-08 | Adding digest/publisher to `revocations.json` makes affected skill invalid; digest- and publisher-level tests. | READY. |
| REQ-09 | T-01, T-02, T-09, T-10 | Test signs via helper, verifies against `trusted_keys.json`; tampered resource fails. (T-10 applies to shipped skills, gated on OQ3.) | T-09 READY (mechanism); T-10 BLOCKED-on-3 (application). |

No REQ is left without a task, and no task is orphaned from a REQ (each task's REQ column
above is non-empty). The one near-gap — the spec's undefined "REQ-10" — is a *reference to a
non-existent requirement*, which this plan records in §9 rather than fabricating a task for it.

## 8. Blocked work

| Task | BLOCKED-on | Decision it waits on | Branches (cost of each) | Who/what resolves it |
|---|---|---|---|---|
| T-10 | OQ3 | "Are the mock 'publishers' to be signed?" — sign lab skills with per-fictional-publisher keys, self-sign all under one lab key, or skip signing lab artifacts. | (a) Per-publisher keys + required signatures (more faithful provenance; higher key-management cost, must keep all keys). (b) Single lab key + required signatures (simpler; loses per-publisher attribution). (c) Leave signatures optional (no lab artifacts signed; mechanism still exists and tested). | A human/tech lead confirming OQ3; until then REQ-09 is proven at mechanism level (T-09) and signed-artifact enforcement is OFF. |
| T-11 | OQ4 | "uv native hash-lock vs. external hashed constraints" for pinning. | (a) Upgrade uv lock to hash format → `uv sync --locked` native; cost = lockfile-format migration + churn, and a specific uv version floor. (b) External hashed constraints (`requirements.lock.txt` `==`+`--hash`) + CI verification; cost = duplicated constraint file to keep in sync with pyproject. | The repo's Python/uv maintainer (OQ4). T-13/T-14 inherit the choice. |
| T-13 | OQ4 | Same pinning-format decision as T-11 (the script must check the chosen form). | Branches mirror T-11 (a/b). | OQ4. |
| T-14 | OQ4 | Same as T-13/T-11; wiring the pin-check step depends on the format. | Branches mirror T-11 (a/b). | OQ4. |
| T-15 | OQ1 | "Private mirror vs. explicit-source allowlist" for `REQ-05`. | (a) Private mirror → new infra the lab does not run today; cost = standing up + maintaining the mirror. (b) `explicit = true` index → self-contained in `pyproject.toml`, no infra; cost = none beyond config, but assumes only public packages are used (they are — no typosquat/dependency-confusion names found, per audit §"Checks that returned no finding"). | The platform/registry owner (OQ1). |
| T-17 | OQ2 | "Is the AST05 hub document meant to stay attacker-editable?" — decides Branch A (protect: non-200) vs. Branch B (preserve the attack + add detection). | (a) Protect (non-200 + relay allowlist) → satisfies REQ-03 verbatim but breaks `test_hub.py:48` and partially suppresses the demonstrated attack. (b) Preserve → keep byte-for-byte serving + record tamper/relay as an observation; `test_hub.py:48` stays green; REQ-03's acceptance row is adapted to a detection-only check. | The security/design lead who wrote the AST05 feature (OQ2); the decision must reconcile the spec's REQ-03 with the lab's stated purpose in `vulnerabilities/ast05-untrusted-external-instructions/hub/rules.json:6-10` and `test_hub.py:48-63`. |

The four decisions that gate work are exactly the spec's Open questions 1, 2, 3, 4. (Open
question 5 additionally gates only the *undefined* REQ-10, which this plan does not task; see
§9.)

## 9. Deferred

Anything worth doing that is not in the spec, recorded but not acted on:

- **D-01 — REQ-10 is undefined (spec gap).** Open question 5 references a "REQ-10
  (project-level agent-permission trust gate)" with no defined content in the spec's
  Remediation requirements. This plan deliberately does **not** invent it. When OQ5 is
  answered affirmatively, REQ-10 must first be written (spec section) before any task is
  planned under it. Deferred, not blocked-as-a-task.
- **D-02 — `.claude/settings.local.json` governance (AST02-010).** Whether the permissive
  `defaultMode: "dontAsk"` (`/claude/settings.local.json:7`) becomes a governed project file
  or stays local depends on OQ5. The file is gitignored (`.gitignore:6`), so it is not part
  of the committed supply chain; no task is planned until OQ5 resolves.
- **D-03 — SBOM / attestation pipeline.** Spec Out of scope lists "full SBOM export or
  attestation pipeline" as out of scope. Worth doing later (would extend REQ-01's digest
  work into a machine-readable artifact manifest) but intentionally not planned now.
- **D-04 — MCP server trust gates.** Spec Out of scope: no MCP config exists in the repo; the
  spec explicitly defers a "separate AST02 follow-up" if MCP servers are introduced. Recorded,
  not planned.
- **D-05 — Container/image supply chain.** No `Dockerfile`/image exists (spec Out of scope).
  Not planned.
- **D-06 — Functional-testing / deployment CI.** The spec scopes REQ-04 to a
  supply-chain-hygiene gate only (spec line 278-279). No general quality/deploy CI is planned
  here; noted so it is not misread as an omission.

**Execution order (recap).** M1: T-01 → T-02 → T-03 (all READY). M2: T-04 → (T-05 → T-06),
with T-07, T-08, T-09 in parallel after T-02/T-04; T-10 BLOCKED-on-3. M3: T-16 (READY) and
T-12 (READY) can run early; T-11, T-13, T-14 BLOCKED-on-4; T-15 BLOCKED-on-1. M4: T-17
BLOCKED-on-2. Each task leaves the app working and is independently reviewable; each
milestone ends at a committable, testable state that is strictly better than the one before
it.
