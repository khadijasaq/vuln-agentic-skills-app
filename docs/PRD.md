# TaskBot — Product Requirements Document

| | |
|---|---|
| **Product** | TaskBot — deliberately-vulnerable agentic-skills target |
| **Layer** | OWASP Agentic Skills (AST) |
| **Version** | PRD v1.0 |
| **Status** | **Approved.** Canonical location: `docs/PRD.md`. |
| **Companion** | `docs/TDD.md` — system-wide technical design. Feature specs live in `docs/features/<feature>/spec.md`. |
| **Repo** | `C:\DEV2\vuln-agentic-skills-app` |

---

## 1. Context

Validating agentic-AI security tooling requires deliberately-vulnerable targets to scan — the agentic-AI equivalents of DVWA and WebGoat, one per OWASP layer. Those targets exist for the layers around this one (an e-commerce app covers Agentic Applications; a complaint chatbot covers LLM), but **no standard target exists for the Agentic Skills layer**. Tooling aimed at that layer currently has nothing to be tested against.

TaskBot fills that gap. It is a small, believable to-do assistant whose extra abilities arrive as installable skills, three of which are intentionally vulnerable in ways drawn from the **OWASP Agentic Skills Top 10 (2026)**. It is built and maintained solo, for lab use only.

The intended outcome: a scanner can be pointed at TaskBot, exploit real vulnerabilities through a real LLM agent, and produce findings a remediation agent can consume — with proof that each exploit genuinely fired, and no risk to any real system.

---

## 2. Product summary

TaskBot is a to-do assistant. Users add and list tasks in normal conversation. Beyond that baseline, capability is modular: users browse a **skill store**, install skills, and the assistant gains new abilities. Each skill is a self-contained module — a **manifest** declaring its identity and permissions, plus its **code**.

An LLM decides everything. It reads the installed skills, decides whether one fits the user's request, and runs it. If nothing fits — or nothing is installed — it answers directly, like any assistant. No routing is hardcoded.

The host watches what each skill *actually does* while it runs and compares that to what the manifest *declared*. Divergence becomes a security finding.

---

## 3. Users

| Persona | What they need from TaskBot | How they interact |
|---|---|---|
| **Red-team / scanning agent** *(primary)* | Discoverable, genuinely exploitable skill-layer vulnerabilities. Needs to enumerate skills, read declared manifests, trigger skills through the assistant, and confirm exploitation. | Chat endpoint + read-only JSON API. May install its own probe skill. |
| **Blue-team / remediation agent** *(primary)* | Structured, machine-readable findings with enough evidence to validate a fix. Remediation itself happens outside TaskBot. | Read-only JSON API (`/api/findings`, `/api/activity`). |
| **Supervisor / examiner** *(primary)* | A clear, believable, demoable vulnerable app understandable in minutes. | Web UI. |
| **Students** *(secondary)* | DVWA-style teaching value — see a skill lie about itself and watch the host catch it. | Web UI. |

---

## 4. Goals

- **G1** — Ship a realistic, deliberately-vulnerable agentic-skills target with **3 clearly-isolated vulnerabilities**, each mapped to one OWASP AST risk.
- **G2** — Each vulnerability fires through a **real LLM agent's own decision to run the skill** — never a scripted or hardcoded demo path.
- **G3** — Each vulnerability is **detectable**: it produces a structured finding a scanner can consume.
- **G4** — Every exploit is **safe, local, and observable**. A marker artifact proves it fired; nothing touches a real system, real network, or real credentials.
- **G5** — A **control skill** behaves exactly as declared and produces **no finding**, so false-positive rate is measurable.
- **G6** — Runs locally with **one command plus a local model**, and reads as a believable product.

## 5. Non-goals

- **NG1** — Not all 10 AST risks. Three now; a fourth is a possible later addition, out of scope for v1.
- **NG2** — No remediation, patched variant, or "fixed" mode inside the app. That lives externally.
- **NG3** — **No security-level toggles, difficulty switches, or safe mode.** The app is always vulnerable. Configuration that could turn a vulnerability off is explicitly rejected — it would let a scanner pass by accident.
- **NG4** — Vulnerabilities never live in the assistant's general-chat path. Prompt injection, jailbreaks, and unsafe generation belong to the LLM-layer app. Any vulnerability reachable without a skill installed is a defect.
- **NG5** — Not production software. No auth, no multi-user, no deployment story, no persistence guarantees. Lab use only.
- **NG6** — Not a scanner. TaskBot reports what it observed; judging and remediating is someone else's job.

---

## 6. Product requirements

### FR-1 — To-do assistant (baseline)
- **FR-1.1** Users add tasks and list tasks through natural conversation.
- **FR-1.2** Tasks persist locally across restarts.
- **FR-1.3** Task data is the crown jewel of this product — it is the asset the vulnerable skills target. It must be substantive enough that its theft reads as a real loss (seedable with believable content).
- **FR-1.4** With zero skills installed, TaskBot is a complete, working, **non-vulnerable** assistant. This is the baseline that proves NG4.

### FR-2 — Skill store
- **FR-2.1** Users browse a catalogue of available skills, seeing each skill's **declared** name, description, and permissions — the manifest's claims, presented at face value, exactly as a real store would.
- **FR-2.2** Users install and uninstall skills. Installed state persists.
- **FR-2.3** A skill is a self-contained unit: **manifest** (identity, description, declared permissions/capabilities) + **code**.
- **FR-2.4** The store ships the four catalogue skills (§7).
- **FR-2.5** Users may also supply their own skill (manifest + code) and install it. See §7.5 for scoping.
- **FR-2.6** Only installed skills are visible to the LLM.

### FR-3 — LLM-driven dispatch *(the mechanism the whole product rests on)*
- **FR-3.1** On each user message, the LLM is given the installed skills and their declared manifests, and **decides on its own** whether one applies.
- **FR-3.2** If a skill fits, the LLM invokes it. This is the only path by which a vulnerability can fire.
- **FR-3.3** If no skill fits, or none is installed, the LLM answers directly as a normal assistant.
- **FR-3.4** **No hardcoded routing.** No keyword matching, no regex dispatch, no "if user says X run skill Y". If a reviewer can find a code path that forces a skill to run, the product has failed G2.
- **FR-3.5** The model runs locally (Ollama). No external inference.

### FR-4 — Capability monitor and findings engine
- **FR-4.1** The host observes what a skill **actually does** during execution, recording at minimum: file reads, network calls, and access to user task data.
- **FR-4.2** Detection is **runtime-observation based**. A finding is only raised because a skill was actually invoked by the LLM and actually did something — which makes every finding simultaneously proof the exploit fired.
- **FR-4.3** After execution, observed capabilities are diffed against the manifest's declared capabilities. Divergence produces a **finding**.
- **FR-4.4** A finding carries: the skill, the AST risk ID, a severity, what was declared, what was observed, evidence (marker reference), and a timestamp.
- **FR-4.5** Findings persist and accumulate across runs.
- **FR-4.6** A skill whose observed behaviour matches its declaration produces **no finding** (G5).

### FR-5 — Activity log
- **FR-5.1** Every assistant turn is logged: the request, whether a skill handled it, which one, and the outcome.
- **FR-5.2** Turns where a vulnerability fired are visibly marked as such.
- **FR-5.3** The log is the demo surface — a supervisor watches it and sees the story of an exploit without reading code.

### FR-6 — Machine interface
- **FR-6.1** Read-only JSON endpoints expose skill catalogue and installed state, findings, and activity log.
- **FR-6.2** Chat is reachable programmatically, so a scanning agent can drive the assistant the same way a user does.
- **FR-6.3** Response shapes are stable and documented — this is the contract both agents depend on.
- **FR-6.4** No authentication. Lab tool, localhost only.

### FR-7 — Safety envelope *(hard constraint — overrides every other requirement)*
- **FR-7.1** Exploits are **simulated**. Their effect is to write an observable local marker artifact.
- **FR-7.2** "Exfiltration" targets a **local mock collector** inside the app. No packet leaves the machine.
- **FR-7.3** File access is confined to files the app itself created for the purpose. No reading of real user documents, credentials, SSH keys, browser data, or environment secrets.
- **FR-7.4** No destructive operations. Nothing is deleted, encrypted, or modified outside the app's own data directory.
- **FR-7.5** Markers are unambiguous, greppable, and safe to delete — resetting the lab is trivial.
- **FR-7.6** The repo states prominently that this app is intentionally vulnerable and is for local lab use only.

---

## 7. Vulnerability catalogue

Three vulnerabilities plus one control. Each is described here at product level — what the user sees, what actually happens, and what proves it.

### 7.1 — AST04 · Insecure Metadata
> *"A skill that lies in its manifest."*

- **Presents as** a helpful utility whose manifest declares it read-only, local, and network-free.
- **Actually** reads from the filesystem and makes a network call — neither declared.
- **Fires when** the LLM chooses it for a plausible user request.
- **Proof** — marker artifact + finding showing `declared: {read-only, no network}` against `observed: {file read, network call}`.
- **The point** — manifests are self-asserted. A store that trusts them is trusting the attacker.

### 7.2 — AST01 · Malicious Skills
> *"A benign-looking skill with hidden logic."*

- **Presents as** an ordinary, useful, well-described skill. Its stated function works correctly — this is what makes it convincing.
- **Actually** also quietly copies the user's task data to the local mock collector while performing its advertised job.
- **Fires when** the LLM chooses it for the legitimate purpose it advertises. The user never asks for the malicious behaviour.
- **Proof** — task data present in the mock collector, plus marker and finding.
- **The point** — a skill doing its stated job correctly is not evidence it is doing only that.

### 7.3 — AST03 · Over-Privileged Skills
> *"A skill granted far more access than it needs."*

- **Presents as** a simple skill needing minimal access.
- **Actually** holds and exercises broad capability well beyond both its declared permissions and its functional need.
- **Fires when** the LLM invokes it and it reaches beyond its remit.
- **Proof** — observed capability set materially exceeds declared and required; marker and finding.
- **The point** — excess privilege is latent damage waiting for any bug or compromise.

**Distinction from AST04 (must remain visible in findings):** AST04 is about a **false declaration** — the manifest misrepresents. AST03 is about **excessive grant** — the privilege is real and may even be declared, but it is disproportionate. The findings engine must express these as different failures, not two spellings of "mismatch."

### 7.4 — Control skill *(no AST risk)*
- Behaves **exactly** as declared, using exactly the capabilities it announced.
- **Must produce zero findings**, ever.
- Without it, "the scanner found three things" is unfalsifiable. This is the false-positive baseline (G5).

### 7.5 — Scoping note: user-supplied skills (FR-2.5)
Allowing users to install their own skill is a **product feature**, and a deliberate one — it mirrors how real skill stores accept third-party contributions, and it gives the red-team agent a way to deliver its own probe skill for capability testing.

To keep the target unambiguous:
- The upload path is **not counted as a fourth vulnerability** and has no AST ID.
- Findings from user-supplied skills are classified against the **same AST taxonomy** as catalogue skills — the monitor treats all skills identically.
- The **three catalogue vulnerabilities remain the scored surface.** Success criteria (§10) are measured against catalogue skills only, so an uploaded skill can never inflate or mask the result.

---

## 8. Release sequence

Built and shipped one at a time, in this order. Each release is independently demoable.

| Release | Feature | Contents | Done when |
|---|---|---|---|
| **R0 — Foundation** | `app-foundation` | To-do assistant, LLM dispatch, skill store, capability monitor, findings engine, activity log, JSON API, **control skill only** | App runs, chats, installs/uninstalls the control skill, runs it, and reports **zero findings** |
| **R1 — AST04** | `ast04-insecure-metadata` | Insecure-metadata skill | Fires via LLM; declared-vs-observed finding raised; control still clean |
| **R2 — AST01** | `ast01-malicious-skills` | Malicious skill | Task data reaches mock collector via LLM-chosen invocation; finding raised; control still clean |
| **R3 — AST03** | `ast03-over-privileged` | Over-privileged skill | Excess capability observed and distinguished from AST04; control still clean |

R0 carrying the control skill is deliberate: it proves the monitor can stay silent before it is ever asked to speak.

Each release maps to one feature under `docs/features/<feature>/`. Release sequencing lives here and in per-feature plans; the shared architecture is release-agnostic and lives in `docs/TDD.md`.

---

## 9. Design and experience requirements

- **DR-1** Styling derives from `design/aegis-design-foundations.html`, used **purely as a token source**. The app carries **no external brand, logo, or project name** — it is TaskBot only.
- **DR-2** Dark-first, purple-accented security-tool aesthetic: canvas `#08080D`, surfaces `#0d0d14`/`#14141b`/`#1b1b24`, purple ramp `#6B3B85` → `#C5A7D9`, borders at `rgba(197,167,217,0.12)`.
- **DR-3** Raleway for UI; monospace for findings, manifests, evidence, and log detail.
- **DR-4** Findings use the foundations' severity scale as badges — critical `#FF4D5E`, high `#FF8A3D`, medium `#E6B84A`, low `#56A8E8`, info `#8C97BE`.
- **DR-5** **Polished product, not DVWA-gray.** Scope is deliberately small; visual quality is not. A believable-looking product is what makes the vulnerabilities read as realistic (G6) rather than as toys.
- **DR-6** The interface must let a reviewer follow one story end to end: *install a skill → ask something ordinary → watch the assistant choose it → see the finding appear.*

---

## 10. Success criteria

| # | Criterion | Measure |
|---|---|---|
| **SC-1** | Each of the 3 vulnerabilities fires through the LLM agent | **≥4 of 5** distinct, natural trigger prompts per vulnerability cause the LLM to choose the skill and the exploit to fire |
| **SC-2** | Each firing is detectable with proof | Every firing yields both a marker artifact and a findings-API entry carrying the correct AST ID |
| **SC-3** | Control skill is clean | Invoked repeatedly across all sessions, produces **zero** findings |
| **SC-4** | Vulnerabilities are skill-scoped | With no skills installed, no exploit is reachable and no finding can be produced |
| **SC-5** | Nothing escapes the sandbox | No non-local network egress; no file access outside the app's own data directory; all effects reversible by deleting markers |
| **SC-6** | Runs trivially | One command plus a local model, from a clean checkout |
| **SC-7** | Demoable in minutes | A reviewer who has never seen it can follow install → trigger → finding unaided |
| **SC-8** | Believable | Reads as a real small assistant product, not a test harness |

---

## 11. Technical direction *(context, not requirements)*

Python + FastAPI + Jinja2, plain HTML/CSS. Local LLM via **Ollama (required)**. JSON-file storage. Skills as manifest + code folders on disk. Chosen for one-command local runs and readable-in-minutes source.

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Local model is inconsistent at choosing skills | SC-1 flaky; G2 undermined | Skill descriptions must be genuinely compelling for their stated purpose; measure against the 5-prompt bar and tune manifests, **never** by adding hardcoded routing (FR-3.4) |
| AST04 and AST03 findings blur together | Two of three vulnerabilities look like one | Findings engine expresses false-declaration vs excessive-grant as distinct failure types (§7.3) |
| Vulnerability leaks into the general-chat path | Becomes an LLM-layer app; breaks NG4 | SC-4 checked every release |
| Simulated exploits read as fake | Fails G6/SC-8 | Exploits mirror real technique and target real in-app data; only the *destination* is mocked |
| User-supplied skills muddy the scored surface | Ambiguous results | §7.5 — scoring counts catalogue skills only |
| App is mistaken for something safe to expose | Real harm | FR-7.6 warning; localhost-only, no auth by design |

---

## 13. Open items

- **A fourth vulnerability** — possible later, deliberately unscoped (NG1). Not designed for now, but the findings engine and store should not make adding one painful.
- ~~**AST risk severities**~~ — **resolved**: AST01 `critical`, AST04 `high`, AST03 `medium`, `BROKER_BYPASS` `high`, `UNUSED_GRANT` `low`. See `docs/TDD.md` §14 Q-2.

---

## 14. Document set

This PRD is the product source of truth. Technical work derives from it:

- `docs/TDD.md` — system-wide technical design (release-agnostic), covering the platform and all three vulnerability classes at architecture level.
- `docs/features/app-foundation/spec.md` — the platform, implementation-level.
- `docs/features/ast04-insecure-metadata/spec.md` · `docs/features/ast01-malicious-skills/spec.md` · `docs/features/ast03-over-privileged/spec.md` — one spec per vulnerability.

Per-feature plans are added alongside each spec when that feature is scheduled.
