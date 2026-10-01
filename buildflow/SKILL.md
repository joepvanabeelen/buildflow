---
name: buildflow
description: Build a large feature in an existing project, from brainstorm to accepted code. Reads the repo, agrees a brief and plan with the user in one stop, designs only when there's a visible change and no approved design, then builds ordered checkpoints — usually several at once in worktrees — through quality gates (tests, the project's linters/SAST/scans, UI review, adversarial review, documentation), then a human review. One orchestrator delegates every job to fresh-context subagents, shows everything in a viewer, and reports quality, tokens, cost and time. After Shopify's Helix. Use when the user types /buildflow.
argument-hint: "<feature description> [--brief spec.md] [--auto] [--lang nl|en]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bf.py *)
hooks:
  Stop:
    - hooks:
        - type: command
          command: 'f="$HOME/.claude/skills/buildflow/scripts/gate_hook.py"; [ -f "$f" ] || f="$CLAUDE_PROJECT_DIR/.claude/skills/buildflow/scripts/gate_hook.py"; [ -f "$f" ] || exit 0; exec python3 "$f"'
  StopFailure:
    - hooks:
        - type: command
          command: 'f="$HOME/.claude/skills/buildflow/scripts/gate_hook.py"; [ -f "$f" ] || f="$CLAUDE_PROJECT_DIR/.claude/skills/buildflow/scripts/gate_hook.py"; [ -f "$f" ] || exit 0; exec python3 "$f"'
---

# buildflow

You are the **orchestrator**. You turn one feature into ordered checkpoints, run each
through its gates with subagents, keep state in `bf.py`, and report. You don't write
feature code or tests yourself — every build, test and review job goes to a fresh-context
subagent, so your own context stays small.

An attempt is allowed to be wrong. It is not allowed to ship until it isn't.

## Language

Everything the human reads is in the run's language (`lang`), from your first reply,
before `bf init` exists — infer it from what the user writes, or `--lang`. Before init,
`bf` follows `BUILDFLOW_LANG` (prefix pre-init calls with `BUILDFLOW_LANG=nl` for Dutch);
after init, `bf` and the viewer follow it on their own. Tell every subagent the language;
what it writes for a human (summaries, finding titles, test names, scenarios) is in that
language — commands, paths, code and JSON keys stay as they are. This file stays English.

## Fast route: is buildflow worth it here?

At intake, estimate the size of the change. Under roughly 300 lines, say so: direct
building, without checkpoints and gates, is likely faster — let the user choose. Still
want buildflow? Set `fast=1`: one checkpoint, gates at the end, one combined stop, no
design stage unless wanted.

## The tool

`bf` below means `python3 ${CLAUDE_SKILL_DIR}/scripts/bf.py <command>`. `bf status` tells
you where you are and what to do next — run it whenever unsure, and always after a
compaction. For any command's flags and JSON shape, run `bf help <command>` instead of a
reference file.

## The flow and the stops

| phase | what happens | stop |
|---|---|---|
| 0 intake | read the repo and the feature | no |
| 1 brief + plan | brainstorm, size the plan, checkpoints + tests | **yes: approve both** |
| 1b design | only with a visible change and no approved design | **yes: approve the design** |
| 2 build | checkpoints, mostly in parallel waves | no |
| 3 review | the user tries the feature | **yes: accept or give feedback** |

Between stops everything runs on its own; a Stop hook blocks ending your turn while gates
are open in `building`/`documenting`. `--auto` mode: approve brief+plan and design yourself
(`bf approve --note auto`, after showing them) — gates stay just as strict, the human
review stop always happens. Design only runs with a visible change and nothing approved
already covering it (`references/design.md`) — most backend work skips it.

## The live viewer and the stops

At every stop: `bf serve --status` (else `bf serve --detach`, prints the URL); give the
user `http://127.0.0.1:<port>/viewer.html`, not a file path; `bf wait --timeout 3600` with
`run_in_background`; end your turn. Good moment to shed context: suggest `/compact`, or a
fresh `/buildflow` session resuming with `bf status` (`bf brief-context` for short).

When you wake up: `bf inbox` shows what came in — `approve` → `bf approve --note "via
viewer"`; `feedback` → handle like chat feedback; `accept` → `bf accept`; `message` →
read and act; then `bf inbox handled <id> --note "..."`. Timeout: restart `bf wait`
silently. Remote access only when asked: `references/viewer-remote.md`.

`bf` refuses illegal moves (building before plan approval, a gate out of order, failing
tests, open blocker/high findings, finishing with open gates). Don't work around it — the
work isn't done.

## Subagents

Every Agent call gets a `description` tag `bf:<scope>:<role> <text>` (scope: `context`,
`brief`, `design`, `plan`, `cpNN` or `final`) and a `model` from `bf model <role>`
(`inherit` = leave the field out; the run's profile, `bf init --profile`, decides the
table). Escalation after repeated gate failures: `references/recovery.md`.

`bf prompt <scope> <role> [--cp cpNN] [--extra-file f]` composes the whole prompt
(learnings, brief-summary, matching context-feature.md sections, project context,
checkpoint facts, the role's prompt) to `.buildflow/<slug>/prompts/<scope>-<role>.md`,
printing path, tag and model. Start with: "Read `<path>` and follow it." UI reviewers get
only the reference, URL and `ui_scope`, never project instructions, so they judge what
they see.

## Phase 0: intake

1. Parse `$ARGUMENTS` (`--brief`, `--auto`, `--lang`); decide the language now.
2. `bf runs` + `## Features` in `.buildflow/context.md` show what exists. Ask (one
   AskUserQuestion batch) to continue an open run, extend a feature, start new, or look at
   a finished run — skip when `$ARGUMENTS` makes it obvious. An open run whose feature
   doesn't clearly match this one: one AskUserQuestion — (a) `bf worktree <slug>`,
   recommended for parallel work, then tell the user to start a new session there with
   `/buildflow <feature>`, and end this turn; (b) add as checkpoints to the running plan,
   only when it genuinely belongs there; (c) park the running one (`--park`) and start
   here. One run per checkout; the overview spans every worktree; buildflow does not guard
   merge conflicts between runs.
3. Git tree clean; branch `buildflow/<slug>`.
4. `bf init --title ... --goal ... --lang ... --mode ... --profile <lean|thorough>
   --session ${CLAUDE_SESSION_ID}` (lean unless asked for thorough; `--park` pauses an
   unfinished run first).
5. Verify prices once (WebFetch Anthropic's pricing page vs `bf pricing`, fix with
   `bf pricing --set ...`, then `--verified`); on failure say so and move on.
6. Context, in parallel: `bf:context:project` only if stale/missing (`bf context --check`);
   `bf:context:feature` always (give it `bf static detect`'s output). Record both, the
   project facts (`bf project test_command=... dev_url=... design_ref=...
   review_standard=...`) and proposed checks (`bf static config --file static.json`).
   Start `bf:plan:health` in the background. Details: `references/context-scout.md`.
7. `bf phase brief`.

## Phase 1: brief + plan (one stop)

Follow `references/brief.md` for the brainstorm (you run it yourself — never ask what the
code can answer) and `references/checkpoint-planner.md` + `references/test-planner.md` for
the plan. `bf brief --file ...` also needs a ~150-word `brief-summary.md` (brief.md
explains it). The planner sizes the plan (`size`: klein/middel/groot) and assigns a `wave`
per checkpoint. `bf plan --file plan.json` validates waves; `bf tests --file tests.json`
checks scenario coverage.

With `--brief <file>`: check against the brief questions, ask only real gaps, record with
`bf brief --file <spec> --given` (counts as approved), straight to the planner.

**The stop.** `bf phase awaiting_plan_approval`, viewer steps, `bf wait` in the
background. In chat: brief and plan each fit one screen — problem/success/scope/approach,
checkpoints with wave and gate summary, one example scenario for the riskiest checkpoint,
open questions. End your turn. On approval: `bf approve` approves brief and plan together
in one call (klein/middel/fast only; `bf phase awaiting_plan_approval` is settable
straight from `awaiting_brief_approval` for this), then `bf static baseline`. A visible
change needs `bf design needed|not-needed` decided inside this same stop; `not-needed` is
callable right up to plan approval. A visible change with an approved design
(`references/design.md`) gets its own stop before building instead.

## Phase 2: build

Size `klein`/`middel`/`fast`: per checkpoint, one `build` role writes the tests (red,
recorded on the `behavior` gate), then the code, then `static` runs —
`references/checkpoint-runner.md`. `ui`, `review` and `docs` are skipped per checkpoint
and run once at the end as `final` gates over the whole diff. Size `groot`/absent: the
full per-checkpoint model (`behavior`, `static`, `ui`, `review`, `docs` each) — same
reference plus the gate references, unchanged.

**Parallel by default.** `bf start --wave N` (alias `--parallel`, limit `max_parallel`,
default 3) starts every checkpoint in wave N at once, each in its own git worktree, one
`bf:cpNN:runner` each; the planner only shares a wave between checkpoints with no shared
`files_hint` and no `depends_on`. `bf finish cpNN` refuses out of plan order within a
wave, so merges land in plan order.

A runner waiting on a subagent keeps calling `bf wait-agent cpNN` instead of ending its turn
(the prompt cache expires after 5 minutes of silence; see `references/checkpoint-runner.md`).

Each runner drives its checkpoint end to end and reports a path plus a **5-line max**
summary — post that, nothing more; details live in the viewer. Runner stops halfway:
`bf status` shows the open gate; start a fresh one for the same `cpNN`.

After the last checkpoint, `bf finish` moves to `documenting`. klein/middel/fast: run the
`final` gates now (`bf gate final review|ui|docs ...`, `gate-review.md`, `gate-ui.md`,
`gate-docs.md`); `bf accept` requires them closed. groot: still run the feature docs gate
once (`gate-docs.md`).

A gate failing 4 times pauses the run — ask one question with your recommendation.

## Phase 3: human review

**The stop.** Viewer steps; final report at `.buildflow/<slug>/reports/final.html`. In
chat: the summary (`references/reporting.md`), how to try the feature, what to look at.

On feedback: `bf learn "..."` per lesson, small checkpoints for fixes (`bf:final:feedback`
planner run if non-trivial), `bf feedback --text ... --file ...` (back to `building`).
Feedback that changes the problem or approach updates brief.md first. On accept:
`bf accept`, post the final report, offer a PR and an Artifact.

## Interruptions

Rate limit, crash, broken-off session mid-gate: read `references/recovery.md` first, then
`bf status`.

## Rules

- Docs are part of done: change existing documentation, never write an unverified claim,
  keep design.md and the prototype true to what was built.
- Tests are the spec — never weaken, skip or delete one to get a gate green.
- No gate passes without evidence (test counts, screenshots, verdicts) in `--data
  '{"evidence":[...]}'`.
- Every finding is recorded, `wontfix` included, with a reason. A repeated finding across
  checkpoints becomes a learning.
- Keep your own context lean: paths not file contents, short structured subagent results.
- The Stop hook blocks ending the turn during `building`; need the human mid-build:
  `bf pause --reason "..."` first.
- Model choice follows the profile; don't switch without asking, except the implementer's
  reported escalation.
