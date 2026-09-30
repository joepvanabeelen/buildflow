# Reporting

The human gets a report after every checkpoint and one at the end. `bf finish` and
`bf accept` write both markdown and HTML versions; your job is to post a readable chat
version and point to the files. Write in the run's language (`lang`), headings and table
labels included (for nl: gate gedrag/statisch/UI/review/docs, geslaagd/overgeslagen,
"Kosten", "Volgende"). Numbers come from `bf`, never from memory.

## After each checkpoint

Keep it to what someone scanning a terminal needs. Use this shape:

```
### cp03 · Leave approval rules ✓   (3 of 8)

Built: <one or two sentences, plain language, what now works>

| gate     | result | detail                                        |
|----------|--------|-----------------------------------------------|
| behavior | passed | 7 new tests, red for the right reason; 61/61 green |
| static   | passed | eslint, tsc, semgrep: 2 new, 2 fixed (1 high) |
| ui       | skipped| logic only                                    |
| review   | passed | 2 rounds; 3 issues found, 3 fixed (1 high)     |
| docs     | passed | docs/api/leave.md, CHANGELOG.md updated        |

Notable: <the one finding or decision worth knowing, or "nothing unusual">
Cost: 412k tokens · $3.18 · 14m 20s   |   run so far: 1.3M · $9.40 · 41m active
Commit: a1b2c3d · report: .buildflow/<slug>/reports/cp03.html
Next: cp04 · <title>
```

Mention it explicitly when a gate needed more than one attempt, when something was marked
`wontfix`, when the red run was not recorded or failed for the wrong reason, when a
learning was added, and when the implementer escalated to the session model. Low and nit
findings that stayed open (no fixer, by design) get one line with their count; the report
file lists them. The final report names the run's model profile.

The same in Dutch (`lang` nl):

```
### cp03 · Regels voor verlofgoedkeuring ✓   (3 van 8)

Gebouwd: <een of twee zinnen, gewone taal, wat nu werkt>

| gate     | uitkomst     | detail                                             |
|----------|--------------|----------------------------------------------------|
| gedrag   | geslaagd     | 7 nieuwe tests, eerst rood om de goede reden; 61/61 groen |
| statisch | geslaagd     | eslint, tsc, semgrep: 2 nieuw, 2 opgelost (1 hoog) |
| UI       | overgeslagen | alleen logica                                      |
| review   | geslaagd     | 2 rondes; 3 problemen gevonden, 3 opgelost         |
| docs     | geslaagd     | docs/api/leave.md, CHANGELOG.md bijgewerkt         |

Opvallend: <de ene bevinding of beslissing die het weten waard is, of "niets bijzonders">
Kosten: 412k tokens · $3.18 · 14m 20s   |   run tot nu toe: 1.3M · $9.40 · 41m actief
Commit: a1b2c3d · rapport: .buildflow/<slug>/reports/cp03.html
Volgende: cp04 · <titel>
```

## Final report (the review stop, and after accept)

Post a condensed version of `reports/final.md`:

1. One paragraph: what the feature now does, and your honest assessment of how solid it
   is (where you are confident, where you are less so and why).
2. How it measured up to the brief: each success outcome from `brief.md` with the
   checkpoint(s) that deliver it, and anything from the brief that did not make it.
3. Outcome numbers: checkpoints passed (and how many came from feedback), tests, review
   findings raised/fixed/open, UI differences found/fixed, human review rounds.
3a. Test-first: scenarios planned, new tests, and in how many checkpoints the red run was
   confirmed (the table "Test-first" in the final report). Say plainly where it was not.
3b. Deterministic checks: which tools ran, the per-checkpoint table from the final report
   (new, fixed, won't fix, pre-existing, tool errors), and what was not available. When
   no tools ran, say so plainly and why; do not let an empty table read as "clean".
4. The checkpoint table (gates, attempts, duration, cost, commit).
5. Cost and time (including the context, brief and design phases): total tokens with the split (input, cache write, cache read, output),
   API-equivalent cost, active time vs. wall-clock vs. waiting on the human, and the three
   most expensive roles or checkpoints. Say why when one stands out (e.g. a review loop
   that took four rounds).
6. Documentation: the feature docs gate result and every documentation file changed or
   created (design.md, prototype pages, docs pages, changelog), marking which were new.
   Open or accepted findings, and the learnings recorded.
7. Links: the live viewer URL (`bf serve --status`), `viewer.html`, `reports/final.html`, the branch.

At the review stop, add the test instructions for the human. After `accept`, offer to open a PR
and to publish the final report as a private Artifact for sharing.

## Cost caveat

Always label the dollar figure as API-equivalent at list prices. On a Claude subscription
the user pays a flat fee; the number is still the right way to compare runs. If
`bf cost` reports unpriced models or zero transcript files, say so instead of reporting
a misleading total.
