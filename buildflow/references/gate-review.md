# Adversarial code review

The feature works and looks right; this gate checks the code underneath. One reviewer
assumes the code is wrong and tries to prove it; a separate fixer addresses what it
finds. Only blocker and high findings buy a fresh reviewer: mediums get one fix round and
the tests, lows and nits go into the report. The gate passes when no blocker/high is left.

**Default (klein/middel/fast): once, over the whole feature.** These sizes skip a review
gate per checkpoint and run this once, after the last checkpoint, as `bf:final:adversary`
— the diff is `git diff <base of cp01>..HEAD`, inputs are the brief's success outcomes
(every checkpoint's done_when combined) and every checkpoint's static results.

```
bf gate final review running
... adversary/fixer loop below ...
bf gate final review passed --summary "..." --file .buildflow/<slug>/evidence/final/review.json
```
`bf finish final` closes this together with `ui` and `docs`; `bf accept` requires all
three for klein/middel/fast.

**groot (or `size` absent): per checkpoint too, as `bf:cpNN:adversary`.** Same prompt and
loop, scoped to `git diff <checkpoint base>..HEAD` plus uncommitted changes, done_when of
that one checkpoint, and `bf gate cpNN review passed --file
.buildflow/<slug>/evidence/cpNN/review.json`. Groot's feature-wide final pass is then
optional — run it only for emergent risk no single checkpoint's review could see
(cross-cutting data flow, interactions between checkpoints).

The gate is as strong as the written standard it enforces: point the adversary at
CLAUDE.md/AGENTS.md, architecture and style docs, and the learnings file.

## `adversary`

---

You are reviewing someone else's change and you assume it is wrong. Your job is to find
out how. You did not write this code and you owe it nothing.

Inputs: the diff, the done_when it must satisfy, the review standard files, the learnings
file, the static gate results (what the linters, type checker, SAST, secret scanner and
dependency audit ran, found, and accepted as won't fix), and previous review findings on
a re-review.

The tools already ran. Do not re-report what they found or would find; a won't-fix
decision on a tool finding is not yours to reopen unless the reason given is wrong. Spend
your attention on what tools cannot see: whether the code does what done_when says,
authorization and business rules, data flow across files, tests that prove nothing, and
the written standard. If a tool should have caught something and didn't, say so once as a
finding about the check set.

Check, in order: correctness (done_when for all inputs, unhappy paths, off-by-one, time
zones, nulls, races, swallowed errors); security and data (authorization on every entry
point, input validation, injection, secrets, personal data in logs); tests (do they
actually prove the behavior, or would they pass with a broken implementation?); the
project standard (quote the rule you apply); maintainability (duplication, dead code,
comments that lie).

Only report what you can point to in the diff. Every finding: severity, file and line,
one sentence on the concrete failure. Choose severity strictly, it decides whether
another round runs: `blocker` (done_when not met, data lost/leaked, security boundary
broken), `high` (only something a user runs into, or a bug you can prove — not a risk you
can only imagine), `medium` (a real weakness that doesn't hit a user now), `low`/`nit`
(everything else). When in doubt, take the lower level.

On a re-review: first check each previous finding (fixed/not fixed/regressed), then the
new changes.

Reply only:
```json
{"verdict": "APPROVED|CHANGES_REQUESTED",
 "findings": [{"severity": "high", "title": "...", "location": "src/x.ts:42", "failure": "..."}],
 "previous": [{"title": "...", "status": "fixed|not_fixed|regressed"}]}
```
APPROVED means no blocker/high remains; medium/low/nit may remain, listed.

## `fixer`

---

Fix these review findings. For each one either fix it, or, if convinced it's wrong, leave
the code and give the evidence (a test, a doc reference, a trace). Don't edit tests to
make them pass; you may add tests. Run the full suite after. Reply only:

```json
{"files_changed": ["..."], "tests_passed": N, "tests_failed": 0,
 "findings": [{"title": "...", "status": "fixed|disputed", "evidence": "..."}],
 "visible_change": false}
```

## Orchestrator loop

```
round = 1
adversary -> blocker/high open? -> fixer (all open blocker/high/medium findings)
                                 -> tests green? (else fix again)
                                 -> bf static run (new blocking findings? static-fix first)
                                 -> visible_change and ui gate open? -> rerun it
                                 -> new adversary run with previous findings
          -> only medium open   -> one fixer round, tests green, static run -> record passed
          -> only low/nit/none  -> record passed (no fixer)
max 4 rounds -> bf pause --reason "review does not converge: <the disagreement>"
```

After the one medium fix round nobody reviews again — tests and static checks are the
check. Record each medium as `fixed`, or `wontfix` with a `reason` (the fixer's evidence
if it disputed the finding). Lows/nits recorded `open`, no fixer, into the report. A
disputed blocker/high goes back to the next adversary run with the fixer's evidence; if
the adversary drops it, record `wontfix` with the reason.

`bf` refuses the pass while a blocker/high is open, or a medium lacks both
`"fix_rounds": 1` and a `reason`.
