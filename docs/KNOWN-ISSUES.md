# TaskBot — Known Issues

Defects and gaps that are **known, deliberate to leave in place for now, and disclosed** —
so that nobody reading the code later has to wonder whether they were missed.

This file is **not** a list of the app's intentional vulnerabilities. Those are the whole
point of the product and live in `docs/PRD.md` §7 and `vulnerabilities/`. This file is for
places where the **platform itself** does not yet do what its own specification says it
does.

Each entry says what is wrong, how it was found, what it does and does not affect, why it
has been left alone, and what fixing it would take.

---

## KI-1 — `UNUSED_GRANT` is implemented but never called

| | |
|---|---|
| **Area** | Findings engine — proportionality axis (AST03) |
| **Status** | **Open.** Deliberately deferred; disclosed here rather than fixed. |
| **Found** | While specifying `ast03-over-privileged` (2026-08-26), by checking the spec's claims against the running code instead of against the foundation documents. |
| **Severity** | Low for the lab's purpose. It removes one of the two AST03 finding types from the live product; the headline AST03 type (`EXCESSIVE_GRANT`) is unaffected. |

### What is wrong

`FindingsEngine.check_unused_grants(...)` in `backend/app/findings/engine.py` is fully
written and unit-tested: given a manifest, the capabilities used recently, an invocation
count and a window, it returns an `UNUSED_GRANT` finding for every capability a skill
holds but has not exercised. `tests/test_engine.py` proves it works, including the "wait
until the skill has run several times" rule (`TDD` D-10, window = 5).

**Nothing in the application ever calls it.** The per-invocation pass
(`FindingsEngine.evaluate_invocation`) runs truthfulness, then proportionality, then
correlation; the install path (`backend/app/api/routes.py`) calls `evaluate_install`,
which is the proportionality check only. A search across `backend/`, `frontend/` and
`tests/` finds exactly three references to the method: its own definition and two
unit-test calls.

So the type is real, its severity is settled (`low`, `TDD §14 Q-2`), it appears in the
taxonomy as implemented — and it **cannot appear in `/api/findings` for any skill**.

### Why this is a defect and not a design choice

`docs/features/app-foundation/spec.md` §9.3 specifies the runtime behaviour as delivered:

> `UNUSED_GRANT`: for a skill with ≥ `unused_grant_window` (5) invocations in
> `activity.json`, any granted capability with zero observations across that window emits
> `UNUSED_GRANT`.

The detector honours that description exactly. The caller that would feed it the
invocation history was never written. The foundation's acceptance criteria did not catch
it, because the only skill that existed at the time (the honest control skill) exercises
everything it declares and would produce no `UNUSED_GRANT` either way.

### What it affects

- **Affected** — the `UNUSED_GRANT` row of the AST03 story. A skill holding a dormant,
  never-used permission is not reported at runtime today.
- **Not affected** — everything else. `EXCESSIVE_GRANT` (AST03, `medium`) fires normally
  from both call sites, at install and on every invocation. The truthfulness axis (AST04)
  and the correlation axis (AST01) are untouched. `Settings.unused_grant_window` and
  `TASKBOT_UNUSED_GRANT_WINDOW` are read correctly and are simply unused.
- **Not a safety issue.** Nothing here can leak, escape, or make the lab less contained.

### Why it is being left alone for now

The AST03 feature (`docs/features/ast03-over-privileged/spec.md`) deliberately does **not**
fix it. `docs/TDD.md` §12 states that the platform is complete for all three
vulnerabilities once the foundation ships, and that a vulnerability feature needing a
`backend/**` edit is a signal the exploit is being faked rather than genuinely exercised
(goal G2). Wiring a new call site into the orchestrator to make AST03 demonstrable would
be exactly that signal.

So AST03 ships on `EXCESSIVE_GRANT` alone, with **zero platform change**, while its skill
(*Focus Picker*) is deliberately built to hold two dormant permissions — making it
`UNUSED_GRANT`-eligible the moment the wiring lands. Its acceptance test **A-7** proves
that eligibility by calling `check_unused_grants` directly, and asserts that no platform
call site invokes the method — so this gap is pinned by a test rather than left to drift.

### What fixing it would take

A small, self-contained foundation task, best sequenced **after all three vulnerabilities
are complete**:

1. In `backend/app/chat/orchestrator.py`, after the per-invocation evaluation, read the
   skill's last `unused_grant_window` activity entries from `activity.json`, collect the
   capabilities observed across them, and count the skill's invocations.
2. Call `engine.check_unused_grants(manifest, used_recently, invocation_count, window)`
   and pass the results through the existing `_save_findings` path — no new persistence,
   no new marker logic, no schema change.
3. Confirm the control skill stays clean (it exercises everything it declares, so it must
   remain silent — `TDD §11` I-12).
4. Re-run the AST03 suite: *Focus Picker*'s two dormant grants should then surface as two
   additional `low` findings, and the expected counts in its acceptance tests A-3 and A-12
   move accordingly. Nothing else in the AST03 spec changes.

### References

- `backend/app/findings/engine.py` — `check_unused_grants`, `evaluate_invocation`,
  `evaluate_install`
- `backend/app/findings/taxonomy.py` — the `UNUSED_GRANT` row (AST03, proportionality, `low`)
- `docs/features/app-foundation/spec.md` §9.3 — the behaviour as specified
- `docs/features/ast03-over-privileged/spec.md` §5.2, §12, A-7 — the disclosure and the
  pinning test
- `docs/TDD.md` §4.5, §12, §14 Q-2, D-10

---

## KI-2 — a finding never remembers where its own evidence file is

| | |
|---|---|
| **Area** | Findings persistence — `store.upsert_finding`, and both places that call it |
| **Status** | **Open.** Found while building AST05; disclosed here rather than fixed. |
| **Found** | 2026-08-27, by an AST05 acceptance test asserting `evidence.marker` through the API and getting `null`. |
| **Severity** | Low for the lab's purpose. The evidence files are written correctly and are findable on disk; only the pointer stored beside the finding is lost. A side effect inflates `occurrences`. |

### What is wrong

Every finding is meant to carry the path of its own marker file, so a reader can go straight
from a finding to its evidence. **No finding does, for any vulnerability, at either call site.**
A second symptom travels with it: `occurrences` reads **2** after a single first sighting.

Both come from the same two-step save, in `backend/app/chat/orchestrator.py` `_save_findings`
and again in `backend/app/api/routes.py` `install_skill`:

```python
stored, is_new = store.upsert_finding(finding)   # 1. appended; is_new=True
if is_new:
    stored.evidence["marker"] = str(write_marker(stored, ...))   # 2. path set on the object
    store.upsert_finding(stored)                 # 3. saved again
```

Step 3 re-enters `upsert_finding`, which computes the dedup key, finds the record **just
appended at step 1**, and takes its "seen before" branch — bumping `occurrences` and returning
without writing the mutated `evidence` back. The marker path is set on an object that is then
discarded.

### What it affects

- **Affected** — `evidence.marker` is `null` on every finding in `/api/findings`, and
  `occurrences` starts at 2 rather than 1. Confirmed against **AST03** (`focus_picker`), which
  has shipped with this behaviour since R3, so it is **not** introduced by AST05.
- **Not affected** — the marker files themselves. They are written, they contain the correct
  contents including the literal `INTENTIONALLY_VULNERABLE_LAB_MARKER` phrase, and
  `count_markers()` is accurate. FR-7.1's actual requirement — an exploit leaves an observable
  artifact — holds.
- **Not a safety issue.** Nothing can leak, escape, or make the lab less contained.

### Why the existing tests did not catch it

They assert the right things for FR-7.1 and stop just short. AST03's A-3 asserts
`count_markers() == 3` and reads the marker files directly; nothing asserted the *pointer*.
AST05's A-17 did, which is how it surfaced.

### Why it is being left alone for now

Fixing it means changing how findings are persisted — shared machinery used by all four
vulnerabilities and both call sites. AST05 already carries the only sanctioned platform change
(`TDD §12` carve-out), and bundling an unrelated persistence fix into it would blur the one
change that had to be argued for. Same reasoning that left KI-1 alone.

Pinned by
`vulnerabilities/ast05-untrusted-external-instructions/tests/test_team_rules_api.py::test_the_marker_pointer_is_empty_for_every_weakness_not_just_this_one`,
which asserts the defect **and** says what to do when it is fixed — so it cannot silently
close or silently widen.

### What fixing it would take

Small and self-contained, best done alongside KI-1 after all four vulnerabilities ship:

1. Give `store` a way to update an existing finding in place — e.g. `update_finding(finding)`
   that replaces the stored record by `id` — rather than re-entering `upsert_finding`.
2. Use it at both call sites for the marker stamp.
3. Assert `occurrences == 1` on a first sighting, and `evidence.marker` non-null, at both.
4. Re-run the AST03 and AST05 suites: AST03's A-12 expects `occurrences >= 2` after an
   invocation following an install, which stays true; the AST05 pinning test above should be
   **updated, not deleted**, and A-17's evidence-pointer assertion restored.

### References

- `backend/app/storage/store.py` — `upsert_finding`
- `backend/app/chat/orchestrator.py` — `_save_findings`
- `backend/app/api/routes.py` — `install_skill`
- `docs/features/ast05-untrusted-external-instructions/spec.md` §10 (A-17)
