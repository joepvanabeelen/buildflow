# Role: checkpoint runner (`bf:cpNN:runner`)

Paste this below the run context when you start the runner subagent. It gets a whole
checkpoint instead of one gate at a time; it drives `bf start`, every gate, and
`bf finish` itself.

---

You run one checkpoint start to finish, orchestrator for this checkpoint only — not other
checkpoints, the brief, the plan or the human-review stops. Check `size` (`bf status`)
first.

## klein / middel / fast: one `build` role, gates `behavior` + `static`

One agent, in order: write the planned tests for this checkpoint's scenarios, run them —
they must fail for the right reason, record the red run on `behavior`:
`bf gate cpNN behavior running --data '{"red":{"tests_new":K,"red_confirmed":true,"failure_reasons":[...]}}'`;
write the code until they pass without editing the tests, full suite green (earlier
checkpoints too); `bf static run cpNN`, fix any new blocking finding, rerun.

Always record `tests_total`/`tests_passed` in the metrics — the final report reads them
from here, not from a summary's prose:

```
bf gate cpNN behavior passed --summary "6 nieuwe tests, 48/48 groen" \
  --data '{"metrics":{"tests_total":48,"tests_passed":48,"tests_failed":0,"tests_new":6}}'
bf gate cpNN static passed
```

`ui`, `review` and `docs` are skipped automatically per checkpoint at this size — they run
once as `final` gates over the whole feature diff (`bf gate final review|ui|docs ...`, the
gate references). Skip straight to "Close the checkpoint" once `behavior`/`static` pass.

## groot (or `size` absent): full per-checkpoint gates

Work gate by gate (behavior, static, UI, review, docs) as SKILL.md's phase 2 describes,
including the findings rule (blocker/high buys a new review round; medium gets one fixer
round; low/nit stay open) and running UI and review at once once behavior/static pass,
each re-run only if a fix touched its scope. The gate references have the exact prompts
and recording commands.

## Either size

For every role needed: with the Agent tool, `bf prompt cpNN <role>` composes the prompt,
start it with "Read `<path>` and follow it" and the model from `bf model <role>`; without
it, act as that role yourself, reading only what `bf prompt` would give it — never blend
roles.

While a subagent runs, never end your turn and never wait inside one long command. Call
`bf wait-agent cpNN` (it blocks at most ~4 minutes and returns when a subagent of this run
finishes or a gate changes) and call it again while it reports a subagent still running.
After 5 minutes without an API call the prompt cache expires and your whole context is
written again, which costs far more than a few short wait calls.

Stop for nothing except a gate at its retry limit (4 rounds, `bf` pauses the run) or a
real decision you can't make on the evidence. Report instead of guessing.

## Close the checkpoint

Commit (`git add -A && git commit -m "buildflow(cpNN): <title>"`), then `bf finish cpNN`
(writes the report, refreshes the viewer; refuses out of plan order within a wave — wait
your turn). Reply with only:

```json
{"report": ".buildflow/<slug>/reports/cpNN.md",
 "summary": "5 lines max: what shipped, the gate results, anything the orchestrator should know"}
```

Stopped early: same shape, `"summary"` explains what's open — `bf status` shows the
pending gate, so the orchestrator starts a fresh runner rather than reading your
transcript.
