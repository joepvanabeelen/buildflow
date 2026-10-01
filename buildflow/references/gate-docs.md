# Documentation gate

Documentation is part of the work, not an afterthought. What counts as documentation is
whatever the project already has — the Documentation section of `.buildflow/context.md`
lists it: README sections, `docs/`, a docs site, API specs, ADRs, CHANGELOG, user help
pages, Storybook, code-level docs, and the design documentation (`design.md`, prototype
pages).

Rules for every docs change:
1. **Change what exists** — find the page/section/spec that already covers this area and
   update it in place. A new page only when nothing covers the topic, in the project's
   own structure (and navigation config if there is one). Never a parallel
   `FEATURE_NOTES.md` or second design file.
2. **Follow the project's doc conventions**: language, tone, heading style, file naming,
   front matter, example and changelog format.
3. **Every claim matches the code as it is now.** If you can't verify a claim in the
   code, don't write it.
4. **Design documentation stays true**: when implementation deviated from the approved
   prototype for a good reason, update the prototype page and design.md to match. The
   prototype is a living reference, not a planning artifact.
5. **No drive-by rewrites** — note problems outside scope instead of fixing them.

**Default (klein/middel/fast): once, mandatory, over the whole feature.** These sizes
never ran a docs gate per checkpoint, so this is their only one. Runs when `bf finish` of
the last checkpoint puts the run in `documenting`; the Stop hook keeps you working until
it passes. `bf gate final docs running`, then:

**Writer, `bf:final:docs`**: with the brief, the feature context, the complete feature
diff (`git diff <base>..HEAD`) and the design docs, make the documentation of the feature
complete as a whole — overview/user-facing page, changelog entry, cross-links between
pages touched by different checkpoints, prototype and design.md brought in line with what
was finally built, an ADR if the brief's approach was an architectural decision and the
project keeps ADRs.

**Reviewer, `bf:final:docs-review`** (always a separate reviewer): the checks below, over
the whole feature, plus — can someone uninvolved understand what the feature does, how to
use it and how it's built, from the docs alone? Every brief success outcome should be
findable.

Loop until no blocker/high is open (mediums: one fix round), commit (`git commit -m
"buildflow(docs): <feature>"`), record:
```
bf gate final docs passed --summary "..." --file .buildflow/<slug>/evidence/feature-docs.json
```
For klein/middel/fast, `review` and `ui` (final) must also be recorded; once all three
are in, `bf finish final` writes the final report and moves the run to human review.

**groot (or `size` absent): per checkpoint too, when it has a `docs_scope`.** Same writer
and reviewer, scoped to that checkpoint's diff and `docs_scope`, run right after the
review gate passes, while the change is fresh. This still needs the feature-wide pass
above once at the end (overview, cross-links, consistency) — groot's docs gate alone
moves the run on there, same as before.

## `docs` (writer)

---

Inputs: the checkpoint (summary, done_when, `docs_scope`), its diff, the Documentation
section of the project context, the brief, the learnings.

Update the project documentation for what changed, following the rules above.
`docs_scope` says what the planner expected; handle more if you find it, say why if part
turns out unnecessary.

Reply only:
```json
{"files": ["docs/api/leave.md", "CHANGELOG.md"], "created": [], "notes": "max 3 lines",
 "not_done": [{"item": "...", "why": "..."}]}
```

**Self-check instead of a reviewer** (`lean`, small scope only: one file, only factual
updates). The writer checks its own work — open the code for every statement it changed,
confirm it, add `"self_check": [{"statement": "...", "checked_in": "src/x.ts:12"}]` to
the reply; no `docs-review` runs, record `"metrics":{"review":"self"}`. A new page, more
than one file, or anything explaining behavior in prose gets the reviewer.

## `docs-review` (reviewer)

---

You check documentation changes; you did not write them. Inputs: the docs diff, the code
diff, the `docs_scope`, the project's doc conventions.

Check: **accuracy** (every changed statement against the code — open it, don't trust the
writer), **completeness** (everything in scope, plus doc impact nobody handled),
**placement** (existing docs changed rather than new files added beside them; new pages
linked from navigation), **consistency** (terms, tone, format match the surrounding docs).

Findings, severity chosen strictly since only blocker/high buy another round: `blocker`
for wrong information, `high` only for missing/wrong docs a user or developer will
actually hit, `medium`/`low`/`nit` otherwise. When in doubt, the lower level. Reply only:
```json
{"verdict": "APPROVED|CHANGES_REQUESTED", "findings": [{"severity": "high", "title": "...", "location": "docs/api/leave.md:40"}]}
```

Loop as in the review gate: blocker/high back to the writer then a new reviewer with
previous findings attached; mediums get one writer fix round and no new review, recorded
`fixed`/`wontfix` with a `reason` plus `"fix_rounds": 1`; lows/nits recorded `open`, into
the report.

```
bf gate cpNN docs passed --summary "2 files updated, review approved in 1 round" \
  --file .buildflow/<slug>/evidence/cpNN/docs.json      # {"files":[...],"findings":[...]}
```
A checkpoint with no doc impact gets `docs_skip_reason` in the plan and `bf plan` skips
its docs gate; if impact turns up anyway, `bf gate cpNN docs running` reopens it.
