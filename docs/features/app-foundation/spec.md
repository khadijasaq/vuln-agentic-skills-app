# Feature: App Foundation — Specification

| | |
|---|---|
| **Feature** | App Foundation — the platform every other feature is built on |
| **Derives from** | `docs/PRD.md` (PRD v1.0) + `docs/TDD.md` (system-wide technical design) |
| **Status** | **Implemented.** Built to this spec on 2026-08-21; 411 tests passing. Two decisions were added during the build — **S-36** (model timeout) and **S-37** (Tasks screen) — both recorded in §18. |
| **Siblings** | `ast04-insecure-metadata` · `ast01-malicious-skills` · `ast03-over-privileged` |

**Reference rule.** Shared architecture is **not restated here** — it is cited as `TDD §n`. This document specifies only what the App Foundation feature builds. If a mechanism is shared by more than one feature it lives in the TDD; this spec pins it at implementation level because this feature is the one that implements it.

**Conventions.** Details settled at spec level are numbered **S-1 … S-37** (§18). Type signatures are interface specification, not implementation; no function bodies appear.

---

## 1. Scope and derivation

### 1.1 In scope

The platform described in `TDD §1`: to-do assistant · LLM dispatch · skill store · capability broker and audit-hook monitor · findings engine · activity log · JSON API · storage · the five screens (Tasks, Chat, Store, Findings, Activity) · the **control skill**.

### 1.2 Out of scope

- **The three vulnerable skills.** `ast04-insecure-metadata`, `ast01-malicious-skills` and `ast03-over-privileged` are separate features with their own specs. Nothing here designs or anticipates their content.
- **`COVERT_DATA_FLOW` evaluation.** The type is declared in the taxonomy (`TDD §4.3`) with `implemented: False`; the correlation pass is not built here. The provisions it depends on — ordered log, payload digests — **are** built (§16-B).
- **User-supplied skill upload** — deferred, `TDD §14 Q-1`.
- **Release sequencing** — belongs in this feature's plan, not its spec.

### 1.3 Binding context

`TDD §14` resolutions Q-1…Q-6 bind this spec. In particular: no upload surface (Q-1), fixed severities (Q-2), `POST /api/reset` in scope (Q-4), resolved model recorded as evidence (Q-5), and **no skill pre-installed** (Q-6).

### 1.4 What "done" means

The platform runs, the control skill is chosen by a real model, and the findings engine **stays silent** (`TDD §11` I-12, PRD SC-3 / G5). A foundation that can stay quiet is one that can be trusted when it speaks.

---

## 2. Runtime and configuration

### 2.1 Platform and dependencies — **S-1**

| Item | Value |
|---|---|
| Python | `>=3.12` (already pinned in `pyproject.toml`; `sys.addaudithook` needs ≥3.8) |
| Web | `fastapi`, `uvicorn[standard]` |
| Templates | `jinja2` |
| HTTP client | `httpx` (Ollama + mock collector) |
| Models | `pydantic` v2 (arrives with FastAPI) |
| Schema validation | `jsonschema` (Draft 2020-12) — validates model-supplied tool arguments |
| HTML form posts | `python-multipart` — required by FastAPI to accept an ordinary form submission from the Chat and Store screens. Added during the build; S-1 did not anticipate it |

No other runtime dependencies. No CDN, no external services beyond a local Ollama (PRD §11, FR-3.5).

### 2.2 Configuration — `app/config.py`

Read once at startup into a frozen `Settings`. All values overridable by environment variable.

| Env var | Default | Meaning |
|---|---|---|
| `TASKBOT_MODEL` | `llama3.1:8b` | Ollama model (`TDD §14 Q-5`, D-14) |
| `TASKBOT_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama base URL |
| `TASKBOT_HOST` | `127.0.0.1` | Bind address — **loopback-enforced, S-2** |
| `TASKBOT_PORT` | `8000` | Bind port |
| `TASKBOT_DATA_DIR` | `./data` | Runtime state root |
| `TASKBOT_SKILLS_DIR` | `./skills` | Skill discovery root |
| `TASKBOT_POLICY_DIR` | `./policy` | Vocabulary + baselines |
| `TASKBOT_HISTORY_TURNS` | `10` | Conversation turns replayed to the model (**S-3**) |
| `TASKBOT_UNUSED_GRANT_WINDOW` | `5` | `UNUSED_GRANT` window (`TDD` D-10) |

**S-2 — Loopback bind is enforced, not merely defaulted.** `Settings` aborts startup with a non-zero exit if `TASKBOT_HOST` is not `127.0.0.1`, `::1`, or `localhost`. A deliberately vulnerable app must be incapable of binding `0.0.0.0` by configuration accident. *(FR-7.6, `TDD §8`)*

**S-3 — Conversation history is derived, not stored.** The model receives the last `TASKBOT_HISTORY_TURNS` `(user_message, reply)` pairs read from `activity.json`, newest last. No `conversation.json` is introduced — `TDD §6`'s storage layout stays exactly as designed.

```python
@dataclass(frozen=True)
class Settings:
    model: str;  ollama_url: str;  host: str;  port: int
    data_dir: Path;  skills_dir: Path;  policy_dir: Path
    history_turns: int;  unused_grant_window: int
    tasks_file: Path; installed_file: Path; findings_file: Path
    activity_file: Path; markers_dir: Path; collector_dir: Path

def load_settings() -> Settings: ...          # raises ConfigError → process exit
```

### 2.3 Identifiers and time

**S-4 — ID format.** `f"{prefix}_{millis:013d}{secrets.token_hex(6)}"` — lexicographically sortable by creation time, collision-safe, stdlib only. Prefixes: `act_`, `inv_`, `fnd_`, `tsk_`.

**S-5 — Timestamps.** ISO-8601 UTC, millisecond precision, `Z` suffix. One helper `now_iso()`; nothing else formats time.

---

## 3. Data shapes

`TDD §2.2`, `§3.1`, `§4.7` define these at design level. This section **pins them at implementation level**, because this feature implements them. Later features consume these shapes and extend only additively (`TDD §7`).

All persisted objects and API payloads carry `schema_version: 1`. Pydantic v2 models are the single definition; JSON on disk and JSON on the wire are the same shapes.

### 3.1 Task *(FR-1.1, FR-1.2)*

```jsonc
{ "schema_version": 1, "id": "tsk_1755702191482a1b2c3",
  "title": "Renew passport",              // 1..200
  "notes": "", "done": false,
  "created_at": "2026-08-14T09:12:00.000Z", "completed_at": null }
```

### 3.2 Installed state *(FR-2.2)*

```jsonc
{ "schema_version": 1, "installed": ["task_summary"], "updated_at": "…" }
```
Ordered list of unique skill IDs; order is install order and drives store display only.

### 3.3 Capability vocabulary entry — `policy/capability_vocabulary.json` *(TDD §2.3)*

```jsonc
{ "schema_version": 1, "capabilities": [
  { "id": "task.read",    "brokered": true,  "scope_kind": "task_glob", "description": "Read the user's tasks" },
  { "id": "task.write",   "brokered": true,  "scope_kind": "task_glob", "description": "Create, modify or delete tasks" },
  { "id": "fs.read",      "brokered": true,  "scope_kind": "path_glob", "description": "Read a file" },
  { "id": "fs.write",     "brokered": true,  "scope_kind": "path_glob", "description": "Write a file" },
  { "id": "net.outbound", "brokered": true,  "scope_kind": "host_glob", "description": "Make an outbound HTTP request" },
  { "id": "env.read",     "brokered": true,  "scope_kind": "key_glob",  "description": "Read configuration or environment" },
  { "id": "proc.spawn",   "brokered": false, "scope_kind": "none",      "description": "Start a subprocess" } ] }
```
`scope_kind` selects the matcher (§6). `brokered: false` means no `ctx` surface exists (`TDD` D-4).

### 3.4 Capability declaration

```jsonc
{ "id": "task.read", "scope": ["*"], "reason": "Reads your tasks to count and summarise them." }
```
`scope` — non-empty glob list. `reason` — 1..200 chars, shown in the store (FR-2.1).

### 3.5 Manifest *(TDD §2.2)*

Fields and constraints: `id` `^[a-z][a-z0-9_]{2,39}$` unique · `name` 1..60 · `version` semver · `category` must exist in baselines · `description` 1..500 · `invocation.when_to_use` 1..300 · `invocation.parameters` valid Draft-2020-12 · `capabilities` list (may be empty) · `entrypoint` `^[A-Za-z0-9_]+\.py:[A-Za-z_][A-Za-z0-9_]*$`.

**Validation failures ⇒ `INVALID`, never a finding** (`TDD §2.2`): malformed JSON · missing/bad-typed field · id pattern or uniqueness violation · unknown `category` · capability id absent from the vocabulary · empty or wrong-kind `scope` · bad parameter schema · missing entrypoint file or attribute.

**S-6 — Root of `invocation.parameters` must be `type: "object"`.** Ollama's tool protocol requires it; rejecting at load turns a runtime protocol error into a clear store-visible defect.

### 3.6 Capability baseline entry — `policy/capability_baselines.json` *(TDD §4.5, D-9)*

```jsonc
{ "schema_version": 1, "categories": {
  "reporting":   { "allowed": ["task.read"],                 "max_scope": { "task.read": ["*"] } },
  "formatting":  { "allowed": ["task.read", "task.write"],   "max_scope": { "fs.read": ["data/skills/**"] } },
  "reminder":    { "allowed": ["task.read", "task.write"],   "max_scope": {} },
  "integration": { "allowed": ["task.read", "net.outbound"], "max_scope": { "net.outbound": ["127.0.0.1"] } } } }
```

**S-7 — All four categories ship**, though only `reporting` is exercised here. This is policy data, not vulnerable-skill design; shipping it keeps later features a data edit (`TDD §12`). A capability absent from `max_scope` inherits `["*"]`.

### 3.7 Observation *(TDD §3.1)*

```jsonc
{ "seq": 3, "invocation_id": "inv_…",
  "capability": "net.outbound",
  "resource": "https://collector.example.com/ingest",
  "detail": { "method": "POST", "bytes": 412, "sha256": "…" },
  "outcome": "ok",                    // "ok" | "refused" | "error"
  "refusal_reason": null,
  "source": "broker",                 // "broker" | "audit_hook"
  "ts": "…" }
```

**S-8 — `bytes` and `sha256` are recorded for every payload-bearing observation** (`net.outbound` bodies, `fs.read`/`fs.write` contents, `task.read` result sets), **plus per-item digests for `task.read`** (`detail.item_digests`). Digest only, never the payload. This is the correlation substrate `TDD §4.6` depends on; the foundation must implement it even though nothing here consumes it (§16-B).

`resource` is canonical per capability: task-id or `*`; POSIX path relative to repo root; full URL; key name; argv[0].

### 3.8 Finding *(TDD §4.7)*

Shape as `TDD §4.7`. Implementation notes:

**S-9 — `trigger` distinguishes install-time from invocation-time findings.** `EXCESSIVE_GRANT` is a grant property evaluated at install (`TDD §4.5`), so `invocation_id`/`activity_id` are nullable. Consumers key on `trigger`, not on null-checking.

**Dedup key** (`TDD` D-11): `(skill_id, skill_version, type, capability_or_null, resource_or_null)`. A repeat bumps `occurrences` and `last_seen`; `id` and `first_seen` never change.

The `correlation` field (`TDD §4.7`) is defined in the model and always `null` in this feature.

### 3.9 Activity entry *(FR-5.1, FR-5.2)*

```jsonc
{ "schema_version": 1, "id": "act_…", "ts": "…",
  "user_message": "…", "reply": "…",
  "model": "llama3.1:8b",
  "skill_invoked": { "skill_id": "…", "skill_version": "…", "invocation_id": "…",
                     "params": {…}, "outcome": "ok", "error": null, "duration_ms": 42 } | null,
  "observations": [ Observation, … ],
  "findings_raised": ["fnd_…"],
  "vulnerability_fired": false }        // == len(findings_raised) > 0
```

### 3.10 Marker *(FR-7.1, TDD §8, D-12)*

Path `data/markers/{ts_compact}-{skill_id}-{type}.json`. Body carries the literal `INTENTIONALLY_VULNERABLE_LAB_MARKER`, the finding id/type/ast/severity, skill id/version, invocation id, resolved model, and the triggering observation.

**S-10 — One marker per newly created finding**; a dedup bump writes none. Keeps `data/markers/` demoable.

---

## 4. Storage

Layout is `TDD §6`. This feature implements the mechanics.

### 4.1 `app/storage/atomic.py`

```python
def read_json(path: Path, default: Any) -> Any: ...
def write_json_atomic(path: Path, value: Any) -> None: ...
@contextmanager
def mutate_json(path: Path, default: Any) -> Iterator[MutableJson]: ...
```

**S-11 — Atomic write.** Serialize → write `{path}.tmp.{pid}` in the same directory → `flush()` + `os.fsync()` → `os.replace()`. Same-filesystem rename is atomic on Windows and POSIX.

**S-12 — Per-path re-entrant lock.** A module-level `dict[Path, threading.RLock]` behind one meta-lock; `mutate_json` holds the lock across the whole read-modify-write. Single process by design (NG5) — no cross-process locking is provided or claimed.

**S-13 — Corrupt or missing file recovery.** On read failure the store logs `WARNING`, moves any existing file to `{name}.corrupt.{ts}`, and returns the caller's default, which is then written. **The lab always starts.** Recovery never raises into a request.

### 4.2 `app/storage/store.py`

```python
def now_iso() -> str: ...
def new_id(prefix: str) -> str: ...

def load_tasks() -> list[Task]: ...
def add_task(title: str, notes: str = "") -> Task: ...
def update_task(task_id: str, *, title: str | None = None,
                notes: str | None = None, done: bool | None = None) -> Task: ...
def delete_task(task_id: str) -> None: ...

def load_installed() -> InstalledState: ...
def set_installed(skill_id: str, installed: bool) -> InstalledState: ...

def load_findings() -> list[Finding]: ...
def upsert_finding(finding: Finding) -> tuple[Finding, bool]: ...      # (stored, was_created)

def append_activity(entry: ActivityEntry) -> ActivityEntry: ...
def load_activity(limit: int | None = None, *, skill_id: str | None = None,
                  since: str | None = None) -> list[ActivityEntry]: ...

def reset_lab() -> ResetSummary: ...                                    # §11.9
```

Errors: `TaskNotFound`, `SkillNotFound`, `StorageError` — all mapped to API errors (§11.2); none escape raw.

### 4.3 Seeding — `app/storage/seed.py` *(FR-1.3)*

**S-14 — Seeding runs at startup only when `tasks.json` is absent**, writing 8 believable tasks with `created_at` spread over the preceding ~3 weeks (so "oldest open task" is meaningful for the control skill) and 3 marked done. Content is ordinary personal/work admin — substantive enough that its later theft by another feature reads as a real loss (FR-1.3). Seeding **never** installs a skill (`TDD §14 Q-6`).

---

## 5. Module specifications

Layout is `TDD §10`. Each entry gives responsibility, interface, error behaviour, and traces.

### 5.1 `app/main.py` — application assembly

**S-15 — Startup order is load-bearing:**
1. `load_settings()` — aborts on non-loopback bind (**S-2**).
2. `install_audit_hook()` — **before any skill can load**; PEP 578 hooks cannot be removed (`TDD` D-8).
3. Ensure the `data/` tree; recover corrupt files (**S-13**).
4. `seed_tasks_if_absent()` (**S-14**).
5. Load `policy/*.json` — a malformed policy file is **fatal**; the findings engine cannot be trusted without it.
6. `registry.discover()`; log valid and invalid skills.
7. Mount `/api`, `/mock`, web routes, `/static`.

### 5.2 `app/llm/ollama_client.py` *(TDD §5, FR-3.5)*

```python
class OllamaUnavailable(Exception):
    reason: Literal["unreachable", "model_missing", "timeout", "protocol"]
    detail: str; remedy: str            # e.g. "ollama pull llama3.1:8b"

@dataclass(frozen=True)
class ToolCall: name: str; arguments: dict
@dataclass(frozen=True)
class ChatResponse: content: str; tool_calls: list[ToolCall]; model: str

class OllamaClient:
    def health(self) -> HealthInfo: ...
    def chat(self, messages: list[dict], tools: list[dict] | None) -> ChatResponse: ...
```

**S-16 — Timeouts and no retries.** `connect=5s`, `read=300s` (widened by **S-36**), `keep_alive=30m`. A retry would re-run a turn whose skill invocation may already have produced observations and findings, corrupting the evidence chain — so there are none.

**S-17 — Tool-calling capability is verified, not assumed.** `health()` reports whether the configured model is present. A tool-call protocol violation raises `OllamaUnavailable(reason="protocol")` naming the model — the operator learns the model lacks tool support rather than watching skills silently never fire.

`ChatResponse.model` is the model the server actually used; this is what gets recorded as evidence (`TDD §14 Q-5`).

### 5.3 `app/skills/manifest.py` *(TDD §2.2, §2.3)*

```python
class CapabilityDeclaration(BaseModel): id: str; scope: list[str]; reason: str
class Invocation(BaseModel): when_to_use: str; parameters: dict
class Manifest(BaseModel):
    schema_version: int; id: str; name: str; version: str; author: str
    category: str; description: str; invocation: Invocation
    capabilities: list[CapabilityDeclaration]; entrypoint: str

class VocabularyEntry(BaseModel): id: str; brokered: bool; scope_kind: str; description: str
class Vocabulary:
    def get(self, cap_id: str) -> VocabularyEntry | None: ...
    def ids(self) -> set[str]: ...

def load_vocabulary(path: Path) -> Vocabulary: ...
def parse_manifest(path: Path, vocab: Vocabulary,
                   categories: set[str]) -> tuple[Manifest | None, list[str]]: ...
```

`parse_manifest` **never raises** — it returns `(None, errors)` with **all** violations collected, so a skill author sees everything wrong at once.

### 5.4 `app/skills/registry.py` *(FR-2.1, FR-2.2, FR-2.6)*

```python
class SkillSource(StrEnum): CATALOGUE = "catalogue"        # S-18: single member for now

@dataclass(frozen=True)
class SkillRecord:
    manifest: Manifest | None; source: SkillSource; root: Path
    valid: bool; errors: list[str]; installed: bool
    entry_file: Path; entry_attr: str; mtime_ns: int

class SkillRegistry:
    def discover(self, roots: Sequence[tuple[SkillSource, Path]]) -> None: ...
    def all(self) -> list[SkillRecord]: ...
    def get(self, skill_id: str) -> SkillRecord: ...        # raises SkillNotFound
    def installed(self) -> list[SkillRecord]: ...           # valid AND installed only
    def install(self, skill_id: str) -> SkillRecord: ...    # raises SkillNotFound, SkillInvalid
    def uninstall(self, skill_id: str) -> SkillRecord: ...
```

**S-18 — The upload seam.** `discover()` takes a *sequence* of `(source, root)` pairs and `SkillSource` is an enum; this feature passes exactly one pair. Re-adding upload later (`TDD §14 Q-1`) is a new enum member plus one more pair — no signature change, no call-site change.

Only `valid` skills install. `installed()` is the **only** source of skills offered to the model (FR-2.6). Duplicate `id` across roots ⇒ first wins, second marked invalid with an explicit error.

### 5.5 `app/skills/context.py` — capability broker

Semantics and invariants: `TDD §3.1`, `§3.5`. Per-method detail: §7.3.

```python
class SkillContext:
    invocation_id: str
    tasks: TaskBroker; files: FileBroker; net: NetBroker
    env: EnvBroker;    log: SkillLogger

class TaskBroker:
    def list(self, scope: Literal["all","open","done"] = "all") -> list[dict]: ...
    def get(self, task_id: str) -> dict: ...
    def add(self, title: str, notes: str = "") -> dict: ...
    def update(self, task_id: str, **fields) -> dict: ...
    def delete(self, task_id: str) -> None: ...

class FileBroker:
    def read(self, path: str) -> str: ...
    def write(self, path: str, content: str) -> None: ...

class NetBroker:
    def get(self, url: str) -> BrokeredResponse: ...
    def post(self, url: str, json: dict | None = None) -> BrokeredResponse: ...

class EnvBroker:
    def get(self, key: str) -> str | None: ...

class SkillLogger:
    def info(self, message: str) -> None: ...     # no capability, no observation
```

**S-19 — Refusals raise `CapabilityRefused`, not sentinels.** The exception is raised *after* the observation is recorded. Sentinel returns would let a skill silently continue on bad data. `CapabilityRefused` carries `capability`, `resource`, `reason`.

There is deliberately **no** `delete`/`move`/`chmod` on `FileBroker` (FR-7.4) and **no** `ctx.proc` (`TDD` D-4).

### 5.6 `app/skills/host.py` *(FR-3.2, FR-3.4 — `TDD §11` I-1)*

```python
@dataclass(frozen=True)
class InvocationResult:
    invocation_id: str; outcome: Literal["ok","error"]
    summary: str; data: dict | None; error: str | None
    observations: list[Observation]; duration_ms: int

class SkillHost:
    def invoke(self, skill_id: str, params: dict) -> InvocationResult: ...
```

**The only function that executes skill code.** Sequence:

1. `registry.get(skill_id)`; refuse if not installed or not valid.
2. Validate `params` against the manifest schema; drop unknown keys; invalid ⇒ `outcome="error"`, never raise into the turn.
3. `invocation_id = new_id("inv")`; create `ObservationLog`.
4. `load_skill_module(record)` (**S-20**).
5. Set contextvars `CURRENT_INVOCATION`, `CURRENT_LOG`; clear `IN_BROKER`.
6. Call the entrypoint in `try/except`. Any exception ⇒ `outcome="error"`, message captured, observations retained.
7. Reset contextvars in `finally` — **always**, or the audit hook keeps attributing unrelated app I/O to this skill (§7.5).
8. Return `InvocationResult`.

**S-20 — Module loading and caching.** `importlib.util.spec_from_file_location` under module name `taskbot_skill_{id}`, cached on `(skill_id, version, entry_file.mtime_ns)`; an mtime change reloads. Import failure ⇒ record re-marked invalid, invocation returns `outcome="error"`.

**S-21 — Import happens inside the invocation's contextvar scope**, so module-level side effects in a skill (`open()` at import time) are attributed and observed rather than escaping unrecorded.

### 5.7 `app/monitor/observations.py` *(TDD §3.1, D-7)*

```python
class Observation(BaseModel): ...             # §3.7
class ObservationLog:
    def record(self, *, capability: str, resource: str, detail: dict,
               outcome: str, source: str, refusal_reason: str | None = None) -> Observation: ...
    def entries(self) -> list[Observation]: ...     # ordered by seq, never re-sorted
```
`seq` starts at 1 per invocation. **Order is preserved verbatim** — `TDD §11` I-5. Appends are lock-guarded; concurrent invocations use separate logs.

### 5.8 `app/monitor/audit_hook.py` *(TDD §3.2–§3.4)*

```python
CURRENT_INVOCATION: ContextVar[str | None]
CURRENT_LOG: ContextVar[ObservationLog | None]
IN_BROKER: ContextVar[bool]

def install_audit_hook() -> None: ...          # idempotent; called once at startup
@contextmanager
def broker_frame() -> Iterator[None]: ...      # sets/restores IN_BROKER
```
Event mapping and attribution: §7.4–§7.5.

### 5.9 `app/findings/*` *(TDD §4)*

```python
# taxonomy.py
class FindingType(BaseModel):
    id: str; ast_id: str; ast_name: str
    axis: Literal["truthfulness","proportionality","correlation"]
    severity: Literal["critical","high","medium","low","info"]
    summary_template: str
    implemented: bool                          # COVERT_DATA_FLOW → False here
TAXONOMY: dict[str, FindingType]

# baselines.py
class Baseline(BaseModel): allowed: list[str]; max_scope: dict[str, list[str]]
def load_baselines(path: Path) -> dict[str, Baseline]: ...

# engine.py
class FindingsEngine:
    def check_truthfulness(self, manifest, observations, *, invocation_id,
                           activity_id, model) -> list[Finding]: ...
    def check_proportionality(self, manifest, *, trigger, model,
                              invocation_id=None, activity_id=None) -> list[Finding]: ...
    def evaluate_invocation(self, manifest, result, *, activity_id, model) -> list[Finding]: ...
    def evaluate_install(self, manifest, *, model) -> list[Finding]: ...

# markers.py
def write_marker(finding: Finding, observation: Observation | null) -> Path: ...
```

**S-22 — The engine is pure and deterministic** (`TDD §4.8`, I-6): manifest + observations in, findings out; persistence and marker writing belong to the caller. No LLM, no clock beyond `now_iso()`, no I/O. This is what makes SC-3 testable rather than flaky. Enforced by the boundary rules in `TDD §10`.

### 5.10 `app/chat/prompts.py` *(FR-3.4)*

```python
def system_prompt() -> str: ...
def build_history(activity: list[ActivityEntry], turns: int) -> list[dict]: ...
```

**S-23 — The system prompt is a module constant containing no skill name, description, or trigger hint.** It states TaskBot's persona and its built-in add/list task behaviour only (FR-1.1). Asserted by A-6b.

### 5.11 `app/chat/orchestrator.py` *(TDD §5)*

```python
@dataclass(frozen=True)
class TurnResult:
    activity: ActivityEntry; findings_raised: list[Finding]
    tool_call_made: bool; model: str

class ChatOrchestrator:
    def run_turn(self, user_message: str) -> TurnResult: ...    # raises OllamaUnavailable
```
Protocol: §8.2.

### 5.12 Other modules
`app/api/*` → §11 · `app/web/*` → §12 · `app/mock/collector.py` → §13.2.

---

## 6. Scope matching — `app/skills/scope.py`

```python
class ScopeMatcher:
    @staticmethod
    def matches(scope: list[str], resource: str, scope_kind: str) -> bool: ...
    @staticmethod
    def is_unbounded(scope: list[str]) -> bool: ...
    @staticmethod
    def is_broader_than(scope: list[str], limit: list[str], scope_kind: str) -> bool: ...
```

**S-24 — Matching rules per `scope_kind`:**

| `scope_kind` | Resource form | Matching |
|---|---|---|
| `task_glob` | task id or `*` | `fnmatch`, case-sensitive |
| `path_glob` | POSIX path relative to repo root | `**` spans separators, `*` does not |
| `host_glob` | hostname from the URL (scheme and port excluded) | `fnmatch`, case-insensitive |
| `key_glob` | env/config key | `fnmatch`, case-sensitive |
| `none` | — | never matches; presence alone is the signal |

**S-35 — A trailing `/**` matches the bare prefix too.** `data/**` matches `data`, `data/x.txt` and `data/a/b/x.txt`. Follows standard gitignore-style glob behaviour.

**S-25 — Unbounded is exactly `["*"]` or `["**"]`** (single element). `is_broader_than` returns `True` when the declared scope is unbounded while the limit is not, or when a declared pattern covers a resource space the limit excludes — evaluated as pattern containment, not enumeration.

---

## 7. Capability broker and audit-hook monitor

> Highest-risk area. Design and invariants: `TDD §3`. This section pins the implementation.

### 7.1 The mandatory ordering *(TDD §3.1, I-3)*

Every broker method executes, in this exact order:

```
1. RECORD INTENT   log.record(capability, resource, detail, outcome="ok", source="broker")
                   ← FIRST, unconditionally, before any safety evaluation
2. CHECK SAFETY    evaluate against the FR-7 envelope ONLY (§7.3)
                   ← NEVER against the manifest (§7.2)
3. EXECUTE/REFUSE  on refusal: amend the observation to outcome="refused" + reason,
                   then raise CapabilityRefused (S-19)
4. RETURN
```

**S-26 — "Amend, not replace."** The observation created at step 1 is mutated in place at step 3; its `seq` and position never change. A refused attempt is therefore indistinguishable *in ordering* from a successful one — which is what lets `TDD §4.6`'s correlation read the true sequence of intent.

### 7.2 The broker does not read the manifest *(TDD §11 I-2)*

`app/skills/context.py` must not import `Manifest`, must not receive declarations, and must not accept a `skill_id` for policy purposes. Enforced by the boundary rules in `TDD §10`; tested by A-15.

### 7.3 Per-method specification

| Method | Capability | `resource` | `detail` | Safety check (FR-7) | Refusal reason |
|---|---|---|---|---|---|
| `tasks.list(scope)` | `task.read` | `"*"` | `{count, sha256, item_digests}` | none | — |
| `tasks.get(id)` | `task.read` | task id | `{sha256}` | none | not-found ⇒ `error` |
| `tasks.add/update/delete` | `task.write` | task id or `"*"` | `{fields}` | none | — |
| `files.read(path)` | `fs.read` | normalised path | `{bytes, sha256}` | resolved path under `data/` or `skills/` | `path_outside_allowed_roots` |
| `files.write(path, content)` | `fs.write` | normalised path | `{bytes, sha256}` | same roots; no state-file overwrite (**S-27**) | `path_outside_allowed_roots`, `protected_state_file` |
| `net.get/post(url, …)` | `net.outbound` | full URL | `{method, bytes, sha256, status}` | host ∈ `{127.0.0.1, localhost, ::1}` **and** scheme ∈ `{http, https}` | `non_local_host`, `unsupported_scheme` |
| `env.get(key)` | `env.read` | key | `{present}` | key in the `TASKBOT_*` allowlist (**S-28**) | `key_not_exposed` |

**S-27 — `fs.write` cannot overwrite state files.** Writes resolving to `tasks.json`, `installed.json`, `findings.json`, `activity.json`, or anything under `markers/` are refused. A skill must not be able to erase the evidence of its own behaviour (FR-7.4).

**S-28 — `env.read` exposes only `TASKBOT_*` keys, and never `TASKBOT_OLLAMA_URL`** (it is a network target). Everything else is refused. Real environment secrets are out of reach through the sanctioned path (FR-7.3).

**Path safety algorithm (`fs.*`).** Interpret relative to repo root → `Path.resolve()` (symlinks followed, `..` collapsed) → require the result under `data/` or `skills/` via `is_relative_to()`. Resolution happens **before** the check, so `../../` and symlink escapes are caught. The *pre-resolution* string is recorded as `resource`, so a finding shows what the skill asked for, not where it landed.

### 7.4 PEP 578 event mapping *(TDD §3.3)*

| Audit event | Capability | `resource` | Notes |
|---|---|---|---|
| `open` | `fs.read` / `fs.write` | `args[0]` | Mode/flags decide; `w`,`a`,`x`,`+` ⇒ write |
| `socket.connect` | `net.outbound` | `host:port` | |
| `socket.getaddrinfo` | `net.outbound` | hostname | Catches DNS before connect |
| `subprocess.Popen` | `proc.spawn` | `args[0]` | |
| `os.system`, `os.exec*`, `os.spawn*` | `proc.spawn` | command string | |

**S-29 — Environment reads are not audit-mapped.** CPython emits no audit event for `os.environ`, so an `env.read` bypass is undetectable. A stated gap (`TDD §3.5`), not papered over with an unreliable mapping.

Audit-layer observations carry `source: "audit_hook"`, `outcome: "ok"` (observe-only), and `detail.audit_event`.

### 7.5 Attribution rules *(TDD §3.4)*

1. `CURRENT_INVOCATION` unset ⇒ return immediately. App I/O, template loads, storage writes and the Ollama call are never recorded.
2. **Re-entrancy suppression** — `IN_BROKER` true ⇒ return immediately. Every broker method body runs inside `broker_frame()`. Without this, `ctx.tasks.list()` — which really does `open()` `data/tasks.json` — records a phantom `fs.read` and **the control skill emits a false finding, breaking SC-3 and G5** (`TDD §3.2`). Pinned by A-5.
3. **Contextvars, not thread-locals.** Concurrent invocations in different workers each carry their own `CURRENT_INVOCATION`.
4. Threads spawned by a skill start with a fresh context; their events are dropped rather than misattributed.
5. The hook never raises — a `WARNING` is logged and swallowed.
6. The hook checks its two contextvars **first**, before any event-name comparison; it runs on every file open in the process.

**S-30 — Skill-invoking endpoints are declared `def`, not `async def`.** This forces FastAPI's threadpool with a copied context, which is what makes rule 3 hold. An `async def` handler would run skill code on the event loop and interleave attribution across concurrent turns.

### 7.6 Limits
Carried unchanged from `TDD §3.5` — the broker is a **cooperative boundary, not a sandbox**. None of the listed limits affects this feature's acceptance: the control skill is honest and exercises no bypass path.

---

## 8. LLM dispatch

> Design: `TDD §5`. This section pins the implementation.

### 8.1 Manifest → tool schema
Exactly `TDD §5.1`. Tool order follows `installed` order — never relevance.

### 8.2 Turn protocol

1. `installed = registry.installed()`; build `tools`. Empty list when nothing is installed.
2. `messages = [system_prompt()] + build_history(activity, history_turns) + [user]`.
3. **Call 1** — `client.chat(messages, tools)`.
4. No `tool_calls` ⇒ `reply = content`, `skill_invoked = None`; go to 8 *(FR-3.3)*.
5. `tool_calls` present — take the first (**S-31**): name not installed ⇒ log and treat as step 4; otherwise `SkillHost.invoke(name, arguments)`.
6. `engine.evaluate_invocation(...)`; `upsert_finding` each; `write_marker` for each newly created finding (**S-10**).
7. **Call 2** — append the tool result (`summary`, or the error text when `outcome == "error"`) as a tool-role message; call Ollama again **with the same `tools`**; its `content` is the reply.
8. Build and append the `ActivityEntry` — `model`, all observations, `findings_raised`, `vulnerability_fired`.
9. Return `TurnResult`.

**S-31 — Exactly one tool call per turn.** Extra tool calls in one response are logged and ignored, recorded on the activity entry as `extra_tool_calls_ignored`. Multi-call turns would interleave two skills' observations inside one activity entry, complicating attribution and the DR-6 story for no benefit here. A documented limitation of this feature, not a permanent product decision.

### 8.3 No-hardcoded-routing enforcement *(FR-3.4, TDD §5.3)*

| # | Guarantee | Enforcement | Test |
|---|---|---|---|
| 1 | One invocation path | `SkillHost.invoke` referenced only in `orchestrator.py`; import-lint (`TDD §10`) | A-15 |
| 2 | `skill_id` has one origin | Only assignment is from `tool_call.name` | A-15 |
| 3 | User text never reaches selection logic | `user_message` passed only into `messages`; no `in`/`startswith`/`re`/`.lower()` comparison against it under `app/chat/` or `app/skills/` | A-6a |
| 4 | Behavioural proof | Stub LLM returning plain text ⇒ no skill executes for any message, including ones quoting the manifest verbatim | A-6 |

### 8.4 Ollama unreachable *(TDD §5.4, D-13)*

`OllamaUnavailable` is never swallowed and never replaced by a canned reply.

| Surface | Behaviour |
|---|---|
| `POST /api/chat` | `503` `{"error":"llm_unavailable","reason":…,"detail":…,"remedy":"ollama pull llama3.1:8b"}` |
| Chat screen | Inline error banner with the exact remedy; composer stays usable |
| Store / Findings / Activity | Fully functional |
| `GET /api/health` | `ollama.reachable=false`, `ollama.model_present`, resolved model |

No activity entry is written for a failed turn — there was no turn.

---

## 9. Findings engine

> Axes, taxonomy and severities: `TDD §4`. This feature implements the truthfulness and proportionality axes and **reserves** correlation.

### 9.1 Implemented in this feature

| Type | Axis | Severity | Status here |
|---|---|---|---|
| `UNDECLARED_CAPABILITY` | truthfulness | high | implemented |
| `SCOPE_VIOLATION` | truthfulness | high | implemented |
| `BROKER_BYPASS` | truthfulness | high | implemented |
| `EXCESSIVE_GRANT` | proportionality | medium | implemented |
| `UNUSED_GRANT` | proportionality | low | implemented |
| `COVERT_DATA_FLOW` | correlation | critical | **`implemented: False`** — row present, never evaluated |

The engine skips any type whose `implemented` is `False`. All five implemented types ship here even though **no skill in this feature can trip any of them** — they are exercised by synthetic-manifest unit tests (A-9), which is how the AST04/AST03 structural distinction is proven before either vulnerable skill exists.

### 9.2 Truthfulness algorithm *(TDD §4.4)*

```
for obs in observations (seq order):
    if obs.source == "audit_hook":                      emit BROKER_BYPASS(observed=obs)
    decl = first d in manifest.capabilities where d.id == obs.capability
    if decl is None:                                    emit UNDECLARED_CAPABILITY(observed=obs)
    elif not ScopeMatcher.matches(decl.scope, obs.resource, kind):
                                                        emit SCOPE_VIOLATION(observed=obs,
                                                                             declared_scope=decl.scope)
```
Refused observations are evaluated identically to successful ones. `BROKER_BYPASS` and `UNDECLARED_CAPABILITY` may co-occur; both are emitted.

### 9.3 Proportionality algorithm *(TDD §4.5)*

```
baseline = baselines[manifest.category]
for g in granted (== manifest.capabilities):
    if g.id not in baseline.allowed:
        emit EXCESSIVE_GRANT(reason="capability_outside_baseline", capability=g.id)
    else:
        limit = baseline.max_scope.get(g.id, ["*"])
        if ScopeMatcher.is_broader_than(g.scope, limit, kind):
            emit EXCESSIVE_GRANT(reason="scope_broader_than_baseline",
                                 capability=g.id, declared_scope=g.scope, limit=limit)
```
Evaluated at **install** (`trigger="install"`, **S-9**) and on **each invocation** (`trigger="invocation"`); dedup collapses repeats.

`UNUSED_GRANT`: for a skill with ≥ `unused_grant_window` (5) invocations in `activity.json`, any granted capability with zero observations across that window emits `UNUSED_GRANT`.

### 9.4 Persistence
The engine returns findings; the orchestrator (invocation) and the install endpoint (install) persist them. `upsert_finding()` → newly created ⇒ `write_marker()` and set `evidence.marker`; dedup bump ⇒ `occurrences += 1`, `last_seen` updated, no new marker (**S-10**).

---

## 10. Control skill

> The only skill in this feature. `TDD §12` records its cross-feature role: every vulnerability feature's acceptance includes "the control skill is still clean."

### 10.1 Location
`skills/catalogue/task_summary/` — `manifest.json` + `skill.py`. **Not installed on first run** (`TDD §14 Q-6`).

### 10.2 Manifest
`id=task_summary` · `name="Task Summary"` · `version=1.0.0` · `category=reporting` · description and `when_to_use` describing task summarisation · parameters `{scope: "all"|"open"|"done"}` with `required: []` · single capability `{"id":"task.read","scope":["*"],"reason":"Reads your tasks to count and summarise them."}` · `entrypoint="skill.py:run"`.

### 10.3 Behaviour
`run(ctx, params)` calls `ctx.tasks.list(params.get("scope","all"))` **once** and returns:

```python
SkillResult(
  summary = "<n> tasks, <d> done (<pct>%). Oldest open: '<title>' from <date>.",
  data    = {"total": int, "open": int, "done": int, "completion_rate": float,
             "oldest_open": {…} | None, "scope": str})
```
It touches nothing else — no `ctx.files`, `ctx.net`, `ctx.env`, and no import of `os`, `open`, `socket`, `httpx`, or `subprocess`. An empty task list yields a valid summary, not an error. It is genuinely useful, so it earns its place in a believable product (SC-8) rather than reading as a test fixture.

### 10.4 Zero-findings proof *(FR-4.6, G5, SC-3, `TDD §11` I-12)*

| Check | Outcome | Why |
|---|---|---|
| `UNDECLARED_CAPABILITY` | none | `O = {task.read}`, `D = {task.read}` ⇒ `O \ D = ∅` |
| `SCOPE_VIOLATION` | none | Declared `["*"]`, resource `"*"` ⇒ matches |
| `BROKER_BYPASS` | none | No direct I/O; the broker's own `open()` is suppressed by `IN_BROKER` (§7.5 rule 2) |
| `EXCESSIVE_GRANT` | none | `baseline("reporting").allowed == ["task.read"]`; `max_scope.task.read == ["*"]` ⇒ not broader |
| `UNUSED_GRANT` | none | `task.read` exercised on every invocation |
| `COVERT_DATA_FLOW` | n/a | `implemented: False`; no `net.outbound` observation exists regardless |

Every branch closed by construction. Pinned by A-4 (≥20 invocations, zero findings).

---

## 11. JSON API

> Contract and stability rules: `TDD §7`. This feature implements the endpoints.

### 11.1 Conventions
Base `http://127.0.0.1:8000` · no auth (FR-6.4) · `application/json` · every body carries `"schema_version": 1`.

### 11.2 Error envelope — **S-32**

```jsonc
{ "schema_version": 1, "error": "skill_not_found", "detail": "No skill with id 'foo'." }
```

| Code | HTTP | Used by |
|---|---|---|
| `skill_not_found` | 404 | skill routes |
| `skill_invalid` | 409 | install |
| `skill_not_installed` | 409 | chat internals |
| `validation_error` | 422 | malformed request bodies |
| `llm_unavailable` | 503 | `/api/chat` (adds `reason`, `remedy`) |
| `storage_error` | 500 | any |

### 11.3 `GET /api/health`
```jsonc
{ "schema_version": 1, "status": "ok", "intentionally_vulnerable": true,
  "model": "llama3.1:8b",
  "ollama": { "reachable": true, "model_present": true, "url": "http://127.0.0.1:11434" },
  "counts": { "skills": 1, "installed": 0, "tasks": 8, "findings": 0, "activity": 0 } }
```
`intentionally_vulnerable: true` is permanent (FR-7.6).

### 11.4 `GET /api/skills`
```jsonc
{ "schema_version": 1, "skills": [
  { "id": "task_summary", "name": "Task Summary", "version": "1.0.0", "author": "…",
    "category": "reporting", "description": "…", "source": "catalogue",
    "installed": false, "valid": true, "errors": [],
    "declared_capabilities": [ { "id": "task.read", "scope": ["*"], "reason": "…" } ] } ] }
```

### 11.5 `GET /api/skills/{id}`
Complete manifest verbatim, plus `installed`, `valid`, `errors`, `source`. `404 skill_not_found`.

### 11.6 `POST /api/skills/{id}/install` · `/uninstall`
No body. Returns the §11.4 skill object with updated `installed`, plus `findings_raised: [Finding, …]` on install (install-time `EXCESSIVE_GRANT`, §9.3). Errors `404`, `409`. Both idempotent.

**No upload endpoint** (`TDD §14 Q-1`) — asserted absent by A-10.

### 11.7 `POST /api/chat` *(FR-6.2)*
```jsonc
// → { "message": "how am I doing on my tasks?" }
{ "schema_version": 1, "reply": "You've got 7 tasks, 3 done…",
  "activity_id": "act_…",
  "skill_invoked": { "skill_id": "task_summary", "invocation_id": "inv_…", "outcome": "ok" },
  "findings_raised": [],
  "llm": { "model": "llama3.1:8b", "tool_call": true } }
```
`findings_raised` holds finding **objects** from *this turn only* — the per-turn exploitation signal every vulnerability feature's scanner relies on (`TDD §7`). `503 llm_unavailable` per §8.4.

### 11.8 `GET /api/findings` · `GET /api/activity`
`{"schema_version":1,"findings":[…],"count":n}` — filters `?skill_id=`, `?ast_id=`, `?severity=`, `?since=`.
`{"schema_version":1,"activity":[…],"count":n}` — filters `?limit=` (default 50, max 500), `?skill_id=`, `?since=`. Newest last.

### 11.9 `POST /api/reset` *(TDD §14 Q-4)*

```jsonc
{ "schema_version": 1,
  "cleared": { "findings": 3, "activity": 12, "markers": 3, "collector": 0 },
  "tasks_reseeded": 8, "installed_preserved": ["task_summary"],
  "note": "Lab convenience only. Reset cannot make the app less vulnerable." }
```

Clears `findings.json`, `activity.json`, `markers/`, `collector/inbox/`; clears and **re-seeds** `tasks.json`; **preserves `installed.json`**.

**Explicitly not a security toggle (NG3, `TDD §11` I-9).** It changes no skill, manifest, baseline, or broker behaviour. Every vulnerability present before a reset is present after it — reset only makes the app *forget what it observed*. There is no configuration, by any route, that reduces the app's vulnerability.

---

## 12. Web UI

> Token system and screen intent: `TDD §9`. This feature builds the screens and the exact static files.

### 12.1 Routes and templates

| Route | Template | Content |
|---|---|---|
| `GET /tasks` | `tasks.html` | The to-do list (**S-37**) |
| `POST /tasks/add` | → redirect `/tasks` | Add an item |
| `POST /tasks/{id}/toggle` | → redirect `/tasks` | Mark done / undo |
| `POST /tasks/{id}/delete` | → redirect `/tasks` | Remove an item |
| `GET /` | `chat.html` | Chat (default screen) |
| `POST /chat` | → redirect `/` | Form post; error banner on `OllamaUnavailable` |
| `GET /store` | `store.html` | Skill store |
| `POST /store/{id}/install` · `/uninstall` | → redirect | |
| `GET /findings` | `findings.html` | Findings list |
| `GET /activity` | `activity.html` | Activity log |

Shared: `base.html` (nav, footer badge); partials `_skill_card.html`, `_finding_card.html`, `_activity_row.html`, `_severity_badge.html`, `_capability_list.html`.

**The task routes never touch the capability broker.** They read and write storage directly, exactly as the built-in tools do (build plan O-1), so they produce **no observations and can raise no finding**. Managing your own tasks is the app performing its own advertised function, not a skill under supervision. Asserted behaviourally and by source inspection in `tests/test_tasks_screen.py`.

### 12.2 Static files — **exact set**

```
static/css/tokens.css       :root token block, copied verbatim from design/aegis-design-foundations.html
static/css/app.css          layout, components, screens — consumes tokens only
static/fonts/raleway.woff2  extracted from the foundations file's base64 @font-face
static/js/app.js            chat submit + activity row expand — no framework, no external fetch
```

**S-33 — `app.css` contains no literal colour values.** Every colour is `var(--token)`. This keeps `TDD §9`'s "token source only" honest and makes drift from the foundations file detectable by grep (A-16).

**S-34 — Raleway is self-hosted, never CDN-loaded.** Consistent with localhost-only operation; the app renders correctly with no network at all.

### 12.3 Screen content *(DR-5, DR-6)*

| Screen | Content in this feature |
|---|---|
| **Tasks** | The to-do list itself (**S-37**). Add box; one-click tick to complete or un-complete; quiet Remove. Unfinished first, oldest first within each group. Nav shows the outstanding count. **Works with no model at all** — no LLM is involved on this screen |
| **Chat** | Message list; a turn that ran a skill shows an inline chip naming it, linking to its activity entry. Error banner on `llm_unavailable` with the exact `ollama pull` command |
| **Store** | One card per skill: name, version, author, description, and **declared capabilities in mono, at face value** (FR-2.1) under the caption *"Declared by the publisher"* — the trust assumption later features exploit is visible in the UI, not just the code. Install/Uninstall action; invalid skills render disabled with their errors |
| **Findings** | Severity-badged cards, newest first; declared vs observed in mono, AST id/name, occurrences, link to the activity entry. **Empty in this feature** — empty state reads *"No findings. The installed skills have behaved exactly as declared."* |
| **Activity** | Reverse-chronological rows, expandable to params, ordered observations, outcome, duration. Rows with `vulnerability_fired == true` get a `--danger` left border (FR-5.2) — none occur here |

**Footer badge, every page (FR-7.6):** *"Intentionally vulnerable — local lab use only."*

---

## 13. Safety envelope enforcement

> Envelope: `TDD §8`. Enforcement points **in this feature's modules**:

| FR | Enforced in |
|---|---|
| **FR-7.1** marker artifact | §3.10, §9.4, **S-10** — host-writes on every new finding |
| **FR-7.2** local egress only | §7.3 `NetBroker` host allowlist + refusal-with-recording (§7.1); collector §13.2 |
| **FR-7.3** app-created files only | §7.3 path algorithm (resolve-then-check); limit stated in §7.6 |
| **FR-7.4** non-destructive | No delete/move/chmod on `FileBroker`; **S-27** protects state files |
| **FR-7.5** reversible | `rm -rf data/`; `POST /api/reset` (§11.9); literal marker string |
| **FR-7.6** clearly labelled | **S-2** loopback-enforced bind; `/api/health.intentionally_vulnerable`; README banner; footer badge |

### 13.2 Mock collector — `app/mock/collector.py`
`POST /mock/collector` accepts any JSON body and writes `data/collector/inbox/{ts}-{sender}.json` with the body, source invocation id (when present), and receipt time. Returns `202 {"received": true}`. It is a **passive sink** — no analysis, no findings. **Nothing in this feature sends to it**; it is built and tested here so the FR-7.2 envelope is real and working before `ast01-malicious-skills` needs it (§16-C).

---

## 14. Files this feature creates

```
app/**                        all modules in TDD §10
policy/capability_vocabulary.json   policy/capability_baselines.json
skills/catalogue/task_summary/{manifest.json, skill.py}
templates/{base,tasks,chat,store,findings,activity}.html   templates/partials/*.html
static/css/{tokens.css,app.css}  static/fonts/raleway.woff2  static/js/app.js
scripts/extract_design_tokens.py    one-off build helper (build plan P-3), not app code
data/.gitkeep
tests/
```
No `skills/user/`, no `data/uploads/` (`TDD §14 Q-1`). Later features add only `skills/catalogue/<skill>/` folders and their tests.

---

## 15. Acceptance criteria

PRD SC-1 and SC-2 depend on the vulnerable skills and are **out of scope for this feature**.

**Outcome column added after the build.** ✅ passing · ⚠️ not yet confirmed.

| # | Criterion | Method | Traces | Outcome |
|---|---|---|---|---|
| **A-1** | Clean checkout runs with one command; `/` loads; `/api/health` returns `status:"ok"` | Manual | SC-6, G6 | ✅ |
| **A-2** | With **zero** skills installed, chat works and the assistant adds and lists tasks | Manual + API | FR-1.1, FR-1.4 | ✅ |
| **A-3** | Control skill installs and is chosen by the model for ≥4 of 5 varied natural summary requests | Manual, live model | FR-2.2, FR-3.1 | ⚠️ **3/5** — see `manual-checks.md`; two misses were cold-start timeouts, since addressed by S-36. Needs re-running |
| **A-4** | **Control skill yields zero findings across ≥20 invocations** | Automated, stubbed LLM | **SC-3, G5, I-12** | ✅ |
| **A-5** | Re-entrancy suppression holds — `ctx.tasks.list()` yields exactly one `task.read` observation and **no** `fs.read` | Unit | §7.5 r2, I-4 | ✅ |
| **A-6** | Stub LLM returning plain text runs **no** skill for any input, including messages quoting the manifest verbatim | Automated | **FR-3.4, I-1** | ✅ 10 prompts |
| **A-6a** | Static scan: no comparison against `user_message` under `app/chat/` or `app/skills/` | Automated | FR-3.4 g3 | ✅ |
| **A-6b** | Rendered system prompt contains no skill id or name | Automated | **S-23** | ✅ |
| **A-7** | With nothing installed, `tools` contains **exactly the two built-in task tools and no skill**; no skill executes for any prompt, and no observation or finding is produced *(wording amended by build plan O-1)* | Automated | SC-4, NG4, I-8 | ✅ |
| **A-8** | Broker refuses **and records**: non-local host; path outside roots; `../` escape; symlink escape; state-file overwrite; non-`TASKBOT_*` env key | Unit | FR-7.2, FR-7.3, S-27, S-28 | ✅ |
| **A-9** | On synthetic manifests: a lying-but-modest manifest yields **only** AST04; an honest-but-broad manifest yields **only** AST03 | Unit, fabricated manifests — **no vulnerable skill shipped** | PRD §7.3 risk, I-7 | ✅ |
| **A-10** | Every endpoint in §11 matches its shape and carries `schema_version`; **no upload endpoint exists** | Contract tests | FR-6.3, Q-1 | ✅ |
| **A-11** | Non-loopback `TASKBOT_HOST` aborts startup; `rm -rf data/` fully resets | Manual | S-2, FR-7.5 | ✅ |
| **A-12** | Ollama down ⇒ `503` + remedy; Store/Findings/Activity still serve | Manual | D-13 | ✅ |
| **A-13** | A reviewer follows install → ask → activity unaided | Walkthrough | SC-7, DR-6 | ✅ |
| **A-14** | `POST /api/reset` clears findings/markers/activity/collector, re-seeds tasks, **preserves installed state**, changes no skill behaviour | Automated + manual | Q-4, NG3, I-9 | ✅ |
| **A-15** | Import-lint: `TDD §10` boundary rules hold; `SkillHost.invoke` referenced only in `orchestrator.py` | Automated | I-1, I-2 | ✅ |
| **A-16** | `static/css/app.css` contains no literal hex colour | Automated grep | S-33, DR-1 | ✅ |
| **A-17** | Every finding and activity entry carries the resolved `model` | Automated | Q-5 | ✅ |
| **A-18** | Observation log order is preserved; `task.read` observations carry `sha256` and `item_digests` | Unit | I-5, S-8, §16-B | ✅ |

| **A-19** | Tasks screen adds, completes, un-completes and removes; unfinished first | Automated | FR-1.1, **S-37** | ✅ |
| **A-20** | Managing tasks through the UI records **no observation** and raises **no finding**; the screen works with no model | Automated + source scan | NG4, **S-37** | ✅ |

A-9 closes the PRD §12 blur risk *before* the AST04 and AST03 features exist to expose it. A-18 proves the correlation substrate works before `ast01-malicious-skills` depends on it.

---

## 16. Seams this feature must expose

Catalogue in `TDD §12`. This feature's obligations:

| Seam | Delivered as |
|---|---|
| **A** — upload | `SkillRegistry.discover(Sequence[(SkillSource, Path)])`, `SkillSource` enum (**S-18**) |
| **B** — correlation substrate | Ordered `ObservationLog` (I-5) + `sha256`/`bytes`/`item_digests` on payload-bearing observations (**S-8**), verified by A-18 |
| **C** — egress target | `POST /mock/collector` live and tested; `NetBroker` loopback allowlist (§13.2) |
| **D** — new finding types | `TAXONOMY` as data with an `implemented` flag; `COVERT_DATA_FLOW` reserved at `critical` (§9.1) |
| **E** — grant/declaration divergence | `granted` modelled as a field distinct from `declared` (§3.8) |
| **F** — vocabulary and baselines | `policy/*.json` as data; all four categories shipped (**S-7**) |
| **G** — additive API | `schema_version` on every payload; contract per `TDD §7` |
| **H** — marker kinds | `write_marker(finding, observation)` accepts any finding type |
| **I** — integrity substrate *(recorded 2026-08-29)* | Not built by this feature. `detail.response_sha256`, delivered by AST05's D-15 response capture, turned out to serve a **second** axis: AST02's integrity check reads it to compare a delivered component against a pinned fingerprint, and needed **no new recording at all**. The same thing happened to **S-8**'s payload digests, which this feature built before AST01 existed to consume them — substrate outliving the feature that motivated it is now the pattern rather than the accident |

Nothing above is built beyond what this feature needs. Seams C and D exist **only** for later features; both cost near-zero now and would be disruptive to retrofit.

---

## 17. Traceability

| PRD | TDD | This spec |
|---|---|---|
| FR-1 tasks | §6 | §3.1, §4.2, §4.3 |
| FR-2 store | §2, §7 | §3.5, §5.4, §11.4–11.6, §12.3 |
| FR-3 dispatch | §5 | §5.11, §8 |
| FR-3.4 no routing | §5.3, §11 I-1 | §8.3, A-6/6a/6b/15 |
| FR-4 monitor + findings | §3, §4 | §3.7, §3.8, §5.5–5.9, §7, §9 |
| FR-5 activity | §6 | §3.9, §12.3 |
| FR-6 API | §7 | §11 |
| FR-7 safety | §8 | §7.1, §7.3, §13, S-2, S-27, S-28 |
| NG3 no toggles | §11 I-9 | §11.9 |
| NG4 skill-scoped | §11 I-8 | A-7 |
| DR-1…DR-6 | §9 | §12 |
| SC-3 control clean | §11 I-12 | §10.4, A-4 |
| SC-5 sandbox | §8 | §7.3, A-8 |
| SC-6 one command | — | A-1 |
| SC-7 demoable | §9 | §12.3, A-13 |

---

## 18. Spec decisions register

| # | Decision | Rationale |
|---|---|---|
| S-1 | Deps: fastapi, uvicorn, jinja2, httpx, pydantic v2, jsonschema | Minimum to satisfy PRD §11 |
| S-2 | Loopback bind enforced at startup; process aborts otherwise | A vulnerable app must not bind `0.0.0.0` by accident (FR-7.6) |
| S-3 | History derived from `activity.json`, no new file | Keeps `TDD §6` layout unchanged |
| S-4 | Sortable IDs `{prefix}_{millis}{hex}`, with a **6-byte** random suffix | Time-ordered, stdlib only. Widened from 3 bytes during the build: 24 bits collides by the birthday paradox at thousands of IDs per millisecond, so it was not actually collision-safe |
| S-5 | ISO-8601 UTC ms `Z`, one formatting helper | Comparable timestamps everywhere |
| S-6 | `invocation.parameters` root must be `type: object` | Protocol requirement caught at load, not runtime |
| S-7 | All four baseline categories ship | Policy data; keeps later features a data edit |
| S-8 | Digest + byte count + per-item digests; never the payload | Correlation substrate for `TDD §4.6` without duplicate storage |
| S-9 | `trigger` field; nullable `invocation_id`/`activity_id` | `EXCESSIVE_GRANT` is a grant property, evaluated at install |
| S-10 | One marker per newly created finding | Keeps `data/markers/` demoable |
| S-11 | tmp + fsync + `os.replace` | Atomic on Windows and POSIX |
| S-12 | Per-path `RLock` | Single-process by design (NG5) |
| S-13 | Corrupt file → aside + default; never raises | The lab always starts |
| S-14 | Seed only when `tasks.json` absent; 8 tasks over ~3 weeks | FR-1.3 believability; makes "oldest open" meaningful |
| S-15 | Fixed startup order; audit hook second | Hook must precede any skill load |
| S-16 | No LLM retries | A retry would re-run a turn that already produced findings |
| S-17 | Tool-calling verified; protocol violation is a named error | Operator sees the real cause, not silent non-firing |
| S-18 | Multi-root/multi-source registry, one root here | Upload seam without a redesign |
| S-19 | Refusals raise `CapabilityRefused`, no sentinels | Unambiguous; host catches it |
| S-20 | Module cache on `(id, version, mtime_ns)` | Correct reloads in dev |
| S-21 | Skill import inside the invocation scope | Import-time side effects are observed |
| S-22 | Findings engine pure and deterministic | Makes SC-3 testable, not flaky |
| S-23 | System prompt names no skill; asserted by test | FR-3.4 |
| S-24 | Scope matching rules per `scope_kind` | Precise, testable semantics |
| S-25 | Unbounded ≡ `["*"]`/`["**"]`; containment-based breadth | Deterministic proportionality input |
| S-26 | Observations amended in place, never replaced | Refusals keep their true position in the sequence |
| S-27 | `fs.write` cannot overwrite state files | A skill must not erase evidence of itself |
| S-28 | `env.read` limited to `TASKBOT_*`, excluding the Ollama URL | Real secrets out of reach via the sanctioned path |
| S-29 | Env reads not audit-mapped — stated gap | CPython emits no event; honesty over a false guarantee |
| S-30 | Skill-invoking endpoints declared `def` | Threadpool + copied context makes attribution correct |
| S-31 | One tool call per turn; extras logged and ignored | Avoids interleaved observations in one activity entry |
| S-32 | Single error envelope with a stable code set | Agents branch on `error`, not prose |
| S-33 | `app.css` has no literal hex | Keeps `TDD §9` "token source only" honest and greppable |
| S-34 | Raleway self-hosted | Renders with no network at all |
| S-35 | A trailing `/**` also matches the bare prefix, so `data/**` covers `data` itself as well as everything under it | Standard gitignore-style glob behaviour, and what an author plainly means by `data/**` |
| S-36 | Model read timeout **300s** (was 120s), and `keep_alive: 30m` sent with every request | Measured on CPU-only inference: an 8B model must load ~5 GB before its first word, and every turn costs **two** model calls. 120s reported a healthy model as broken. `keep_alive` stops Ollama unloading between messages, so only the first message pays the load cost |
| S-37 | A **Tasks screen** (`/tasks`) with add, complete/undo and remove, reached from the main nav | A to-do app whose to-dos are invisible fails SC-8 ("reads as a believable product"), and FR-1.3 calls the task list the crown jewel whose theft must "read as a real loss" — which requires the user to have seen it. Routes bypass the broker and raise no findings, exactly as the built-in tools do |

---

## 19. Next step

**Spec only.** The build plan for this feature is the next deliverable, then code.
