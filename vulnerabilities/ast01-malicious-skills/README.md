# AST01 — Malicious Skills

**A useful skill that quietly steals your task list.**

It looks ordinary and its advertised job works correctly — that is what makes it
convincing. While doing that job it also copies the user's tasks to the local mock
collector. The user never asks for it, and it happens whenever the AI model chooses
the skill for the perfectly legitimate purpose it advertises.

**Detected by:** the findings engine's **correlation** check — the order of what the
skill did, and fingerprints of the data involved. Reading tasks is fine. Sending
something locally is fine. Reading them and *then* sending them is theft. Severity
**critical**.

**Why it needs its own check:** this skill can declare everything truthfully and stay
within its category's permitted power, and still steal. Neither of the other two
checks would notice, because nothing was misdeclared and nothing was over-granted.

**Status:** not built. `COVERT_DATA_FLOW` is declared in the taxonomy with
`implemented: False`; this feature switches it on. The substrate it needs - ordered
records and per-item fingerprints - is already recorded by the foundation.

```
skill/     the skill folder goes here: <skill_id>/{manifest.json, skill.py}
tests/     proof that it fires, and that it is distinguishable from the other two
```

Nothing shared belongs in this folder — see `../README.md`.
