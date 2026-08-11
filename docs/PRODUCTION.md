# Producing the video — tools, standards, and what the research actually changed

*Written 2026-08-12, two days before feature freeze. Everything here either goes
into the film or gets thrown away. Nothing in this document is a project.*

---

## 🎯 The one tool that changes the shoot

**VHS** *(`charmbracelet/vhs`, MIT)* records a terminal from a **script**, not from a
performance. You write a `.tape` file listing what is typed and when, and it renders
GIF, MP4 or WebM with **identical output every run**.

➡️ **Why it matters here specifically, and not just as a convenience.** The stress
bench already proved `agent_loop.py` returns byte-identical output across runs. With
VHS the *recording* becomes deterministic too, so **the rehearsal and the take are
the same artefact.** A project whose entire claim is reproducibility should not have
its demo depend on a human typing without a mistake.

⚠️ Alternative if VHS will not build on Windows: **asciinema** records live and
replays exactly, but it captures a performance rather than a script, so a fluffed
line means a retake. Use it only as a fallback.

For the browser half — the demo page, the propose/commit gesture — **OBS Studio**
*(GPLv2)*. Nothing else is needed: no compositor, no motion graphics, no 3D. The
machine takes 11 minutes per Cycles frame, so rendered shots were excluded from the
start and that constraint has not moved.

| need | tool | licence | cost |
|---|---|---|---|
| terminal, deterministic | **VHS** | MIT | free |
| browser capture | **OBS Studio** | GPLv2 | free |
| edit and cut | **Shotcut** or **Kdenlive** | GPL | free |
| voice | **ElevenLabs** | free tier | 10k chars/month, the script is ~2.2k |
| subtitles | **Whisper** *(local)* or the editor's own | MIT | free |

**Nothing on this list needs a card, and nothing needs an account except the voice.**

---

## What the UI research changed, and what it did not

The contest weighs **UI at 15%**. That is real, and it is also the smallest slice
after documentation at 25% and creativity at 20%. So the rule for the next two days
is: **only changes that cost minutes.**

Three principles came back from every source, French, Japanese and English alike,
and the Japanese Digital Agency publishes an official dashboard guidebook that says
the same:

| principle | what it means here | state |
|---|---|---|
| **hierarchy** — what matters goes top-left | the page opens on *"The memory that says what it is missing"* | 🟢 already true |
| **proximity** — related things sit together | belief, status, source and date are on one row | 🟢 already true |
| **accessibility first**, now mainstream rather than a courtesy | contrast, focus rings, `prefers-reduced-motion` | ⚠️ **unverified** |

🔴 **The only UI item worth touching before the freeze is accessibility**, because it
is the one that is both cheap and unmeasured. Everything else on the page is already
doing what the guidebooks ask.

⛔ **Not doing:** redesign, animation, a component library, dark mode, a landing
page. Each would be defensible on any other week.

---

## What the orchestration research changed — and this one changes the SCRIPT

**12-Factor Agents** *(HumanLayer)* is the closest thing the field has to a
best-practice list for agent design. Two of its factors are already satisfied here
without having been aimed at:

| factor | what it asks | this project |
|---|---|---|
| **8 — own your control flow** | own the loop; do not let a framework decide when to retry, pause or stop | 🟢 `agent_loop.py` is the loop. No framework |
| **12 — stateless reducer** | the agent is a pure function `f(events) -> next_action` | 🟢 same memory in, same decision out, proven byte-identical |
| **9 — compact errors** | catch failures and feed a short version back rather than crashing | 🟢 three benches, 59 cases, no traceback |

🎯 **And the headline of that literature is the line to steal:** *production LLM
applications are mostly deterministic code.*

**This agent takes that to its limit: it calls no model at all.** That is not a
missing feature to apologise for. The decision follows from stored beliefs, and an
agent that reasons its way to a different answer on a Tuesday is not a memory, it is
a mood. **Say it in the film, once, and move on.**

---

## The storytelling change, measured rather than felt

The script was measured against the author's own writing samples *(`07_Signature`,
gold rewrites)*. Most differences are the medium doing its job — spoken sentences are
shorter, a technical demo carries more numbers. One difference is not:

| marker | his own writing | the script |
|---|---|---|
| words per sentence | 14 | 9 *(fine, it is spoken)* |
| digits per 1000 words | 14.8 | 33.9 *(fine, it is a demo)* |
| **first person per 1000 words** | **32.8** | 🔴 **12.1** |

**The script is nearly three times less personal than the person reading it.**

➡️ That matters here more than it would elsewhere, because the subject of the film is
*"every revision is a moment where I was wrong and found out"*. Told in the third
person, that thesis is a feature list. **Told in the first person, it is a
confession, and a confession is what a jury remembers.**

The gap is not spread evenly. Blocks 1 and 4 are already personal. **Blocks 3 and 5
are where the narrator disappears**, and those are the two to rewrite — without
adding a second, because there are only 19 spare against a hard limit.

---

## What is deliberately NOT in this document

No component library, no design system, no motion language, no analytics, no
telemetry, no landing page, no second video. Each of those is a good idea on a week
that is not this one.

**The freeze is on the 14th and the video does not exist. Everything above either
shortens the shoot or it does not get done.**
