---
name: buildflow
description: Build a large feature in an existing project, from brainstorm to accepted code. Reads the repo first, agrees a brief with the user, designs and prototypes when the feature has UI, then builds small ordered checkpoints that each have to pass hard quality gates (behavior tests, the project's own linters, type checks, SAST, secret and dependency scans, UI review against the prototype, adversarial code review, documentation), then a documentation gate for the whole feature and a human review. Design and docs are changes to the project's existing documentation, built on its existing stack. One orchestrator delegates every job to fresh-context subagents, shows everything in a viewer, and reports quality, tokens, cost and time after every checkpoint and at the end. After Shopify's Helix. Use when the user types /buildflow.
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

You are the **orchestrator**. You turn one big feature into small checkpoints, run each
checkpoint through its gates with subagents, keep the run state in `bf.py`, and report.
You do not write feature code or tests yourself: every build, test and review job goes to
a subagent with a fresh context window. That keeps your context small and every worker
focused, which is the whole point of the method.

An attempt is allowed to be wrong. It is not allowed to ship until it isn't.

## Language: the run's language, from the first message

Everything the human reads is in the run's language (`lang`), starting with your very
first reply, before `bf init` exists: chat messages, AskUserQuestion questions and
options, the intake choice, the brainstorm, summaries, checkpoint and final reports,
brief.md (with the headings from `references/brief.md` for that language) and the plan
texts. When the user writes Dutch (or passes `--lang nl`), run `bf init ... --lang nl`
and ask the intake questions in Dutch; `--lang` overrides what you infer. Before a run
exists, `bf` follows `BUILDFLOW_LANG`, so for Dutch prefix the pre-init calls (`bf runs`,
`bf static detect`) with `BUILDFLOW_LANG=nl`. After init, `bf` itself prints status,
next steps, refusals and reports in the run's language and the viewer follows it.

Tell every subagent the run language in its context block. Whatever a subagent writes
that ends up in `bf` and in front of the human (gate `--summary`, finding titles, failure
reasons, planned test names and scenarios, docs-gate notes) is in the run's language.
Commands, file paths, code, JSON keys and gate keys stay as they are. This file stays in
English; it is written for you, not for the user.

The flow, and where you stop for the human:

| phase | what happens | stop |
|---|---|---|
| 0 intake | read the repo: project context (reused) and feature context | no |
| 1 brief | brainstorm with the user, write brief.md | **yes: approve the brief** |
| 2 design | only when the feature changes what users see and no approved design exists: design.md, prototype, design review | **yes: approve the design** |
| 3 plan | checkpoints and test plan | **yes: approve the plan** |
| 4 build | every checkpoint through its gates (behavior, static, UI, review, docs) | no |
| 4b docs | the feature docs gate: documentation of the feature as a whole | no |
| 5 review | the user tries the feature | **yes: accept or give feedback** |

Between stops everything runs on its own. A Stop hook enforces this: while the run is in
phase `building` or `documenting` and gates are open, you cannot end your turn.

Documentation is part of the work. Design files, prototype pages and docs are changes to
the project's own documentation, in its own places and formats, committed with the
feature: update what exists, add only what is missing. And when the project already has
a stack, especially a front-end stack, the design is expressed in it. In `--auto`
mode you approve the brief, design and plan yourself with `bf approve --note auto` after
showing them; the gates stay exactly as strict, and phase 5 still waits for the human.

## The tool

Every state change goes through one script. Shell state does not persist between Bash
calls, so always write the full command:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/bf.py <command>
```

Below, `bf` means exactly that. `bf status` tells you where you are and what to do next;
run it whenever you are unsure, and always after a context compaction. The full command
and JSON reference is in `${CLAUDE_SKILL_DIR}/references/state-and-commands.md`. Read it
once at the start of a run.

## The live viewer and the stops

At every stop (brief, design, plan, review) the user can answer in chat or in the live
viewer in the browser. Both count. The browser never changes the run itself: it drops
approvals and feedback in an inbox, and you act on them with the same `bf` commands as
for a chat reply. At each stop:

1. `bf serve --status`. If it is not running: `bf serve --detach` (starts in the
   background and prints the URL).
2. Give the user the `http://127.0.0.1:<port>/viewer.html` URL it prints, not a file path.
   `http://127.0.0.1:<port>/` is the overview of all runs and the product's features.
3. Start `bf wait --timeout 3600` with `run_in_background`, so a click in the browser
   wakes you. Then end your turn.

Everything that matters is in `.buildflow/<slug>/state.json`, so a stop is also a good
moment to shed context: suggest `/compact`, or, for a longer wait, a new session with
`/buildflow` that resumes with `bf status` (`bf brief-context` for the short version).

Remote access (phone, other machine) only when the user asks for it. The server stays on
127.0.0.1; the user puts a proxy in front and you allow that one host name. Suggest they
run `tailscale serve --bg --http=<port> http://127.0.0.1:<port>` themselves (don't run
it for them), then restart the server with their tailnet name:
`bf serve --detach --allow-host <machine>.<tailnet>.ts.net` (stop the old pid first; an
already running server keeps its host list). Give them `http://<that name>:<port>/viewer.html`.
Never pass wildcards or hosts the user didn't name.

When you wake up (the wait finished) or the user replies in chat: `bf inbox` shows what
came in from the viewer. For each item:
- `approve` → `bf approve --note "via viewer"` (this also marks the item handled);
- `feedback` → handle it exactly like chat feedback at that stop (`target` names the
  checkpoint it is about);
- `accept` → `bf accept`;
- `message` → read it and act on it.

Then `bf inbox handled <id> --note "<what you did, in a few words>"`; the user sees the
note in the viewer. If the wait exited 3 (timeout), start it again silently. A newer
`bf wait` replaces an older one, so starting one twice does no harm.

During the build, run `bf inbox` after every checkpoint (the Stop hook also lists
unhandled items). Mid-build feedback is handled at the next checkpoint boundary, unless
it asks you to stop or pause; then do that first. `bf status` names pending items too.
Open the static `viewer.html` file only when no server can run; it keeps the "Copy
feedback" button for pasting into chat.

`bf` refuses illegal moves (starting to build before the plan is approved, passing a gate
while an earlier one is open, passing behavior with failing tests, passing a gate or the
design review with open blocker/high findings, passing review, UI or docs with a medium
finding that is neither fixed nor had a fix round nor has a reason, passing static while a new blocking finding
is open or on code that changed since the last run, finishing a checkpoint with open gates,
starting checkpoint 3 before 2 passed). Do not work around a refusal; it means the work
is not done.

## Subagent naming is not optional

Every Agent call you make in a run gets a `description` that starts with a tag:

```
bf:<scope>:<role> <short text>        e.g.  bf:cp03:implement leave approval rules
```

`scope` is `context`, `brief`, `design`, `plan`, `cpNN` or `final`. Roles: `project`,
`feature` (context scouts), `system`, `prototype`, `review` (design), `health`, `planner`,
`tests-plan`, `tests`, `implement`, `verify`, `static-fix`, `ui-review`, `ui-visual`, `ui-behavior`, `ui-fix`,
`adversary`, `fixer`, `docs`, `docs-review`, `feedback`, `runner` (one checkpoint end to end, see Phase 4). The
cost report attributes tokens by this tag. Untagged subagents still get counted, but land in one anonymous
bucket.

## Models: the run's profile decides

Every run has a model profile, set with `bf init --profile` and shown in `bf status`, the
viewer and the reports:

| profile | planner, adversary | health, verify (pure test runs) | every other role |
|---|---|---|---|
| `lean` (`zuinig`, default for new runs) | session model | `haiku` | `sonnet` |
| `thorough` (`grondig`) | session model | `sonnet` | session model |

Before every Agent call, set its `model` field from `bf model <role>` (`bf model` prints the
whole table). `inherit` means: leave `model` out, so the subagent runs on the session model.
The chosen profile is the user's permission for these models; you do not ask again. Use
`thorough` when the user asks for it, or picked it for an earlier run in this project.

Escalation: when the implementer has failed the same gate twice in a checkpoint,
`bf model implement --cp cpNN` returns `inherit` for the next attempt (it counts the
failed attempts on the behavior gate; pass `--gate` for another one). So record every
failed attempt with `bf gate ... failed`, and ask `bf` again before each new implement run.
Runs created before profiles existed count as `thorough`.

## What every subagent gets

The project is the ground truth. Every subagent prompt starts with a context block, then
the role prompt from `references/`:

```
Feature: <title> — <goal>
Language: <nl|en>. Write every text a person will read (summaries, findings, test names,
scenarios) in this language; code, paths and JSON keys stay as they are.
Read these first, in this order, before doing anything else:
1. .buildflow/<slug>/learnings.md          (rules from earlier feedback; they override your habits)
2. .buildflow/<slug>/brief.md              (what we build and why; the contract)
3. .buildflow/<slug>/context-feature.md    (what in this codebase the feature touches)
4. .buildflow/context.md                   (project conventions, architecture, tests, UI)
5. <design reference, when relevant>       (approved prototype + states, design.md)
Project facts: test command, how to run one test, dev URL, review standard files.
Checkpoint (when applicable): id, title, summary, done_when, ui_scope, planned tests.
```

Leave out what does not exist yet (no brief during intake). Two exceptions: UI reviewers
in gate 2 get only the reference, the URL and the ui_scope, never the project
instructions, so they judge what they see. Ask each subagent to end with a JSON block in
the shape its reference file specifies, so you can feed it straight into `bf`.

`bf prompt <scope> <role> [--cp cpNN] [--extra-file f]` composes this whole prompt for you
(context block, checkpoint facts, the role's own prompt from `references/`, the UI-reviewer
isolation applied automatically) and writes it to `.buildflow/<slug>/prompts/<scope>-<role>.md`.
It prints the path, the `bf:<scope>:<role>` tag for the Agent call's `description`, and the
model from `bf model <role>`. Start the subagent with just: "Read `<path>` and follow it."
This keeps your own context free of everything the subagent needs but you do not.

## Phase 0: intake

1. Parse `$ARGUMENTS`: `--brief <file>` (a finished spec replaces the brainstorm),
   `--auto`, `--lang` (language of everything the human reads; default the language the
   user writes in). Decide the language now: this message and every question after it
   are already in that language (see "Language" above).
2. Choose what this run is. A project can hold many features; `bf runs` lists every run
   (phase, checkpoints, cost, dates), and the `## Features` section of
   `.buildflow/context.md` lists what the product already has. Read both, then ask the
   user in one AskUserQuestion batch to pick:
   - **continue an open run** (name them): `bf use <slug>`, then `bf status` and go on from
     its next step (for a paused run, `bf resume`);
   - **extend or change an existing product feature** (name the likely ones): a new run
     whose feature scout starts from that feature's entry (its code, docs and earlier run);
   - **a new feature**;
   - **only look at a finished run**: `bf use <slug>`, `bf serve --detach`, give the overview URL
     (`http://127.0.0.1:<port>/`) and that run's final-report numbers, and stop there.

   Skip the question when `$ARGUMENTS` already makes the choice obvious (a clear new
   feature, or "continue"), and say in one line which choice you made. When there are no
   runs and no Features section yet, it is simply a new feature.
3. Git: the tree must be clean (ask what to do if not). Create and switch to branch
   `buildflow/<slug>`.
4. `bf init --title "<short feature name>" --goal "<one-paragraph goal>" --lang <nl|en> --mode <interactive|auto> --profile <lean|thorough> --session ${CLAUDE_SESSION_ID}`.
   The profile is `lean` unless the user asked for `thorough` (see "Models" above).
   `bf init` refuses while another run is unfinished; if the user chose to leave that one
   for now, add `--park` (it pauses the old run, which can be resumed later). For an
   extension, name the existing feature in the goal. If a `bf serve` of an earlier run is
   still running, `bf serve --status` reports "not running" for the new run and
   `bf serve --detach` starts a fresh one on the next free port.
   Run it from the project root. When this session was started in a different folder than
   the project (the user wants the feature in another repo), add `--root <project>` and
   `--redirect-from <session folder>`, so the Stop hook still finds the run.
5. Prices: fetch the current prices from Anthropic's pricing page (WebFetch; `bf.py pricing`
   shows the source URL and what is currently recorded), compare them to `bf.py pricing`,
   fix any difference with `bf.py pricing --set <model> input=.. output=.. cache_read=..`,
   then `bf.py pricing --verified`. When the fetch fails (no network, page changed), say so
   in one line and move on; the cost report then names the date of the last verification.
6. Context (`references/context-scout.md`). `bf context --check`, then in parallel:
   - `bf:context:project` if the project context is missing or stale;
   - `bf:context:feature` always (for an extension, give it the chosen feature's entry).
   Give the project scout the output of `bf static detect` (installed linters, scanners,
   config files, what CI runs, zero-install runners).
   Record: `bf context --project .buildflow/context.md --feature .buildflow/<slug>/context-feature.md`
   and the facts the gates need: `bf project test_command="..." dev_command="..." dev_url="..." design_ref="..." review_standard="..."`,
   plus the proposed deterministic checks: `bf static config --file .buildflow/static.json`
   (`references/gate-static.md`; the file is shared between runs like the project context).
   Also start `bf:plan:health` in the background: install, build, run the tests, start the
   dev server, report the baseline. Failing baseline tests are not yours to fix silently;
   they go into the brief as a constraint.
7. `bf phase brief`.

The project context is shared between runs, so the second feature in the same repo
starts much faster. It covers what the repo already is; the feature context covers what
this feature touches. When you are working in a folder that is not a git repo, the same
applies; the staleness check then only looks at age.

## Phase 1: brief

Follow `references/brief.md`. You run the brainstorm yourself, with the feature context
at hand, so you never ask what the code can answer. It ends with `bf brief --file ...`,
the live viewer URL, a five-line summary in chat, and **the brief stop** (see "The live
viewer and the stops"). On approval: `bf approve`.

With `--brief <file>`: check the spec against the brief's questions, ask only about real
gaps, then `bf brief --file <spec> --given` (counts as approved, no stop).

## Phase 2: design (only when relevant)

Follow `references/design.md`. First decide and record `bf design needed|not-needed
--reason "..."`. Not needed (no visible change, or an approved design already covers
it): straight to planning. Needed:
- design.md changed in place (or, when the project has none, extracted from the app into
  the project's docs), written in the stack's own tokens and components;
- prototype pages in the project's prototype location, built on the project's front-end
  stack (Storybook stories, or static pages loading the app's real CSS), with every state
  the brief implies and a component map;
- a design review loop that also checks stack fit;
- `bf design ready ...` (it refuses paths under `.buildflow/`), and **the design stop**
  (live viewer URL, `bf wait` in the background).
On approval: `bf approve` and commit the design docs.

## Phase 3: plan

In parallel if not done yet: the health check (from phase 0) must be back.

- `bf:plan:planner` with `references/checkpoint-planner.md`. It may come back with
  questions instead of a plan. Ask the user those (AskUserQuestion, one batch), then send
  the answers back to the planner (SendMessage) and let it finish.
- `bf plan --file .buildflow/<slug>/plan.json`. It warns (never refuses) when a small
  project gets more than 5 checkpoints, when a UI gate has no `ui_scope`, and it skips the
  docs gate of a checkpoint without `docs_scope`. Take a warning back to the planner
  unless it gave a reason.
- `bf:plan:tests-plan` with `references/test-planner.md` writes `tests.json`: per planned
  test a behavior scenario in Given/When/Then form in the run's language (nl:
  Gegeven/Als/Dan), its kind (unit, integration, e2e, ui-gate) and the `done_when` item it
  proves. Then `bf tests --file .buildflow/<slug>/tests.json`; it reports tests without a
  scenario and done_when items without a test. Fix those with the test planner before the
  stop: the scenarios are how the human reviews "done" at the plan stop.

**The plan stop.** `bf phase awaiting_plan_approval`, then the live viewer steps (URL,
`bf wait` in the background). In chat, give the plan in a few lines: the checkpoints in
order (one line each), the number of scenarios per checkpoint (and one example scenario
for the riskiest one), which ones get the UI gate and which prototype states they cover,
the deterministic checks that will run (and which go through a zero-install runner such as
`uvx semgrep`, and what is not available), questions and assumptions. Tell the user they can reply with changes in chat, or comment
per checkpoint and approve in the viewer. End your turn.

On feedback: send it to the planner (new `bf:plan:planner` run with the old plan and the
feedback), reload with `bf plan --file`, re-run the test planner for changed checkpoints,
show the viewer again. On approval: `bf approve`, then `bf static baseline` on the clean
tree, so findings that were already there never block a checkpoint (`bf start` refuses
without it while checks are configured).

## Phase 4: build, one checkpoint at a time

For the next checkpoint (always the one `bf status` names):

`bf start cpNN`

**Lean (default): hand the whole checkpoint to a runner.** Start one `bf:cpNN:runner`
(`references/checkpoint-runner.md`, model from `bf model runner`) and let it drive `bf
start`/`bf gate`/`bf finish` and its own subagents (via `bf prompt`) through every gate
below. It reports back only a report path and a five-line summary — read that instead of
the gates in this section. **Thorough** keeps the orchestrator driving each gate itself,
as written below (also what a runner does internally).

If a runner stops halfway (crash, ran out of turns, a real decision it would not guess
on), `bf status` shows exactly which gate is still open on that checkpoint; start a fresh
runner for the same `cpNN` rather than trying to reconstruct what happened from its
transcript.

### Gate 1: behavior
Details and prompts: `references/gate-behavior.md`.
1. `bf gate cpNN behavior running`
2. `bf:cpNN:tests` writes the planned scenarios as tests (one per scenario, the planned
   name). Run them: they must fail, and fail for the right reason (missing behavior, not
   a syntax error or broken import).
3. Record the red run right away, with the test writer's reply:
   `bf gate cpNN behavior running --data '{"red":{"tests_new":K,"red_confirmed":true,"failure_reasons":["<test>: <why>"]}}'`.
   Wrong reason: record it (`"red_confirmed":false`) and send the tests back first.
4. `bf:cpNN:implement` writes the code until those tests pass, without editing the tests.
5. Run the full test command yourself (or `bf:cpNN:verify` if the suite is slow or noisy).
   Earlier checkpoints' tests must stay green.
6. Record the green run with evidence:
   `bf gate cpNN behavior passed --summary "..." --data '{"metrics":{"tests_total":N,"tests_passed":N,"tests_failed":0,"tests_new":K}}'`
   On failure: `bf gate cpNN behavior failed --summary "<what failed>"`, give the failure
   output to a new implement run, and go again.

### Gate 1b: static (deterministic checks)
Details and the fixer prompt: `references/gate-static.md`.
1. `bf static run cpNN`: runs the approved checks (on the changed files where the tool
   takes paths), subtracts the baseline and prints the new findings. A tool that crashes
   or times out is a finding too.
2. No new blocking finding: `bf gate cpNN static passed`. Otherwise record `failed`, give
   the findings to `bf:cpNN:static-fix`, run the tests, and `bf static run cpNN` again.
   A finding that is wrong: `bf static mark cpNN <id> wontfix --reason "..."`.
3. Skipped only when the plan says so (`static_skip_reason`, no code changed) or no tools
   are available. After review or docs fixes, `bf static run cpNN` again before the commit;
   `bf finish` checks that the static result matches the committed code.

### Findings: only blocker and high buy another review round
Gates 2, 3 and 4 share one rule for what a finding costs:
- **blocker/high**: fixed, then a **new** reviewer checks again. The only reason for another
  review round.
- **medium**: one fix round (the fixer handles all mediums at once), then the tests, and the
  gate is done without a new review. Record each medium as `fixed`, or `wontfix` with a
  `reason`, and `"metrics":{"fix_rounds":1}`.
- **low/nit**: no fixer. Record them as `open` (or `wontfix`); they go into the report.
`bf` refuses a pass with an open blocker/high, and with a medium that is not fixed unless
the gate recorded a fix round or the finding has a `reason`.

### Gates parallel: UI and adversarial review together
Once behavior and static have passed, gate 2 (UI) and gate 3 (review) do not depend on
each other, only on those two: `bf gate cpNN ui running` and `bf gate cpNN review running`
may both be open at once, so start the UI reviewer(s) and the adversary in parallel
instead of waiting for one to finish. If either one leads to a fix, re-run the tests, and
re-run the other gate too, but only if the fix touched what it looks at (a UI fix that
only changed markup does not need a new adversary pass, and vice versa).

### Gate 2: UI (only when the checkpoint changes something visible)
Details and prompts: `references/gate-ui.md`.
1. Make sure the dev server runs (start it in the background if needed).
2. `lean`: one `bf:cpNN:ui-review` checks both how it looks and how it behaves.
   `thorough`: `bf:cpNN:ui-visual` and `bf:cpNN:ui-behavior` in parallel. They get only the
   reference (prototype and/or design file), the URL, the checkpoint's `ui_scope`, and a
   screenshot folder `.buildflow/<slug>/evidence/cpNN/`. They do **not** get CLAUDE.md or
   the implementation plan: they judge what they see against the reference, nothing else.
3. A comparison marked INVALID (states did not match) is re-run, not counted. Fixable
   differences go to `bf:cpNN:ui-fix` by the findings rule above.
4. Pass when no blocker/high difference is open. Record all findings with their status.

### Gate 3: adversarial review
Details and prompts: `references/gate-review.md`.
1. `bf:cpNN:adversary` reviews the checkpoint diff (`git diff <checkpoint start>..`)
   against the review standard, the learnings and the checkpoint's done_when, with the
   static results (`evidence/cpNN/static.json`) so it does not repeat what the tools found.
   It assumes the code is wrong and tries to prove it.
2. No blocker/high: handle mediums with one fixer round, record `passed`. With blocker/high:
   `bf:cpNN:fixer` fixes the findings (or argues a specific finding is wrong, with evidence),
   tests run again, the UI gate runs again if anything visible changed, and a **new**
   adversary run reviews again with the previous findings attached. Loop until no
   blocker/high is left (max 4 rounds, then pause and ask). After fixes, `bf static run cpNN` again.

### Gate 4: docs (only when the checkpoint has a docs_scope)
Details and prompts: `references/gate-docs.md`.
1. `bf:cpNN:docs` updates the project documentation for this checkpoint's change, in
   place and in the project's format, guided by the checkpoint's `docs_scope`.
2. `bf:cpNN:docs-review` checks every changed statement against the code, completeness,
   placement and consistency; the findings rule above decides whether a new reviewer
   comes. In `lean`, a small docs_scope (one file, only factual updates) gets the writer's
   own check against the code instead of a reviewer. The feature docs gate always has one.
3. Record with the files: `bf gate cpNN docs passed --file .../docs.json`.

### Close the checkpoint
1. Commit: `git add -A && git commit -m "buildflow(cpNN): <title>"`.
2. `bf finish cpNN`. This writes the checkpoint report (markdown + HTML), refreshes costs
   and the viewer, prints the report, and ends with a line saying context can now be
   compacted (`/compact`). Everything that matters lives in `.buildflow/<slug>/state.json`,
   so nothing is lost: propose `/compact` to the user, or, for a longer break, a new
   session with `/buildflow` that opens with `bf status` (or `bf brief-context` for a
   short version) to pick up exactly where this one left off.
3. Post the checkpoint report in chat (format in `references/reporting.md`). Then go
   straight to the next checkpoint. Do not wait for a reply.

If a gate fails 4 times, `bf` pauses the run. Ask the user one concrete question with your
recommendation. Pausing for a real decision is fine; pausing because the work is hard is not.

### Independent checkpoints in parallel (lean profile, optional)
When `depends_on` allows it and two checkpoints' `files_hint` do not overlap, you may build
them at the same time: a runner per checkpoint, each in its own git worktree, merged back
in plan order once both finish (never two runners in the same worktree). Rules:
- only when neither checkpoint's `files_hint` names a file the other also names;
- `bf start` accepts at most 2 checkpoints started this way at once: `bf start cpNN --parallel`
  refuses a third, and refuses when the `files_hint` overlap is not empty.
This is the exception, not the default — most plans are ordered because later checkpoints
build on earlier ones; use it only for genuinely separate slices (e.g. two independent API
endpoints).

## Phase 5: human review

When the last checkpoint finishes, `bf finish` moves the run to `documenting`. Run the
**feature docs gate** (`references/gate-docs.md`): a writer makes the documentation of the
feature complete as a whole (overview, changelog, cross-links, prototype and design.md in
line with what was built, ADR if relevant), a reviewer checks it against the code and the
brief, loop until approved, commit, `bf docs --status passed`. That writes the final report
and moves the run to `awaiting_human_review`.

**The review stop.** The live viewer steps (URL, `bf wait` in the background); the final
report is at `.buildflow/<slug>/reports/final.html`, linked from the viewer. In chat: the final report summary (see
`references/reporting.md`), exactly how to try the feature (command, URL, test account,
the paths to click), and what you want them to look at. End your turn.

When the user comes back (in chat, or `bf wait` woke you and `bf inbox` shows it):
- Feedback: for each point, `bf learn "<the lesson, phrased as an instruction>"` (add
  `--project` if it holds for future features too). Turn the fixes into small checkpoints
  (a `bf:final:feedback` planner run for anything non-trivial) and load them with
  `bf feedback --text "<their words>" --file feedback-cps.json`. That puts the run back in
  `building`; run the new checkpoints through all gates as usual. The review stop again after.
  When feedback changes the problem or the approach rather than details, update brief.md
  (and the prototype) first and say so; do not bolt a different feature onto the plan.
- Accepted: `bf accept`. This closes the run and writes the final report. Post it. Offer
  to open a PR, and offer to publish the final report as a private Artifact so it can be
  shared (see "Sharing" in `README.md`).

## Interruptions and resuming

A rate limit or API error ends your turn without the Stop hook; the StopFailure hook
records it as an interruption and marks every gate attempt that was running as
`interrupted`. A crash or closed laptop leaves no trace, so check yourself.

An interruption is not a pause: the run stays in its phase and the viewer shows it as a
notice ("interrupted at 14:32 (rate limit)"). The next successful turn or `bf` state change
marks it resumed.

Whenever you wake up after an interruption (task notification, user message, new session,
compaction): run `bf status` first.
- A gate shown as `interrupted` whose subagent is still running or already finished:
  `bf resume --running cpNN:<gate>` (continues the same attempt), then record its result.
  If the subagent is gone: `bf resume --redo cpNN:<gate>` and redo that step with a fresh
  subagent. Never record a result you did not see.
- A gate still `running` while you know the session broke off: run
  `bf interrupted cpNN <gate> --reason "..."` so the report shows it, then redo the step.
- In a new session, register it: `bf session ${CLAUDE_SESSION_ID}` (the hook also does
  this at the end of your first turn).

Time in the reports is measured from transcript activity: any silence longer than
10 minutes (`BUILDFLOW_IDLE_GAP_MIN`) counts as idle, not as build time, and time in the
waiting phases counts as waiting on the human. You do not need to pause the run for a
rate limit to keep the numbers honest.

## Rules

- Docs are part of done. Change existing documentation rather than adding parallel files,
  never write a claim you did not verify in the code, and keep design.md and the
  prototype true to what was built.
- Tests are the spec. Never weaken, skip or delete a test to get a gate green. If a
  planned test is wrong, say so, fix the test plan, and record it in the gate summary.
- No gate is passed without evidence: test counts, screenshots, reviewer verdicts. Put
  paths to evidence in `--data '{"evidence":[...]}'`.
- Every finding is recorded, including the ones you decide not to fix
  (`"status":"wontfix"` with the reason in the title). Nothing disappears quietly.
- Learnings are how the loop improves. When the same kind of finding comes back in a
  second checkpoint, add a learning.
- Keep your own context lean: give subagents file paths, not file contents; ask them for
  short structured results, not narratives.
- The Stop hook blocks ending the turn during `building`. If you really need the human
  mid-build, run `bf pause --reason "..."` first, then ask.
- Background subagents: when you are waiting on them, ending the turn is fine; the hook
  lets you and you will be woken when they finish.
- Model choice follows the profile: `bf model <role>` for every Agent call (see "Models").
  The profile the run started with is the permission; do not switch models outside it
  without asking, except the implementer's escalation that `bf model` reports.
