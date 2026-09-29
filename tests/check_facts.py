"""Leest feiten uit de buildflow-skill zelf, zodat de pagina daarmee te vergelijken is.

De skillbron is de map met SKILL.md en README.md van de skill. Die staat in de
omgevingsvariabele BUILDFLOW_SKILL_SRC, of standaard in ../skill-buildflow/skills/buildflow
naast deze repo. Alleen de stdlib.

Los draaien: python3 tests/check_facts.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STANDAARD_BRON = os.path.join(os.path.dirname(ROOT), "skill-buildflow", "skills", "buildflow")


def skill_bron():
    """Het pad naar de skillbron. Controleert niet of de map bestaat; zie vereis_bron()."""
    return os.environ.get("BUILDFLOW_SKILL_SRC") or STANDAARD_BRON


def vereis_bron():
    bron = skill_bron()
    if not os.path.isdir(bron):
        raise FileNotFoundError(
            melding_ontbrekende_bron(bron))
    return bron


def melding_ontbrekende_bron(bron):
    return (f"skillbron niet gevonden: {bron}. Zet BUILDFLOW_SKILL_SRC op de map met "
            "SKILL.md en README.md van de buildflow-skill (standaard "
            "../skill-buildflow/skills/buildflow naast deze repo). Zie README.md, onder "
            "de tests.")


def frontmatter(skill_md):
    m = re.match(r"---\n(.*?)\n---\s*(?:\n|$)", skill_md, flags=re.S)
    return m.group(1) if m else ""


def hook_commandos(skill_md):
    """Alle 'command:'-waarden uit de frontmatter van SKILL.md, zonder quotes."""
    uit = []
    for m in re.finditer(r"^\s*command:\s*(.+?)\s*$", frontmatter(skill_md), flags=re.M):
        waarde = m.group(1)
        if len(waarde) >= 2 and waarde[0] == waarde[-1] and waarde[0] in "'\"":
            waarde = waarde[1:-1]
            if m.group(1)[0] == "'":
                waarde = waarde.replace("''", "'")
        uit.append(waarde)
    return uit


def hook_volgorde(cmd):
    """De skill-paden in de volgorde waarin de hookregel ze probeert.

    Geeft een lijst als ['home', 'project']. De regel moet de vorm hebben
    f="<pad1>"; [ -f "$f" ] || f="<pad2>"; ..., anders ValueError.
    """
    m = re.match(r'\s*f="([^"]+)";\s*\[ -f "\$f" \] \|\| f="([^"]+)";', cmd)
    if not m:
        raise ValueError(f"hookregel heeft niet de verwachte vorm: {cmd}")
    soorten = {"$HOME/.claude/skills/buildflow/": "home",
               "$CLAUDE_PROJECT_DIR/.claude/skills/buildflow/": "project"}
    uit = []
    for pad in m.groups():
        soort = next((v for k, v in soorten.items() if pad.startswith(k)), None)
        if soort is None:
            raise ValueError(f"onbekend pad in hookregel: {pad}")
        uit.append(soort)
    return uit


# De skill-map op de pagina: in de homemap of in het project.
HOME_SKILLS = "~/.claude/skills"
PROJECT_SKILLS = ".claude/skills"


def _regels(el):
    return [r.strip() for r in el.alle_tekst().splitlines() if r.strip()]


def _codeblokken(el):
    return [_regels(c) for c in el.iter() if c.tag == "code" and c.parent is not None
            and c.parent.tag == "pre"]


def _vind(pagina, pred):
    return next((el for el in pagina.elementen() if pred(el)), None)


def controleer_installatie(pagina):
    """Controleert elk installatiecommando op zijn eigen plek. Geeft meldingen; leeg is goed.

    Plekken: stap 2 en 3 van Installeren (homemap), het blok voor het team (project) en de
    twee blokken in de FAQ over bijwerken.
    """
    meldingen = []
    home_unzip = f"unzip -o buildflow.zip -d {HOME_SKILLS}"
    proj_unzip = f"unzip -o buildflow.zip -d {PROJECT_SKILLS}"

    stappen = _vind(pagina, lambda el: el.tag == "ol" and "stappen" in el.classes
                    and el.parent is not None)
    items = [c for c in stappen.children if c.tag == "li"] if stappen else []
    if len(items) < 3:
        meldingen.append("installatiestappen (ol.stappen met minstens 3 stappen) ontbreken")
    else:
        blokken = _codeblokken(items[1])
        if blokken != [[f"mkdir -p {HOME_SKILLS}", home_unzip]]:
            meldingen.append(f"stap 2 (uitpakken) klopt niet: {blokken}")
        blokken = _codeblokken(items[2])
        if blokken != [[f"python3 {HOME_SKILLS}/buildflow/scripts/bf.py doctor"]]:
            meldingen.append(f"stap 3 (doctor) klopt niet: {blokken}")

    team = _vind(pagina, lambda el: el.tag == "details" and "install-extra" in el.classes)
    if team is None:
        meldingen.append("blok 'In één project installeren' ontbreekt")
    else:
        blokken = _codeblokken(team)
        regels = blokken[0] if len(blokken) == 1 else []
        verwacht = [f"mkdir -p {PROJECT_SKILLS}", proj_unzip,
                    f"python3 {PROJECT_SKILLS}/buildflow/scripts/bf.py doctor"]
        if len(blokken) != 1:
            meldingen.append(f"teamblok moet één codeblok hebben, heeft er {len(blokken)}")
        for moet in verwacht:
            if moet not in regels:
                meldingen.append(f"teamblok mist de regel: {moet}")
        for r in regels:
            if r.startswith("unzip") and r != proj_unzip:
                meldingen.append(f"teamblok heeft een ander uitpakcommando: {r}")

    faq = _vind(pagina, lambda el: el.tag == "details"
                and "Hoe werk ik bij" in el.alle_tekst())
    if faq is None:
        meldingen.append("FAQ 'Hoe werk ik bij' ontbreekt")
    else:
        blokken = _codeblokken(faq)
        verwacht = [[f"rm -rf {HOME_SKILLS}/buildflow", home_unzip],
                    [f"rm -rf {PROJECT_SKILLS}/buildflow", proj_unzip]]
        if blokken != verwacht:
            meldingen.append(f"FAQ bijwerken klopt niet: {blokken}, verwacht {verwacht}")
    return meldingen


def pagina_volgorde(pagina):
    """De volgorde van de skill-paden in de zin over de Stop-hook in het teamblok.

    Geeft bijvoorbeeld ['home', 'project'], of ValueError als de zin niet te vinden is.
    """
    team = _vind(pagina, lambda el: el.tag == "details" and "install-extra" in el.classes)
    zin = team and _vind_in(team, lambda el: el.tag == "p" and "Stop-hook" in el.alle_tekst())
    if not zin:
        raise ValueError("zin over de Stop-hook in het teamblok ontbreekt")
    if not re.search(r"\beerst\b", zin.alle_tekst()) or "daarna" not in zin.alle_tekst():
        raise ValueError("zin over de Stop-hook noemt geen volgorde (eerst ... daarna)")
    uit = []
    for c in zin.children:
        if c.tag != "code":
            continue
        pad = c.alle_tekst().strip()
        if pad == f"{HOME_SKILLS}/buildflow":
            uit.append("home")
        elif pad == f"{PROJECT_SKILLS}/buildflow":
            uit.append("project")
    return uit


def _vind_in(el, pred):
    return next((c for c in el.iter() if pred(c)), None)


def python_eis(readme):
    """De minimale Python-versie uit de README, bijvoorbeeld '3.9' uit 'Python 3.9+'."""
    m = re.search(r"Python\s+(3\.\d+)\+", readme)
    if not m:
        raise ValueError("geen 'Python 3.x+' gevonden in de README van de skill")
    return m.group(1)


if __name__ == "__main__":
    try:
        bron = vereis_bron()
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    with open(os.path.join(bron, "SKILL.md"), encoding="utf-8") as f:
        print("\n".join(hook_commandos(f.read())))
    with open(os.path.join(bron, "README.md"), encoding="utf-8") as f:
        print("Python", python_eis(f.read()))
