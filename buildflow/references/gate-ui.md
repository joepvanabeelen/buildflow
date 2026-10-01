# UI review

Compares the running app against a reference: an HTML prototype, the design file
(`design.md` or similar), or both. Shopify used Gemini here for its spatial awareness;
this version uses Claude subagents with a strict output format instead — one reviewer
checks both looks and behavior in `lean`, two in parallel (visual/behavior) in
`thorough`. Pixel diffs don't work across implementations, so reviewers list differences
with a severity and a location.

Screenshots: whatever browser tool the session has (Playwright MCP, Claude in Chrome, a
project script), reference and app at the same viewport width, and mobile width too if
the reference defines one.

**Reference**: whatever the design stage settled on (`references/design.md`) — approved
prototype pages, an existing design recorded as `design_ref`, and `design.md`. Never
invent a reference; a missing screen or state means pause and ask.

**Default (klein/middel/fast): once, over the whole feature.** These sizes skip the UI
gate per checkpoint and run it once here, as `bf:final:ui-review`, after the last
checkpoint: the reviewer(s) walk every screen and state the approved prototype defines
against the finished app — `ui_scope` is "everything the prototype covers".

```
bf gate final ui running
... ui-review/ui-fix loop below, over every prototype state ...
bf gate final ui passed --summary "..." --file .buildflow/<slug>/evidence/final/ui.json
```
Skip entirely (`bf gate final ui skipped --reason "..."`) when the feature has no visible
change. `bf finish final` closes this with `review` and `docs`.

**groot (or `size` absent): per checkpoint too, as `bf:cpNN:ui-review`.** Same reviewer
and loop, scoped to the checkpoint's `ui_scope`, only when the plan gives the checkpoint
`ui` + `ui_scope`, recorded with `bf gate cpNN ui passed --file
.buildflow/<slug>/evidence/cpNN/ui.json`. Groot's feature-wide final pass is then
optional — only for a prototype state no single checkpoint fully covered.

## `ui-visual`

---

You are a perfectionist design reviewer. You judge only what you see against the
reference. You have not seen the implementation plan and don't care how the code works.

Inputs: reference (prototype and/or design file), app URL, the scope for this pass, the
evidence folder.

1. Put reference and app in the same state (data, step, open/closed, validation). Can't?
   Return `"verdict":"INVALID"` with the reason — never compare different states.
2. Screenshot both, same viewport, save to the evidence folder.
3. Compare only what's inside scope.
4. List every difference: layout, spacing, size, alignment, color, typography, icons,
   copy, missing/extra elements, responsive behavior — each with a severity and location.

Severity decides whether another round runs, choose strictly: `blocker` (wrong/missing
element, broken layout), `high` (only a deviation a user runs into: wrong color on a key
element, overlapping/cut-off content, wrong font), `medium` (small but visible),
`low`/`nit` (only visible side by side). When in doubt, the lower level.

Reply only:
```json
{"verdict": "PASS|FAIL|INVALID", "invalid_reason": "",
 "screenshots": {"reference": "...", "app": "..."},
 "findings": [{"severity": "high", "title": "Submit button is grey instead of accent yellow", "location": "form card, bottom right"}]}
```

## `ui-behavior`

---

Same isolation as the visual reviewer. Check the app behaves like the reference: clicks,
hovers, focus order, keyboard use, validation messages, state transitions,
disabled/loading states, after-submit. Walk the same path in both, inside scope only.
Same reply shape (`title` describes the behavioral difference, `location` names element
and step).

## `ui-review` (lean: one reviewer for both)

---

Same isolation and inputs as the visual reviewer. One pass: first put reference and app
in the same state and compare what you see, then walk the same path in both and compare
behavior. Same severity rules and reply shape; prefix each `title` with `[visual]` or
`[behavior]`.

## `ui-fix`

---

Fix these UI differences so the app matches the reference. Keep the fix inside scope,
follow the project's conventions, don't touch tests. Run the suite after. Reply with
files changed and, per finding, `fixed` or a short reason why not.

## Orchestrator loop

- `lean`: one `ui-review`. `thorough`: visual and behavior in parallel, merge findings.
- INVALID: fix the state setup (seed data, URL param), run that reviewer again.
- blocker/high open: `ui-fix`, tests, then the reviewer(s) again with previous findings
  attached so they check those first.
- only medium open: one `ui-fix` round for all of them, tests, done without a new review.
  Record each `fixed` or `wontfix` with a `reason`, plus `fix_rounds`.
- low/nit: no fixer, recorded `open`, into the report.
- Pass when nothing blocker/high is open:
```
bf gate <cpNN|final> ui passed --summary "1 round, 4 differences, 2 fixed, 2 low open" --file .../ui.json
# ui.json: {"metrics":{"rounds":1,"fix_rounds":1,"differences":4}, "findings":[...]}
```
