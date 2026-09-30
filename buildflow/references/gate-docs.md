# Gate 4 and the feature docs gate: project documentation

Documentation is part of the work, not an afterthought. It is checked twice:

- **Gate 4 (per checkpoint, only when the checkpoint has a `docs_scope`)**: the checkpoint's
  own doc impact, right after the code review passed, while the change is fresh.
- **Feature docs gate (once, after the last checkpoint, mandatory)**: the documentation
  of the feature as a whole is complete, consistent and matches the final code, before
  the human reviews the feature.

What counts as documentation is whatever the project already has. The Documentation
section of `.buildflow/context.md` lists it: README sections, `docs/`, a docs site
(Docusaurus, MkDocs, VitePress, ...), API specs (OpenAPI, GraphQL schema docs), ADRs,
CHANGELOG, user help pages, Storybook, code-level docs where the project relies on them,
and the design documentation: `design.md` and the prototype pages from the design stage.

## Rules for every docs change

1. **Change what exists.** Find the page, section or spec that already covers this area
   and update it in place. Add a new page only when nothing covers the topic, and put it
   where the project's docs structure says it belongs (and in the navigation/sidebar
   config if the docs tool has one). Never create a parallel `FEATURE_NOTES.md` or a
   second design file.
2. **Follow the project's doc conventions**: language, tone, heading style, file naming,
   front matter, how examples are written, how the changelog is formatted.
3. **Every claim matches the code as it is now**: routes, parameters, field names,
   permissions, defaults, error messages, screenshots. If you cannot verify a claim in
   the code, do not write it.
4. **Design documentation stays true**: when implementation deviated from the approved
   prototype for a good reason (a finding in gate 2 or 3, human feedback), update the
   prototype page and design.md so they describe what was built. The prototype is a
   living reference, not an artifact of the planning phase.
5. **No drive-by rewrites**: do not restyle or reorganize docs outside this feature's
   scope. Note problems you see instead.

## `bf:cpNN:docs` (docs writer, gate 4)

---

Inputs: the checkpoint (summary, done_when, `docs_scope`), the diff of this checkpoint,
the Documentation section of the project context, the brief, and the learnings.

Update the project documentation for what this checkpoint changed, following the rules
above. `docs_scope` says what the planner expected (e.g. "API reference for
POST /leave/{id}/approve; manager help page"); if you find more doc impact, handle it
and say so; if part of the scope turns out to be unnecessary, say why.

Reply only:
```json
{"files": ["docs/api/leave.md", "CHANGELOG.md"], "created": [], "notes": "max 3 lines",
 "not_done": [{"item": "...", "why": "..."}]}
```

**Self-check instead of a reviewer (lean profile, small scope only).** When the run's
profile is `lean` and the docs_scope is small (one file, only factual updates: a new
parameter, a changed default, a line in the changelog), the orchestrator asks the writer
to check its own work before replying: open the code for every statement it changed and
confirm it, and add `"self_check": [{"statement": "...", "checked_in": "src/x.ts:12"}]`
to the reply. No `docs-review` runs then; record `"metrics":{"review":"self"}`. A new page,
more than one file, or anything that explains behavior in prose gets the reviewer.

## `bf:cpNN:docs-review` (docs reviewer, gate 4)

---

You check documentation changes; you did not write them. Inputs: the docs diff, the code
diff of this checkpoint, the checkpoint's `docs_scope`, the project's doc conventions.

Check:
1. **Accuracy**: every changed statement against the code. Open the code; do not trust
   the writer.
2. **Completeness**: everything in `docs_scope`, and doc impact of the code diff that
   nobody handled (new setting, changed permission, new error, changed UI flow).
3. **Placement**: existing docs were changed rather than new files added next to them;
   new pages sit in the right place and are linked from navigation.
4. **Consistency**: terms, tone and format match the surrounding docs; no contradictions
   with other pages.

Findings with severity, chosen strictly because only blocker and high buy another review
round: `blocker` for wrong information, `high` only for missing or wrong docs a user or
developer will actually run into, `medium`/`low`/`nit` otherwise (wording, format,
cross-links). When in doubt, take the lower level. File and line. Reply only:
```json
{"verdict": "APPROVED|CHANGES_REQUESTED", "findings": [{"severity": "high", "title": "...", "location": "docs/api/leave.md:40"}]}
```

Loop like gate 3: blocker/high go back to the writer and then to a new reviewer with the
previous findings attached. Mediums get one fix round by the writer and no new review;
record them as `fixed` or `wontfix` with a `reason`, plus `"fix_rounds": 1`. Lows and nits
are recorded as `open` and go into the report. Record:
```
bf gate cpNN docs passed --summary "2 files updated, review approved in 1 round" \
  --file .buildflow/<slug>/evidence/cpNN/docs.json      # {"files":[...],"findings":[...]}
```
A checkpoint with no doc impact was planned with `docs` left out of its gates and a
`docs_skip_reason`; `bf plan` also skips the docs gate of a checkpoint without a
`docs_scope`. If it turns out to have doc impact after all, run the gate anyway:
`bf gate cpNN docs running` reopens a skipped gate, and the checkpoint cannot be
finished until it passes.

## Feature docs gate (`bf:final:docs`, `bf:final:docs-review`)

Runs when `bf finish` of the last checkpoint puts the run in phase `documenting`.
The Stop hook keeps you working until it passes.

`bf docs --status running`, then:

**Writer, `bf:final:docs`**: with the brief, the feature context, the complete feature
diff (`git diff <base>..HEAD`), all per-checkpoint docs changes and the design docs:
make the documentation of the feature complete as a whole. Typical work: the overview
or user-facing page that explains the feature end to end, the changelog entry, cross
links between pages touched by different checkpoints, the prototype page and design.md
brought in line with what was finally built, an ADR if the brief's chosen approach was
an architectural decision and the project keeps ADRs.

**Reviewer, `bf:final:docs-review`** (always a separate reviewer, also in `lean`): as the gate 4 reviewer, over the whole feature, plus:
can someone who was not involved understand what the feature does, how to use it and
how it is built, from the docs alone? Every success outcome in the brief should be
findable in the docs.

Loop until no blocker/high is open (mediums: one fix round, as in gate 4), then commit (`git commit -m "buildflow(docs): <feature>"`) and
record, which writes the final report and moves the run to the human review:
```
bf docs --status passed --summary "..." --file .buildflow/<slug>/evidence/feature-docs.json
```
