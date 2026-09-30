# buildflow

Een Claude Code-skill om grote features te bouwen in kleine, geordende checkpoints die elk
door vaste kwaliteitspoorten (gates) moeten. Gebaseerd op
[Shopify's Helix](https://shopify.engineering/helix) en de uitwerking daarvan door AI Labs
([video](https://youtu.be/bBMp5tLxShQ)), zelf opnieuw opgebouwd en aangevuld met
rapportage over kwaliteit, tokens, kosten en tijd.

## Hoe het werkt

Je start met `/buildflow <wat je wilt bouwen>` in de repo of projectmap waar het moet
komen. Eén orchestrator (de hoofdsessie) doet zelf geen bouwwerk, maar zet voor elke taak
een subagent in met een schone context. Dat houdt elke agent scherp, ook bij features die
uren duren.

0. **Project lezen.** Een verkenner schrijft een projectprofiel (`.buildflow/context.md`):
   stack, conventies uit CLAUDE.md/AGENTS.md en de code zelf, architectuur, tests, hoe je
   de app draait, het bestaande design. Dat profiel wordt hergebruikt door volgende
   features en alleen ververst als het verouderd is (ouder dan 30 dagen, veel gewijzigde
   bestanden, of een sleutelbestand als CLAUDE.md of package.json veranderd). Een tweede
   verkenner beschrijft per feature wat die in de code raakt: bestaand gedrag, raakvlakken,
   vergelijkbare features om na te volgen. Elke subagent leest beide bestanden eerst.
1. **Brief, stop 1.** De orchestrator brainstormt met jou: probleem, gebruikers, wanneer
   het geslaagd is, scope en wat er expliciet niet in zit, twee of drie aanpakken met een
   advies, risico's. Vragen die de code kan beantwoorden stelt hij niet. Het resultaat is
   `brief.md`, dat jij goedkeurt. Heb je al een spec, dan geef je die mee met
   `--brief spec.md` en vervalt het gesprek.
2. **Design, stop 2 (alleen als het relevant is).** Verandert de feature iets wat
   gebruikers zien en is er geen goedgekeurd ontwerp, dan volgt een designstap. Die levert
   projectdocumentatie op, geen wegwerpbestanden:
   - `design.md` wordt aangevuld waar hij al bestaat, en anders afgeleid uit de bestaande
     app, op de plek waar het project zijn docs heeft;
   - prototypepagina's komen in de docs van het project en worden gecommit met de feature;
   - alles sluit aan op de bestaande stack, vooral de front-end: tokens en componenten
     heten zoals in de code, het prototype gebruikt Storybook als het project dat heeft,
     en anders een statische pagina met de echte CSS van de app. Een componentkaart laat
     per element zien welk bestaand component het bouwt, of welk nieuw component nodig is;
   - de design-review controleert ook of het design met de stack te bouwen is.

   Jij keurt het goed in de viewer, waar het prototype ingebed staat. Voor backend-werk
   of features met een bestaand ontwerp wordt deze stap overgeslagen, met de reden erbij.
3. **Plan, stop 3.** Een checkpoint-planner knipt de feature op in checkpoints, van simpel
   naar complex. Het aantal volgt de omvang: een klein project (een statische site, één
   script, ruwweg minder dan 1500 gewijzigde regels) krijgt 3 tot 5 checkpoints, een groot
   project tot 12. `bf.py` waarschuwt als een klein project er meer krijgt. De planner
   knipt langs de schermen en states van het prototype, en elke uitkomst uit de brief moet
   in een checkpoint terugkomen. Een test-planner bepaalt per
   checkpoint welke tests "klaar" definiëren, elk als scenario in de taal van de run
   (Gegeven/Als/Dan), met het soort test en het klaar-wanneer-punt dat het bewijst. In de
   viewer lees je die scenario's per checkpoint voordat je het plan goedkeurt.
4. **Bouwen.** Per checkpoint, in volgorde:
   - *Gate 1, gedrag*: tests eerst, eerst rood, dan code tot alles groen is (ook de tests
     van eerdere checkpoints). De rode run wordt vastgelegd met de faalredenen, zodat je in
     de viewer per checkpoint ziet: rood (zoveel tests, om de goede reden) → groen (n/n), en
     per scenario of het gepland, rood bevestigd of groen is.
   - *Gate 1b, statisch*: de linters, typecheckers, SAST, secret-scanner en dependency-audit
     die het project zelf al gebruikt (bij voorkeur wat CI draait) lopen over de gewijzigde
     bestanden. Alleen nieuwe bevindingen tellen: wat er vóór de feature al stond, zit in een
     baseline. Een secret blokkeert altijd, een tool die crasht of vastloopt is zelf een
     bevinding. Er wordt niets in het project geïnstalleerd; semgrep en gitleaks mogen via
     `uvx`/`pipx run`/docker als je dat bij het plan goedkeurt. Is er geen enkele tool, dan
     staat dat gewoon zo in het rapport.
   - *Gate 2, UI* (alleen als de checkpoint iets zichtbaars verandert): de app wordt
     vergeleken met het goedgekeurde prototype, op uiterlijk en op gedrag. In het zuinige
     profiel doet één reviewer allebei, in het grondige profiel zijn het er twee parallel.
     Ze zien de projectinstructies niet, alleen de referentie. Elk verschil krijgt een ernst
     en een plek op het scherm.
   - *Gate 3, adversarial review*: een reviewer die aanneemt dat de code fout is en een fixer
     die oplost. De reviewer krijgt de uitkomst van gate 1b mee en besteedt zijn aandacht
     aan wat tools niet zien.
   - *Gate 4, docs* (alleen als de checkpoint een `docs_scope` heeft): de bestaande
     documentatie wordt bijgewerkt (API-docs, helppagina's, README, changelog) en een
     reviewer controleert elke bewering tegen de code. In het zuinige profiel mag een kleine
     update (één bestand, alleen feiten) met een zelfcontrole van de schrijver af.

   Voor alle reviewgates geldt dezelfde regel: alleen een blocker of high levert een nieuwe
   reviewronde op. Een medium krijgt één fixronde, daarna draaien de tests en is het klaar.
   Low en nit gaan alleen het rapport in, zonder fixer. De reviewers krijgen de opdracht de
   ernst streng te kiezen: high alleen voor iets waar een gebruiker tegenaan loopt, of een
   bug die ze kunnen aantonen.
   - Commit, checkpoint-rapport in de chat en als bestand, door naar de volgende.
4b. **Documentatie van de feature.** Na de laatste checkpoint volgt een verplichte
   docs-gate over de feature als geheel: overzicht, changelog, verwijzingen tussen
   pagina's, en design.md en het prototype in lijn met wat er uiteindelijk gebouwd is.
   Pas daarna gaat de feature naar jou.
5. **Review, stop 4.** Jij test de feature. Feedback wordt nieuwe checkpoints (door dezelfde
   gates) plus regels in `learnings.md`, die elke agent voortaan eerst leest. Verandert je
   feedback het probleem of de aanpak, dan wordt eerst de brief bijgewerkt.

In `--auto`-modus keurt de orchestrator brief, design en plan zelf goed (na ze te tonen);
de gates blijven even streng en de eindreview blijft bij jou.

Twee dingen maken het afdwingbaar in plaats van vrijblijvend:

- `bf.py` weigert illegale stappen: plannen of bouwen zonder goedgekeurde brief en
  afgerond design, een prototype in de niet-gecommitte `.buildflow`-map, een checkpoint
  afronden met een open docs-gate, de statische gate passeren met een nieuwe blokkerende
  bevinding of op code die na de laatste run nog veranderd is, de review starten voordat de feature-docs rond zijn,
  een gate passeren terwijl een eerdere open staat,
  gedrag goedkeuren met falende tests, UI, review of docs goedkeuren met open blocker/high
  bevindingen of met een medium die geen fixronde en geen reden heeft, of checkpoint 3
  starten voordat 2 klaar is.
- Een Stop-hook (het Ralph-loop-idee) laat de orchestrator zijn beurt niet beëindigen
  zolang er in de bouwfase gates open staan. Wachten op achtergrond-subagents mag wel, en
  na herhaald blokkeren zonder voortgang geeft de hook het op in plaats van eindeloos te
  lussen.

## Modelprofielen

Elke run heeft een modelprofiel, dat je kiest bij de start (`bf.py init --profile`) en
terugziet in `bf.py status`, de viewer en de rapporten.

- **zuinig** (`lean`, de standaard): de planner en de adversarial reviewer draaien op het
  model van je sessie, want daar zitten de beslissingen die het duurst zijn om fout te
  hebben. De andere rollen (tests schrijven, implementeren, UI-review, fixers, docs,
  verkenners) draaien op Sonnet, testruns en de gezondheidscheck op Haiku.
- **grondig** (`thorough`): alles op het sessiemodel, behalve testruns en de
  gezondheidscheck. Zo werkte buildflow voordat er profielen waren, en zo blijven oudere
  runs zonder profiel ook draaien.

De orchestrator vraagt per subagent aan `bf.py model <rol>` welk model hij moet gebruiken.
Faalt de implementer twee keer op dezelfde gate, dan krijgt de volgende poging het
sessiemodel. Hoeveel het zuinige profiel scheelt, hangt af van hoeveel werk er in de
Sonnet-rollen zit; het kostenrapport splitst per model en per rol, dus je ziet het per run.
Er is geen budgetplafond: het profiel en de regels voor reviewrondes bepalen de kosten,
niet een pauze op een bedrag.

## Taal

Alles wat je leest volgt de taal van de run, vanaf het eerste bericht: de chat, de vragen
bij de intake, brief.md (met Nederlandse kopjes), de rapporten, de meldingen van `bf` en
elke tekst in de viewer. Schrijf je in het Nederlands, dan start de run met `--lang nl`;
vóór er een run is, bepaalt `BUILDFLOW_LANG` de taal van `bf`. Commando's, bestandsnamen
en JSON blijven Engels. Oudere runs houden wat ze ooit in het Engels opsloegen, maar de
viewer toont de bekende standaardteksten (overgeslagen gates, samenvattingen van de
statische checks) gewoon in het Nederlands.

## Rapportage

Na elke checkpoint krijg je in de chat een rapport met per gate het resultaat, het aantal
pogingen, tests, bevindingen (gevonden, opgelost, bewust niet opgelost), duur en kosten.
Na de laatste checkpoint en na acceptatie volgt een eindrapport. Alles staat ook als
Markdown en HTML in `.buildflow/<feature>/reports/`.

Kosten en tijd komen uit de transcripts die Claude Code zelf bijhoudt
(`~/.claude/projects/...`), inclusief die van subagents. `bf.py` telt per API-call de
input-, cache- en output-tokens, rekent ze om met `pricing.json` en verdeelt ze per rol
(planner, implementer, adversary, ...), per checkpoint en per model. Tijd wordt gesplitst
in actieve bouwtijd, doorlooptijd en de tijd dat de run op jou wachtte.

De kosten gelden voor de hele feature: alle sessies die aan de run gekoppeld zijn, van
`init` tot `accept`, inclusief feedbackrondes. Alles wat je in die periode in dezelfde
sessie doet telt mee, dus stel losse vragen liever in een andere sessie.

Tijd wordt gemeten op activiteit in de transcripts. Een stilte van meer dan 10 minuten
(rate limit, crash, dichtgeklapte laptop) telt als stil/onderbroken, de wachtfases als
wachten op jou; de rest is actieve bouwtijd. Een rate limit wordt via een
`StopFailure`-hook vastgelegd en de gate-poging die op dat moment liep, wordt als
onderbroken gemarkeerd, zodat de agent die stap bij het hervatten opnieuw doet in plaats
van een resultaat te verzinnen. Een onderbreking is geen pauze: de viewer toont hem als
melding ("onderbroken om 14:32 (rate limit)"), en zodra de sessie weer iets doet staat er
"hervat om ...". Liep de subagent gewoon door, dan zet `bf.py resume --running cp08:behavior`
de gate terug op lopend binnen dezelfde poging; was hij weg, dan begint `--redo` een nieuwe.

Het dollarbedrag is een API-equivalent tegen lijstprijzen. Met een Claude-abonnement betaal
je niet per token, maar het is wel de eerlijkste maat om runs met elkaar te vergelijken.
Prijzen wijzigen: werk `pricing.json` bij als dat gebeurt.

## De viewer

`.buildflow/<feature>/viewer.html` is één zelfstandig HTML-bestand: plan, voortgang per
gate, kosten en learnings. Het werkt op telefoon, tablet en desktop, kan geprint worden
naar PDF, en je kunt het zonder verdere bestanden doorsturen.

Tijdens een run draait de viewer live op `http://127.0.0.1:<poort>/viewer.html`
(`bf.py serve`). Bij elke stop geeft Claude je die link. Daar kun je de brief, het design
of het plan direct goedkeuren, feedback sturen op de brief, het design, het hele plan of
per checkpoint, en aan het eind de feature accepteren. Claude wacht op de achtergrond
(`bf.py wait`) en pakt het op zodra je iets verstuurt; tijdens het bouwen kijkt hij na
elke checkpoint in de inbox. Een klein paneel "Naar Claude" laat zien wat je stuurde en
of Claude het gelezen en verwerkt heeft, met een korte notitie. Antwoorden in de chat
blijft gewoon werken.

De pagina ververst zichzelf binnen een paar seconden als er iets verandert (een gate die
start of slaagt, een nieuwe fase), zonder dat je half getypte tekst, scrollpositie of
opengeklapte onderdelen kwijtraakt.

De checkpoint waar de run mee bezig is (of de volgende die start) staat bij het openen
geselecteerd: de kaart is open en gemarkeerd, de pagina scrolt er één keer naartoe en de
stappenbalk noemt hem. Schuift de run door naar de volgende checkpoint, dan klapt die
open; kaarten die je zelf open- of dichtklapte blijven zoals je ze liet.

Een paar keuzes rond veiligheid en betrouwbaarheid:

- De server luistert alleen op 127.0.0.1 en accepteert acties alleen met een token dat
  bij het starten wordt aangemaakt en in de geserveerde pagina wordt gezet, nooit in
  `viewer.html` op schijf. Verzoeken van een andere host of origin worden geweigerd,
  tenzij je die naam zelf toestaat (zie hieronder).
- De browser verandert de run nooit zelf. Acties komen in `inbox.jsonl`; Claude voert ze
  uit met dezelfde commando's als bij een chatantwoord. Goedkeuren kan alleen in de
  bijbehorende wachtfase, anders krijg je een duidelijke melding.
- Open je `viewer.html` als los bestand, dan werkt het zoals voorheen: lezen, en feedback
  kopiëren om in de chat te plakken.

### De viewer op je telefoon (via Tailscale)

Wil je vanaf je telefoon goedkeuren of feedback geven, dan zet je zelf een proxy voor de
server; de server blijft op 127.0.0.1 luisteren. Met Tailscale gaat dat zo, met de poort
die `bf.py serve` noemt:

```bash
tailscale serve --bg --http=8765 http://127.0.0.1:8765
```

Standaard weigert de server verzoeken die via die naam binnenkomen, omdat de Host dan
niet 127.0.0.1 of localhost is. Start hem daarom opnieuw met de tailnet-naam erbij:

```bash
python3 ~/.claude/skills/buildflow/scripts/bf.py serve --detach --allow-host joeps-mac-mini.tailc23dd9.ts.net
```

`--allow-host` mag vaker, en `BUILDFLOW_ALLOW_HOSTS` (komma-gescheiden) werkt ook. Alleen
exacte namen, geen wildcards. Het token blijft voor elke actie nodig; dat staat in de
pagina die je via die naam opent. De toegestane namen staan in `serve.json` en in
`bf.py serve --status`. Draait er al een server, stop die dan eerst: een lopende server
neemt geen nieuwe namen over. Daarna open je
`http://joeps-mac-mini.tailc23dd9.ts.net:8765/viewer.html` op je telefoon. Iedereen in je
tailnet die die URL opent, kan de viewer bekijken en acties sturen, dus gebruik dit op een
tailnet dat van jou is. Met `tailscale serve --http=8765 off` haal je de proxy weer weg.

## Meerdere features in één project

Een project kan veel buildflow-runs hebben, één per feature. `bf.py runs` toont ze
allemaal met fase, voortgang, kosten, actieve tijd en datums. `.buildflow/index.html` is
het overzicht daarvan in dezelfde stijl als de viewer: een kaart per run met links naar
de viewer, het eindrapport en de checkpoint-rapporten, en daaronder de features die het
product al heeft (uit de sectie `## Features` die de projectverkenner in
`.buildflow/context.md` schrijft). Het werkt als los bestand en live via `bf.py serve`
(`http://127.0.0.1:<poort>/`), en elke viewer linkt terug naar het overzicht.

Bij de start vraagt Claude wat je wilt: een open run afmaken, een bestaande feature
uitbreiden of aanpassen (de nieuwe run begint dan vanuit de code, docs en eerdere run van
die feature), iets nieuws bouwen, of alleen de cijfers van een afgeronde run bekijken.
Is dat uit je opdracht al duidelijk, dan slaat hij de vraag over en zegt wat hij koos.
`bf.py init` start nooit stilletjes een nieuwe run over een onafgemaakte heen: je moet de
oude eerst afmaken of expliciet parkeren (`--park` pauzeert hem).

## Installeren

Download `buildflow.zip` van de site (https://joepvanabeelen.github.io/buildflow/)
en pak hem uit in je skills-map:

```bash
mkdir -p ~/.claude/skills
unzip -o buildflow.zip -d ~/.claude/skills
```

Werk je vanuit een git-checkout van de skill, dan kan de map ook een symlink zijn:
`ln -s <checkout>/skills/buildflow ~/.claude/skills/buildflow`.

Voor een team kan de map ook in een project onder `.claude/skills/buildflow/` staan; de
Stop-hook zoekt het script op beide plekken. Vereisten: Python 3.9+ (alleen de
standaardbibliotheek), git, en voor de UI-gate een browsertool in Claude Code (Playwright
MCP of Claude in Chrome).

`python3 ~/.claude/skills/buildflow/scripts/bf.py doctor` controleert de setup.

## Delen

- **De skill**: stuur iemand naar de site voor de zip, of kopieer de map `skills/buildflow`.
  Er zit niets persoonlijks in.
- **Een plan of rapport**: stuur `viewer.html` of `reports/final.html` door. Beide bevatten
  alle data zelf. Of vraag Claude na afloop het eindrapport als private Artifact te
  publiceren; dan krijg je een link die je zelf deelt wanneer je wilt.
- Run-data staat standaard buiten git (`.buildflow/.gitignore`). Wil je rapporten
  committen, verwijder dan dat bestand.

## Bestanden

```
SKILL.md                    instructies voor de orchestrator
references/                 rolprompts per fase en subagent (context, brief, design, planner,
                            gates, rapportage) en het bf.py-naslagwerk
scripts/bf.py               state, gates, kosten, rapporten, viewer, live server en inbox (stdlib)
scripts/gate_hook.py        Stop-hook
assets/viewer.html          template voor viewer en rapporten (geel/zwart)
pricing.json                prijzen per model voor de kostenberekening
```

## Verschillen met de video en met Helix

- Helix gebruikt Gemini voor de UI-review; hier doen Claude-subagents dat (één in het
  zuinige profiel, twee in het grondige), met een
  vast uitvoerformaat (ernst, locatie, INVALID bij ongelijke schermstatus) dat uit de
  Helix-blog komt.
- Helix laat twee reviewers onafhankelijk keuren; de video gebruikt reviewer plus fixer.
  buildflow doet het laatste, maar laat elke herbeoordeling door een nieuwe reviewer doen,
  met de vorige bevindingen erbij, zodat niemand zijn eigen werk goedkeurt. Die
  herbeoordeling komt er alleen voor blocker- en high-bevindingen.
- Na een fix draaien de tests opnieuw, en de UI-gate ook als er iets zichtbaars veranderde
  (uit de Helix-blog, niet in de video).
- Kosten- en tijdrapportage per checkpoint en per rol zit in geen van beide.
- Brainstorm (brief) en een design-fase met eigen review en akkoord zitten in geen van
  beide; Helix begint bij een bestaand scherm als referentie, de video bij een al bestaand
  prototype.
- Het projectprofiel wordt gedeeld tussen features en ververst als het verouderd is.
