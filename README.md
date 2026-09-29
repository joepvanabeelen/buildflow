# buildflow website

Statische website voor de buildflow-skill (Claude Code): wat hij doet, hoe je hem gebruikt, installatie en download.

## Lokaal bekijken

Er is geen buildstap en er zijn geen dependencies. Start vanuit de root van de repo een simpele webserver en open daarna http://localhost:8765/ in je browser:

```
python3 -m http.server 8765
```

## Welke bestanden de site vormen

De pagina is `index.html` in de root, met alle opmaak in `assets/site.css`. De enige externe bron is Google Fonts. Het lege bestand `.nojekyll` staat er voor GitHub Pages.

## Tests

De tests in `tests/` controleren onder meer dat de HTML klopt, dat elke ankerlink naar een bestaand id wijst en dat de bestanden waar de pagina naar verwijst bestaan. Ze gebruiken alleen de standaardbibliotheek van Python:

```
python3 -m unittest discover -s tests -v
```

Naast die basiscontroles zijn er drie inhoudelijke controles. De logica staat in drie scripts in `tests/`, de bijbehorende tests heten `test_cp04_*.py`.

`check_copy.py` leest de tekst die een bezoeker te zien of te horen krijgt, inclusief `alt`, `title`, `aria-label`, de paginatitel en de beschrijvingen in `<meta>`, en zoekt naar woorden uit de vermijdlijsten `VERMIJD` (Nederlands) en `VERMIJD_EN` (Engels) in datzelfde script. Het telt ook de gedachtestreepjes; meer dan vijf op de hele pagina is een fout. Tekst binnen `<script>`, `<style>`, `<code>`, `<pre>`, `<template>` en `<noscript>` telt niet mee, HTML-commentaar ook niet.

`check_privacy.py` doorzoekt alles wat GitHub Pages zou publiceren op persoonlijke paden (homemappen op macOS en Linux en de tijdelijke map van macOS), e-mailadressen en sessie-id's. Gepubliceerd betekent hier: alles wat git bijhoudt plus nieuwe bestanden die `.gitignore` niet uitsluit, behalve `.buildflow/` en `tests/`. Het script roept `git ls-files` aan, dus het werkt alleen in een git-checkout.

`check_facts.py` leest de Stop-hook uit de frontmatter van `SKILL.md` en de minimale Python-versie uit de `README.md` van de skill. De tests in `test_cp04_feiten.py` vergelijken de pagina daarmee: de uitpak- en doctor-commando's bij Installeren, het blok voor installatie in één project, de FAQ over bijwerken, de volgorde waarin de pagina zegt dat de hook de twee installatieplekken probeert en de Python-versie die de pagina noemt.

De eerste twee scripts kun je los draaien; ze printen `ok` of hun meldingen en eindigen met exitcode 1 als er iets gevonden is. `check_facts.py` los draaien vergelijkt niets, het laat alleen zien wat het uit de skill leest.

```
python3 tests/check_copy.py
python3 tests/check_privacy.py
python3 tests/check_facts.py
```

### De skillbron

Voor de feitencontrole is een map nodig met de skill erin: `SKILL.md`, `README.md` en `scripts/`. Het pad naar die map komt uit de omgevingsvariabele `BUILDFLOW_SKILL_SRC`. Is die niet gezet, dan wordt `../skill-buildflow/skills/buildflow` gebruikt; dat is de afspraak voor wie de skill lokaal naast deze repo heeft staan. Een andere plek geef je zo op:

```
BUILDFLOW_SKILL_SRC=/pad/naar/buildflow python3 -m unittest discover -s tests -v
```

Zonder lokale kopie van de skill kun je, zodra er een release is, `buildflow.zip` van de Releases-pagina van deze repo downloaden, uitpakken en `BUILDFLOW_SKILL_SRC` op de uitgepakte map `buildflow` zetten.

Vindt de test geen skillmap, dan draaien alle andere tests gewoon, maar de feitentests in `test_cp04_feiten.py` worden niet overgeslagen: ze falen met één fout die zegt welk pad gezocht is en naar deze sectie verwijst. De hele run eindigt dan dus als mislukt. `python3 tests/check_facts.py` geeft in dat geval dezelfde melding en eindigt met exitcode 1.

## Een release maken

Een release is één bestand, `buildflow.zip`, met de skill erin, als asset van een GitHub Release. Alles loopt via `scripts/release.py`. Het script kent drie standen: alleen de zip bouwen, de zip bouwen en de releasegegevens op de pagina zetten, en het hele publiceren.

### Eenmalig, met de hand

Twee dingen doet het script niet, en die hoeven ook maar één keer. Maak de repo op GitHub openbaar. Op een gratis account werkt Pages niet vanuit een privérepo, en zolang de repo privé is kan niemand anders de zip uit de release downloaden. Zet daarna GitHub Pages aan onder Settings > Pages: bij Source kies je "Deploy from a branch", met branch `main` en map `/ (root)`. Het lege bestand `.nojekyll` in de root zorgt dat Pages de bestanden zonder Jekyll-bewerking serveert.

Voor het publiceren heb je verder `git` en de GitHub CLI `gh` nodig. `gh` moet ingelogd zijn met toegang tot de repo waar `origin` naar wijst.

### Alleen de zip bouwen

```
python3 scripts/release.py --dry-run
```

Dit bouwt `dist/buildflow.zip` en doet verder niets: geen wijziging aan de pagina, geen git, geen gh. Draai je het script zonder `--dry-run` en zonder `--version`, dan stopt het met een melding en exitcode 1.

Het script zoekt de skillmap zo: eerst `--src`, dan, net als bij de feitencontrole, `BUILDFLOW_SKILL_SRC`, en anders `../skill-buildflow/skills/buildflow` naast deze repo. De skillmap wordt alleen gelezen.

```
python3 scripts/release.py --dry-run --src /pad/naar/buildflow
```

Na afloop print het script het pad van de zip, de grootte, het aantal bestanden en de lijst met paden in de zip. `dist/` staat in `.gitignore`, dus de zip komt niet in git terecht.

### Versie en datum op de pagina zetten

```
python3 scripts/release.py --version v1.0.0 --date 2026-09-29
```

Met `--version` bouwt het script de zip en vult het daarna in `index.html` de releasegegevens in. De versie moet de vorm `vX.Y.Z` hebben. `--date` in de vorm `JJJJ-MM-DD` zet de releasedatum vast; zonder `--date` geldt vandaag. Hier maakt `--dry-run` niets uit, want deze stand publiceert sowieso niets.

Het script verandert alleen de tekst van elementen met een `data-release`-attribuut: `versie` (topbalk, downloadkaart en footer), `datum` en `grootte` (allebei in de downloadkaart). De datum komt er in het Nederlands te staan, zoals `29 sep. 2026`, de grootte in hele kB (1 kB is 1000 bytes). De rest van de pagina blijft byte voor byte gelijk, en een tweede keer draaien met dezelfde waarden verandert niets. De downloadknoppen wijzen naar `releases/latest/download/buildflow.zip` en hoeven dus nooit mee te veranderen. Heeft een `data-release`-element geneste elementen, een onbekende waarde of ontbreekt er een van de drie, dan stopt het script met een melding.

### Publiceren

```
python3 scripts/release.py --version v1.0.0 --publish
```

`--publish` gaat niet samen met `--dry-run` en heeft `--version` nodig. Voordat er iets gebouwd wordt, controleert het script een paar dingen en weigert het als een ervan niet klopt. Je moet op `main` staan, want dat is de branch waar Pages vanaf publiceert. De werkkopie moet schoon zijn, zodat er alleen de releasegegevens in `index.html` in de releasecommit komen. Na een `git fetch origin` moet `main` precies gelijk zijn aan `origin/main`, niet voor en niet achter. `origin` moet naar een GitHub-repo wijzen; `gh` krijgt die repo met `--repo` mee, zodat git en gh zeker dezelfde repo gebruiken. En de versie mag nog niet bestaan, niet als lokale tag, niet als tag op `origin` en niet als GitHub Release.

Daarna bouwt het de zip en laat het een plan zien: de waarden die op de pagina komen en de commando's die het gaat draaien. Het gaat alleen verder als je de versie letterlijk intypt, bijvoorbeeld `v1.0.0`. Elk ander antwoord, ook een lege regel, stopt het script met de melding `bevestiging klopt niet (verwacht v1.0.0); er is niets gepubliceerd en index.html is niet aangepast`. De zip in `dist/` is op dat moment wel opnieuw gebouwd, maar er is niets gepubliceerd en `index.html` is niet veranderd. Na de bevestiging kijkt het nog een keer of de werkkopie schoon is, en dan doet het dit, in deze volgorde:

1. `index.html` invullen zoals hierboven
2. `git add index.html` en `git commit` met de melding `Release v1.0.0`, alleen voor `index.html`
3. `git tag -a v1.0.0`
4. `git push origin main`
5. `git push origin v1.0.0`
6. `gh release create v1.0.0 dist/buildflow.zip --repo <eigenaar/naam> --verify-tag` met titel en release notes

Als alles lukt, eindigt het met `v1.0.0 is gepubliceerd`. Pages publiceert de bijgewerkte pagina vanzelf vanaf `main`.

### Als het misgaat

Mislukt een stap, dan stopt het script direct, laat het de foutmelding van git of gh zien en print het drie lijstjes: wat gelukt is, welke commando's nog moeten (volledig uitgeschreven, in de goede volgorde) en hoe je het terugdraait. Hervatten doe je door die resterende commando's zelf te draaien; het script opnieuw starten werkt niet, want dan is de werkkopie niet meer schoon, loopt `main` voor op `origin/main` of bestaat de tag al, en elk daarvan laat het script weigeren.

Het terugdraaiadvies hangt af van hoe ver het kwam. Is er nog niets gecommit, dan is het `git checkout HEAD -- index.html`. Staan de commit en eventueel de tag alleen lokaal, dan zijn het `git tag -d` en `git reset --hard HEAD~1`; dat is veilig omdat de werkkopie vooraf schoon moest zijn. Staat de releasecommit al op `origin/main`, dan raadt het script geen reset aan maar `git revert HEAD` met een nieuwe push, plus het verwijderen van de tag, op `origin` met `git push origin :refs/tags/v1.0.0` als die al gepusht was. Werd `gh release create` onderbroken, dan kan de GitHub Release al bestaan, ook al zegt het terugdraailijstje daar nu niets over. Kijk dat na met `gh release view v1.0.0 --repo <eigenaar/naam>` en verwijder hem zo nodig met `gh release delete v1.0.0 --repo <eigenaar/naam>`.

Breek je af met Ctrl-C, dan hangt de melding af van het moment. Tijdens de bevestigingsvraag print het `release.py: afgebroken; er is niets gepubliceerd`. Onderbreek je na de bevestiging maar voordat `index.html` is ingevuld, dan wordt dat `release.py: afgebroken voordat er iets veranderd is; er is niets gepubliceerd`. Zodra de stappen lopen, begint de melding met `afgebroken tijdens het publiceren`. Daarna volgen dezelfde drie lijstjes, met erbij welke stap onderbroken werd; of die nog gelukt is weet het script niet, dus het noemt de commando's waarmee je dat nakijkt (`git log -1 --oneline`, `git tag --list`, `git ls-remote` en `gh release view`).

### Wat er in de zip gaat

In de zip staat bovenaan één map, `buildflow/`. Daarin komt alleen wat op de allowlist in `scripts/release.py` staat: `SKILL.md`, `README.md` en `pricing.json` in de skillmap zelf, de `*.py`-bestanden uit `scripts/`, de `*.md`-bestanden uit `references/` en alles uit `assets/`. Submappen daarin mogen niet: een bestand in een submap laat de bouw stoppen. De `LICENSE` uit de root van deze repo gaat er als `buildflow/LICENSE` bij; een eventuele LICENSE in de skillmap wordt genegeerd. Verborgen bestanden (alles wat met een punt begint, zoals `.DS_Store`), `__pycache__` en `.pyc`-bestanden slaat het script stil over.

Voor de rest is het streng. Staat er in de skillmap een bestand dat niet op de allowlist staat, of ergens een symlink, dan stopt de bouw met een foutmelding die de paden noemt. Een symlink kan naar bestanden buiten de skill wijzen, en die horen niet in een publieke zip. Moet een nieuw bestand wel mee, pas dan de allowlist in het script aan. De bouw stopt ook als een bestand of map niet te lezen is, of als een van de verplichte onderdelen ontbreekt: `SKILL.md`, `README.md`, `pricing.json`, `scripts/bf.py`, `scripts/gate_hook.py`, `assets/viewer.html` en minstens één `*.md` in `references/`. Die controles gebeuren voordat er iets geschreven wordt, dus een eerder gebouwde zip blijft dan staan. De zip zelf schrijft het script eerst naar een tijdelijk bestand in `dist/` en zet dat pas op zijn plek als het klaar is.

Alle bestanden in de zip krijgen dezelfde vaste tijdstempel, dezelfde rechten (een gewoon bestand met modus 0644) en een vaste volgorde, dus twee builds van dezelfde skillmap leveren dezelfde zip op.

### Tests voor het script

De tests staan in `tests/test_cp05_release.py` (de zip) en `tests/test_cp06_release.py` (pagina invullen en publiceren). Ze kopiëren alleen `scripts/release.py`, `LICENSE` en `index.html` naar een tijdelijke map en bouwen daar tegen een nagemaakte skillmap, zodat de echte `index.html` en `dist/` niet veranderen. In al deze tests staan `git` en `gh` als nepprogramma's vooraan op het pad: ze loggen hun aanroepen, beantwoorden hooguit leesvragen en publiceren niets. Eén test haalt de echte skillmap naast deze repo door de allowlist en de controle op verplichte onderdelen; staat die skillmap er niet, dan wordt alleen die test overgeslagen.

### Licentie

In de root van deze repo staat `LICENSE` met de MIT-licentie. Dat is ook het bestand dat als `buildflow/LICENSE` in de zip terechtkomt, dus wie de zip downloadt krijgt de licentie erbij.

## Ontwerp

Het ontwerp staat in `docs/design/`. `design.md` beschrijft de huisstijl, die uit de viewer van de skill komt, en per sectie hoe de pagina is opgebouwd. `docs/design/prototype/index.html` is het klikbare prototype; met `?state=` in de URL zie je de verschillende standen, bijvoorbeeld `?state=zonder-js` of `?state=lang`. Wijkt de gebouwde pagina bewust af van het ontwerp, dan worden design.md en het prototype bijgewerkt, zodat ze blijven beschrijven wat er staat.
