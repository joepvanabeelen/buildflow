# buildflow website

Statische website voor de buildflow-skill (Claude Code): wat hij doet, hoe je hem gebruikt, installatie en download.

De skill zelf staat in een aparte, private repo onder `skills/buildflow`.

## Lokaal bekijken

Er is geen buildstap en er zijn geen dependencies. Start vanuit de root van de repo een simpele webserver en open daarna http://localhost:8765/ in je browser:

```
python3 -m http.server 8765
```

## Welke bestanden de site vormen

De pagina is `index.html` in de root, met alle opmaak in `assets/site.css`. De enige externe bron is Google Fonts. Het lege bestand `.nojekyll` staat er voor GitHub Pages.

De tests in `tests/` controleren onder meer dat de HTML klopt, dat elke ankerlink naar een bestaand id wijst en dat de bestanden waar de pagina naar verwijst bestaan. Ze gebruiken alleen de standaardbibliotheek van Python:

```
python3 -m unittest discover -s tests -v
```

## Ontwerp

Het ontwerp staat in `docs/design/`. `design.md` beschrijft de huisstijl, die uit de viewer van de skill komt, en per sectie hoe de pagina is opgebouwd. `docs/design/prototype/index.html` is het klikbare prototype; met `?state=` in de URL zie je de verschillende standen, bijvoorbeeld `?state=zonder-js` of `?state=lang`. Wijkt de gebouwde pagina bewust af van het ontwerp, dan worden design.md en het prototype bijgewerkt, zodat ze blijven beschrijven wat er staat.
