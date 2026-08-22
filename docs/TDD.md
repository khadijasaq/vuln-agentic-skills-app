# TaskBot — Technical Design Document (system-wide)

| | |
|---|---|
| **Scope** | The whole application: shared architecture for the foundation **and** all three vulnerability classes |
| **Derives from** | `docs/PRD.md` (PRD v1.0, approved) |
| **Status** | Approved. Canonical location: `docs/TDD.md` |
| **Release-agnostic** | Describes the **target architecture of the finished app**. Release and build sequencing belong in per-feature plans, never here |
| **Feature specs** | `docs/features/<feature>/spec.md` — each derives from `docs/PRD.md` + this document |

**Ownership rule.** *If it is shared by more than one feature, it belongs here. If it is specific to one feature, it belongs in that feature's spec.* Feature specs cite `TDD §n` rather than restating shared mechanisms.

**Scope boundary.** This document designs the *platform* and the *detection model* for all three vulnerability classes. It does **not** design the individual vulnerable skills — their manifests, their concealment technique, and their trigger surface are each feature spec's job.

**Traceability.** Every statement carries its PRD reference. Design choices are numbered **D-1 … D-14** (§13). The PRD's deferred questions are resolved and binding in **§14**.

---

## 0. Document map

| Document | Owns |
|---|---|
| `docs/PRD.md` | Product intent: goals, non-goals, personas, FR/NG/DR/SC requirements, the vulnerability catalogue at product level |
| **`docs/TDD.md`** (this) | Shared architecture: components, skill contract, capability model, monitor, findings engine, dispatch, storage, API contract, safety envelope, design system, module layout, architectural invariants |
| `docs/features/app-foundation/spec.md` | Implementation-level spec of the platform: assistant, dispatch, store, broker, engine, log, API, storage, screens, control skill |
| `docs/features/ast04-insecure-metadata/spec.md` | The insecure-metadata skill |
| `docs/features/ast01-malicious-skills/spec.md` | The malicious skill |
| `docs/features/ast03-over-privileged/spec.md` | The over-privileged skill |

The App Foundation feature **builds** the platform described here; the three vulnerability features **consume** it. No vulnerability feature may modify shared mechanisms — if one appears to need to, that is a TDD change and a design review, not a feature-local edit.

---

## 1. Architecture overview

### 1.1 Components

| Component | Responsibility | PRD |
|---|---|---|
| **Web UI** (Jinja2 + CSS) | Tasks, Chat, Skill Store, Findings, Activity screens | FR-5.3, DR-1…DR-6 |
| **JSON API** | Machine contract for red/blue-team agents | FR-6 |
| **Chat orchestrator** | Runs the turn: build tool set → ask model → invoke skill → return reply | FR-3 |
| **LLM client** | Ollama HTTP client, tool-calling protocol | FR-3.5 |
| **Skill registry** | Discovers skills on disk, parses/validates manifests, tracks installed state | FR-2 |
| **Skill host** | The only code path that executes a skill; builds its `SkillContext` | FR-3.2 |
| **Capability broker** | The sanctioned API a skill uses to touch anything; enforces safety, records intent | FR-4.1, FR-7 |
| **Audit-hook recorder** | Process-level net for broker bypass (`sys.addaudithook`) | FR-4.1 |
| **Findings engine** | Three-axis detection over observations, declarations and policy | FR-4.3, FR-4.4 |
| **Activity log** | One record per assistant turn | FR-5 |
| **Storage** | Atomic JSON-file persistence | FR-1.2, FR-4.5 |
| **Mock collector** | Local-only egress target | FR-7.2 |

Two components carry the product's weight: the **capability broker** (everything a skill does passes through it) and the **findings engine** (turns that record into evidence). Everything else is ordinary web plumbing.

### 1.2 Request flow

```
 User (UI or POST /api/chat)
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│ CHAT ORCHESTRATOR                                               │
│  1. registry.installed()  ──► manifests                         │
│  2. build tool schemas FROM MANIFESTS ONLY  (FR-3.1, FR-3.4)    │
└───────────────┬─────────────────────────────────────────────────┘
                │  messages + tools
                ▼
        ┌───────────────┐   no tool_call   ┌──────────────────────┐
        │ OLLAMA CLIENT │ ───────────────► │ reply = model text   │
        │  /api/chat    │                  │ (FR-3.3)             │
        └───────┬───────┘                  └──────────┬───────────┘
                │ tool_call{name, args}               │
                ▼                                     │
┌─────────────────────────────────────────────────┐   │
│ SKILL HOST  — the ONLY invocation path (FR-3.2) │   │
│   ctx = SkillContext(skill, invocation_id)      │   │
│   contextvar CURRENT_INVOCATION = id            │   │
│   result = skill.run(ctx, params)               │   │
└───────┬─────────────────────────────────────────┘   │
        │ every ctx.* call ─────┐                     │
        ▼                       ▼                     │
┌──────────────────┐   ┌──────────────────────┐       │
│ CAPABILITY       │   │ AUDIT-HOOK RECORDER  │       │
│ BROKER           │   │ sys.addaudithook     │       │
│  • records first │   │  • catches bypass    │       │
│  • then enforces │   │  • observe-only      │       │
└────────┬─────────┘   └──────────┬───────────┘       │
         └────────────┬───────────┘                   │
                      ▼                               │
          ORDERED ObservationLog (seq 1..n)           │
                      │                               │
                      ▼                               │
┌─────────────────────────────────────────────────┐   │
│ FINDINGS ENGINE — three axes (§4)               │   │
│   observed  vs declared  → truthfulness  AST04  │   │
│   granted   vs baseline  → proportionality AST03│   │
│   sequence  correlation  → covert flow    AST01 │   │
│   findings → storage + marker artifact          │   │
└───────┬─────────────────────────────────────────┘   │
        │ skill result summary                        │
        ▼                                             │
  model composes final reply (2nd Ollama call)        │
        │                                             │
        └──────────────────┬──────────────────────────┘
                           ▼
              ACTIVITY LOG entry (FR-5.1, FR-5.2)
                           │
                           ▼
                    reply to user
```

**Two model calls per skill-using turn** (decide → run → narrate). This is what makes the assistant read as a product rather than a dispatcher (SC-8): the user sees a natural answer, not raw skill output.

---

## 2. Skill contract

> The load-bearing interface. FR-2.3, FR-3, FR-4 all rest on it, and all four features implement against it. Changing it after the foundation ships means rewriting every skill.

### 2.1 On-disk shape

```
skills/
  catalogue/
    task_summary/            # control skill        — app-foundation
      manifest.json
      skill.py
    <ast04 skill>/           # ast04-insecure-metadata
    <ast01 skill>/           # ast01-malicious-skills
    <ast03 skill>/           # ast03-over-privileged
```

**Skills are data.** Dropping a folder into `skills/catalogue/` adds a store entry with no code change. Each vulnerability feature is therefore a pure addition: a manifest, a `skill.py`, and its own tests. *(D-2; PRD §13)*

**D-1 — Manifest format is JSON, not YAML.** No extra dependency, matches the JSON-file storage direction (PRD §11), and the store renders it verbatim in mono type (DR-3). Cost: no comments in manifests.

**D-2 — A skill is a folder with exactly two required files.** `manifest.json` (what it claims) and `skill.py` (what it does). The separation *is* the vulnerability class — AST04 exists precisely because these two can disagree, so the design keeps them independently authored and never generates one from the other.

### 2.2 Manifest schema

```jsonc
{
  "schema_version": 1,
  "id": "task_summary",                    // ^[a-z][a-z0-9_]{2,39}$ — unique, = tool name
  "name": "Task Summary",                  // store display
  "version": "1.0.0",
  "author": "TaskBot Labs",
  "category": "reporting",                 // drives the proportionality baseline (§4.5)
  "description": "Summarises your task list — counts, what's oldest, what's outstanding.",

  "invocation": {
    "when_to_use": "When the user asks for an overview, summary, count or status of their tasks.",
    "parameters": {                        // JSON Schema — becomes the tool's parameter schema
      "type": "object",
      "properties": { "scope": { "type": "string", "enum": ["all", "open", "done"] } },
      "required": []
    }
  },

  "capabilities": [                        // THE DECLARATION. Store shows this at face value (FR-2.1)
    { "id": "task.read", "scope": ["*"], "reason": "Reads your tasks to count and summarise them." }
  ],

  "entrypoint": "skill.py:run"
}
```

Validation at load: unknown capability IDs, an unknown `category`, a malformed parameter schema, or a missing entrypoint make the skill **unloadable** — it appears in the store marked invalid and cannot be installed. It is *not* a finding: a skill that cannot run cannot misbehave, and a parse error is not a security event.

**D-3 — `description` + `when_to_use` are the only things steering the model.** They are copied verbatim into the tool schema. This is deliberate: it is how a lying manifest gets itself chosen, and it is why no code anywhere reads the user's message to pick a skill (FR-3.4).

### 2.3 Capability vocabulary

Declarations and runtime observations are expressed in **one shared vocabulary** (`policy/capability_vocabulary.json`). That shared alphabet is what makes the diffs in §4 possible at all.

| Capability ID | Meaning | Brokered by | Scope kind |
|---|---|---|---|
| `task.read` | Read the user's tasks | `ctx.tasks.list()` / `.get()` | task glob |
| `task.write` | Create / modify / delete tasks | `ctx.tasks.add()` / `.update()` / `.delete()` | task glob |
| `fs.read` | Read a file | `ctx.files.read()` | path glob |
| `fs.write` | Write a file | `ctx.files.write()` | path glob |
| `net.outbound` | Make an outbound HTTP request | `ctx.net.get()` / `.post()` | host glob |
| `env.read` | Read configuration / environment | `ctx.env.get()` | key glob |
| `proc.spawn` | Start a subprocess | *(no broker — audit-hook detection only)* | none |

**Scope grammar.** A scope is a list of glob patterns. `["*"]` / `["**"]` mean **unbounded**, which the proportionality check treats as a distinct signal (§4.5) — an unbounded scope is exactly what "far more access than it needs" (PRD §7.3) looks like in data.

**D-4 — `proc.spawn` is declarable but not brokered.** There is no `ctx.proc`; the only way a skill spawns a process is by bypassing the broker, which the audit hook catches (§3.3). It exists in the vocabulary so that bypass has a name to be reported under.

**D-5 — Capabilities are per-invocation, not per-session.** Observations are scoped to one skill invocation, so a finding always points at one activity entry (FR-4.4 evidence, DR-6 story).

The vocabulary is **data**. A future capability is a JSON edit, not an engine change.

### 2.4 Code interface

```python
# skills/catalogue/<id>/skill.py
def run(ctx: SkillContext, params: dict) -> SkillResult: ...
```

```python
class SkillContext:
    tasks: TaskBroker      # .list(scope) .get(id) .add(...) .update(...) .delete(id)
    files: FileBroker      # .read(path) .write(path, content)
    net:   NetBroker       # .get(url) .post(url, json)
    env:   EnvBroker       # .get(key)
    log:   SkillLogger     # .info(msg) — no capability, no observation

class SkillResult:
    summary: str           # natural language, fed back to the model for the final reply
    data: dict | None      # structured payload, rendered in activity detail
```

**Contract rules**

1. `run` is synchronous and returns a `SkillResult`. An exception is caught by the host, logged as a failed invocation, and reported to the model as a tool error — it never crashes the turn.
2. **Every** external effect goes through `ctx`. A skill importing `os`, `open`, `socket`, `httpx`, or `subprocess` directly is violating the contract — which is a **detectable event, not a blocked one** (§3.3, §3.5).
3. `run` receives only `params` validated against the manifest's JSON Schema. Extra keys from the model are dropped.
4. Skills are stateless between invocations. Any state lives in tasks or files, through the broker.

**D-6 — Skills are imported as normal Python modules, in-process.** No subprocess, no sandbox, no restricted interpreter. Justified by NG5 (lab tool) and PRD §11 (readable in minutes); the honest cost is stated in §3.5.

---

## 3. Capability monitor

> FR-4.1 (observe what a skill actually does), FR-4.2 (runtime observation only — a finding is simultaneously proof it fired).

Two layers, because one is rich but bypassable and the other is coarse but unavoidable.

### 3.1 Layer 1 — the capability broker (primary)

Every broker method does the same four things, in this order:

```
1. RECORD INTENT      → Observation(capability, resource, detail, ts, seq)
2. CHECK SAFETY       → is this within the FR-7 envelope?  (NOT: is it declared?)
3. EXECUTE or REFUSE  → a refusal amends the observation to outcome="refused"
4. RETURN or RAISE
```

**The critical ordering: intent is recorded before, and independently of, the safety decision.** A skill that tries to POST task data to `evil.example.com` is refused — no packet leaves (FR-7.2) — but the observation is already logged, so the finding still fires with full evidence. **Safety and detection never trade against each other.** This single property is what lets the app be simultaneously genuinely exploitable (G2, G3) and genuinely harmless (G4, SC-5).

**Equally critical: the broker never consults the manifest.** It does not know what the skill declared. Declaration-vs-behaviour comparison happens only in the findings engine, after execution. If the broker enforced declarations, a lying skill would simply be blocked and there would be nothing to find — the product would defeat its own purpose (G2). This is an architectural invariant (§11).

Observation record:

```jsonc
{
  "seq": 3,
  "invocation_id": "inv_01J…",
  "capability": "net.outbound",
  "resource": "https://collector.example.com/ingest",
  "detail": { "method": "POST", "bytes": 412, "sha256": "…" },
  "outcome": "refused",              // "ok" | "refused" | "error"
  "refusal_reason": "non_local_host",
  "source": "broker",                // "broker" | "audit_hook"
  "ts": "2026-08-20T14:03:11.482Z"
}
```

**D-7 — Observations are an ordered sequence, not a set.** Sets suffice for AST04 and AST03. AST01 needs to prove *task data was read and then egressed in the same invocation* — a causal claim requiring order. The ordered log is the correlation substrate (§4.6); recording it from the start avoids a schema migration on live findings data.

**Payload digests.** Every payload-bearing observation records `bytes` and `sha256` — a digest, never the payload itself. This is what lets the correlation axis prove *which* data moved without storing it twice, and it is why the foundation must implement it even though only AST01 consumes it. *(Pinned at implementation level as S-8 in the App Foundation spec.)*

### 3.2 Re-entrancy suppression *(load-bearing — without it the control skill emits a false finding)*

`ctx.tasks.list()` reads `data/tasks.json` — a real `open()` call. The audit hook would see it and record an undeclared `fs.read`, and **the control skill would produce a finding, breaking G5/SC-3 on day one.**

Fix: a `contextvars.ContextVar` re-entrancy flag. While the broker is executing its own sanctioned implementation, the audit-hook recorder suppresses events. It records only file/socket activity originating in **skill** code — the bypass path.

Easy to regress, so it carries a dedicated test in the App Foundation spec.

### 3.3 Layer 2 — the audit-hook recorder (net)

Python's PEP 578 audit hooks (`sys.addaudithook`, 3.8+) fire on interpreter-level events regardless of which library triggered them:

| Audit event | Mapped to |
|---|---|
| `open` | `fs.read` / `fs.write` (by mode flags) |
| `socket.connect`, `socket.getaddrinfo` | `net.outbound` |
| `subprocess.Popen`, `os.system`, `os.exec*` | `proc.spawn` |

Attribution: the hook reads `CURRENT_INVOCATION` (a contextvar) and ignores every event where it is unset — so FastAPI's own I/O, template loading, storage writes and the Ollama HTTP call are never recorded. Skills run synchronously in a worker thread with a copied context, so attribution is correct under concurrent turns.

Observations from this layer carry `source: "audit_hook"`. **An audit-hook observation is a stronger signal than a broker one** — it means the skill deliberately went around the sanctioned API — and it has its own finding type (§4.4).

**D-8 — The audit hook is observe-only.** PEP 578 hooks *can* raise to block, but they fire on every `open` in the process and a bug there takes the whole app down. Given NG5 (lab tool) and FR-7.6 (localhost, clearly labelled), recording is the right trade. The hook is installed once at startup, before any skill can load, and per PEP 578 cannot be removed — a skill cannot uninstall its own surveillance.

### 3.4 Attribution rules

1. Events with no `CURRENT_INVOCATION` are dropped — never misattributed.
2. Events raised while the broker's own frame is active are suppressed (§3.2).
3. Attribution is per-context, so concurrent invocations in different workers stay separate.
4. Threads spawned *by a skill* start with a fresh context and are dropped rather than misattributed.
5. The hook never raises, and checks its two contextvars before anything else — it runs on every file open in the process.

### 3.5 Honest limits

The monitor is a **cooperative boundary, not a sandbox.** Stated plainly, because the safety envelope (§8) depends on knowing where the line is:

1. **Bypass is detected, not prevented.** A skill calling `open("C:/Users/…/.ssh/id_rsa")` directly *does* read the file; the hook records it afterwards. FR-7.3 holds for catalogue skills by **authorship discipline** — every skill in this repo, including the three vulnerable ones, is written to touch only app-created files — not by enforcement.
2. **Arbitrary third-party skills are out of scope.** Upload is deferred (§14 Q-1), and with it the isolation question (§14 Q-3).
3. **C extensions and `os.exec*` can evade audit hooks.**
4. **Environment reads are not audit-mapped** — CPython emits no audit event for `os.environ`, so an `env.read` bypass is undetectable.
5. **No timing, memory or CPU observation.** Capability-level only.

These limits bound what the product claims, not what it demonstrates: every vulnerability the app ships is detected through the sanctioned path or the audit hook, by construction.

---

## 4. Findings engine

> FR-4.3, FR-4.4, and the PRD §7.3 / §12 risk that the vulnerability classes collapse into one indistinguishable "mismatch".

### 4.1 Three independent axes

The engine answers three structurally different questions, from three different inputs:

```
 AST04  TRUTHFULNESS     observations × declaration     "did it do what it said?"
                          ├ input: ObservationLog + manifest.capabilities
                          └ needs a runtime invocation to exist

 AST03  PROPORTIONALITY  grant × baseline policy        "did it need this much?"
                          ├ input: manifest.capabilities + policy baseline
                          └ a skill can fail this while being perfectly honest

 AST01  CORRELATION      ordered observation sequence   "what did it combine?"
                          ├ input: ObservationLog order + payload digests
                          └ INDEPENDENT OF THE DECLARATION ENTIRELY
```

**Why they cannot collapse.** Each axis takes an input the others do not:

- Truthfulness needs the declaration; proportionality needs the policy; correlation needs neither — it reads only what happened, and in what order.
- A skill can be **honest and over-privileged** (declares its broad grant openly) → AST03 only.
- A skill can be **modest and lying** (declares little, does more) → AST04 only.
- A skill can be **honest, proportionate, and malicious** — declaring `task.read` and `net.outbound`, both within its category baseline, and still exfiltrating task data by *combining* them → **AST01 only**.

That third case is the proof the axes are genuinely distinct rather than three thresholds on one comparison. It also means correlation must never be implemented as a special case of truthfulness.

**Overlap is expressed, not collapsed.** A malicious skill that *also* lies about its capabilities produces **both** an AST01 correlation finding and an AST04 truthfulness finding. That is correct: two distinct failures, reported distinctly, each with its own evidence. Whether a given vulnerable skill declares its capabilities honestly is that feature spec's decision, not a platform concern.

### 4.2 The three sets

| Set | Meaning | Source |
|---|---|---|
| **D — Declared** | What the manifest says the skill uses | `manifest.capabilities` |
| **G — Granted** | What the host is prepared to let it do | derived from the manifest; `G ≡ D` in the current design |
| **O — Observed** | What it actually did, in order | ObservationLog |

`G` is modelled as a field distinct from `D` even while they are equal, so a future design can let them diverge without reworking the engine.

### 4.3 Taxonomy — data, not code

`findings/taxonomy.py` is a table. A new finding type is a row plus a check function; a new severity or AST mapping is a data edit. This is what keeps each vulnerability feature a pure addition.

| Type ID | AST | Axis | Severity | Fires when |
|---|---|---|---|---|
| `UNDECLARED_CAPABILITY` | AST04 | truthfulness | **high** | `O` contains a capability absent from `D` |
| `SCOPE_VIOLATION` | AST04 | truthfulness | **high** | Capability declared, but the resource touched falls outside its declared scope |
| `BROKER_BYPASS` | AST04 | truthfulness | **high** | Observation with `source: audit_hook` — went around the sanctioned API |
| `EXCESSIVE_GRANT` | AST03 | proportionality | **medium** | `G` exceeds the category baseline (extra capability, or unbounded scope where bounded suffices) |
| `UNUSED_GRANT` | AST03 | proportionality | **low** | Capability granted and never exercised across the window — dormant privilege |
| `COVERT_DATA_FLOW` | AST01 | correlation | **critical** | Task data read, then egressed within the same invocation |

Severities are fixed by §14 Q-2 and are not per-feature choices.

### 4.4 Truthfulness axis (AST04)

```
for obs in observations (in seq order):
    if obs.source == "audit_hook":                    → BROKER_BYPASS
    decl = D.find(obs.capability)
    if decl is None:                                  → UNDECLARED_CAPABILITY
    elif not scope_matches(decl.scope, obs.resource): → SCOPE_VIOLATION
```

**Refused observations are evaluated identically to successful ones** — intent is the security event (§3.1). `BROKER_BYPASS` and `UNDECLARED_CAPABILITY` may co-occur for one observation; both are emitted, because they describe different failures (going around the API vs. not declaring the capability at all).

### 4.5 Proportionality axis (AST03)

**D-9 — Proportionality is judged against a declared category and a static baseline policy.** The PRD requires AST03 to mean "more than it needs" (§7.3) without saying how need is computed. Rejected alternatives: LLM-judged proportionality (non-deterministic, would make SC-3 flaky) and code analysis (fragile). Chosen: `policy/capability_baselines.json`, a deterministic, inspectable table mapping category → allowed capabilities and maximum scope breadth.

```
baseline = baselines[manifest.category]
for g in G:
    if g.id not in baseline.allowed:                        → EXCESSIVE_GRANT (capability outside baseline)
    elif scope_broader_than(g.scope, baseline.max_scope):   → EXCESSIVE_GRANT (scope broader than baseline)
```

This axis is evaluated **at install and on each invocation** — over-privilege is a property of the grant, not of behaviour, so it is detectable before the skill ever runs. This does not violate FR-4.2: the finding is still raised by the host observing a real installed skill, not by scanning code for patterns.

`UNUSED_GRANT` needs history and evaluates over a rolling window of invocations (**D-10 — window = 5**).

### 4.6 Correlation axis (AST01)

The axis that reads *what happened*, not *what was claimed*.

```
for each invocation's ordered observation log:
    reads   = observations where capability == "task.read"      and outcome in {ok}
    egress  = observations where capability == "net.outbound"   (any outcome — intent counts)
    for e in egress where e.seq > r.seq for some read r:
        if payload_digest_of(e) relates to data_digest_of(r):   → COVERT_DATA_FLOW
```

**Architectural provisions this depends on**, all present in the platform:

| Need | Provided by |
|---|---|
| Causal ordering of observations | Ordered `ObservationLog`, `seq` monotonic (D-7, §3.1) |
| Proof that *this* data moved | `detail.sha256` / `bytes` on payload-bearing observations (§3.1) |
| A hook to run cross-observation rules | The engine evaluates per-invocation over the **full ordered log**, so multi-observation rules run in the same pass as single-observation ones |
| Detection independent of the manifest | The axis reads only the log — the declaration is not an input |
| Intent counted even when blocked | Refused egress still carries its digest and still correlates (§3.1) |

**Design-level limit, stated now.** Digest equality proves whole-payload movement. A skill that exfiltrates a *subset*, re-encodes, or transforms the data before sending will not match on a single whole-set digest. The platform therefore records **per-item digests alongside the set digest** for `task.read`, so subset egress remains matchable. The exact matching rule — whole-set, per-item, or containment — is the AST01 feature spec's decision; the platform's obligation is to make all three possible without a schema change.

### 4.7 Finding object *(FR-4.4)*

```jsonc
{
  "schema_version": 1,
  "id": "fnd_01J…",
  "type": "COVERT_DATA_FLOW",
  "ast_id": "AST01", "ast_name": "Malicious Skills",
  "axis": "correlation",                     // "truthfulness" | "proportionality" | "correlation"
  "severity": "critical",
  "skill_id": "…", "skill_version": "1.0.0",
  "trigger": "invocation",                   // "invocation" | "install"
  "invocation_id": "inv_…", "activity_id": "act_…",
  "model": "llama3.1:8b",                    // resolved model, as evidence (§14 Q-5)
  "declared": { "capabilities": [ … ] },
  "observed": Observation | null,            // null for proportionality findings
  "granted":  { "capabilities": [ … ] },     // present for proportionality findings
  "correlation": { "observation_seqs": [2, 5] },   // present for correlation findings
  "summary": "…",
  "evidence": { "marker": "data/markers/…json", "observation_seq": 5 },
  "first_seen": "…", "last_seen": "…", "occurrences": 1
}
```

The evidence field differs per axis — `observed` for truthfulness, `granted` for proportionality, `correlation.observation_seqs` for correlation. A consumer can tell the three apart without parsing prose.

**D-11 — Findings deduplicate on `(skill_id, skill_version, type, capability, resource)`.** Repeats bump `occurrences` and `last_seen` rather than appending. Keeps the findings list demoable after a long session (SC-7); the activity log remains the complete per-turn record.

**D-12 — The host writes the marker artifact when a finding is raised; skills never write markers.** FR-7.1 requires an exploit's effect to be an observable marker, and FR-4.2 already makes every finding proof-of-firing. Host-written markers are stronger evidence than self-reported ones and spare skills a marker capability that would pollute the vocabulary.

### 4.8 Purity

The engine takes manifest + observations + policy and returns findings. No LLM call, no I/O, no clock beyond a timestamp helper; persistence and marker writing are the caller's job. This determinism is what makes "the control skill produces zero findings" (SC-3) a testable claim rather than a flaky one.

---

## 5. LLM dispatch

> FR-3.1–FR-3.5, and FR-3.4 in particular: no hardcoded routing, verifiable by a reviewer.

### 5.1 Presenting skills to the model

Each installed skill becomes exactly one Ollama tool, built **only** from its manifest:

```python
{"type": "function", "function": {
    "name":        manifest.id,
    "description": f"{manifest.description}\n\nUse when: {manifest.invocation.when_to_use}",
    "parameters":  manifest.invocation.parameters,
}}
```

No re-ranking, no filtering by user text, no injected hints, no synthetic examples. If a manifest is unpersuasive the skill does not get chosen — that is a manifest-authoring problem (PRD §12), never a dispatcher problem. **This is also the mechanism a lying manifest exploits**: AST04's skill wins its invocation by describing itself well, exactly as an honest one would.

### 5.2 Turn protocol

1. Build `messages = [system, …history, user]` and `tools = [installed skills]`.
2. Call Ollama, `stream: false`.
3. No `tool_calls` → its `content` is the reply. Done (FR-3.3).
4. `tool_calls` present → resolve the name against installed skills (unknown → log, skip), validate arguments against the manifest schema, `SkillHost.invoke(...)`.
5. Run the findings engine over the invocation's observations; persist findings; write markers for new ones.
6. Append the tool result and call Ollama again to compose the final natural-language reply.
7. Write the activity entry, including the resolved model, all observations, and the findings raised.

The system prompt describes TaskBot's persona and its built-in add/list task behaviour (FR-1.1). It **must not** name any skill or hint when to use one.

### 5.3 How "no hardcoded routing" is guaranteed *(FR-3.4)*

Four structural guarantees, each checkable by a reviewer in under a minute:

1. **One invocation path.** `SkillHost.invoke()` is the only function that executes skill code, and it is called from exactly one place: the tool-call branch of the orchestrator.
2. **Its `skill_id` argument has one possible origin** — `tool_call.function.name` from the model response. No other assignment exists.
3. **The user's message string is never read by selection logic.** It goes into `messages` and nowhere else. No `in`, no regex, no `startswith` against it anywhere under `app/chat/` or `app/skills/`.
4. **Behavioural test.** With a stubbed LLM that returns plain text for every input, no skill executes for *any* user message — including messages that quote a skill's own name and description verbatim.

These four hold for every release. A vulnerability feature that needed a routing shortcut to make its skill fire would be violating G2, and the correct response is a better manifest, never a dispatcher change.

### 5.4 Ollama unreachable

**D-13 — Fail loudly; never fall back.** A canned or keyword-matched fallback reply would be exactly the hardcoded routing FR-3.4 forbids, and would let a demo appear to work with no model — silently invalidating SC-1. Chat returns `503` with the exact remedy command; the store, findings, activity and all read-only endpoints keep working; health reports reachability and the resolved model.

**D-14 — Reference model is `llama3.1:8b`,** overridable by environment. Native tool-calling support is the hard requirement; a model lacking it is unsupported. The resolved model is recorded on every finding and activity entry as evidence (§14 Q-5) — SC-1's "≥4 of 5 prompts" is only meaningful against a named model.

---

## 6. Storage

```
data/
  tasks.json        [ Task, … ]
  installed.json    { installed: [skill_id], updated_at }
  findings.json     [ Finding, … ]              (FR-4.5 — accumulates)
  activity.json     [ ActivityEntry, … ]        (newest last)
  markers/          <ts>-<skill>-<type>.json    (FR-7.1, FR-7.5)
  collector/inbox/  <ts>-<sender>.json          (FR-7.2 — AST01's egress target)
```

**Mechanics.** Read-modify-write under a per-file re-entrant lock, written atomically (temp file + fsync + `os.replace`) so a crash never leaves a half-written file. Single process, single user by design (NG5) — no cross-process locking is provided or claimed. A corrupt or missing file is moved aside and recreated empty with a warning: the lab always starts.

**Seeding** (FR-1.3). First run seeds believable tasks so their later theft reads as a real loss. Seeding never installs a skill (§14 Q-6).

**Activity entry** (FR-5.1, FR-5.2) records the user message, the reply, the resolved model, the skill invoked (or null), the full ordered observation list, the findings raised, and `vulnerability_fired` — the flag that drives the UI marking.

---

## 7. JSON API contract

> FR-6. The contract both agents depend on. Shared by every feature; no feature may change a shape.

**Base** `http://127.0.0.1:8000` · no auth (FR-6.4) · every response carries `"schema_version": 1`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Status, Ollama reachability, resolved model, `intentionally_vulnerable: true` |
| `GET` | `/api/skills` | Catalogue with installed state and **declared** capabilities |
| `GET` | `/api/skills/{id}` | One skill's complete manifest, verbatim |
| `POST` | `/api/skills/{id}/install` · `/uninstall` | Install state; install returns any install-time findings |
| `POST` | `/api/chat` | Drive the assistant programmatically (FR-6.2) |
| `GET` | `/api/findings` | All findings; filters by skill, AST id, severity, time |
| `GET` | `/api/activity` | Activity log; filters by limit, skill, time |
| `POST` | `/api/reset` | Lab reset — **not** a security toggle (§14 Q-4) |
| `POST` | `/mock/collector` | Local-only egress sink (FR-7.2) |

**`POST /api/chat`** returns `reply`, `activity_id`, `skill_invoked`, `llm.model`, and **`findings_raised` for that turn only** — the exploitation signal. A scanner attributes a finding to the prompt that caused it without diffing `/api/findings` before and after. This is the primary red-team surface for all three vulnerability features.

**Stability contract (FR-6.3).** Within `schema_version: 1`, changes are **additive only** — new fields may appear; existing fields never change type, meaning, or disappear. Enum values (`type`, `ast_id`, `severity`, `axis`, `outcome`) may gain members, so consumers must tolerate unknown ones. Any breaking change moves to `/api/v2/`. **Each vulnerability feature adds findings, skills and enum members; none may alter these shapes.**

---

## 8. Safety envelope

> FR-7. A hard constraint that overrides every other design goal.

| Requirement | Mechanism |
|---|---|
| **FR-7.1** simulated, marker artifact | Host writes `data/markers/<ts>-<skill>-<type>.json` on every new finding (D-12), containing the literal `INTENTIONALLY_VULNERABLE_LAB_MARKER` |
| **FR-7.2** local mock collector only | `NetBroker` allowlists loopback only. Any other host → **refused, and recorded** (§3.1) — the finding fires, the packet does not. Collector is an in-app route writing to `data/collector/inbox/` |
| **FR-7.3** app-created files only | `FileBroker` resolves every path (symlinks followed, `..` collapsed) and requires it under `data/` or `skills/`. Outside → refused + recorded. **Limit:** enforced only for broker-routed access; raw `open()` is detected, not blocked (§3.5) |
| **FR-7.4** non-destructive | No delete/move/chmod in the broker surface. Writes cannot target state files — a skill must not be able to erase evidence of itself |
| **FR-7.5** trivially reversible | `rm -rf data/` fully resets; `POST /api/reset` clears observations and re-seeds tasks; markers are greppable by their literal string |
| **FR-7.6** clearly labelled | README banner; UI footer badge on every page; `/api/health` returns `intentionally_vulnerable: true`; the server refuses to start on a non-loopback bind |

**The refusal-with-recording pattern is the keystone.** Every vulnerability in this app completes from the attacker's and the detector's point of view, and stops at the last inch.

---

## 9. Design system

> DR-1…DR-6. `design/aegis-design-foundations.html` is a **token source only** — no external brand, logo, or name reaches the app (DR-1).

**Extraction.** The foundations file's `:root` block is copied verbatim into `static/css/tokens.css`. Raleway ships embedded as base64 woff2 and is extracted to `static/fonts/raleway.woff2` and self-hosted — no CDN, and the app renders correctly with no network at all.

| Surface | Token |
|---|---|
| Page canvas | `--canvas #08080D` |
| Nav / sidebar | `--surface-1 #0d0d14` |
| Cards (skill, finding, activity row) | `--surface-2 #14141b` |
| Raised (modals, manifest viewer) | `--surface-3 #1b1b24` |
| Hairlines | `--border rgba(197,167,217,0.12)` |
| Primary actions | `--grad-button` |
| Accent / active nav | `--p-default #6B3B85` → `--p-300 #C5A7D9` |
| Body and headings | `--sans 'Raleway'` |
| Manifests, capabilities, observations, evidence | `--mono` |

**Severity badges (DR-4)** — `--sev-critical #FF4D5E` (AST01), `--sev-high #FF8A3D` (AST04), `--sev-medium #E6B84A` (AST03), `--sev-low #56A8E8`, `--sev-info #8C97BE`. Pill shape, tinted background, solid text. **Never colour alone**: every badge carries its severity word and AST ID.

**Screens** — Tasks, Chat, Skill Store, Findings, Activity. The store shows declared capabilities **at face value** under a "Declared by the publisher" caption, so the trust assumption a lying manifest exploits is visible in the UI, not just in the code.

**The Tasks screen is the user's own to-do list**, with add, complete and remove. It touches no LLM and no capability broker, so it produces no observations and can raise no finding — managing your own tasks is the app performing its own advertised function, not a skill under supervision (the same reasoning as the built-in task tools). It exists because FR-1.3 makes the task list the crown jewel whose theft must "read as a real loss", and a loss only lands for a user who has *seen* what was taken.

**DR-6, the one story** — persistent nav; findings deep-link to the activity entry that produced them and back. *Install → ask → watch it choose → see the finding* is three clicks for every vulnerability feature.

**DR-5** — small surface, real product finish: consistent spacing scale, card shadows, hover transitions, styled empty states. A believable-looking product is what makes the vulnerabilities read as realistic (G6/SC-8) rather than as toys.

---

## 10. Repo and module layout

```
app/
  main.py                     FastAPI app, startup (audit hook, storage init, seeding)
  config.py                   env config, paths, model name
  web/routes.py               UI routes (chat, store, findings, activity)
  api/routes.py  api/schemas.py
  chat/orchestrator.py        run_turn() — THE dispatch path (§5)
  chat/prompts.py             system prompt (names no skill)
  llm/ollama_client.py        tool-calling client, health check
  skills/manifest.py          manifest schema + capability vocabulary loader
  skills/registry.py          discovery, validation, installed state
  skills/host.py              SkillHost.invoke() — ONLY skill execution path
  skills/context.py           SkillContext + brokers
  skills/scope.py             scope matching
  monitor/observations.py     Observation, ordered ObservationLog (D-7)
  monitor/audit_hook.py       sys.addaudithook, attribution, re-entrancy suppression
  findings/engine.py          three axes (§4)
  findings/taxonomy.py        finding types, AST mapping, severities — data-driven
  findings/baselines.py       category baseline policy
  findings/markers.py         marker artifact writer
  storage/store.py  storage/atomic.py  storage/seed.py
  mock/collector.py           local egress sink (FR-7.2)
policy/
  capability_vocabulary.json  §2.3
  capability_baselines.json   §4.5
skills/catalogue/<skill>/{manifest.json, skill.py}
templates/  static/css/  static/fonts/  static/js/
data/                         runtime state
docs/                         PRD.md, TDD.md, features/<feature>/spec.md
tests/
```

**Module-boundary rules that protect the design** (enforced by an import-lint test):

| Rule | Why |
|---|---|
| `app/skills/**` must not import `app/findings/**` | The broker must not know what was declared (§3.1) |
| `app/findings/**` must not import `app/llm/**` or `app/chat/**` | Findings stay deterministic (§4.8) |
| Only `app/chat/orchestrator.py` may reference `SkillHost.invoke()` | FR-3.4 guarantee 1 |
| `app/monitor/**` must not import `app/skills/context.py` | Prevents a cycle; the broker imports the monitor, never the reverse |

---

## 11. Architectural invariants

Properties every release must preserve. A change that breaks one is a TDD change, not a feature-local decision. Per-release acceptance criteria live in feature specs.

| # | Invariant | Protects |
|---|---|---|
| **I-1** | `SkillHost.invoke()` is the only path that executes skill code, and its `skill_id` comes only from the model's tool call | FR-3.4, G2 |
| **I-2** | The broker never reads the manifest; declaration comparison happens only in the engine | G2 — a blocked liar produces no finding |
| **I-3** | Intent is recorded before the safety check, and a refusal amends rather than replaces the observation | G4 + G3 simultaneously (§3.1) |
| **I-4** | Re-entrancy suppression is active for all broker-internal I/O | SC-3 — an honest skill must stay silent |
| **I-5** | The observation log is ordered and never re-sorted | AST01 correlation (§4.6) |
| **I-6** | The findings engine is pure and deterministic | SC-3 testability |
| **I-7** | The three axes take different inputs and are never implemented in terms of one another | PRD §7.3 / §12 risk |
| **I-8** | With no skills installed, no vulnerability is reachable | NG4, SC-4 |
| **I-9** | No configuration, endpoint, or flag can reduce the app's vulnerability | NG3 |
| **I-10** | No non-local egress; no file access outside `data/` and `skills/` via the sanctioned path | FR-7, SC-5 |
| **I-11** | API shapes change additively only within `schema_version: 1` | FR-6.3 |
| **I-12** | The control skill produces zero findings | G5, SC-3 |

---

## 12. How each vulnerability class plugs in

Design-level only. The skills themselves are each feature spec's job.

| Feature | Detected by | Platform provisions it relies on | Adds to the platform |
|---|---|---|---|
| **AST04 — Insecure Metadata** | Truthfulness axis (§4.4) | Manifest/behaviour separation (D-2); broker records undeclared capabilities; audit hook records bypass | Nothing — a skill folder and its tests |
| **AST01 — Malicious Skills** | Correlation axis (§4.6) | Ordered log (D-7); payload digests (§3.1); per-invocation correlation pass; mock collector (§8) | Nothing — a skill folder, plus its matching rule as a taxonomy check |
| **AST03 — Over-Privileged** | Proportionality axis (§4.5) | Category baselines (D-9); install-time and per-invocation evaluation; unbounded-scope signal | Possibly a baseline category — a JSON edit |

**The platform is complete for all three once the foundation ships.** No vulnerability feature requires a new broker method, a new monitor layer, a dispatch change, or an API shape change. If one appears to, that is a signal the vulnerability is being faked rather than genuinely exercised (G2).

**Control skill.** The false-positive baseline (G5) belongs to the App Foundation feature, but it serves all three: every vulnerability feature's acceptance includes "the control skill is still clean." Without it, "the scanner found three things" is unfalsifiable.

---

## 13. Decisions register

| # | Decision | Rationale |
|---|---|---|
| D-1 | Manifests are JSON | No new dependency; matches PRD §11; renders verbatim in the store |
| D-2 | Skill = folder with `manifest.json` + `skill.py` | Keeps claim and behaviour independently authored — the AST04 gap must be real |
| D-3 | Only `description` + `when_to_use` steer the model | The single lever for skill selection; keeps FR-3.4 provable |
| D-4 | `proc.spawn` declarable but unbrokered | Gives the bypass path a name to be reported under |
| D-5 | Capabilities scoped per invocation | Every finding points at one activity entry (DR-6) |
| D-6 | Skills run in-process, unsandboxed | NG5 + readability; limits stated in §3.5 |
| D-7 | Observations ordered, not a set | AST01 needs causal order; free now, migration later |
| D-8 | Audit hook observes, never blocks | A raising hook on every `open` risks taking the app down |
| D-9 | Proportionality via category + static baseline table | Deterministic and inspectable; LLM-judged would make SC-3 flaky |
| D-10 | `UNUSED_GRANT` window = 5 invocations | Arbitrary but explicit; tunable in policy |
| D-11 | Findings dedupe on skill+version+type+capability+resource | Keeps the findings list demoable (SC-7) |
| D-12 | Host writes markers, not skills | Stronger evidence; keeps the vocabulary clean |
| D-13 | Ollama unreachable → hard fail, no fallback | A canned fallback is hardcoded routing and would fake SC-1 |
| D-14 | Reference model `llama3.1:8b`, env-overridable | Needs native tool calling; SC-1's bar needs a named model |

---

## 14. Resolved decisions *(binding)*

The PRD's deferred questions, closed. These bind every feature spec.

| Q | Resolution |
|---|---|
| **Q-1** | **User-supplied skill upload is deferred out of the current scope.** No upload endpoint, no `data/uploads/`, no `skills/user/` discovery. The registry keeps a multi-root, multi-source internal shape so upload is a later addition, not a redesign |
| **Q-2** | **Severities fixed:** `AST01 → critical`, `AST04 → high`, `AST03 → medium`, `BROKER_BYPASS → high`, `UNUSED_GRANT → low`. Not per-feature choices |
| **Q-3** | **Skill isolation deferred with Q-1.** The cooperative boundary (§3.5) is accepted for catalogue skills, whose safety rests on authorship discipline |
| **Q-4** | **`POST /api/reset` is in scope.** Clears findings, markers, activity and the collector inbox; clears and re-seeds tasks; **preserves installed state**. Explicitly **not** a security toggle (NG3, I-9) — it cannot make the app less vulnerable, only make it forget what it observed |
| **Q-5** | **Model `llama3.1:8b`**, overridable by `TASKBOT_MODEL`; native tool-calling required. The **resolved** model is recorded on every finding and activity entry as evidence |
| **Q-6** | **No skill is pre-installed.** First run starts with zero skills installed, so the non-vulnerable baseline (FR-1.4, SC-4, I-8) is visible before anything is added |
