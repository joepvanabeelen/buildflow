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
the user something the code can answer. Use what the scout found: "Leave requests already
exist in `src/leave/`, but only as a draft status. Is this feature about the approval
step on top of that?" is a good question; "Do you have a leave module?" is not.

## The conversation

Short rounds, a few questions at a time, each with your recommended answer and why. Use
AskUserQuestion when the options are clear, open questions when they are not. Stop
asking once the brief below can be written without guessing. Usually two or three
rounds.

1. **Problem**: what is going wrong or missing today, for whom, how often, and what it
   costs them. Push past the solution the user came with to the problem underneath.
2. **Users and situations**: who uses this, in which moments, on which devices, with
   which permissions.
3. **Success**: how we will know it works. Observable outcomes, not features. What does
   the user do differently afterwards?
4. **Scope**: what is in, and just as important what is explicitly out. What is the
   smallest version worth shipping?
5. **Approaches**: propose two or three genuinely different ways to solve it (different
   UX flows, a config option instead of a new screen, extending an existing feature
   instead of a new one). For each: what it looks like, what it costs to build, what it
   makes harder later. Recommend one and say why. Let the user choose or combine.
6. **Constraints and risks**: data, privacy, performance, migrations, other teams,
   deadlines, what must not break.
7. **Open questions** that stay open: write them down with who decides.

Keep the user's own words where they are precise. Do not pad.

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

Then `bf brief --file .buildflow/<slug>/brief.md`, make sure the live viewer runs
(`bf serve --status`, else `bf serve --detach`), and in chat give its URL and a five-line
summary (in the run's language): problem, success, scope, chosen approach, and whether a design step follows.
Tell the user they can reply with changes or approve, in chat or in the viewer. Start
`bf wait --timeout 3600` in the background and end your turn (SKILL.md, "The live viewer
and the stops").

On changes: update brief.md, record again with `bf brief --file ...`, show again.
On approval: `bf approve`.
