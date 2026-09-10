# AST04 — Insecure Metadata

**A skill that lies in its description.**

It presents as a helpful utility whose description declares it read-only, local and
network-free. In fact it reads from the filesystem and makes a network call, and it
declared neither.

**Detected by:** the findings engine's **truthfulness** check — what the skill did,
compared against what it said it would do. Severity **high**.

**The point:** a description is only ever a claim. A store that trusts it is trusting
whoever wrote it.

**Status:** not built. Specification: `docs/features/ast04-insecure-metadata/spec.md`.

```
skill/     the skill folder goes here: <skill_id>/{manifest.json, skill.py}
tests/     proof that it fires, and that exactly the right finding is raised
```

Nothing shared belongs in this folder — see `../README.md`.
