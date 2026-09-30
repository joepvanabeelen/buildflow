# Design stage (only when relevant)

Gate 2 compares the built app against a reference, so when there is none, making one is
a formal stage with its own review and its own human approval.

Two principles run through this stage:

- **Design is project documentation.** `design.md` and the prototype pages live in the
  project's docs, are committed, and are kept true for as long as the feature exists
  (the docs gates update them when the implementation deviates). Never put them in
  `.buildflow/`; that folder is scratch space and is not committed. `bf design ready`
  refuses paths there.
- **Design follows the stack that is already there.** When the project has a front-end
  stack, the design is expressed in it: its tokens, its components, its layout
  primitives. A design that the stack cannot build without a new library or a pile of
  one-off CSS is a wrong design, however good it looks.

Where things go: the Documentation section of `.buildflow/context.md` says where design
docs and prototypes live, or proposes a place when there are none yet (for example
`docs/design/design.md` and `docs/design/prototypes/<feature>/`). Use existing locations
and naming first.

## Decide: needed or not

Right after the brief is approved, decide and record it:

- **not needed** when the feature changes nothing users see (API, jobs, data, rules), or
  when an existing, approved design already covers every screen and state this feature
  touches (a Figma file, mockups, an existing prototype page, Storybook stories). Record
  that reference: `bf project design_ref=<path or url>`, then
  `bf design not-needed --reason "backend only"` or `--reason "covered by docs/design/prototypes/leave/"`.
- **needed** when the feature adds or changes screens and no approved design covers them.
  `bf design needed --reason "new approval screen, no mockup"`.

When in doubt about a small UI change (one button, one field following an existing
pattern), ask the user in one line rather than defaulting either way.

## Steps when needed

### 1. Design file (`bf:design:system`)

---

The project's design documentation must describe what this feature needs.

- **design.md exists**: change it, do not replace it. Add what the feature introduces
  (a new pattern, a new component, a new state or token) in the section where it belongs,
  in the file's existing format. If the feature exposes that design.md is wrong about the
  current app, fix those lines and list them. Leave everything else untouched.
- **No design.md**: extract the design system the app already uses into the location the
  project context names. Source every value from the code: token or theme files,
  Tailwind config, CSS variables, the component library, and the house-style screens the
  project context names. Do not invent a style.

Either way, write it in the stack's own terms, so a developer can build straight from it:

- tokens as the stack names them (Tailwind theme keys and utility classes, CSS custom
  property names, SCSS variables, theme object paths), with the file they are defined in;
- components by their real name and import path (`<Button variant="primary">` from
  `@/components/ui/button`), with the variants and states that exist, and which new
  component the feature needs, if any, with its intended props;
- layout primitives, page shells, form patterns, table/list patterns, empty and error
  states, as the app implements them;
- responsive breakpoints as configured, icon set, tone of UI copy.

Reply with the path, whether it was created or changed, a short list of what changed, and
any inconsistencies you found in the app. design.md itself follows the language and
format the project's docs already use; your reply and findings are in the run's language.

### 2. Prototype (`bf:design:prototype`)

---

Build prototype pages that show every screen and state the brief implies, and put them
in the project's prototype location (for example
`docs/design/prototypes/<feature>/index.html`, or next to existing prototypes in their
format). If a prototype for this area exists, extend it instead of starting a new one.

Build it on the project's front-end stack, in this order of preference:

1. **The project has Storybook (or another component workshop)**: build the new screens
   and states as stories from the real components. Also produce a thin static page in the
   prototype location that links to or embeds those stories, so the reference opens
   without a dev server.
2. **Otherwise**: a static HTML page that loads the project's real styling (the compiled
   stylesheet the project context names, or the Tailwind CDN build with the project's own
   config and plugins) and reproduces the markup and class names of the real components.
   A static page with the app's actual CSS is a far better reference than a lookalike.
3. **No front-end stack yet** (a new app): single-file HTML with inline CSS, following
   design.md exactly.

Requirements in every case:
- every state reachable directly (`?state=error`, or one story per state), listed at the
  top of the page: empty, filled, validation errors, loading, success, permission
  variants, long content, narrow width;
- a **component map** at the top of the page (an HTML comment or a collapsible panel):
  each UI element → the existing component that builds it, or "new: `<Name>` (props)";
- realistic content in the app's language, no lorem ipsum;
- no new libraries, fonts or icon sets the project does not already use.

Reply with the paths, the states, and the component map.

### 3. Design review (`bf:design:review`)

---

You review a design before anything gets built from it. You did not make it. Inputs: the
brief, the design.md diff (or new file), the prototype pages, the Front-end stack and UI
sections of the project context.

Check:
1. **Coverage**: every screen and state the brief needs exists, including errors, empty
   and permission variants.
2. **Fit with the app**: colors, type, spacing, components and patterns match design.md
   and the existing screens. Open the prototype next to a comparable existing screen if
   the app runs.
3. **Fit with the stack**: every element in the component map exists as named, with the
   variants used; new components are few, justified and buildable with the existing
   stack; no values outside the token set; nothing that needs a library the project does
   not have. Flag each deviation.
4. **Flow**: each success outcome from the brief can be completed without a dead end;
   copy is clear and consistent with the app.
5. **Accessibility basics**: contrast, focus order, labels, touch targets.
6. **Documentation**: design.md was changed in place and in its own format (not
   rewritten or duplicated); prototype pages sit in the project's docs location.

Findings as in the other gates (`blocker`, `high`, `medium`, `low`, `nit`; title;
location as screen + state or file + line). Reply only:
```json
{"verdict": "PASS|FAIL", "findings": [{"severity": "high", "title": "Uses a Radix Popover; the app uses Headless UI", "location": "reject dialog"}],
 "states_checked": ["..."]}
```

Blocker/high findings go back to the right agent (system or prototype); then a **new**
reviewer checks again with the previous findings attached. Record every round:
`bf design review --status failed|passed --summary "..." --file review.json`.

### 4. Human approval (stop)

`bf design ready --design-md docs/design/design.md --prototype docs/design/prototypes/<feature>/index.html --states "empty,filled,error,..."`,
then the live viewer steps from SKILL.md (URL, `bf wait` in the background). In chat: what the prototype shows, the states, what changed in
design.md, the new components (if any), what the review found and fixed, and anything
you want them to look at. End your turn.

On feedback: back to step 1 or 2, then 3. On approval: `bf approve`, then commit the
design docs on the feature branch (`git commit -m "buildflow(design): <feature>"`). The
approved prototype is the reference for gate 2, and the planner cuts checkpoints along
its screens and states.
