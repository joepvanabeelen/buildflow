#!/usr/bin/env python3
"""buildflow: state, gates, cost measurement, reports and viewer for a checkpoint-and-gate build.

Stdlib only. All run data lives in <project>/.buildflow/<slug>/.
Run `bf.py --help` or `bf.py <command> --help`.
"""
import argparse
import datetime as dt
import glob
import hashlib
import hmac
import html
import http.server
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CP_GATES = ["behavior", "static", "ui", "review", "docs"]  # per checkpoint, in this order
GATE_DONE = {"passed", "skipped"}
PHASES = ["intake", "brief", "awaiting_brief_approval", "design", "awaiting_design_approval",
          "planning", "awaiting_plan_approval", "building", "documenting", "awaiting_human_review", "paused", "done"]
WAIT_PHASES = {"awaiting_brief_approval", "awaiting_design_approval", "awaiting_plan_approval",
               "awaiting_human_review", "paused"}
APPROVAL_NEXT = {"awaiting_brief_approval": ("brief", "design"),
                 "awaiting_design_approval": ("design", "planning"),
                 "awaiting_plan_approval": ("plan", "building")}
# project files whose change makes the shared project context stale
# where scratch run data lives; project documentation (design.md, prototypes) must not end up here
SCRATCH_DIR = ".buildflow"
CONTEXT_KEY_FILES = re.compile(r"(^|/)(CLAUDE|AGENTS|README|CONTRIBUTING|DESIGN|design)\.md$|(^|/)(package\.json|pyproject\.toml|"
                               r"composer\.json|Gemfile|go\.mod|Cargo\.toml|tsconfig\.json|docker-compose\.ya?ml)$|(^|/)docs/")
TAG_RE = re.compile(r"^\s*bf:([a-z0-9_-]+):([a-z0-9_-]+)", re.I)


# ---------------------------------------------------------------- language of everything a human reads
# JSON keys, commands, file names and state values stay English; every sentence a person reads (status,
# next steps, refusals, reports) follows the run's `lang`. Before a run exists: `init --lang`, else the
# BUILDFLOW_LANG environment variable, else English.

LANGS = ("en", "nl")
LANG = None  # set by main() / load() from the active run


def lang_of(st=None):
    lg = st.get("lang") if isinstance(st, dict) else None
    if lg in LANGS:
        return lg
    if LANG in LANGS:
        return LANG
    env = (os.environ.get("BUILDFLOW_LANG") or "").strip().lower()[:2]
    return env if env in LANGS else "en"


def t(key, st=None, **kw):
    """Message from the catalog in the run's language."""
    e = MSG[key]
    s = e[1] if lang_of(st) == "nl" and len(e) > 1 else e[0]
    return s.format(**kw) if kw else s


def name_of(table, key, st=None):
    """Human label for a phase, gate, status or role; the key itself when unknown."""
    e = table.get(key)
    if not e:
        return str(key)
    return e[1] if lang_of(st) == "nl" else e[0]


PHASE_NAMES = {
    "intake": ("reading the project", "project lezen"), "brief": ("brief", "brief"),
    "awaiting_brief_approval": ("awaiting brief approval", "wacht op akkoord brief"), "design": ("design", "design"),
    "awaiting_design_approval": ("awaiting design approval", "wacht op akkoord design"), "planning": ("planning", "plannen"),
    "awaiting_plan_approval": ("awaiting plan approval", "wacht op akkoord plan"), "building": ("building", "bouwen"),
    "documenting": ("documenting", "documenteren"), "awaiting_human_review": ("awaiting your review", "wacht op jouw review"),
    "paused": ("paused", "gepauzeerd"), "done": ("done", "klaar")}
GATE_NAMES = {"behavior": ("behavior", "gedrag"), "static": ("static", "statisch"), "ui": ("UI", "UI"),
              "review": ("review", "review"), "docs": ("docs", "docs")}
STATUS_NAMES = {
    "pending": ("pending", "open"), "running": ("running", "bezig"), "passed": ("passed", "geslaagd"),
    "failed": ("failed", "gefaald"), "skipped": ("skipped", "overgeslagen"), "interrupted": ("interrupted", "onderbroken"),
    "in_progress": ("in progress", "bezig"), "blocked": ("blocked", "geblokkeerd"), "open": ("open", "open"),
    "fixed": ("fixed", "opgelost"), "wontfix": ("won't fix", "bewust niet opgelost"), "approved": ("approved", "goedgekeurd"),
    "awaiting": ("awaiting approval", "wacht op akkoord"), "not_needed": ("not needed", "niet nodig"),
    "done": ("done", "klaar"), "given": ("given", "aangeleverd"), "brainstorm": ("brainstorm", "brainstorm"),
    "resumed": ("resumed", "hervat"), "auto": ("automatically", "automatisch"), "manual": ("by hand", "met de hand")}
STAGE_NAMES = {"brief": ("brief", "brief"), "design": ("design", "design"), "plan": ("plan", "plan"),
               "review": ("review", "review"), "checkpoint": ("checkpoint", "checkpoint")}
# role tags stay as they are in the transcripts (bf:cpNN:<role>); reports show a readable name
ROLE_NAMES = {
    "orchestrator": ("orchestrator", "orchestrator"), "subagent (untagged)": ("subagent (untagged)", "subagent (zonder tag)"),
    "project": ("project scout", "projectverkenner"), "feature": ("feature scout", "featureverkenner"),
    "system": ("design system", "designsysteem"), "prototype": ("prototype", "prototype"), "health": ("health check", "gezondheidscheck"),
    "planner": ("planner", "planner"), "tests-plan": ("test planner", "testplanner"), "tests": ("test writer", "tests schrijven"),
    "implement": ("implementer", "implementatie"), "verify": ("test run", "testrun"), "static-fix": ("static fixes", "statische fixes"),
    "ui-visual": ("UI visual review", "UI-review uiterlijk"), "ui-behavior": ("UI behavior review", "UI-review gedrag"),
    "ui-fix": ("UI fixes", "UI-fixes"), "adversary": ("adversarial review", "adversarial review"), "fixer": ("fixer", "fixer"),
    "docs": ("docs writer", "docs schrijven"), "docs-review": ("docs review", "docs-review"), "feedback": ("feedback", "feedback"),
    "review": ("review", "review"), "ui-review": ("UI review", "UI-review"),
    "runner": ("checkpoint runner", "checkpoint-runner")}

# ---------------------------------------------------------------- model profile: which model each subagent role runs on
# lean (default for new runs): planner and adversary on the session model, pure test runs and the health check on haiku,
# everything else on sonnet. thorough: the session model everywhere except the health check and pure test runs (the
# behavior before profiles existed, so runs without a profile field are thorough). "inherit" means: leave the Agent
# call's `model` field out, so the subagent runs on the session model.
PROFILES = ("lean", "thorough")
PROFILE_ALIASES = {"lean": "lean", "zuinig": "lean", "thorough": "thorough", "grondig": "thorough"}
PROFILE_NAMES = {"lean": ("lean", "zuinig"), "thorough": ("thorough", "grondig")}
INHERIT = "inherit"
PROFILE_DEFAULT_MODEL = {"lean": "sonnet", "thorough": INHERIT}
PROFILE_MODELS = {"lean": {"planner": INHERIT, "adversary": INHERIT, "health": "haiku", "verify": "haiku", "runner": INHERIT},
                  "thorough": {"health": "sonnet", "verify": "sonnet"}}
MODEL_ROLES = ["project", "feature", "system", "prototype", "review", "health", "planner", "tests-plan", "tests", "implement",
               "verify", "static-fix", "ui-visual", "ui-behavior", "ui-review", "ui-fix", "adversary", "fixer", "docs",
               "docs-review", "feedback", "runner"]
ESCALATE_GATE = {"implement": "behavior"}  # role -> the gate whose failures move it to the session model
ESCALATE_AFTER = 2


def profile_of(st):
    if not st:
        return "lean"  # before a run exists: what `init` would choose
    return st.get("profile") if st.get("profile") in PROFILES else "thorough"


def model_for(st, role, cp=None, gate=None):
    """(model, escalation note) for a subagent role in this run's profile."""
    prof = profile_of(st)
    model = PROFILE_MODELS[prof].get(role, PROFILE_DEFAULT_MODEL[prof])
    g = gate or ESCALATE_GATE.get(role)
    if (model != INHERIT and cp is not None and role in ESCALATE_GATE and g in cp["gates"]
            and cp["gates"][g]["status"] not in GATE_DONE):
        fails = sum(1 for x in cp["gates"][g]["attempts"] if x.get("result") == "failed")
        if fails >= ESCALATE_AFTER:
            return INHERIT, t("model_escalated", st, cp=cp["id"], n=fails, gate=name_of(GATE_NAMES, g, st))
    return model, ""


def model_label(m, st=None):
    return t("session_model", st) if m == INHERIT else m


def models_line(st):
    """One line for bf status: the default model of the profile and the roles that differ."""
    prof = profile_of(st)
    groups = {}
    for r in MODEL_ROLES:
        m = model_for(st, r)[0]
        if m != PROFILE_DEFAULT_MODEL[prof]:
            groups.setdefault(m, []).append(r)
    exc = "; ".join(f"{model_label(m, st)}: {', '.join(rs)}" for m, rs in groups.items())
    return t("status_models", st, default=model_label(PROFILE_DEFAULT_MODEL[prof], st), exc=exc or "-")


KIND_NAMES ={"unit": ("unit", "unit"), "integration": ("integration", "integratie"), "e2e": ("e2e", "e2e"),
              "ui-gate": ("UI gate", "UI-gate")}
CHECK_NAMES = {"clean": ("clean", "schoon"), "findings": ("findings", "bevindingen"), "skipped": ("skipped", "overgeslagen"),
               "crashed": ("crashed", "gecrasht"), "timeout": ("timed out", "time-out")}


def check_result(c, st=None):
    """One check's outcome for people: what is new for this checkpoint versus what the baseline already had."""
    if c.get("new") is None or c.get("status") in ("crashed", "timeout", "skipped"):
        return name_of(CHECK_NAMES, c.get("status"), st) + (f" ({c['findings']})" if c.get("findings") else "")
    if not c["new"]:
        return name_of(CHECK_NAMES, "clean", st) + (f" ({t('n_baseline', st, n=c['baseline'])})" if c.get("baseline") else "")
    return t("n_new", st, n=c["new"]) + (f", {t('n_baseline', st, n=c['baseline'])}" if c.get("baseline") else "")


BUCKET_NAMES = {"planning": ("planning", "plannen"), "review & feedback": ("review & feedback", "review & feedback"),
                "context": ("context", "context"), "brief": ("brief", "brief"), "design": ("design", "design")}

# ---------------------------------------------------------------- message catalog: key -> (en, nl)
# Commands, flags, file names and gate keys inside messages stay as they are: they are what you type.

MSG = {
    # general words
    "then": ("Then", "Daarna"), "next_l": ("next", "volgende stap"), "yes": ("yes", "ja"), "no": ("no", "nee"),
    "active_l": ("active", "actief"), "from_l": ("from", "vanuit"), "none_paren": ("(none)", "(geen)"),
    "blocking": ("blocking", "blokkerend"), "report_only": ("report only", "alleen rapporteren"),
    "not_available": ("not available", "niet beschikbaar"), "evidence": ("evidence", "bewijs"),
    "findings_l": ("findings", "bevindingen"), "wontfix_l": ("won't fix", "bewust niet opgelost"),
    "phase_l": ("phase", "fase"), "report_l": ("report", "rapport"), "final_report_l": ("final report", "eindrapport"),
    "paused_l": ("paused", "gepauzeerd"), "resumed_l": ("resumed", "hervat"), "handled_l": ("handled", "verwerkt"),
    "sessions_l": ("sessions", "sessies"), "feature_docs_l": ("feature docs", "documentatie van de feature"),
    "mode_interactive": ("interactive", "interactief"), "mode_auto": ("auto", "automatisch"),
    "no_run": ("no active buildflow run here. Start one with `bf.py init`.",
               "hier loopt geen buildflow-run. Start er een met `bf.py init`."),
    "state_missing": ("state not found: {p}", "state niet gevonden: {p}"),
    "unknown_cp": ("unknown checkpoint {cid}", "onbekende checkpoint {cid}"),
    "unknown_phase": ("unknown phase {phase}; use one of {phases}", "onbekende fase {phase}; kies uit {phases}"),
    "not_found": ("not found: {p}", "niet gevonden: {p}"),
    "expected_kv": ("expected key=value, got {kv}", "verwacht key=value, kreeg {kv}"),

    # default skip reasons (stored in the run)
    "skip_not_needed": ("not needed for this checkpoint", "niet nodig voor deze checkpoint"),
    "skip_docs_migrated": ("run started before the docs gate existed", "run gestart voordat de docs-gate bestond"),
    "skip_static_migrated": ("added after this checkpoint", "toegevoegd na deze checkpoint"),
    "skip_no_tools": ("no deterministic tools available: {why}", "geen deterministische tools beschikbaar: {why}"),

    # next steps
    "na_intake": ("Intake: `bf.py context --check`; if missing or stale run the context scout, then "
                  "`bf.py context --project .buildflow/context.md --feature <run>/context-feature.md`.",
                  "Intake: `bf.py context --check`; ontbreekt de context of is hij verouderd, laat dan de contextverkenner "
                  "lopen en daarna `bf.py context --project .buildflow/context.md --feature <run>/context-feature.md`."),
    "na_intake_done": ("Intake done: `bf.py phase brief` and start the brainstorm with the user.",
                       "Intake klaar: `bf.py phase brief` en begin de brainstorm met de gebruiker."),
    "na_brief": ("Brief: brainstorm with the user, write brief.md, then `bf.py brief --file <run>/brief.md`.",
                 "Brief: brainstorm met de gebruiker, schrijf brief.md en daarna `bf.py brief --file <run>/brief.md`."),
    "na_wait_brief": ("Waiting for the human to approve the brief, in chat or in the live viewer (`bf.py wait` / `bf.py inbox`; then `bf.py approve`).",
                      "Wacht op akkoord op de brief, in de chat of in de live viewer (`bf.py wait` / `bf.py inbox`; daarna `bf.py approve`)."),
    "na_design_decide": ("Decide on design: `bf.py design needed --reason ...` or `bf.py design not-needed --reason ...`.",
                         "Besluit over design: `bf.py design needed --reason ...` of `bf.py design not-needed --reason ...`."),
    "na_design_make": ("Design: make design.md/prototype, run the design review, record it with `bf.py design review --status passed|failed`.",
                       "Design: maak design.md en het prototype, laat de design-review lopen en leg die vast met `bf.py design review --status passed|failed`."),
    "na_design_ready": ("Design reviewed: `bf.py design ready --design-md ... --prototype ...`, then stop for the human.",
                        "Design gereviewd: `bf.py design ready --design-md ... --prototype ...` en stop dan voor akkoord."),
    "na_wait_design": ("Waiting for the human to approve the design and prototype, in chat or in the live viewer (then `bf.py approve`).",
                       "Wacht op akkoord op het design en prototype, in de chat of in de live viewer (daarna `bf.py approve`)."),
    "na_plan": ("Planning: run the checkpoint planner, then `bf.py plan --file plan.json`.",
                "Plannen: laat de checkpoint-planner lopen, daarna `bf.py plan --file plan.json`."),
    "na_tests": ("Planning: run the test planner (a Given/When/Then scenario per test), then `bf.py tests --file tests.json`.",
                 "Plannen: laat de testplanner lopen (per test een scenario Gegeven/Als/Dan), daarna `bf.py tests --file tests.json`."),
    "na_plan_done": ("Planning done: `bf.py phase awaiting_plan_approval`, `bf.py serve --detach`, then stop for the human.",
                     "Plan klaar: `bf.py phase awaiting_plan_approval`, `bf.py serve --detach` en stop dan voor akkoord."),
    "na_wait_plan": ("Waiting for the human to approve the plan, in chat or in the live viewer (then `bf.py approve`).",
                     "Wacht op akkoord op het plan, in de chat of in de live viewer (daarna `bf.py approve`)."),
    "na_documenting": ("All checkpoints passed. Feature docs gate: update the project documentation for the feature as a whole, "
                       "review it, then `bf.py docs --status passed|failed`.",
                       "Alle checkpoints zijn geslaagd. Docs-gate van de feature: werk de projectdocumentatie bij voor de feature "
                       "als geheel, laat die reviewen en daarna `bf.py docs --status passed|failed`."),
    "na_wait_review": ("Waiting for human review of the finished feature, in chat or in the live viewer (feedback -> `bf.py feedback`, accept -> `bf.py accept`).",
                       "Wacht op de review van de gebruiker, in de chat of in de live viewer (feedback -> `bf.py feedback`, akkoord -> `bf.py accept`)."),
    "na_paused": ("Paused: {why}. Resume with `bf.py resume`.", "Gepauzeerd: {why}. Verder met `bf.py resume`."),
    "na_done": ("Done.", "Klaar."),
    "na_start": ("Start {cp} ({title}): `bf.py start {cp}`.", "Start {cp} ({title}): `bf.py start {cp}`."),
    "na_when": (" ({err} at {at})", " ({err} om {at})"),
    "na_interrupted": ("{cp} gate `{gate}` was interrupted{when}. If its subagent is still running or already finished: "
                       "`bf.py resume --running {cp}:{gate}` (continues the same attempt), then record its result. "
                       "If it is gone: `bf.py resume --redo {cp}:{gate}` and redo that step with a fresh subagent.",
                       "Gate {gname} van {cp} is onderbroken{when}. Loopt de subagent nog of is hij al klaar: "
                       "`bf.py resume --running {cp}:{gate}` (dezelfde poging gaat door) en leg daarna het resultaat vast. "
                       "Is hij weg: `bf.py resume --redo {cp}:{gate}` en doe die stap opnieuw met een verse subagent."),
    "na_static": ("{cp} gate `static` is {status}: {hint}.", "Gate statisch van {cp} staat op {status}: {hint}."),
    "na_behavior": ("{cp} gate `behavior` is {status}. Test first: the test writer writes the planned scenarios as tests and "
                    "runs them; record the red run with `bf.py gate {cp} behavior running --data '{{\"red\":...}}'`, then the "
                    "implementer makes them green and you record `bf.py gate {cp} behavior passed|failed`.",
                    "Gate gedrag van {cp} staat op {status}. Test eerst: de testschrijver zet de geplande scenario's om in tests en "
                    "draait ze; leg de rode run vast met `bf.py gate {cp} behavior running --data '{{\"red\":...}}'`, daarna "
                    "maakt de implementer ze groen en leg je `bf.py gate {cp} behavior passed|failed` vast."),
    "na_gate": ("{cp} gate `{gate}` is {status}. Run gate {gate} and record it with `bf.py gate {cp} {gate} passed|failed`.",
                "Gate {gname} van {cp} staat op {status}. Voer de gate uit en leg hem vast met `bf.py gate {cp} {gate} passed|failed`."),
    "na_finish": ("All gates of {cp} passed: commit and run `bf.py finish {cp}`.",
                  "Alle gates van {cp} zijn geslaagd: commit en draai `bf.py finish {cp}`."),
    "na_all_passed": ("All checkpoints passed: `bf.py phase awaiting_human_review`.",
                      "Alle checkpoints zijn geslaagd: `bf.py phase awaiting_human_review`."),
    "ow_docs": ("feature docs gate is {status}", "docs-gate van de feature staat op {status}"),
    "ow_cp": ("{cp} {title}: open gates {gates}", "{cp} {title}: open gates {gates}"),
    "ow_finish": ("(finish/commit)", "(afronden/commit)"),
    "inbox_hint": ("{n} unhandled message(s) from the viewer: run `bf.py inbox`, act on them, then `bf.py inbox handled <id> --note \"...\"`.",
                   "{n} onverwerkt(e) bericht(en) uit de viewer: draai `bf.py inbox`, handel ze af en daarna `bf.py inbox handled <id> --note \"...\"`."),
    "note_approved": ("{stage} approved", "{stage} goedgekeurd"),
    "note_accepted": ("feature accepted", "feature geaccepteerd"),

    # static gate
    "static_hint_unset": ("no deterministic checks are configured for this run: record them (`bf.py static detect`, then "
                          "`bf.py static config --file .buildflow/static.json`, see references/gate-static.md) or skip with "
                          "`bf.py gate {cp} static skipped --reason \"...\"`",
                          "voor deze run zijn geen deterministische checks ingesteld: leg ze vast (`bf.py static detect`, daarna "
                          "`bf.py static config --file .buildflow/static.json`, zie references/gate-static.md) of sla over met "
                          "`bf.py gate {cp} static skipped --reason \"...\"`"),
    "static_hint_none": ("no tools available ({why}): `bf.py gate {cp} static skipped --reason \"no deterministic tools available\"`",
                         "geen tools beschikbaar ({why}): `bf.py gate {cp} static skipped --reason \"geen deterministische tools beschikbaar\"`"),
    "static_hint_run": ("`bf.py static run {cp}`; new blocking findings go to a `bf:{cp}:static-fix` subagent, then run it again "
                        "until clean, then `bf.py gate {cp} static passed`",
                        "`bf.py static run {cp}`; nieuwe blokkerende bevindingen gaan naar een `bf:{cp}:static-fix`-subagent, draai "
                        "daarna opnieuw tot het schoon is en dan `bf.py gate {cp} static passed`"),
    "usage_static": ("usage: bf.py static {action} cpNN ...", "gebruik: bf.py static {action} cpNN ..."),
    "static_none_reason": ("--none needs --reason (what was looked for and why nothing can run)",
                           "--none heeft --reason nodig (waar is naar gezocht en waarom kan er niets draaien)"),
    "check_needs_name": ("every check needs a name and a cmd: {c}", "elke check heeft een name en een cmd nodig: {c}"),
    "check_dup": ("duplicate check name {name}", "dubbele checknaam {name}"),
    "check_installs": ("check {name} would install something ({cmd}). A check never installs at run time; add the tool as a "
                       "dev dependency in its own commit before the baseline, or use a zero-install runner (uvx, pipx run, docker run).",
                       "check {name} zou iets installeren ({cmd}). Een check installeert nooit tijdens het draaien; voeg de tool "
                       "toe als dev-dependency in een eigen commit vóór de baseline, of gebruik een runner zonder installatie "
                       "(uvx, pipx run, docker run)."),
    "check_kind": ("check {name}: kind must be one of {kinds}", "check {name}: kind moet een van deze zijn: {kinds}"),
    "check_scope": ("check {name}: scope must be changed or all", "check {name}: scope moet changed of all zijn"),
    "check_format": ("check {name}: format must be one of {formats}", "check {name}: format moet een van deze zijn: {formats}"),
    "check_npx": ("warning: {name} uses npx without --no-install; npx may download the package. Prefer `npx --no-install {name}` "
                  "or the node_modules/.bin path.",
                  "let op: {name} gebruikt npx zonder --no-install; npx kan het pakket downloaden. Gebruik liever "
                  "`npx --no-install {name}` of het pad in node_modules/.bin."),
    "baseline_not_covered": ("note: the baseline does not cover {names}; run `bf.py static baseline` on a clean tree (at a "
                             "checkpoint boundary) or their pre-existing findings count as new.",
                             "let op: de baseline dekt {names} niet; draai `bf.py static baseline` op een schone tree (tussen twee "
                             "checkpoints), anders tellen hun bestaande bevindingen als nieuw."),
    "checks_recorded": ("{n} static check(s) recorded.", "{n} statische check(s) vastgelegd."),
    "none_available": ("None available: {why}", "Niets beschikbaar: {why}"),
    "checks_next": ("Show this set at the plan stop; next: `bf.py static baseline` on a clean tree before `bf.py start cp01`.",
                    "Laat deze set zien bij de planstop; daarna `bf.py static baseline` op een schone tree, vóór `bf.py start cp01`."),
    "checks_next_none": ("The static gate of each checkpoint will be recorded as skipped with this reason.",
                         "De statische gate van elke checkpoint wordt met deze reden als overgeslagen vastgelegd."),
    "no_static_run": ("no static run for {cp} yet", "nog geen statische run voor {cp}"),
    "baseline_no_config": ("no static checks configured: `bf.py static config --file ...` first",
                           "geen statische checks ingesteld: eerst `bf.py static config --file ...`"),
    "baseline_nothing": ("no checks configured (none available); nothing to baseline",
                         "geen checks ingesteld (niets beschikbaar); er valt niets vast te leggen"),
    "baseline_dirty": ("the working tree is not clean; the baseline must describe the code before the feature. Commit or stash "
                       "first (or --allow-dirty if these changes are not part of the feature).",
                       "de working tree is niet schoon; de baseline moet de code van vóór de feature beschrijven. Eerst committen "
                       "of stashen (of --allow-dirty als deze wijzigingen niet bij de feature horen)."),
    "baseline_done": ("baseline: {n} pre-existing finding(s) at {commit}; they will not block a checkpoint.",
                      "baseline: {n} bestaande bevinding(en) op {commit}; die blokkeren geen checkpoint."),
    "baseline_tool_errors": ("WARNING: these checks failed at baseline, fix the command before building:",
                             "LET OP: deze checks faalden bij de baseline, repareer het commando voordat je gaat bouwen:"),
    "usage_mark": ("usage: bf.py static mark {cp} <finding id>... wontfix --reason \"...\"",
                   "gebruik: bf.py static mark {cp} <finding id>... wontfix --reason \"...\""),
    "mark_fixed_refused": ("findings are marked fixed by running the checks again: `bf.py static run {cp}` (whatever no longer "
                           "shows up is recorded as fixed)",
                           "bevindingen worden als opgelost gemarkeerd door de checks opnieuw te draaien: `bf.py static run {cp}` "
                           "(wat niet meer terugkomt, telt als opgelost)"),
    "wontfix_reason": ("wontfix needs --reason", "wontfix heeft --reason nodig"),
    "no_finding": ("no finding with id {ids} in {cp} (see `bf.py static show {cp}`)",
                   "geen bevinding met id {ids} in {cp} (zie `bf.py static show {cp}`)"),
    "secret_blocker": ("a secret stays a blocker: remove it from the code and rotate it. Only a proven false positive may be "
                       "accepted, with --force and the reason.",
                       "een secret blijft blokkerend: haal hem uit de code en roteer hem. Alleen een aangetoond vals positief mag "
                       "je accepteren, met --force en de reden."),
    "marked_wontfix": ("{n} finding(s) marked wontfix on {cp}; blocking open: {open}",
                       "{n} bevinding(en) op {cp} als bewust niet opgelost gemarkeerd; blokkerend open: {open}"),
    "static_not_building": ("static checks run while building (phase {phase})", "statische checks draaien tijdens het bouwen (fase {phase})"),
    "cp_not_started": ("{cp} has not started", "{cp} is nog niet gestart"),
    "static_earlier": ("cannot run the static gate: earlier gate(s) {gates} not passed on {cp}",
                       "de statische gate kan niet: eerdere gate(s) {gates} van {cp} zijn niet geslaagd"),
    "no_baseline_warn": ("warning: no baseline recorded (`bf.py static baseline`); every finding counts as new.",
                         "let op: geen baseline vastgelegd (`bf.py static baseline`); elke bevinding telt als nieuw."),
    "static_run_line": ("{cp} · static run {run}: {new} new finding(s), {open} blocking open, {fixed} fixed, {wontfix} won't fix, "
                        "{pre} pre-existing (baseline), {errors} tool error(s)",
                        "{cp} · statische run {run}: {new} nieuwe bevinding(en), {open} blokkerend open, {fixed} opgelost, "
                        "{wontfix} bewust niet opgelost, {pre} bestaand (baseline), {errors} toolfout(en)"),
    "recheck_clean": ("re-check clean: the static gate stays passed", "hercontrole schoon: de statische gate blijft geslaagd"),
    "recheck_reopened": ("static gate reopened by the re-check: fix via bf:{cp}:static-fix, `bf.py static run {cp}` again, then "
                         "`bf.py gate {cp} static passed`",
                         "statische gate heropend door de hercontrole: fixen via bf:{cp}:static-fix, opnieuw `bf.py static run {cp}`, "
                         "daarna `bf.py gate {cp} static passed`"),
    "static_next_failed": ("next: `bf.py gate {cp} static failed --summary \"...\"`, give the findings to a bf:{cp}:static-fix "
                           "subagent, then `bf.py static run {cp}` again (or `bf.py static mark {cp} <id> wontfix --reason ...`)",
                           "volgende stap: `bf.py gate {cp} static failed --summary \"...\"`, geef de bevindingen aan een "
                           "bf:{cp}:static-fix-subagent en draai daarna opnieuw `bf.py static run {cp}` (of "
                           "`bf.py static mark {cp} <id> wontfix --reason ...`)"),
    "static_next_passed": ("next: `bf.py gate {cp} static passed`", "volgende stap: `bf.py gate {cp} static passed`"),
    "recheck_summary": ("re-check after later changes", "hercontrole na latere wijzigingen"),
    "recheck_blocking": (": {n} new blocking finding(s)", ": {n} nieuwe blokkerende bevinding(en)"),
    "static_attempt_summary": ("run {run}: {checks} check(s), {new} new, {open} blocking open, {fixed} fixed, {pre} pre-existing",
                               "run {run}: {checks} check(s), {new} nieuw, {open} blokkerend open, {fixed} opgelost, {pre} bestaand"),
    "static_explain": ("The static gate runs the deterministic checks (linters, type checks, SAST, secrets, dependency audit).",
                       "De statische gate draait de deterministische checks (linters, typecheckers, SAST, secrets, dependency-audit)."),
    "static_added_mid": ("It was added to buildflow while this checkpoint was in progress.",
                         "Die is aan buildflow toegevoegd terwijl deze checkpoint liep."),

    # init / runs / plan / tests / phases
    "run_exists": ("run '{slug}' already exists. Use `bf.py use {slug}` to continue it, or --force to overwrite.",
                   "run '{slug}' bestaat al. Ga verder met `bf.py use {slug}`, of overschrijf met --force."),
    "active_unfinished": ("the active run '{cur}' is not finished (phase {phase}). Continue it (`bf.py use {cur}`), or start this one "
                          "anyway with --park, which pauses '{cur}' so it can be resumed later.",
                          "de actieve run '{cur}' is nog niet klaar (fase {phase}). Ga daarmee verder (`bf.py use {cur}`), of start "
                          "deze toch met --park: dan wordt '{cur}' gepauzeerd en kun je hem later hervatten."),
    "parked_reason": ("parked: started run '{slug}'", "geparkeerd: run '{slug}' gestart"),
    "parked": ("parked '{cur}' (paused from {phase}; resume with `bf.py use {cur}` and `bf.py resume`)",
               "'{cur}' geparkeerd (gepauzeerd vanuit {phase}; hervatten met `bf.py use {cur}` en `bf.py resume`)"),
    "learn_head": ("Every agent reads this before starting work. Newest last.", "Elke agent leest dit voordat hij begint. Nieuwste onderaan."),
    "learn_carried": ("Carried over from earlier runs", "Overgenomen uit eerdere runs"),
    "redirect_written": ("redirect written: {rd}/redirect -> {root}", "redirect geschreven: {rd}/redirect -> {root}"),
    "initialised": ("initialised run '{slug}' in {d}", "run '{slug}' aangemaakt in {d}"),
    "no_such_run": ("no run '{slug}' under {d}", "geen run '{slug}' in {d}"),
    "active_run": ("active run: {slug}", "actieve run: {slug}"),
    "no_runs": ("no buildflow runs in this project yet", "nog geen buildflow-runs in dit project"),
    "overview_line": ("overview: {path}  (* = active run)", "overzicht: {path}  (* = actieve run)"),
    "plan_empty": ("plan has no checkpoints", "het plan heeft geen checkpoints"),
    "plan_started": ("checkpoints already started; use --append to add more", "er zijn al checkpoints gestart; voeg toe met --append"),
    "plan_loaded": ("{n} checkpoints loaded ({total} total).", "{n} checkpoints geladen ({total} in totaal)."),
    "plan_many_small": ("note: {n} checkpoints for a small project ({size}). The planner's rule is 3 to 5; merge checkpoints "
                        "unless there is a reason not to.",
                        "let op: {n} checkpoints voor een klein project ({size}). De regel voor de planner is 3 tot 5; voeg "
                        "checkpoints samen, tenzij daar een reden voor is."),
    "plan_no_size": ("note: the plan has no \"size\" estimate ({\"class\":\"small|medium|large\",\"est_lines\":N}), so bf cannot "
                     "check the number of checkpoints against it.",
                     "let op: het plan heeft geen \"size\"-schatting ({\"class\":\"small|medium|large\",\"est_lines\":N}), dus bf "
                     "kan het aantal checkpoints daar niet aan toetsen."),
    "plan_docs_no_scope": ("note: docs gate skipped for {cps}: no docs_scope. Give a docs_scope if the checkpoint does touch docs.",
                           "let op: docs-gate overgeslagen voor {cps}: geen docs_scope. Geef een docs_scope als de checkpoint wel docs raakt."),
    "plan_ui_no_scope": ("note: UI gate without ui_scope for {cps}; the UI reviewer then does not know what to judge.",
                         "let op: UI-gate zonder ui_scope voor {cps}; de UI-reviewer weet dan niet wat hij moet beoordelen."),
    "skip_docs_no_scope": ("no docs_scope: this checkpoint does not touch documentation",
                           "geen docs_scope: deze checkpoint raakt geen documentatie"),
    "tests_attached": ("{n} planned tests attached ({sc} with a Given/When/Then scenario).",
                       "{n} geplande tests toegevoegd ({sc} met een scenario Gegeven/Als/Dan)."),
    "tests_no_scenario": ("note: {n} test(s) have no Given/When/Then scenario; the viewer shows only their name.",
                          "let op: {n} test(s) hebben geen scenario Gegeven/Als/Dan; de viewer toont alleen de naam."),
    "tests_uncovered": ("note: done_when items without a test: {items}", "let op: done_when-punten zonder test: {items}"),
    "block_brief": ("the brief is not approved (`bf.py brief`, then the human approves)",
                    "de brief is niet goedgekeurd (`bf.py brief`, daarna keurt de gebruiker goed)"),
    "block_design": ("the design stage is not settled (`bf.py design needed|not-needed`)",
                     "de designstap is niet afgerond (`bf.py design needed|not-needed`)"),
    "cannot_phase": ("cannot go to {phase}: ", "kan niet naar {phase}: "),
    "nothing_waiting": ("nothing is waiting for approval (phase {phase})", "er wacht niets op akkoord (fase {phase})"),
    "approve_no_cps": ("nothing to approve: no checkpoints", "niets om goed te keuren: geen checkpoints"),
    "cannot_approve_plan": ("cannot approve the plan: ", "het plan kan niet worden goedgekeurd: "),
    "approved_line": ("{stage} approved -> {nxt}", "{stage} goedgekeurd -> {nxt}"),
    "approved_closed": (" (viewer request {ids} handled)", " (verzoek {ids} uit de viewer verwerkt)"),
    "plan_not_approved": ("plan is not approved yet (phase {phase}). Wait for the human, or in --mode auto run `bf.py approve --note auto`.",
                          "het plan is nog niet goedgekeurd (fase {phase}). Wacht op de gebruiker, of draai in --mode auto `bf.py approve --note auto`."),
    "depends_on": ("{cp} depends on {dep}, which has not passed", "{cp} hangt af van {dep}, en die is niet geslaagd"),
    "earlier_cp": ("{cp} has not passed yet. Checkpoints run in order (use --force to override).",
                   "{cp} is nog niet geslaagd. Checkpoints gaan op volgorde (--force om dat te negeren)."),
    "start_no_baseline": ("static checks are configured but there is no baseline yet: run `bf.py static baseline` on a clean tree "
                          "first, so findings that were already there do not block this checkpoint.",
                          "er zijn statische checks ingesteld maar nog geen baseline: draai eerst `bf.py static baseline` op een "
                          "schone tree, zodat bevindingen die er al waren deze checkpoint niet blokkeren."),
    "cp_started": ("{cp} started: {title}", "{cp} gestart: {title}"),

    # gates
    "gate_one_of": ("gate must be one of {gates}", "gate moet een van deze zijn: {gates}"),
    "gate_order": ("cannot mark {gate} {status}: earlier gate(s) {gates} not passed on {cp}.",
                   "{gate} kan niet op {status}: eerdere gate(s) {gates} van {cp} zijn niet geslaagd."),
    "static_skip_reason": ("skipping the static gate needs --reason (e.g. no code changed, no tools available, added mid-checkpoint)",
                           "de statische gate overslaan kan alleen met --reason (bijvoorbeeld geen code gewijzigd, geen tools, halverwege toegevoegd)"),
    "static_skip_force": ("static checks are configured for this run, so {cp} runs them: `bf.py static run {cp}`. Skipping anyway "
                          "needs --force with the reason.",
                          "voor deze run zijn statische checks ingesteld, dus {cp} draait ze: `bf.py static run {cp}`. Toch "
                          "overslaan kan alleen met --force en de reden."),
    "static_pass_norun": ("cannot pass static: no static run for {cp} yet. {hint}.",
                          "statisch kan niet slagen: nog geen statische run voor {cp}. {hint}."),
    "static_pass_changed": ("cannot pass static: the code changed since the last static run. Run `bf.py static run {cp}` again.",
                            "statisch kan niet slagen: de code is gewijzigd sinds de laatste statische run. Draai opnieuw `bf.py static run {cp}`."),
    "static_pass_blockers": ("cannot pass static: {n} new blocking finding(s) open ({tools}). Fix them (bf:{cp}:static-fix, then "
                             "`bf.py static run {cp}`) or `bf.py static mark {cp} <id> wontfix --reason ...`.",
                             "statisch kan niet slagen: {n} nieuwe blokkerende bevinding(en) open ({tools}). Los ze op "
                             "(bf:{cp}:static-fix, daarna `bf.py static run {cp}`) of `bf.py static mark {cp} <id> wontfix --reason ...`."),
    "gate_blockers": ("cannot pass {gate}: {n} open blocker/high findings. Fix them or mark them wontfix with a reason.",
                      "{gate} kan niet slagen: {n} open blocker/high-bevindingen. Los ze op of markeer ze als wontfix met een reden."),
    "gate_medium": ("cannot pass {gate}: {n} medium finding(s) not fixed, without a fix round. Give them one fix round (then record "
                    "\"metrics\":{{\"fix_rounds\":1}}), or give each one a \"reason\". Low and nit may stay open.",
                    "{gate} kan niet slagen: {n} medium-bevinding(en) niet opgelost, zonder fixronde. Geef ze één fixronde (leg dan "
                    "\"metrics\":{{\"fix_rounds\":1}} vast), of geef elk een \"reason\". Low en nit mogen open blijven."),
    "behavior_failed_tests": ("cannot pass behavior: tests_failed > 0", "gedrag kan niet slagen: tests_failed > 0"),
    "behavior_wrong_red": ("cannot pass behavior: the recorded red run of {cp} failed for the wrong reason (a broken test, not missing "
                           "behavior). Fix the tests, record a new red run (`--data '{{\"red\":...}}'`), then pass.",
                           "gedrag kan niet slagen: de vastgelegde rode run van {cp} faalde om de verkeerde reden (een kapotte test, "
                           "niet ontbrekend gedrag). Repareer de tests, leg een nieuwe rode run vast (`--data '{{\"red\":...}}'`) en "
                           "rond dan af."),
    "red_only_behavior": ("note: red/green evidence belongs to the behavior gate; ignored here.",
                          "let op: rood/groen-bewijs hoort bij de gedrag-gate; hier genegeerd."),
    "red_recorded": ("red run recorded: {n} test(s) fail, {why}.", "rode run vastgelegd: {n} test(s) falen, {why}."),
    "right_reason": ("for the right reason", "om de goede reden"),
    "wrong_reason": ("for the wrong reason", "om de verkeerde reden"),
    "reason_unknown": ("reason not stated", "reden niet vermeld"),
    "pause_failed": ("{cp} gate {gate} failed {n} times; needs a human decision",
                     "{cp} gate {gate} is {n} keer gefaald; er is een besluit van de gebruiker nodig"),
    "finish_open": ("cannot finish {cp}: gates not passed: {gates}", "{cp} kan niet worden afgerond: niet geslaagde gates: {gates}"),
    "finish_changed": ("cannot finish {cp}: the code changed after the static gate passed (review or docs fixes). Run "
                       "`bf.py static run {cp}` again; if it finds nothing new the gate stays passed.",
                       "{cp} kan niet worden afgerond: de code is gewijzigd nadat de statische gate slaagde (review- of docs-fixes). "
                       "Draai opnieuw `bf.py static run {cp}`; vindt die niets nieuws, dan blijft de gate geslaagd."),
    "all_passed": ("ALL CHECKPOINTS PASSED. Next: the feature docs gate (`bf.py docs --status running`), then the final report and "
                   "the human review.",
                   "ALLE CHECKPOINTS GESLAAGD. Volgende stap: de docs-gate van de feature (`bf.py docs --status running`), "
                   "daarna het eindrapport en de review door de gebruiker."),
    "feedback_recorded": ("feedback recorded, {n} new checkpoint(s): {ids}", "feedback vastgelegd, {n} nieuwe checkpoint(s): {ids}"),
    "learning_added": ("learning added.", "learning toegevoegd."),
    "accept_open": ("cannot accept: checkpoints not passed: {cps}", "accepteren kan niet: niet geslaagde checkpoints: {cps}"),
    "expected_cpgate": ("expected cpNN:gate (e.g. cp08:behavior), got {v}", "verwacht cpNN:gate (bijvoorbeeld cp08:behavior), kreeg {v}"),
    "not_interrupted": ("{cp} {gate} is not interrupted (interrupted: {list})", "{cp} {gate} is niet onderbroken (onderbroken: {list})"),
    "running_and_redo": ("{x} cannot be both --running and --redo", "{x} kan niet tegelijk --running en --redo zijn"),
    "resume_running": ("{cp} {gate}: running again, same attempt (record its result with `bf.py gate {cp} {gate} passed|failed`)",
                       "{cp} {gname}: loopt weer, dezelfde poging (leg het resultaat vast met `bf.py gate {cp} {gate} passed|failed`)"),
    "redo_summary": ("redo after an interruption", "opnieuw na een onderbreking"),
    "resume_redo": ("{cp} {gname}: new attempt {n}; redo the step with a fresh subagent",
                    "{cp} {gname}: nieuwe poging {n}; doe de stap opnieuw met een verse subagent"),
    "n_resumed": ("{n} interruption(s) marked resumed", "{n} onderbreking(en) als hervat gemarkeerd"),
    "still_interrupted": ("still interrupted: {list}. Subagent still running or finished: `bf.py resume --running <cp:gate>`; "
                          "gone: `bf.py resume --redo <cp:gate>`.",
                          "nog onderbroken: {list}. Subagent loopt nog of is klaar: `bf.py resume --running <cp:gate>`; "
                          "weg: `bf.py resume --redo <cp:gate>`."),
    "nothing_to_resume": ("nothing to resume", "niets te hervatten"),

    # context / brief / design / docs / interrupted
    "ctx_project": ("project context", "projectcontext"), "ctx_feature": ("feature context", "featurecontext"),
    "ctx_missing": ("missing", "ontbreekt"), "ctx_stale": ("stale", "verouderd"), "ctx_fresh": ("fresh", "actueel"),
    "ctx_recorded": ("recorded", "vastgelegd"),
    "ctx_age": ("{n} days old", "{n} dagen oud"),
    "ctx_changed_n": ("{n} files changed since {head}", "{n} bestanden gewijzigd sinds {head}"),
    "ctx_changed": ("changed", "gewijzigd"),
    "ctx_fresh_changed": ("({n} files changed since it was written; the feature scout should look at those)",
                          "({n} bestanden gewijzigd sinds hij is geschreven; de featureverkenner moet daarnaar kijken)"),
    "spec_given": ("spec provided by the user", "spec aangeleverd door de gebruiker"),
    "brief_recorded": ("brief recorded ({src}), phase {phase}", "brief vastgelegd ({src}), fase {phase}"),
    "design_before_plan": ("design decision belongs before planning (phase {phase})", "het designbesluit hoort vóór het plannen (fase {phase})"),
    "design_review_status": ("design review needs --status running|passed|failed", "design review heeft --status running|passed|failed nodig"),
    "design_review_blockers": ("cannot pass the design review: {n} open blocker/high findings",
                               "de design-review kan niet slagen: {n} open blocker/high-bevindingen"),
    "design_review_not_passed": ("the design review has not passed yet", "de design-review is nog niet geslaagd"),
    "design_give_paths": ("give --prototype and/or --design-md", "geef --prototype en/of --design-md"),
    "design_in_scratch": ("{k} is under {d}/, which is not committed. Design files and prototypes are project documentation: put "
                          "them in the project's docs (see the Documentation section of the project context).",
                          "{k} staat onder {d}/, en dat wordt niet gecommit. Designbestanden en prototypes zijn projectdocumentatie: "
                          "zet ze in de docs van het project (zie de sectie Documentatie in de projectcontext)."),
    "design_line": ("design: {status} · review {review} · phase {phase}", "design: {status} · review {review} · fase {phase}"),
    "docs_after_last": ("the feature docs gate runs after the last checkpoint (phase is {phase})",
                        "de docs-gate van de feature komt na de laatste checkpoint (fase is {phase})"),
    "docs_blockers": ("cannot pass the docs gate: {n} open blocker/high findings", "de docs-gate kan niet slagen: {n} open blocker/high-bevindingen"),
    "docs_passed": ("FEATURE DOCS PASSED. Final report: {path}", "DOCUMENTATIE VAN DE FEATURE GESLAAGD. Eindrapport: {path}"),
    "no_running_attempt": ("{cp} {gate} has no running attempt", "{cp} {gate} heeft geen lopende poging"),
    "interruption_recorded": ("interruption recorded ({why}); marked: {marked}", "onderbreking vastgelegd ({why}); gemarkeerd: {marked}"),
    "no_running_attempts": ("no running attempts", "geen lopende pogingen"),

    # status
    "status_head": ("{title}  [{slug}]  phase: {phase} · mode: {mode}", "{title}  [{slug}]  fase: {phase} · modus: {mode}"),
    "status_legend": ("gates: {legend}", "gates: {legend}"),
    "status_profile": ("profile: {profile}", "profiel: {profile}"),
    "status_models": ("models: {default} for every role, except {exc}. Per role: `bf.py model <role>`",
                      "modellen: {default} voor elke rol, behalve {exc}. Per rol: `bf.py model <rol>`"),
    "session_model": ("session model", "sessiemodel"),
    "model_escalated": ("escalated: the implementer failed {n}x on {gate} in {cp}, so this attempt runs on the session model",
                        "geëscaleerd: de implementer faalde {n}x op {gate} in {cp}, dus deze poging draait op het sessiemodel"),
    "model_unknown_role": ("unknown role '{role}'. Roles: {roles}", "onbekende rol '{role}'. Rollen: {roles}"),
    "model_head": ("model per role (profile {profile}; inherit = leave the Agent call's model field out):",
                   "model per rol (profiel {profile}; inherit = laat het model-veld van de Agent-call weg):"),
    "status_ints": ("interruptions: {n} (last: {err} at {at}, {state}; marked {marked})",
                    "onderbrekingen: {n} (laatste: {err} om {at}, {state}; gemarkeerd {marked})"),
    "status_int_gates": ("interrupted gates: {list} -> subagent still running/finished: `bf.py resume --running <cp:gate>`; gone: "
                         "`bf.py resume --redo <cp:gate>`",
                         "onderbroken gates: {list} -> subagent loopt nog of is klaar: `bf.py resume --running <cp:gate>`; weg: "
                         "`bf.py resume --redo <cp:gate>`"),
    "status_running": ("running: {cp} {gname} since {since}. If this session was interrupted and its subagent is gone, run "
                       "`bf.py interrupted {cp} {gate} --reason \"...\"` and redo the step.",
                       "bezig: {cp} {gname} sinds {since}. Is deze sessie onderbroken en is de subagent weg, draai dan "
                       "`bf.py interrupted {cp} {gate} --reason \"...\"` en doe de stap opnieuw."),
    "st_testfirst": ("test-first: {planned} planned test(s), {sc} with a scenario · red: {red} · green: {green}",
                     "test-first: {planned} geplande test(s), {sc} met scenario · rood: {red} · groen: {green}"),
    "st_red": ("{n} failing {why}", "{n} falen {why}"),
    "st_red_flag": ("confirmed (no details)", "bevestigd (zonder details)"),
    "st_red_none": ("not recorded yet", "nog niet vastgelegd"),

    # cost / serve / inbox / wait / doctor
    "cost_line": ("tokens {tok} · {usd} (API-equivalent) · active {active} · wall {wall} · {n} transcript files",
                  "tokens {tok} · {usd} (API-equivalent) · actief {active} · doorlooptijd {wall} · {n} transcriptbestanden"),
    "no_transcripts": ("WARNING: no transcripts found. Register the session with `bf.py session <id>`.",
                       "LET OP: geen transcripts gevonden. Registreer de sessie met `bf.py session <id>`."),
    "bad_host": ("--allow-host / BUILDFLOW_ALLOW_HOSTS: '{raw}' is not an exact host name (like my-mac.tail1234.ts.net); wildcards are not accepted",
                 "--allow-host / BUILDFLOW_ALLOW_HOSTS: '{raw}' is geen exacte hostnaam (zoals my-mac.tail1234.ts.net); wildcards worden niet geaccepteerd"),
    "already_serving": ("already serving: {url} (pid {pid})", "draait al: {url} (pid {pid})"),
    "also_allowed": ("also allowed: {hosts}", "ook toegestaan: {hosts}"),
    "host_not_allowed": ("note: the running server does not allow {hosts}; stop it (kill {pid}) and start `bf.py serve` again with --allow-host to add hosts",
                         "let op: de draaiende server staat {hosts} niet toe; stop hem (kill {pid}) en start `bf.py serve` opnieuw met --allow-host"),
    "serving_detached": ("serving {url} (pid {pid}, log {log}); all runs: http://127.0.0.1:{port}/",
                         "viewer draait op {url} (pid {pid}, log {log}); alle runs: http://127.0.0.1:{port}/"),
    "also_answers": ("also answers as {url} (via your proxy, e.g. `tailscale serve --bg --http={port} http://127.0.0.1:{port}`)",
                     "ook bereikbaar als {url} (via je proxy, bijvoorbeeld `tailscale serve --bg --http={port} http://127.0.0.1:{port}`)"),
    "server_down": ("the server did not come up; see {log}", "de server is niet opgestart; zie {log}"),
    "no_port": ("no free port in {a}..{b}", "geen vrije poort in {a}..{b}"),
    "serving": ("serving {url} (all runs: http://127.0.0.1:{port}/; live viewer; browser actions land in {inbox}). Ctrl-C to stop.",
                "viewer draait op {url} (alle runs: http://127.0.0.1:{port}/; live viewer; acties uit de browser komen in {inbox}). Stoppen met Ctrl-C."),
    "inbox_give_ids": ("give the id(s) to mark handled: `bf.py inbox handled <id> --note \"...\"`",
                       "geef de id('s) die verwerkt zijn: `bf.py inbox handled <id> --note \"...\"`"),
    "inbox_unknown": ("unknown inbox id(s): {ids}", "onbekende inbox-id('s): {ids}"),
    "wait_replaced": ("bf wait: replaced by a newer `bf.py wait`; nothing to do.", "bf wait: vervangen door een nieuwere `bf.py wait`; niets te doen."),
    "wait_timeout": ("bf wait: no viewer messages within {s}s. Start `bf.py wait` again to keep listening.",
                     "bf wait: geen berichten uit de viewer binnen {s}s. Start `bf.py wait` opnieuw om te blijven luisteren."),
    "doc_skill_dir": ("skill dir", "skillmap"), "doc_root": ("project root", "projectmap"),
    "doc_models": ("priced models", "modellen met prijs"), "doc_lang": ("language", "taal"),
    "doc_no_run": ("no active run", "geen actieve run"),
    "doc_active": ("active run: {slug} · phase: {phase}", "actieve run: {slug} · fase: {phase}"),
    "doc_session": ("session {sid}: {m} main transcript(s), {s} subagent transcript(s)",
                    "sessie {sid}: {m} hoofdtranscript(s), {s} subagent-transcript(s)"),
    "doc_no_session": ("WARNING: no session registered; costs cannot be measured yet.",
                       "LET OP: geen sessie geregistreerd; kosten kunnen nog niet worden gemeten."),

    # reports
    "md_profile": ("Model profile", "Modelprofiel"), "reason_l": ("reason", "reden"),
    "md_feature": ("Feature", "Feature"),"md_status": ("Status", "Status"), "md_duration": ("Duration", "Duur"),
    "md_wall_idle": (" (wall-clock {wall}, idle {idle})", " (doorlooptijd {wall}, stil {idle})"),
    "md_built": ("What was built", "Wat er gebouwd is"), "md_done_when": ("Done when", "Klaar wanneer"),
    "md_gates": ("Quality gates", "Kwaliteitsgates"),
    "md_gate_head": ("| gate | status | attempts | findings | fixed | open |", "| gate | status | pogingen | bevindingen | opgelost | open |"),
    "attempt_l": ("attempt", "poging"), "metrics_l": ("metrics", "metingen"), "files_l": ("files", "bestanden"),
    "md_cp_cost": ("Cost of this checkpoint", "Kosten van deze checkpoint"),
    "api_cost": ("API-equivalent cost", "kosten (API-equivalent)"), "by_role": ("by role", "per rol"),
    "run_so_far": ("run so far: {tok} tokens, {usd}, active {active}", "run tot nu toe: {tok} tokens, {usd}, actief {active}"),
    "md_progress": ("Progress", "Voortgang"),
    "md_progress_line": ("{done}/{n} checkpoints passed. Next: {next}", "{done}/{n} checkpoints geslaagd. Volgende stap: {next}"),
    "md_scenarios": ("Scenarios", "Scenario's"),
    "md_planned": ("Planned tests", "Geplande tests"),
    "sc_planned": ("planned", "gepland"), "sc_red": ("red confirmed", "rood bevestigd"),
    "sc_red_wrong": ("red, wrong reason", "rood, verkeerde reden"), "sc_green": ("green", "groen"),
    "md_tdd_totals_head": ("Test-first per checkpoint", "Test-first per checkpoint"),
    "tdd_totals": ("{scen} of {planned} planned tests have a scenario · {new} new tests · red confirmed in {red} of {n} checkpoints",
                   "{scen} van {planned} geplande tests hebben een scenario · {new} nieuwe tests · rood bevestigd in {red} van {n} checkpoints"),
    "md_tdd_head": ("| # | checkpoint | planned | scenarios | new tests | green |",
                    "| # | checkpoint | gepland | scenario's | nieuwe tests | groen |"),
    "static_not_run": ("not run (see Deterministic checks)", "niet gedraaid (zie Deterministische checks)"),
    "static_outcome": ("{n} checkpoint(s) checked; {new} new finding(s), {fixed} fixed, {wontfix} won't fix, {open} blocking open",
                       "{n} checkpoint(s) gecontroleerd; {new} nieuwe bevinding(en), {fixed} opgelost, {wontfix} bewust niet opgelost, "
                       "{open} blokkerend open"),
    "md_static": ("Deterministic checks", "Deterministische checks"),
    "static_unset": ("No deterministic checks were configured for this run.", "Voor deze run waren geen deterministische checks ingesteld."),
    "static_unset_migrated": ("No deterministic checks were configured for this run (it started before the static gate existed).",
                              "Voor deze run waren geen deterministische checks ingesteld (hij begon voordat de statische gate bestond)."),
    "static_no_tools": ("No tools were available, so no deterministic checks ran: {why}",
                        "Er waren geen tools beschikbaar, dus er draaiden geen deterministische checks: {why}"),
    "checks_l": ("Checks", "Checks"),
    "baseline_line": ("Baseline: {n} pre-existing finding(s) at `{commit}`, not counted against the feature",
                      "Baseline: {n} bestaande bevinding(en) op `{commit}`, telt niet mee voor de feature"),
    "baseline_none": ("Baseline: none recorded, so every finding counted as new", "Baseline: niet vastgelegd, dus elke bevinding telde als nieuw"),
    "not_available_line": ("Not available (not installed and not added)", "Niet beschikbaar (niet geïnstalleerd en niet toegevoegd)"),
    "md_final_title": ("final report", "eindrapport"), "md_goal": ("Goal", "Doel"), "md_phase": ("Phase", "Fase"),
    "md_outcome": ("Outcome", "Uitkomst"),
    "out_cps": ("checkpoints: {done}/{n} passed ({fb} came from human feedback)", "checkpoints: {done}/{n} geslaagd ({fb} kwamen uit feedback)"),
    "out_tests": ("tests: {p}/{n} passing at last run", "tests: {p}/{n} groen bij de laatste run"),
    "out_findings": ("review findings: {n} raised, {fixed} fixed, {open} open, {wontfix} won't fix",
                     "reviewbevindingen: {n} gemeld, {fixed} opgelost, {open} open, {wontfix} bewust niet opgelost"),
    "out_rounds": ("human review rounds: {n}", "reviewrondes van de gebruiker: {n}"),
    "md_checkpoints": ("Checkpoints", "Checkpoints"),
    "md_final_head_tail": ("attempts | duration | cost | commit", "pogingen | duur | kosten | commit"),
    "md_cost_time": ("Cost and time", "Kosten en tijd"),
    "tot_tokens": ("total tokens: **{tok}** (input {inp}, cache write {cw}, cache read {cr}, output {out})",
                   "tokens totaal: **{tok}** (input {inp}, cache write {cw}, cache read {cr}, output {out})"),
    "time_line": ("active: **{active}** · waiting on human: {wait} · idle/interrupted: {idle} · wall-clock: {wall}",
                  "actief: **{active}** · wachten op jou: {wait} · stil/onderbroken: {idle} · doorlooptijd: {wall}"),
    "int_line": ("interruptions: {n}", "onderbrekingen: {n}"),
    "idle_periods": ("idle periods longer than {min} min: {n}", "stiltes langer dan {min} min: {n}"),
    "sub_line": ("subagent runs: {n} · summed subagent time: {d}", "subagent-runs: {n} · opgetelde subagent-tijd: {d}"),
    "role_l": ("role", "rol"), "phase_cp_l": ("phase / checkpoint", "fase / checkpoint"), "cost_l": ("cost", "kosten"),
    "pricing_note": ("API-equivalent cost at list prices (pricing.json). On a Claude subscription you are not billed per token.",
                     "Kosten als API-equivalent tegen lijstprijzen (pricing.json). Met een Claude-abonnement betaal je niet per token."),
    "unpriced": ("Unpriced models (not in pricing.json)", "Modellen zonder prijs (niet in pricing.json)"),
    "cost_verified_line": ("prices verified on {date}", "prijzen geverifieerd op {date}"),
    "cost_verified_none": ("prices never verified", "prijzen nog nooit geverifieerd"),
    "pricing_never": ("Prices were never verified (pricing.json): run `bf.py pricing --check`, then `bf.py pricing --verified`.",
                      "Prijzen zijn nog nooit geverifieerd (pricing.json): draai `bf.py pricing --check`, daarna `bf.py pricing --verified`."),
    "pricing_check_hint": ("Prices last verified on {date}: check them against the pricing page at the start of this run, then `bf.py pricing --verified`.",
                           "Prijzen laatst geverifieerd op {date}: controleer ze bij aanvang tegen de prijspagina, daarna `bf.py pricing --verified`."),
    "pricing_stale": ("Prices are outdated (last verified {date}, {days} days ago): check them against the pricing page, then `bf.py pricing --verified`.",
                      "Prijzen zijn verouderd (laatst geverifieerd op {date}, {days} dagen geleden): controleer ze tegen de prijspagina, daarna `bf.py pricing --verified`."),
    "pricing_table_head": ("model  input/M  output/M  cache_read/M  fast", "model  input/M  output/M  cache_read/M  fast"),
    "pricing_verified_line": ("verified: {date}  source: {source}", "geverifieerd: {date}  bron: {source}"),
    "pricing_check_ok": ("Every model in this run's transcripts is in pricing.json.",
                         "Elk model uit de transcripts van deze run staat in pricing.json."),
    "pricing_check_found": ("{n} message(s) from model(s) without a price: {models}. Add them with `bf.py pricing --set <model> input=.. output=.. cache_read=..`.",
                            "{n} bericht(en) van model(len) zonder prijs: {models}. Voeg ze toe met `bf.py pricing --set <model> input=.. output=.. cache_read=..`."),
    "pricing_set_usage": ("usage: bf.py pricing --set <model> key=value ... (input, output, cache_read, cache_write_5m, cache_write_1h, fast_multiplier)",
                          "gebruik: bf.py pricing --set <model> key=value ... (input, output, cache_read, cache_write_5m, cache_write_1h, fast_multiplier)"),
    "pricing_set_field": ("unknown price field {k}", "onbekend prijsveld {k}"),
    "pricing_set_number": ("{k}={v} is not a number", "{k}={v} is geen getal"),
    "pricing_set_done": ("{model} updated in pricing.json.", "{model} bijgewerkt in pricing.json."),
    "pricing_verified_set": ("verified_at set to {date}.", "verified_at gezet op {date}."),
    "md_brief_design": ("Brief and design", "Brief en design"),
    "design_review_line": ("design review: {status} after {n} attempt(s); {f} findings, {fixed} fixed",
                           "design-review: {status} na {n} poging(en); {f} bevindingen, {fixed} opgelost"),
    "design_file_l": ("design file", "designbestand"), "proto_states": ("prototype states", "states van het prototype"),
    "md_docs": ("Documentation", "Documentatie"),
    "docs_gate_line": ("feature docs gate: {status} after {n} attempt(s)", "docs-gate van de feature: {status} na {n} poging(en)"),
    "docs_cps_line": ("checkpoints with a docs gate: {n}/{total}", "checkpoints met een docs-gate: {n}/{total}"),
    "no_doc_files": ("no documentation files recorded", "geen documentatiebestanden vastgelegd"),
    "md_open_findings": ("Open or accepted findings", "Open of geaccepteerde bevindingen"),
    "md_interruptions": ("Interruptions", "Onderbrekingen"), "int_attempts": ("interrupted attempts", "onderbroken pogingen"),
    "md_human_feedback": ("Human feedback", "Feedback van de gebruiker"), "no_new_cps": ("no new checkpoints", "geen nieuwe checkpoints"),
    "md_learnings": ("Learnings", "Learnings"),
    "hook_gave_up": ("buildflow: stop hook gave up after repeated blocks without progress. Run `bf.py status` and either "
                     "continue, or `bf.py pause --reason ...`.",
                     "buildflow: de stop-hook geeft het op na herhaalde blokkades zonder voortgang. Draai `bf.py status` en ga "
                     "verder, of `bf.py pause --reason ...`."),
    "n_new": ("{n} new", "{n} nieuw"), "n_baseline": ("{n} baseline", "{n} baseline"),
    # ------------------------------------------------------------ bf prompt / brief-context / compact hints
    "prompt_lang_note": ("Write every text a person will read (summaries, findings, test names, scenarios) in this "
                         "language; code, paths and JSON keys stay as they are.",
                         "Schrijf elke tekst die een mens leest (samenvattingen, bevindingen, testnamen, scenario's) "
                         "in deze taal; code, paden en JSON-sleutels blijven zoals ze zijn."),
    "prompt_read_l": ("Read these first, in this order, before doing anything else:",
                      "Lees dit eerst, in deze volgorde, voordat je iets anders doet:"),
    "prompt_facts_l": ("Project facts", "Projectfeiten"),
    "prompt_cp_l": ("Checkpoint", "Checkpoint"),
    "prompt_done_l": ("done_when", "done_when"),
    "prompt_ui_scope_l": ("ui_scope", "ui_scope"),
    "prompt_docs_scope_l": ("docs_scope", "docs_scope"),
    "prompt_tests_l": ("Planned tests", "Geplande tests"),
    "prompt_ui_isolation": ("You judge only what you see against the reference below. You do not get the brief, "
                            "the plan or the implementation.",
                            "Je beoordeelt alleen wat je ziet tegenover de referentie hieronder. Je krijgt de brief, "
                            "het plan of de implementatie niet."),
    "prompt_ref_l": ("Reference", "Referentie"), "prompt_url_l": ("URL", "URL"),
    "prompt_no_role": ("no prompt text found for role '{role}'; write one in references/ or pass --extra-file",
                       "geen prompttekst gevonden voor rol '{role}'; schrijf er een in references/ of geef --extra-file mee"),
    "prompt_written": ("prompt written: {path}", "prompt geschreven: {path}"),
    "prompt_tag_l": ("tag", "tag"), "prompt_model_l": ("model", "model"),
    "finish_compact_hint": ("Context can now be compacted safely (/compact).",
                           "Context kan nu veilig gecompacteerd worden (/compact)."),
    "brief_context_head": ("Brief context for a new session — {title} ({slug})",
                          "Korte context voor een nieuwe sessie — {title} ({slug})"),
    "brief_context_no_run": ("no active run; nothing to summarise", "geen actieve run; niets samen te vatten"),
    "parallel_max": ("already 2 checkpoints in progress ({cp} among them); finish one before starting another "
                    "in parallel", "er lopen al 2 checkpoints tegelijk (waaronder {cp}); rond er een af voor je "
                    "een volgende parallel start"),
    "parallel_overlap": ("shares files with a checkpoint already in progress ({files}); build them in sequence "
                        "instead", "deelt bestanden met een checkpoint dat al loopt ({files}); bouw ze na elkaar"),
}


# ---------------------------------------------------------------- basics

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def die(msg, code=1):
    print(f"bf: {msg}", file=sys.stderr)
    sys.exit(code)


def find_root(start=None):
    if os.environ.get("BUILDFLOW_ROOT"):
        return os.environ["BUILDFLOW_ROOT"]
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, ".buildflow", "active")):
            return d
        # the session was started in another folder than the project: .buildflow/redirect names it
        redirect = os.path.join(d, ".buildflow", "redirect")
        if os.path.isfile(redirect):
            target = os.path.expanduser(open(redirect).read().strip())
            if os.path.isfile(os.path.join(target, ".buildflow", "active")):
                return target
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(start or os.getcwd())


def bf_dir(root):
    return os.path.join(root, ".buildflow")


def active_slug(root):
    p = os.path.join(bf_dir(root), "active")
    if not os.path.isfile(p):
        return None
    s = open(p).read().strip()
    return s or None


def run_dir(root, slug):
    return os.path.join(bf_dir(root), slug)


def load(root, slug=None, required=True):
    active = slug is None or slug == active_slug(root)
    slug = slug or active_slug(root)
    if not slug:
        if required:
            die(t("no_run"))
        return None
    p = os.path.join(run_dir(root, slug), "state.json")
    if not os.path.isfile(p):
        if required:
            die(t("state_missing", p=p))
        return None
    with open(p) as f:
        st = json.load(f)
    if active:
        global LANG
        LANG = st.get("lang") if st.get("lang") in LANGS else LANG
    # runs created before the brief/design stages existed
    st.setdefault("stages", {"context": {"status": "done"}, "brief": {"status": "skipped"},
                             "design": {"status": "pending", "review": {"status": "pending", "attempts": []}}})
    st.setdefault("approvals", [])
    st.setdefault("profile", "thorough")  # runs from before model profiles keep running on the session model
    st["stages"].setdefault("docs", {"status": "pending", "attempts": []})
    st.setdefault("static", {"checks": None})
    for x in st.get("interruptions", []):
        if "status" not in x:  # recorded before interruptions had a lifecycle
            x["status"] = "resumed" if st.get("phase") in ("done", "awaiting_human_review") else "open"
    for cp in st.get("checkpoints", []):
        cp["gates"].setdefault("docs", {"status": "skipped", "attempts": [],
                                        "skip_reason": t("skip_docs_migrated", st)})
        if "static" not in cp["gates"]:
            # the static gate was added to buildflow while this run existed
            if cp.get("status") == "passed":
                cp["gates"]["static"] = {"status": "skipped", "attempts": [], "migrated": True,
                                         "skip_reason": t("skip_static_migrated", st)}
            elif cp.get("status") in (None, "pending"):
                cp["gates"]["static"] = {"status": "pending", "attempts": []}
            else:
                cp["gates"]["static"] = {"status": "pending", "attempts": [], "added_mid_checkpoint": True}
    return st


def read_text(root, rel, limit=60000):
    if not rel:
        return ""
    p = rel if os.path.isabs(rel) else os.path.join(root, rel)
    try:
        with open(p, errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


CURRENT_CMD = None  # the bf command being run (None when imported by the hook)


def save(root, st, render=True, resume=True):
    """Write state. A state change made by a bf command means the session is working again, so open
    interruptions are marked resumed (the hook and `bf interrupted` pass resume=False)."""
    d = run_dir(root, st["slug"])
    os.makedirs(d, exist_ok=True)
    if resume:
        resume_interruptions(st, "auto", f"bf {CURRENT_CMD}" if CURRENT_CMD else "hook")
    st["updated_at"] = now()
    tmp = os.path.join(d, "state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, "state.json"))
    if render:
        write_data_json(root, st)
        write_overview(root)


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or "feature"


def git(root, *args):
    try:
        return subprocess.check_output(["git", "-C", root, *args], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def set_phase(st, phase):
    if phase not in PHASES:
        die(t("unknown_phase", phase=phase, phases=", ".join(PHASES)))
    if st.get("phase") == phase:
        return
    st["phase"] = phase
    st.setdefault("phase_log", []).append({"phase": phase, "at": now()})


def interrupt_open_attempts(st, reason, at=None):
    """Close every gate attempt that was still running as `interrupted`. Returns what it marked."""
    marked = []
    for cp in st.get("checkpoints", []):
        for g in CP_GATES:
            gs = cp["gates"][g]
            att = gs["attempts"][-1] if gs["attempts"] else None
            if gs["status"] == "running" and att and not att.get("result"):
                att["result"] = "interrupted"
                att["ended_at"] = at or now()
                att["summary"] = (att.get("summary", "") + f" [interrupted: {reason}]").strip()
                gs["status"] = "interrupted"
                marked.append(f"{cp['id']}:{g}")
    fd = st.get("stages", {}).get("docs", {})
    att = fd.get("attempts", [])[-1] if fd.get("attempts") else None
    if fd.get("status") == "running" and att and not att.get("result"):
        att.update(result="interrupted", ended_at=at or now(),
                   summary=(att.get("summary", "") + f" [interrupted: {reason}]").strip())
        fd["status"] = "interrupted"
        marked.append("feature:docs")
    return marked


def record_interruption(st, error, details="", source="hook"):
    t = now()
    marked = interrupt_open_attempts(st, error, t)
    st.setdefault("interruptions", []).append({
        "at": t, "error": error or "unknown", "details": (details or "")[:300],
        "phase": st.get("phase"), "attempts": marked, "source": source, "status": "open"})
    return marked


def open_interruptions(st):
    return [x for x in st.get("interruptions", []) if x.get("status", "open") == "open"]


def resume_interruptions(st, how, via):
    """open -> resumed. how: auto (a later successful turn or bf command) or manual (`bf resume`)."""
    done = []
    for x in open_interruptions(st):
        x.update(status="resumed", resumed_at=now(), resumed_how=how, resumed_via=via)
        done.append(x)
    return done


def interrupted_gates(st):
    return [(cp, g) for cp in st.get("checkpoints", []) for g in CP_GATES
            if cp["gates"].get(g, {}).get("status") == "interrupted"]


def continue_interrupted_attempt(gs):
    """An interrupted attempt whose subagent kept going: reopen that same attempt instead of adding a new one."""
    att = gs["attempts"][-1] if gs["attempts"] else None
    if not att or att.get("result") != "interrupted":
        return None
    m = re.search(r"\s*\[interrupted: ([^\]]*)\]$", att.get("summary", ""))
    att.setdefault("interruptions", []).append({"at": att.get("ended_at"), "reason": m.group(1) if m else ""})
    if m:
        att["summary"] = att["summary"][:m.start()]
    att["result"] = None
    att.pop("ended_at", None)
    gs["status"] = "running"
    return att


def get_cp(st, cid):
    cid = norm_cp(cid)
    for cp in st["checkpoints"]:
        if cp["id"] == cid:
            return cp
    die(t("unknown_cp", cid=cid))


def norm_cp(cid):
    cid = str(cid).lower().strip()
    m = re.match(r"^(?:cp)?0*(\d+)$", cid)
    return f"cp{int(m.group(1)):02d}" if m else cid


def new_checkpoint(n, raw, source="plan", st=None):
    gates_needed = [g for g in raw.get("gates", CP_GATES) if g in CP_GATES]
    if "behavior" not in gates_needed:
        gates_needed.insert(0, "behavior")
    if "review" not in gates_needed:
        gates_needed.append("review")
    # deterministic checks are mandatory; only an explicit reason (no code changed) skips them
    if "static" not in gates_needed and not raw.get("static_skip_reason"):
        gates_needed.append("static")
    # a per-checkpoint docs gate only when the checkpoint names the docs it touches
    no_docs_scope = "docs" in gates_needed and not str(raw.get("docs_scope") or "").strip()
    if no_docs_scope:
        gates_needed.remove("docs")
    gates = {}
    for g in CP_GATES:
        gates[g] = {"status": "pending" if g in gates_needed else "skipped", "attempts": []}
        if g not in gates_needed:
            gates[g]["skip_reason"] = raw.get(f"{g}_skip_reason") or (
                t("skip_docs_no_scope", st) if g == "docs" and no_docs_scope else t("skip_not_needed", st))
    return {
        "id": f"cp{n:02d}",
        "n": n,
        "title": raw.get("title", f"Checkpoint {n}"),
        "summary": raw.get("summary", ""),
        "why": raw.get("why", ""),
        "done_when": raw.get("done_when", []),
        "complexity": raw.get("complexity"),
        "ui_scope": raw.get("ui_scope", ""),
        "docs_scope": raw.get("docs_scope", ""),
        "depends_on": [norm_cp(x) for x in raw.get("depends_on", [])],
        "files_hint": raw.get("files_hint", []),
        "tests": [norm_test(x) for x in raw.get("tests", [])],
        "source": source,
        "status": "pending",
        "started_at": None,
        "ended_at": None,
        "commit": None,
        "gates": gates,
    }


def read_json_arg(data=None, data_file=None):
    if data_file:
        with open(data_file) as f:
            return json.load(f)
    if data:
        return json.loads(data)
    return {}


# ---------------------------------------------------------------- inbox (actions from the live viewer)
# Single writer per file: `bf serve` only appends new items to inbox.jsonl; bf commands only append
# status events (read / handled + note) to inbox-status.jsonl. Nobody rewrites a file, so a
# browser click can never race a bf command, and state.json is only ever written by bf commands.

INBOX_TYPES = ("approve", "feedback", "accept", "message")
INBOX_STAGES = ("brief", "design", "plan", "review", "checkpoint")
INBOX_STATUS_RANK = {"new": 0, "read": 1, "handled": 2}
INBOX_MAX_TEXT = 8000
PHASE_DEFAULT_STAGE = {"awaiting_brief_approval": "brief", "brief": "brief", "awaiting_design_approval": "design",
                       "design": "design", "planning": "plan", "awaiting_plan_approval": "plan",
                       "building": "checkpoint", "documenting": "checkpoint", "awaiting_human_review": "review"}


def inbox_paths(root, slug):
    d = run_dir(root, slug)
    return os.path.join(d, "inbox.jsonl"), os.path.join(d, "inbox-status.jsonl")


def read_jsonl(p):
    out = []
    try:
        f = open(p, errors="replace")
    except OSError:
        return out
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue  # a line still being written
            if isinstance(d, dict):
                out.append(d)
    return out


def append_jsonl(p, obj):
    """One write() on an O_APPEND file: concurrent appenders never interleave a line."""
    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def inbox_items(root, slug):
    """All viewer items in submit order, with their current status folded in from the status log."""
    ip, sp = inbox_paths(root, slug)
    by = {}
    for it in read_jsonl(ip):
        if it.get("id") and it["id"] not in by:
            it["status"] = "new"
            by[it["id"]] = it
    for ev in read_jsonl(sp):
        it = by.get(ev.get("id"))
        rank = INBOX_STATUS_RANK.get(ev.get("status"), -1)
        if not it or rank < INBOX_STATUS_RANK[it["status"]]:
            continue  # status never goes back
        it["status"] = ev["status"]
        it[ev["status"] + "_at"] = ev.get("at")
        if ev.get("note"):
            it["note"] = ev["note"]
    return list(by.values())


def inbox_unhandled(root, slug):
    return [x for x in inbox_items(root, slug) if x["status"] != "handled"]


def inbox_mark(root, slug, ids, status, note=""):
    _, sp = inbox_paths(root, slug)
    for i in ids:
        ev = {"id": i, "status": status, "at": now()}
        if note:
            ev["note"] = note
        append_jsonl(sp, ev)


def inbox_hint(root, slug, st=None):
    n = len(inbox_unhandled(root, slug))
    if not n:
        return ""
    return t("inbox_hint", st, n=n)


def inbox_close(root, slug, typ, stage, note):
    """`bf approve` / `bf accept` settle the matching viewer request themselves."""
    ids = [x["id"] for x in inbox_unhandled(root, slug) if x.get("type") == typ and (stage is None or x.get("stage") == stage)]
    if ids:
        inbox_mark(root, slug, ids, "handled", note)
    return ids


def inbox_new_item(st, existing, body):
    """Validate a viewer action. Returns (http status, item or error dict)."""
    def err(code, key, msg):
        return code, {"ok": False, "code": key, "error": msg}
    if not isinstance(body, dict):
        return err(400, "bad_request", "expected a JSON object")
    typ = body.get("type")
    if typ not in INBOX_TYPES:
        return err(400, "bad_type", f"type must be one of {', '.join(INBOX_TYPES)}")
    text = str(body.get("text") or "").strip()
    if len(text) > INBOX_MAX_TEXT:
        return err(413, "too_large", f"text is longer than {INBOX_MAX_TEXT} characters")
    stage = body.get("stage") or None
    if stage is not None and stage not in INBOX_STAGES:
        return err(400, "bad_stage", f"stage must be one of {', '.join(INBOX_STAGES)}")
    target = body.get("target") or None
    if target is not None:
        target = norm_cp(target)
        if not re.match(r"^cp\d+$", target) and target != "general":
            return err(400, "bad_target", "target must be a checkpoint id like cp03")
    ph = st["phase"]
    pending = [x for x in existing if x["status"] != "handled"]
    if typ == "approve":
        if ph not in APPROVAL_NEXT:
            return err(409, "wrong_phase", f"nothing is waiting for approval (phase {ph})")
        want = APPROVAL_NEXT[ph][0]
        if stage and stage != want:
            return err(409, "wrong_phase", f"the {stage} is not waiting for approval (phase {ph})")
        stage = want
    elif typ == "accept":
        if ph != "awaiting_human_review":
            return err(409, "wrong_phase", f"the feature can only be accepted in awaiting_human_review (phase {ph})")
        stage = "review"
    else:
        if not text:
            return err(400, "text_required", "text is required for feedback and messages")
        stage = stage or PHASE_DEFAULT_STAGE.get(ph)
    if typ in ("approve", "accept") and any(x.get("type") == typ and x.get("stage") == stage for x in pending):
        return err(409, "duplicate", f"a {typ} for the {stage} is already waiting for Claude")
    item = {"id": "v" + secrets.token_hex(3), "at": now(), "type": typ, "stage": stage, "target": target,
            "text": text, "phase_at_submit": ph, "status": "new"}
    return 200, item


# ---------------------------------------------------------------- static gate: deterministic checks
# Linters, type checkers, SAST, secret scanners and dependency audits the project already uses.
# `bf static config` records which ones (approved with the plan), `bf static baseline` stores what
# they find before the feature starts, `bf static run cpNN` runs them on the checkpoint and keeps
# only what is new. The gate cannot pass while a new blocking finding is open.

STATIC_KINDS = ("lint", "format", "types", "sast", "secrets", "deps", "other")
STATIC_FORMATS = ("sarif", "json", "text")
STATIC_DEFAULT_TIMEOUT = 300
STATIC_MAX_FILES = 400            # more changed files than this: pass the whole tree instead
STATIC_RAW_LIMIT = 200_000        # bytes of raw tool output kept as evidence
BLOCKING_SEV = ("blocker", "critical", "high", "major")
# commands that would change the project's dependencies; a check must never do that
INSTALL_RE = re.compile(r"\b(npm\s+(i|install|add)|yarn\s+add|pnpm\s+(add|install|i)|pip3?\s+install|poetry\s+add|"
                        r"uv\s+(add|pip\s+install)|bundle\s+(add|install)|gem\s+install|go\s+get|cargo\s+(add|install)|"
                        r"brew\s+install|apt(-get)?\s+install)\b")


def static_cfg(st):
    return st.setdefault("static", {"checks": None})


def static_checks(st):
    return static_cfg(st).get("checks") or []


def static_evidence(root, st, cp):
    return os.path.join(run_dir(root, st["slug"]), "evidence", cp["id"])


def sev_norm(raw, default):
    """Map a tool's severity to buildflow's scale: error/high -> high, warning/medium -> medium, info/low -> low."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (int, float)):  # eslint: 2 error, 1 warning
        return "high" if raw >= 2 else "medium" if raw >= 1 else "low"
    r = str(raw).strip().lower()
    if r in ("blocker",):
        return "blocker"
    if r in ("error", "high", "critical", "fatal", "severe", "err", "e"):
        return "high"
    if r in ("warning", "warn", "medium", "moderate", "w"):
        return "medium"
    if r in ("info", "low", "note", "none", "convention", "refactor", "style", "hint", "information", "negligible", "weak"):
        return "low"
    return default


def rel_path(root, p):
    if not p:
        return ""
    p = str(p)
    if p.startswith("file://"):
        p = urllib.parse.unquote(urllib.parse.urlparse(p).path)
    if os.path.isabs(p):
        try:
            rp = os.path.relpath(os.path.realpath(p), os.path.realpath(root))
            if not rp.startswith(".."):
                p = rp
        except ValueError:
            pass
    while p.startswith("./"):
        p = p[2:]
    return p


def _raw(rule="", file="", line=None, message="", severity=None, secret=False):
    try:
        line = int(line) if line not in (None, "") else None
    except (TypeError, ValueError):
        line = None
    return {"rule": str(rule or ""), "file": str(file or ""), "line": line,
            "message": " ".join(str(message or "").split())[:400], "severity": severity, "secret": secret}


def parse_sarif(doc):
    out = []
    for run in doc.get("runs") or []:
        rules = {}
        for r in ((run.get("tool") or {}).get("driver") or {}).get("rules") or []:
            rules[r.get("id")] = ((r.get("defaultConfiguration") or {}).get("level"))
        for res in run.get("results") or []:
            loc = ((res.get("locations") or [{}])[0].get("physicalLocation") or {})
            msg = res.get("message") or {}
            out.append(_raw(res.get("ruleId") or (res.get("rule") or {}).get("id"),
                            (loc.get("artifactLocation") or {}).get("uri"), (loc.get("region") or {}).get("startLine"),
                            msg.get("text") or msg.get("markdown") or "", res.get("level") or rules.get(res.get("ruleId"))))
    return out


def parse_json_doc(doc):
    """Recognise the JSON output of common tools. Returns a list, or None when the shape is unknown."""
    out = []
    if isinstance(doc, dict) and "runs" in doc and ("version" in doc or "$schema" in doc):
        return parse_sarif(doc)
    if isinstance(doc, list):
        if not doc:
            return []
        first = doc[0] if isinstance(doc[0], dict) else {}
        if "messages" in first and "filePath" in first:                    # eslint -f json
            for f in doc:
                for m in f.get("messages") or []:
                    out.append(_raw(m.get("ruleId") or ("fatal" if m.get("fatal") else ""), f.get("filePath"), m.get("line"),
                                    m.get("message"), m.get("severity")))
            return out
        if "RuleID" in first or "Secret" in first:                          # gitleaks (never keep the secret itself)
            return [_raw(x.get("RuleID"), x.get("File"), x.get("StartLine"), x.get("Description") or "secret found",
                         "blocker", True) for x in doc]
        if "warnings" in first and "source" in first:                       # stylelint
            for f in doc:
                for w in f.get("warnings") or []:
                    out.append(_raw(w.get("rule"), f.get("source"), w.get("line"), w.get("text"), w.get("severity")))
            return out
        if "ruleNames" in first:                                            # markdownlint
            return [_raw("/".join(x.get("ruleNames") or []), x.get("fileName"), x.get("lineNumber"),
                         x.get("ruleDescription"), "medium") for x in doc]
        if "DetectorName" in first or "SourceMetadata" in first:             # trufflehog (ndjson, joined)
            res = []
            for x in doc:
                fs = (((x.get("SourceMetadata") or {}).get("Data") or {}).get("Filesystem") or {})
                res.append(_raw(x.get("DetectorName"), fs.get("file"), fs.get("line"),
                                f"{x.get('DetectorName', 'secret')} credential" + (" (verified)" if x.get("Verified") else ""), "blocker", True))
            return res
        if first.get("reason") in ("compiler-message", "compiler-artifact", "build-finished", "build-script-executed"):
            for x in doc:                                                   # cargo clippy --message-format=json
                m = x.get("message") or {}
                if x.get("reason") != "compiler-message" or m.get("level") not in ("error", "warning"):
                    continue
                sp = next((y for y in m.get("spans") or [] if y.get("is_primary")), (m.get("spans") or [{}])[0])
                out.append(_raw((m.get("code") or {}).get("code") or "clippy", sp.get("file_name"), sp.get("line_start"),
                                m.get("message"), m.get("level")))
            return out
        keys = set(first)
        if keys & {"file", "filename", "path"} and keys & {"message", "text", "msg"}:  # ruff, shellcheck, hadolint, ...
            for x in doc:
                loc = x.get("location") or {}
                out.append(_raw(x.get("code") or x.get("rule") or x.get("check_id") or x.get("symbol"),
                                x.get("filename") or x.get("file") or x.get("path"),
                                x.get("line") or loc.get("row") or loc.get("line"),
                                x.get("message") or x.get("text") or x.get("msg"), x.get("level") or x.get("severity") or x.get("type")))
            return out
        return None
    if not isinstance(doc, dict):
        return None
    if isinstance(doc.get("results"), list) and ("errors" in doc or "paths" in doc or "version" in doc) \
            and (not doc["results"] or "check_id" in doc["results"][0]):   # semgrep --json
        for r in doc["results"]:
            ex = r.get("extra") or {}
            out.append(_raw(r.get("check_id"), r.get("path"), (r.get("start") or {}).get("line"), ex.get("message"),
                            ex.get("severity")))
        return out
    if isinstance(doc.get("results"), list) and (not doc["results"] or "test_id" in doc["results"][0]):  # bandit
        return [_raw(r.get("test_id"), r.get("filename"), r.get("line_number"), r.get("issue_text"), r.get("issue_severity"))
                for r in doc["results"]]
    if isinstance(doc.get("results"), list) and doc["results"] and "packages" in doc["results"][0]:  # osv-scanner
        for r in doc["results"]:
            src = (r.get("source") or {}).get("path")
            for pk in r.get("packages") or []:
                name = (pk.get("package") or {}).get("name")
                for v in pk.get("vulnerabilities") or []:
                    sev = (v.get("database_specific") or {}).get("severity")
                    out.append(_raw(v.get("id"), src, None, f"{name}: {v.get('summary') or v.get('id')}", sev))
        return out
    if isinstance(doc.get("vulnerabilities"), dict) and "list" not in doc["vulnerabilities"]:  # npm audit --json (v7+)
        for name, v in doc["vulnerabilities"].items():
            via = [x.get("title") for x in v.get("via") or [] if isinstance(x, dict) and x.get("title")]
            out.append(_raw(name, "package.json", None, f"{name} {v.get('range', '')}: {(via or ['vulnerable dependency'])[0]}",
                            v.get("severity")))
        return out
    if isinstance(doc.get("advisories"), dict):                              # npm v6 / pnpm audit --json
        for a in doc["advisories"].values():
            out.append(_raw(a.get("github_advisory_id") or a.get("id"), "package.json", None,
                            f"{a.get('module_name')}: {a.get('title')}", a.get("severity")))
        return out
    if isinstance(doc.get("dependencies"), list) and (not doc["dependencies"] or "vulns" in doc["dependencies"][0]):  # pip-audit
        for d in doc["dependencies"]:
            for v in d.get("vulns") or []:
                out.append(_raw(v.get("id"), "", None, f"{d.get('name')} {d.get('version')}: {v.get('id')}"
                                + (f" (fix: {', '.join(v.get('fix_versions') or [])})" if v.get("fix_versions") else ""), None))
        return out
    if isinstance(doc.get("vulnerabilities"), dict) and "list" in doc["vulnerabilities"]:  # cargo audit --json
        for v in doc["vulnerabilities"]["list"]:
            a, pk = v.get("advisory") or {}, v.get("package") or {}
            out.append(_raw(a.get("id"), "Cargo.lock", None, f"{pk.get('name')} {pk.get('version')}: {a.get('title')}", None))
        return out
    if isinstance(doc.get("Issues"), list):                                  # gosec / golangci-lint
        for i in doc["Issues"]:
            pos = i.get("Pos") or {}
            out.append(_raw(i.get("rule_id") or i.get("FromLinter"), i.get("file") or pos.get("Filename"),
                            i.get("line") or pos.get("Line"), i.get("details") or i.get("Text"), i.get("severity") or i.get("Severity")))
        return out
    if isinstance(doc.get("warnings"), list) and "scan_info" in doc:        # brakeman
        return [_raw(w.get("check_name") or w.get("warning_type"), w.get("file"), w.get("line"),
                     f"{w.get('warning_type')}: {w.get('message')}", {"High": "high", "Medium": "medium"}.get(w.get("confidence"), "low"))
                for w in doc["warnings"]]
    if isinstance(doc.get("files"), list) and "summary" in doc:              # rubocop
        for f in doc["files"]:
            for o in f.get("offenses") or []:
                out.append(_raw(o.get("cop_name"), f.get("path"), (o.get("location") or {}).get("line"), o.get("message"),
                                o.get("severity")))
        return out
    if isinstance(doc.get("generalDiagnostics"), list):                     # pyright --outputjson
        return [_raw(d.get("rule") or "pyright", d.get("file"), ((d.get("range") or {}).get("start") or {}).get("line"),
                     d.get("message"), d.get("severity")) for d in doc["generalDiagnostics"]]
    return None


TEXT_PATTERNS = [
    # tsc: src/a.ts(12,5): error TS2322: Type ...
    re.compile(r"^(?P<file>[^\s(:][^(:]*)\((?P<line>\d+),\d+\):\s*(?P<sev>error|warning)\s+(?P<rule>TS\d+):\s*(?P<msg>.*)$"),
    # mypy / flake8 / gcc style: path:12[:5]: [error:] message [code]
    re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+)(?::\d+)?:\s*(?:(?P<sev>error|warning|note|info)\s*:\s*)?"
               r"(?P<msg>.*?)(?:\s+\[(?P<rule>[\w\-./]+)\])?\s*$"),
    re.compile(r"^\[warn\]\s+(?P<file>\S+)$"),                               # prettier --check
    re.compile(r"^would reformat (?P<file>.+)$"),                            # black --check
]


def parse_text(text):
    out = []
    for ln in text.splitlines():
        ln = ln.rstrip()
        for i, rx in enumerate(TEXT_PATTERNS):
            m = rx.match(ln)
            if not m:
                continue
            g = m.groupdict()
            if i >= 2:
                out.append(_raw("format", g["file"], None, "file is not formatted", None))
            else:
                msg, rule = g.get("msg") or "", g.get("rule")
                if not rule:
                    m2 = re.match(r"^([A-Z]{1,4}\d{2,5})\b\s*(.*)$", msg)  # flake8: E501 line too long
                    if m2:
                        rule, msg = m2.group(1), m2.group(2) or msg
                out.append(_raw(rule, g["file"], g["line"], msg, g.get("sev")))
            break
    return out


def parse_tool_output(fmt, text):
    """-> list of raw findings; raises ValueError when the output cannot be read."""
    if fmt == "text":
        return parse_text(text)
    t = text.strip()
    if not t:
        raise ValueError("no output")
    try:
        doc = json.loads(t)
    except ValueError:
        # newline-delimited JSON (trufflehog, cargo --message-format=json), or JSON after a banner line
        items = []
        for ln in t.splitlines():
            ln = ln.strip()
            if ln.startswith("{") or ln.startswith("["):
                try:
                    items.append(json.loads(ln))
                except ValueError:
                    pass
        if not items:
            raise ValueError("output is not JSON")
        doc = items[0] if len(items) == 1 else items
    if fmt == "sarif":
        if not isinstance(doc, dict) or "runs" not in doc:
            raise ValueError("output is not SARIF")
        return parse_sarif(doc)
    res = parse_json_doc(doc)
    if res is None:
        raise ValueError("JSON output of an unknown shape (set format to sarif or text, or use a supported tool)")
    return res


def norm_msg(m):
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", (m or "").lower())).strip()


def finding_fp(tool, rule, file, message):
    """Line-insensitive fingerprint: moving code around does not make an old finding new."""
    return hashlib.sha1("|".join([tool, rule, file, norm_msg(message)]).encode()).hexdigest()[:10]


def tool_error(chk, why, detail=""):
    return {"id": finding_fp(chk["name"], "tool-error", "", why), "tool": chk["name"], "kind": chk.get("kind", "other"),
            "rule": "tool-error", "file": "", "line": None, "message": (why + (f": {detail}" if detail else ""))[:600],
            "severity": "high", "blocking": bool(chk.get("blocking", True)), "tool_error": True, "status": "open"}


def git_changed_files(root, base):
    """Files changed since base plus untracked ones; None outside git (then checks get the whole tree)."""
    if git(root, "rev-parse", "--git-dir") is None:
        return None
    files = set()
    if base:
        out = git(root, "diff", "--name-only", base)
        files |= {x for x in (out or "").splitlines() if x}
    out = git(root, "ls-files", "--others", "--exclude-standard")
    files |= {x for x in (out or "").splitlines() if x}
    return sorted(f for f in files if not f.startswith(SCRATCH_DIR + "/") and os.path.isfile(os.path.join(root, f)))


def worktree_state(root):
    """Content id of the working tree (tracked + untracked, minus ignored), equal before and after a commit.
    Built in a copy of the index so the real one is never touched. None outside git."""
    idx = git(root, "rev-parse", "--git-path", "index")
    if idx is None:
        return None
    idx = idx if os.path.isabs(idx) else os.path.join(root, idx)
    fd, tmp = tempfile.mkstemp(prefix="bf-index-")
    os.close(fd)
    try:
        if os.path.isfile(idx):
            shutil.copyfile(idx, tmp)
        else:
            os.remove(tmp)
        env = dict(os.environ, GIT_INDEX_FILE=tmp)
        r = subprocess.run(["git", "-C", root, "add", "-A", "."], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            return None
        r = subprocess.run(["git", "-C", root, "write-tree"], env=env, capture_output=True, text=True)
        return r.stdout.strip() or None if r.returncode == 0 else None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def run_shell(cmd, cwd, timeout):
    """-> (returncode | None on timeout, stdout, stderr, seconds). Kills the whole process group on timeout."""
    t0 = time.time()
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()
        out, err = p.communicate()
        rc = None
    return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), round(time.time() - t0, 2)


def run_static_check(root, chk, files, outdir, mode, default_timeout):
    """Run one configured check. mode: 'baseline' (whole tree) or 'checkpoint' (changed files when scope=changed).
    A check with per_file (tools that take one path, like `gitleaks dir`) runs once per file.
    -> (result dict, findings list)."""
    name = chk["name"]
    res = {"name": name, "kind": chk.get("kind", "other"), "scope": chk.get("scope", "changed"),
           "blocking": bool(chk.get("blocking", True)), "status": None, "exit": None, "seconds": 0}
    cmd = chk["cmd"]
    exts = tuple(chk.get("ext") or ())
    mine = None if files is None else [f for f in files if not exts or f.endswith(exts)]
    if mode == "checkpoint" and chk.get("scope", "changed") == "changed" and mine == []:
        res.update(status="skipped", note="no changed files for this check")
        return res, []
    variants = [cmd]
    if "{files}" in cmd:
        whole = mode == "baseline" or chk.get("scope", "changed") == "all" or mine is None or len(mine) > STATIC_MAX_FILES
        if whole:
            variants = [cmd.replace("{files}", chk.get("all_arg", "."))]
        elif chk.get("per_file"):
            variants = [cmd.replace("{files}", shlex.quote(f)) for f in mine]
        else:
            variants = [cmd.replace("{files}", " ".join(shlex.quote(f) for f in mine))]
    secret_tool = chk.get("kind") == "secrets" or re.search(r"gitleaks|trufflehog|detect-secrets", cmd)
    findings, statuses, raw_log = [], [], []
    for n, c in enumerate(variants):
        st_, fs, rc, secs, text = _run_static_variant(root, chk, c, outdir, mode, n, default_timeout)
        statuses.append(st_)
        findings += fs
        res["exit"] = rc if res["exit"] in (None, 0) else res["exit"]
        res["seconds"] = round(res["seconds"] + secs, 2)
        raw_log.append(text)
    res["cmd"] = variants[0][:500] + (f" (+{len(variants) - 1} more files)" if len(variants) > 1 else "")
    if not secret_tool:  # raw output of a secret scanner can hold the secret: never keep it
        os.makedirs(os.path.join(outdir, "static-raw"), exist_ok=True)
        raw_p = os.path.join(outdir, "static-raw", f"{mode}-{slugify(name)}.txt")
        with open(raw_p, "w") as f:
            f.write("\n\n".join(raw_log)[:STATIC_RAW_LIMIT])
        res["raw"] = os.path.relpath(raw_p, root)
    res["status"] = next((x for x in ("timeout", "crashed") if x in statuses), "findings" if findings else "clean")
    res["findings"] = len([f for f in findings if not f.get("tool_error")])
    return res, findings


def _run_static_variant(root, chk, cmd, outdir, mode, n, default_timeout):
    """-> (status, findings, exit code, seconds, raw log text)"""
    name, fmt = chk["name"], chk.get("format", "text")
    report = None
    if "{report}" in cmd:
        report = os.path.join(outdir, f"static-{mode}-{slugify(name)}-{n}.report")
        if os.path.exists(report):
            os.remove(report)
        cmd = cmd.replace("{report}", shlex.quote(report))
    timeout = int(chk.get("timeout") or default_timeout)
    rc, out, err, secs = run_shell(cmd, root, timeout)
    text = out
    if report:
        try:
            text = open(report, errors="replace").read()
        except OSError:
            text = ""
        try:
            os.remove(report)  # parsed below; a secret scanner's report is not kept
        except OSError:
            pass
    log = f"$ {cmd}\n# exit {rc} after {secs}s\n\n{text[:STATIC_RAW_LIMIT]}\n\n# stderr\n{err[-20000:]}"
    tail = (err.strip() or out.strip())[-400:]
    if rc is None:
        return "timeout", [tool_error(chk, f"{name} timed out after {timeout}s")], rc, secs, log
    if rc not in chk.get("ok_exit", [0, 1]):
        return "crashed", [tool_error(chk, f"{name} exited with code {rc}", tail)], rc, secs, log
    try:
        raws = parse_tool_output(fmt, text if fmt != "text" else (text + "\n" + err))
    except ValueError as e:
        return "crashed", [tool_error(chk, f"{name}: {e}", tail)], rc, secs, log
    if fmt == "text" and rc != 0 and not raws:
        # the tool says something is wrong but in a form we cannot read: that is a finding, not a pass
        raws = [_raw("exit-" + str(rc), "", None, tail or f"{name} exited with code {rc}", None)]
    default_sev = chk.get("severity") or ("high" if chk.get("blocking", True) else "medium")
    findings = []
    for r in raws:
        secret = r["secret"] or chk.get("kind") == "secrets"
        sev = "blocker" if secret else sev_norm(r["severity"], default_sev)
        f = rel_path(root, r["file"])
        findings.append({"id": finding_fp(name, r["rule"], f, r["message"]), "tool": name, "kind": chk.get("kind", "other"),
                         "rule": r["rule"], "file": f, "line": r["line"], "message": r["message"], "severity": sev,
                         "blocking": bool(secret or chk.get("blocking", True)), "status": "open"})
    return ("findings" if findings else "clean"), findings, rc, secs, log


def run_all_static(root, st, files, outdir, mode, timeout):
    os.makedirs(outdir, exist_ok=True)
    results, findings = [], []
    for chk in static_checks(st):
        r, f = run_static_check(root, chk, files, outdir, mode, timeout)
        results.append(r)
        findings += f
    return results, findings


def is_blocking(f):
    return f.get("status", "open") == "open" and f.get("blocking", True) and str(f.get("severity", "")).lower() in BLOCKING_SEV


def static_attempt_findings(res):
    """static.json findings in the shape every gate uses (severity, title, location, status)."""
    out = []
    for f in res.get("findings", []) + res.get("fixed", []):
        loc = f["file"] + (f":{f['line']}" if f.get("line") else "") if f.get("file") else ""
        title = f"{f['tool']}" + (f" {f['rule']}" if f.get("rule") else "") + f": {f['message']}"
        if f.get("status") == "wontfix" and f.get("reason"):
            title += f" ({t('wontfix_l')}: {f['reason']})"
        out.append({"severity": f["severity"], "title": title[:300], "location": loc, "status": f.get("status", "open"),
                    "id": f["id"], "tool": f["tool"], "blocking": f.get("blocking", True)})
    return out


def static_metrics(res):
    fs = res.get("findings", [])
    checks = res.get("checks", [])
    return {"checks_run": sum(1 for c in checks if c["status"] not in ("skipped",)),
            "checks_skipped": sum(1 for c in checks if c["status"] == "skipped"),
            "tool_errors": sum(1 for c in checks if c["status"] in ("crashed", "timeout")),
            "new_findings": len(fs), "blocking_open": sum(1 for f in fs if is_blocking(f)),
            "fixed": len(res.get("fixed", [])), "wontfix": sum(1 for f in fs if f.get("status") == "wontfix"),
            "baseline_matched": res.get("baseline_matched", 0)}


def read_static_result(root, st, cp):
    p = os.path.join(static_evidence(root, st, cp), "static.json")
    if not os.path.isfile(p):
        return None
    with open(p) as f:
        return json.load(f)


def write_static_result(root, st, cp, res):
    d = static_evidence(root, st, cp)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "static.json.tmp")
    with open(tmp, "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, "static.json"))


def cp_base(st, cp):
    if cp.get("base_commit"):
        return cp["base_commit"]
    prev = [c for c in st["checkpoints"] if c["n"] < cp["n"] and c.get("commit")]
    return prev[-1]["commit"] if prev else (st.get("project") or {}).get("base_commit")


def static_hint(st, cp):
    """What to do about an open static gate."""
    cfg = static_cfg(st)
    if cfg.get("checks") is None:
        return t("static_hint_unset", st, cp=cp["id"])
    if not cfg.get("checks"):
        return t("static_hint_none", st, cp=cp["id"], why=cfg.get("reason") or "-")
    return t("static_hint_run", st, cp=cp["id"])


def cmd_static(a):
    root = find_root()
    if a.action == "detect":  # works before a run exists: the project scout uses it
        print(json.dumps(static_detect(root), indent=2))
        return
    if a.action in ("run", "mark") and not a.cp:
        die(t("usage_static", action=a.action))
    st = load(root)
    cfg = static_cfg(st)
    if a.action == "config":
        if a.none:
            if not a.reason:
                die(t("static_none_reason"))
            cfg.update(checks=[], reason=a.reason, not_available=[], configured_at=now())
        else:
            raw = read_json_arg(a.data, a.file)
            checks = raw if isinstance(raw, list) else raw.get("checks", [])
            clean, names = [], set()
            for c in checks:
                if not isinstance(c, dict) or not c.get("name") or not c.get("cmd"):
                    die(t("check_needs_name", c=c))
                if c["name"] in names:
                    die(t("check_dup", name=c["name"]))
                names.add(c["name"])
                if INSTALL_RE.search(c["cmd"]):
                    die(t("check_installs", name=c["name"], cmd=c["cmd"]))
                c = dict(c)
                c.setdefault("kind", "other")
                c.setdefault("scope", "changed")
                c.setdefault("format", "text")
                c.setdefault("blocking", True)
                if c["kind"] not in STATIC_KINDS:
                    die(t("check_kind", name=c["name"], kinds=", ".join(STATIC_KINDS)))
                if c["scope"] not in ("changed", "all"):
                    die(t("check_scope", name=c["name"]))
                if c["format"] not in STATIC_FORMATS:
                    die(t("check_format", name=c["name"], formats=", ".join(STATIC_FORMATS)))
                if re.search(r"(^|[\s;&|])npx\s", c["cmd"]) and not re.search(r"npx\s+(--no-install|--no)\b", c["cmd"]):
                    print(t("check_npx", name=c["name"]), file=sys.stderr)
                clean.append(c)
            cfg.update(checks=clean, not_available=(raw.get("not_available", []) if isinstance(raw, dict) else []),
                       reason=(raw.get("note", "") if isinstance(raw, dict) else ""), configured_at=now())
            if a.file:
                cfg["file"] = os.path.relpath(os.path.abspath(a.file), root)
        bl = cfg.get("baseline")
        if bl:
            # keep the baseline: fingerprints carry the tool name, so unchanged checks stay covered
            covered = set(bl.get("checks_covered") or [])
            bl["not_covered"] = [c["name"] for c in cfg["checks"] if c["name"] + "|" + c["cmd"] not in covered]
        save(root, st)
        for c in cfg["checks"]:
            print(f"  {c['name']:<16} {c['kind']:<8} scope={c['scope']:<8} {c['format']:<6} "
                  f"{t('blocking') if c['blocking'] else t('report_only')}  $ {c['cmd']}")
        for n in cfg.get("not_available", []):
            print(f"  ({t('not_available')}) {n.get('name')}: {n.get('reason', '')}")
        if (cfg.get("baseline") or {}).get("not_covered"):
            print(t("baseline_not_covered", names=", ".join(cfg["baseline"]["not_covered"])))
        print(t("checks_recorded", n=len(cfg["checks"])) + ("" if cfg["checks"] else " " + t("none_available", why=cfg["reason"])))
        print(t("checks_next") if cfg["checks"] else t("checks_next_none"))
        return
    if a.action == "show":
        if a.cp:
            cp = get_cp(st, a.cp)
            res = read_static_result(root, st, cp)
            print(json.dumps(res, indent=2, ensure_ascii=False) if res else t("no_static_run", cp=cp["id"]))
        else:
            print(json.dumps({k: v for k, v in cfg.items()}, indent=2, ensure_ascii=False))
        return
    if a.action == "baseline":
        if cfg.get("checks") is None:
            die(t("baseline_no_config"))
        if not cfg["checks"]:
            print(t("baseline_nothing"))
            return
        dirty = git(root, "status", "--porcelain")
        if dirty and not a.allow_dirty:
            die(t("baseline_dirty"))
        outdir = os.path.join(run_dir(root, st["slug"]), "evidence", "baseline")
        results, findings = run_all_static(root, st, [], outdir, "baseline", a.timeout)
        counts = {}
        for f in findings:
            if not f.get("tool_error"):
                counts[f["id"]] = counts.get(f["id"], 0) + 1
        bl = {"at": now(), "commit": git(root, "rev-parse", "HEAD"), "checks": results,
              "findings": [f for f in findings if not f.get("tool_error")], "counts": counts,
              "tool_errors": [f for f in findings if f.get("tool_error")]}
        p = os.path.join(run_dir(root, st["slug"]), "static-baseline.json")
        with open(p, "w") as f:
            json.dump(bl, f, indent=2, ensure_ascii=False)
        cfg["baseline"] = {"at": bl["at"], "commit": bl["commit"], "file": os.path.relpath(p, root),
                           "checks_covered": [c["name"] + "|" + c["cmd"] for c in cfg["checks"]], "not_covered": [],
                           "findings": len(bl["findings"]), "tool_errors": [f["message"] for f in bl["tool_errors"]]}
        save(root, st)
        for r in results:
            print(f"  {r['name']:<16} {name_of(CHECK_NAMES, r['status']):<11} exit={r['exit']} {r['seconds']}s  {t('findings_l')}={r.get('findings', 0)}")
        print(t("baseline_done", n=len(bl["findings"]), commit=(bl["commit"] or "-")[:10]))
        if bl["tool_errors"]:
            print(t("baseline_tool_errors") + "\n  " + "\n  ".join(f["message"] for f in bl["tool_errors"]))
        return
    if a.action == "mark":
        cp = get_cp(st, a.cp)
        res = read_static_result(root, st, cp)
        if not res:
            die(t("no_static_run", cp=cp["id"]))
        status = a.ids[-1] if a.ids and a.ids[-1] in ("fixed", "wontfix") else None
        if not status or len(a.ids) < 2:
            die(t("usage_mark", cp=cp["id"]))
        if status == "fixed":
            die(t("mark_fixed_refused", cp=cp["id"]))
        if not a.reason:
            die(t("wontfix_reason"))
        ids = set(a.ids[:-1])
        hit = [f for f in res["findings"] if f["id"] in ids]
        if not hit:
            die(t("no_finding", ids=", ".join(sorted(ids)), cp=cp["id"]))
        if any(f.get("kind") == "secrets" for f in hit) and not a.force:
            die(t("secret_blocker"))
        wf = cp["gates"]["static"].setdefault("wontfix", {})
        for f in hit:
            f["status"], f["reason"] = "wontfix", a.reason
            wf[f["id"]] = a.reason
        write_static_result(root, st, cp, res)
        static_record_attempt(st, cp, res)
        save(root, st)
        print(t("marked_wontfix", n=len(hit), cp=cp["id"], open=static_metrics(res)["blocking_open"]))
        return
    # run
    cp = get_cp(st, a.cp)
    gs = cp["gates"]["static"]
    if st["phase"] != "building":
        die(t("static_not_building", phase=name_of(PHASE_NAMES, st["phase"])))
    if cp["status"] == "pending":
        die(t("cp_not_started", cp=cp["id"]))
    earlier = [g for g in CP_GATES[:CP_GATES.index("static")] if cp["gates"][g]["status"] not in GATE_DONE]
    if earlier:
        die(t("static_earlier", gates=", ".join(name_of(GATE_NAMES, g) for g in earlier), cp=cp["id"]))
    if cfg.get("checks") is None:
        die(static_hint(st, cp))
    if not cfg["checks"]:
        gs["status"] = "skipped"
        gs["skip_reason"] = t("skip_no_tools", st, why=cfg.get("reason") or "-")
        save(root, st)
        print(f"{cp['id']} · {name_of(GATE_NAMES, 'static')}: {name_of(STATUS_NAMES, 'skipped')} ({gs['skip_reason']})")
        print(next_action(st))
        return
    if not cfg.get("baseline"):
        print(t("no_baseline_warn"), file=sys.stderr)
    if gs["status"] == "interrupted":
        continue_interrupted_attempt(gs)
    files = git_changed_files(root, cp_base(st, cp))
    outdir = static_evidence(root, st, cp)
    results, findings = run_all_static(root, st, files, outdir, "checkpoint", a.timeout)
    # subtract the baseline: per fingerprint, only occurrences beyond the baseline count are new
    bl_counts = {}
    if cfg.get("baseline"):
        try:
            bl_counts = dict(json.load(open(os.path.join(root, cfg["baseline"]["file"]))).get("counts", {}))
        except (OSError, ValueError):
            bl_counts = {}
    new, matched, per_tool = [], 0, {}
    for f in findings:
        pt = per_tool.setdefault(f["tool"], {"new": 0, "baseline": 0, "blocking_new": 0})
        if not f.get("tool_error") and bl_counts.get(f["id"], 0) > 0:
            bl_counts[f["id"]] -= 1
            matched += 1
            pt["baseline"] += 1
            continue
        new.append(f)
        if not f.get("tool_error"):
            pt["new"] += 1
            pt["blocking_new"] += 1 if is_blocking(f) else 0
    # per check: what is new for this checkpoint and what the baseline already had, so a tool that only
    # finds pre-existing issues reads as clean, not as a problem
    for r in results:
        pt = per_tool.get(r["name"], {"new": 0, "baseline": 0, "blocking_new": 0})
        r.update(pt)
    prev = read_static_result(root, st, cp) or {}
    wontfix = gs.get("wontfix", {})
    for f in new:
        if f["id"] in wontfix:
            f["status"], f["reason"] = "wontfix", wontfix[f["id"]]
    now_ids = {f["id"] for f in new}
    fixed = [dict(f, status="fixed") for f in prev.get("findings", []) if f["id"] not in now_ids and f.get("status") != "wontfix"]
    fixed_all = {f["id"]: f for f in prev.get("fixed", []) + fixed if f["id"] not in now_ids}
    res = {"cp": cp["id"], "at": now(), "base": cp_base(st, cp), "tree": worktree_state(root),
           "changed_files": files if files is not None else "(not a git repo: whole tree)", "checks": results, "findings": new, "fixed": list(fixed_all.values()),
           "baseline_matched": matched, "run": (prev.get("run") or 0) + 1}
    res["summary"] = static_metrics(res)
    write_static_result(root, st, cp, res)
    static_record_attempt(st, cp, res)
    m = res["summary"]
    save(root, st)
    for r in results:
        print(f"  {r['name']:<16} {check_result(r):<24} exit={r['exit']} {r['seconds']}s" + (f"  {r.get('note')}" if r.get("note") else ""))
    print(t("static_run_line", cp=cp["id"], run=res["run"], new=m["new_findings"], open=m["blocking_open"], fixed=m["fixed"],
            wontfix=m["wontfix"], pre=m["baseline_matched"], errors=m["tool_errors"]))
    for f in new:
        if f.get("status") == "open":
            loc = f["file"] + (f":{f['line']}" if f.get("line") else "")
            print(f"  [{f['severity']}{'' if f.get('blocking') else ', ' + t('report_only')}] {f['id']} {f['tool']} {f['rule']} {loc}: {f['message'][:160]}")
    print(f"{t('evidence')}: {os.path.relpath(os.path.join(outdir, 'static.json'), root)}")
    last_att = gs["attempts"][-1] if gs["attempts"] else {}
    if gs["status"] == "passed":
        print(t("recheck_clean"))
    elif gs["status"] == "failed" and (last_att.get("recheck") or last_att.get("summary", "").startswith("re-check")):
        print(t("recheck_reopened", cp=cp["id"]))
    elif m["blocking_open"]:
        print(t("static_next_failed", cp=cp["id"]))
    else:
        print(t("static_next_passed", cp=cp["id"]))


def static_record_attempt(st, cp, res):
    """Mirror the latest static run into the gate's current attempt, so reports and the viewer show it.
    A run after the gate passed is a re-check: on changed code it becomes its own attempt, and a new
    blocking finding turns the gate back to failed."""
    gs = cp["gates"]["static"]
    last = gs["attempts"][-1] if gs["attempts"] else None
    m = static_metrics(res)
    if gs["status"] == "passed" and last and last.get("result") == "passed":
        if last.get("tree") == res.get("tree"):
            att = last
        else:
            ok = not m["blocking_open"]
            att = {"n": len(gs["attempts"]) + 1, "started_at": now(), "ended_at": now(), "result": "passed" if ok else "failed",
                   "recheck": True, "summary": t("recheck_summary", st) + ("" if ok else t("recheck_blocking", st, n=m["blocking_open"]))}
            gs["attempts"].append(att)
            gs["status"] = att["result"]
    else:
        att = last if last and not last.get("result") else None
        if att is None:
            att = {"n": len(gs["attempts"]) + 1, "started_at": now(), "result": None}
            gs["attempts"].append(att)
        gs["status"] = "running"
        att["summary"] = t("static_attempt_summary", st, run=res.get("run"), checks=m["checks_run"], new=m["new_findings"],
                           open=m["blocking_open"], fixed=m["fixed"], pre=m["baseline_matched"])
    # the latest run carries the whole picture (open, fixed, won't fix); older attempts keep their summary
    # and metrics, so findings are not counted twice in the reports
    for old in gs["attempts"]:
        if old is not att:
            old.pop("findings", None)
    att["findings"] = static_attempt_findings(res)
    att["metrics"] = res["summary"] = m
    att["checks"] = [{k: c.get(k) for k in ("name", "kind", "status", "exit", "seconds", "findings", "note", "new", "baseline",
                                            "blocking_new") if c.get(k) is not None} for c in res["checks"]]
    att["evidence"] = [f"{SCRATCH_DIR}/{st['slug']}/evidence/{cp['id']}/static.json"]
    att["tree"], att["run"] = res.get("tree"), res.get("run")


STATIC_TOOLS = {
    # name: (kind, how to find it)
    "semgrep": ("sast", ["semgrep"]), "bandit": ("sast", ["bandit"]), "gosec": ("sast", ["gosec"]),
    "brakeman": ("sast", ["brakeman"]), "codeql": ("sast", ["codeql"]),
    "gitleaks": ("secrets", ["gitleaks"]), "trufflehog": ("secrets", ["trufflehog"]),
    "eslint": ("lint", ["node_modules/.bin/eslint", "eslint"]), "prettier": ("format", ["node_modules/.bin/prettier", "prettier"]),
    "stylelint": ("lint", ["node_modules/.bin/stylelint", "stylelint"]),
    "markdownlint": ("lint", ["node_modules/.bin/markdownlint-cli2", "node_modules/.bin/markdownlint", "markdownlint-cli2", "markdownlint"]),
    "tsc": ("types", ["node_modules/.bin/tsc", "tsc"]),
    "ruff": ("lint", [".venv/bin/ruff", "ruff"]), "black": ("format", [".venv/bin/black", "black"]),
    "flake8": ("lint", [".venv/bin/flake8", "flake8"]), "mypy": ("types", [".venv/bin/mypy", "mypy"]),
    "pyright": ("types", ["node_modules/.bin/pyright", ".venv/bin/pyright", "pyright"]),
    "pip-audit": ("deps", [".venv/bin/pip-audit", "pip-audit"]), "osv-scanner": ("deps", ["osv-scanner"]),
    "npm": ("deps", ["npm"]), "pnpm": ("deps", ["pnpm"]),
    "rubocop": ("lint", ["bin/rubocop", "rubocop"]), "golangci-lint": ("lint", ["golangci-lint"]),
    "cargo-clippy": ("lint", ["cargo-clippy"]), "cargo-audit": ("deps", ["cargo-audit"]),
    "shellcheck": ("lint", ["shellcheck"]), "hadolint": ("lint", ["hadolint"]),
}
STATIC_CONFIG_FILES = [
    ".semgrep.yml", ".semgrep.yaml", ".semgrep", ".semgrepignore", ".gitleaks.toml", ".gitleaksignore",
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", "eslint.config.js", "eslint.config.mjs",
    "eslint.config.cjs", "eslint.config.ts", ".prettierrc", ".prettierrc.json", ".prettierrc.js", "prettier.config.js",
    ".stylelintrc", ".stylelintrc.json", "stylelint.config.js", ".markdownlint.json", ".markdownlint.yaml", ".markdownlint-cli2.jsonc",
    "tsconfig.json", "pyproject.toml", "setup.cfg", ".flake8", "tox.ini", "mypy.ini", "ruff.toml", ".ruff.toml", "pyrightconfig.json",
    ".bandit", ".rubocop.yml", ".golangci.yml", ".golangci.yaml", "Cargo.toml", ".shellcheckrc", ".hadolint.yaml",
    ".pre-commit-config.yaml", "package.json", "Makefile", "justfile", "Taskfile.yml",
]
CI_GLOBS = [".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml", "bitbucket-pipelines.yml",
            ".circleci/config.yml", "azure-pipelines.yml", "Jenkinsfile", ".buildkite/*.yml", ".woodpecker.yml"]


def static_detect(root):
    """What deterministic tooling this project already has: installed tools, config files, CI steps, runners."""
    tools = {}
    for name, (kind, cands) in STATIC_TOOLS.items():
        found = None
        for c in cands:
            if "/" in c:
                if os.access(os.path.join(root, c), os.X_OK):
                    found = c
                    break
            elif shutil.which(c):
                found = shutil.which(c)
                break
        tools[name] = {"kind": kind, "path": found}
    configs = [f for f in STATIC_CONFIG_FILES if os.path.exists(os.path.join(root, f))]
    pyproject = read_text(root, "pyproject.toml")
    py_tools = [t for t in ("ruff", "black", "mypy", "pyright", "bandit", "flake8") if f"[tool.{t}" in pyproject]
    scripts = {}
    try:
        pkg = json.load(open(os.path.join(root, "package.json")))
        scripts = {k: v for k, v in (pkg.get("scripts") or {}).items()
                   if re.search(r"lint|format|prettier|type|tsc|check|audit|semgrep|secret", k + " " + v, re.I)}
    except (OSError, ValueError):
        pass
    tool_re = re.compile(r"\b(" + "|".join(re.escape(t) for t in list(STATIC_TOOLS) + ["codeql-action", "npm audit", "pnpm audit",
                                                                                     "clippy", "cargo audit", "prettier --check"]) + r")\b")
    ci = []
    for g in CI_GLOBS:
        for p in sorted(glob.glob(os.path.join(root, g))):
            lines = [ln.strip()[:160] for ln in read_text(root, p, 200000).splitlines() if tool_re.search(ln)]
            ci.append({"file": os.path.relpath(p, root), "lines": lines[:25]})
    docker = False
    if shutil.which("docker"):
        try:
            docker = subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            docker = False
    runners = {"uvx": bool(shutil.which("uvx")), "pipx": bool(shutil.which("pipx")), "docker_running": docker}
    return {"available": {k: f"{v['path']} ({v['kind']})" for k, v in tools.items() if v["path"]},
            "not_found": sorted(k for k, v in tools.items() if not v["path"]), "config_files": configs, "pyproject_tools": py_tools, "package_scripts": scripts,
            "ci": ci, "runners": runners,
            "note": "Prefer what the project and its CI already run. A missing tool may be proposed as a dev dependency "
                    "of the project's own stack at the plan stop (installed in its own commit before the baseline); "
                    "semgrep and gitleaks may instead run through a zero-install runner (uvx semgrep, pipx run semgrep, "
                    "docker run) when one is present."}


# ---------------------------------------------------------------- next action

def next_action(st, root=None):
    """What to do next, in the run's language. With `root`, unhandled viewer messages come first."""
    hint = inbox_hint(root, st["slug"], st) if root else ""
    base = _next_action(st)
    return f"{hint} {t('then', st)}: {base}" if hint else base


def _next_action(st):
    ph = st["phase"]
    stg = st.get("stages", {})
    if ph == "intake":
        if stg.get("context", {}).get("status") != "done":
            return t("na_intake", st)
        return t("na_intake_done", st)
    if ph == "brief":
        return t("na_brief", st)
    if ph == "awaiting_brief_approval":
        return t("na_wait_brief", st)
    if ph == "design":
        d = stg.get("design", {})
        if d.get("status") in (None, "pending"):
            return t("na_design_decide", st)
        if d.get("review", {}).get("status") != "passed":
            return t("na_design_make", st)
        return t("na_design_ready", st)
    if ph == "awaiting_design_approval":
        return t("na_wait_design", st)
    if ph == "planning":
        if not st["checkpoints"]:
            return t("na_plan", st)
        if not any(cp.get("tests") for cp in st["checkpoints"]):
            return t("na_tests", st)
        return t("na_plan_done", st)
    if ph == "awaiting_plan_approval":
        return t("na_wait_plan", st)
    if ph == "documenting":
        return t("na_documenting", st)
    if ph == "awaiting_human_review":
        return t("na_wait_review", st)
    if ph == "paused":
        return t("na_paused", st, why=st.get("pause_reason", ""))
    if ph == "done":
        return t("na_done", st)
    for cp in st["checkpoints"]:
        if cp["status"] == "passed":
            continue
        if cp["status"] == "pending":
            return t("na_start", st, cp=cp["id"], title=cp["title"])
        for g in CP_GATES:
            gs = cp["gates"][g]
            if gs["status"] == "interrupted":
                last = (st.get("interruptions") or [{}])[-1]
                when = t("na_when", st, err=last.get("error", "error"), at=last.get("at", "?")) if last else ""
                return t("na_interrupted", st, cp=cp["id"], gate=g, gname=name_of(GATE_NAMES, g, st), when=when)
            if gs["status"] not in GATE_DONE:
                if g == "static":
                    return t("na_static", st, cp=cp["id"], status=name_of(STATUS_NAMES, gs["status"], st), hint=static_hint(st, cp))
                if g == "behavior":
                    return t("na_behavior", st, cp=cp["id"], status=name_of(STATUS_NAMES, gs["status"], st))
                return t("na_gate", st, cp=cp["id"], gate=g, gname=name_of(GATE_NAMES, g, st),
                         status=name_of(STATUS_NAMES, gs["status"], st))
        return t("na_finish", st, cp=cp["id"])
    return t("na_all_passed", st)


def open_work(st):
    """List of unfinished items that should keep the orchestrator working."""
    if st["phase"] == "documenting":
        return [t("ow_docs", st, status=name_of(STATUS_NAMES, st["stages"].get("docs", {}).get("status", "pending"), st))]
    if st["phase"] != "building":
        return []
    items = []
    for cp in st["checkpoints"]:
        if cp["status"] == "passed":
            continue
        pend = [name_of(GATE_NAMES, g, st) for g in CP_GATES if cp["gates"][g]["status"] not in GATE_DONE]
        items.append(t("ow_cp", st, cp=cp["id"], title=cp["title"], gates=", ".join(pend) or t("ow_finish", st)))
    return items


# ---------------------------------------------------------------- cost measurement

PRICING_FILE = "pricing.json"
PRICING_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h", "fast_multiplier")
PRICING_STALE_DAYS = 30


def load_pricing():
    with open(os.path.join(SKILL_DIR, PRICING_FILE)) as f:
        return json.load(f)


def save_pricing(pricing):
    with open(os.path.join(SKILL_DIR, PRICING_FILE), "w") as f:
        json.dump(pricing, f, indent=2, ensure_ascii=False)
        f.write("\n")


def pricing_age_days(pricing):
    ver = pricing.get("verified_at")
    if not ver:
        return None
    try:
        d = dt.date.fromisoformat(ver)
    except ValueError:
        return None
    return (dt.date.today() - d).days


def pricing_hint(st=None):
    """Nudge to verify pricing.json at the start of a run: the date of the last check, or that it is stale."""
    pricing = load_pricing()
    ver = pricing.get("verified_at")
    age = pricing_age_days(pricing)
    if not ver:
        return t("pricing_never", st)
    if age is not None and age >= PRICING_STALE_DAYS:
        return t("pricing_stale", st, date=ver, days=age)
    return t("pricing_check_hint", st, date=ver)


def pricing_verified_note(st=None):
    ver = load_pricing().get("verified_at")
    return t("cost_verified_line", st, date=ver) if ver else t("cost_verified_none", st)


def price_for(pricing, model):
    best = None
    for key in pricing["models"]:
        if model and model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return (best, pricing["models"][best]) if best else (None, None)


def transcript_files(session_id):
    base = os.path.expanduser("~/.claude/projects")
    main = glob.glob(os.path.join(base, "*", f"{session_id}.jsonl"))
    subs = glob.glob(os.path.join(base, "*", session_id, "subagents", "*.jsonl"))
    return main, subs


TS_RE = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')


def read_usage_records(path, kind, meta, activity=None):
    """API calls with usage from one transcript; every line's timestamp goes into `activity`."""
    recs = []
    try:
        f = open(path, errors="replace")
    except OSError:
        return recs
    with f:
        for line in f:
            if activity is not None:
                m_ts = TS_RE.search(line)
                if m_ts:
                    t = parse_ts(m_ts.group(1))
                    if t:
                        activity.append(t)
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message")
            if not isinstance(m, dict) or not m.get("usage") or d.get("type") != "assistant":
                continue
            if m.get("model") in (None, "<synthetic>"):
                continue
            recs.append({
                "id": m.get("id") or d.get("requestId") or d.get("uuid"),
                "ts": d.get("timestamp"),
                "model": m.get("model"),
                "usage": m["usage"],
                "kind": kind,
                "meta": meta,
                "sidechain": bool(d.get("isSidechain")),
            })
    return recs


def usage_tokens(u):
    cc = u.get("cache_creation") or {}
    c5 = cc.get("ephemeral_5m_input_tokens")
    c1 = cc.get("ephemeral_1h_input_tokens")
    total_cw = u.get("cache_creation_input_tokens") or 0
    if c5 is None and c1 is None:
        c5, c1 = total_cw, 0
    return {
        "input": u.get("input_tokens") or 0,
        "cache_write_5m": c5 or 0,
        "cache_write_1h": c1 or 0,
        "cache_read": u.get("cache_read_input_tokens") or 0,
        "output": u.get("output_tokens") or 0,
    }


def usd(pricing, model, tok, speed=None):
    key, p = price_for(pricing, model)
    if not p:
        return None
    inp = p["input"]
    cw5 = p.get("cache_write_5m", inp * pricing.get("cache_write_5m_multiplier", 1.25))
    cw1 = p.get("cache_write_1h", inp * pricing.get("cache_write_1h_multiplier", 2.0))
    cost = (tok["input"] * inp
            + tok["cache_write_5m"] * cw5
            + tok["cache_write_1h"] * cw1
            + tok["cache_read"] * p.get("cache_read", inp * 0.1)
            + tok["output"] * p["output"]) / 1e6
    if speed == "fast":
        cost *= p.get("fast_multiplier", 1.0)
    return cost


def empty_bucket():
    return {"input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0, "output": 0,
            "total_tokens": 0, "usd": 0.0, "messages": 0, "unpriced_messages": 0}


def add_to(b, tok, cost):
    for k in ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output"):
        b[k] += tok[k]
    b["total_tokens"] += sum(tok.values())
    b["messages"] += 1
    if cost is None:
        b["unpriced_messages"] += 1
    else:
        b["usd"] += cost


def phase_intervals(st, end):
    """[(phase, start, end)] from phase_log."""
    log = st.get("phase_log", [])
    out = []
    for i, e in enumerate(log):
        s = parse_ts(e["at"])
        t = parse_ts(log[i + 1]["at"]) if i + 1 < len(log) else end
        if s and t:
            out.append((e["phase"], s, t))
    return out


def idle_gap_seconds(st):
    """A gap without any transcript activity longer than this counts as idle, not as build time.
    Bash calls time out at 10 minutes, so a longer silence is almost never real work."""
    return float(os.environ.get("BUILDFLOW_IDLE_GAP_MIN") or st.get("idle_gap_minutes") or 10) * 60


def overlap(a, b, ivs):
    return sum(max(0.0, (min(b, y) - max(a, x)).total_seconds()) for x, y in ivs)


def compute_cost(st):
    pricing = load_pricing()
    start = parse_ts(st["created_at"])
    finished = parse_ts(st.get("finished_at"))
    end = finished or dt.datetime.now(dt.timezone.utc)
    approved = parse_ts(st.get("approved_at"))
    stage_ends = []   # (stage label, approved at) in order; calls before an approval belong to that stage
    for ap in st.get("approvals", []):
        if ap.get("stage") in ("brief", "design") and parse_ts(ap.get("at")):
            stage_ends.append((ap["stage"], parse_ts(ap["at"])))

    # collect records from all sessions that touched this run
    recs, files_found, activity = [], 0, []
    subagent_spans = []
    for sid in st.get("sessions", []):
        mains, subs = transcript_files(sid)
        for p in mains:
            files_found += 1
            recs += read_usage_records(p, "main", {}, activity)
        for p in subs:
            files_found += 1
            meta = {}
            mp = p[:-len(".jsonl")] + ".meta.json"
            if os.path.isfile(mp):
                try:
                    meta = json.load(open(mp))
                except ValueError:
                    meta = {}
            r = read_usage_records(p, "subagent", meta, activity)
            recs += r
            ts = [parse_ts(x["ts"]) for x in r if x["ts"]]
            ts = [t for t in ts if t and start <= t <= end]
            if ts:
                subagent_spans.append((min(ts), max(ts), meta.get("description", "")))

    cps = st["checkpoints"]
    windows = []
    for cp in cps:
        s, e = parse_ts(cp.get("started_at")), parse_ts(cp.get("ended_at")) or (end if cp.get("started_at") else None)
        if s:
            windows.append((cp["id"], s, e))

    totals, by_model, by_role, by_cp = empty_bucket(), {}, {}, {}
    by_cp_role, by_cp_model = {}, {}   # the same split per checkpoint / phase, for scoped reports
    unpriced_models = set()
    # one API call can be written as several lines; keep the one with the final (highest) output count
    uniq = {}
    for r in recs:
        prev = uniq.get(r["id"])
        if prev is None or (r["usage"].get("output_tokens") or 0) > (prev["usage"].get("output_tokens") or 0):
            uniq[r["id"]] = r
    for r in uniq.values():
        t = parse_ts(r["ts"])
        if not t or t < start or t > end:
            continue
        tok = usage_tokens(r["usage"])
        cost = usd(pricing, r["model"], tok, r["usage"].get("speed"))
        if cost is None:
            unpriced_models.add(r["model"])

        # role + checkpoint attribution
        cp_id, role = None, "orchestrator"
        if r["kind"] == "subagent":
            desc = (r["meta"] or {}).get("description", "") or ""
            m = TAG_RE.match(desc)
            if m:
                scope, role = m.group(1).lower(), m.group(2).lower()
                if re.match(r"^cp\d+$", scope) or scope.isdigit():
                    cp_id = norm_cp(scope)
                elif scope in ("plan", "planning"):
                    cp_id = "planning"
                elif scope in ("context", "brief", "design"):
                    cp_id = scope
                else:
                    cp_id = scope
            else:
                role = "subagent (untagged)"
        if cp_id is None:
            for wid, s, e in windows:
                if s <= t <= e:
                    cp_id = wid
            if cp_id is None:
                for label, at in stage_ends:
                    if t <= at:
                        cp_id = label
                        break
            if cp_id is None:
                if approved is None or t < approved:
                    cp_id = "planning"
                else:
                    cp_id = "review & feedback"

        add_to(totals, tok, cost)
        add_to(by_model.setdefault(r["model"], empty_bucket()), tok, cost)
        add_to(by_role.setdefault(role, empty_bucket()), tok, cost)
        add_to(by_cp.setdefault(cp_id, empty_bucket()), tok, cost)
        add_to(by_cp_role.setdefault(cp_id, {}).setdefault(role, empty_bucket()), tok, cost)
        add_to(by_cp_model.setdefault(cp_id, {}).setdefault(r["model"], empty_bucket()), tok, cost)

    # time: wall = active + idle (no activity for longer than the idle gap: rate limits,
    # crashes, a closed laptop) + waiting (phases where the run waits on the human)
    idle_gap = idle_gap_seconds(st)
    wait_iv = [(a, b) for ph, a, b in phase_intervals(st, end) if ph in WAIT_PHASES]
    points = [start] + sorted(t for t in activity if start <= t <= end) + [end]
    gaps = [(a, b) for a, b in zip(points, points[1:]) if (b - a).total_seconds() > idle_gap]

    def split(s, e):
        """(wall, waiting, idle, active) seconds for the window s..e"""
        w = max(0.0, (e - s).total_seconds())
        wait = overlap(s, e, wait_iv)
        idle = 0.0
        for a, b in gaps:
            a2, b2 = max(a, s), min(b, e)
            if b2 > a2:
                idle += (b2 - a2).total_seconds() - overlap(a2, b2, wait_iv)
        return w, wait, idle, max(0.0, w - wait - idle)

    wall, waiting, idle, active = split(start, end)
    agent_seconds = sum((b - a).total_seconds() for a, b, _ in subagent_spans)
    cp_time, cp_wall, cp_idle = {}, {}, {}
    for cp in cps:
        s, e = parse_ts(cp.get("started_at")), parse_ts(cp.get("ended_at"))
        if s:
            w, _, i, act = split(s, e or end)
            cp_time[cp["id"]], cp_wall[cp["id"]], cp_idle[cp["id"]] = act, w, i
    interruptions = [x for x in st.get("interruptions", [])
                     if (parse_ts(x.get("at")) or start) >= start and (parse_ts(x.get("at")) or end) <= end]

    return {
        "computed_at": now(),
        "sessions": st.get("sessions", []),
        "transcript_files": files_found,
        "totals": totals,
        "by_model": by_model,
        "by_role": by_role,
        "by_checkpoint": by_cp,
        "by_checkpoint_role": by_cp_role,
        "by_checkpoint_model": by_cp_model,
        "unpriced_models": sorted(unpriced_models),
        "time": {
            "wall_seconds": wall,
            "waiting_seconds": waiting,
            "idle_seconds": idle,
            "active_seconds": active,
            "idle_gap_seconds": idle_gap,
            "idle_periods": len([1 for a, b in gaps if (b - a).total_seconds() - overlap(a, b, wait_iv) > idle_gap]),
            "interruptions": len(interruptions),
            "interruption_types": sorted({x.get("error", "unknown") for x in interruptions}),
            "subagent_seconds": agent_seconds,
            "subagent_runs": len(subagent_spans),
            "checkpoint_seconds": cp_time,
            "checkpoint_wall_seconds": cp_wall,
            "checkpoint_idle_seconds": cp_idle,
        },
        "pricing_note": "API-equivalent cost at list prices (pricing.json). On a Claude subscription you are not billed per token.",
    }


# ---------------------------------------------------------------- formatting helpers

def fmt_dur(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_tok(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1e6:.2f}M"
    if n >= 1_000:
        return f"{n / 1e3:.1f}k"
    return str(n)


def fmt_usd(x):
    return "-" if x is None else f"${x:,.2f}"


def gate_counts(cp):
    out = {}
    for g in CP_GATES:
        gs = cp["gates"][g]
        f_all = [f for a in gs["attempts"] for f in a.get("findings", [])]
        out[g] = {
            "status": gs["status"],
            "attempts": len(gs["attempts"]),
            "findings": len(f_all),
            "fixed": sum(1 for f in f_all if f.get("status") == "fixed"),
            "open": sum(1 for f in f_all if f.get("status", "open") == "open"),
        }
    return out


def last_metrics(cp, gate):
    for a in reversed(cp["gates"][gate]["attempts"]):
        if a.get("metrics"):
            return a["metrics"]
    return {}


def latest_test_metrics(cps):
    """The behavior-gate metrics of the most recent test run across checkpoints (the whole suite as it stood
    then), not summed across checkpoints: each run re-runs the growing suite, so a sum inflates hugely."""
    best, best_at = {}, ""
    for cp in cps:
        for a in reversed(cp["gates"]["behavior"]["attempts"]):
            m = a.get("metrics")
            if m and m.get("tests_total") is not None:
                at = a.get("ended_at") or a.get("started_at") or ""
                if at >= best_at:
                    best_at, best = at, m
                break
    return best


# ---------------------------------------------------------------- test-first (BDD scenarios, red -> green)
# tests.json may give every planned test a Given/When/Then scenario (`scenario: {given, when, then}`, a
# `gherkin` string, or the older one-line `given_when_then`) and the done_when item(s) it proves. The
# behavior gate records the red run (tests written first, failing for the right reason) and the green run.

TEST_KINDS = ("unit", "integration", "e2e", "ui-gate")
GWT_WORDS = {"given": "given", "gegeven": "given", "when": "when", "als": "when", "wanneer": "when",
             "then": "then", "dan": "then", "and": "and", "en": "and", "but": "and", "maar": "and"}
GWT_LINE = re.compile(r"^\s*(given|gegeven|when|als|wanneer|then|dan|and|en|but|maar)\b[:,]?\s*(.*)$", re.I)
GWT_ONE = re.compile(r"^\s*(?:given|gegeven)\s+(?P<given>.+?)[,;]?\s+(?:when|als|wanneer)\s+(?P<when>.+?)[,;]?\s+"
                     r"(?:then|dan)\s+(?P<then>.+?)\s*\.?\s*$", re.I | re.S)


def parse_gwt(text):
    """'Given a, when b, then c' (one line) or Gherkin lines (Given/When/Then/And, or Gegeven/Als/Dan/En)
    -> {given, when, then}, or None when the text has no such shape."""
    text = str(text or "").strip()
    if not text:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip() and not re.match(r"^\s*(scenario|feature|functionaliteit)\b", ln, re.I)]
    if len(lines) > 1:
        out, last = {"given": [], "when": [], "then": []}, None
        for ln in lines:
            m = GWT_LINE.match(ln)
            if not m:
                if last:
                    out[last].append(ln.strip())
                continue
            k = GWT_WORDS[m.group(1).lower()]
            text = m.group(2).strip()
            if k == "and":  # And/En/But continues the previous step and keeps its own word
                k, text = last, f"{m.group(1).lower()} {text}"
            if k:
                out[k].append(text)
                last = k
        if any(out.values()):
            return {k: ", ".join(v) for k, v in out.items()}
    m = GWT_ONE.match(text)
    if m:
        return {k: m.group(k).strip() for k in ("given", "when", "then")}
    return None


def done_when_refs(test):
    """The done_when items (1-based) a test proves: `done_when: 2 | [1, 3] | "done_when 2"`, else from `covers`."""
    raw = test.get("done_when")
    if raw is None:
        cov = str(test.get("covers") or "")
        if not re.search(r"done[_ ]when|klaar", cov, re.I):
            return []
        raw = cov
    vals = raw if isinstance(raw, list) else [raw]
    out = []
    for v in vals:
        for n in re.findall(r"\d+", str(v)):
            if int(n) not in out:
                out.append(int(n))
    return out


def norm_test(x):
    """A planned test as loaded from tests.json, with a parsed scenario when there is one. Unknown fields stay."""
    if isinstance(x, str):
        return {"name": x}
    if not isinstance(x, dict):
        return {"name": str(x)}
    d = dict(x)
    if not d.get("name"):
        d["name"] = d.get("title") or d.get("test") or "?"
    if not d.get("kind") and d.get("type"):
        d["kind"] = d["type"]
    sc = d.get("scenario")
    if isinstance(sc, dict):
        sc = {k: str(sc.get(k) or "").strip() for k in ("given", "when", "then")}
        d["scenario"] = sc if any(sc.values()) else None
    else:
        d["scenario"] = parse_gwt(sc if isinstance(sc, str) else d.get("gherkin") or d.get("given_when_then"))
    if d["scenario"] is None:
        d.pop("scenario")
    refs = done_when_refs(d)
    if refs:
        d["done_when_refs"] = refs
    return d


def norm_red(raw):
    """The red run of a behavior gate: tests written first and run before any implementation.
    Accepts the test writer's reply ({tests_new, red_confirmed, failure_reasons}) or {tests, failed, right_reason, failures}."""
    if not isinstance(raw, dict):
        return None
    fails = []
    for f in raw.get("failures") or raw.get("failure_reasons") or []:
        if isinstance(f, dict):
            fails.append({"test": str(f.get("test") or f.get("name") or ""), "reason": str(f.get("reason") or f.get("error") or "")})
        else:
            txt = str(f)
            name, _, why = txt.partition(": ")
            fails.append({"test": name.strip(), "reason": why.strip()} if why else {"test": "", "reason": txt.strip()})
    right = raw.get("right_reason", raw.get("red_confirmed"))
    tests = raw.get("tests", raw.get("tests_new"))
    failed = raw.get("failed", raw.get("tests_failed"))
    if failed is None and right:
        failed = tests
    return {"at": now(), "tests": int(tests) if str(tests or "").isdigit() else (len(fails) or None),
            "failed": int(failed) if str(failed if failed is not None else "").isdigit() else None,
            "right_reason": bool(right) if right is not None else None, "failures": fails[:50],
            "files": raw.get("files") or [], "tests_red": raw.get("tests_red") or []}


def norm_green(raw, metrics=None):
    raw = raw if isinstance(raw, dict) else {}
    m = metrics or {}
    g = {k: raw.get(k, m.get(k)) for k in ("tests_total", "tests_passed", "tests_failed", "tests_new")}
    return {"at": now(), **{k: v for k, v in g.items() if v is not None}}


def _match(name, other):
    a, b = (name or "").strip().lower(), (other or "").strip().lower()
    return bool(a and b) and (a == b or a in b or b in a)


def tdd_summary(cp):
    """Per checkpoint: planned scenarios with their state (planned, red, red_wrong, green), the red run and the green run."""
    gs = cp["gates"].get("behavior", {})
    atts = gs.get("attempts", [])
    red = next((x["red"] for x in reversed(atts) if x.get("red")), None)
    green = next((x["green"] for x in reversed(atts) if x.get("green")), None)
    m = last_metrics(cp, "behavior") if atts else {}
    passed = gs.get("status") == "passed"
    if passed and not green and m:
        green = {k: m[k] for k in ("tests_total", "tests_passed", "tests_failed", "tests_new") if k in m}
    red_ok = bool(red and red.get("right_reason")) or (not red and m.get("red_confirmed") is True)
    named = [f["test"] for f in (red or {}).get("failures", []) if f.get("test")] + list((red or {}).get("tests_red") or [])
    tests = [norm_test(x) for x in cp.get("tests") or []]
    scen = []
    for x in tests:
        if passed:
            state = "green"
        elif red and red.get("right_reason") is False:
            state = "red_wrong"
        elif red_ok and (not named or any(_match(x["name"], n) for n in named)):
            state = "red"
        else:
            state = "planned"
        reason = next((f["reason"] for f in (red or {}).get("failures", []) if _match(x["name"], f.get("test"))), "")
        scen.append({"name": x["name"], "kind": x.get("kind", ""), "scenario": x.get("scenario"),
                     "done_when": [{"n": n, "text": (cp.get("done_when") or [])[n - 1] if 0 < n <= len(cp.get("done_when") or []) else ""}
                                   for n in x.get("done_when_refs", [])],
                     "covers": x.get("covers", ""), "text": x.get("given_when_then") or x.get("gherkin") or "",
                     "state": state, "red_reason": reason})
    return {"scenarios": scen, "planned": len(tests), "with_scenario": sum(1 for x in tests if x.get("scenario")),
            "red": red, "green": green, "red_confirmed": red_ok if (red or "red_confirmed" in m) else None,
            "tests_new": (red or {}).get("tests") or m.get("tests_new")}


def gwt_words(st=None):
    return ("Gegeven", "Als", "Dan") if lang_of(st) == "nl" else ("Given", "When", "Then")


def md_tdd(st, cp):
    """The planned scenarios of a checkpoint report, as BDD (Given/When/Then)."""
    td = tdd_summary(cp)
    if not td["scenarios"]:
        return []
    gw = gwt_words(st)
    out = [f"## {t('md_scenarios' if td['with_scenario'] else 'md_planned', st)} ({len(td['scenarios'])})", ""]
    for x in td["scenarios"]:
        dw = ", ".join(f"#{d['n']}" for d in x["done_when"])
        out.append(f"- [{t('sc_' + x['state'], st)}] {x['name']}" + (f" · {name_of(KIND_NAMES, x['kind'], st)}" if x["kind"] else "")
                   + (f" · done_when {dw}" if dw else ""))
        sc = x["scenario"]
        if sc:
            out.append(f"  - {gw[0]} {sc['given']} · {gw[1].lower()} {sc['when']} · {gw[2].lower()} {sc['then']}")
    out.append("")
    return out


# ---------------------------------------------------------------- markdown reports

def md_cost_table(bucket_map, label, st=None, names=None):
    rows = sorted(bucket_map.items(), key=lambda kv: -kv[1]["usd"])
    out = [f"| {label} | tokens | output | cache read | {t('cost_l', st)} |", "|---|---:|---:|---:|---:|"]
    for k, b in rows:
        lbl = name_of(names, k, st) if names else k
        out.append(f"| {lbl} | {fmt_tok(b['total_tokens'])} | {fmt_tok(b['output'])} | {fmt_tok(b['cache_read'])} | {fmt_usd(b['usd'])} |")
    return "\n".join(out)


def role_label(k, st=None):
    return name_of(ROLE_NAMES, k, st) if k in ROLE_NAMES else name_of(BUCKET_NAMES, k, st)


def md_checkpoint(st, cp, cost):
    gc = gate_counts(cp)
    S = lambda k: name_of(STATUS_NAMES, k, st)
    G = lambda g: name_of(GATE_NAMES, g, st)
    idle = (cost['time'].get('checkpoint_idle_seconds') or {}).get(cp['id'], 0) > 0
    lines = [f"# buildflow · {cp['id']} · {cp['title']}", "",
             f"**{t('md_feature', st)}:** {st['title']}  ", f"**{t('md_status', st)}:** {S(cp['status'])}  ",
             f"**{t('md_profile', st)}:** {name_of(PROFILE_NAMES, profile_of(st), st)}  ",
             f"**Commit:** `{cp.get('commit') or '-'}`  ",
             f"**{t('md_duration', st)}:** {fmt_dur(cost['time']['checkpoint_seconds'].get(cp['id']))} {t('active_l', st)}"
             + (t("md_wall_idle", st, wall=fmt_dur(cost['time']['checkpoint_wall_seconds'].get(cp['id'])),
                  idle=fmt_dur(cost['time']['checkpoint_idle_seconds'].get(cp['id']))) if idle else ""), "",
             f"## {t('md_built', st)}", "", cp["summary"] or "-", ""]
    if cp.get("done_when"):
        lines += [f"**{t('md_done_when', st)}:**", ""] + [f"{i}. {x}" for i, x in enumerate(cp["done_when"], 1)] + [""]
    lines += md_tdd(st, cp)
    lines += [f"## {t('md_gates', st)}", "", t("md_gate_head", st), "|---|---|---:|---:|---:|---:|"]
    for g in CP_GATES:
        c = gc[g]
        lines.append(f"| {G(g)} | {S(c['status'])} | {c['attempts']} | {c['findings']} | {c['fixed']} | {c['open']} |")
    lines.append("")
    for g in CP_GATES:
        gs = cp["gates"][g]
        if gs["status"] == "skipped":
            lines += [f"### {G(g)}: {S('skipped')}", "", gs.get("skip_reason", ""), ""]
            continue
        lines += [f"### {G(g)}", ""]
        for a in gs["attempts"]:
            lines.append(f"- {t('attempt_l', st)} {a['n']}: **{S(a.get('result') or 'running')}** · {a.get('summary') or ''}")
            if a.get("metrics"):
                lines.append(f"  - {t('metrics_l', st)}: " + ", ".join(f"{k}={v}" for k, v in a["metrics"].items()))
            if a.get("files"):
                lines.append(f"  - {t('files_l', st)}: " + ", ".join(f"`{x}`" for x in a["files"]))
            if a.get("checks"):
                lines.append("  - checks: " + ", ".join(f"{c['name']} {check_result(c, st)}" for c in a["checks"]))
            for f in a.get("findings", []):
                loc = f" ({f['location']})" if f.get("location") else ""
                why = f" ({t('reason_l', st)}: {f['reason']})" if f.get("reason") else ""
                lines.append(f"  - [{f.get('severity', '?')}] {f.get('title', '')}{loc} → {S(f.get('status', 'open'))}{why}")
        lines.append("")
    b = cost["by_checkpoint"].get(cp["id"], empty_bucket())
    lines += [f"## {t('md_cp_cost', st)}", "",
              f"- tokens: {fmt_tok(b['total_tokens'])} (output {fmt_tok(b['output'])}, cache read {fmt_tok(b['cache_read'])})",
              f"- {t('api_cost', st)}: {fmt_usd(b['usd'])}",
              f"- {t('by_role', st)}: " + (", ".join(f"{role_label(k, st)} {fmt_usd(v['usd'])}" for k, v in sorted(
                  (cost.get("by_checkpoint_role") or {}).get(cp["id"], {}).items(), key=lambda kv: -kv[1]["usd"])) or "-"),
              "- " + t("run_so_far", st, tok=fmt_tok(cost['totals']['total_tokens']), usd=fmt_usd(cost['totals']['usd']),
                       active=fmt_dur(cost['time']['active_seconds'])),
              f"- {pricing_verified_note(st)}", ""]
    done = sum(1 for c in st["checkpoints"] if c["status"] == "passed")
    lines += [f"## {t('md_progress', st)}", "", t("md_progress_line", st, done=done, n=len(st["checkpoints"]), next=next_action(st)), ""]
    return "\n".join(lines)


def static_outcome(cps, st=None):
    ms = [last_metrics(c, "static") for c in cps if c["gates"]["static"]["status"] != "skipped"]
    if not ms:
        return t("static_not_run", st)
    tot = lambda k: sum(int(m.get(k, 0) or 0) for m in ms)
    return t("static_outcome", st, n=len(ms), new=tot('new_findings') + tot('fixed'), fixed=tot('fixed'),
             wontfix=tot('wontfix'), open=tot('blocking_open'))


def md_static_section(st):
    """Deterministic checks: which ones are configured and what the baseline was (per-checkpoint results are
    in the checkpoint's own gate section, not repeated here)."""
    cfg = st.get("static") or {}
    cps = st["checkpoints"]
    out = [f"## {t('md_static', st)}", ""]
    if cfg.get("checks") is None:
        migrated = any(c["gates"]["static"].get("migrated") or c["gates"]["static"].get("added_mid_checkpoint") for c in cps)
        out += [t("static_unset_migrated" if migrated else "static_unset", st), ""]
    elif not cfg["checks"]:
        out += [t("static_no_tools", st, why=cfg.get('reason') or '-'), ""]
    else:
        out.append(t("checks_l", st) + ": " + ", ".join(
            f"{c['name']} ({c['kind']}, {c['scope']}{'' if c.get('blocking', True) else ', ' + t('report_only', st)})" for c in cfg["checks"]))
        bl = cfg.get("baseline") or {}
        out.append(t("baseline_line", st, n=bl.get('findings', 0), commit=(bl.get('commit') or '-')[:10]) if bl else t("baseline_none", st))
        out.append("")
    if cfg.get("not_available"):
        out += [t("not_available_line", st) + ": " + ", ".join(f"{n.get('name')} ({n.get('reason', '')})" for n in cfg["not_available"]), ""]
    return out


def md_tdd_totals(st):
    """Final report: scenarios and new tests per checkpoint."""
    cps = st["checkpoints"]
    rows = [(cp, tdd_summary(cp)) for cp in cps]
    if not any(td["planned"] or td["red"] or td["green"] for _, td in rows):
        return []
    out = [f"## {t('md_tdd_totals_head', st)}", "",
           t("tdd_totals", st, scen=sum(td["with_scenario"] for _, td in rows), planned=sum(td["planned"] for _, td in rows),
             new=sum(int(td["tests_new"] or 0) for _, td in rows),
             red=sum(1 for _, td in rows if td["red_confirmed"]), n=len(cps)), "",
           t("md_tdd_head", st), "|---|---|---:|---:|---:|---|"]
    for cp, td in rows:
        g = td["green"] or {}
        out.append(f"| {cp['n']} | {cp['title']} | {td['planned']} | {td['with_scenario']} | {td['tests_new'] or '-'} | "
                   + (f"{g.get('tests_passed', '?')}/{g.get('tests_total', '?')}" if g else "-") + " |")
    out.append("")
    return out


def md_final(st, cost):
    cps = st["checkpoints"]
    tm = cost["time"]
    S = lambda k: name_of(STATUS_NAMES, k, st)
    ltm = latest_test_metrics(cps)
    tests_total = int(ltm.get("tests_total", 0) or 0)
    tests_passed = int(ltm.get("tests_passed", 0) or 0)
    all_f = [f for cp in cps for g in CP_GATES for a in cp["gates"][g]["attempts"] for f in a.get("findings", [])]
    lines = [f"# buildflow · {t('md_final_title', st)} · {st['title']}", "",
             f"**{t('md_goal', st)}:** {st.get('goal', '')}", "",
             f"**{t('md_phase', st)}:** {name_of(PHASE_NAMES, st['phase'], st)} · **Branch:** `{st.get('project', {}).get('branch') or '-'}` · "
             f"**Base:** `{(st.get('project', {}).get('base_commit') or '-')[:10]}` → **Head:** `{(git(st['_root'], 'rev-parse', 'HEAD') or '-')[:10]}`"
             f" · **{t('md_profile', st)}:** {name_of(PROFILE_NAMES, profile_of(st), st)}", "",
             f"## {t('md_outcome', st)}", "",
             "- " + t("out_cps", st, done=sum(1 for c in cps if c['status'] == 'passed'), n=len(cps),
                      fb=sum(1 for c in cps if c.get('source') == 'feedback')),
             "- " + t("out_tests", st, p=tests_passed, n=tests_total),
             "- " + t("out_findings", st, n=len(all_f), fixed=sum(1 for f in all_f if f.get('status') == 'fixed'),
                      open=sum(1 for f in all_f if f.get('status', 'open') == 'open'), wontfix=sum(1 for f in all_f if f.get('status') == 'wontfix')),
             f"- {t('md_static', st).lower()}: " + static_outcome(cps, st),
             "- " + t("out_rounds", st, n=len(st.get('feedback', []))), "",
             f"## {t('md_checkpoints', st)}", "",
             "| # | checkpoint | " + " | ".join(name_of(GATE_NAMES, g, st) for g in CP_GATES) + " | " + t("md_final_head_tail", st) + " |",
             "|---|---|---|---|---|---|---|---:|---:|---:|---|"]
    for cp in cps:
        gc = gate_counts(cp)
        b = cost["by_checkpoint"].get(cp["id"], empty_bucket())
        att = sum(gc[g]["attempts"] for g in CP_GATES)
        lines.append(f"| {cp['n']} | {cp['title']} | " + " | ".join(S(gc[g]['status']) for g in CP_GATES)
                     + f" | {att} | {fmt_dur(tm['checkpoint_seconds'].get(cp['id']))} | {fmt_usd(b['usd'])} | `{(cp.get('commit') or '-')[:8]}` |")
    lines += [""] + md_tdd_totals(st) + md_static_section(st)
    lines += [f"## {t('md_cost_time', st)}", "",
              "- " + t("tot_tokens", st, tok=fmt_tok(cost['totals']['total_tokens']), inp=fmt_tok(cost['totals']['input']),
                       cw=fmt_tok(cost['totals']['cache_write_5m'] + cost['totals']['cache_write_1h']),
                       cr=fmt_tok(cost['totals']['cache_read']), out=fmt_tok(cost['totals']['output'])),
              f"- {t('api_cost', st)}: **{fmt_usd(cost['totals']['usd'])}**",
              "- " + t("time_line", st, active=fmt_dur(tm['active_seconds']), wait=fmt_dur(tm['waiting_seconds']),
                       idle=fmt_dur(tm['idle_seconds']), wall=fmt_dur(tm['wall_seconds'])),
              "- " + t("int_line", st, n=tm['interruptions']) + (f" ({', '.join(tm['interruption_types'])})" if tm['interruptions'] else "")
              + " · " + t("idle_periods", st, min=int(tm['idle_gap_seconds'] // 60), n=tm['idle_periods']),
              "- " + t("sub_line", st, n=tm['subagent_runs'], d=fmt_dur(tm['subagent_seconds'])), "",
              md_cost_table(cost["by_role"], t("role_l", st), st, ROLE_NAMES), "",
              md_cost_table(cost["by_checkpoint"], t("phase_cp_l", st), st, BUCKET_NAMES), "",
              md_cost_table(cost["by_model"], "model", st), "",
              f"_{t('pricing_note', st)}_", ""]
    if cost.get("unpriced_models"):
        lines += [f"_{t('unpriced', st)}: {', '.join(cost['unpriced_models'])}_", ""]
    lines += [f"_{pricing_verified_note(st)}_", ""]
    stg = st.get("stages", {})
    b, dz = stg.get("brief", {}), stg.get("design", {})
    lines += [f"## {t('md_brief_design', st)}", "",
              f"- brief: {S(b.get('status', '-'))} ({S(b.get('source', '-'))}) · `{b.get('file') or '-'}`"
              + (f" · {S('approved')} {b['approved_at']}" if b.get("approved_at") else ""),
              f"- design: {S(dz.get('status', '-'))}" + (f" · {dz.get('reason')}" if dz.get("reason") else "")]
    rv = dz.get("review", {})
    if rv.get("attempts"):
        allf = [f for at in rv["attempts"] for f in at.get("findings", [])]
        lines.append("- " + t("design_review_line", st, status=S(rv.get('status')), n=len(rv['attempts']), f=len(allf),
                                fixed=sum(1 for f in allf if f.get('status') == 'fixed')))
    for k, label in (("design_md", t("design_file_l", st)), ("prototype", "prototype")):
        if dz.get(k):
            lines.append(f"- {label}: `{dz[k]}`")
    if dz.get("states"):
        lines.append(f"- {t('proto_states', st)}: {', '.join(dz['states'])}")
    lines.append("")
    fd = stg.get("docs", {})
    doc_files = sorted({x for cp in cps for at in cp["gates"]["docs"]["attempts"] for x in at.get("files", [])}
                       | {x for at in fd.get("attempts", []) for x in at.get("files", [])})
    for k in ("design_md", "prototype"):
        if dz.get(k):
            doc_files = sorted(set(doc_files) | {dz[k]})
    lines += [f"## {t('md_docs', st)}", "",
              "- " + t("docs_gate_line", st, status=S(fd.get('status', '-')), n=len(fd.get('attempts', []))),
              "- " + t("docs_cps_line", st, n=sum(1 for cp in cps if cp['gates']['docs']['status'] != 'skipped'), total=len(cps))]
    lines += [f"- `{x}`" for x in doc_files] or ["- " + t("no_doc_files", st)]
    lines.append("")
    open_f = [(cp["id"], g, f) for cp in cps for g in CP_GATES for a in cp["gates"][g]["attempts"] for f in a.get("findings", [])
              if f.get("status", "open") in ("open", "wontfix")]
    if open_f:
        lines += [f"## {t('md_open_findings', st)}", ""]
        lines += [f"- {cid} · {name_of(GATE_NAMES, g, st)} · [{f.get('severity', '?')}] {f.get('title', '')} → {S(f.get('status', 'open'))}"
                  + (f" ({t('reason_l', st)}: {f['reason']})" if f.get("reason") else "") for cid, g, f in open_f]
        lines.append("")
    if st.get("interruptions"):
        lines += [f"## {t('md_interruptions', st)}", ""]
        for x in st["interruptions"]:
            lines.append(f"- {x['at']} · {x['error']} ({x.get('source', 'hook')}) · {t('md_phase', st).lower()} "
                         f"{name_of(PHASE_NAMES, x.get('phase'), st)} · {t('int_attempts', st)}: {', '.join(x.get('attempts', [])) or '-'}")
        lines.append("")
    if st.get("feedback"):
        lines += [f"## {t('md_human_feedback', st)}", ""]
        for i, fb in enumerate(st["feedback"], 1):
            lines.append(f"{i}. {fb['text']} → {', '.join(fb.get('checkpoints', [])) or t('no_new_cps', st)}")
        lines.append("")
    lp = os.path.join(run_dir(st["_root"], st["slug"]), "learnings.md")
    if os.path.isfile(lp):
        lines += [f"## {t('md_learnings', st)}", "", open(lp).read().strip(), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML rendering

def payload(root, st, focus=None):
    d = dict(st)
    d.pop("_root", None)
    lp = os.path.join(run_dir(root, st["slug"]), "learnings.md")
    d["learnings"] = open(lp).read() if os.path.isfile(lp) else ""
    d["next_action"] = next_action(st)
    d["focus"] = focus
    stg = st.get("stages", {})
    d["brief_text"] = read_text(root, stg.get("brief", {}).get("file"))
    d["feature_context_text"] = read_text(root, stg.get("context", {}).get("feature_file"))
    d["project_context_text"] = read_text(root, stg.get("context", {}).get("project_file"), 20000)
    # links in the page are relative to where the html file lives
    d["rel_root"] = "../../../" if focus else "../../"
    d["active_checkpoint"] = active_cp(st)
    d["tdd"] = {cp["id"]: tdd_summary(cp) for cp in st.get("checkpoints", [])}
    return d


def active_cp(st):
    """The checkpoint the run is on: the running or blocked one, else the next one to start while building."""
    cps = st.get("checkpoints", [])
    for cp in cps:
        if cp["status"] in ("in_progress", "blocked"):
            return cp["id"]
    ph = st.get("paused_from") if st.get("phase") == "paused" else st.get("phase")
    if ph == "building":
        for cp in cps:
            if cp["status"] != "passed":
                return cp["id"]
    return None


# ---------------------------------------------------------------- all runs: registry and overview page

def all_runs(root):
    out = []
    for p in sorted(glob.glob(os.path.join(bf_dir(root), "*", "state.json"))):
        try:
            st = load(root, os.path.basename(os.path.dirname(p)), required=False)
        except (ValueError, OSError, KeyError):
            continue  # a broken or half-written run should not break the overview
        if st:
            out.append(st)
    return sorted(out, key=lambda s: s.get("created_at") or "", reverse=True)


def run_summary(root, st, active=None):
    cps = st.get("checkpoints", [])
    cost = st.get("cost") or {}
    reports = {k: f"{st['slug']}/{v['html']}" for k, v in (st.get("reports") or {}).items()
               if os.path.isfile(os.path.join(run_dir(root, st["slug"]), v.get("html", "")))}
    return {"slug": st["slug"], "title": st.get("title", st["slug"]), "goal": st.get("goal", ""),
            "phase": st.get("phase"), "paused_from": st.get("paused_from"), "active": st["slug"] == active,
            "checkpoints_passed": sum(1 for c in cps if c["status"] == "passed"), "checkpoints_total": len(cps),
            "checkpoints": [{"id": c["id"], "title": c["title"], "status": c["status"]} for c in cps],
            "usd": (cost.get("totals") or {}).get("usd"), "tokens": (cost.get("totals") or {}).get("total_tokens"),
            "active_seconds": (cost.get("time") or {}).get("active_seconds"),
            "created_at": st.get("created_at"), "finished_at": st.get("finished_at"), "updated_at": st.get("updated_at"),
            "branch": (st.get("project") or {}).get("branch"), "lang": st.get("lang"),
            "viewer": f"{st['slug']}/viewer.html", "reports": reports,
            "interruption": next(({"at": x.get("at"), "error": x.get("error"), "status": x.get("status", "open"),
                                   "resumed_at": x.get("resumed_at")} for x in reversed(st.get("interruptions", []))), None),
            "interrupted_gates": [f"{c['id']}:{g}" for c, g in interrupted_gates(st)]}


FEATURES_HEAD = re.compile(r"^(#{1,6})\s*(?:\d+[.)]\s*)?\**\s*(features|existing features|product features|functionaliteiten)\b",
                           re.I)


def features_section(root):
    """The 'Features' section the project scout writes in .buildflow/context.md (existing product features)."""
    text = read_text(root, os.path.join(bf_dir(root), "context.md"), 200000)
    lines, out, level = text.splitlines(), [], None
    for ln in lines:
        m = re.match(r"^(#{1,6})\s", ln)
        if level is None:
            h = FEATURES_HEAD.match(ln)
            if h:
                level = len(h.group(1))
            continue
        if m and len(m.group(1)) <= level:
            break
        out.append(ln)
    return "\n".join(out).strip()


def overview_payload(root):
    runs = all_runs(root)
    act = active_slug(root)
    cur = next((s for s in runs if s["slug"] == act), runs[0] if runs else None)
    return {"overview": True, "project": os.path.basename(os.path.abspath(root)), "lang": (cur or {}).get("lang", "en"),
            "active": act, "generated_at": now(), "runs": [run_summary(root, s, act) for s in runs],
            "features_text": features_section(root)}


def write_overview(root):
    """.buildflow/index.html (all runs + existing features) and overview.json for its live refresh."""
    d = bf_dir(root)
    if not os.path.isdir(d):
        return None
    data = overview_payload(root)
    with open(os.path.join(SKILL_DIR, "assets", "viewer.html")) as f:
        tpl = f.read()
    title = ("Overzicht" if data["lang"] == "nl" else "Overview") + " · " + data["project"]
    page = tpl.replace("/*__BF_DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")) \
              .replace("__BF_TITLE__", html.escape(title))
    for name, body in (("overview.json", json.dumps(data, ensure_ascii=False)), ("index.html", page)):
        tmp = os.path.join(d, name + ".tmp")
        with open(tmp, "w") as f:
            f.write(body)
        os.replace(tmp, os.path.join(d, name))
    return os.path.join(d, "index.html")


def render_html(root, st, focus=None):
    with open(os.path.join(SKILL_DIR, "assets", "viewer.html")) as f:
        tpl = f.read()
    data = json.dumps(payload(root, st, focus), ensure_ascii=False).replace("</", "<\\/")
    title = st["title"] if not focus else (f"{st['title']} · {focus}")
    return tpl.replace("/*__BF_DATA__*/null", data).replace("__BF_TITLE__", html.escape(title))


def write_data_json(root, st):
    d = run_dir(root, st["slug"])
    with open(os.path.join(d, "data.json"), "w") as f:
        json.dump(payload(root, st), f, ensure_ascii=False)


def write_viewer(root, st):
    p = os.path.join(run_dir(root, st["slug"]), "viewer.html")
    with open(p, "w") as f:
        f.write(render_html(root, st))
    return p


def open_path(p):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            webbrowser.open("file://" + p)
    except Exception:
        pass


def refresh_cost(root, st):
    st["_root"] = root
    st["cost"] = compute_cost(st)
    return st["cost"]


def write_report(root, st, which):
    cost = refresh_cost(root, st)
    rd = os.path.join(run_dir(root, st["slug"]), "reports")
    os.makedirs(rd, exist_ok=True)
    if which == "final":
        md = md_final(st, cost)
        name = "final"
    else:
        cp = get_cp(st, which)
        md = md_checkpoint(st, cp, cost)
        name = cp["id"]
        cp["report"] = f"reports/{name}.html"
    st.setdefault("reports", {})[name] = {"md": f"reports/{name}.md", "html": f"reports/{name}.html", "at": now()}
    st.pop("_root", None)
    save(root, st)
    with open(os.path.join(rd, f"{name}.md"), "w") as f:
        f.write(md)
    with open(os.path.join(rd, f"{name}.html"), "w") as f:
        f.write(render_html(root, st, focus=name))
    write_viewer(root, st)
    write_overview(root)  # the new report is on disk now, so the overview can link it
    return md, os.path.join(rd, f"{name}.html")


# ---------------------------------------------------------------- commands

def cmd_init(a):
    root = os.path.abspath(a.root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    slug = a.slug or slugify(a.title)
    d = run_dir(root, slug)
    lang = a.lang or lang_of()  # --lang, else BUILDFLOW_LANG, else en
    if os.path.isfile(os.path.join(d, "state.json")) and not a.force:
        die(t("run_exists", slug=slug))
    # another feature is still open: never leave it half-way without an explicit choice
    cur = active_slug(root)
    cst = load(root, cur, required=False) if cur and cur != slug else None
    if cst and cst["phase"] not in ("done", "paused"):
        if not a.park:
            die(t("active_unfinished", cur=cur, phase=name_of(PHASE_NAMES, cst["phase"])))
        cst["pause_reason"] = t("parked_reason", cst, slug=slug)
        cst["paused_from"] = cst["phase"]
        set_phase(cst, "paused")
        save(root, cst)
        print(t("parked", cur=cur, phase=name_of(PHASE_NAMES, cst["paused_from"])))
    os.makedirs(os.path.join(d, "evidence"), exist_ok=True)
    os.makedirs(os.path.join(d, "reports"), exist_ok=True)
    t0 = now()
    st = {
        "version": 1, "slug": slug, "title": a.title, "goal": a.goal or "", "lang": lang,
        "mode": a.mode, "profile": PROFILE_ALIASES[a.profile],"created_at": t0, "updated_at": t0, "approved_at": None, "finished_at": None,
        "phase": "intake", "phase_log": [{"phase": "intake", "at": t0}],
        "stages": {"context": {"status": "pending"}, "brief": {"status": "pending"},
                   "design": {"status": "pending", "review": {"status": "pending", "attempts": []}},
                   "docs": {"status": "pending", "attempts": []}},
        "approvals": [],
        "sessions": [a.session] if a.session and "CLAUDE_SESSION_ID" not in a.session else [],
        "project": {"root": root, "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
                    "base_commit": git(root, "rev-parse", "HEAD")},
        "checkpoints": [], "feedback": [], "questions": [], "assumptions": [],
    }
    lp = os.path.join(d, "learnings.md")
    if not os.path.isfile(lp):
        # carry over project-wide learnings from earlier runs
        shared = os.path.join(bf_dir(root), "learnings.md")
        with open(lp, "w") as f:
            f.write(f"# Learnings: {a.title}\n\n{t('learn_head', st)}\n")
            if os.path.isfile(shared):
                f.write(f"\n## {t('learn_carried', st)}\n\n" + open(shared).read().strip() + "\n")
    with open(os.path.join(bf_dir(root), "active"), "w") as f:
        f.write(slug)
    gi = os.path.join(bf_dir(root), ".gitignore")
    if not os.path.isfile(gi):
        with open(gi, "w") as f:
            f.write("# buildflow run data. Remove this file if you want to commit reports.\n*\n")
    save(root, st)
    if a.redirect_from and os.path.abspath(a.redirect_from) != root:
        rd = os.path.join(os.path.abspath(a.redirect_from), ".buildflow")
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, "redirect"), "w") as f:
            f.write(root)
        if not os.path.isfile(os.path.join(rd, ".gitignore")):
            with open(os.path.join(rd, ".gitignore"), "w") as f:
                f.write("*\n")
        print(t("redirect_written", rd=rd, root=root))
    write_viewer(root, st)  # the overview links every run's viewer, so it exists from the start
    print(t("initialised", st, slug=slug, d=d))
    print(t("status_profile", st, profile=name_of(PROFILE_NAMES, st["profile"], st)) + " · " + models_line(st))
    print(pricing_hint(st))
    print(next_action(st))


def cmd_use(a):
    root = find_root()
    if not os.path.isfile(os.path.join(run_dir(root, a.slug), "state.json")):
        die(t("no_such_run", slug=a.slug, d=bf_dir(root)))
    with open(os.path.join(bf_dir(root), "active"), "w") as f:
        f.write(a.slug)
    write_overview(root)
    print(t("active_run", slug=a.slug))


def cmd_runs(a):
    root = find_root()
    act = active_slug(root)
    runs = [run_summary(root, s, act) for s in all_runs(root)]
    if a.json:
        print(json.dumps(runs, indent=2, ensure_ascii=False))
        return
    if not runs:
        print(t("no_runs"))
        return
    for r in runs:
        ph = name_of(PHASE_NAMES, r["phase"]) + (f" ({t('from_l')} {name_of(PHASE_NAMES, r['paused_from'])})"
                                                  if r["phase"] == "paused" and r.get("paused_from") else "")
        print(f"{'*' if r['active'] else ' '} {r['slug']:<28} {ph:<24} {r['checkpoints_passed']}/{r['checkpoints_total']} cps  "
              f"{fmt_usd(r['usd']):>8}  {fmt_dur(r['active_seconds']):>8} {t('active_l')}  "
              f"{(r['created_at'] or '')[:10]} -> {(r['finished_at'] or '')[:10] or '...':<10}  {r['branch'] or '-'}  {r['title']}")
    p = write_overview(root)
    print(t("overview_line", path=os.path.relpath(p, root) if p else "-"))


def cmd_session(a):
    root = find_root()
    st = load(root)
    if a.id and "CLAUDE_SESSION_ID" not in a.id and a.id not in st["sessions"]:
        st["sessions"].append(a.id)
        save(root, st)
    print(t("sessions_l") + ":", ", ".join(st["sessions"]) or t("none_paren"))


def cmd_project(a):
    root = find_root()
    st = load(root)
    for kv in a.kv:
        if "=" not in kv:
            die(t("expected_kv", kv=kv))
        k, v = kv.split("=", 1)
        st["project"][k.strip()] = v
    save(root, st)
    print(json.dumps(st["project"], indent=2))


def cmd_plan(a):
    root = find_root()
    st = load(root)
    raw = read_json_arg(a.data, a.file)
    items = raw.get("checkpoints", raw if isinstance(raw, list) else [])
    if not items:
        die(t("plan_empty"))
    started = [c for c in st["checkpoints"] if c["status"] != "pending"]
    if started and not a.append:
        die(t("plan_started"))
    if not a.append:
        st["checkpoints"] = []
    base = len(st["checkpoints"])
    for i, it in enumerate(items, 1):
        st["checkpoints"].append(new_checkpoint(base + i, it, source=a.source, st=st))
    for k in ("questions", "assumptions", "out_of_scope", "size"):
        if raw.get(k) if isinstance(raw, dict) else None:
            st[k] = raw[k]
    save(root, st)
    write_viewer(root, st)
    print(t("plan_loaded", n=len(items), total=len(st["checkpoints"])))
    for w in plan_warnings(st, st["checkpoints"][base:], whole=not a.append):
        print(w)
    print(next_action(st))


SMALL_PROJECT_LINES = 1500   # rough rule: fewer lines to change than this is a small project
SMALL_PROJECT_MAX_CPS = 5


def plan_warnings(st, new_cps, whole=True):
    """Soft checks on a loaded plan: gates in proportion to the work. Warnings, never refusals."""
    out = []
    size = st.get("size") if isinstance(st.get("size"), dict) else {}
    n = len(st["checkpoints"])
    try:
        est = int(size.get("est_lines")) if size.get("est_lines") is not None else None
    except (TypeError, ValueError):
        est = None
    small = size.get("class") == "small" or (est is not None and est < SMALL_PROJECT_LINES)
    if not size and whole:
        out.append(t("plan_no_size", st))
    elif small and n > SMALL_PROJECT_MAX_CPS:
        out.append(t("plan_many_small", st, n=n, size=", ".join(f"{k}={v}" for k, v in size.items())))
    no_docs = [c["id"] for c in new_cps if c["gates"]["docs"].get("skip_reason") == t("skip_docs_no_scope", st)]
    if no_docs:
        out.append(t("plan_docs_no_scope", st, cps=", ".join(no_docs)))
    no_ui = [c["id"] for c in new_cps if c["gates"]["ui"]["status"] != "skipped" and not str(c.get("ui_scope") or "").strip()]
    if no_ui:
        out.append(t("plan_ui_no_scope", st, cps=", ".join(no_ui)))
    return out


def cmd_tests(a):
    root = find_root()
    st = load(root)
    raw = read_json_arg(a.data, a.file)
    raw = raw.get("checkpoints", raw)
    n, with_sc, no_ref = 0, 0, []
    for cid, tests in raw.items():
        cp = get_cp(st, cid)
        cp["tests"] = [norm_test(x) for x in (tests or [])]
        n += len(cp["tests"])
        with_sc += sum(1 for x in cp["tests"] if x.get("scenario"))
        covered = {r for x in cp["tests"] for r in x.get("done_when_refs", [])}
        no_ref += [f"{cp['id']} #{i}" for i in range(1, len(cp.get("done_when") or []) + 1) if cp["tests"] and covered and i not in covered]
    save(root, st)
    write_viewer(root, st)
    print(t("tests_attached", n=n, sc=with_sc))
    if n and with_sc < n:
        print(t("tests_no_scenario", n=n - with_sc))
    if no_ref:
        print(t("tests_uncovered", items=", ".join(no_ref[:12])))
    print(next_action(st))


def stages_blocking_plan(st):
    """What still has to happen before planning may be approved or building may start."""
    stg = st.get("stages", {})
    out = []
    if stg.get("brief", {}).get("status") not in ("approved", "skipped"):
        out.append(t("block_brief", st))
    if stg.get("design", {}).get("status") not in ("approved", "not_needed", "skipped"):
        out.append(t("block_design", st))
    return out


def cmd_phase(a):
    root = find_root()
    st = load(root)
    if a.phase in ("planning", "awaiting_plan_approval", "building"):
        blocking = stages_blocking_plan(st)
        if blocking:
            die(t("cannot_phase", phase=name_of(PHASE_NAMES, a.phase)) + "; ".join(blocking))
    set_phase(st, a.phase)
    if a.phase == "awaiting_human_review":
        st.pop("_root", None)
    save(root, st)
    write_viewer(root, st)
    print(f"{t('phase_l', st)}: {name_of(PHASE_NAMES, st['phase'], st)}")
    print(next_action(st))


def cmd_approve(a):
    root = find_root()
    st = load(root)
    ph = st["phase"]
    if ph not in APPROVAL_NEXT:
        die(t("nothing_waiting", phase=name_of(PHASE_NAMES, ph)))
    stage, nxt = APPROVAL_NEXT[ph]
    if stage == "plan" and not st["checkpoints"]:
        die(t("approve_no_cps"))
    if stage == "plan" and stages_blocking_plan(st):
        die(t("cannot_approve_plan") + "; ".join(stages_blocking_plan(st)))
    t0 = now()
    st.setdefault("approvals", []).append({"stage": stage, "at": t0, "note": a.note or ""})
    if stage == "plan":
        st["approved_at"] = st.get("approved_at") or t0
        if static_cfg(st).get("checks") is not None:
            static_cfg(st)["approved_at"] = t0
    else:
        st["stages"][stage]["status"] = "approved"
        st["stages"][stage]["approved_at"] = t0
    set_phase(st, nxt)
    save(root, st)
    write_viewer(root, st)
    closed = inbox_close(root, st["slug"], "approve", stage, t("note_approved", st, stage=name_of(STAGE_NAMES, stage, st)))
    print(t("approved_line", st, stage=name_of(STAGE_NAMES, stage, st), nxt=name_of(PHASE_NAMES, nxt, st))
          + (t("approved_closed", st, ids=", ".join(closed)) if closed else ""))
    print(next_action(st, root))


def cmd_start(a):
    root = find_root()
    st = load(root)
    cp = get_cp(st, a.cp)
    if st["phase"] != "building":
        if not st.get("approved_at"):
            die(t("plan_not_approved", phase=name_of(PHASE_NAMES, st["phase"])))
        set_phase(st, "building")
    for dep in cp.get("depends_on", []):
        if get_cp(st, dep)["status"] != "passed":
            die(t("depends_on", cp=cp["id"], dep=dep))
    earlier = [c for c in st["checkpoints"] if c["n"] < cp["n"] and c["status"] != "passed"]
    if earlier and not a.force and not a.parallel:
        die(t("earlier_cp", cp=earlier[0]["id"]))
    if a.parallel:
        running = [c for c in st["checkpoints"] if c["status"] == "in_progress"]
        if len(running) >= 2:
            die(t("parallel_max", cp=running[-1]["id"]))
        overlap = {f for c in running for f in c.get("files_hint", [])} & set(cp.get("files_hint", []))
        if overlap:
            die(t("parallel_overlap", files=", ".join(sorted(overlap))))
    if static_checks(st) and not static_cfg(st).get("baseline") and cp["gates"]["static"]["status"] not in GATE_DONE:
        die(t("start_no_baseline"))
    cp["status"] = "in_progress"
    cp["started_at"] = cp.get("started_at") or now()
    cp["base_commit"] = cp.get("base_commit") or git(root, "rev-parse", "HEAD")
    save(root, st)
    print(t("cp_started", st, cp=cp["id"], title=cp["title"]))
    print(next_action(st))


def findings_refusal(extra, metrics, gate_label, blockers_key="gate_blockers"):
    """Why a gate may not pass on these findings, or None. Only blocker/high force another round. A medium that is
    not fixed needs one fix round behind it (metrics.fix_rounds) or its own reason; low and nit may stay open."""
    fs = [f for f in (extra.get("findings") or []) if isinstance(f, dict)]
    sev = lambda f: str(f.get("severity", "")).lower()
    blockers = [f for f in fs if f.get("status", "open") == "open" and sev(f) in BLOCKING_SEV]
    if blockers:
        return t(blockers_key, gate=gate_label, n=len(blockers))
    try:
        fix_rounds = int(metrics.get("fix_rounds") or 0)
    except (TypeError, ValueError):
        fix_rounds = 0
    medium = [f for f in fs if sev(f) == "medium" and f.get("status", "open") != "fixed" and not str(f.get("reason") or "").strip()]
    if medium and fix_rounds < 1:
        return t("gate_medium", gate=gate_label, n=len(medium))
    return None


def cmd_gate(a):
    root = find_root()
    st = load(root)
    cp = get_cp(st, a.cp)
    if a.gate not in CP_GATES:
        die(t("gate_one_of", gates=", ".join(CP_GATES)))
    gs = cp["gates"][a.gate]
    if a.status in ("running", "passed") and a.gate != "behavior":
        order = CP_GATES[:CP_GATES.index(a.gate)]
        # ui and review are independent of each other (both need only behavior+static): they may run at
        # the same time, and a fix from one does not have to wait for the other to finish first.
        if a.gate in ("ui", "review"):
            order = [g for g in order if g not in ("ui", "review")]
        blocking = [g for g in order if cp["gates"][g]["status"] not in GATE_DONE]
        if blocking:
            hint = ""
            if "static" in blocking:
                sg = cp["gates"]["static"]
                hint = (" " + t("static_explain") + " " + (t("static_added_mid") + " " if sg.get("added_mid_checkpoint") else "")
                        + t("next_l") + ": " + static_hint(st, cp) + ".")
            die(t("gate_order", gate=name_of(GATE_NAMES, a.gate), status=name_of(STATUS_NAMES, a.status),
                  gates=", ".join(name_of(GATE_NAMES, g) for g in blocking), cp=cp["id"]) + hint)
    reason = a.reason or a.summary
    if a.gate == "static" and a.status == "skipped":
        if not reason:
            die(t("static_skip_reason"))
        planned = gs.get("skip_reason") and not gs["attempts"]
        if static_checks(st) and not (gs.get("added_mid_checkpoint") or planned or a.force):
            die(t("static_skip_force", cp=cp["id"]))
    if a.gate == "static" and a.status == "passed":
        res = read_static_result(root, st, cp)
        if not res:
            die(t("static_pass_norun", cp=cp["id"], hint=static_hint(st, cp)))
        cur = worktree_state(root)
        if res.get("tree") and cur and cur != res["tree"]:
            die(t("static_pass_changed", cp=cp["id"]))
        blockers = [f for f in res.get("findings", []) if is_blocking(f)]
        if blockers:
            die(t("static_pass_blockers", n=len(blockers), tools=", ".join(sorted({f['tool'] for f in blockers})), cp=cp["id"]))
    if cp["status"] == "pending":
        cp["status"] = "in_progress"
        cp["started_at"] = now()
    if gs["status"] == "interrupted" and a.status in ("running", "passed", "failed"):
        continue_interrupted_attempt(gs)
    extra = read_json_arg(a.data, a.file)
    if a.gate == "static":
        extra.pop("findings", None)  # static findings come from `bf static run`, never from the orchestrator
    if a.status == "skipped":
        gs["status"] = "skipped"
        gs["skip_reason"] = reason or extra.get("reason") or name_of(STATUS_NAMES, "skipped", st)
    else:
        att = gs["attempts"][-1] if gs["attempts"] and not gs["attempts"][-1].get("result") else None
        if att is None:
            att = {"n": len(gs["attempts"]) + 1, "started_at": now(), "result": None}
            gs["attempts"].append(att)
        if a.status == "running":
            gs["status"] = "running"
        else:
            if a.status == "passed":
                refusal = findings_refusal(extra, {**att.get("metrics", {}), **(extra.get("metrics") or {})},
                                           name_of(GATE_NAMES, a.gate))
                if refusal:
                    die(refusal)
                if a.gate == "behavior":
                    m = extra.get("metrics", {})
                    if m and int(m.get("tests_failed", 0) or 0) > 0:
                        die(t("behavior_failed_tests"))
                    red = norm_red(extra["red"]) if extra.get("red") else next(
                        (x["red"] for x in reversed(gs["attempts"]) if x.get("red")), None)
                    if red and red.get("right_reason") is False:
                        die(t("behavior_wrong_red", cp=cp["id"]))
            att["result"] = a.status
            att["ended_at"] = now()
            gs["status"] = a.status
        if a.summary:
            att["summary"] = a.summary
        if extra.get("metrics"):
            att["metrics"] = {**att.get("metrics", {}), **extra["metrics"]}
        if extra.get("findings"):
            att["findings"] = extra["findings"]
        if extra.get("evidence"):
            att["evidence"] = extra["evidence"]
        if extra.get("files"):
            att["files"] = extra["files"]
        if a.gate == "behavior":
            if extra.get("red"):
                att["red"] = norm_red(extra["red"])
                # the latest red run decides, unless the metrics in this same call say otherwise
                mm = att.setdefault("metrics", {})
                given = extra.get("metrics") or {}
                if att["red"].get("right_reason") is not None and "red_confirmed" not in given:
                    mm["red_confirmed"] = att["red"]["right_reason"]
                if att["red"].get("tests") is not None and "tests_new" not in given:
                    mm["tests_new"] = att["red"]["tests"]
            if extra.get("green") or (a.status == "passed" and att.get("metrics")):
                att["green"] = norm_green(extra.get("green"), att.get("metrics"))
        elif extra.get("red") or extra.get("green"):
            print(t("red_only_behavior"), file=sys.stderr)
        if a.status == "failed":
            fails = sum(1 for x in gs["attempts"] if x.get("result") == "failed")
            if fails >= a.max_attempts:
                cp["status"] = "blocked"
                set_phase(st, "paused")
                st["pause_reason"] = t("pause_failed", st, cp=cp["id"], gate=name_of(GATE_NAMES, a.gate, st), n=fails)
    # a code change after review invalidates nothing automatically, but flag it
    save(root, st)
    print(f"{cp['id']} · {name_of(GATE_NAMES, a.gate, st)}: {name_of(STATUS_NAMES, gs['status'], st)}")
    if a.gate == "behavior" and gs["attempts"] and gs["attempts"][-1].get("red") and a.status == "running":
        r = gs["attempts"][-1]["red"]
        print(t("red_recorded", st, n=r.get("tests") if r.get("tests") is not None else "?",
                why=t("right_reason", st) if r.get("right_reason") else t("wrong_reason", st) if r.get("right_reason") is False else t("reason_unknown", st)))
    print(next_action(st))


def cmd_finish(a):
    root = find_root()
    st = load(root)
    cp = get_cp(st, a.cp)
    pend = [g for g in CP_GATES if cp["gates"][g]["status"] not in GATE_DONE]
    if pend:
        hint = f" ({static_hint(st, cp)})" if "static" in pend else ""
        die(t("finish_open", cp=cp["id"], gates=", ".join(name_of(GATE_NAMES, g) for g in pend)) + hint)
    if cp["gates"]["static"]["status"] == "passed":
        res = read_static_result(root, st, cp) or {}
        cur = worktree_state(root)
        if res.get("tree") and cur and cur != res["tree"]:
            die(t("finish_changed", cp=cp["id"]))
    cp["status"] = "passed"
    cp["ended_at"] = now()
    cp["commit"] = a.commit or git(root, "rev-parse", "HEAD")
    save(root, st)
    md, path = write_report(root, st, cp["id"])
    st = load(root)
    if all(c["status"] == "passed" for c in st["checkpoints"]):
        st["stages"]["docs"]["status"] = "pending"
        set_phase(st, "documenting")
        save(root, st)
        print(md)
        print("\n---\n" + t("all_passed", st))
        print(t("finish_compact_hint", st))
    else:
        print(md)
        print(f"\n{t('report_l', st)}: {path}")
        print(t("finish_compact_hint", st))


def cmd_feedback(a):
    root = find_root()
    st = load(root)
    raw = read_json_arg(a.data, a.file) if (a.data or a.file) else {}
    items = raw.get("checkpoints", [])
    base = len(st["checkpoints"])
    ids = []
    for i, it in enumerate(items, 1):
        cp = new_checkpoint(base + i, it, source="feedback", st=st)
        st["checkpoints"].append(cp)
        ids.append(cp["id"])
    st.setdefault("feedback", []).append({"at": now(), "text": a.text, "checkpoints": ids})
    if ids:
        st["stages"]["docs"]["status"] = "pending"
        set_phase(st, "building")
    save(root, st)
    write_viewer(root, st)
    print(t("feedback_recorded", st, n=len(ids), ids=", ".join(ids) or "-"))
    print(next_action(st))


def cmd_learn(a):
    root = find_root()
    st = load(root)
    line = f"- {dt.date.today().isoformat()} · {a.text.strip()}\n"
    for p in (os.path.join(run_dir(root, st["slug"]), "learnings.md"),) + ((os.path.join(bf_dir(root), "learnings.md"),) if a.project else ()):
        with open(p, "a") as f:
            f.write(line)
    save(root, st)
    print(t("learning_added", st))


def cmd_accept(a):
    root = find_root()
    st = load(root)
    open_cps = [c["id"] for c in st["checkpoints"] if c["status"] != "passed"]
    if open_cps:
        die(t("accept_open", cps=", ".join(open_cps)))
    set_phase(st, "done")
    st["finished_at"] = now()
    save(root, st)
    inbox_close(root, st["slug"], "accept", None, t("note_accepted", st))
    md, path = write_report(root, st, "final")
    print(md)
    print(f"\n{t('final_report_l', st)}: {path}")


def cmd_pause(a):
    root = find_root()
    st = load(root)
    st["pause_reason"] = a.reason
    if st["phase"] != "paused":
        st["paused_from"] = st["phase"]
    set_phase(st, "paused")
    save(root, st)
    print(f"{t('paused_l', st)}: {a.reason}")


def parse_gate_targets(values, gates):
    """--running/--redo values: 'all' or cpNN:gate. -> list of (cp, gate) among the interrupted gates."""
    out = []
    for v in values or []:
        if v == "all":
            out += [x for x in gates if x not in out]
            continue
        if ":" not in v:
            die(t("expected_cpgate", v=v))
        cid, g = v.split(":", 1)
        hit = [x for x in gates if x[0]["id"] == norm_cp(cid) and x[1] == g]
        if not hit:
            die(t("not_interrupted", cp=norm_cp(cid), gate=g, list=", ".join(c['id'] + ':' + gg for c, gg in gates) or "-"))
        out += [x for x in hit if x not in out]
    return out


def cmd_resume(a):
    root = find_root()
    st = load(root)
    msgs = []
    if st["phase"] == "paused":
        for c in st["checkpoints"]:
            if c["status"] == "blocked":
                c["status"] = "in_progress"
        st.pop("pause_reason", None)
        back = st.get("paused_from") or ("building" if st.get("approved_at") else "planning")
        set_phase(st, back)
        msgs.append(f"{t('resumed_l', st)}: {name_of(PHASE_NAMES, st['phase'], st)}")
    gates = interrupted_gates(st)
    run_t = parse_gate_targets(a.running, gates)
    redo_t = parse_gate_targets(a.redo, gates)
    both = [x for x in run_t if x in redo_t]
    if both:
        die(t("running_and_redo", x=f"{both[0][0]['id']}:{both[0][1]}"))
    for cp, g in run_t:
        continue_interrupted_attempt(cp["gates"][g])
        msgs.append(t("resume_running", st, cp=cp["id"], gate=g, gname=name_of(GATE_NAMES, g, st)))
    for cp, g in redo_t:
        gs = cp["gates"][g]
        gs["attempts"].append({"n": len(gs["attempts"]) + 1, "started_at": now(), "result": None,
                               "summary": t("redo_summary", st)})
        gs["status"] = "running"
        msgs.append(t("resume_redo", st, cp=cp["id"], gname=name_of(GATE_NAMES, g, st), n=len(gs["attempts"])))
    resumed = resume_interruptions(st, "manual", "bf resume")
    if resumed:
        msgs.append(t("n_resumed", st, n=len(resumed)))
    save(root, st)
    left = interrupted_gates(st)
    if left:
        msgs.append(t("still_interrupted", st, list=", ".join(f"{c['id']}:{g}" for c, g in left)))
    print("\n".join(msgs) or t("nothing_to_resume", st))
    print(next_action(st))


def context_status(root, st):
    """missing | stale: <why> | fresh"""
    c = st.get("stages", {}).get("context", {})
    pf = os.path.join(bf_dir(root), "context.md")
    meta_p = os.path.join(bf_dir(root), "context.json")
    if not os.path.isfile(pf) or not os.path.isfile(meta_p):
        return "missing", []
    meta = json.load(open(meta_p))
    age = (dt.datetime.now(dt.timezone.utc) - (parse_ts(meta.get("at")) or dt.datetime.now(dt.timezone.utc))).days
    changed = []
    if meta.get("head"):
        out = git(root, "diff", "--name-only", meta["head"], "HEAD")
        changed = [x for x in (out or "").splitlines() if x]
    key = [x for x in changed if CONTEXT_KEY_FILES.search(x)]
    reasons = []
    if age > 30:
        reasons.append(t("ctx_age", st, n=age))
    if len(changed) > 25:
        reasons.append(t("ctx_changed_n", st, n=len(changed), head=meta["head"][:8]))
    if key:
        reasons.append(t("ctx_changed", st) + ": " + ", ".join(key[:5]))
    return ("stale: " + "; ".join(reasons), changed) if reasons else ("fresh", changed)


def cmd_context(a):
    root = find_root()
    st = load(root)
    if a.check:
        status, changed = context_status(root, st)
        word, _, why = status.partition(": ")
        print(f"{t('ctx_project', st)}: {t('ctx_' + word, st)}" + (f": {why}" if why else ""))
        if changed and status == "fresh":
            print(t("ctx_fresh_changed", st, n=len(changed)))
        fc = st.get("stages", {}).get("context", {}).get("feature_file")
        print(f"{t('ctx_feature', st)}: " + (t("ctx_recorded", st) + ": " + fc if fc else t("ctx_missing", st)))
        return
    c = st["stages"].setdefault("context", {})
    if a.project:
        if not os.path.isfile(os.path.join(root, a.project)) and not os.path.isfile(a.project):
            die(t("not_found", p=a.project))
        with open(os.path.join(bf_dir(root), "context.json"), "w") as f:
            json.dump({"at": now(), "head": git(root, "rev-parse", "HEAD"), "file": ".buildflow/context.md"}, f)
        c["project_file"] = ".buildflow/context.md"
    if a.feature:
        c["feature_file"] = os.path.relpath(os.path.abspath(a.feature), root)
    if c.get("project_file") and c.get("feature_file"):
        c["status"] = "done"
        c["at"] = now()
    save(root, st)
    print(json.dumps(c, indent=2))
    print(next_action(st))


def cmd_brief(a):
    root = find_root()
    st = load(root)
    src = os.path.abspath(a.file)
    if not os.path.isfile(src):
        die(t("not_found", p=a.file))
    b = st["stages"]["brief"]
    b["file"] = os.path.relpath(src, root)
    b["source"] = "given" if a.given else "brainstorm"
    if a.given:
        # the user handed in a finished spec: that is their approval
        b["status"] = "approved"
        b["approved_at"] = now()
        st.setdefault("approvals", []).append({"stage": "brief", "at": b["approved_at"], "note": t("spec_given", st)})
        set_phase(st, "design")
    else:
        b["status"] = "awaiting"
        set_phase(st, "awaiting_brief_approval")
    save(root, st)
    write_viewer(root, st)
    print(t("brief_recorded", st, src=name_of(STATUS_NAMES, b["source"], st), phase=name_of(PHASE_NAMES, st["phase"], st)))
    print(next_action(st))


def cmd_design(a):
    root = find_root()
    st = load(root)
    d = st["stages"]["design"]
    d.setdefault("review", {"status": "pending", "attempts": []})
    if a.action in ("needed", "not-needed"):
        if st["phase"] not in ("design", "brief", "intake"):
            die(t("design_before_plan", phase=name_of(PHASE_NAMES, st["phase"])))
        d["needed"] = a.action == "needed"
        d["reason"] = a.reason or ""
        d["status"] = "in_progress" if d["needed"] else "not_needed"
        set_phase(st, "design" if d["needed"] else "planning")
    elif a.action == "review":
        if not a.status:
            die(t("design_review_status"))
        extra = read_json_arg(a.data, a.file)
        rv = d["review"]
        att = rv["attempts"][-1] if rv["attempts"] and not rv["attempts"][-1].get("result") else None
        if att is None:
            att = {"n": len(rv["attempts"]) + 1, "started_at": now(), "result": None}
            rv["attempts"].append(att)
        if a.status == "passed":
            blockers = [f for f in extra.get("findings", []) if f.get("status", "open") == "open"
                        and f.get("severity", "").lower() in ("blocker", "critical", "high", "major")]
            if blockers:
                die(t("design_review_blockers", n=len(blockers)))
        if a.status != "running":
            att["result"] = a.status
            att["ended_at"] = now()
        rv["status"] = a.status
        for k in ("metrics", "findings", "evidence"):
            if extra.get(k):
                att[k] = extra[k]
        if a.summary:
            att["summary"] = a.summary
    elif a.action == "ready":
        if d.get("review", {}).get("status") != "passed":
            die(t("design_review_not_passed"))
        for k, v in (("design_md", a.design_md), ("prototype", a.prototype)):
            if v:
                d[k] = os.path.relpath(os.path.abspath(v), root)
        if a.states:
            d["states"] = [x.strip() for x in a.states.split(",") if x.strip()]
        if not d.get("prototype") and not d.get("design_md"):
            die(t("design_give_paths"))
        for k in ("prototype", "design_md"):
            if d.get(k) and (d[k] == SCRATCH_DIR or d[k].startswith(SCRATCH_DIR + "/")):
                die(t("design_in_scratch", k=k, d=SCRATCH_DIR))
            if d.get(k) and not os.path.exists(os.path.join(root, d[k])):
                die(t("not_found", p=f"{k} {d[k]}"))
        d["status"] = "awaiting"
        set_phase(st, "awaiting_design_approval")
        if d.get("prototype"):
            st["project"]["prototype"] = d["prototype"]
        if d.get("design_md"):
            st["project"]["design_ref"] = d["design_md"]
    save(root, st)
    write_viewer(root, st)
    print(t("design_line", st, status=name_of(STATUS_NAMES, d.get("status"), st), review=name_of(STATUS_NAMES, d["review"]["status"], st),
            phase=name_of(PHASE_NAMES, st["phase"], st)))
    print(next_action(st))


def cmd_docs(a):
    """Feature-level docs gate: the project documentation for the whole feature is complete and correct."""
    root = find_root()
    st = load(root)
    if st["phase"] != "documenting":
        die(t("docs_after_last", phase=name_of(PHASE_NAMES, st["phase"])))
    fd = st["stages"]["docs"]
    extra = read_json_arg(a.data, a.file)
    if fd.get("status") == "interrupted":
        continue_interrupted_attempt(fd)
    att = fd["attempts"][-1] if fd["attempts"] and not fd["attempts"][-1].get("result") else None
    if att is None:
        att = {"n": len(fd["attempts"]) + 1, "started_at": now(), "result": None}
        fd["attempts"].append(att)
    if a.status == "passed":
        refusal = findings_refusal(extra, {**att.get("metrics", {}), **(extra.get("metrics") or {})},
                                   t("feature_docs_l"), blockers_key="docs_blockers")
        if refusal:
            die(refusal)
    if a.status != "running":
        att["result"] = a.status
        att["ended_at"] = now()
    fd["status"] = a.status
    for k in ("metrics", "findings", "evidence", "files"):
        if extra.get(k):
            att[k] = extra[k]
    if a.summary:
        att["summary"] = a.summary
    if a.status == "passed":
        set_phase(st, "awaiting_human_review")
        save(root, st)
        fmd, fpath = write_report(root, st, "final")
        print(fmd)
        print("\n---\n" + t("docs_passed", st, path=fpath))
        return
    save(root, st)
    print(f"{t('feature_docs_l', st)}: {name_of(STATUS_NAMES, fd['status'], st)}")
    print(next_action(st))


def cmd_interrupted(a):
    root = find_root()
    st = load(root)
    if a.cp:
        cp = get_cp(st, a.cp)
        gs = cp["gates"][a.gate]
        att = gs["attempts"][-1] if gs["attempts"] else None
        if gs["status"] != "running" or not att or att.get("result"):
            die(t("no_running_attempt", cp=cp["id"], gate=name_of(GATE_NAMES, a.gate)))
        att.update(result="interrupted", ended_at=now(),
                   summary=(att.get("summary", "") + f" [interrupted: {a.reason}]").strip())
        gs["status"] = "interrupted"
        marked = [f"{cp['id']}:{a.gate}"]
        st.setdefault("interruptions", []).append({"at": now(), "error": a.reason, "details": "", "phase": st["phase"],
                                                   "attempts": marked, "source": "manual", "status": "open"})
    else:
        marked = record_interruption(st, a.reason, source="manual")
    save(root, st, resume=False)
    print(t("interruption_recorded", st, why=a.reason, marked=", ".join(marked) or t("no_running_attempts", st)))
    print(next_action(st))


# ---------------------------------------------------------------- bf prompt: compose a subagent's whole prompt
# so the orchestrator only has to say "read <path> and follow it", instead of re-typing the context
# block and the role prompt into the Agent call each time.

PROMPT_REF = {
    "project": "context-scout.md", "feature": "context-scout.md",
    "system": "design.md", "prototype": "design.md", "review": "design.md",
    "planner": "checkpoint-planner.md", "tests-plan": "test-planner.md",
    "tests": "gate-behavior.md", "implement": "gate-behavior.md", "verify": "gate-behavior.md",
    "static-fix": "gate-static.md",
    "ui-visual": "gate-ui.md", "ui-behavior": "gate-ui.md", "ui-review": "gate-ui.md", "ui-fix": "gate-ui.md",
    "adversary": "gate-review.md", "fixer": "gate-review.md",
    "docs": "gate-docs.md", "docs-review": "gate-docs.md",
    "runner": "checkpoint-runner.md",
}
UI_REVIEWER_ROLES = {"ui-visual", "ui-behavior", "ui-review"}


def extract_role_prompt(role):
    """The role's own prompt text from its reference file: the body of the `## `bf:<scope>:<role>`` section
    (heading, optional blurb, a lone '---' line, then the prompt), or, for a reference that is a single
    role end to end (checkpoint-planner.md, test-planner.md, checkpoint-runner.md), everything after the
    file's first '---' line."""
    fname = PROMPT_REF.get(role)
    if not fname:
        return None
    path = os.path.join(SKILL_DIR, "references", fname)
    if not os.path.isfile(path):
        return None
    lines = open(path, errors="replace").read().splitlines()
    heading_re = re.compile(r"^#{2,3}.*`bf:[^:`]+:%s`" % re.escape(role))
    start = next((i for i, ln in enumerate(lines) if heading_re.search(ln)), None)
    if start is None:
        return "\n".join(lines[lines.index("---") + 1:]).strip() if "---" in lines else None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("#")), len(lines))
    block = lines[start + 1:end]
    if "---" in block:
        block = block[block.index("---") + 1:]
    return "\n".join(block).strip()


def cmd_prompt(a):
    root = find_root()
    st = load(root)
    role = a.role.lower()
    scope = a.scope.lower()
    cp = None
    if re.match(r"^(?:cp)?\d+$", scope):
        cp = get_cp(st, scope)
        scope = cp["id"]
    role_txt = extract_role_prompt(role)
    if not role_txt and not a.extra_file:
        die(t("prompt_no_role", st, role=role))
    parts = []
    if role in UI_REVIEWER_ROLES:
        # isolation rule: a UI reviewer judges only what it sees, never the brief, the plan or the code
        parts.append(t("prompt_ui_isolation", st))
        ref = st.get("project", {}).get("design_ref") or st.get("project", {}).get("prototype") or ""
        if ref:
            parts.append(f"{t('prompt_ref_l', st)}: {ref}")
        url = st.get("project", {}).get("dev_url", "")
        if url:
            parts.append(f"{t('prompt_url_l', st)}: {url}")
        if cp and cp.get("ui_scope"):
            parts.append(f"{t('prompt_ui_scope_l', st)}: {cp['ui_scope']}")
    else:
        parts.append(f"Feature: {st.get('title', '')} — {st.get('goal', '')}")
        parts.append(f"Language: {lang_of(st)}. " + t("prompt_lang_note", st))
        slug = st["slug"]
        reads = []
        for rel in (f".buildflow/{slug}/learnings.md", f".buildflow/{slug}/brief.md",
                    f".buildflow/{slug}/context-feature.md", ".buildflow/context.md"):
            if os.path.isfile(os.path.join(root, rel)):
                reads.append(rel)
        design_ref = st.get("project", {}).get("design_ref")
        if design_ref and st.get("stages", {}).get("design", {}).get("status") in ("approved", "done"):
            reads.append(design_ref)
        if reads:
            parts.append(t("prompt_read_l", st))
            parts += [f"{i}. {r}" for i, r in enumerate(reads, 1)]
        facts = {k: v for k, v in (("test_command", st.get("project", {}).get("test_command")),
                                    ("dev_command", st.get("project", {}).get("dev_command")),
                                    ("dev_url", st.get("project", {}).get("dev_url")),
                                    ("design_ref", design_ref),
                                    ("review_standard", st.get("project", {}).get("review_standard"))) if v}
        if facts:
            parts.append(f"{t('prompt_facts_l', st)}: " + " ".join(f"{k}={v}" for k, v in facts.items()))
        if cp:
            parts.append(f"{t('prompt_cp_l', st)}: {cp['id']} — {cp['title']}")
            if cp.get("summary"):
                parts.append(cp["summary"])
            if cp.get("done_when"):
                parts.append(f"{t('prompt_done_l', st)}: " + "; ".join(cp["done_when"]))
            if cp.get("ui_scope"):
                parts.append(f"{t('prompt_ui_scope_l', st)}: {cp['ui_scope']}")
            if cp.get("docs_scope"):
                parts.append(f"{t('prompt_docs_scope_l', st)}: {cp['docs_scope']}")
            if cp.get("tests"):
                parts.append(f"{t('prompt_tests_l', st)}:")
                for x in cp["tests"]:
                    sc = x.get("scenario") or {}
                    gwt = " / ".join(f"{k}: {v}" for k, v in sc.items() if v)
                    parts.append(f"- {x.get('name')}" + (f" ({gwt})" if gwt else ""))
    if role_txt:
        parts.append("---")
        parts.append(role_txt)
    for f in (a.extra_file or []):
        if os.path.isfile(f):
            parts.append("---")
            parts.append(open(f, errors="replace").read().strip())
    d = os.path.join(run_dir(root, st["slug"]), "prompts")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{scope}-{role}.md")
    with open(path, "w") as fh:
        fh.write("\n\n".join(p for p in parts if p).strip() + "\n")
    cp_for_model = cp if a.cp is None else get_cp(st, a.cp)
    model, _ = model_for(st, role, cp_for_model) if role in MODEL_ROLES else (INHERIT, None)
    print(os.path.relpath(path, root))
    print(f"{t('prompt_tag_l', st)}: bf:{scope}:{role}")
    print(f"{t('prompt_model_l', st)}: {model}")


def cmd_brief_context(a):
    """~15 lines so a new session can pick up an existing run without reading the whole state: phase,
    checkpoint, open gates, the last decisions and the next step."""
    root = find_root()
    st = load(root, required=False)
    if not st:
        print(t("brief_context_no_run"))
        return
    lines = [t("brief_context_head", st, title=st.get("title", st["slug"]), slug=st["slug"])]
    lines.append(f"{t('phase_l', st)}: {name_of(PHASE_NAMES, st['phase'], st)}  ·  "
                 f"{t('status_profile', st, profile=name_of(PROFILE_NAMES, profile_of(st), st))}")
    act = active_cp(st)
    if act:
        cp = get_cp(st, act)
        open_gates = [g for g in CP_GATES if cp["gates"][g]["status"] not in GATE_DONE and cp["gates"][g]["status"] != "skipped"]
        lines.append(f"{t('prompt_cp_l', st)}: {cp['id']} {cp['title']} ({name_of(STATUS_NAMES, cp['status'], st)})")
        if open_gates:
            lines.append("open gates: " + ", ".join(name_of(GATE_NAMES, g, st) for g in open_gates))
    running = [(cp["id"], g) for cp in st["checkpoints"] for g in CP_GATES if cp["gates"][g]["status"] == "running"]
    if running:
        lines.append("running: " + ", ".join(f"{c}:{g}" for c, g in running))
    fb = st.get("feedback") or []
    if fb:
        lines.append("recent feedback: " + "; ".join(str(x.get("note", x) if isinstance(x, dict) else x) for x in fb[-3:]))
    learn_p = os.path.join(run_dir(root, st["slug"]), "learnings.md")
    if os.path.isfile(learn_p):
        tail = [ln for ln in open(learn_p, errors="replace").read().splitlines() if ln.strip().startswith("-")][-3:]
        if tail:
            lines.append("last learnings: " + " | ".join(tail))
    lines.append(f"{t('next_l', st)}: {next_action(st, root)}")
    print("\n".join(lines[:16]))


def cmd_status(a):
    root = find_root()
    st = load(root)
    if a.json:
        print(json.dumps(payload(root, st), indent=2, ensure_ascii=False))
        return
    cps = st["checkpoints"]
    hint = inbox_hint(root, st["slug"], st)
    if hint:
        print(hint)
    S = lambda k: name_of(STATUS_NAMES, k, st)
    print(t("status_head", st, title=st["title"], slug=st["slug"], phase=name_of(PHASE_NAMES, st["phase"], st),
            mode=t("mode_" + (st.get("mode") or "interactive"), st)))
    print("  " + t("status_profile", st, profile=name_of(PROFILE_NAMES, profile_of(st), st)) + " · " + models_line(st))
    if st["phase"] == "intake":
        print("  " + pricing_hint(st))
    act_id = active_cp(st)
    if act_id:
        _, why = model_for(st, "implement", get_cp(st, act_id))
        if why:
            print("  " + why)
    if cps:
        print("  " + t("status_legend", st, legend="  ".join(f"{name_of(GATE_NAMES, g, st)[0].upper()}={name_of(GATE_NAMES, g, st)}" for g in CP_GATES)))
    act = active_cp(st)
    for cp in cps:
        g = " ".join(f"{name_of(GATE_NAMES, x, st)[0].upper()}:{S(cp['gates'][x]['status'])[:4]}" for x in CP_GATES)
        print(f"  {cp['id']} {S(cp['status']):<12} {g}  {cp['title']}")
        if cp["id"] == act and cp["status"] != "pending":
            td = tdd_summary(cp)
            if td["planned"] or td["red"]:
                red = td["red"]
                r = (t("st_red", st, n=red.get("tests") if red.get("tests") is not None else "?",
                       why=t("right_reason", st) if red.get("right_reason") else t("wrong_reason", st) if red.get("right_reason") is False else t("reason_unknown", st))
                     if red else t("st_red_flag", st) if td["red_confirmed"] else t("st_red_none", st))
                gr = td["green"]
                print("      " + t("st_testfirst", st, planned=td["planned"], sc=td["with_scenario"], red=r,
                                   green=f"{gr.get('tests_passed', '?')}/{gr.get('tests_total', '?')}" if gr else "-"))
    ints = st.get("interruptions", [])
    if ints:
        last = ints[-1]
        state = S("open") if last.get("status", "open") == "open" else \
            f"{S('resumed')} {last.get('resumed_at') or ''} ({S(last.get('resumed_how', '-'))})"
        print(t("status_ints", st, n=len(ints), err=last["error"], at=last["at"], state=state,
                marked=", ".join(last.get("attempts", [])) or "-"))
    ig = interrupted_gates(st)
    if ig:
        print(t("status_int_gates", st, list=", ".join(f"{c['id']}:{g}" for c, g in ig)))
    running = [(cp["id"], g, cp["gates"][g]["attempts"][-1].get("started_at")) for cp in cps for g in CP_GATES
               if cp["gates"][g]["status"] == "running" and cp["gates"][g]["attempts"]]
    for cid, g, since in running:
        print(t("status_running", st, cp=cid, gate=g, gname=name_of(GATE_NAMES, g, st), since=since))
    print(f"{t('next_l', st)}:", next_action(st, root))


def cmd_model(a):
    """Which model a subagent role runs on in this run's profile: the value for the Agent call's `model` field."""
    root = find_root()
    st = load(root, required=False)
    if a.role:
        role = a.role.lower()
        if role not in MODEL_ROLES:
            die(t("model_unknown_role", st, role=a.role, roles=", ".join(MODEL_ROLES)))
        cp = get_cp(st, a.cp) if (a.cp and st) else None
        m, why = model_for(st, role, cp, a.gate)
        if a.json:
            print(json.dumps({"role": role, "model": m, "profile": profile_of(st), "escalated": bool(why)}))
            return
        print(m)
        if why:
            print(why)
        return
    table = {r: model_for(st, r)[0] for r in MODEL_ROLES}
    if a.json:
        print(json.dumps({"profile": profile_of(st), "models": table}, indent=2))
        return
    print(t("model_head", st, profile=name_of(PROFILE_NAMES, profile_of(st), st)))
    for r in MODEL_ROLES:
        print(f"  {r:<12} {table[r]:<8} {role_label(r, st)}")


def cmd_cost(a):
    root = find_root()
    st = load(root)
    cost = refresh_cost(root, st)
    st.pop("_root", None)
    save(root, st)
    if a.json:
        print(json.dumps(cost, indent=2))
        return
    tm = cost["time"]
    print(t("cost_line", st, tok=fmt_tok(cost['totals']['total_tokens']), usd=fmt_usd(cost['totals']['usd']),
            active=fmt_dur(tm['active_seconds']), wall=fmt_dur(tm['wall_seconds']), n=cost['transcript_files']))
    print(md_cost_table(cost["by_role"], t("role_l", st), st, ROLE_NAMES))
    print()
    print(md_cost_table(cost["by_checkpoint"], "checkpoint", st, BUCKET_NAMES))
    if not cost["transcript_files"]:
        print("\n" + t("no_transcripts", st))


def cmd_pricing(a):
    pricing = load_pricing()
    if a.verified:
        pricing["verified_at"] = dt.date.today().isoformat()
        save_pricing(pricing)
        print(t("pricing_verified_set", date=pricing["verified_at"]))
        return
    if a.set:
        if not a.model or not a.kv:
            die(t("pricing_set_usage"))
        m = dict(pricing["models"].get(a.model) or {})
        for kv in a.kv:
            if "=" not in kv:
                die(t("pricing_set_usage"))
            k, v = kv.split("=", 1)
            if k not in PRICING_FIELDS:
                die(t("pricing_set_field", k=k))
            try:
                m[k] = float(v)
            except ValueError:
                die(t("pricing_set_number", k=k, v=v))
        pricing["models"][a.model] = m
        save_pricing(pricing)
        print(t("pricing_set_done", model=a.model))
        return
    if a.check:
        root = find_root()
        st = load(root)
        cost = refresh_cost(root, st)
        st.pop("_root", None)
        save(root, st)
        unpriced = cost.get("unpriced_models") or []
        n = sum(b.get("unpriced_messages", 0) for b in (cost.get("by_model") or {}).values())
        if not unpriced:
            print(t("pricing_check_ok", st))
        else:
            print(t("pricing_check_found", st, n=n, models=", ".join(unpriced)))
        return
    for name, p in sorted(pricing["models"].items()):
        print(f"  {name:<20} input={p.get('input','-')}  output={p.get('output','-')}  cache_read={p.get('cache_read','-')}"
              + (f"  fast={p['fast_multiplier']}x" if p.get("fast_multiplier") else ""))
    print(t("pricing_verified_line", date=pricing.get("verified_at") or "-", source=pricing.get("source") or "-"))


def cmd_report(a):
    root = find_root()
    st = load(root)
    md, path = write_report(root, st, a.which)
    print(md)
    print(f"\n{t('report_l', st)}: {path}")
    if a.open:
        open_path(path)


def cmd_viewer(a):
    root = find_root()
    st = load(root)
    if a.cost:
        refresh_cost(root, st)
        st.pop("_root", None)
        save(root, st)
    p = write_viewer(root, st)
    print(p)
    if a.open:
        open_path(p)


# ---------------------------------------------------------------- live viewer: bf serve, inbox, wait

SERVE_HOSTS = ("127.0.0.1", "localhost")
SERVE_PRIVATE = {"serve.json", "serve.log", "wait.json", "inbox.jsonl", "inbox-status.jsonl"}
SERVE_MAX_BODY = 64 * 1024
SERVE_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def parse_allow_hosts(values):
    """Extra host names the server answers to (e.g. a Tailscale name in front of `tailscale serve`).
    Exact names only: no wildcards, no bare single-label names, no IP ranges. Accepts `name`, `name:port`
    or a URL; returns the lower-cased host names."""
    out = []
    for v in values:
        for raw in (v or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            host = urllib.parse.urlsplit(raw if "//" in raw else "//" + raw).hostname or ""
            if "*" in raw or not SERVE_HOST_RE.match(host):
                die(t("bad_host", raw=raw))
            if host not in SERVE_HOSTS and host not in out:
                out.append(host)
    return out


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def serve_info(root, slug):
    """serve.json of a server that is really running (pid alive and answering /api/ping), else None."""
    p = os.path.join(run_dir(root, slug), "serve.json")
    try:
        info = json.load(open(p))
    except (OSError, ValueError):
        return None
    if not pid_alive(info.get("pid")):
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/api/ping", timeout=2) as r:
            ping = json.load(r)
    except Exception:
        return None
    return info if ping.get("slug") == slug else None


def file_fp(*paths):
    out = []
    for p in paths:
        try:
            s = os.stat(p)
            out.append(f"{s.st_mtime_ns}-{s.st_size}")
        except OSError:
            out.append("0")
    return ".".join(out)


def make_handler(root, slug, token, lock, allow_hosts=()):
    d = run_dir(root, slug)
    hosts = set(SERVE_HOSTS) | set(allow_hosts)
    base = f"/{SCRATCH_DIR}/{slug}/"

    class H(http.server.SimpleHTTPRequestHandler):
        server_version = "buildflow"

        def __init__(self, *args, **kw):
            super().__init__(*args, directory=root, **kw)

        def log_message(self, *args):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            # a DNS-rebinding page arrives with its own host name; only answer to the loopback names
            # and the exact names given with --allow-host (a reverse proxy such as `tailscale serve`)
            try:
                host = urllib.parse.urlsplit("//" + (self.headers.get("Host") or "")).hostname
            except ValueError:
                return False
            return host in hosts

        def _origin_ok(self):
            o = self.headers.get("Origin")
            if not o:
                return True
            try:
                u = urllib.parse.urlsplit(o)
                h = u.hostname
            except ValueError:
                return False
            if h in SERVE_HOSTS:
                return u.scheme == "http"
            return u.scheme in ("http", "https") and h in hosts

        def _token_ok(self):
            got = (self.headers.get("X-BF-Token") or "").encode("utf-8", "replace")
            return hmac.compare_digest(got, token.encode())

        def _state(self):
            return load(root, slug, required=False)

        def _allowed(self, path):
            """Project files are served so the viewer's links to prototypes and docs work. From .buildflow/
            only the overview and the run folders (viewers, reports, evidence); no other dot folders
            (.git, .env) and none of the server's private files."""
            parts = [x for x in urllib.parse.unquote(path).split("/") if x]
            if parts and parts[-1] in SERVE_PRIVATE:
                return False
            if parts[:1] == [SCRATCH_DIR]:
                if len(parts) == 2:
                    return parts[1] in ("index.html", "overview.json")
                if len(parts) < 3 or not os.path.isfile(os.path.join(bf_dir(root), parts[1], "state.json")):
                    return False
                parts = parts[2:]
            return not any(x.startswith(".") for x in parts)

        def list_directory(self, path):
            self.send_error(404)
            return None

        def do_HEAD(self):
            if not self._host_ok():
                return self.send_error(403)
            path = urllib.parse.urlsplit(self.path).path
            if path.startswith("/api/") or not self._allowed(path):
                return self.send_error(404)
            return super().do_HEAD()

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"ok": False, "code": "forbidden", "error": "unknown host"})
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/ping":
                st = self._state()
                return self._json(200, {"ok": True, "slug": slug, "phase": st and st.get("phase")})
            if path == "/api/version":
                ip, sp = inbox_paths(root, slug)
                return self._json(200, {"state": file_fp(os.path.join(d, "data.json")), "inbox": file_fp(ip, sp),
                                        "overview": file_fp(os.path.join(bf_dir(root), "overview.json"))})
            if path == "/api/inbox":
                if not self._token_ok():
                    return self._json(403, {"ok": False, "code": "forbidden", "error": "missing or wrong token"})
                return self._json(200, {"ok": True, "items": inbox_items(root, slug)})
            if path.startswith("/api/"):
                return self._json(404, {"ok": False, "code": "not_found", "error": "unknown endpoint"})
            target = {"/": "/.buildflow/index.html", "/index.html": "/.buildflow/index.html",
                      "/.buildflow": "/.buildflow/index.html", "/.buildflow/": "/.buildflow/index.html",
                      "/viewer.html": base + "viewer.html", base[:-1]: base + "viewer.html",
                      base: base + "viewer.html"}.get(path)
            if target:
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == base + "viewer.html":
                # the token only ever lives in the served copy, never in viewer.html on disk
                try:
                    page = open(os.path.join(d, "viewer.html"), encoding="utf-8").read()
                except OSError:
                    return self.send_error(404)
                page = page.replace("<head>", f'<head>\n<meta name="bf-token" content="{token}">', 1).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if not self._allowed(path):
                return self.send_error(404)
            return super().do_GET()

        def do_POST(self):
            if not self._host_ok() or not self._origin_ok():
                return self._json(403, {"ok": False, "code": "forbidden", "error": "only the local viewer may post"})
            if urllib.parse.urlsplit(self.path).path != "/api/action":
                return self._json(404, {"ok": False, "code": "not_found", "error": "unknown endpoint"})
            if not self._token_ok():
                return self._json(403, {"ok": False, "code": "forbidden", "error": "missing or wrong token"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > SERVE_MAX_BODY:
                return self._json(413, {"ok": False, "code": "too_large", "error": "request too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"ok": False, "code": "bad_request", "error": "invalid JSON"})
            with lock:
                st = self._state()
                if not st:
                    return self._json(500, {"ok": False, "code": "no_run", "error": "run state not found"})
                code, res = inbox_new_item(st, inbox_items(root, slug), body)
                if code != 200:
                    return self._json(code, res)
                append_jsonl(inbox_paths(root, slug)[0], res)
            return self._json(200, {"ok": True, "item": res})

    return H


def cmd_serve(a):
    root = find_root()
    st = load(root)
    slug = st["slug"]
    d = run_dir(root, slug)
    info = serve_info(root, slug)
    if a.status:
        extra = {"url": info["url"], "overview_url": f"http://127.0.0.1:{info['port']}/", "port": info["port"], "pid": info["pid"],
                 "started": info.get("started"), "allow_hosts": info.get("allow_hosts") or [],
                 "remote_urls": [f"http://{h}:{info['port']}/viewer.html" for h in info.get("allow_hosts") or []]} if info else {}
        print(json.dumps({"running": bool(info), **extra}))
        sys.exit(0 if info else 1)
    allow = parse_allow_hosts((a.allow_host or []) + [os.environ.get("BUILDFLOW_ALLOW_HOSTS", "")])
    if info:
        print(t("already_serving", st, url=info["url"], pid=info["pid"]))
        now_allowed = info.get("allow_hosts") or []
        if now_allowed:
            print(t("also_allowed", st, hosts=", ".join(now_allowed)))
        if set(allow) - set(now_allowed):
            print(t("host_not_allowed", st, hosts=", ".join(sorted(set(allow) - set(now_allowed))), pid=info["pid"]))
        if a.open:
            open_path(info["url"])
        return
    if a.detach:
        # the child reads the same BUILDFLOW_ALLOW_HOSTS; pass the parsed names explicitly as well
        env = dict(os.environ, BUILDFLOW_ROOT=root)
        log = open(os.path.join(d, "serve.log"), "a")
        cmd = [sys.executable, os.path.abspath(__file__), "serve", "--port", str(a.port)]
        for h in allow:
            cmd += ["--allow-host", h]
        subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, cwd=root, env=env,
                         start_new_session=True)
        for _ in range(50):
            time.sleep(0.1)
            info = serve_info(root, slug)
            if info:
                print(t("serving_detached", st, url=info["url"], pid=info["pid"], log=os.path.relpath(log.name, root), port=info["port"]))
                for h in info.get("allow_hosts") or []:
                    print(t("also_answers", st, url=f"http://{h}:{info['port']}/viewer.html", port=info["port"]))
                if a.open:
                    open_path(info["url"])
                return
        die(t("server_down", log=log.name))
    write_viewer(root, st)
    write_data_json(root, st)
    write_overview(root)
    token = secrets.token_urlsafe(24)
    handler = make_handler(root, slug, token, threading.Lock(), allow)
    srv = None
    for port in ([0] if a.port == 0 else range(a.port, a.port + 20)):
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    if srv is None:
        die(t("no_port", a=a.port, b=a.port + 19))
    srv.daemon_threads = True
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/viewer.html"
    sp = os.path.join(d, "serve.json")
    tmp = sp + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"port": port, "pid": os.getpid(), "token": token, "started": now(), "url": url, "slug": slug,
                   "allow_hosts": allow}, f)
    os.replace(tmp, sp)

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    print(t("serving", st, url=url, port=port, inbox=os.path.relpath(inbox_paths(root, slug)[0], root)), flush=True)
    for h in allow:
        print(t("also_answers", st, url=f"http://{h}:{port}/viewer.html", port=port), flush=True)
    if a.open:
        open_path(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        try:
            if json.load(open(sp)).get("pid") == os.getpid():
                os.remove(sp)
        except (OSError, ValueError):
            pass


def cmd_inbox(a):
    root = find_root()
    st = load(root)
    slug = st["slug"]
    if a.action == "handled":
        if not a.ids:
            die(t("inbox_give_ids"))
        known = {x["id"] for x in inbox_items(root, slug)}
        missing = [i for i in a.ids if i not in known]
        if missing:
            die(t("inbox_unknown", ids=", ".join(missing)))
        inbox_mark(root, slug, a.ids, "handled", a.note or "")
        print(f"{t('handled_l', st)}: {', '.join(a.ids)}")
        return
    items = inbox_items(root, slug)
    shown = items if a.all else [x for x in items if x["status"] != "handled"]
    new = [x["id"] for x in shown if x["status"] == "new"]
    if new:
        inbox_mark(root, slug, new, "read")
        for x in shown:
            if x["id"] in new:
                x["status"] = "read"
    print(json.dumps(shown, indent=2, ensure_ascii=False))


def cmd_wait(a):
    root = find_root()
    st = load(root)
    slug = st["slug"]
    wp = os.path.join(run_dir(root, slug), "wait.json")
    # one listener per run: a newer `bf wait` replaces an older one, so one click never wakes Claude twice
    try:
        old = json.load(open(wp)).get("pid")
    except (OSError, ValueError):
        old = None
    if old and old != os.getpid() and pid_alive(old):
        cmdline = subprocess.run(["ps", "-p", str(old), "-o", "command="], capture_output=True, text=True).stdout
        if "bf.py" in cmdline and " wait" in cmdline:
            try:
                os.kill(int(old), signal.SIGTERM)
            except OSError:
                pass
    with open(wp, "w") as f:
        json.dump({"pid": os.getpid(), "started": now()}, f)

    def cleanup():
        try:
            if json.load(open(wp)).get("pid") == os.getpid():
                os.remove(wp)
        except (OSError, ValueError):
            pass

    def superseded(*_):
        cleanup()
        print(t("wait_replaced", st), flush=True)
        os._exit(0)
    signal.signal(signal.SIGTERM, superseded)
    deadline = time.time() + a.timeout
    ip, sp = inbox_paths(root, slug)
    last = None
    try:
        while True:
            fp = file_fp(ip, sp)
            if fp != last:
                last = fp
                new = [x for x in inbox_items(root, slug) if x["status"] == "new"]
                if new:
                    inbox_mark(root, slug, [x["id"] for x in new], "read")
                    for x in new:
                        x["status"] = "read"
                    print(json.dumps(new, indent=2, ensure_ascii=False))
                    return
            if time.time() >= deadline:
                print(t("wait_timeout", st, s=a.timeout))
                sys.exit(3)
            time.sleep(a.interval)
    finally:
        cleanup()


def cmd_doctor(a):
    root = find_root()
    st = load(root, required=False)
    print(t("doc_skill_dir", st) + ":", SKILL_DIR)
    print(t("doc_root", st) + ":", root)
    print("python:", sys.version.split()[0])
    pricing = load_pricing()
    print(t("doc_models", st) + ":", ", ".join(pricing["models"]))
    print(t("doc_lang", st) + ":", lang_of(st))
    if not st:
        print(t("doc_no_run"))
        return
    print(t("doc_active", st, slug=st["slug"], phase=name_of(PHASE_NAMES, st["phase"], st)))
    for sid in st.get("sessions", []):
        m, s = transcript_files(sid)
        print(t("doc_session", st, sid=sid, m=len(m), s=len(s)))
    if not st.get("sessions"):
        print(t("doc_no_session", st))


def main():
    p = argparse.ArgumentParser(prog="bf.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="start a new run")
    s.add_argument("--title", required=True)
    s.add_argument("--goal", default="")
    s.add_argument("--slug")
    s.add_argument("--lang", choices=LANGS, help="language of everything shown to humans (nl, en); default BUILDFLOW_LANG, else en")
    s.add_argument("--mode", default="interactive", choices=["interactive", "auto"])
    s.add_argument("--profile", default="lean", type=str.lower, choices=list(PROFILE_ALIASES),
                   help="model profile: lean/zuinig (default: sonnet for most roles) or thorough/grondig (session model); "
                        "see `bf.py model`")
    s.add_argument("--session", help="Claude Code session id, for cost measurement")
    s.add_argument("--root")
    s.add_argument("--force", action="store_true", help="overwrite a run with the same slug")
    s.add_argument("--park", action="store_true", help="pause the active unfinished run and start this one")
    s.add_argument("--redirect-from", help="folder the Claude Code session runs in, when that is not the project root; "
                                           "writes <folder>/.buildflow/redirect so the Stop hook finds this run")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("runs", help="all runs (features) in this project; also rewrites .buildflow/index.html")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_runs)

    s = sub.add_parser("use", help="switch the active run")
    s.add_argument("slug")
    s.set_defaults(fn=cmd_use)

    s = sub.add_parser("session", help="register a session id for cost measurement")
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_session)

    s = sub.add_parser("context", help="record or check the project and feature context")
    s.add_argument("--check", action="store_true", help="is .buildflow/context.md missing, stale or fresh?")
    s.add_argument("--project", help="path of the project context file (normally .buildflow/context.md)")
    s.add_argument("--feature", help="path of this run's feature context file")
    s.set_defaults(fn=cmd_context)

    s = sub.add_parser("brief", help="record the brief; --given when the user supplied a finished spec")
    s.add_argument("--file", required=True)
    s.add_argument("--given", action="store_true")
    s.set_defaults(fn=cmd_brief)

    s = sub.add_parser("design", help="design stage: needed | not-needed | review | ready")
    s.add_argument("action", choices=["needed", "not-needed", "review", "ready"])
    s.add_argument("--reason")
    s.add_argument("--status", choices=["running", "passed", "failed"])
    s.add_argument("--summary")
    s.add_argument("--data")
    s.add_argument("--file")
    s.add_argument("--design-md")
    s.add_argument("--prototype")
    s.add_argument("--states", help="comma-separated screen states the prototype covers")
    s.set_defaults(fn=cmd_design)

    s = sub.add_parser("project", help="set project facts: key=value ...")
    s.add_argument("kv", nargs="+")
    s.set_defaults(fn=cmd_project)

    for name, fn, h in (("plan", cmd_plan, "load checkpoints from the planner's JSON"),
                        ("tests", cmd_tests, "attach the test plan {cpNN: [tests]}")):
        s = sub.add_parser(name, help=h)
        s.add_argument("--file")
        s.add_argument("--data")
        if name == "plan":
            s.add_argument("--append", action="store_true")
            s.add_argument("--source", default="plan")
        s.set_defaults(fn=fn)

    s = sub.add_parser("phase", help="set the phase")
    s.add_argument("phase", choices=PHASES)
    s.set_defaults(fn=cmd_phase)

    s = sub.add_parser("approve", help="human approved what is waiting: brief, design or plan")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("start", help="start a checkpoint")
    s.add_argument("cp")
    s.add_argument("--force", action="store_true")
    s.add_argument("--parallel", action="store_true",
                   help="start alongside another in_progress checkpoint, in a separate git worktree "
                        "(lean profile only; at most 2 checkpoints active this way, and only when their "
                        "files_hint do not overlap)")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("gate", help="record a gate result")
    s.add_argument("cp")
    s.add_argument("gate", choices=CP_GATES)
    s.add_argument("status", choices=["running", "passed", "failed", "skipped"])
    s.add_argument("--summary")
    s.add_argument("--reason", help="why a gate is skipped (required for static)")
    s.add_argument("--force", action="store_true", help="static: skip even though checks are configured (give --reason)")
    s.add_argument("--data", help='JSON: {"metrics":{...},"findings":[{"severity","title","location","status"}],"evidence":[paths]}')
    s.add_argument("--file")
    s.add_argument("--max-attempts", type=int, default=4)
    s.set_defaults(fn=cmd_gate)

    s = sub.add_parser("static", help="static gate: detect | config | baseline | run cpNN | mark cpNN <id> wontfix | show [cpNN]")
    s.add_argument("action", choices=["detect", "config", "baseline", "run", "mark", "show"])
    s.add_argument("cp", nargs="?")
    s.add_argument("ids", nargs="*", help="mark: finding ids, then the status (wontfix)")
    s.add_argument("--file", help="config: JSON with {checks:[{name, cmd, kind, scope, format, blocking, timeout, ext, ok_exit}], not_available:[...]}")
    s.add_argument("--data")
    s.add_argument("--none", action="store_true", help="config: no tools available (needs --reason)")
    s.add_argument("--reason")
    s.add_argument("--timeout", type=int, default=STATIC_DEFAULT_TIMEOUT, help="default seconds per check")
    s.add_argument("--allow-dirty", action="store_true", help="baseline: run on a tree with uncommitted changes")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_static)

    s = sub.add_parser("finish", help="close a checkpoint after all gates passed; writes its report")
    s.add_argument("cp")
    s.add_argument("--commit")
    s.set_defaults(fn=cmd_finish)

    s = sub.add_parser("feedback", help="record human feedback; --file adds checkpoints")
    s.add_argument("--text", required=True)
    s.add_argument("--file")
    s.add_argument("--data")
    s.set_defaults(fn=cmd_feedback)

    s = sub.add_parser("learn", help="append a learning every agent must read")
    s.add_argument("text")
    s.add_argument("--project", action="store_true", help="also keep it for future runs in this project")
    s.set_defaults(fn=cmd_learn)

    s = sub.add_parser("accept", help="human accepted the feature; closes the run")
    s.set_defaults(fn=cmd_accept)

    s = sub.add_parser("pause")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_pause)
    s = sub.add_parser("resume", help="end a pause, and settle interruptions: --running cpNN:gate continues the "
                                      "interrupted attempt, --redo cpNN:gate starts a fresh one ('all' for every interrupted gate)")
    s.add_argument("--running", action="append", nargs="?", const="all", metavar="CP:GATE",
                   help="the gate's subagent kept going or finished: continue the same attempt (repeatable)")
    s.add_argument("--redo", action="append", nargs="?", const="all", metavar="CP:GATE",
                   help="the gate's subagent is gone: open a fresh attempt and redo the step (repeatable)")
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("docs", help="feature docs gate, after the last checkpoint")
    s.add_argument("--status", required=True, choices=["running", "passed", "failed"])
    s.add_argument("--summary")
    s.add_argument("--data", help='JSON: {"files":[...],"findings":[...],"metrics":{...}}')
    s.add_argument("--file")
    s.set_defaults(fn=cmd_docs)

    s = sub.add_parser("interrupted", help="record an interruption the hook missed (crash, closed laptop); marks running attempts")
    s.add_argument("cp", nargs="?")
    s.add_argument("gate", nargs="?", choices=CP_GATES)
    s.add_argument("--reason", default="session interrupted")
    s.set_defaults(fn=cmd_interrupted)

    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("prompt", help="compose a subagent's whole prompt (context block + role prompt) and write it "
                                      "to .buildflow/<slug>/prompts/<scope>-<role>.md")
    s.add_argument("scope", help="context, brief, design, plan, cpNN or final")
    s.add_argument("role", help="e.g. implement, tests, adversary, ui-review, runner")
    s.add_argument("--cp", help="checkpoint to base the model escalation check on, when different from scope")
    s.add_argument("--extra-file", action="append", help="extra file(s) appended verbatim after the role prompt")
    s.set_defaults(fn=cmd_prompt)

    s = sub.add_parser("brief-context", help="~15 lines a new session can read instead of the whole state: "
                                             "phase, checkpoint, open gates, last decisions, next step")
    s.set_defaults(fn=cmd_brief_context)

    s = sub.add_parser("model", help="model per subagent role in this run's profile ('inherit' = leave the Agent call's "
                                     "model field out); with a role: just that model")
    s.add_argument("role", nargs="?")
    s.add_argument("--cp", help="checkpoint: the implementer escalates to the session model after 2 failed attempts on its gate")
    s.add_argument("--gate", choices=CP_GATES, help="the gate to count failures on (default: behavior for implement)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_model)

    s = sub.add_parser("cost", help="measure tokens, cost and time from Claude Code transcripts")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_cost)

    s = sub.add_parser("pricing", help="show pricing.json, or verify it: --check | --set <model> k=v ... | --verified")
    s.add_argument("model", nargs="?", help="with --set: the model id to add or update")
    s.add_argument("kv", nargs="*", help="with --set: key=value pairs (input, output, cache_read, cache_write_5m, cache_write_1h, fast_multiplier)")
    s.add_argument("--check", action="store_true", help="compare models in this run's transcripts against pricing.json")
    s.add_argument("--set", action="store_true", help="add or update a model's price")
    s.add_argument("--verified", action="store_true", help="record today as the verification date")
    s.set_defaults(fn=cmd_pricing)

    s = sub.add_parser("report", help="write a report: cpNN or final")
    s.add_argument("which")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("viewer", help="render the viewer html")
    s.add_argument("--open", action="store_true")
    s.add_argument("--cost", action="store_true", help="refresh cost numbers first")
    s.set_defaults(fn=cmd_viewer)

    s = sub.add_parser("serve", help="serve the live viewer: live refresh, approvals and feedback from the browser")
    s.add_argument("--port", type=int, default=8765, help="first port to try (the next 19 are tried too); 0 = any")
    s.add_argument("--open", action="store_true")
    s.add_argument("--detach", action="store_true", help="start in the background, print the URL once it answers")
    s.add_argument("--status", action="store_true", help="is it running? JSON with the URL; exit 1 when not")
    s.add_argument("--allow-host", action="append", metavar="HOST",
                   help="also accept requests for this exact host name, e.g. the Tailscale name when "
                        "`tailscale serve` proxies the port (repeatable; also BUILDFLOW_ALLOW_HOSTS, comma-separated). "
                        "The server still binds 127.0.0.1 only and every action still needs the token")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("inbox", help="actions sent from the live viewer: list unhandled (marks them read), or mark handled")
    s.add_argument("action", nargs="?", choices=["handled"])
    s.add_argument("ids", nargs="*")
    s.add_argument("--note", help="what you did with it; shown in the viewer")
    s.add_argument("--all", action="store_true", help="also show handled items")
    s.set_defaults(fn=cmd_inbox)

    s = sub.add_parser("wait", help="block until the viewer sends something; exit 3 on timeout (run in the background)")
    s.add_argument("--timeout", type=int, default=3600)
    s.add_argument("--interval", type=float, default=1.0)
    s.set_defaults(fn=cmd_wait)

    s = sub.add_parser("doctor")
    s.set_defaults(fn=cmd_doctor)

    a = p.parse_args()
    global CURRENT_CMD, LANG
    CURRENT_CMD = a.cmd
    LANG = getattr(a, "lang", None) if a.cmd == "init" else None
    if LANG is None:
        try:  # the active run decides; before a run exists BUILDFLOW_LANG does (see lang_of)
            r = find_root()
            LANG = json.load(open(os.path.join(run_dir(r, active_slug(r) or "-"), "state.json"))).get("lang")
        except (OSError, ValueError, TypeError):
            LANG = None
    a.fn(a)


if __name__ == "__main__":
    main()
