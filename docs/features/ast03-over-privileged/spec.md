# Feature: AST03 — Over-Privileged Skills — Specification

| | |
|---|---|
| **Feature** | AST03 · Over-Privileged Skills — a simple utility that honestly declares, and is honestly granted, far more capability than its job warrants |
| **Derives from** | `docs/PRD.md` (PRD v1.0) §7.3 + `docs/TDD.md` (system-wide technical design) §4.5 |
| **Status** | **Built.** The skill and its tests ship under `vulnerabilities/ast03-over-privileged/`; zero platform change, verified. A-2…A-13 pass; **A-1 is the live-model manual check and has not been run**. |
| **Siblings** | `app-foundation` (built) · `ast04-insecure-metadata` (built) · `ast01-malicious-skills` (built) |

> **Reference rule.** Shared architecture is **not restated here** — it is cited as `TDD §n`, and the platform mechanics this feature stands on are cited into the App Foundation spec as `Foundation §n` / `Foundation S-n` / `Foundation A-n`. This document specifies only what the AST03 feature adds.
>
> **Conventions.** Details settled at spec level are numbered **S-1 … S-11** (§10) and are local to this spec. Type signatures and JSON shapes are interface specification, not implementation; no function bodies appear. A-list acceptance criteria are **A-1 … A-13** (§9).

---

## 1. Scope and derivation

> The proportionality axis — the check that catches a disproportionate grant — is `TDD §4.5`, and it is **already built and already firing** in the platform: `check_proportionality` in `backend/app/findings/engine.py`, called at install from `backend/app/api/routes.py` (`evaluate_install`) and on every skill run from `backend/app/chat/orchestrator.py` (`evaluate_invocation`). The category yardstick it measures against is `backend/policy/capability_baselines.json`. Like AST04, this feature builds **nothing** on the platform. It ships a skill that exercises the axis, and the proof that it does.

### 1.1 In scope

- **One over-privileged skill**, *Focus Picker*, shipped under `vulnerabilities/ast03-over-privileged/` (§4). Its advertised function — telling the user which task to work on next — works correctly and needs `task.read` and nothing else. Its manifest **honestly** declares four capabilities: `task.read` (needed), plus `fs.read`, `task.write` and `net.outbound` (not needed by its job, and outside its category baseline). The host grants exactly what is declared (`G ≡ D`, `TDD §4.2`).
- **The over-reach is real, not a claim** — the skill genuinely exercises one excess capability (`fs.read` over the app's activity log) through the real `FileBroker`, so the observation log shows an observed capability set that materially exceeds what the job requires (PRD §7.3 *"holds and exercises"*). The other two excess grants are held and never touched — dormant privilege (§4.3, **S-5**, **S-6**).
- **Three `EXCESSIVE_GRANT` findings** (AST03, proportionality, **medium**), one per capability outside the `reporting` baseline, raised at install and again on every invocation (§5.1). Verified against the shipped baselines file — see §5.4.
- **The `UNUSED_GRANT` position, stated honestly** — the shipped manifest is *eligible* for `UNUSED_GRANT` on `task.write` and `net.outbound`, and that is proved at unit level against the existing `check_unused_grants`. It cannot currently appear in `/api/findings`, because **no caller in the platform invokes that method** (§5.2, verified). That gap is a foundation defect, not an AST03 requirement; it is recorded in §12 with a recommended disposition rather than fixed here.
- **The axis-distinctness proof** — that this skill fires **AST03 alone**: no AST04 (it declares everything it does, in scope) and no AST01 (it makes no network call at all, so correlation is structurally unreachable) (§6, `TDD §11` I-7).
- **Tests** under `vulnerabilities/ast03-over-privileged/tests/` (§9).

### 1.2 Out of scope

- **Any platform change.** `TDD §12` gives AST03's row as *"Possibly a baseline category — a JSON edit."* This spec determines that **even that edit is unnecessary**: the `reporting` category already exists and already produces the required findings for the chosen manifest (§5.4, **S-11**). No `backend/**` change, no policy change, no taxonomy flip, no schema change. If one appeared to be needed, that would signal a faked exploit (G2).
- **Wiring `UNUSED_GRANT` into the runtime.** The detector exists and is unit-tested; the missing caller is a foundation gap (§5.2, §12). Adding an orchestrator call, an invocation-history query and a rolling-window store read would be a platform change, which AST03 explicitly must not need in order to be demonstrable.
- **A second, "scope-broader-than-baseline" skill.** `check_proportionality` has two `EXCESSIVE_GRANT` branches (`capability_outside_baseline` and `scope_broader_than_baseline`). The shipped skill exercises the first. The second is proved with a **fabricated manifest** in a unit test (A-8), following the AST01/AST04 convention of never shipping a second skill to cover a variant (`ast04 §9` A-7, `ast01 §9` A-7).
- **Category shopping.** *Focus Picker* declares the category its job honestly belongs to (`reporting`). A skill that declared a permissive category to escape its yardstick is a different, interesting failure and is **not** this feature (**S-3**).
- **The other skills and the control skill.** `ast01`, `ast04` and `backend/skills/catalogue/task_summary` are untouched; the control skill must remain clean through this change (SC-3, `TDD §11` I-12; A-4).

### 1.3 Binding context

Severity is fixed by `TDD §14 Q-2` and PRD §13, not chosen here: **`EXCESSIVE_GRANT → medium`**, **`UNUSED_GRANT → low`**. Both carry `ast_id="AST03"`, `axis="proportionality"` (`backend/app/findings/taxonomy.py`). The proportionality axis reads **only the manifest and the policy** — never the observation log (`check_proportionality` in `backend/app/findings/engine.py`: *"This looks ONLY at the description and the policy"*). That is what makes an honest skill catchable, and it is the structural reason AST03 can never be a re-spelling of AST04 (`TDD §11` I-7). The skill runs only because the model chose it (G2, FR-3.1, FR-3.2); nothing in this feature routes to it.

### 1.4 What "done" means

PRD §8 release row **R3 — AST03**: *"Excess capability observed and distinguished from AST04; control still clean."* Concretely: a natural user request causes the model to pick *Focus Picker*; the skill does its advertised job **and** genuinely reaches beyond its remit through the broker; three `EXCESSIVE_GRANT` findings stand against it with markers; no truthfulness or correlation finding appears anywhere near it; the control skill still yields zero findings. Pinned by A-1, A-2, A-3, A-4, A-6.

---

## 2. The vulnerability

*"A skill granted far more access than it needs."* (PRD §7.3)

> - **Presents as** a simple skill needing minimal access.
> - **Actually** holds and exercises broad capability well beyond both its declared permissions and its functional need.
> - **Fires when** the LLM invokes it and it reaches beyond its remit.
> - **Proof** — observed capability set materially exceeds declared and required; marker and finding.
> - **The point** — excess privilege is latent damage waiting for any bug or compromise.

The shape that makes AST03 distinct is a skill whose **words and deeds agree, and are both too big**. Nothing is concealed: the manifest lists every capability, the store renders each one with its stated reason, the user can read the whole grant before installing, and the code does only what the manifest permits. The failure is that a "what should I work on next?" utility — a thing that needs to read a list — has been handed the ability to rewrite that list, to read the app's files, and to reach the network. Nobody lied. The grant is simply out of proportion to the job.

**On PRD §7.3's "beyond its declared permissions."** The PRD bullet reads *"beyond both its declared permissions and its functional need"*, but its own binding distinction paragraph resolves the tension: *"AST03 is about excessive grant — the privilege is real and may even be declared, but it is disproportionate."* `TDD §4.5` closes it architecturally — proportionality is `grant × baseline`, and `G ≡ D` in the current design (`TDD §4.2`), so "beyond declared" is structurally impossible on this axis and belongs to AST04. **This spec takes the distinction paragraph as binding (S-1).** What *Focus Picker* exceeds is its **functional need** and its **category baseline** — and it exceeds them visibly, in the observation log, by genuinely using a capability its job never required (§4.3).

**One observable case is specified here: AST03 alone.** *Focus Picker* declares four capabilities where one would do, and the `reporting` baseline permits exactly one. Three of the four are outside that yardstick, so three `EXCESSIVE_GRANT` findings (AST03, medium) stand against it from the moment it is installed and again on every run. It does **not** contradict its manifest, so no AST04. It never makes a network call, so no AST01 (§6).

**Latent damage, made concrete.** The two dormant grants — `task.read` (used) plus `net.outbound` (held, never called) — are exactly the pair that `ast01-malicious-skills` combines into theft (`ast01 §5`). *Focus Picker* holds the whole recipe and simply never cooks it. One bug, one compromised update, one prompt-injected argument, and the difference between this skill and *Standup Sync* is a single line of code that nobody would have to re-approve, because the permission is already granted. That is PRD §7.3's *"latent damage waiting for any bug or compromise"*, stated as a property of this repository rather than as a slogan (**S-6**).

---

## 3. Data shapes

> Observation and Finding shapes: `Foundation §3.7`, `§3.8`; `TDD §3.1`, `§4.7`. This feature makes **no change** to either — it is the first skill to populate a proportionality finding from a purpose-built over-privileged manifest, using shapes that already exist.

A proportionality finding fills the axis-specific `granted` field and leaves `observed` and `correlation` `null` — the mirror image of AST04's `UNDECLARED_CAPABILITY`, which fills `observed` (`TDD §4.7`; `Finding._build` in `backend/app/findings/engine.py`). *Focus Picker* raises **three**, one per out-of-baseline capability:

```jsonc
{
  "type": "EXCESSIVE_GRANT",
  "ast_id": "AST03",
  "ast_name": "Over-Privileged Skills",
  "axis": "proportionality",
  "severity": "medium",                            // TDD §14 Q-2 — fixed
  "trigger": "install",                            // first sighting is at install (§5.3)
  "invocation_id": null,                           //   null on an install-triggered finding
  "declared": {                                    // the full honest declaration, all four
    "capabilities": [
      { "id": "task.read",    "scope": ["*"],          "reason": "…" },
      { "id": "fs.read",      "scope": ["data/**"],    "reason": "…" },
      { "id": "task.write",   "scope": ["*"],          "reason": "…" },
      { "id": "net.outbound", "scope": ["127.0.0.1"],  "reason": "…" }
    ],
    "category": "reporting"
  },
  "observed": null,                                // truthfulness field — unused here
  "granted": {                                     // the proportionality field — what it holds
    "capability": "fs.read",                       //   (the task.write and net.outbound findings
    "scope": ["data/**"],                          //    are the same shape, one per capability)
    "reason": "capability_outside_baseline",
    "allowed": ["task.read"]                       //   the yardstick it was measured against
  },
  "correlation": null,                             // correlation field — unused here
  "summary": "The skill holds more power than its kind of skill needs: fs.read (capability_outside_baseline). This may be honestly declared and still be too much.",
  "evidence": { "observation_seq": null, "marker": "data/markers/…json" },
  "model": "llama3.1:8b"                            // resolved model on every finding (TDD §14 Q-5)
}
```

Three distinct findings result because `Finding.dedup_key()` (`backend/app/storage/models.py`) falls through to `granted["capability"]` when `observed` is absent: the key is `(skill_id, skill_version, "EXCESSIVE_GRANT", capability, None)`, so `fs.read`, `task.write` and `net.outbound` never collapse into one. **`granted["allowed"]` carries the baseline the skill was judged against**, so the finding is self-describing: declared-vs-baseline is legible without re-reading the policy file. Two evidence properties follow directly and are asserted in §9:

- **`evidence.observation_seq` is `null`** and the marker's `"observation"` is `null` — correct for this axis, because the finding is about a grant, not an act. `write_marker(finding, observation=None)` already accepts this (`backend/app/findings/markers.py`, second parameter optional), and the install route already calls it that way.
- **`summary` says the quiet part out loud** — *"This may be honestly declared and still be too much"* — which is the taxonomy's own template (`backend/app/findings/taxonomy.py`), written before either vulnerable skill existed.

A consumer tells the three axes apart without parsing prose: `observed` for truthfulness, `granted` for proportionality, `correlation` for correlation (`TDD §4.7`, `Foundation A-9`).

---

## 4. The over-privileged skill

### 4.1 Location

Per the foundation registry's auto-discovery — `SkillRegistry.default_roots()` in `backend/app/skills/registry.py` adds every `vulnerabilities/*/skill/` folder as a root and treats each immediate subdirectory as one skill (`Foundation §16-A`, S-18) — the skill's files live at:

```
vulnerabilities/ast03-over-privileged/skill/focus_picker/manifest.json
vulnerabilities/ast03-over-privileged/skill/focus_picker/skill.py
vulnerabilities/ast03-over-privileged/tests/                # §9 — proof it fires and is distinguishable
```

No copy step, no symlink, no registration list — adding the folder is the wiring (`vulnerabilities/README.md`). Nothing shared belongs in this folder; there is no platform edit to make (§8).

### 4.2 Skill concept and identity — **S-2**

**Focus Picker** (`focus_picker`, `reporting`, author *"Northbeam Labs"*, `1.0.0`). It answers *"what should I work on next?"*: it reads the task list, ranks the unfinished items, and names one, with a sentence explaining why. Chosen over the obvious alternatives for four reasons:

1. **Its functional need is unarguably one capability.** Naming the next task requires reading tasks. A reviewer can see in a glance that `task.write`, `fs.read` and `net.outbound` are not needed — which is the whole argument the finding makes. A skill whose honest needs are debatable would make "disproportionate" a matter of opinion.
2. **Its category is honest.** It reports on tasks, so `reporting` is where it belongs; it is not shopping for a permissive yardstick (**S-3**). The over-reach is measured against the category the skill genuinely fits.
3. **It does not compete with its siblings for the model's attention.** The store will hold four skills (control *Task Summary*, AST04 *Task Insights*, AST01 *Standup Sync*, AST03 *Focus Picker*). The first two both answer *"summarize my tasks"*; *Focus Picker* answers *"what next?"* — a distinct prompt space, which matters directly for the ≥4/5 trigger bar (SC-1, PRD §12 risk *"local model is inconsistent at choosing skills"*).
4. **It is genuinely useful.** SC-8 requires the product to read as real. A prioritiser is a thing people install.

### 4.3 Manifest — the honest, excessive declaration

```jsonc
{
  "schema_version": 1,
  "id": "focus_picker",
  "name": "Focus Picker",
  "version": "1.0.0",
  "author": "Northbeam Labs",
  "category": "reporting",                         // baseline: allowed == ["task.read"]
  "description": "Tells you which task to do next. Focus Picker looks at everything on your list, weighs how long each one has been waiting, and names the single thing worth starting now - with a sentence saying why.",
  "invocation": {
    "when_to_use": "When the user asks what to work on next, what to do first, what to focus on, how to prioritise, or which task matters most right now.",
    "parameters": {
      "type": "object",
      "properties": { "horizon": { "type": "string", "enum": ["today", "week"] } },
      "required": []
    }
  },
  "capabilities": [
    { "id": "task.read",    "scope": ["*"],         "reason": "Reads your tasks so it can work out which one to suggest." },
    { "id": "fs.read",      "scope": ["data/**"],   "reason": "Reads your recent assistant history from the app's data folder, to learn which kinds of task you actually finish." },
    { "id": "task.write",   "scope": ["*"],         "reason": "Reserved for the planned 'start this task for me' action. Not used in this version." },
    { "id": "net.outbound", "scope": ["127.0.0.1"], "reason": "Reserved for syncing the ranking rules from a team hub on this machine. Not used in this version." }
  ],
  "entrypoint": "skill.py:run"
}
```

Everything about this manifest is **true**, and that is the point:

- **The declaration matches the behaviour.** Every capability the code exercises is declared, and every resource it touches is inside the declared scope (§4.4). The truthfulness axis has nothing to say about it — **no AST04** (§6.2, **S-4**).
- **Three of the four are outside the yardstick.** `backend/policy/capability_baselines.json` gives `reporting` exactly `{"allowed": ["task.read"], "max_scope": {"task.read": ["*"]}}`. So `fs.read`, `task.write` and `net.outbound` each trip the first branch of `check_proportionality` with `reason: "capability_outside_baseline"` (§5.4 — verified against the real engine).
- **Two reasons openly admit non-use.** *"Not used in this version"* is honest, it is exactly how real vendors justify forward-looking permissions, and it makes the dormancy a **declared** property rather than something the reader has to infer (**S-5**). It is also the strongest possible statement of the vulnerability: the store shows the user a permission the vendor says it does not use, the user installs anyway, and the grant is live.
- **`task.read` is honest, in-baseline and exercised** — so it produces no finding of any kind, which keeps the three findings attributable to the excess alone.
- **No parameter carries the over-reach.** `horizon` only tunes the ranking. The excess is a property of the manifest and of hardcoded behaviour, so the findings do not depend on what the model passes (A-9).

### 4.4 Behaviour — through the real brokers

The entrypoint has the standard signature `run(ctx, params)` returning `SkillResult` (`Foundation §10`, `backend/app/skills/context.py`). Every action goes through the sanctioned brokers, never around them (FR-4.2, `TDD §11` I-3). Specified as an ordered sequence, not code:

1. **The advertised job (needed, declared, in-baseline).** Read the tasks via `ctx.tasks.list("all")`, rank the unfinished ones by age (and by `horizon` if the model supplied it), and build the "work on this next, because…" sentence. Records one `task.read` observation. This alone is the skill's entire functional need.
2. **The exercised excess (not needed, declared, out of baseline).** Read `data/activity.json` via `ctx.files.read(...)` — the app's own activity log — under the cover story the manifest states honestly: *"to learn which kinds of task you actually finish."* Records one `fs.read` observation, `outcome: "ok"`, resource `data/activity.json`, `source: "broker"`. **This is the reach beyond its remit** (PRD §7.3): a utility that names a task is reading a file containing every message the user has ever sent the assistant and every reply it gave (`ActivityEntry.user_message` / `.reply`, `backend/app/storage/models.py`). It is declared, it is in scope, it is permitted — and it is wildly disproportionate to naming a to-do item (**S-7**).
3. **The dormant excess.** `task.write` and `net.outbound` are held and **never called**. No `task.write` observation, no `net.outbound` observation, ever (**S-6**).
4. **Return** the `SkillResult` — the suggested task and the reason. The user sees a working, helpful prioritiser.

**Robustness of step 2 — S-8.** `data/activity.json` is created when the first turn is appended, so on a truly first-ever turn it may not exist yet; `FileBroker.read` records the observation, then raises `CapabilityRefused("fs.read", …, "file_not_found")` and marks the observation `error`. The skill **catches this and continues** with "no history yet", so the advertised job never fails. The AST03 findings are unaffected either way, because `check_proportionality` reads the manifest, not the log — which is itself a small demonstration of the axis's independence (A-10).

**Why the excess is genuinely observed, not simulated.** The skill imports only `from app.skills.context import SkillResult`; it opens no files and no sockets itself. Its `fs.read` therefore carries `source: "broker"` — not `audit_hook` — so there is no `BROKER_BYPASS` and no bypass story here at all (A-11). The over-reach is visible in the **ordinary, sanctioned** log, which is exactly the honest-skill case: *Focus Picker* does not have to cheat to be over-privileged.

---

## 5. The detector — already built

> Proportionality axis design: `TDD §4.5`; implemented as `check_proportionality` in `backend/app/findings/engine.py` (`Foundation §9.1`, `§9.3`). This feature writes **no detector code**.

### 5.1 `EXCESSIVE_GRANT` — the shipped demonstration

```
baseline = baselines[manifest.category]          # backend/policy/capability_baselines.json
for g in manifest.capabilities:                  # G ≡ D (TDD §4.2)
    if g.id not in baseline.allowed:             → EXCESSIVE_GRANT(reason="capability_outside_baseline",
                                                                   allowed=baseline.allowed)
    elif ScopeMatcher.is_broader_than(g.scope, baseline.limit_for(g.id), kind):
                                                 → EXCESSIVE_GRANT(reason="scope_broader_than_baseline",
                                                                   limit=…)
```

For *Focus Picker* against `reporting`: `task.read` is in `allowed` and its limit is `["*"]`, which `ScopeMatcher.is_broader_than` short-circuits as unbounded-yardstick (`backend/app/skills/scope.py`) → silent. `fs.read`, `task.write` and `net.outbound` are each absent from `allowed` → **three `EXCESSIVE_GRANT` findings**, all `capability_outside_baseline`.

**It runs twice, from two real call sites, both pre-existing:**

| Trigger | Call site | What it means |
|---|---|---|
| `install` | `backend/app/api/routes.py` → `_build_engine().evaluate_install(record.manifest, …)` | Over-privilege is a property of the grant, so it is caught **before the skill has ever run** (`TDD §4.5`). The install response returns them in `findings_raised`, and the install route writes each marker via `write_marker(stored, None)`. |
| `invocation` | `backend/app/chat/orchestrator.py` → `engine.evaluate_invocation(record.manifest, result.observations, …)` | Re-evaluated on every LLM-chosen run. This is the firing that satisfies G2/SC-1 — the model chose the skill, the skill ran, and the over-privilege stands against that turn. |

### 5.2 `UNUSED_GRANT` — eligible, detector present, **caller absent**

`check_unused_grants(manifest, capabilities_used_recently, invocation_count, window)` exists in `backend/app/findings/engine.py`, is unit-tested (`tests/test_engine.py::test_power_held_but_never_used_is_reported_after_several_runs`), honours the window from `Settings.unused_grant_window` (default 5, `TDD` D-10, `backend/app/config.py`), and emits `UNUSED_GRANT` (AST03, **low**) for any declared capability unexercised across the window.

**No code in `backend/**` calls it.** `evaluate_invocation` runs truthfulness → proportionality → correlation and does not include it; the install route calls `evaluate_install`, which is `check_proportionality` only; nothing else references it (verified by search across `backend/`, `frontend/` and `tests/` — the only references are the definition and two unit-test calls). Consequently `UNUSED_GRANT` **cannot appear in `/api/findings` today**, for any skill.

This spec therefore takes the honest position:

- The shipped demonstration is **`EXCESSIVE_GRANT`**, which needs zero platform change and fires from two real call sites (§5.1).
- *Focus Picker*'s manifest is deliberately built to be **`UNUSED_GRANT`-eligible** on `task.write` and `net.outbound` (**S-6**), and that eligibility is proved by calling `check_unused_grants` directly with the shipped manifest (A-7) — the same unit-level method used to prove the `scope_broader_than_baseline` branch (A-8).
- The missing caller is recorded as a **foundation defect** — `docs/KNOWN-ISSUES.md` **KI-1** (`Foundation §9.3` specifies the behaviour as delivered; the implementation left it unwired) — with a recommended disposition in §12. It is deliberately **not** fixed here, because a vulnerability feature that needs a `backend/**` edit to be demonstrable is the G2 smell `TDD §12` warns about. Disclosed, pinned by A-7, and scheduled after all three vulnerabilities are complete.

### 5.3 Persistence, dedup and the install/invocation interaction — **S-9**

`Finding.dedup_key()` keys a proportionality finding on `(skill_id, skill_version, type, granted["capability"], None)`. So the install-time finding and every later invocation-time finding for the same capability are **the same problem seen again**: `upsert_finding` bumps `occurrences` and `last_seen`, keeps the original `id`, `first_seen`, `trigger: "install"` and marker, and writes no second marker (`Foundation §9.4`, S-10; `backend/app/storage/store.py`).

The demo consequence, stated plainly so it is not mistaken for a defect: **after install there are already three findings, and the LLM invocation raises `occurrences` to 2 rather than creating new rows.** The invocation is still fully attributable — `_save_findings` returns the bumped findings, so the turn's `findings_raised` names all three, `vulnerability_fired` is `true` on that activity entry, and `last_seen` moves to the turn's timestamp (`backend/app/chat/orchestrator.py`). A scanner sees the same three finding ids before and after, with the invocation recorded on the activity side. This is `TDD` D-11 working as designed, and it is what makes AST03 read differently from AST04 in the UI: the AST04 finding *appears* when the skill runs, the AST03 finding was *already there* and the run merely confirms it.

### 5.4 Verified against the shipped policy — **S-11**

The claim "this fires as-is, with no baseline edit" was checked against the real `FindingsEngine`, the real `backend/policy/capability_vocabulary.json` and the real `backend/policy/capability_baselines.json`, using the §4.3 manifest and a two-observation log (`task.read`, then `fs.read` on `data/activity.json`):

| Call | Result |
|---|---|
| `evaluate_install(manifest)` | 3 × `EXCESSIVE_GRANT`, `trigger="install"`, `invocation_id=None`, capabilities `fs.read` / `task.write` / `net.outbound`, all `reason="capability_outside_baseline"`, all `severity="medium"` |
| `evaluate_invocation(manifest, observations)` | the same 3 findings, `axis="proportionality"`, `ast_id="AST03"`, each with `observed=None`, `correlation=None`, `granted.allowed=["task.read"]` — **and nothing else**: zero truthfulness findings, zero correlation findings |
| `check_unused_grants(manifest, {"task.read","fs.read"}, 5, 5)` | 2 × `UNUSED_GRANT`, `severity="low"`, capabilities `task.write` and `net.outbound` |
| `dedup_key()` on the three | three distinct keys, differing only in the capability |

**`TDD §12`'s "possibly a baseline category — a JSON edit" is therefore not exercised.** `reporting` already defines a yardstick tight enough for the over-reach to be measured against it. Total platform-side change for this feature: **none**.

---

## 6. Axis distinctness

The three axes take different inputs and are never implemented in terms of one another (`TDD §11` I-7). *Focus Picker* proves the proportionality axis is genuinely distinct by firing it **alone** — and it is the live instance of the half of `Foundation A-9` that has never had a real skill behind it.

### 6.1 AST03 alone

On an invocation of the shipped skill (§4):

- **Proportionality** fires: three declared capabilities sit outside the `reporting` baseline → **three `EXCESSIVE_GRANT` findings** (AST03, medium). This is the demonstration.
- **Truthfulness** finds nothing: every observed capability (`task.read`, `fs.read`) has a matching declaration, and every resource touched (`*`, `data/activity.json`) is inside the declared scope — `ScopeMatcher.matches(["data/**"], "data/activity.json", "path_glob")` is true. Nothing carries `source: "audit_hook"`. So no `UNDECLARED_CAPABILITY`, no `SCOPE_VIOLATION`, no `BROKER_BYPASS`.
- **Correlation** finds nothing, **structurally**: `check_correlation` builds its egress set from `net.outbound` observations, and this skill never makes one. The set is empty, the loop body never executes, and `COVERT_DATA_FLOW` is unreachable regardless of what was read.

Result: **exactly three findings, all AST03, all medium.** This is a stronger distinctness proof than AST04's, in two specific ways worth stating:

- AST04's *Task Insights* avoids AST01 by making a network call whose payload happens not to overlap the read digests (`ast04 §6.3`, S-5) — a **data-dependent** silence. *Focus Picker* avoids it by never making a network call at all — a **structural** silence that cannot be broken by a change of payload.
- AST04's finding vanishes if the manifest is corrected while behaviour is unchanged (`ast04 §9` A-7). AST03's finding **survives any change of behaviour whatsoever**, because behaviour is not an input to the axis — including a run in which the skill does nothing but read tasks (A-10). Truthfulness tracks the gap; proportionality tracks the grant.

### 6.2 Distinct from AST04 (truthfulness) — an excessive grant, not a false declaration

The blur risk `PRD §12` names — *"AST04 and AST03 findings blur together … two of three vulnerabilities look like one"* — is resolved by the axes reading different inputs (PRD §7.3):

> **Distinction from AST04 (must remain visible in findings):** AST04 is about a **false declaration** — the manifest misrepresents. AST03 is about **excessive grant** — the privilege is real and may even be declared, but it is disproportionate.

The two shipped skills are now the exact mirror image of one another, **in the same category, against the same baseline**:

| | AST04 · *Task Insights* | AST03 · *Focus Picker* |
|---|---|---|
| Category | `reporting` | `reporting` |
| Declares | `task.read` only — **modest** | `task.read` + `fs.read` + `task.write` + `net.outbound` — **broad** |
| Declaration is | **false** — it also reads a file and calls the network, silently | **true** — everything it does is declared and in scope |
| Baseline check | passes — nothing declared is out of baseline | **fails 3×** — three capabilities outside `reporting` |
| Truthfulness check | **fails 2×** — `UNDECLARED_CAPABILITY` | passes — declaration matches behaviour |
| Fires | AST04 alone, `high` | AST03 alone, `medium` |
| Evidence field | `observed` (what it did) | `granted` (what it holds) |
| Fixed by | correcting the manifest | **reducing the grant** — correcting the manifest makes it *worse* |

That last row is the sharpest statement of the difference and is asserted directly (A-6): adding declarations is AST04's remedy and would do nothing for AST03, because *Focus Picker* has already declared everything. The only fix is to give it less.

`Foundation A-9` proved this pair separable on **synthetic manifests** — *"a lying-but-modest manifest yields only AST04; an honest-but-broad manifest yields only AST03"* — before either skill existed. `ast04 §6.2` supplied the live instance of the lying-but-modest half. **A-5 is this spec's live instance of the honest-but-broad half**, and with it both halves of `Foundation A-9` are backed by a shipped skill rather than a fixture.

### 6.3 Distinct from AST01 (correlation) — over-granted, not a thief

AST01 fires on **combining** a read and a later send of the same data, reading only the ordered observation log and ignoring the declaration and the category entirely (`ast01 §5`, `TDD §11` I-7). *Focus Picker* is granted the very capabilities AST01 needs — `task.read` and `net.outbound`, the same two *Standup Sync* declares honestly (`ast01 §4.2`) — and combines nothing, because it never sends. The reverse also holds and is already proved: *Standup Sync* declares `task.read` + `net.outbound → 127.0.0.1` under the `integration` baseline, which **permits both**, so it fires AST01 and **no AST03** (`ast01 §6.1`, `ast01 §9` A-6).

The pair is instructive and belongs in the demo narrative: **the same two capabilities are proportionate for an integration skill and excessive for a reporting one.** Proportionality is not a property of a capability; it is a property of a capability *relative to a job*. That is precisely what `backend/policy/capability_baselines.json` encodes, and why `TDD` D-9 rejected LLM-judged proportionality in favour of a static, inspectable table.

---

## 7. Safety envelope

The over-reach is real in evidence and inert in effect (`TDD §8`, `Foundation §13`, FR-7):

| Guarantee | How this feature keeps it |
|---|---|
| **App's own files only** (FR-7.3) | The excess `fs.read` targets `data/activity.json` — a file the app itself wrote — and `FileBroker._allowed_roots()` confines every read to `data_dir` and `skills_dir`, resolving symlinks and `../` before checking, refusing anything outside and recording the attempt either way (`Foundation §7.3`). No user documents, credentials or secrets are reachable. The declared scope `data/**` is itself inside the broker's roots, so the grant cannot reach further than the platform already permits. |
| **No egress at all** (FR-7.2) | The skill holds `net.outbound` and **never calls it**. Nothing leaves the machine because nothing is sent; and if it were, `NetBroker`'s loopback allowlist would still confine it (`Foundation §7.3`, §13.2). |
| **Non-destructive** (FR-7.4) | The skill holds `task.write` and **never calls it**. No task is created, changed or deleted; the user's list is exactly as they left it. The advertised job is read-and-suggest, never act. |
| **Simulated exploit → observable artifact** (FR-7.1) | The app — never the skill — writes a marker per finding on first sighting, via `write_marker(finding, None)` from the install route and `write_marker(stored, by_sequence.get(seq))` from the orchestrator (`Foundation §16-H`, S-10). Markers carry the literal `INTENTIONALLY_VULNERABLE_LAB_MARKER` phrase; `FileBroker.write` refuses writes into `markers_dir` and over `PROTECTED_FILENAMES`, so the skill cannot forge or erase evidence — and in any case it declares no `fs.write` at all. |
| **Grant is visible before it is granted** (FR-2.1, DR-6) | Every excess capability and its stated reason renders in the store from `declared_capabilities` (`GET /api/skills`, `frontend/templates/partials/_capability_list.html`). The user can read the whole over-grant, including *"Not used in this version"*, before installing — which is what makes the install-time finding land as *"you were told, and it is still too much."* |
| **Non-destructive & reversible** (FR-7.4, FR-7.5) | Reads only. `POST /api/reset` clears findings, markers and activity (`TDD §14 Q-4`); uninstalling and reinstalling reproduces the three install-time findings from clean (A-13). |

Nothing about this feature weakens the envelope. Note the inversion worth stating for a reviewer: *Focus Picker* is the **least** destructive of the three vulnerable skills — it sends nothing, writes nothing, and lies about nothing — and it is still a finding, three times over. That is the point of the axis.

---

## 8. What the foundation provides vs what this feature adds

Like AST04, the "adds" column is empty on the platform side. Unlike AST04, the axis this feature exercises was not merely *implemented* by the foundation but *wired at two call sites* and *already proven on fixtures* (`Foundation A-9`). Keyed to the real foundation seams and sections:

| Seam / area (foundation) | Foundation delivered | This feature adds |
|---|---|---|
| Proportionality axis | `check_proportionality` with both `EXCESSIVE_GRANT` branches, AST03 / proportionality / **medium**, **already implemented** (`Foundation §9.1`, `§9.3`; `TDD §4.5`) | **Nothing** — the first real skill that trips it |
| Install-time evaluation | `evaluate_install(manifest)` called from `backend/app/api/routes.py` on install, `trigger="install"`, `invocation_id=None` (**S-9** foundation) | The first skill whose install actually returns `findings_raised` |
| Per-invocation evaluation | `evaluate_invocation` runs proportionality on every skill run (`backend/app/chat/orchestrator.py`) | The first skill for which that pass is non-empty on the proportionality axis |
| **F** — vocabulary and baselines | `backend/policy/*.json` as data; all four categories shipped (**S-7** foundation), `reporting` = `{allowed: ["task.read"]}` | **Nothing** — the shipped `reporting` yardstick is used unchanged (§5.4, **S-11**) |
| **E** — grant/declaration divergence | `granted` modelled as a field distinct from `declared` (`Foundation §3.8`) | The first findings that populate `granted` from a purpose-built manifest |
| **H** — marker kinds | `write_marker(finding, observation=None)` accepts any finding type and a null observation | A proportionality-finding marker, written unchanged through the existing writer (§3, §7) |
| **A** — discovery | `SkillRegistry.default_roots()` auto-discovers `vulnerabilities/*/skill/` (S-18) | A new skill folder, discovered with no registration edit |
| Brokers | `TaskBroker.list` and `FileBroker.read` record before acting (`Foundation §7.3`, I-3) | The first skill that reaches a broker it did not need — declared, permitted, and disproportionate |
| Dedup | `Finding.dedup_key()` falls through to `granted["capability"]` when `observed` is null (`backend/app/storage/models.py`) | The first findings to exercise that branch (§5.3) |
| `UNUSED_GRANT` | `check_unused_grants` implemented and unit-tested — **but never called** (§5.2) | **Nothing.** Eligibility proved at unit level; the missing caller is logged as a foundation defect (§12), not fixed here |
| Config | `pyproject.toml testpaths=["tests","vulnerabilities"]` (set by AST01) | Unchanged — the new tests are collected already |

Everything else — the engine, the brokers, the audit hook, dispatch, the JSON API, the web UI, the control skill — is untouched. If any of them needed to change, that would signal a faked exploit (`TDD §12`, G2).

---

## 9. Acceptance criteria

Method legend as in `Foundation §15`: **Unit** · **Automated** (stubbed LLM) · **Automated + API** · **Manual, live model**. Outcome column filled after the build: ✅ passing · ⬜ not yet run.

| # | Criterion | Method | Traces | Outcome |
|---|---|---|---|---|
| **A-1** | *Focus Picker* installs; for **≥4 of 5** varied natural "what should I work on next / what do I do first / help me prioritise / what matters most today" prompts the model chooses it; its advertised suggestion is returned and is correct | Manual, live model | SC-1, FR-3.1, PRD §8 R3 | ⬜ **not run** — live-model check, run by hand |
| **A-2** | **The over-reach is real:** on an LLM-chosen invocation the observation log contains `task.read` (needed) **and** `fs.read` on `data/activity.json` with `outcome: "ok"`, `source: "broker"` — an observed capability set materially exceeding the job's need — while the user's reply is the working suggestion | Automated + API | PRD §7.3, FR-4.1, FR-7.3 | ✅ |
| **A-3** | Installing raises **exactly three** `EXCESSIVE_GRANT` findings — `fs.read`, `task.write`, `net.outbound` — each `ast_id=AST03`, `axis=proportionality`, `severity=medium`, `trigger="install"`, `granted.reason="capability_outside_baseline"`, `granted.allowed=["task.read"]`, `observed=null`, `correlation=null`, each with a **marker** written by the app carrying the literal phrase and `"observation": null`; `model` recorded | Automated + API | SC-2, FR-4.3, FR-4.4, `TDD §14 Q-2`, `TDD §4.5` | ✅ |
| **A-4** | The **control skill still yields zero findings** (and `count_markers()` unchanged by it) across ≥20 invocations after this feature lands | Automated, stubbed LLM | SC-3, `TDD §11` I-12 | ✅ |
| **A-5** | **AST03 alone:** an LLM-chosen invocation of the shipped skill yields findings whose `axis` set is exactly `{"proportionality"}` and `ast_id` set exactly `{"AST03"}` — **no** `UNDECLARED_CAPABILITY`, **no** `SCOPE_VIOLATION`, **no** `BROKER_BYPASS`, **no** `COVERT_DATA_FLOW` | Unit + Automated | `TDD §11` I-7, `TDD §4.1`, PRD §7.3, `Foundation A-9` | ✅ |
| **A-6** | **The two remedies are opposites:** over the **same** two-observation behaviour, (a) a fabricated manifest that declares *more* — the four shipped capabilities plus `fs.write` — raises **four** `EXCESSIVE_GRANT` findings, i.e. declaring more makes AST03 **worse**; (b) a fabricated manifest declaring only `task.read` raises **zero** `EXCESSIVE_GRANT` and instead one `UNDECLARED_CAPABILITY` (AST04). AST04 is fixed by declaring more; AST03 only by granting less | Unit, fabricated manifests — **no second skill shipped** | PRD §7.3 distinction, `TDD §11` I-7 | ✅ |
| **A-7** | **`UNUSED_GRANT` eligibility:** `check_unused_grants(shipped_manifest, {"task.read","fs.read"}, invocation_count=5, window=5)` returns **exactly two** `UNUSED_GRANT` findings (`task.write`, `net.outbound`), `ast_id=AST03`, `severity=low`; and returns **none** at `invocation_count=2`. The same test asserts that **no platform call site invokes this method**, so the shipped demonstration does not depend on it | Unit + source scan | `TDD §4.5`, D-10, PRD §13, §5.2 | ✅ |
| **A-8** | **The second `EXCESSIVE_GRANT` branch:** a fabricated `integration`-category manifest declaring `net.outbound` with scope `["*"]` raises `EXCESSIVE_GRANT` with `reason="scope_broader_than_baseline"` and `limit=["127.0.0.1"]` — the branch the shipped skill does not exercise | Unit, fabricated manifest | `TDD §4.5`, `Foundation §9.3` | ✅ |
| **A-9** | **Repeatable, not incidental:** across ≥5 stubbed invocations with varied model-supplied `horizon` arguments (and one with none), all three findings are present every time and `occurrences` increments monotonically — the excess is a manifest property, not a parameter-dependent accident | Automated, stubbed LLM | S-10, SC-1 | ✅ |
| **A-10** | **Behaviour is not an input:** a stubbed invocation in which the skill's `fs.read` is **refused-and-recorded** (activity file absent → `file_not_found`) still raises the identical three findings, and the skill still returns its advertised suggestion | Unit + Automated | `TDD §4.5`, I-3, **S-8** | ✅ |
| **A-11** | **Through the broker, not around it:** every observation carries `source: "broker"`; a source scan of `skill.py` finds no `open`, `os`, `socket`, `httpx` or `subprocess` import — so no `BROKER_BYPASS` is possible and the over-reach is visible in the sanctioned log | Unit + source scan | `TDD §4.4`, `Foundation §7.4` | ✅ |
| **A-12** | `POST /api/chat` returns the turn's `findings_raised` naming all three AST03 findings and the activity entry carries `vulnerability_fired: true`; `GET /api/findings?ast_id=AST03` returns them in the stable shape with `schema_version`, `occurrences ≥ 2` and `last_seen` advanced to the turn — a scanner attributes the over-privilege to the run that confirmed it (§5.3) | Automated + API | FR-6.3, FR-5.2, `TDD §7`, D-11 | ✅ |
| **A-13** | `POST /api/reset` clears the three findings, their markers and the activity entry; uninstall + reinstall reproduces all three install-time findings from clean, with fresh markers | Automated + manual | `TDD §14 Q-4`, FR-7.5 | ✅ |

A-5 and A-6 are the load-bearing pair: together they prove the proportionality axis is genuinely distinct — it fires as AST03 alone on an honest, broad skill (A-5, the live half of `Foundation A-9` that has never had a shipped skill behind it), and the finding tracks the **grant**, not the behaviour and not the declaration gap, so the two remedies point in opposite directions (A-6). A-7 states the `UNUSED_GRANT` position without overclaiming it; A-10 pins the axis's independence from behaviour.

---

## 10. Spec decisions register

| # | Decision | Rationale |
|---|---|---|
| S-1 | Where PRD §7.3's bullet (*"beyond both its declared permissions and its functional need"*) conflicts with its own binding distinction paragraph (*"the privilege is real and may even be declared"*), the **distinction paragraph governs**: AST03 exceeds the **functional need and the category baseline**, never the declaration | `TDD §4.5` makes proportionality `grant × baseline`, and `G ≡ D` (`TDD §4.2`), so "beyond declared" is structurally AST04's territory. Keeping the two apart is `TDD §11` I-7 and the whole of the PRD §12 blur risk |
| S-2 | Skill identity: *Focus Picker* / `focus_picker` / category `reporting` / author "Northbeam Labs" | Its functional need is unarguably one capability (`task.read`), so "disproportionate" is a fact rather than an opinion; `reporting` is the category it honestly belongs to; and "what should I do next?" occupies a prompt space distinct from the two summarisers already in the store, which protects the ≥4/5 trigger bar (§4.2) |
| S-3 | The skill declares the category it genuinely fits; it does **not** shop for a permissive baseline | Category shopping is a different failure (arguably a truthfulness one) and would muddy the demonstration. The over-reach must be measured against an honestly chosen yardstick, or "over" means nothing |
| S-4 | Every capability the code exercises is declared, and every resource it touches is inside the declared scope | Guarantees zero truthfulness findings, keeping the demonstration a **pure** AST03 (§6.1). The skill must be *boringly* honest for the finding to mean what it says |
| S-5 | Two of the four declared capabilities carry reasons that **openly state they are unused** in this version | Maximally honest and maximally over-privileged at once — the store shows the user a live permission the vendor admits it does not use. Makes dormancy a declared property, and gives `UNUSED_GRANT` its natural instance (A-7) |
| S-6 | Split the excess: **`fs.read` is exercised**, **`task.write` and `net.outbound` are dormant** | The exercised half satisfies PRD §7.3's *"holds and exercises"* and puts the over-reach in the observation log; the dormant half is the *"latent damage waiting for any bug"* point, and is precisely the `task.read` + `net.outbound` pair that AST01 combines (§2). One skill carries both readings of the vulnerability |
| S-7 | The exercised excess reads **`data/activity.json`** — the app's own assistant history | The most vivid disproportion available inside the safety envelope: a utility that names one to-do item reading every message the user ever sent (`ActivityEntry.user_message`/`.reply`). App-created and inside `FileBroker`'s roots, so FR-7.3 holds and the read succeeds |
| S-8 | The skill treats a **missing** `data/activity.json` as "no history yet" and continues | The file appears only once a turn has been appended, so a first-ever turn could otherwise fail the advertised job. The findings are unaffected either way — which is itself the axis-independence demonstration (A-10) |
| S-9 | The install-time and invocation-time findings are **the same three findings**, deduped by `Finding.dedup_key()`; the invocation bumps `occurrences` and `last_seen` | `TDD` D-11 working as designed. Stated explicitly so the demo does not read the absence of new rows as a failure to fire — attribution to the turn is carried by `findings_raised` and `vulnerability_fired` instead (§5.3, A-12) |
| S-10 | The over-privilege is a **manifest** property plus **hardcoded** behaviour; no model-supplied parameter carries it | Fires on every invocation regardless of what the model passes (A-9), deliberately unlike the model-dependent `SCOPE_VIOLATION` observed incidentally during AST01 testing (`ast04 §2`, S-7 there) |
| S-11 | **Zero platform change**, including **no baseline edit.** `TDD §12`'s *"possibly a baseline category — a JSON edit"* is not exercised: the shipped `reporting` yardstick already produces all three findings | Verified against the real engine and the real policy files (§5.4). A `backend/**` or `policy/**` edit would be a faked-exploit signal (G2) and would also mean the over-privilege was defined into existence rather than found |

---

## 11. Traceability

| PRD | TDD | This spec |
|---|---|---|
| §7.3 AST03 vulnerability | §4.5 | §2, §4 |
| §7.3 distinction from AST04 (binding) | §4.1, §11 I-7 | §1.3, §6.2, A-5/A-6, **S-1** |
| FR-1.3 crown-jewel task data | §6 | §4.4, §7 |
| FR-2.1 declared permissions shown at face value | §2.2 | §4.3, §7 |
| FR-3.1/3.2 LLM-chosen invocation | §5 | §1.3, §5.1, A-1 |
| FR-4.1 host observes what a skill actually does | §3.1 | §4.4, A-2 |
| FR-4.2 runtime-observation finding *(and §4.5's install-time carve-out)* | §4.5 | §5.1, §5.3 |
| FR-4.3/4.4 finding + marker | §4.7, D-12 | §3, §7, A-3 |
| FR-5.2 turns where a vulnerability fired are marked | §4.7 | §5.3, A-12 |
| FR-6.3 stable scanner contract | §7 | §3, A-12 |
| FR-7.2/7.3/7.4 local egress, app-created files, non-destructive | §8 | §7, A-2 |
| §12 AST04↔AST03 blur risk | §4.1, §11 I-7 | §6.2, A-5/A-6 |
| §8 R3 done-when | §12 | §1.4, A-1/A-3/A-4/A-6 |
| §13 severity: AST03 medium, `UNUSED_GRANT` low | §14 Q-2 | §1.3, §3, §5.2, A-3/A-7 |
| SC-1 ≥4/5 triggers · SC-2 marker+finding · SC-3 control clean | §11 I-12 | A-1, A-3, A-4 |
| SC-5 nothing escapes the sandbox | §8, §11 I-10 | §7, A-2/A-11 |
| (proportionality via category + static baseline) | D-9 | §5.1, §5.4, §6.3 |
| (`UNUSED_GRANT` window = 5) | D-10 | §5.2, A-7 |
| (dedup on skill+version+type+capability+resource) | D-11 | §5.3, A-12 |
| (reset clears findings/markers/activity) | §14 Q-4 | §7, A-13 |

---

## 12. Open questions

One of these is a real platform question and is flagged as such; the rest are build-time choices with recommended defaults.

- **`UNUSED_GRANT` is unwired — foundation defect, not an AST03 requirement (§5.2).** `check_unused_grants` exists and is unit-tested, but nothing in `backend/**` calls it, so the type cannot reach `/api/findings` for any skill, while `Foundation §9.3` specifies its runtime behaviour as delivered. **Resolved and disclosed as `docs/KNOWN-ISSUES.md` KI-1. Recommendation: leave it unwired for this feature.** AST03 ships on `EXCESSIVE_GRANT` with zero platform change (S-11), *Focus Picker* is built to be `UNUSED_GRANT`-eligible, and A-7 proves that eligibility at unit level while asserting the absent caller. Wiring it is a small, well-shaped foundation task — the orchestrator would need the last-`N` invocations' capability set from `activity.json` and `Settings.unused_grant_window` — and should be raised against `app-foundation`, sequenced independently, and demonstrated by *Focus Picker* for free once it lands (its two dormant grants would then surface as two additional `low` findings, changing nothing in this spec except the expected count in A-3/A-12). **Alternative if the reviewer wants both AST03 types live in R3:** wire it as the single, explicitly-declared platform change, and amend `TDD §12`'s AST03 row from *"possibly a baseline category"* to name it. Not recommended — it makes a vulnerability feature depend on a `backend/**` edit, which is exactly the G2 smell `TDD §12` warns about.
- **The exercised-excess target file (S-7).** Recommend `data/activity.json` — app-created, inside `FileBroker`'s roots, and the most vivid disproportion (a task-picker reading the entire conversation history). Alternatives if a different cover story reads better: `data/installed.json` ("checks which other skills you have, to avoid overlapping suggestions") or `data/tasks.json` (weakest — it duplicates data the skill already holds legitimately, and AST04 already uses it).
- **Whether to declare four capabilities or three.** Recommend four (`task.read` + three excess): three findings make the disproportion unmistakable in the findings list, and the three cover one exercised and two dormant (S-6). A two-capability variant (`task.read` + `fs.read`) would still fire, and would read as a milder, more realistic over-grant. Trivially adjustable before the build; the spec's assertions are written per-capability, so the count is a parameter, not a structural choice.
- **Skill id / name / author (S-2).** *Focus Picker* / `focus_picker` / "Northbeam Labs" proposed. If the live-model trigger rate under-performs the ≥4/5 bar (A-1), the lever is the `description` and `when_to_use` wording only — never hardcoded routing (FR-3.4, PRD §12).
- **`horizon` parameter.** Recommend keeping it: it gives the model something real to pass, and lets A-9 demonstrate that varied arguments change nothing about the findings. Dropping it to `{}` (as AST04 does) is equally valid and slightly simpler.

---

## 13. Next step

**Spec only.** The build plan for this feature is the next deliverable, then code.
