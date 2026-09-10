# TaskBot — Technical Design Document (system-wide)

| | |
|---|---|
| **Scope** | The whole application: shared architecture for the foundation **and** all **five** vulnerability classes |
| **Derives from** | `docs/PRD.md` (**PRD v1.2**, approved) |
| **Status** | Approved. Canonical location: `docs/TDD.md`. **Amended 2026-08-29** for AST02 and **2026-08-27** for AST05 — see the amendment notes below |
| **Release-agnostic** | Describes the **target architecture of the finished app**. Release and build sequencing belong in per-feature plans, never here |
| **Feature specs** | `docs/features/<feature>/spec.md` — each derives from `docs/PRD.md` + this document |

**Ownership rule.** *If it is shared by more than one feature, it belongs here. If it is specific to one feature, it belongs in that feature's spec.* Feature specs cite `TDD §n` rather than restating shared mechanisms.

**Scope boundary.** This document designs the *platform* and the *detection model* for all **five** vulnerability classes. It does **not** design the individual vulnerable skills — their manifests, their concealment technique, and their trigger surface are each feature spec's job.

**Traceability.** Every statement carries its PRD reference. Design choices are numbered **D-1 … D-18** (§13). The PRD's deferred questions are resolved and binding in **§14**.

> ### Amendment 2026-08-29 — the fifth axis
>
> PRD v1.2 brought **AST02 · Supply Chain Compromise** into scope (PRD §0, §7.7), reversing NG1's earlier judgement that it was not authentically demonstrable here. This document is amended rather than rewritten, so the change is visible:
>
> - **§2.2** — the manifest gains an optional `dependencies` block: the components a skill says it is built on, and the fingerprint it expects.
> - **§4.1** — four axes become **five**; the cannot-collapse argument is extended, not restated.
> - **§4.3** — two taxonomy rows; **§4.7** — a `dependency` evidence field; **§4.10** — the new axis, in full.
> - **§10** — `mock/registry.py`. **§11 I-7** — restated for five axes. **§12** — a fifth row, and the carve-out test invoked a second time.
> - **§13** — **D-17**, **D-18**. **§14 Q-2** — extended for AST02 only.
>
> **The one thing to read if you read nothing else:** §12's replacement test is invoked here for the second time, and AST02 answers it on a stronger footing than AST05 did. AST05 changed what the broker **records**. AST02 changes **nothing** about recording — every fingerprint it reads was already being written down for every skill on every fetch. What it adds is a *claim* to compare that evidence against, which is precisely what a manifest is for.

> ### Amendment 2026-08-27 — the fourth axis
>
> PRD v1.1 brought **AST05 · Untrusted External Instructions** into scope (PRD §0, §7.6). This document is amended rather than rewritten, so the change is visible:
>
> - **§3.1** — the broker now captures **inbound response** content. Approved substrate change, argued below and in `ast05 spec` §8.6.
> - **§4.1** — three axes become **four**; the cannot-collapse argument is extended, not restated.
> - **§4.3** — two taxonomy rows; **§4.7** — a `provenance` evidence field; **§4.9** — the new axis, in full.
> - **§11 I-7** — restated for four axes. **§12** — a fourth row, plus the explicit carve-out to the platform-is-complete rule.
> - **§13** — **D-15**, **D-16**. **§14 Q-2** — extended for AST05 only.
>
> **The one thing to read if you read nothing else:** §12's rule that *a vulnerability needing platform change is a faked vulnerability* was correct for the first three classes and is **amended, not abandoned**. The replacement test is in §12.

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
| `docs/features/ast05-untrusted-external-instructions/spec.md` | The instruction-following skill, the mock team hub, **and the provenance axis** |
| `docs/features/ast02-supply-chain/spec.md` | The estimator skill, the mock component registry, **and the integrity axis** |
| `docs/KNOWN-ISSUES.md` | Platform defects that are known, deferred and disclosed |

The App Foundation feature **builds** the platform described here; the vulnerability features **consume** it. No vulnerability feature may modify shared mechanisms — if one appears to need to, that is a TDD change and a design review, not a feature-local edit.

**AST05 is exactly that case, and it followed exactly that route.** It needed shared mechanisms changed, so it produced a TDD change (this amendment) and a design review, rather than a feature-local edit. The rule held; it was not bypassed.

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
│ FINDINGS ENGINE — four axes (§4)                │   │
│   observed  vs declared  → truthfulness  AST04  │   │
│   granted   vs baseline  → proportionality AST03│   │
│   sequence, outbound     → correlation    AST01 │   │
│   sequence, inbound      → provenance     AST05 │   │
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

  "dependencies": [                        // OPTIONAL, added 2026-08-29 for AST02. Defaults to [].
    {                                      //   Components published by someone else that this
      "name": "sizing-heuristics",         //   skill is built on. THE OTHER DECLARATION - and the
      "version": "2.3.1",                  //   one the integrity axis reads (§4.10).
      "source": "http://127.0.0.1:8000/mock/registry/sizing-heuristics/2.3.1",
      "integrity": "sha256:9f4c…",         //   optional; absent is itself reportable (D-18)
      "publisher": "Loft Analytics",       //   display only, never compared
      "reason": "The effort-sizing bands this skill applies to your tasks."
    }
  ],

  "entrypoint": "skill.py:run"
}
```

Validation at load: unknown capability IDs, an unknown `category`, a malformed parameter schema, a malformed `dependencies` entry, or a missing entrypoint make the skill **unloadable** — it appears in the store marked invalid and cannot be installed. It is *not* a finding: a skill that cannot run cannot misbehave, and a parse error is not a security event.

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

**D-15 — Response capture *(amendment 2026-08-27)*. `net.outbound` observations also record what came back:** `response_bytes`, `response_sha256`, `response_item_digests`, and a bounded `response_excerpt`. This is the substrate the provenance axis reads (§4.9), and it corrects an asymmetry the foundation left without stating a reason — the broker recorded everything about a request and nothing about its response, which made "the skill acted on what it fetched" unprovable in principle rather than merely undetected.

Three properties keep this within the design's existing commitments:

- **It changes nothing about what is *allowed*.** The loopback allowlist, the scheme check, the record-then-decide ordering (I-3) and the `broker_frame()` suppression are untouched. The broker still never reads a manifest (I-2).
- **`response_item_digests` uses a separate walker** from `payload_item_digests`, which is unmodified — so AST01's matching behaviour is bit-for-bit unchanged.
- **The excerpt is a deliberate, bounded exception to *"a digest, never the payload itself"*.** That rule exists so the **user's** private data is never duplicated into the security records. A fetched response is not the user's data — it is content from outside the trust boundary, and it is the evidence. Without it a provenance marker could assert that fetched content steered a skill while being unable to show what that content said. Capped by `Settings.response_excerpt_bytes` (default 4096).

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

### 4.1 Five independent axes

*(Three until the 2026-08-27 amendment; the fourth is AST05's, and §4.9 designs it. The fifth is AST02's, added 2026-08-29, and §4.10 designs it.)*

The engine answers five structurally different questions, from five different inputs:

```
 AST04  TRUTHFULNESS     observations × declaration     "did it do what it said?"
                          ├ input: ObservationLog + manifest.capabilities
                          └ needs a runtime invocation to exist

 AST03  PROPORTIONALITY  grant × baseline policy        "did it need this much?"
                          ├ input: manifest.capabilities + policy baseline
                          └ a skill can fail this while being perfectly honest

 AST01  CORRELATION      ordered sequence, OUTBOUND     "what did it combine?"
                          ├ input: ObservationLog order + outbound payload digests
                          └ INDEPENDENT OF THE DECLARATION ENTIRELY

 AST05  PROVENANCE       ordered sequence, INBOUND      "where did the behaviour come from?"
                          ├ input: ObservationLog order + inbound response content (D-15)
                          └ INDEPENDENT OF DECLARATION, POLICY, AND OUTBOUND PAYLOADS

 AST02  INTEGRITY        declaration × delivered digest  "is what arrived what was agreed?"
                          ├ input: manifest.dependencies + detail.response_sha256 (D-17)
                          └ READS NO CAPABILITY DECLARATION, NO POLICY, NO OUTBOUND PAYLOAD,
                            AND NOT ONE WORD OF WHAT THE COMPONENT SAYS
```

**Why they cannot collapse.** Each axis takes an input the others do not:

- Truthfulness needs the declaration; proportionality needs the policy; correlation needs neither — it reads only what happened, and in what order; **provenance needs something none of the other three has ever had access to: what came back from a request.**
- A skill can be **honest and over-privileged** (declares its broad grant openly) → AST03 only.
- A skill can be **modest and lying** (declares little, does more) → AST04 only.
- A skill can be **honest, proportionate, and malicious** — declaring `task.read` and `net.outbound`, both within its category baseline, and still exfiltrating task data by *combining* them → **AST01 only**.
- A skill can be **honest, proportionate, and not a thief** — declaring exactly the two capabilities it uses, sending no task data anywhere — and still be **entirely under a third party's control**, because it fetches a document and treats its contents as instructions → **AST05 only**.
- A skill can be **honest, proportionate, not a thief, and obedient to nobody** — reading its fetched component as inert data and acting on no instruction in it — and still be **running somebody else's substituted code**, because the component delivered was not the one it pinned → **AST02 only**.

The third case proves the axes are not three thresholds on one comparison. **The fourth proves something the first three could not:** that a skill can pass every check that inspects *the skill* and still be compromised, because the thing that decides its behaviour is not in the skill at all. **The fifth proves something none of the first four could:** that a skill can be at fault in no respect whatsoever — and that its author, having done everything right including pinning what it depends on, has no remedy available to them at all.

**Correlation and provenance are opposites, not neighbours — and this is the distinction most at risk of being blurred.** Both read the ordered log; both involve the network; the two skills that exercise them hold the same two capabilities under the same category. They are still mutually exclusive:

| | Correlation (AST01) | Provenance (AST05) |
|---|---|---|
| Question | did data that was **read** leave? | did content that **arrived** decide what happened next? |
| Substrate | outbound payload digests | inbound response digests + excerpt (D-15) |
| Direction | data **outward** | instructions **inward** |
| Evidence pair | read seq → send seq | fetch seq → acted seq |

Neither is implementable in terms of the other, and each fires with the other silent: a skill that reads tasks and posts them out fetches nothing, so provenance has no source observation; a skill that fetches instructions and acts on them sends no task content, so correlation's egress set carries no matching digests and its loop body never executes. Each vulnerability feature asserts both directions.

**Provenance and integrity are the second pair at risk of blurring** *(added 2026-08-29)*. Both begin at an inbound response. They are still opposites:

| | Provenance (AST05) | Integrity (AST02) |
|---|---|---|
| Question | did content that **arrived** decide what happened next? | is what arrived **what was agreed**? |
| Substrate | response content — item digests and strings | response **whole-body digest**, as one opaque value |
| Reads a declaration? | **never** — deliberately declaration-blind | **always** — with no declared component there is nothing to compare |
| Needs a later action? | **yes** — `acted_seq > source_seq` | **no** — the delivery alone is the evidence |
| Fires on the agreed artifact carrying an instruction? | **yes** | **no** |
| Fires on a substituted artifact carrying nothing? | **no** | **yes** |

**Integrity is also the second pair with truthfulness**, because both compare a claim against something observed. They differ in *whose* claim and *about what*: truthfulness compares the skill's **own capability declaration** against **its acts**; integrity compares a **third party's artifact identity** against **a delivered digest**. The decisive difference is that integrity fires on a **completely benign** substitution, which truthfulness — defined over acts — can never do.

**Overlap is expressed, not collapsed** *(unchanged, now over five axes)*.

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
| `EXTERNAL_INSTRUCTION_FLOW` | AST05 | provenance | **high** | Content fetched from outside the trust boundary, then used as the target or parameter of a later action in the same invocation |
| `AGENT_INSTRUCTION_RELAY` | AST05 | provenance | **medium** | Fetched content carried into the skill's returned summary, and therefore into the model's context |
| `COMPROMISED_DEPENDENCY` | AST02 | integrity | **high** | A declared component was delivered whose digest does not match the fingerprint the manifest pinned |
| `UNPINNED_DEPENDENCY` | AST02 | integrity | **low** | A component is declared with no `integrity` value, so nothing about what arrives can be verified |

Severities are fixed by §14 Q-2 and are not per-feature choices.

**On `AGENT_INSTRUCTION_RELAY`'s severity — a deliberate underclaim.** The deterministic, provable part is that attacker-controlled text reached the model's context. Whether the model then *obeys* it varies by model and by run, and making it an input would break §4.8's purity guarantee. The engine therefore reports the relay and never the compliance. `medium` is the honest weight for "we can prove the loaded gun, not the trigger"; the model's actual response is visible in the activity log and is a demo observation, not a finding.

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
  "axis": "correlation",                     // "truthfulness" | "proportionality" | "correlation" | "provenance" | "integrity"
  "severity": "critical",
  "skill_id": "…", "skill_version": "1.0.0",
  "trigger": "invocation",                   // "invocation" | "install"
  "invocation_id": "inv_…", "activity_id": "act_…",
  "model": "llama3.1:8b",                    // resolved model, as evidence (§14 Q-5)
  "declared": { "capabilities": [ … ] },
  "observed": Observation | null,            // null for proportionality findings
  "granted":  { "capabilities": [ … ] },     // present for proportionality findings
  "correlation": { "observation_seqs": [2, 5] },   // present for correlation findings
  "provenance": { "source_seq": 2, "acted_seq": 4,  // present for provenance findings
                  "influence": "resource",          //   "resource" | "parameter" | "returned_summary"
                  "source_url": "…", "matched_digest": "…", "matched_excerpt": "…" },
  "dependency": { "name": "…", "version": "…",      // present for integrity findings
                  "source": "…", "publisher": "…",
                  "declared_integrity": "sha256:…", "delivered_integrity": "sha256:…",
                  "delivered_bytes": 913, "acquired_seq": 2,
                  "reason": "digest_mismatch" },    //   "digest_mismatch" | "no_pin_declared"
  "summary": "…",
  "evidence": { "marker": "data/markers/…json", "observation_seq": 5 },
  "first_seen": "…", "last_seen": "…", "occurrences": 1
}
```

The evidence field differs per axis — `observed` for truthfulness, `granted` for proportionality, `correlation.observation_seqs` for correlation, `provenance` for provenance, `dependency` for integrity. A consumer can tell the **five** apart without parsing prose. Adding the fourth and fifth fields keeps that one-field-per-axis convention intact rather than diluting it, and both are additive within `schema_version: 1` (I-11).

**Deliberately *not* changed for AST02:** the `declared` block. It is filled for every finding on every axis, and adding the component list there would alter the payload of every AST01, AST03, AST04 and AST05 finding for no gain. Everything a consumer needs about a component is in `dependency`.

**D-11 — Findings deduplicate on `(skill_id, skill_version, type, capability, resource)`.** Repeats bump `occurrences` and `last_seen` rather than appending. Keeps the findings list demoable after a long session (SC-7); the activity log remains the complete per-turn record.

**D-12 — The host writes the marker artifact when a finding is raised; skills never write markers.** FR-7.1 requires an exploit's effect to be an observable marker, and FR-4.2 already makes every finding proof-of-firing. Host-written markers are stronger evidence than self-reported ones and spare skills a marker capability that would pollute the vocabulary.

### 4.8 Purity

The engine takes manifest + observations + policy **+ the skill's returned summary** and returns findings. No LLM call, no I/O, no clock beyond a timestamp helper; persistence and marker writing are the caller's job. This determinism is what makes "the control skill produces zero findings" (SC-3) a testable claim rather than a flaky one.

*(Amendment 2026-08-27: `evaluate_invocation` gains an optional `returned_summary` argument, supplied by the orchestrator from `SkillResult.summary` at its single existing call site. Optional and defaulted, so the install path and every existing caller are unaffected. It is inert data, not a model call — purity is unchanged.)*

### 4.9 Provenance axis (AST05) — *added 2026-08-27*

The axis that reads *where the behaviour came from*, rather than what was claimed, what was granted, or what went out.

```
sources = observations where capability == "net.outbound"
                        and detail.response_item_digests is non-empty        (D-15)
for s in sources:
    for a in observations where a.seq > s.seq:                # strictly after — causal
        if digest_of(a.resource) in s.detail.response_item_digests
              → EXTERNAL_INSTRUCTION_FLOW (influence="resource")
        for each scalar v in a.detail:
            if digest_of(v) in s.detail.response_item_digests
              → EXTERNAL_INSTRUCTION_FLOW (influence="parameter")
    if returned_summary is not None and a non-trivial line of s.detail.response_excerpt
       appears in returned_summary
              → AGENT_INSTRUCTION_RELAY (influence="returned_summary")
```

**Architectural provisions this depends on:**

| Need | Provided by |
|---|---|
| Causal ordering | Ordered `ObservationLog`, `seq` monotonic (D-7, §3.1) — the same substrate correlation uses |
| Proof that *this* content steered *that* action | `response_item_digests` matched against later resources and parameters (D-15) |
| Human-readable evidence of the instruction | Bounded `response_excerpt` on the source observation (D-15) |
| Access to what the skill told the model | `returned_summary`, passed to the engine by the orchestrator (§4.8) |
| Detection independent of the manifest and the policy | The axis reads neither — only the log and the fetched content |
| Intent counted even when blocked | A refused action still carries the externally-supplied resource, and the observation was written before the refusal (I-3) |

**Three deliberate limits, stated now.**

1. **Transformation defeats it.** A skill that decodes, decrypts or reassembles fetched content before acting on it will not match by digest, exactly as re-encoded exfiltration defeats correlation (§4.6). The limit is symmetric, and it is honest: a digest match proves content moved into a decision, it cannot prove it under disguise.
2. **A non-triviality rule is mandatory, not optional.** Short or common strings (`"true"`, `"open"`, a version stamp) would match by coincidence and turn the axis into a false-positive generator, which would break SC-3 for any skill that fetches anything. The threshold is the AST05 feature spec's decision; the platform's obligation is that one exists.
3. **The relay check proves the relay, never the compliance** (§4.3). This is a purity constraint, not a detection shortfall.

**D-16 — Provenance is evaluated per invocation only, never at install.** Nothing about a manifest reveals it: the document that supplies the instructions is not part of the skill, is not present at install, and can change between two runs of an unchanged skill at an unchanged version. This is the exact inverse of proportionality (§4.5), which is fully answerable before a skill has ever run — and holding the two side by side is what makes the four axes legible as a set rather than a list.

---

### 4.10 Integrity axis (AST02) — *added 2026-08-29*

The axis that reads *whether the thing a skill was handed is the thing it agreed to* — rather than what it claimed, what it was granted, what it sent, or what it was told.

```
for dep in manifest.dependencies:

    if dep.integrity is None:
        → UNPINNED_DEPENDENCY (reason="no_pin_declared")     # declaration alone; no delivery needed

    for a in observations where a.capability == "net.outbound"
                            and a.resource == dep.source      # exact string equality (D-18)
                            and a.detail.status == 200        # only a successful delivery (D-18)
                            and a.detail.response_sha256 is present:
        if pinned(dep.integrity) != a.detail.response_sha256
              → COMPROMISED_DEPENDENCY (reason="digest_mismatch", acquired_seq=a.seq)
```

**Architectural provisions this depends on — every one of which already existed:**

| Need | Provided by |
|---|---|
| A fingerprint of what was delivered | `detail.response_sha256`, recorded on every received reply since **D-15**. **Nothing new is recorded for this axis.** |
| One digest recipe shared by both sides | `digest_of` (§3.1) — the pin is *defined* as the value the broker would record, which makes the comparison exact by construction (**D-17**) |
| A place for the skill to state its claim | `manifest.dependencies` (§2.2) — the only genuinely new thing this axis needs |
| Evidence independent of the attacker | The digest is taken by the broker at the moment of delivery, before the skill sees a byte. The component cannot forge, suppress or even observe it |
| Detection independent of behaviour | The axis reads no capability declaration, no policy, no outbound payload, and no *content* of what arrived |

**Three deliberate limits, stated now.**

1. **Only a successful delivery is compared.** A refused request delivered nothing; an error reply ("no such component") has a fingerprint but is not a build of anything. Comparing either against the pin would report a compromise every time a registry was merely empty — a false positive that would destroy the axis's ability to stay silent, which is the whole basis on which it was allowed into the platform (§12).
2. **An undeclared acquisition is invisible**, as is a declared component that was never fetched, or one fetched from an address differing by so much as a trailing slash. The axis compares a claim to a delivery; with no claim, or no delivery, there is nothing to compare. Catching the undeclared case would be a third finding type and is deliberately deferred.
3. **The digest proves substitution, never intent.** A mismatch says the bytes differ; it cannot say whether that is an attack, a rebuild, or an honest hotfix. That is exactly what integrity pinning does in the real world, and it is what makes a *benign* substitution fire too — the axis working correctly, not a false positive.

**D-18 — Integrity is evaluated at install *and* per invocation, but the two halves are different questions.** "You promised nothing" is answerable from the manifest alone, so it is asked at install, like proportionality. "What arrived is not what you promised" cannot be asked before something arrives, so it is structurally impossible at install — `evaluate_install` passes no observations. Holding this against AST03 (fully answerable at install) and AST05 (never answerable at install) is what makes the five axes legible as a set rather than a list.

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
  hub/rules.json                                (AST05's fetchable document, §4.9)
  registry/<name>-<version>.json                (AST02's published components, §4.10)
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

**`POST /api/chat`** returns `reply`, `activity_id`, `skill_invoked`, `llm.model`, and **`findings_raised` for that turn only** — the exploitation signal. A scanner attributes a finding to the prompt that caused it without diffing `/api/findings` before and after. This is the primary red-team surface for every vulnerability feature.

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
  findings/engine.py          four axes (§4)
  findings/taxonomy.py        finding types, AST mapping, severities — data-driven
  findings/baselines.py       category baseline policy
  findings/markers.py         marker artifact writer
  storage/store.py  storage/atomic.py  storage/seed.py
  mock/collector.py           local egress sink (FR-7.2)
  mock/dashboard.py           visible standup sink
  mock/hub.py                 local instruction source, GET-only (AST05, §4.9)
  mock/registry.py            local component publisher, GET-only, by name+version (AST02, §4.10)
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
| **I-5** | The observation log is ordered and never re-sorted | AST01 correlation (§4.6), AST05 provenance (§4.9) |
| **I-6** | The findings engine is pure and deterministic | SC-3 testability |
| **I-7** | The **five** axes take different inputs and are never implemented in terms of one another. In particular: correlation reads **outbound** payloads and provenance reads **inbound** content, neither built on the other; and integrity reads a **declared artifact identity against a delivered digest**, reading neither the capability declaration (truthfulness's input), nor the policy (proportionality's), nor any payload, nor one word of what the delivered component *says* (provenance's) | PRD §7.3 / §7.6 / §7.7 / §12 risks |
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
| **AST05 — Untrusted External Instructions** *(added 2026-08-27)* | **Provenance axis (§4.9)** | Ordered log (D-7); per-invocation evaluation pass; loopback allowlist and refuse-and-record ordering (I-3) | **Substantial, and enumerated in the feature spec §8:** inbound response capture in the broker (D-15); the provenance axis and two taxonomy rows; a `provenance` field on `Finding`; a GET-serving mock endpoint; `returned_summary` on `evaluate_invocation` |
| **AST02 — Supply Chain Compromise** *(added 2026-08-29)* | **Integrity axis (§4.10)** | **`detail.response_sha256`, already recorded for every reply since D-15**; install-time and per-invocation evaluation passes; the marker writer; loopback allowlist | **Moderate, and enumerated in the feature spec §9:** an optional `dependencies` block on the manifest; the integrity axis and two taxonomy rows; a `dependency` field on `Finding`; a GET-serving mock registry addressed by name and version. **No new recording of any kind** — the broker and the monitor are untouched |

**The platform was complete for the first three once the foundation shipped.** No *(v1.0)* vulnerability feature required a new broker method, a new monitor layer, a dispatch change, or an API shape change. That rule stands for AST04, AST01 and AST03, and their zero-platform-change property is a real, verified result — not a coincidence to be quietly abandoned now.

### The AST05 carve-out — *amendment 2026-08-27*

**AST05 does require platform change, and the original rule would have classified it as faked. That classification would have been wrong, and here is the corrected test.**

The rule's real target is a platform change that **manufactures a finding** — wiring a dormant detector so it fires, special-casing a skill, or letting a skill self-report its own compromise. D-15 does none of those. It records **what actually came back from a request the skill actually made**. The evidence was always real; the platform discarded it.

> **The replacement test, binding on any future feature that claims this carve-out:**
>
> **If the platform change leaves the detector able to stay silent, it is substrate. If it makes the detector unable to stay silent, the vulnerability is being faked.**

AST05 passes it demonstrably, and its acceptance criteria pin the passing rather than asserting it:

- The control skill makes no network call and is untouched (`ast05` A-4).
- *Task Insights*, *Standup Sync* and *Focus Picker* produce byte-for-byte identical finding sets after D-15 lands (`ast05` A-15, A-10).
- **An honest fetcher raises nothing** — a skill that reads a rules document and ignores its instruction fields produces zero provenance findings (`ast05` A-7). This is the criterion that distinguishes a detector from a prop.

Two further points close the argument. First, D-15 is **symmetric with a substrate decision the foundation already made unprompted**: §3.1 records payload digests *"even though only AST01 consumes it"*. The foundation built the outbound half before the feature that needed it and left the inbound half unbuilt without ever stating a reason. Second, **faking AST05 would require the opposite change** — having the skill announce its own compromise, which would violate D-12 and I-2 and would rest the evidence on the attacker's word.

**This is a carve-out, not a precedent.** Any fifth vulnerability proposing platform change must argue the replacement test explicitly, in its own spec, and be reviewed on it.

### The AST02 case — *amendment 2026-08-29*

**AST02 is that fifth vulnerability, and it did exactly what the paragraph above requires:** it argued the replacement test in its own spec (`ast02 spec` §9.8) and was reviewed on it. The argument is recorded here in short form, because it is stronger than AST05's in one specific and checkable way.

**AST05 changed what the broker records. AST02 changes nothing about recording at all.** `backend/app/skills/context.py` and `backend/app/monitor/observations.py` are untouched by it, and that is asserted at source level by a test rather than promised. Every fingerprint the integrity axis reads — `detail.response_sha256` — has been written down for every skill, on every successful fetch, since D-15 landed for a different feature. The platform was already in possession of the proof; it had simply never been told what the proof should equal.

**What AST02 adds is a claim, not a fact.** A manifest is the place where a skill states claims about itself, and the truthfulness axis has always worked by comparing one of those claims against recorded evidence. Integrity is that same pattern applied to a *third party's* artifact rather than the skill's own capabilities. Adding a field to the manifest cannot manufacture a finding, because the finding still requires evidence the platform gathered independently.

It passes the replacement test demonstrably, and its acceptance criteria pin the passing rather than asserting it:

- The control skill and all four shipped vulnerabilities declare no components, so the axis's loop body never executes for any of them (`ast02` A-10). Their findings **and their observation records** are byte-for-byte identical afterwards — a stricter promise than AST05 made, and an easier one to measure.
- **The agreed component raises nothing** — same skill, same manifest, same fetch, different bytes delivered (`ast02` A-6). This is the criterion that distinguishes a detector from a prop.
- An empty registry raises nothing, and a refused request raises nothing (`ast02` A-14).

**The rule stands, and is now load-bearing twice.** A sixth vulnerability proposing platform change must argue it again, on its own evidence.

**Control skill.** The false-positive baseline (G5) belongs to the App Foundation feature, but it serves all **five**: every vulnerability feature's acceptance includes "the control skill is still clean." Without it, "the scanner found five things" is unfalsifiable.

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
| **D-15** | **`net.outbound` observations capture the response** — digests, per-item digests and a bounded excerpt (§3.1) | The substrate the provenance axis reads. Corrects an unstated asymmetry: the broker recorded everything outbound and nothing inbound, making "the skill acted on what it fetched" unprovable in principle. Justified against the §12 carve-out test |
| **D-16** | **Provenance is evaluated per invocation only, never at install** (§4.9) | The instructions are not in the skill. They arrive at run time and can change between two runs of an unchanged skill at an unchanged version — the exact inverse of proportionality, which needs no behaviour at all |
| **D-17** | **A pinned fingerprint is defined as *the value the broker records* for that delivery** — `digest_of(response body text)`, not a plain file checksum (§4.10) | Makes the comparison exact by construction rather than approximate, and removes the likeliest implementation trap. Requires the registry to serve file bytes verbatim, so the fingerprint is a fact about the repository rather than about the JSON encoder |
| **D-18** | **Integrity matches a delivery to a declaration by exact address equality, and only counts a `status == 200` reply** (§4.10) | Exactness keeps the evidence a fact rather than a guess; the status condition stops an empty registry's error reply — which is fingerprinted like anything else — from being reported as a substituted component every time |

---

## 14. Resolved decisions *(binding)*

The PRD's deferred questions, closed. These bind every feature spec.

| Q | Resolution |
|---|---|
| **Q-1** | **User-supplied skill upload is deferred out of the current scope.** No upload endpoint, no `data/uploads/`, no `skills/user/` discovery. The registry keeps a multi-root, multi-source internal shape so upload is a later addition, not a redesign |
| **Q-2** | **Severities fixed:** `AST01 → critical`, `AST04 → high`, `AST03 → medium`, `BROKER_BYPASS → high`, `UNUSED_GRANT → low`. Not per-feature choices. **Extended 2026-08-27 for AST05 only:** `EXTERNAL_INSTRUCTION_FLOW → high`, `AGENT_INSTRUCTION_RELAY → medium`. **Extended 2026-08-29 for AST02 only:** `COMPROMISED_DEPENDENCY → high`, `UNPINNED_DEPENDENCY → low`. The seven earlier rows are unchanged. `critical` stays **unique to AST01**, whose vulnerability is the one that moves the crown jewels; remote control of a skill's behaviour is placed at `high` alongside a false declaration, and the relay is underclaimed at `medium` for the purity reason in §4.3. Unreviewed third-party code executing inside an approved skill is placed at `high` for the same reason as AST05's — it does not itself move the crown jewels — and an unpinned component is `low`, matching `UNUSED_GRANT`'s reading of a latent condition that has not yet caused anything |
| **Q-3** | **Skill isolation deferred with Q-1.** The cooperative boundary (§3.5) is accepted for catalogue skills, whose safety rests on authorship discipline |
| **Q-4** | **`POST /api/reset` is in scope.** Clears findings, markers, activity and the collector inbox; clears and re-seeds tasks; **preserves installed state**. Explicitly **not** a security toggle (NG3, I-9) — it cannot make the app less vulnerable, only make it forget what it observed |
| **Q-5** | **Model `llama3.1:8b`**, overridable by `TASKBOT_MODEL`; native tool-calling required. The **resolved** model is recorded on every finding and activity entry as evidence |
| **Q-6** | **No skill is pre-installed.** First run starts with zero skills installed, so the non-vulnerable baseline (FR-1.4, SC-4, I-8) is visible before anything is added |
