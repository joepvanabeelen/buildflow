# Static gate: deterministic checks

Linters, formatters, type checkers, SAST, secret scanners and dependency audits give the
same answer every time, cost seconds, and catch a class of problems no reviewer should
have to spend attention on. This gate runs the ones the project already uses on every
checkpoint, right after behavior and before the UI and review gates. Only findings the
checkpoint introduced count: whatever the tools found before the feature started is the
baseline.

`bf` does the running, parsing and bookkeeping. Your job is choosing the check set,
getting it approved, and sending new findings to a fixer.

## 1. The check set (intake and plan)

The project scout (`references/context-scout.md`) lists the tooling the project has in
the `Deterministic checks` section of `.buildflow/context.md` and writes the proposed set
to `.buildflow/static.json`. Run `bf static detect` first and give its output to the
scout: it lists installed tools, config files, package scripts, what CI runs and which
zero-install runners exist. The project context is shared between runs, so a later run
reuses `.buildflow/static.json`; when it is missing, have the scout add only that part.

Rules for the set:

- **Prefer what the project already runs**, CI first: the same commands, the same config.
  A check the project does not run on itself produces noise, not signal.
- **Adding a tool is allowed, as a dev dependency of the project's own stack** (`ruff`,
  `eslint`, `semgrep`, ... in `package.json`, `pyproject.toml`, or whatever the project
  already uses), proposed at the plan stop. Approving the plan approves the addition;
  installing it is a separate commit, before `bf static baseline`, never inside a check's
  own `cmd` (`bf static config` refuses a `cmd` that installs anything). A tool nobody
  proposes to add is listed under `not_available` with the reason.
- **semgrep and gitleaks** may also run through a zero-install runner already on the
  machine, instead of being added as a dependency: `uvx semgrep ...`, `pipx run semgrep
  ...`, or `docker run ...` when docker is running. They go in the set like any other
  check and the human approves them at the plan stop, same as an added dependency.
- Use the project's semgrep config when it has one; otherwise `p/default` or the
  rulesets for its languages (`p/python`, `p/javascript`, `p/typescript`, ...).
  Registry rules need network access; a check that cannot fetch them fails loudly.
- Prefer machine-readable output: `semgrep --sarif`, `eslint -f json`, `ruff check
  --output-format json`, `bandit -f json`, `gitleaks ... --report-format json
  --report-path {report} --redact`, `npm audit --json`, `pip-audit -f json`,
  `osv-scanner --format json`, `cargo audit --json`, `gosec -fmt json`, `rubocop
  --format json`, `golangci-lint run --out-format json`, `pyright --outputjson`,
  `shellcheck -f json`, `hadolint -f json`. `tsc --noEmit`, `mypy`, `flake8`,
  `prettier --check` and `black --check` are read as text.
- Use `npx --no-install <tool>` or `node_modules/.bin/<tool>`, never a bare `npx`, which
  can download the package.

`static.json`:

```json
{"checks": [
  {"name": "eslint", "cmd": "npx --no-install eslint -f json {files}", "kind": "lint",
   "scope": "changed", "format": "json", "ext": [".js", ".ts", ".tsx"], "blocking": true},
  {"name": "tsc", "cmd": "npx --no-install tsc --noEmit -p .", "kind": "types",
   "scope": "all", "format": "text", "ok_exit": [0, 1, 2]},
  {"name": "semgrep", "cmd": "uvx semgrep scan --config p/default --sarif --quiet --metrics off {files}",
   "kind": "sast", "scope": "changed", "format": "sarif", "timeout": 600},
  {"name": "gitleaks", "cmd": "gitleaks dir {files} --report-format json --report-path {report} --redact --no-banner --log-level error",
   "kind": "secrets", "scope": "changed", "format": "json", "per_file": true},
  {"name": "npm-audit", "cmd": "npm audit --json", "kind": "deps", "scope": "all",
   "format": "json", "blocking": false}
 ],
 "not_available": [{"name": "bandit", "reason": "not installed; no Python in this project"}],
 "note": "CI runs eslint and tsc (.github/workflows/ci.yml); semgrep via uvx, to approve"}
```

| field | meaning |
|---|---|
| `cmd` | run from the project root in a shell. `{files}` becomes the changed files (for `scope: changed`) or `.` (baseline, `scope: all`, more than 400 files; override with `all_arg`). `{report}` becomes a file the tool writes its report to |
| `kind` | `lint`, `format`, `types`, `sast`, `secrets`, `deps`, `other` |
| `scope` | `changed`: only files changed since the checkpoint started (skipped when none match `ext`); `all`: the whole project |
| `format` | `sarif`, `json` (the tools above are recognised) or `text` (`file:line: message`, tsc, prettier, black) |
| `blocking` | `false`: findings are reported but never block the gate |
| `per_file` | the tool takes one path (`gitleaks dir`): run the command once per changed file |
| `ext` | only files with these extensions count for this check |
| `ok_exit` | exit codes that mean "ran fine" (default `[0, 1]`; anything else is a tool error) |
| `timeout` | seconds (default 300, or `bf static run --timeout`) |

Record it: `bf static config --file .buildflow/static.json`. When nothing can run:
`bf static config --none --reason "<what was looked for>"`; every static gate is then
recorded as skipped with that reason and the reports say so plainly.

**At the plan stop**, list the set in chat in a few lines (tool, what it checks, which
ones run through a zero-install runner, what is not available). The viewer shows it under
the plan. Approving the plan approves the set; feedback on it goes through `bf static
config` again.

## 2. The baseline (once, before cp01)

After the plan is approved: if it added a tool as a dev dependency, install it now, in its
own commit. Then, on a clean tree: `bf static baseline`. It runs every check
on the whole project and stores the findings, fingerprinted by tool, rule, file and
message (not the line, so moved code is not new). `bf start` refuses while checks are
configured and no baseline exists. A check that fails at baseline is a broken command:
fix it in `static.json` before building. Changing the set later keeps the baseline;
`bf static config` names the checks it does not cover, and `bf static baseline` at the
next checkpoint boundary (clean tree) adds them.

## 3. Per checkpoint

```
bf static run cpNN          # after behavior passed
```

It runs the checks, subtracts the baseline, writes
`.buildflow/<slug>/evidence/cpNN/static.json` (raw output per tool under `static-raw/`,
never for secret scanners) and prints the new findings with their ids. Severity: error,
high, critical → `high`; warning, medium, moderate → `medium`; info, low, note → `low`.
Secrets are always `blocker`. A tool that crashes, times out, exits with an unexpected code
or prints output `bf` cannot read is a finding of its own (`tool-error`), never a pass.

- No blocking findings (`blocker`/`high` from a blocking check): `bf gate cpNN static passed`.
- Otherwise: `bf gate cpNN static failed --summary "<n> blocking: <tools>"`, give the
  findings to `bf:cpNN:static-fix`, then `bf static run cpNN` again. Findings that no
  longer show up are recorded as fixed; there is no marking them fixed by hand.
- A finding that is wrong or accepted: `bf static mark cpNN <id> wontfix --reason "..."`.
  It stays in the report with the reason and survives reruns. A secret cannot be waived
  this way (remove and rotate it); only a proven false positive, with `--force`.
- Max 4 failed rounds, then `bf` pauses the run like any other gate.

`bf gate cpNN static passed` refuses while a blocking finding is open, when no run exists
for this checkpoint, and when the code changed since the last run. The review and docs
gates change code too: after their fixes, run `bf static run cpNN` again before the
commit. `bf finish` refuses when the committed code differs from what the static gate
saw; a clean re-check keeps the gate passed, a new blocking finding reopens it.

Skipping: a checkpoint that changes no code gets `static_skip_reason` in the plan. When no
checks are configured, `bf gate cpNN static skipped --reason "..."`. With checks
configured, skipping an unplanned checkpoint needs `--force` and a reason.

The static results go to the adversary (`references/gate-review.md`): it does not repeat
what the tools found and spends its attention on what they cannot see.

## `bf:cpNN:static-fix`

---

Fix these findings from the project's own linters, type checker, security scanners and
dependency audit. They are new in this checkpoint. Inputs: the findings (tool, rule,
file, line, message), `.buildflow/<slug>/evidence/cpNN/static.json`, the checkpoint
summary, and the review standard files.

Rules:
1. Fix the cause in the code. Do not silence the tool: no disable comments, no config
   changes, no baseline or ignore-file edits, no `# type: ignore` or `eslint-disable`,
   unless the project's standard explicitly allows that for this case (quote it).
2. A secret: remove it from the code and use the project's configuration mechanism
   instead. Say that the value must be rotated; never repeat the value in your reply.
3. A vulnerable dependency: report the fixed version and what upgrading would touch. Do
   not change dependency files unless the finding is caused by a dependency this
   checkpoint added.
4. A tool error (crash, timeout, unreadable output): do not change code for it; report
   what you see, it is the orchestrator's call (fix the command in `static.json`, or
   accept it as won't fix with a reason).
5. If you are convinced a finding is a false positive, leave the code and give the
   evidence (the rule's intent, the data flow, a test).
6. Do not edit tests to make them pass. Run the full test suite after your changes.

Reply only:
```json
{"files_changed": ["..."], "tests_passed": N, "tests_failed": 0,
 "findings": [{"id": "a1b2c3d4e5", "status": "fixed|disputed|needs_decision", "evidence": "..."}],
 "visible_change": false}
```

## Orchestrator loop

```
bf static run cpNN -> blocking open? no  -> bf gate cpNN static passed
                                    yes -> bf gate cpNN static failed
                                           static-fix -> tests green? -> bf static run cpNN (again)
disputed with evidence  -> bf static mark cpNN <id> wontfix --reason "<evidence>"
tool error              -> fix the command (bf static config --file ...) or wontfix with the reason
max 4 rounds            -> bf pause --reason "static checks do not converge on cpNN: ..."
```
