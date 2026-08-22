# Vulnerabilities

One folder per deliberate weakness. Each is completely independent of the others.

```
vulnerabilities/
├── ast04-insecure-metadata/     a skill that lies in its description
├── ast01-malicious-skills/      a useful skill that quietly steals your task list
└── ast03-over-privileged/       a skill holding far more power than it needs
```

Each folder holds exactly one weakness, in the same shape:

```
<name>/
├── README.md      what this weakness is and how it is detected
├── skill/         <skill_id>/{manifest.json, skill.py}
└── tests/         proof that it fires, and that it is detected correctly
```

The app finds these automatically: `SkillRegistry.default_roots()` searches the shared
catalogue **plus** every `vulnerabilities/*/skill/` folder. Adding a weakness means
adding a folder — no wiring, no registration list to update.

---

## The rule that matters: shared stays shared

**A weakness folder contains only that weakness.** It must never contain a copy of any
part of the platform.

The capability broker, the watchers, the findings engine, the taxonomy, the
conversation and dispatch code, storage, the policy files, and the honest control skill
are all **shared foundation**, and they live in `backend/`. A weakness *plugs into*
them; it does not carry its own version of them.

This is not tidiness. Three things depend on it:

1. **The weaknesses must be comparable.** All three are judged by the same engine
   against the same policy. If each carried its own detector, "the scanner found three
   problems" would mean three different scanners agreeing with themselves.

2. **The control skill must stay meaningful.** `backend/skills/catalogue/task_summary`
   is honest and must always produce zero findings. That only proves anything if it
   runs through the *same* machinery the weaknesses do.

3. **A weakness must not be able to weaken another.** Keeping each one isolated, with
   no shared code of its own, means adding or removing one cannot change how any other
   behaves.

If a weakness genuinely needs something new from the platform — a new detection rule,
a new recorded field — **that change belongs in `backend/`**, shared by everyone. Not
copied into the folder.

---

## What is not here yet

All three folders are empty apart from their READMEs. The platform they plug into is
built and tested; the weaknesses themselves are separate pieces of work, each with its
own specification under `docs/features/`.

The findings engine already knows about all three risk types. Two of them —
truthfulness (AST04) and proportionality (AST03) — are fully implemented and proven
against fabricated test descriptions. The third, correlation (AST01), is declared in
the taxonomy with `implemented: False`, waiting for its feature.
