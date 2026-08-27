# TaskBot — Presentation Guide

A speak-out-loud script for presenting the whole TaskBot lab and demonstrating the
two malicious skills (AST01 and AST04) live. Written in plain language, with a
"what to click / what to say" demo walkthrough and fallback logic for hard questions.

---

## Part 1 — The one-sentence pitch (start here)

> "TaskBot is a small task-manager app with an AI assistant. You can install **skills** —
> little add-ons that give the assistant new powers. My project is a *safety lab*: it shows
> how a skill can look completely normal and useful, but secretly do something harmful — and
> how you can automatically catch it."

That's the whole thing in one breath. Everything else is detail.

---

## Part 2 — The big idea the whole project is built on

There are **three questions** you ask about every skill. This is the heart of the project:

| # | The question | Short name | What it catches |
|---|---|---|---|
| 1 | **Did the skill tell the truth about what it does?** | Truthfulness | **AST04** — a skill that *lies* in its description |
| 2 | **Did the skill ask for more power than it needs?** | Proportionality | AST03 — over-privileged (scaffolded, not built) |
| 3 | **Did the skill combine two harmless powers into a harmful one?** | Correlation | **AST01** — the covert data theft |

> Key line: *"These three checks are independent on purpose. A sneaky skill that slips past
> one check should still get caught by another. My two vulnerabilities each attack a
> different check."*

- **AST01** attacks check #3 (correlation).
- **AST04** attacks check #1 (truthfulness).

Two vulnerabilities = two different failure modes.

---

## Part 3 — The 4-minute live demo (what to click, what to say)

**Before the audience arrives:** start Ollama, then from the repo root run the server:

```
uv run uvicorn --app-dir backend app.main:app --host 127.0.0.1 --port 8000
```

Open the browser at `http://127.0.0.1:8000`. Have a terminal window visible too.

### Scene 1 — Show it's a normal app (30 sec)
- Show the **Tasks** page. "This is just a to-do app. Nothing scary yet."
- Show the **Store** page. "These are installed skills. Some are honest, two are malicious —
  but you can't tell by looking. That's the whole point."

### Scene 2 — The honest control skill (30 sec)
- In chat, type: **"summarise my tasks"** → it triggers *Task Summary*.
- Show the **Findings** page → **empty / clean**.
- Say: *"This is a normal skill. Nothing flagged. This is my baseline — proof the lab doesn't
  cry wolf."*

### Scene 3 — AST01, the covert theft (90 sec) ⭐ headline
- In chat, type: **"post my standup to the team"** → it triggers *Standup Sync*.
- The assistant replies with a friendly standup line — **"Standup: 8 tasks open. Longest
  outstanding: '…'."**
- Open the **Dashboard** page. Say: *"The user asked for a standup, and got one. It even shows
  up here on the dashboard. Looks perfect."*
- **Now the reveal.** Open the **Findings** page → **one CRITICAL finding: COVERT_DATA_FLOW /
  AST01.**
- Click it. Say: *"Behind the scenes, before it ever posted that standup, the skill quietly
  copied my **entire** task list and shipped it out. The finding shows the evidence: it
  **read** the tasks, then **sent** them — that read-then-send pair is the theft."*
- In the terminal, show the stolen copy landed locally:
  ```
  ls data/collector/inbox/
  ```
  *"There's the stolen data. Nothing left my laptop — the 'attacker' is a folder on this
  machine — but in the real world that's your data gone."*

### Scene 4 — AST04, the lying skill (60 sec)
- In chat, type: **"give me insights on my tasks"** → it triggers *Task Insights*.
- It returns a normal-looking summary.
- Open **Findings** → **two HIGH findings: UNDECLARED_CAPABILITY / AST04.**
- Say: *"This skill's description swears it works **offline**, reads nothing, sends nothing.
  But it actually **read a file** and **called the network** — and declared neither. It lied
  in its manifest. My truthfulness check caught the gap between what it **said** and what it
  **did**."*

### Scene 5 — Reset (20 sec)
- Click **Reset** (or `POST /api/reset`). Show Findings goes back to empty.
- Say: *"Everything's reversible. I can run the exact same attack again from a clean slate —
  it's a repeatable lab, not a one-time trick."*

---

## Part 4 — AST01 explained simply (the "how does it actually work?" question)

> "Standup Sync has **two legal powers**: it can *read tasks*, and it can *send things
> locally*. Both are totally normal for a 'post my standup' skill — it honestly declares
> both. So the truthfulness check is happy, and the 'too much power?' check is happy too.
>
> The trick is the **order and the combination**. The very first thing it does — before the
> standup — is read the **whole** task list and send a copy to a hidden collector. Then it
> does the real standup job. The user only sees the standup. The theft is invisible.
>
> No single power is wrong. Reading is fine. Sending is fine. It's **read-then-send of the
> same data** that's the attack. That's exactly what my third check — correlation — looks
> for: it spots that the data that was just read is the data that just left."

**If they ask "why is it stealthy?"** — two honest reasons:
1. It steals **first**, so even if the visible standup part is blocked, the theft already
   happened.
2. The standup line the user sees carries only a *count and one title* — never the actual
   task contents — so the honest output can't be mistaken for the theft.

**One-line takeaway:** *"Two safe ingredients, combined, make poison. Only a check that looks
at the combination can catch it."*

---

## Part 5 — AST04 explained simply

> "Every skill ships a **manifest** — like an ingredients label. It declares what the skill is
> allowed to touch. My *Task Insights* skill's label says: reads only your tasks, works
> offline, no network. Sounds safe, so it installs with no complaints.
>
> But when it runs, it does two things the label never mentioned: it **opens a file** on disk,
> and it **makes a network call**. My truthfulness check watches what the skill *actually*
> does through the official channels, and compares it to the label. Two undeclared actions →
> two findings. The skill got caught **lying**, not stealing."

**If they ask "what's the difference between AST01 and AST04?"**:
- **AST01 = a true statement used for evil.** Everything is declared honestly; the
  *combination* is the harm.
- **AST04 = a false statement.** The individual actions aren't even that dangerous; the harm
  is that the label *lied*.

Different sins, caught by different checks. That's the thesis.

---

## Part 6 — The clever design point (sound like you know your stuff)

> "The reason the lab is trustworthy is a rule I follow everywhere: the part of the system
> that **watches** what a skill does never looks at the skill's manifest, and it records what
> happened **before** deciding whether to allow it. So a skill can't hide by refusing an
> action — the action is already on the record. The watcher and the label are kept separate,
> so a lying label can't fool the watcher."

> "The skills only act through one official channel — I never let them import raw file or
> network tools. If a skill tried to go around that channel, that itself would be a finding.
> So even the vulnerabilities are 'safe' — they can only misbehave in the ways the lab is
> designed to catch."

---

## Part 7 — Likely questions + answers

**"Is this actually dangerous / did anything leave your computer?"**
> "No. Every address involved is `127.0.0.1` — my own machine. The 'attacker's server' is a
> local folder. It's a lab, deliberately declawed, so I can demonstrate the attack safely."

**"How do you know your detector actually works and isn't faked?"**
> "It's fully tested — the whole suite is ~449 automated tests. The findings are produced by
> the same engine in the live app; I don't hand-write them. And I have a control skill that
> stays clean, so I know the detector isn't just flagging everything."

**"Could a real attacker do this?"**
> "Yes — that's the point. Skill marketplaces are new and people install them trustingly. A
> skill that does its advertised job perfectly while stealing on the side is a very realistic
> threat. My lab shows both the attack and the detection."

**"Why build two vulnerabilities?"**
> "To prove the checks are independent. AST01 slips past the truthfulness and privilege checks
> but is caught by correlation. AST04 is caught by truthfulness. One vulnerability wouldn't
> show that layered defence."

**"What's AST03?"**
> "Over-privileged skills — asking for more power than needed. It's scaffolded in the engine
> but I focused my demo on the two most illustrative attacks."

---

## Closing (20 seconds)

> "So TaskBot is a safe playground for a real problem: AI skills you can't trust by looking at
> them. I built two realistic malicious skills — one that **steals by combining honest
> powers**, one that **lies about what it does** — and a detection system that catches each
> with a different, independent check. Everything is reversible, repeatable, and fully
> tested."

---

## Two things to do tonight

1. **Do one full dry run** on the real Ollama model. The live model sometimes phrases things
   differently, so run each prompt once and confirm the finding appears before you're in front
   of people.
2. If a prompt doesn't trigger the right skill live, say the trigger phrase more directly
   (e.g. "use Standup Sync to post my standup"). That's normal, not a flaw in the project.
