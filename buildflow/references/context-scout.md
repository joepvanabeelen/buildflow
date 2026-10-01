# Project and feature context

buildflow runs inside an existing repo, and every agent works from what's already there.
Context comes in two files:

| file | scope | written by | lifetime |
|---|---|---|---|
| `.buildflow/context.md` | the whole project | `bf:context:project` | reused by every run; refreshed when stale |
| `.buildflow/<slug>/context-feature.md` | this feature | `bf:context:feature` | one per run |

`bf context --check` says `missing`/`stale`(why)/`fresh` for the project file (stale:
older than 30 days, 25+ files changed since written, or a key file changed — CLAUDE.md,
package.json, design.md, anything under docs/). Only rewrite it when not fresh. The
feature file is always written fresh. A context without `## Features` or
`## Deterministic checks` counts as stale for that section only — have the scout add just
that part.

Every subagent reads both files and the learnings file first, then goes to the source
files it actually needs — these are pointers, not substitutes for reading code. If the
project has a knowledge graph (`graphify-out/`), scouts use it first for structure.

`bf prompt <scope> <role> --cp cpNN` only includes the context-feature.md sections whose
path prefix-matches the checkpoint's `files_hint`, plus brief-summary.md and learnings in
full, plus context.md. No match, or no paths in the headings: the whole file goes in (old
behavior).

## `bf:context:project`

---

Write a project profile to `.buildflow/context.md`, **ceiling ~600 words**. Factual,
specific, a file path for every claim; "none found" rather than omitting a section. This
is a map for subagents to navigate from, not the whole territory — point at files instead
of summarizing their contents.

Sections, each a tight paragraph or a few bullets, not a chapter:

1. **What this is**: product and purpose, main user types, a short domain glossary with
   where each term is defined.
2. **Stack and layout**: languages, frameworks, package manager, top-level folders, entry
   points.
3. **How to run it**: install, start (URL/port), seed data, test accounts.
4. **Tests**: framework, location, how to run all/one/a single test, current baseline
   (count, failures) if quick to check.
5. **Conventions**: CLAUDE.md/AGENTS.md/CONTRIBUTING, lint/format config, patterns the
   code actually follows. Where docs and code disagree, say so.
6. **Architecture**: layers, request flow, where business rules and data live,
   integrations, with pointers to ADRs.
7. **Front-end stack**: framework, component library and import path, styling approach and
   token location, forms/validation, state management, Storybook or not, how to load the
   built CSS outside the app.
8. **UI and design, docs**: where design.md/design system docs, screens, prototypes and
   project documentation live, their conventions, two or three example screens/pages.
9. **Review standard**: what an adversarial reviewer should enforce, as a checklist with
   sources.
10. **Watch out**: generated code, fragile areas, slow/flaky tests.
11. **Deterministic checks** (`## Deterministic checks` → `.buildflow/static.json`): the
    linters, type checkers, SAST, secret and dependency scanners this project uses, exact
    command and config per tool. Start from CI (`bf static detect`'s output), then package
    scripts, pre-commit, config files. Format per `references/gate-static.md`. A missing
    tool may be proposed as a dev dependency, or via `uvx`/`pipx`/docker for semgrep/
    gitleaks, noted as such. List what's missing and not proposed under `not_available`.
12. **Features** (`## Features`, one bullet each): `- **<name>**: <one line> · code: <main
    paths> · docs: <pages or none> · run: <slug or none>` — what the user picks from when
    extending an existing feature.

Reply only:
```json
{"file": ".buildflow/context.md", "test_command": "...", "dev_command": "...", "dev_url": "...",
 "design_ref": "path or none", "review_standard": ["CLAUDE.md", "..."], "baseline": {"tests_total": 0, "tests_failed": 0},
 "frontend": {"framework": "...", "components": "...", "styling": "...", "storybook": false, "compiled_css": "path or none"},
 "docs": {"root": "docs/", "tooling": "...", "design_docs": "docs/design/", "prototypes": "docs/design/prototypes/", "changelog": "CHANGELOG.md"},
 "static_checks": ".buildflow/static.json", "static_not_available": ["bandit: not installed"]}
```

`bf context --project F` warns (never fails) when the written file is over ~700 words —
trim rather than ignore the warning; a bloated project context is read by every subagent
in every future run.

## `bf:context:feature`

---

Inputs: the feature description (and the brief once it exists), the project context, and,
for an extension, the existing feature's `## Features` entry (its code/docs paths, its
run's brief and final report).

Write `.buildflow/<slug>/context-feature.md` as short sections per area, each headed with
its paths so `bf prompt` can match a checkpoint's `files_hint` against it:

```markdown
## Approval rules — `src/leave/approval/`
Existing behavior, touch points, closest similar feature, data/permissions, tests, docs —
whatever is relevant to this area, in a few sentences and bullets. Skip what doesn't apply.

## Notifications — `src/notifications/`, `src/leave/events.ts`
...
```

Cover, across the sections: existing behavior and which parts already exist, touch points
(modules/routes/models/migrations likely to change), the closest existing examples to copy
structure from, data and permissions, tests in the area, docs that will need to change,
and recent relevant commits. End with a final, un-sectioned list of **open questions for
the brief** — what the code can't answer.

Reply only:
```json
{"file": ".buildflow/<slug>/context-feature.md", "touch_points": ["..."], "ui_affected": true,
 "existing_design_for_this_feature": "path or none", "docs_affected": ["..."], "open_questions": ["..."]}
```

## `bf:plan:health`

---

Runs in the background during intake, alongside the context scouts — a quick sanity check,
not a full review. Check: does the project build/typecheck, does the existing test suite
run at all (don't fix failures, just note the count), are there obvious blockers (missing
.env, broken install) that would stall the whole run. A few minutes of work, not an audit.

Reply only:
```json
{"buildable": true, "install_ok": true, "baseline": {"tests_total": 0, "tests_failed": 0},
 "blockers": ["..."]}
```
