# Gate 1: behavior

Proves the checkpoint works, without a browser. Tests are written first, fail first, and
then all have to pass, including every test from earlier checkpoints.

## `bf:cpNN:tests` (test writer)

---

Write the planned tests for this checkpoint (listed below, each with its Given/When/Then
scenario) in the project's existing test style and location. One test per scenario, named
with the planned name, so the red run can be matched back to the scenario. Do not write implementation code, stubs that make tests pass, or
mocks of the thing under test.

Then run only these tests. They must fail, and fail because the behavior is missing
(assertion failure, 404, missing export), not because of a typo, bad import or broken
fixture. Fix the tests until that is true.

If a planned test turns out to be wrong or impossible, do not quietly change its meaning:
write the closest correct test and report the change.

Reply only (failure reasons in the run's language where you write them yourself; quoted
error output stays as it is):
```json
{"files": ["..."], "tests_new": N, "red_confirmed": true,
 "failure_reasons": ["<planned test name>: expected X, got 404"], "plan_changes": []}
```

## `bf:cpNN:implement` (implementer)

---

Make this checkpoint's failing tests pass with production-quality code that follows the
project's conventions (read CLAUDE.md/AGENTS.md and the learnings first). Build only what
this checkpoint needs. Later checkpoints will add more.

You may not edit, skip, weaken or delete tests. If you believe a test is wrong, stop and
report it with your reasoning instead.

Run the checkpoint's tests, then the full suite. Earlier checkpoints must stay green.

Reply only:
```json
{"files_changed": ["..."], "tests_total": N, "tests_passed": N, "tests_failed": 0,
 "failing": [], "notes": "anything the reviewer should know, max 3 lines"}
```

When sent back after a failed gate, you get the failure output. Fix the cause, not the
symptom.

## `bf:cpNN:verify` (optional; for slow or noisy suites)

---

Run `<test command>` and report the counts and every failure with its first relevant
error lines. Do not change any file. Reply only:
```json
{"tests_total": N, "tests_passed": N, "tests_failed": N, "failing": [{"name": "...", "error": "..."}]}
```

## Recording: red, then green

The red run is evidence too. As soon as the test writer is back, record it on the running
gate; its reply can go in as it is:

```
bf gate cpNN behavior running --data '{"red":{"tests_new":6,"red_confirmed":true,
  "failure_reasons":["weigert een aanvraag met einddatum voor begindatum: expected 422, got 201"]}}'
```

(`red` also accepts `{"tests", "failed", "right_reason", "failures":[{"test","reason"}]}`.)
When the tests failed for the wrong reason, record that too (`"red_confirmed": false`) and
send the tests back; `bf` refuses to pass the gate on a red run that failed for the wrong
reason until a new red run is recorded. After the implementer and the full test run:

```
bf gate cpNN behavior passed --summary "6 nieuwe tests, 48/48 groen" \
  --data '{"metrics":{"tests_total":48,"tests_passed":48,"tests_failed":0,"tests_new":6}}'
```

The green numbers are stored from the metrics (or pass `"green": {...}` explicitly). The
viewer shows the strip rood -> groen per checkpoint and marks each scenario as planned,
red confirmed or green. Write `--summary` in the run's language.
