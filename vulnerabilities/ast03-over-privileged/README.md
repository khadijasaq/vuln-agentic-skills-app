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

**Status:** not built. The proportionality check itself is already implemented and
proven against fabricated descriptions. Specification:
`docs/features/ast03-over-privileged/spec.md`.

```
skill/     the skill folder goes here: <skill_id>/{manifest.json, skill.py}
tests/     proof that it fires, and that it is not confused with AST04
```

Nothing shared belongs in this folder — see `../README.md`.
