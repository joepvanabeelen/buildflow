# buildflow

Een Claude Code-skill om grote features te bouwen in kleine, geordende checkpoints die elk
door vaste kwaliteitspoorten (gates) moeten. Gebaseerd op
[Shopify's Helix](https://shopify.engineering/helix) en de uitwerking daarvan door AI Labs
([video](https://youtu.be/bBMp5tLxShQ)), zelf opnieuw opgebouwd en aangevuld met
rapportage over kwaliteit, tokens, kosten en tijd.

## Hoe het werkt

Je start met `/buildflow <wat je wilt bouwen>` in de repo of projectmap waar het moet
komen. Eén orchestrator doet zelf geen bouwwerk, maar zet voor elke taak een subagent in
met een schone context — dat houdt elke agent scherp, ook bij features die uren duren.

Bij de intake schat Claude eerst de omvang. Onder ongeveer 300 gewijzigde regels zegt hij
eerlijk dat het zonder buildflow sneller gaat; kies je toch voor buildflow, dan draait de
run met `fast=1`: één checkpoint, gates aan het eind, één stop.

0. **Project lezen.** Een verkenner schrijft een projectprofiel (`.buildflow/context.md`,
   plafond ~600 woorden): stack, conventies, architectuur, tests, hoe je de app draait,
   het bestaande design — hergebruikt door volgende features, alleen ververst als
   verouderd. Een tweede verkenner beschrijft per feature, in korte secties per gebied,
   wat die in de code raakt; een subagent in een checkpoint krijgt alleen de secties die
   bij zijn bestanden horen.
1. **Brief en plan, stop 1.** De orchestrator brainstormt met jou (probleem, gebruikers,
   succes, scope, aanpakken met advies, risico's — vragen die de code kan beantwoorden
   stelt hij niet; een spec meegeven kan met `--brief spec.md`), en een planner knipt de
   feature meteen op in checkpoints. Brief en plan passen elk op één scherm en je keurt
   ze in één keer goed.
2. **Design, alleen als relevant.** Een zichtbare wijziging zonder goedgekeurd ontwerp
   krijgt een eigen designstap met eigen stop, vóór het bouwen: `design.md` aangevuld of
   afgeleid, prototypepagina's in de projectdocs op de bestaande stack (tokens,
   componenten, Storybook of een statische pagina met de echte CSS), een componentkaart,
   een design-review die ook de stackfit checkt. Backend-werk of een bestaand ontwerp
   slaat deze stap over.
3. **Plan.** Een planner knipt in checkpoints, simpel naar complex, en schat de omvang:
   klein (< ~1500 gewijzigde regels, 3-5 checkpoints), middel (4-8) of groot (6-12).
   Checkpoints zonder afhankelijkheid of overlappende bestanden delen een golf, voor
   parallel bouwen. Een test-planner bepaalt per checkpoint de tests als scenario in de
   taal van de run (Gegeven/Als/Dan) — die lees je in de viewer vóór goedkeuring.
4. **Bouwen**, standaard een hele golf tegelijk: elk checkpoint krijgt zijn eigen
   git-worktree, gemerget in planvolgorde zodra klaar (`max_parallel`, standaard 3).

   **Klein of middel**: één agent per checkpoint schrijft eerst de tests (rood om de
   goede reden), dan de code tot groen, dan de statische checks (linters, typecheckers,
   SAST, secret-scanner, dependency-audit). UI-review, adversarial review en docs draaien
   niet per checkpoint maar één keer aan het eind, over de hele feature — goedkoper, en
   pas dan is er een compleet beeld om tegen te reviewen.

   **Groot** (of zonder omvangsveld, het oude gedrag): elk checkpoint krijgt alle gates
   apart — gedrag, statisch, UI (alleen bij zichtbare wijziging), adversarial review
   (reviewer plus fixer), docs (alleen met `docs_scope`).

   Voor alle reviewgates: alleen blocker of high levert een nieuwe ronde op, een medium
   krijgt één fixronde, low/nit gaan alleen het rapport in. Na elk checkpoint: commit, en
   een rapport in de chat van hoogstens vijf regels — details uitklapbaar in de viewer.
4b. **Documentatie van de feature.** Na de laatste checkpoint altijd een docs-gate over de
   feature als geheel (bij klein/middel ook UI en review): overzicht, changelog,
   kruisverwijzingen, design.md en prototype in lijn met wat gebouwd is.
5. **Review, stop 2.** Jij test de feature. Feedback wordt nieuwe checkpoints plus regels
   in `learnings.md`; verandert de feedback het probleem of de aanpak, dan wordt eerst de
   brief bijgewerkt.

In `--auto`-modus keurt de orchestrator brief, design en plan zelf goed; gates blijven
even streng, de eindreview blijft bij jou. Afdwingbaar door twee dingen: `bf.py` weigert
illegale stappen (bouwen zonder goedgekeurd plan, een gate uit volgorde, falende tests of
open blocker/high, afronden met open gates), en een Stop-hook houdt de orchestrator vast
zolang er gates open staan tijdens het bouwen.

## Modelprofielen

Elke run heeft een modelprofiel (`bf.py init --profile`, zichtbaar in status, viewer en
rapporten): **zuinig** (`lean`, standaard) draait de planner en de adversarial reviewer op
het sessiemodel (daar zitten de duurste fouten), de rest op Sonnet, testruns en
gezondheidscheck op Haiku; **grondig** (`thorough`) draait alles op het sessiemodel
behalve testruns en gezondheidscheck — zo draaien ook oudere runs zonder profiel. Faalt de
implementer twee keer op dezelfde gate, dan krijgt de volgende poging het sessiemodel.
Geen budgetplafond: het profiel en de regels voor reviewrondes bepalen de kosten.

De checkpoint-runner draait in het zuinige profiel op Sonnet. Wil je per rol afwijken, bijvoorbeeld
de runner op Haiku proberen, zet dan een projectfeit: `bf.py project model_runner=haiku`
(toegestaan: `haiku`, `sonnet`, `opus`, `inherit`). Zo'n keuze gaat voor op het profiel en de
runnergrootte. Vergelijk daarna met `bf.py cost` het aantal gate-rondes en de kosten.

## Wachten op een subagent

Een runner die op een achtergrond-subagent wacht, beëindigt zijn beurt niet. Na 5 minuten
zonder aanroep verloopt de promptcache en schrijft de volgende beurt de hele context opnieuw
weg, en dat was in de gemeten runs het grootste deel van de runnerkosten. `bf.py wait-agent
[cpNN]` blokkeert daarom hooguit 4 minuten (nooit langer dan 270 seconden) en keert terug zodra
een subagent van de run klaar is of een gate verandert. Staat er geen subagent te draaien, dan
keert het meteen terug. Is er na de wachttijd nog steeds een subagent bezig, dan roept de runner
het commando opnieuw aan.

## Taal

Alles wat je leest volgt de taal van de run, vanaf het eerste bericht, inclusief brief.md,
de rapporten, de meldingen van `bf` en de viewer. Schrijf je Nederlands, dan start de run
met `--lang nl`; vóór er een run is bepaalt `BUILDFLOW_LANG` de taal van `bf`. Commando's,
bestandsnamen en JSON blijven Engels.

## Rapportage

Na elke checkpoint een rapport in de chat: resultaat per gate, pogingen, tests,
bevindingen, duur en kosten; na de laatste checkpoint en na acceptatie een eindrapport.
Alles staat ook als Markdown en HTML in `.buildflow/<feature>/reports/`.

Kosten en tijd komen uit de Claude Code-transcripts (inclusief subagents): `bf.py` telt de
tokens per API-call, rekent om met `pricing.json`, verdeelt per rol, checkpoint en model.
Tijd splitst in actieve bouwtijd, doorlooptijd en wachttijd op jou; een stilte boven de 10
minuten telt als onderbroken. Een rate limit wordt via een `StopFailure`-hook vastgelegd,
zodat de agent die stap opnieuw doet in plaats van een resultaat te verzinnen (`bf.py
resume --running` of `--redo`). De kosten gelden voor de hele feature, van `init` tot
`accept` — stel losse vragen liever in een andere sessie.

Het dollarbedrag is een API-equivalent tegen lijstprijzen — met een abonnement betaal je
niet per token, maar het is de eerlijkste maat om runs te vergelijken.

## De viewer

`.buildflow/<feature>/viewer.html` is één zelfstandig HTML-bestand: plan, voortgang per
gate, kosten en learnings. Werkt op telefoon, tablet en desktop, print naar PDF, en kun je
zonder verdere bestanden doorsturen.

Tijdens een run draait hij live op `http://127.0.0.1:<poort>/viewer.html` (`bf.py serve`).
Bij elke stop geeft Claude je die link; je keurt er direct goed of stuurt feedback, en
accepteert aan het eind de feature. Claude wacht op de achtergrond (`bf.py wait`) en pakt
het op zodra je iets verstuurt; antwoorden in de chat blijven gewoon werken. De pagina
ververst zichzelf bij elke wijziging zonder je scrollpositie kwijt te raken.

Veiligheid: de server luistert alleen op 127.0.0.1, met een sessietoken (nooit op schijf);
verzoeken van een andere host worden geweigerd tenzij je die naam toestaat. De browser
verandert de run nooit zelf — acties komen in een inbox en Claude voert ze uit met
dezelfde commando's als bij een chatantwoord. Als los bestand geopend werkt `viewer.html`
read-only, met een knop om feedback te kopiëren.

**Op je telefoon** (Tailscale): proxy voor de server
(`tailscale serve --bg --http=8765 http://127.0.0.1:8765`), server herstarten met de
tailnet-naam (`bf.py serve --detach --allow-host <naam>.ts.net`, alleen exacte namen).
Iedereen op je tailnet die de URL opent kan meekijken en sturen — alleen op je eigen
tailnet dus.

## Meerdere features in één project

`bf.py runs` toont elke run met fase, voortgang, kosten en datums. `.buildflow/index.html`
is het overzicht in dezelfde stijl, met links naar viewer en rapporten, en de features die
het product al heeft (`## Features` in `.buildflow/context.md`). Werkt als los bestand en
live via `bf.py serve`.

Bij de start vraagt Claude: een open run afmaken, een bestaande feature uitbreiden (vanuit
code, docs en eerdere run), iets nieuws bouwen, of de cijfers van een afgeronde run
bekijken — tenzij je opdracht het al duidelijk maakt. `bf.py init` start nooit stilletjes
een nieuwe run over een onafgemaakte heen: eerst afmaken, of parkeren (`--park`).

## Installeren

```bash
mkdir -p ~/.claude/skills
unzip -o buildflow.zip -d ~/.claude/skills
```

(zip van https://joepvanabeelen.github.io/buildflow/). Vanuit een git-checkout mag de map
ook een symlink zijn: `ln -s <checkout>/skills/buildflow ~/.claude/skills/buildflow`. Voor
een team ook onder `.claude/skills/buildflow/` in het project — de Stop-hook zoekt op
beide plekken. Vereisten: Python 3.9+ (stdlib), git, en voor de UI-gate een browsertool
(Playwright MCP of Claude in Chrome). `bf.py doctor` controleert de setup.

## Delen

- **De skill**: de zip, of kopieer `skills/buildflow` — niets persoonlijks erin.
- **Een plan of rapport**: stuur `viewer.html` of `reports/final.html` door (bevatten
  alle data zelf), of vraag Claude het eindrapport als private Artifact te publiceren.
- Run-data staat standaard buiten git (`.buildflow/.gitignore`); verwijder dat bestand om
  rapporten te committen.

## Bestanden

```
SKILL.md                    instructies voor de orchestrator
references/                 rolprompts per fase en subagent, en de gate-naslagwerken
scripts/bf.py                state, gates, kosten, rapporten, viewer, live server, inbox
scripts/gate_hook.py        Stop-hook
assets/viewer.html          template voor viewer en rapporten
pricing.json                prijzen per model voor de kostenberekening
```

## Verschillen met de video en met Helix

- Helix gebruikt Gemini voor UI-review; hier doen Claude-subagents dat, met een vast
  uitvoerformaat (ernst, locatie, INVALID bij ongelijke schermstatus) uit de Helix-blog.
- Helix laat twee reviewers onafhankelijk keuren, de video reviewer plus fixer; buildflow
  doet het laatste, maar met een nieuwe reviewer per herbeoordeling, en alleen voor
  blocker/high.
- Na een fix draaien de tests opnieuw, en de UI-gate ook bij zichtbare wijziging (uit de
  Helix-blog, niet de video).
- Kosten- en tijdrapportage per checkpoint zit in geen van beide, net als de brainstorm
  en een eigen designstap met review: Helix begint bij een bestaand scherm, de video bij
  een bestaand prototype.
- Het projectprofiel wordt gedeeld tussen features.
