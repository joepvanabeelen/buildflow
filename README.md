# buildflow

Een Claude Code-skill om grote features te bouwen in kleine checkpoints die elk door vaste kwaliteitspoorten moeten: gedrag, statische controles, UI, een kritische review en docs. Wat de skill doet en hoe je hem gebruikt, staat op https://joepvanabeelen.github.io/buildflow/.

## Wat hier staat

Deze branch (`main`) bevat alleen de skill. De map `buildflow/` is precies wat er in `buildflow.zip` bij de [releases](https://github.com/joepvanabeelen/buildflow/releases) zit: `SKILL.md`, de scripts, de references, de viewer en de LICENSE. De uitleg over de werking zelf staat in `buildflow/README.md`.

De website, het releasescript en de tests staan op de branch [`site`](https://github.com/joepvanabeelen/buildflow/tree/site). GitHub Pages serveert de site vanaf die branch.

## Installeren

Download `buildflow.zip` van de laatste release en pak hem uit in je skills-map:

```
unzip -o buildflow.zip -d ~/.claude/skills
python3 ~/.claude/skills/buildflow/scripts/bf.py doctor
```

Een clone van deze branch werkt ook: kopieer dan de map `buildflow/` naar `~/.claude/skills/`.

## Releases

Commit hier niet met de hand. Elke release maakt `scripts/release.py --publish` op de branch `site`: dat zet een commit met de nieuwe versie van de skill bovenop `main`, tagt die commit en maakt de GitHub Release. Daardoor bevatten de source-archieven van een release ook alleen de skill.

## Licentie

MIT, zie `LICENSE`.
