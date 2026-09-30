# Project and feature context

buildflow runs inside an existing repo or project folder, and every agent has to work
from what is already there: its conventions, architecture, design, tests and domain.
Context comes in two files:

| file | scope | written by | lifetime |
|---|---|---|---|
| `.buildflow/context.md` | the whole project | `bf:context:project` | reused by every run; refreshed when stale |
| `.buildflow/<slug>/context-feature.md` | this feature | `bf:context:feature` | one per run |

`bf context --check` says whether the project file is `missing`, `stale` (older than 30
days, more than 25 files changed since it was written, or a key file changed such as
CLAUDE.md, package.json, design.md or anything under docs/) or `fresh`. Only (re)write it
when it is not fresh. The feature file is always written for a new run. A project context
written before the `## Features` section existed counts as stale for that part: when it
has no such section, have the project scout add it (only that section) before intake.
The same goes for `## Deterministic checks` and `.buildflow/static.json`.

Every subagent in the run gets both paths and reads them before anything else, together
with the learnings file. The files point to sources; agents read the sources they need
directly rather than trusting a summary for details.

If the project has a knowledge graph (`graphify-out/`), the scouts use it first for
structure and relationships and read files only to confirm.

## `bf:context:project`

---

Write a project profile to `.buildflow/context.md` for agents that will build a feature
here. Be factual and specific; cite file paths for every claim; no generic advice. If
something does not exist, write "none found" rather than leaving it out. Aim for 150 to
300 lines.

Sections:

1. **What this is**: product and purpose in three sentences, the main user types, the
   domain words the code uses (a short glossary with the file where each is defined).
2. **Stack and layout**: languages, frameworks and versions, package manager, the
   top-level folders and what lives where, entry points.
3. **How to run it**: install, start (with URL and port), seed data, test accounts,
   environment variables needed locally (names only, never values).
4. **Tests**: framework(s), where tests live, naming, fixtures/factories, how to run all
   tests, one file, one test; how integration tests reach the app; current state of the
   suite if you can run it quickly (count, failures).
5. **Conventions**: everything in CLAUDE.md, AGENTS.md, CONTRIBUTING, lint and format
   config, and the patterns the code actually follows (naming, error handling, data
   access, state management, API style). Quote the written rules. Where docs and code
   disagree, say so.
6. **Architecture**: layers and boundaries, how a request flows through the app, where
   business rules live, how data is stored and migrated, background jobs, integrations.
   Point to ADRs or architecture docs.
7. **Front-end stack**: framework and version (React/Next, Vue/Nuxt, Svelte, Angular,
   Blade/Livewire, Rails views, ...), rendering (SPA, SSR, server templates), the
   component library (shadcn/ui, MUI, Vuetify, Flux, in-house) with the import path of
   the main components, the styling approach (Tailwind with its config file, CSS modules,
   CSS-in-JS, SCSS) and where the design tokens are defined, icon set, forms and
   validation library, state management, how a new page and a new component are added
   (file locations and naming), Storybook or another component workshop, and how the
   built CSS can be loaded outside the app (the path of the compiled stylesheet, or the
   Tailwind config a CDN build could use).
8. **UI and design**: `design.md` or similar, design system docs, where screens and shared
   components live, existing prototypes or mockups and where they are kept. Name two or
   three screens that are good examples of house style.
9. **Documentation**: where docs live (README sections, `docs/`, a docs site and its
   tooling and navigation config, API specs, ADRs, CHANGELOG, user help, Storybook docs),
   their conventions (language, tone, format, front matter, changelog format), and what
   a typical feature in this project gets documented (look at two or three recent
   features and their doc changes in git history). Where design documentation lives, or
   where it would fit if there is none yet (propose one path, e.g. `docs/design/`).
10. **Review standard**: which of the above an adversarial reviewer should enforce, as a
   checklist with sources.
11. **Watch out**: generated code, fragile areas, things that look unused but are not,
   slow or flaky tests.
12. **Deterministic checks**: the linters, formatters, type checkers, SAST, secret
   scanners and dependency audits this project uses, with the exact command and config
   file for each. Start from what CI runs (`.github/workflows`, `.gitlab-ci.yml`, ...),
   then package scripts (`lint`, `typecheck`, `format:check`), pre-commit hooks and config
   files; the orchestrator gives you the output of `bf static detect`. Write the proposed
   set to `.buildflow/static.json` in the format of `references/gate-static.md`: tools
   that are installed or run by CI, machine-readable output where the tool has it,
   `{files}` where the tool takes paths. A tool that is missing may be proposed as a dev
   dependency of the project's own stack, installed in its own commit once the plan is
   approved; when semgrep or gitleaks is missing but `uvx`, `pipx` or a running docker is
   there, propose it through that runner instead, marked as such in `note`. List what is
   missing and not proposed under `not_available` with the reason.
13. **Features**: the features the product already has, as the user would name them
   (routes, menus, docs and help pages are good sources). Use exactly the heading
   `## Features`, one bullet per feature:
   `- **<name>**: <one line> · code: <main paths> · docs: <pages or none> · run: <slug or none>`.
   `run` is the buildflow run that built or changed it (see `bf runs`; each run's
   `brief.md` says what it built). This list is what the user picks from when a new run
   extends an existing feature, and the overview page shows it.

Reply only:
```json
{"file": ".buildflow/context.md", "test_command": "...", "dev_command": "...", "dev_url": "...",
 "design_ref": "path or none", "review_standard": ["CLAUDE.md", "..."], "baseline": {"tests_total": 0, "tests_failed": 0},
 "frontend": {"framework": "...", "components": "...", "styling": "...", "storybook": false, "compiled_css": "path or none"},
 "docs": {"root": "docs/", "tooling": "...", "design_docs": "docs/design/", "prototypes": "docs/design/prototypes/", "changelog": "CHANGELOG.md"},
 "static_checks": ".buildflow/static.json", "static_not_available": ["bandit: not installed"]}
```

## `bf:context:feature`

---

Inputs: the feature description (and the brief once it exists), the project context file,
and, when the run extends an existing product feature, that feature's entry from the
`## Features` section (start from its code and docs paths, and from its run's brief and
final report if it has one).

Write `.buildflow/<slug>/context-feature.md`: what in this codebase this feature touches.

1. **Existing behavior**: what the app does today in this area, with file paths. If part
   of the feature already exists, say exactly which part.
2. **Touch points**: the modules, routes, screens, components, models, tables and
   migrations this feature will likely change or depend on.
3. **Closest existing examples**: two or three similar features to copy structure from,
   with the files that show the pattern.
4. **Data and permissions**: the data model involved, who may do what, where access is
   checked today.
5. **Tests in this area**: which tests cover it now and how they are set up.
6. **Docs in this area**: the existing pages, API spec entries, help texts, design docs
   and prototypes that describe this part of the app and will need to change.
7. **Recent changes**: relevant commits or open work (`git log` on the touched paths),
   and files changed since the project context was written if `bf context --check`
   listed any.
8. **Open questions for the brief**: what the code cannot tell you and the user must
   decide. These feed the brainstorm.

Reply only:
```json
{"file": ".buildflow/<slug>/context-feature.md", "touch_points": ["..."], "ui_affected": true,
 "existing_design_for_this_feature": "path or none", "docs_affected": ["..."], "open_questions": ["..."]}
```
