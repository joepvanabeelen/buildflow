# Brief: brainstorm before anything is designed or planned

The most expensive mistake in this workflow is building the wrong thing well. The gates
check that the feature is built right; the brief is where you check it is the right
feature. You (the orchestrator) run this yourself, as a conversation with the user. It is
not delegated: the thinking has to happen with the person who owns the problem.

Skip the conversation only when the user hands in a finished spec (`--brief <file>`):
read it, check it against the questions below, ask about real gaps, then record it with
`bf brief --file <spec> --given`. That counts as approved.

## Before you ask anything

Have the feature context ready (`bf:context:feature`), or at least started. Never ask
something the code can answer. Use what the scout found: "Leave requests already exist in
`src/leave/`, only as a draft status — is this about the approval step on top of that?"
is a good question; "Do you have a leave module?" is not.

## The conversation

Short rounds, a few questions at a time, each with your recommended answer and why. Use
AskUserQuestion when the options are clear, open questions when they are not. Stop
asking once the brief below can be written without guessing. Usually two or three
rounds.

1. **Problem**: what's going wrong or missing today, for whom, how often, what it costs
   them — push past the solution the user came with to the problem underneath.
2. **Users and situations**: who uses this, when, on which devices, with which
   permissions.
3. **Success**: observable outcomes, not features — what does the user do differently
   afterwards?
4. **Scope**: what's in, and just as important what's explicitly out; the smallest
   version worth shipping.
5. **Approaches**: two or three genuinely different ways to solve it, each with what it
   costs and what it makes harder later. Recommend one and say why; let the user choose.
6. **Constraints and risks**: data, privacy, performance, migrations, other teams,
   deadlines, what must not break.
7. **Open questions** that stay open: write them down with who decides.

Keep the user's own words where precise. Don't pad.

## brief.md

Write `.buildflow/<slug>/brief.md` in the run's language, headings included. The
questions you ask in the conversation above are in that language too, from the first one.

With `lang` nl, use exactly these headings:

```markdown
# <feature>

## Probleem
## Gebruikers en situaties
## Wat succes is
- waarneembare uitkomst 1 ...
## Scope
**Wel:** ...
**Niet:** ...
**Kleinste versie die het waard is:** ...
## Gekozen aanpak
<de aanpak, waarom deze, welke alternatieven afvielen en waarom>
## UI
<verandert dit wat gebruikers zien? welke schermen en states? bestaand design om te volgen?>
## Randvoorwaarden en risico's
## Open vragen
```

With `lang` en:

```markdown
# <feature>

## Problem
## Users and situations
## What success looks like
- observable outcome 1 ...
## Scope
**In:** ...
**Out:** ...
**Smallest version worth shipping:** ...
## Chosen approach
<the approach, why this one, which alternatives were dropped and why>
## UI
<does this change what users see? which screens and states? existing design to follow?>
## Constraints and risks
## Open questions
```

Also write `.buildflow/<slug>/brief-summary.md`: the brief shortened to ~150 words,
deterministically (goal + the acceptance/success outcomes, shortened, not a fresh
summary) — this is what `bf prompt` hands subagents instead of the whole brief. Then
`bf brief --file .buildflow/<slug>/brief.md` (records the summary too, or ask for it
explicitly if `bf` doesn't derive it).

No stop of its own — the brief feeds straight into the planner
(`references/checkpoint-planner.md`, `references/test-planner.md`); the human sees brief
and plan together at one stop (SKILL.md phase 1). Both must fit one screen: for the brief
that means the sections above kept tight, no restating. Don't pad to look thorough.

Once the plan is ready too, give the viewer URL and both summaries in chat (SKILL.md
phase 1's stop). Feedback on the brief: update brief.md and brief-summary.md, record
again, re-run the planner before showing the stop again. On approval: `bf approve`.
