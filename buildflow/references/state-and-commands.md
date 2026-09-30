# bf.py reference

`bf` = `python3 ${CLAUDE_SKILL_DIR}/scripts/bf.py`. Run data lives in
`<project>/.buildflow/<slug>/`; `.buildflow/active` names the active run. The folder has
its own `.gitignore` (`*`), so run data is not committed unless you remove that file.

```
.buildflow/
  active                    slug of the active run
  index.html, overview.json overview of all runs + the product's existing features (rewritten on every change)
  context.md, context.json  project context, shared by all runs (+ when/at which commit it was written)
  static.json               the proposed deterministic checks (project scout), shared by all runs
  learnings.md              project-wide learnings (bf learn --project), copied into new runs
  <slug>/
    state.json              the run (source of truth)
    data.json               what the live viewer loads (rewritten on every state change)
    inbox.jsonl             approvals/feedback sent from the live viewer (only `bf serve` appends)
    inbox-status.jsonl      read/handled events + notes (only bf commands append)
    serve.json              port, pid and token of the running `bf serve` (never served)
    context-feature.md      what this feature touches in the codebase
    brief.md                the approved brief
    plan.json, tests.json   planner output as loaded
    static-baseline.json    findings of the checks before the feature (bf static baseline)
    learnings.md            every agent reads this first
  (design.md and prototype pages are NOT here: they are project documentation and live
   in the project's docs, committed with the feature)
    evidence/cpNN/          screenshots, review outputs, test logs; static.json + static-raw/ (bf static run)
    reports/cpNN.{md,html}  checkpoint reports
    reports/final.{md,html} final report
    viewer.html             self-contained viewer (open or share this file)
```

## Commands

| command | what it does |
|---|---|
| `init --title T --goal G --lang nl --mode interactive --profile lean --session ID [--park]` | new run, phase `intake`. `--lang` sets the language of everything bf shows a person (status, next steps, refusals, reports, viewer); without it `BUILDFLOW_LANG`, else `en`. `--profile` is `lean` (default) or `thorough`, also as `zuinig`/`grondig`; stored as `profile` in state.json. A run without `profile` counts as `thorough`. Refuses an existing slug (`--force` overwrites) and refuses while the active run is unfinished; `--park` pauses that run first |
| `runs [--json]` | every run in the project: slug, title, phase, checkpoints passed/total, cost, active time, dates, branch, reports; also rewrites `.buildflow/index.html` |
| `context --check` | project context missing / stale (why) / fresh |
| `context --project F --feature F` | record the context files (stamps the commit) |
| `brief --file F [--given]` | record the brief; waits for approval, or counts as approved with `--given` |
| `design needed\|not-needed --reason R` | design stage decision |
| `design review --status running\|passed\|failed [--summary] [--file F]` | record a design review round |
| `design ready --prototype P [--design-md D] [--states a,b]` | design reviewed, wait for approval; refuses paths under `.buildflow/` and paths that do not exist |
| `use <slug>` | switch the active run |
| `session <id>` | register another session id (after `/clear` or a new session) |
| `project key=value ...` | store project facts (test_command, dev_url, design_ref, prototype, review_standard) |
| `plan --file plan.json [--append]` | load checkpoints |
| `tests --file tests.json` | attach planned tests per checkpoint; reports how many have a Given/When/Then scenario and which done_when items have no test |
| `phase <phase>` | intake, brief, awaiting_brief_approval, design, awaiting_design_approval, planning, awaiting_plan_approval, building, documenting, awaiting_human_review, paused, done |
| `approve [--note]` | approve what is waiting: brief → design, design → planning, plan → building |
| `start cpNN [--force] [--parallel]` | start a checkpoint (refuses if an earlier one is open, unless `--parallel`: allows a second checkpoint in progress when its `files_hint` does not overlap the running one's, at most 2 at a time) |
| `gate cpNN <behavior\|static\|ui\|review\|docs> <running\|passed\|failed\|skipped> [--summary] [--reason R] [--data JSON\|--file F]` | record a gate attempt (`running` reopens a skipped gate; on an interrupted gate it continues the same attempt). `static skipped` needs `--reason`, and `--force` when checks are configured and the plan did not skip it. `ui` and `review` do not block each other: both may be `running` (or `passed`) at once, once `behavior` and `static` are done |
| `prompt <scope> <role> [--cp cpNN] [--extra-file F]...` | compose a subagent's whole prompt (context block + checkpoint facts + the role's prompt from `references/`, with the UI-reviewer isolation applied for `ui-visual`/`ui-behavior`/`ui-review`) and write it to `.buildflow/<slug>/prompts/<scope>-<role>.md`; prints the path, the `bf:<scope>:<role>` tag and the model from `bf model <role>` |
| `brief-context` | ~15 lines for a new session to resume from: phase, checkpoint, open gates, last feedback/learnings, next step |
| `static detect` | installed linters/scanners, their config files, package scripts, what CI runs, runners (uvx, pipx, docker); works before `init` |
| `static config --file static.json` / `static config --none --reason R` | record the check set (refuses install commands); `--none` when no tool can run |
| `static baseline [--allow-dirty]` | run every check on the clean tree and store what it finds; required before `start` while checks are configured |
| `static run cpNN [--timeout S]` | run the checks (changed files where the tool takes paths), subtract the baseline, write `evidence/cpNN/static.json`, mirror it into the gate attempt |
| `static mark cpNN <id>... wontfix --reason R` | accept a finding; kept across reruns. `fixed` is only set by a rerun. Secrets need `--force` |
| `static show [cpNN]` | the check set and baseline, or a checkpoint's static.json |
| `finish cpNN [--commit sha]` | close the checkpoint, write its report, print a line that context can now be compacted (`/compact`); after the last one the run moves to `documenting` |
| `docs --status running\|passed\|failed [--summary] [--file F]` | feature docs gate; `passed` writes the final report and moves to the human review |
| `feedback --text "..." [--file cps.json]` | human review round; new checkpoints put the run back in `building` |
| `learn "..." [--project]` | append a learning |
| `accept` | human accepted; run `done`, final report |
| `pause --reason "..."` / `resume` | explicit human decision point; `resume` ends a pause |
| `resume --running cpNN:gate` / `resume --redo cpNN:gate` | settle an interrupted gate: continue the same attempt (its subagent kept going) or open a fresh one (it is gone). Repeatable; without a value: every interrupted gate. Marks open interruptions resumed |
| `interrupted [cpNN gate] [--reason]` | record an interruption the hook missed (crash, closed laptop) and mark the running attempt |
| `status [--json]` | where are we, what is next; also the profile and which model each role gets |
| `model [role] [--cp cpNN] [--gate G] [--json]` | the model per subagent role in the run's profile; with a role only that value, for the Agent call's `model` field (`inherit` = leave the field out). With `--cp`, `implement` returns `inherit` after 2 failed attempts on the behavior gate (or `--gate`) while that gate is open |
| `cost [--json]` | tokens, cost and time from the session transcripts |
| `pricing` | show `pricing.json`'s table and when it was last verified |
| `pricing --check` | compare the models seen in this run's transcripts against `pricing.json`; names any without a price (those messages count as `unpriced_messages`) |
| `pricing --set <model> input=.. output=.. cache_read=.. [cache_write_5m=.. cache_write_1h=.. fast_multiplier=..]` | add or update a model's price |
| `pricing --verified` | record today as `pricing.json`'s `verified_at` |
| `report <cpNN\|final> [--open]` | (re)write a report |
| `viewer [--open] [--cost]` | render `viewer.html` |
| `serve [--port 8765] [--open] [--detach] [--allow-host <host>]...` | serve the live viewer on 127.0.0.1 (next free port from 8765); `--detach` starts it in the background and prints the URL (and passes `--allow-host` on); if one already runs it just prints its URL and warns when a requested host is not in its list |
| `serve --status` | JSON `{"running", "url", "overview_url", "port", "pid", "started", "allow_hosts", "remote_urls"}`; exit 1 when not running (a serve.json of a dead server counts as not running) |
| `inbox [--all]` | unhandled viewer items as JSON (marks new ones read); `--all` includes handled ones |
| `inbox handled <id>... [--note "..."]` | mark items handled; the note shows in the viewer |
| `wait [--timeout 3600]` | block until the viewer sends something new, print it as JSON (marked read), exit 0; exit 3 on timeout. Run it in the background at a stop. A newer wait replaces an older one |
| `doctor` | check setup, sessions and transcripts |

## The live viewer (`bf serve`)

`bf serve` binds to 127.0.0.1 only and serves the project root, so the viewer's links to
prototypes and docs work; dot folders (`.git`, other runs) and its own private files are
not served; from `.buildflow/` only `index.html`, `overview.json` and the run folders.
`/` redirects to the overview (`/.buildflow/index.html`), `/viewer.html` to
`/.buildflow/<slug>/viewer.html`. Every run viewer links back to the overview, also as
static files. On start it makes
a random token, writes it to `serve.json` and injects it into the served viewer page as
`<meta name="bf-token">` (never into `viewer.html` on disk). Redirects are host-relative
(`Location: /...`) and the pages use relative URLs, so everything also works through a proxy.

Requests must carry Host `127.0.0.1` or `localhost` (DNS-rebinding guard), plus any exact
names given with `--allow-host` (repeatable) or `BUILDFLOW_ALLOW_HOSTS` (comma-separated).
A value may include a port or scheme (`name:443`, `https://name`); only the lower-cased
host name is kept. Wildcards and single-label names are refused. The list is stored in
`serve.json` as `allow_hosts`. Intended for `tailscale serve --bg --http=<port>
http://127.0.0.1:<port>`, which the user runs; the server itself never binds anything but
127.0.0.1. An `Origin` header, when present, must be `http://` for the loopback names and
`http://` or `https://` for an allowed host.

| endpoint | |
|---|---|
| `GET /api/ping` | `{"ok", "slug", "phase"}` |
| `GET /api/version` | fingerprints of data.json and the inbox; the page polls this every 2 s and only reloads what changed |
| `GET /api/inbox` | items with status (token required) |
| `POST /api/action` | new item; needs header `X-BF-Token` and a loopback or allowed Host/Origin (else 403) |

A POST body is `{"type", "stage", "target", "text"}`. `approve` is accepted only in the
matching `awaiting_*` phase and `accept` only in `awaiting_human_review` (else 409
`wrong_phase`); a second approve/accept while one is unhandled gives 409 `duplicate`;
`feedback` and `message` need text (400); text is capped at 8000 characters (413). The
browser never writes state.json: `bf approve` and `bf accept` also mark the matching
viewer request handled.

An inbox item:

```json
{"id": "v3f9a2c", "at": "2026-09-29T15:27:45Z", "type": "feedback", "stage": "plan",
 "target": "cp02", "text": "Split rejecting into its own checkpoint",
 "phase_at_submit": "awaiting_plan_approval", "status": "read", "note": "..."}
```

`type`: approve, feedback, accept, message. `stage`: brief, design, plan, review,
checkpoint. `status`: new (sent), read (`bf inbox` or `bf wait` saw it), handled.

## plan.json (checkpoint planner output)

```json
{
  "checkpoints": [
    {
      "title": "Leave request form skeleton",
      "summary": "A page with the empty leave request form. Nothing is saved yet.",
      "why": "Gets routing, layout and the form component in place before any logic.",
      "done_when": ["The page opens from the menu", "The form shows the fields from the prototype"],
      "gates": ["behavior", "ui", "review", "docs"],
      "ui_scope": "Page header and the form card only",
      "docs_scope": "User help page 'Verlof aanvragen': new section on the form",
      "complexity": 1,
      "depends_on": [],
      "files_hint": ["src/pages/leave/"]
    }
  ],
  "questions": [{"q": "Can a manager approve their own leave?", "a": "No"}],
  "assumptions": ["Public holidays come from the existing holidays table"],
  "out_of_scope": ["Email notifications"]
}
```

`size` (optional but expected): `{"class": "small|medium|large", "est_lines": N}`. `bf plan`
warns when it is missing, and when a small project (class `small` or `est_lines` under
1500) has more than 5 checkpoints. It also warns about a `ui` gate without `ui_scope`.

`gates`: `behavior`, `static` and `review` are always added. A `docs` gate without a
`docs_scope` is skipped (reason "no docs_scope"). Leave `ui` out for logic-only
checkpoints and `docs` out when nothing documented changes; add `"ui_skip_reason"` /
`"docs_skip_reason"` to say why. `static` is skipped only with `"static_skip_reason"`
(the checkpoint changes no code). Gates run in the order behavior, static, ui, review, docs.

## tests.json (test planner output)

```json
{
  "cp01": [
    {"name": "shows the leave form to a logged-in employee", "kind": "integration", "done_when": 2,
     "scenario": {"given": "an employee who is logged in", "when": "they open /leave/new",
                  "then": "the form shows start, end and type"}}
  ]
}
```

`kind`: unit, integration, e2e, ui-gate. The scenario is written in the run's language
(nl: Gegeven/Als/Dan as words, keys stay `given`/`when`/`then`). Alternatives, all
optional and backward compatible: `gherkin` (multi-line `Given/When/Then/And` or
`Gegeven/Als/Dan/En`), the older one-line `given_when_then`, and `covers` ("done_when 2")
instead of `done_when`. Tests without any scenario still load; the viewer then shows only
their name, kind and covers.

## Language

Every sentence `bf` prints or writes for a person follows the run's `lang` (nl or en):
next steps, `bf status`, refusals, reports, the Stop hook's user message and every label
in the viewer. Commands, flags, gate keys (`behavior`, `static`, ...), JSON keys and
state values stay English; `bf status --json` and `bf inbox` are machine output. Before
a run exists, `BUILDFLOW_LANG` decides. Old runs keep what they stored; the viewer shows
the known English texts bf used to store (default skip reasons, static summaries) in
Dutch.

## gate --data / --file

```json
{
  "metrics": {"tests_total": 42, "tests_passed": 42, "tests_failed": 0, "tests_new": 6},
  "findings": [
    {"severity": "high", "title": "Approve endpoint does not check the approver is the manager",
     "location": "src/api/leave.ts:88", "status": "fixed"}
  ],
  "evidence": [".buildflow/leave/evidence/cp03/visual-1.png"]
}
```

Severities: `blocker`, `high`, `medium`, `low`, `nit`. Status: `open`, `fixed`, `wontfix`.
A finding may carry a `reason` (why it stays open or is not fixed); the reports show it.
`bf` refuses `passed` while a blocker/high finding is `open`; refuses it on ui, review and
docs (and `bf docs`) while a medium finding is not `fixed`, unless the gate recorded
`"metrics": {"fix_rounds": 1}` (or more) or that finding has a `reason`; and refuses a
behavior pass with `tests_failed > 0`. Low and nit may stay `open`. Recommended metrics per gate:

- behavior: `tests_total`, `tests_passed`, `tests_failed`, `tests_new`, `red_confirmed` (true when the new tests failed first).
  Plus the test-first evidence as top-level keys of `--data`: `"red": {"tests_new", "red_confirmed", "failure_reasons": [...]}`
  (or `{"tests", "failed", "right_reason", "failures": [{"test", "reason"}]}`), recorded with `gate cpNN behavior running`
  right after the test writer; and optionally `"green": {"tests_total", "tests_passed", "tests_failed"}` (taken from the
  metrics when the gate passes). A red run with `right_reason` false blocks `passed` until a new red run is recorded.
- static: written by `bf static run` (`checks_run`, `new_findings`, `blocking_open`, `fixed`, `wontfix`, `baseline_matched`, `tool_errors`); findings passed with `--data` are ignored
- ui: `differences`, `blocking`, `rounds`, `fix_rounds`, `invalid_comparisons`
- review: `rounds`, `fix_rounds`, `issues_found`, `issues_fixed`
- docs: `rounds`, `fix_rounds`, `files_changed`, `files_created`, `review` (`"self"` when the writer's self-check replaced the reviewer); put the paths in `"files": [...]`

For findings with quotes or newlines, write the JSON to a file and use `--file`.

## Cost measurement

`bf cost` reads `~/.claude/projects/*/<session>.jsonl` and
`~/.claude/projects/*/<session>/subagents/*.jsonl` for every session registered on the run
(the Stop hook registers sessions automatically; `init --session` registers the first).
It deduplicates API calls by message id, keeps only calls inside the run's time window,
and prices them with `pricing.json` (list prices, cache writes and reads priced
separately). Attribution:

- role: the `bf:<scope>:<role>` tag at the start of the subagent's description, else
  `orchestrator` for the main thread
- checkpoint/phase: the tag's scope (`context`, `brief`, `design`, `planning`, `cpNN`),
  else the checkpoint whose start/end window contains the call, else by approval time:
  `brief` (before the brief was approved), `design` (before the design was approved),
  `planning` (before the plan was approved), otherwise `review & feedback`

`cost` in state.json has the run totals and `by_role`, `by_model`, `by_checkpoint`, plus
`by_checkpoint_role` and `by_checkpoint_model` (the same split per checkpoint or phase).
A checkpoint report shows only that checkpoint's numbers, with the run total as one line.

Time: wall-clock from `init` to `accept` = active + waiting + idle.
- waiting: time in any `awaiting_*` phase and in `paused`
- idle: silences without any transcript line (main session or subagent) longer than
  10 minutes (`BUILDFLOW_IDLE_GAP_MIN`, or `idle_gap_minutes` in state.json), outside the
  waiting phases. Rate limits, crashes and a closed laptop end up here.
- active: the rest
Per checkpoint the same split is made over its start..end window. Summed subagent time
shows how much parallel work ran.

Interruptions: the StopFailure hook appends `{"at","error","details","phase","attempts","status":"open"}`
to `interruptions` in state.json and closes running attempts with result `interrupted`
(gate status `interrupted`). `bf interrupted` does the same by hand. An interruption does
not change the phase. It becomes `resumed` (`resumed_at`, `resumed_how`: auto or manual,
`resumed_via`) on the next normal Stop hook event, the next `bf` command that changes state,
or `bf resume`. Interrupted gates stay interrupted until `bf resume --running|--redo` or a
`bf gate` result for them; while background tasks run, the Stop hook asks for that (at most
twice for the same gates). Every interruption counts in the time report, whatever its status.
