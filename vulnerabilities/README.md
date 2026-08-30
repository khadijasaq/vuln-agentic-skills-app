# Vulnerabilities

One folder per deliberate weakness. Each is completely independent of the others.

```
vulnerabilities/
├── ast04-insecure-metadata/               a skill that lies in its description
├── ast01-malicious-skills/                a useful skill that quietly steals your task list
├── ast03-over-privileged/                 a skill holding far more power than it needs
├── ast05-untrusted-external-instructions/ a skill that does whatever a fetched document says
└── ast02-supply-chain/                    a skill handed a different component than it pinned
```

Each folder holds exactly one weakness, in the same shape:

```
<name>/
├── README.md      what this weakness is and how it is detected
├── skill/         <skill_id>/{manifest.json, skill.py}
└── tests/         proof that it fires, and that it is detected correctly
```

Two of them carry one extra folder, because their attack is **content** rather than code —
a file a person can read and edit without touching Python:

```
ast05-.../hub/       the document the mock team hub serves
ast02-.../registry/  the components the mock registry publishes
```

The app finds all of this automatically. `SkillRegistry.default_roots()` searches the shared
catalogue **plus** every `vulnerabilities/*/skill/` folder, and the startup steps copy any
`hub/` document and any `registry/` components into `data/` on a fresh lab. None of that
machinery knows the name of a single weakness — it looks for the shape, not for `ast02`.
Adding a weakness means adding a folder — no wiring, no registration list to update.

---

## The rule that matters: shared stays shared

**A weakness folder contains only that weakness.** It must never contain a copy of any
part of the platform.

The capability broker, the watchers, the findings engine, the taxonomy, the
conversation and dispatch code, storage, the policy files, and the honest control skill
are all **shared foundation**, and they live in `backend/`. A weakness *plugs into*
them; it does not carry its own version of them.

This is not tidiness. Three things depend on it:

1. **The weaknesses must be comparable.** All five are judged by the same engine
   against the same policy. If each carried its own detector, "the scanner found five
   problems" would mean five different scanners agreeing with themselves.

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

## What is here

All five weaknesses are built: each ships its manifest, its code, and its own tests, and
each has a specification under `docs/features/`.

The findings engine asks **five** separate questions, and each weakness exists to prove that
one of them is genuinely necessary:

| Question | Asks | Weakness |
|---|---|---|
| truthfulness | did it do what it said? | AST04 |
| proportionality | did it need that much power? | AST03 |
| correlation | did it combine two harmless abilities into a harmful one? | AST01 |
| provenance | where did its behaviour come from? | AST05 |
| integrity | is what it was handed what it agreed to? | AST02 |

Two of them needed something added to the shared platform, and both had to argue for it
against the rule in `docs/TDD.md` §12. **AST05** made the capability broker start recording
what comes back from a network request. **AST02** added no recording at all — it gave a
manifest somewhere to declare which component it depends on, and a check that compares that
promise against a fingerprint the app was already writing down.

Everything else plugs into machinery that was finished before it existed.
