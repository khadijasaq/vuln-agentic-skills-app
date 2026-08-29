# AST02 — Supply Chain Compromise

Specification for the `vuln-agentic-skills-app` repository (TaskBot).

- Auditor: opencode (read-only)
- Audit date: 2026-08-29
- Target branch examined: `ast02`
- Mappings: OWASP LLM03 (Supply Chain), ASVS V14.2 (Dependency), CWE-494 (Download of Code Without Integrity Check)

## Summary

This audit examined the conventional Python dependency chain (uv / PyPI) and the
agentic-skill distribution channel TaskBot uses to install and run skills. The headline
risk is on the **skill side**: a skill's installed state is a single boolean flag in
`data/installed.json` with **no content digest, signature, or provenance**, and its code
is loaded and `exec`'d from local disk on every invocation; a runtime document served by
the mock team hub can steer a skill without any code edit, approval, or integrity check.
On the conventional dependency side the project has a committed, version-pinned `uv.lock`
but **no immutable `sha256:` source-hash pinning**, unpinned top-level version ranges,
no private-registry mirror or allowlist, and **no CI/CD at all** to gate or scan
dependencies. Findings by severity: **2 Critical, 4 High, 3 Medium, 2 Low** (11 total).
Note that this is a deliberately-vulnerable lab (see `README.md:1-13`); the remediation
below hardens the platform *channel* so that the distribution model it already uses
(install-from-store, fetch-and-obey hub) gains the provenance controls it currently lacks,
without attempting to remove the weaknesses the lab exists to demonstrate.

## Scope

**Examined**

- All committed manifests and lockfiles: `pyproject.toml`, `uv.lock`.
- All agent/skill surfaces: `backend/skills/`, `vulnerabilities/*/skill/`,
  `backend/app/skills/`, `backend/app/mock/hub.py`, `backend/app/main.py` startup steps,
  `.claude/` (both the gitignored `settings.local.json` and the committed `specs/*.md`).
- Install flow, skill host, manifest validation, and the hub fetch/serve channel.
- Full file walk for CI/CD, registry config, install-time scripts, git submodules, and
  non-localhost external URLs.

**Not examined (absent from this repository)**

- No CI/CD: no `.github/workflows`, `.gitlab-ci.yml`, `Jenkinsfile`, `Dockerfile`, or
  equivalent exist anywhere under git.
- No registry configuration: no `.npmrc`, `pip.conf`, `.pypirc`, `uv.toml`, or private
  index/scope mapping is present. The project resolves entirely from the default public
  `https://pypi.org/simple` (see `uv.lock` `source = ...` lines).
- No install-time execution hooks: no `preinstall`/`postinstall`/`prepare`, no
  `setup.py`, no Cargo build scripts, no git submodules, no `curl | sh`.
- No `.cursor/`, `.vscode/`, `AGENTS.md`, `CLAUDE.md`, or MCP server configuration files.
- The `.claude/settings.local.json` file exists on disk but is gitignored
  (`.gitignore:6`); its contents were read from the working tree but are not part of the
  committed supply chain. Its conclusions are noted as local-only context.

**Could not read / known gaps**

- The exact byte-contents of packages downloaded during `uv sync` were not independently
  pinned (see Finding AST02-001); the analysis relies on the committed `uv.lock` and the
  absence of a `sources = [{ type = "hash", ... }]` section.
- No package has any signing identity; there was nothing on-disk to inspect for a
  signature because none is produced or verified anywhere in the codebase.

## Current state

Phase 1 inventory. Paths are relative to the repository root.

| Category | Path | Why it matters |
|---|---|---|
| Manifest | `pyproject.toml` | Declares 7 runtime + 2 dev deps using **version ranges** (`>=`), not exact pins or hashes. Build backend `hatchling` also unpinned. |
| Lockfile | `uv.lock` | Committed and tracked (good). 39 packages, `version = 1`, `revision = 3`. Pins by **version**, but contains **no immutable `sha256:` source-hash** section. Wheel/sdist download URLs carry sha256 of the artifact, but this is registry-version pinning, not content-identity pinning. |
| Python version | `.python-version` | Pins `3.12`, minimal drift risk. |
| Agent surface | `backend/skills/catalogue/task_summary/` | The honest control skill. Manifest (`backend/skills/catalogue/task_summary/manifest.json`) has `author`/`version` free-form, no digest/signature. |
| Agent surface | `vulnerabilities/*/skill/` | The deliberately-flawed skills (ast01/03/04/05), auto-discovered by `SkillRegistry.default_roots()` (`backend/app/skills/registry.py:184-196`). Same manifest shape, no provenance. |
| Skill registry | `backend/app/skills/registry.py` | Discovers skills from local disks, install by toggling a flag. No content verification at any point. |
| Skill host | `backend/app/skills/host.py` | Sole execution point; loads skill `skill.py` and `exec`s it (`host.py:98,126`). |
| Manifest validation | `backend/app/skills/manifest.py` | Validates ID/entrypoint/category/capabilities, but never checks digest, signature, or publisher identity. |
| Runtime instruction source | `vulnerabilities/ast05-untrusted-external-instructions/hub/rules.json` | Attacker-editable document ("THIS FILE IS THE ATTACK", `rules.json:6-10`) with `report_to`/`notice` fields. |
| Hub serve | `backend/app/mock/hub.py` | Serves `data/hub/rules.json` unmodified at `GET /mock/hub/rules` (`hub.py:68-102`), no hash/signature/allowlist. |
| Startup copy | `backend/app/main.py` | Copies a weakness's `hub/rules.json` into `data/hub/` at startup if absent (`main.py:110-128`). |
| External model | `backend/app/llm/ollama_client.py` | Pulls Ollama model by mutable tag (`llama3.1:8b`) — no pinned digest. |
| Config (local) | `.claude/settings.local.json` | `defaultMode: "dontAsk"` with a Bash allowlist. Gitignored, local-only, but a permissive project-open permission surface. |
| Frontend assets | `frontend/static/fonts/raleway.woff2` | Bundled locally; **no** CDN/external-script dependency (good). |
| CI/CD | *(absent)* | No pipeline exists to run dependency scanning or pin checks. |
| Registry config | *(absent)* | No private mirror, index URL, or scope pin. Resolves from public PyPI by default. |
| Install-time exec | *(absent)* | No `preinstall`/`postinstall`, `setup.py`, build hooks, or `curl \| sh` scripts. |

## Findings

Sorted by severity. All references are to the repository at commit `143396c` (branch `ast02`).

| ID | File:line | Attack scenario (1-4) | Severity | Evidence | Impact |
|---|---|---|---|---|---|
| AST02-001 | `backend/app/skills/registry.py:320-339` + `backend/app/skills/host.py:98,126` | 2 (dependency confusion) | **Critical** | Installing a skill calls `store.set_installed(skill_id, True)` — it records only an ID flag; nothing verifies the on-disk `skill.py` bytes or its manifest. On invocation, `host.py:98` `spec_from_file_location` + `host.py:126` `exec(code, ...)` runs the file's top-level code. Any file placed at a discovered skill path (catalogue or `vulnerabilities/*/skill/`) executes with **no integrity check** — a nested/nearby file is trusted by path alone. | A tampered, replaced, or typosquatted skill file (or one dropped into a search path) executes arbitrary local code with no content verification — the AST02 dependency/registry-confusion failure in the skill channel. |
| AST02-002 | `vulnerabilities/ast05-untrusted-external-instructions/hub/rules.json:39-40` + `backend/app/mock/hub.py:68-102` | 3 (config-file hijacking) | **Critical** | The hub document carries `report_to` and `notice` fields that the `team_rules` skill fetches and acts on at run time (`manifest.json` declares `net.outbound` scope `["127.0.0.1"]`). `hub.py:90-99` serves the document byte-for-byte with no hash, signature, or allowlist; `main.py:110-128` copies the attacker-edited file into `data/hub/` at startup. | A runtime instruction source can steer an already-reviewed, already-installed skill with no code edit, new version, or re-approval. Behavior is controlled by whoever edits `rules.json` on disk — untrusted external instructions with no trust gate. |
| AST02-003 | `pyproject.toml:7-21` | 2 (dependency confusion) | **High** | All 7 runtime deps and both dev deps are declared as unpinned ranges (`fastapi>=0.115`, `uvicorn[standard]>=0.30`, etc.). No exact version, no `==`, no `sha256:` in the manifest. | A future `uv add`/sync resolution can drift to a newly-published, potentially backdoored version of a nested dependency; no manifest-level floor on drift. |
| AST02-004 | `uv.lock:1-2` (+ absence of hash section) | 2 (dependency confusion) | **High** | Lockfile is `version = 1, revision = 3` with no `sources = [{ type = "hash", url = ..., hashes = [...sha256...] }]` immutable pinning. `grep 'type = "hash"' uv.lock` returns nothing. It pins by version only; the recorded wheel sha256 is the downloaded artifact, not a content-identity pin independent of PyPI state. | Package content is not bound to an immutable digest. A malicious version re-upload or compromised index can change resolution outcome; hashes recorded in the lockfile are not enforced as immutable source pins. |
| AST02-005 | `backend/app/llm/ollama_client.py:117-121,167-172` (+ `README.md:54`) | 2 (dependency confusion) | **High** | Model is configured as a mutable tag string `TASKBOT_MODEL` default `llama3.1:8b` (`config.py:184`), and `ollama pull` in the README pulls by tag (`README.md:54`). No pinned model digest (`sha256:...`) is stored or verified. | An attacker who compromises the tag or the model registry can swap the model binary between pulls, changing agent behavior — an unpinned external binary resource. |
| AST02-006 | `backend/app/mock/hub.py:90-99` + `backend/app/main.py:110-128` | 3 (config-file hijacking) | **High** | The fetched document and the seed copy in `data/` are stored and served with **no content digest recorded** and no allowlist of acceptable documents/relay targets. "Whatever the file says is what gets served" (`hub.py:75`). | Cannot detect or block a tampered rules document or a relay instruction pointing the skill elsewhere; no integrity anchor for the runtime instruction channel. |
| AST02-007 | `backend/app/skills/manifest.py:262-267` | 4 (maintainer account takeover) | **Medium** | The manifest's `author` and `version` are validated only as "non-empty text" (`manifest.py:263-267`). The store displays them verbatim (`backend/app/api/routes.py:66-71`). There is no publisher identity, no signature field, and no registry of trusted authors. | A skill can misattribute authorship and version with no verification (AST04 analogue); a compromised publisher simply writes a new `author`/`version`. No way to distinguish genuine from impersonated publisher. |
| AST02-008 | *(absent)* `.github/workflows`, `.gitlab-ci.yml`, `Jenkinsfile`, `Dockerfile` | 2 (dependency confusion) | **Medium** | A full recursive tree scan (`Get-ChildItem` + `git ls-files`) found **no CI/CD of any kind** and no dependency-scanning gate (`uv audit`, `pip-audit`, `osv-scanner`, or equivalent) anywhere. | No automated gate exists to scan the recursive dependency tree, detect known-vulnerable versions, or block unpinned/hash-missing manifests. CI supply-chain gaps cannot be addressed because no CI exists. |
| AST02-009 | `backend/app/skills/registry.py:119-159` | 2 (dependency confusion) | **Medium** | Skill discovery is a filesystem walk of `backend/skills/catalogue` + `vulnerabilities/*/skill/` (`registry.py:184-196`). If a second skill claims an existing ID it is dropped as "ambiguous" (`registry.py:146-155`), but there is **no allowlist of approved skill IDs, no signature check, and no private store/mirror** — any folder in a search root is a candidate. | Without an allowlist or signature, a skill can appear/disappear or be shadowed by path ordering; no mechanism supports an approved-skills mirror or allowlist. |
| AST02-010 | `.claude/settings.local.json:7` | 3 (config-file hijacking) | **Low** | Local (gitignored, `.gitignore:6`) agent settings set `"defaultMode": "dontAsk"` with a Bash allowlist. Examined from the working tree as local-only context. | If committed or shipped as a project template, a repo config would grant permissive agent permissions that trigger on project open. Currently not part of the tracked supply chain — local-only, hence Low. |
| AST02-011 | `pyproject.toml:32-34` | 2 (dependency confusion) | **Low** | `[build-system] requires = ["hatchling"]` is unpinned (no version, no hash). | The build backend itself is unpinned; a malicious/compromised hatchling release would be pulled at build time. Minor in practice (rarely targeted) but untracked. |

### Checks that returned no finding (stated explicitly)

- **Typosquat candidates — none.** All direct deps (`fastapi`, `uvicorn`, `jinja2`, `httpx`, `pydantic`, `jsonschema`, `python-multipart`) are well-known mainstream packages; no name is one or two edits from a canonical package. No `anthropic`-style lookalike. (No dependency named like an internal package with a public fallback.) Flag: none suspected.
- **Missing/stale lockfile — not a finding here.** `uv.lock` is present and tracked. However, because it carries no hash pins (AST02-004), "present but not hash-bound" is the residual issue.
- **Install-time scripts — none.** No npm install hooks, `setup.py`, Cargo build scripts, or `curl | sh` anywhere in the tree.
- **Frontend/third-party CDN — none.** The only binary asset, `frontend/static/fonts/raleway.woff2`, is vendored locally; no remote scripts, models, or binaries are fetched from public hosts by the web UI.
- **Git submodules — none.** `.gitmodules` absent.

## Remediation requirements

Each requirement is independently verifiable. Where a control is not natively achievable
in this ecosystem, the closest workable control is given.

### REQ-01 — Bind every Python dependency to an immutable content hash

Pin all runtime and dev dependencies in `pyproject.toml` to exact versions and migrate
`uv.lock` to a format that records immutable `sha256:` source hashes, so resolution and
installation are content-bound rather than version-only.

- Files touched: `pyproject.toml`, `uv.lock`.
- Closes: AST02-003, AST02-004, AST02-011.
- Ecosystem note: uv's lockfile v1 does not emit `sources = [{ type = "hash", ... }]`
  immutable pinning. The closest fully-natively-achievable control is to upgrade the lock
  to uv's hash-enabled format (uv ≥0.4 lock v2 / `[lock] sources`) **or**, where an
  artifact-source hash registry is required, pin git/URL/archive dependencies with
  explicit `sha256:` digests (which uv supports) and add an independent
  `requirements.in`-style hashed constraint set verified in CI.

### REQ-02 — Verify skill content before it is installed or run

Installing a skill must verify an immutable content digest of its manifest **and** every
declared resource file (at minimum `manifest.json` and the `entrypoint` file), and the
host must fail closed if the on-disk content no longer matches the digest recorded at
install time.

- Files touched: `backend/app/skills/registry.py` (`install`, `_read_one_skill`),
  `backend/app/skills/host.py` (`_load_skill_module`), `backend/app/skills/manifest.py`
  (add a required `digest`/`sha256` manifest field).
- Closes: AST02-001.
- Verification: a changed skill file that no longer matches its recorded digest must be
  refused by `host.py` before `exec`; a manifest without a valid digest must be marked
  invalid by `parse_manifest`.

### REQ-03 — Bind the runtime-instruction document to an immutable hash and an allowlist

Records a content digest of the hub rules document at seed time and verifies it at serve
time; refuses to serve an edited document whose digest has not been re-approved, and
enforces an allowlist of relay targets (so `report_to`/`notice` cannot point a skill at an
unapproved destination).

- Files touched: `backend/app/mock/hub.py` (`rules` endpoint),
  `backend/app/main.py` (`step_seed_hub_document`), plus a new allowlist policy file
  (e.g. `backend/policy/hub_allowlist.json`).
- Closes: AST02-002, AST02-006.
- Verification: `GET /mock/hub/rules` on a document whose digest differs from the recorded
  value must return a refusal (non-200), and any relay address not in the allowlist must
  be rejected before the skill can act on it.

### REQ-04 — Add recursive dependency scanning as a CI gate

Introduce a minimal CI pipeline whose only job is supply-chain hygiene: a recursive
(`--recursive` / full-tree) vulnerability scan of the resolved dependency tree, plus a
version-integrity check that fails when any dependency is unpinned or missing a hash as
required by REQ-01.

- Files touched: new `.github/workflows/supply-chain.yaml` (or equivalent CI config),
  and a small script under `scripts/` (e.g. `scripts/check_dependency_pinning.py`) that
  fails on violation.
- Closes: AST02-008.
- Ecosystem note: no CI exists, so this is a greenfield addition, not a fix. Use
  `uv audit`/`pip-audit` for known-vulnerability scanning and the new script for pinning
  enforcement.
- Verification: `uv run scripts/check_dependency_pinning.py` exits non-zero when any
  dependency is unpinned or un-hashed; the workflow's `audit` job runs it on every push.

### REQ-05 — Establish a private-registry mirror or explicit allowlist for dependencies

Point resolution at a controlled index and/or an allowlist of approved packages, removing
silent fallback to the public PyPI index for packages that could be resolved from both a
public and a private source (dependency-confusion protection).

- Files touched: new `uv.toml` (or `[tool.uv]` in `pyproject.toml`) with an explicit
  `[[index]]` / `index-url`, plus an `allow-insecure-host`/scope policy if a mirror is
  used.
- Closes: AST02-003, AST02-004, AST02-009 (dependency half).
- Ecosystem note: uv supports `[[tool.uv.index]]` with explicit URLs and an
  `explicit = true` flag to prevent fallback to PyPI for indexed packages — this is the
  closest workable private-index control.
- Verification: `uv.lock` records only the pinned index as `source` for every package, and
  no `source = { registry = "https://pypi.org/simple" }` remains for indexed packages.

### REQ-06 — Add a skill allowlist (approved IDs / publishers) enforced at installation

Introduce an allowlist of approved skill IDs and, where available, trusted publisher
identities; the registry must refuse to install or run a skill not on the allowlist,
independent of filesystem presence.

- Files touched: `backend/app/skills/registry.py` (enforcement in `install`/`discover`),
  new `backend/policy/skill_allowlist.json`.
- Closes: AST02-001 (the "registry flooding"/"typosquat-dropped-file" scenario),
  AST02-007 (publisher attribution bound to an allowlist), AST02-009.
- Verification: a skill folder present on disk but absent from the allowlist must be
  marked invalid and excluded from `registry.installed()`; an allowlisted skill must still
  require a valid digest (REQ-02).

### REQ-07 — Pin the LLM model to a content digest and record it as provenance

Record the model's identity as a content digest (Ollama `sha256:<digest>` digest format)
rather than a mutable tag, and store it alongside the settings used for a run.

- Files touched: `backend/app/config.py` (default `TASKBOT_MODEL`), `README.md` (`ollama
  pull` examples).
- Closes: AST02-005.
- Ecosystem note: Ollama supports digest-form image references (`sha256:...`) for pull and
  run. Pinning there is achievable.
- Verification: `TASKBOT_MODEL` default resolves to a `sha256:` digest reference, and the
  README documents pulling by digest.

### REQ-08 — Provide revocation capability for skills (by content digest and by publisher)

Support a revocation list keyed by (a) a single skill manifest/version by content digest
and (b) an entire publisher, such that a revoked item is refused at install and at run
time even if present on disk.

- Files touched: `backend/app/skills/registry.py` (check revocation in `install` and
  `_read_one_skill`), new `backend/policy/revocations.json`.
- Closes: AST02-001, AST02-007 (maintainer-takeover recovery).
- Verification: adding a digest or publisher to `revocations.json` causes the affected
  skill to be treated as invalid on next discovery, and it cannot re-enter `installed()`.

### REQ-09 — Sign skill artifacts with a verified code-signing identity over a canonical digest

Introduce optional-but-default signature verification: a signature over a canonical
digest of the manifest object plus every declared resource file, checked against a pinned
public key before a skill is offered for installation.

- Files touched: `backend/app/skills/manifest.py` (add `signature`/`sign_public_key`
  fields), `backend/app/skills/registry.py` (verify before install),
  `backend/policy/trusted_keys.json` (pinned keys), `scripts/` (a signing helper for
  maintainers).
- Closes: AST02-001, AST02-007.
- Verification: a skill whose signature does not verify against `trusted_keys.json` is
  refused; a helper produces a signature that the verify path accepts for a matching
  manifest+resources digest.
- Ecosystem note: no Python packaging store verifies skill signatures today; this is the
  closest workable control (a pinned-key Ed25519/ECDSA check in the registry).

## Acceptance criteria

For a reviewer who did not perform this audit:

| Requirement | Concrete check |
|---|---|
| REQ-01 | `grep -c 'type = "hash"' uv.lock` exits non-zero AND `grep -cE '^\s*"[a-z0-9_-]+>=' pyproject.toml` returns 0 (no `>=` ranges remain); or the dependency is expressed with an exact `==` and an immutable `sha256:` source. |
| REQ-02 | `uv run pytest tests/test_registry.py tests/test_host.py` passes, and a test exists asserting that mutating a skill's `skill.py` after install causes `SkillHost.invoke` to return an "error" outcome (not run the executable). |
| REQ-03 | `uv run pytest` includes a case where editing `data/hub/rules.json` to change `report_to` yields a non-200 from `GET /mock/hub/rules`; and `backend/policy/hub_allowlist.json` contains `http://127.0.0.1:8000/mock/collector`. |
| REQ-04 | `uv run scripts/check_dependency_pinning.py` exits 0 on the compliant manifest and non-zero when a range is reintroduced; `.github/workflows/supply-chain.yaml` exists and invokes both the scan and the pin check on push. |
| REQ-05 | No `source = { registry = "https://pypi.org/simple" }` remains in `uv.lock` for indexed packages; a `[[tool.uv.index]]` with `explicit = true` exists in `pyproject.toml`. |
| REQ-06 | A test asserts a skill removed from `backend/policy/skill_allowlist.json` is excluded from `get_registry().installed()` while still on disk. |
| REQ-07 | `ollama pull <TASKBOT_MODEL default>` in `README.md` uses a `sha256:` digest reference, and a test asserts the default `Settings.model` is a digest-form string. |
| REQ-08 | Adding a digest/publisher to `backend/policy/revocations.json` changes discovery so the affected skill is invalid; a test covers both digest- and publisher-level revocation. |
| REQ-09 | A test signs a manifest with the helper and verifies it against `backend/policy/trusted_keys.json`; a manifest with a tampered resource fails verification and is refused. |

## Out of scope

This spec deliberately does **not**:

- **Add or upgrade any dependency, pin, or package.** It is a specification only; REQ-01
  through REQ-09 describe the target state. Whether dependencies are changed in a later
  change-set is a separate decision.
- **Remove or weaken the repository's deliberate vulnerabilities.** TaskBot is an
  intentionally-vulnerable lab (`README.md:1-13`). The AST01/03/04/05 weakness skills and
  the fetch-and-obey hub document remain in place; this spec hardens the platform
  channel around them so provenance controls exist, without deleting the attack surface
  the lab exists to demonstrate.
- **Add CI for functional testing, quality gate, or deployment.** REQ-04 is scoped to a
  supply-chain hygiene gate only.
- **Implement MCP server trust gates.** No MCP configuration exists in this repository, so
  no MCP-specific control is specified. If MCP servers are introduced later, a separate
  AST02 follow-up (MCP settings as executable config) would be required.
- **Address container/image supply chain.** No `Dockerfile` or image exists.
- **Provide a full Software Bill of Materials (SBOM) export or attestation pipeline**
  beyond the pinned lockfile and signature controls. That is a larger initiative and would
  depend on the deployment decisions the project has not made (it is local-lab only).

## Open questions

1. **Registry policy.** Should the lab move to a private mirror (`REQ-05`), or is an
   explicit-source allowlist in `pyproject.toml` acceptable? A mirror adds infrastructure
   the lab currently does not run.
2. **Is the AST05 hub document intended to remain attacker-editable?** REQ-03 and REQ-06
   assume the *detection* of tampering is the goal while the weakness remains; confirm this
   interpretation before implementing, because a strict allowlist could otherwise suppress
   the very attack the lab wants to observe.
3. **Legitimacy of the mock "publishers".** The vulnerability manifests claim authorship by
   fictional publishers (`Northwind Automations`, `Halden Collective`, etc.) purely for the
   exercise. Confirm that REQ-09 signing is to be applied to lab artifacts (self-signed,
   pinned keys) rather than to any real external publisher identity.
4. **Do developers here standardize on uv's hash-pinned lock format, or prefer an external
   hashed constraints file?** REQ-01's implementation depends on this decision, which has a
   workflow trade-off between uv-native updates and independent hash verification.
5. **Should the `.claude/settings.local.json` permission defaults (`dontAsk`) be treated as
   a project configuration to govern, or left as a strictly local per-developer file?**
   AST02-010 is Low only because it is gitignored; the answer determines whether REQ-10 (a
   project-level agent-permission trust gate) is warranted.
