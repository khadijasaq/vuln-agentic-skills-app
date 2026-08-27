# AST03 — Over-Privileged Skills

**A skill holding far more power than it needs.**

It presents as something simple, then asks for sweeping access well beyond both what
it declared and what its job could possibly require.

**Detected by:** the findings engine's **proportionality** check — what the skill asked
for, compared against what its kind of skill reasonably needs
(`backend/policy/capability_baselines.json`). Severity **medium**.

**How this differs from AST04:** that one is about a **false claim** — the description
misrepresents. This one is about a **disproportionate grant** — the power is real, may
be declared perfectly honestly, and is still far too much. Different question,
different evidence, reported differently.

**The point:** excess privilege is latent damage, waiting for any bug or compromise to
turn it into real damage.

**The skill:** *Focus Picker* (`focus_picker`) - a small helper that names the one task
worth starting now. That job needs one ability: reading your list. It was handed four.
It really does use one of the extra three (it reads the app's record of every past
conversation, to "learn which kinds of task you finish"). The other two - changing your
tasks, and contacting the network - it holds and never touches. That dormant pair is
exactly what the thieving skill combines: the whole recipe, never cooked.

**What fires:** three `EXCESSIVE_GRANT` findings, severity **medium**, one per ability
outside what a reporting skill should have. They appear the moment the skill is
installed, because the question is only ever "how much was this handed?" - and every run
afterwards counts them again rather than adding new ones.

**Known gap:** the two dormant abilities would also be reported as `UNUSED_GRANT`, but the
app never asks that question yet. That is a platform defect, recorded as
`docs/KNOWN-ISSUES.md` **KI-1** and deliberately not fixed here - making a weakness
demonstrable by editing the platform would fake it.

**Status:** built. Specification: `docs/features/ast03-over-privileged/spec.md`;
build plan: `docs/features/ast03-over-privileged/plan.md`.

```
skill/focus_picker/    manifest.json + skill.py
tests/                 proof that it fires, and that it is not confused with AST04 or AST01
```

Nothing shared belongs in this folder — see `../README.md`.
