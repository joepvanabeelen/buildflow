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

Een release is één bestand, `buildflow.zip`, met de skill erin. Die zip bouw je met `scripts/release.py`. Voorlopig kan het script alleen een proefdraai: het bouwt de zip in `dist/buildflow.zip` en publiceert niets. Het publiceren zelf (een GitHub Release aanmaken en de versie en datum op de pagina zetten) komt in een volgende stap. Draai je het script zonder `--dry-run`, dan stopt het met een melding en exitcode 1, en er komt geen zip.

```
python3 scripts/release.py --dry-run
```

Het script zoekt de skillmap zo: eerst `--src`, dan, net als bij de feitencontrole, `BUILDFLOW_SKILL_SRC`, en anders `../skill-buildflow/skills/buildflow` naast deze repo. De skillmap wordt alleen gelezen.

```
python3 scripts/release.py --dry-run --src /pad/naar/buildflow
```

Na afloop print het script het pad van de zip, de grootte, het aantal bestanden en de lijst met paden in de zip. `dist/` staat in `.gitignore`, dus de zip komt niet in git terecht.

In de zip staat bovenaan één map, `buildflow/`. Daarin komt alleen wat op de allowlist in `scripts/release.py` staat: `SKILL.md`, `README.md` en `pricing.json` in de skillmap zelf, de `*.py`-bestanden uit `scripts/`, de `*.md`-bestanden uit `references/` en alles uit `assets/`. Submappen daarin mogen niet: een bestand in een submap laat de bouw stoppen. De `LICENSE` uit de root van deze repo gaat er als `buildflow/LICENSE` bij; een eventuele LICENSE in de skillmap wordt genegeerd. Verborgen bestanden (alles wat met een punt begint, zoals `.DS_Store`), `__pycache__` en `.pyc`-bestanden slaat het script stil over.

Voor de rest is het streng. Staat er in de skillmap een bestand dat niet op de allowlist staat, of ergens een symlink, dan stopt de bouw met een foutmelding die de paden noemt. Een symlink kan naar bestanden buiten de skill wijzen, en die horen niet in een publieke zip. Moet een nieuw bestand wel mee, pas dan de allowlist in het script aan. De bouw stopt ook als een van de verplichte onderdelen ontbreekt: `SKILL.md`, `pricing.json`, `scripts/bf.py`, `scripts/gate_hook.py`, `assets/viewer.html` en minstens één `*.md` in `references/`. Die controles gebeuren voordat er iets geschreven wordt, dus een eerder gebouwde zip blijft dan staan. De zip zelf schrijft het script eerst naar een tijdelijk bestand in `dist/` en zet dat pas op zijn plek als het klaar is.

Alle bestanden in de zip krijgen dezelfde vaste tijdstempel en een vaste volgorde, dus twee builds van dezelfde skillmap leveren dezelfde zip op.

De tests voor het script staan in `tests/test_cp05_release.py`. Ze draaien het script tegen een nagemaakte skillmap in een tijdelijke map, en één test haalt de echte skillmap naast deze repo door de allowlist en de controle op verplichte onderdelen. Staat die skillmap er niet, dan wordt alleen die test overgeslagen.

### Licentie

In de root van deze repo staat `LICENSE` met de MIT-licentie. Dat is ook het bestand dat als `buildflow/LICENSE` in de zip terechtkomt, dus wie de zip downloadt krijgt de licentie erbij.

## Ontwerp

Het ontwerp staat in `docs/design/`. `design.md` beschrijft de huisstijl, die uit de viewer van de skill komt, en per sectie hoe de pagina is opgebouwd. `docs/design/prototype/index.html` is het klikbare prototype; met `?state=` in de URL zie je de verschillende standen, bijvoorbeeld `?state=zonder-js` of `?state=lang`. Wijkt de gebouwde pagina bewust af van het ontwerp, dan worden design.md en het prototype bijgewerkt, zodat ze blijven beschrijven wat er staat.
