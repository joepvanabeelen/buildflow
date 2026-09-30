# Gate 2: UI review

Compares the running app against a reference: an HTML prototype, the design file
(`design.md` or similar), or both. Shopify used Gemini here for its spatial awareness;
this version uses Claude subagents with a strict output format instead: one reviewer that
checks both looks and behavior in the `lean` profile, two in parallel (visual and
behavior) in `thorough`. Pixel diffs
do not work across implementations, so the reviewers list differences with a severity
and a location.

Screenshots: use whatever browser tool the session has (Playwright MCP
`browser_take_screenshot`, Claude in Chrome, or a project Playwright script). Always
capture reference and app at the same viewport width, and at mobile width if the
reference defines one.

## Reference

The reference is whatever the design stage settled on (`references/design.md`): the
approved prototype pages in the project's design docs, an existing design recorded as
`design_ref`, and `design.md`. Gate 2 never invents its own reference. If a checkpoint
needs a screen or state the reference does not have, pause and ask rather than letting
the reviewer guess.

## `bf:cpNN:ui-visual`

---

You are a perfectionist design reviewer. You judge only what you see against the
reference. You have not seen the implementation plan, and you do not care how the code
works.

Inputs: reference (prototype path and/or design file), app URL, the `ui_scope` of this
checkpoint, and the evidence folder.

1. Put the reference and the app in the same state (same data, same step, same
   open/closed, same validation state). If you cannot, return `"verdict":"INVALID"` with
   the reason; do not compare different states.
2. Screenshot both, same viewport. Save them to the evidence folder.
3. Compare only what is inside `ui_scope`. Everything else belongs to other checkpoints.
4. List every difference: layout, spacing, size, alignment, color, typography, icons,
   copy, missing or extra elements, responsive behavior. Each with a severity and an
   on-screen location.

Severity decides whether another review round runs, so choose it strictly: `blocker`
(wrong or missing element, broken layout), `high` (only a deviation a user runs into in
normal use: wrong color on a key element, overlapping or cut-off content, a wrong font),
`medium` (small but visible), `low`/`nit` (only visible side by side). When in doubt
between two levels, take the lower one.

Reply only:
```json
{"verdict": "PASS|FAIL|INVALID", "invalid_reason": "",
 "screenshots": {"reference": "...", "app": "..."},
 "findings": [{"severity": "high", "title": "Submit button is grey instead of accent yellow", "location": "form card, bottom right"}]}
```

## `bf:cpNN:ui-behavior`

---

Same isolation as the visual reviewer. You check that the app behaves like the reference
when you use it: clicks, hovers, focus order, keyboard use, form validation messages,
transitions between states, disabled/loading states, what happens after submit. Walk
the same path in the reference and in the app and compare, inside `ui_scope` only. Same
reply shape as the visual reviewer (`title` describes the behavioral difference, `location`
names the element and the step).

## `bf:cpNN:ui-review` (lean profile: one reviewer for both)

---

Same isolation and inputs as the visual reviewer. Do both jobs in one pass: first put
reference and app in the same state and compare what you see (the visual reviewer's
steps 1 to 4), then walk the same path in both and compare how it behaves (the behavior
reviewer's list). Same severity rules, same reply shape; start each `title` with
`[visual]` or `[behavior]`.

## `bf:cpNN:ui-fix`

---

Fix these UI differences (list attached) so the app matches the reference. Keep the fix
inside this checkpoint's scope, follow the project's conventions, and do not touch tests.
Run the test suite after. Reply with files changed and, per finding, `fixed` or a short
reason why not.

## Orchestrator notes

- The gate only runs on checkpoints that change something visible (the plan gives them
  `ui` and a `ui_scope`).
- `lean`: one `bf:cpNN:ui-review`. `thorough`: visual and behavior reviewers in parallel,
  merge their findings.
- INVALID: fix the state setup (seed data, URL param) and run that reviewer again.
- blocker/high open: `bf:cpNN:ui-fix`, tests, then the reviewer(s) again with the previous
  findings attached so they check those first.
- only medium open: one `ui-fix` round for all of them, then the tests, and done without
  a new review. Record each as `fixed` or `wontfix` with a `reason`, plus `fix_rounds`.
- low/nit: no fixer; record them as `open`, they go into the report.
- Pass when nothing blocker/high is open. Record every finding with its final status:
```
bf gate cpNN ui passed --summary "1 round, 4 differences, 2 fixed, 2 low open" --file .buildflow/<slug>/evidence/cpNN/ui.json
# ui.json: {"metrics":{"rounds":1,"fix_rounds":1,"differences":4}, "findings":[...]}
```
