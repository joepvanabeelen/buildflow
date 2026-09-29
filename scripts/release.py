#!/usr/bin/env python3
"""Bouwt dist/buildflow.zip uit de skillmap van buildflow, zet de release op de pagina en
publiceert hem na bevestiging.

De zip heeft bovenaan één map, buildflow/, met de skillbestanden en de LICENSE uit de root
van deze repo. Alleen wat op de allowlist staat gaat mee: SKILL.md, README.md, pricing.json,
scripts/*.py, references/*.md en assets/*. Cachebestanden (__pycache__, *.pyc) en verborgen
bestanden (alles wat met een punt begint, zoals .DS_Store) worden stil overgeslagen. Elk
ander bestand, een symlink ergens in de skillmap, een map of bestand dat niet te lezen is of
een ontbrekend verplicht onderdeel (SKILL.md, README.md, pricing.json, scripts/bf.py,
scripts/gate_hook.py, references/*.md, assets/viewer.html) laat de bouw stoppen met een
foutmelding die de paden noemt. De volgorde in de zip ligt vast en alle bestanden krijgen
dezelfde tijdstempel en modus (gewoon bestand, 0644), zodat twee builds van dezelfde bron
gelijk zijn.

Gebruik:
    python3 scripts/release.py --dry-run [--src <skillmap>]
    python3 scripts/release.py --version vX.Y.Z [--date JJJJ-MM-DD] [--dry-run] [--src <skillmap>]
    python3 scripts/release.py --version vX.Y.Z --publish [--src <skillmap>]

Zonder --src komt de skillmap uit BUILDFLOW_SKILL_SRC, en anders uit
../skill-buildflow/skills/buildflow naast deze repo. De skillmap wordt alleen gelezen.

--dry-run zonder --version bouwt alleen de zip. Met --version vult het script daarna in
index.html de tekst van elk element met data-release="versie|datum|grootte" in (de rest van
de pagina blijft byte voor byte gelijk; nog een keer draaien verandert niets). --date zet de
releasedatum vast, anders geldt vandaag. De downloadknoppen wijzen naar
releases/latest/download/buildflow.zip en veranderen dus niet.

--publish weigert tenzij je op main staat (de Pages-branch), de werkkopie schoon is en main
na git fetch origin gelijk is aan origin/main. Het weigert ook als de versie al als tag
(lokaal of op origin) of als GitHub Release bestaat. gh krijgt --repo mee met de repo waar
git naartoe pusht (git remote get-url --push origin). Daarna bouwt het de zip, toont het welke commando's het gaat draaien en
gaat het alleen door als je de versie letterlijk intypt. Dan vult het index.html in, commit
alleen die, maakt de tag, pusht beide en maakt de release met gh. Mislukt een stap of breek
je af met Ctrl-C, dan meldt het wat gelukt is, welke commando's nog moeten en hoe je het
terugdraait; hervatten doe je door die commando's met de hand te draaien.
"""
import argparse
import datetime
import html
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STANDAARD_SRC = REPO.parent / "skill-buildflow" / "skills" / "buildflow"
ZIP_MAP = "buildflow"
ZIP_PAD = Path("dist") / "buildflow.zip"
# Vaste tijdstempel (het vroegste wat zip toestaat), zodat de zip reproduceerbaar is.
VASTE_TIJD = (1980, 1, 1, 0, 0, 0)


# Alleen deze onderdelen van de skillmap gaan mee in de zip.
LOSSE_BESTANDEN = {"SKILL.md", "README.md", "pricing.json"}
MAPPEN = {"scripts": ".py", "references": ".md", "assets": None}  # None: elk bestand
# Deze moeten er zijn, anders is de skill niet bruikbaar.
VERPLICHT = ["SKILL.md", "README.md", "pricing.json", "scripts/bf.py", "scripts/gate_hook.py",
             "assets/viewer.html"]
VERPLICHTE_MAPPEN = {"references": ".md"}


INDEX = "index.html"
PAGES_TAK = "main"  # GitHub Pages publiceert vanaf deze branch
VERSIE_PATROON = re.compile(r"v\d+\.\d+\.\d+")
MAANDEN = ["jan.", "feb.", "mrt.", "apr.", "mei", "jun.", "jul.", "aug.", "sep.", "okt.",
           "nov.", "dec."]
# Een element met data-release en alleen tekst erin (geen geneste elementen).
RELEASE_VELD = re.compile(
    r'(<(?P<tag>[a-zA-Z][\w-]*)\b[^>]*?\sdata-release="(?P<soort>[^"]*)"[^>]*>)'
    r'(?P<tekst>[^<]*)(</(?P=tag)\s*>)')


class BronFout(Exception):
    """De skillmap is niet geschikt om te verpakken."""


class ReleaseFout(Exception):
    """Pagina invullen of publiceren kan niet doorgaan."""


def nl_datum(dag: datetime.date) -> str:
    """'29 sep. 2026', los van de systeemlocale."""
    return f"{dag.day} {MAANDEN[dag.month - 1]} {dag.year}"


def kb(n: int) -> str:
    """Grootte in hele kB (1000 bytes, afgerond), minimaal '1 kB' voor een niet-lege zip."""
    if n <= 0:
        return "0 kB"
    return f"{max(1, int(n / 1000 + 0.5))} kB"


def onleesbaar(e: OSError):
    pad = e.filename or "?"
    raise BronFout(f"kan {pad} niet lezen (geen toegang of leesfout: {e.strerror}); "
                   "maak het leesbaar of haal het uit de skillmap")


def ruis(rel: Path) -> bool:
    """True voor verborgen onderdelen, __pycache__ en .pyc-bestanden: stil overslaan."""
    if any(deel.startswith(".") or deel == "__pycache__" for deel in rel.parts):
        return True
    return rel.suffix == ".pyc"


def toegestaan(rel: Path) -> bool:
    """True als het bestand op de allowlist staat."""
    if len(rel.parts) == 1:
        return rel.name in LOSSE_BESTANDEN
    if len(rel.parts) == 2 and rel.parts[0] in MAPPEN:
        extensie = MAPPEN[rel.parts[0]]
        return extensie is None or rel.suffix == extensie
    return False


def controleer_symlinks(src: Path) -> None:
    """Weigert de bouw als er ergens in de skillmap een symlink staat (bestand of map).

    De skillmap zelf mag een link zijn; alleen de inhoud wordt gecontroleerd.
    """
    links = []
    for wortel, mappen, namen in os.walk(src, onerror=onleesbaar):
        for naam in mappen + namen:
            pad = Path(wortel) / naam
            if pad.is_symlink():
                links.append(pad)
    if links:
        raise BronFout("de skillmap bevat symlinks; die volg ik niet, want ze kunnen naar "
                       "bestanden buiten de skill wijzen: "
                       + ", ".join(str(p) for p in sorted(links)))


def controleer_verplicht(src: Path) -> None:
    ontbreekt = [rel for rel in VERPLICHT if not (src / rel).is_file()]
    for map_, extensie in VERPLICHTE_MAPPEN.items():
        pad = src / map_
        if not pad.is_dir() or not any(p.is_file() and p.suffix == extensie
                                       for p in pad.iterdir()):
            ontbreekt.append(f"{map_}/ (met minstens één *{extensie})")
    if ontbreekt:
        raise BronFout(f"verplichte onderdelen ontbreken in {src}: " + ", ".join(ontbreekt))


def skillbestanden(src: Path):
    """(pad in de zip, bron) voor elk bestand dat meegaat, gesorteerd op pad in de zip.

    Weigert (BronFout) bij symlinks, ontbrekende verplichte onderdelen en bestanden die
    niet op de allowlist staan. Verborgen bestanden en cache worden stil overgeslagen.
    """
    controleer_symlinks(src)
    controleer_verplicht(src)
    uit, onbekend = [], []
    for wortel, mappen, namen in os.walk(src, onerror=onleesbaar):
        mappen[:] = [m for m in mappen if not ruis(Path(m))]
        for naam in namen:
            bron = Path(wortel) / naam
            rel = bron.relative_to(src)
            # De LICENSE komt altijd uit de repo, niet uit de skillmap.
            if rel == Path("LICENSE") or ruis(rel):
                continue
            if not toegestaan(rel) or not bron.is_file():
                onbekend.append(rel.as_posix())
                continue
            uit.append((rel.as_posix(), bron))
    if onbekend:
        raise BronFout("bestanden buiten de allowlist in de skillmap (pas de allowlist in "
                       "scripts/release.py aan als ze mee moeten): " + ", ".join(sorted(onbekend)))
    return sorted(uit)


def schrijf_bestand(z: zipfile.ZipFile, naam: str, data: bytes) -> None:
    info = zipfile.ZipInfo(f"{ZIP_MAP}/{naam}", date_time=VASTE_TIJD)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # unix, zodat unzip de modus overneemt
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    z.writestr(info, data)


def bouw_zip(src: Path, license_pad: Path, doel: Path):
    """Schrijft de zip via een tijdelijk bestand en geeft de lijst met paden in de zip."""
    bestanden = skillbestanden(src)
    inhoud = []
    for naam, bron in bestanden:
        try:
            inhoud.append((naam, bron.read_bytes()))
        except OSError as e:
            onleesbaar(e)
    inhoud.append(("LICENSE", license_pad.read_bytes()))
    inhoud.sort()
    doel.parent.mkdir(parents=True, exist_ok=True)
    fd, tijdelijk = tempfile.mkstemp(prefix=".buildflow-", suffix=".zip", dir=doel.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tijdelijk, "w") as z:
            for naam, data in inhoud:
                schrijf_bestand(z, naam, data)
        os.chmod(tijdelijk, 0o644)  # mkstemp maakt 0600; de zip is voor iedereen leesbaar
        os.replace(tijdelijk, doel)
    except BaseException:
        if os.path.exists(tijdelijk):
            os.unlink(tijdelijk)
        raise
    return [naam for naam, _ in inhoud]


def kies_src(arg):
    if arg:
        return Path(arg)
    env = os.environ.get("BUILDFLOW_SKILL_SRC")
    return Path(env) if env else STANDAARD_SRC


def fout(tekst: str) -> int:
    print(f"release.py: {tekst}", file=sys.stderr)
    return 1


def vul_pagina_in(tekst: str, waarden: dict) -> str:
    """Vervangt alleen de tekst van elk data-release-element; de rest blijft gelijk."""
    gevonden, onbekend = set(), []

    def vervang(m):
        soort = m.group("soort")
        if soort not in waarden:
            onbekend.append(soort)
            return m.group(0)
        gevonden.add(soort)
        return m.group(1) + html.escape(waarden[soort], quote=False) + m.group(5)

    nieuw, aantal = RELEASE_VELD.subn(vervang, tekst)
    if onbekend:
        raise ReleaseFout(f"onbekende data-release-waarde in {INDEX}: "
                          + ", ".join(sorted(set(onbekend))))
    if aantal != tekst.count("data-release="):
        raise ReleaseFout(f"niet elk data-release-element in {INDEX} bevat alleen tekst; "
                          "zet de waarde in een eigen element zonder kinderen")
    ontbreekt = sorted(set(waarden) - gevonden)
    if ontbreekt:
        raise ReleaseFout(f"geen data-release-element voor {', '.join(ontbreekt)} in {INDEX}")
    return nieuw


def schrijf_pagina(pad: Path, tekst: str) -> bool:
    """Schrijft via een tijdelijk bestand; False als er niets te veranderen was."""
    data = tekst.encode("utf-8")
    if pad.read_bytes() == data:
        return False
    fd, tijdelijk = tempfile.mkstemp(prefix=".index-", suffix=".html", dir=pad.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tijdelijk, stat.S_IMODE(pad.stat().st_mode))
        os.replace(tijdelijk, pad)
    except BaseException:
        if os.path.exists(tijdelijk):
            os.unlink(tijdelijk)
        raise
    return True


def draai(args):
    try:
        return subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
    except OSError as e:
        raise ReleaseFout(f"kan {args[0]} niet starten ({e.strerror}); staat het op PATH?")


def github_repo(url: str) -> str:
    """'eigenaar/naam' uit een GitHub-remote-URL (ssh, scp-vorm of https)."""
    m = re.fullmatch(r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
                     r"([\w.-]+)/([\w.-]+?)(?:\.git)?/?", url.strip())
    if not m:
        raise ReleaseFout(f"origin wijst niet naar een GitHub-repo ({url.strip() or 'leeg'}); "
                          "gh moet dezelfde repo gebruiken als origin")
    return f"{m.group(1)}/{m.group(2)}"


def git_uitvoer(args, wat: str) -> str:
    uit = draai(args)
    if uit.returncode != 0:
        raise ReleaseFout(f"kan {wat} niet bepalen: "
                          f"{uit.stderr.strip() or ' '.join(args) + ' mislukte'}")
    return uit.stdout.strip()


def controleer_schoon() -> None:
    status = git_uitvoer(["git", "status", "--porcelain"], "de status van de werkkopie")
    if status:
        raise ReleaseFout("de werkkopie is niet schoon; commit of stash eerst deze "
                          "wijzigingen, zodat alleen de releasevelden in index.html in de "
                          "releasecommit komen:\n" + status)


def controleer_werkkopie() -> str:
    """Weigert tenzij we op main staan, schoon, en gelijk met origin/main.

    Geeft de GitHub-repo van origin terug ('eigenaar/naam'), die gh ook moet gebruiken.
    """
    tak = git_uitvoer(["git", "branch", "--show-current"], "de huidige branch")
    if tak != PAGES_TAK:
        raise ReleaseFout(f"publiceren kan alleen vanaf {PAGES_TAK} (de Pages-branch); je staat "
                          f"op {tak or 'een losse commit (detached HEAD)'}. "
                          f"Doe eerst git switch {PAGES_TAK}")
    controleer_schoon()
    # De push-URL, niet de fetch-URL: gh moet de repo gebruiken waar de tag heen gaat.
    repo = github_repo(git_uitvoer(["git", "remote", "get-url", "--push", "origin"],
                                   "de push-URL van origin"))
    git_uitvoer(["git", "fetch", "origin"], "de stand van origin (git fetch origin)")
    kop = git_uitvoer(["git", "rev-parse", "HEAD"], "HEAD")
    remote = git_uitvoer(["git", "rev-parse", f"refs/remotes/origin/{PAGES_TAK}"],
                         f"origin/{PAGES_TAK}")
    if kop != remote:
        raise ReleaseFout(f"{PAGES_TAK} is niet gelijk aan origin/{PAGES_TAK} (HEAD {kop[:12]}, "
                          f"origin/{PAGES_TAK} {remote[:12]}); push of pull eerst, zodat de "
                          "release precies bevat wat op GitHub staat")
    return repo


def controleer_nieuwe_versie(versie: str, repo: str) -> None:
    """Weigert als de versie al als tag (lokaal of op origin) of als GitHub Release bestaat."""
    bestaat = []
    uit = draai(["git", "tag", "--list", versie])
    if uit.returncode != 0:
        raise ReleaseFout(f"kan de lokale tags niet lezen: {uit.stderr.strip()}")
    if uit.stdout.strip():
        bestaat.append("als lokale tag")
    uit = draai(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{versie}"])
    if uit.returncode == 0:
        bestaat.append("als tag op origin")
    elif uit.returncode != 2:
        raise ReleaseFout(f"kan niet nagaan of {versie} al op origin staat: "
                          f"{uit.stderr.strip() or 'git ls-remote mislukte'}")
    uit = draai(["gh", "release", "view", versie, "--repo", repo])
    if uit.returncode == 0:
        bestaat.append("als GitHub Release")
    elif "not found" not in uit.stderr.lower():
        raise ReleaseFout(f"kan niet nagaan of release {versie} al bestaat: "
                          f"{uit.stderr.strip() or 'gh release view mislukte'}")
    if bestaat:
        raise ReleaseFout(f"{versie} bestaat al ({', '.join(bestaat)}); kies een nieuwe versie")


# Indexen in publicatiestappen(); herstelhulp() rekent ermee.
ADD, COMMIT, TAG, PUSH_TAK, PUSH_TAG, GH_RELEASE = range(6)


def publicatiestappen(versie: str, repo: str):
    return [
        ["git", "add", INDEX],
        ["git", "commit", "--allow-empty", "-m", f"Release {versie}", "--", INDEX],
        ["git", "tag", "-a", versie, "-m", f"buildflow {versie}"],
        ["git", "push", "origin", PAGES_TAK],
        ["git", "push", "origin", versie],
        ["gh", "release", "create", versie, ZIP_PAD.as_posix(), "--repo", repo, "--verify-tag",
         "--title", f"buildflow {versie}",
         "--notes", f"buildflow {versie}. Pak buildflow.zip uit in ~/.claude/skills."],
    ]


def als_commando(args) -> str:
    return " ".join(shlex.quote(a) for a in args)


def herstelhulp(versie, repo, stappen, klaar, onderbroken) -> str:
    """Tekst na een mislukte of onderbroken publicatie.

    klaar: aantal stappen dat zeker gelukt is. onderbroken: True als stap `klaar` midden in
    het draaien is afgebroken, zodat niet zeker is of die gelukt is.
    """
    regels = []
    if klaar:
        regels.append("Gelukt:")
        regels.append(f"  {INDEX} ingevuld")
        regels += ["  " + als_commando(s) for s in stappen[:klaar]]
    else:
        regels.append(f"Gelukt: alleen {INDEX} ingevuld (nog niets gecommit of gepusht)")
    if onderbroken:
        regels.append(f"Onderbroken tijdens: {als_commando(stappen[klaar])}. Of die stap nog "
                      "gelukt is weet ik niet; kijk dat na met git log -1 --oneline, "
                      f"git tag --list {versie}, git ls-remote origin {PAGES_TAK} {versie} en "
                      f"gh release view {versie} --repo {repo}.")
    regels.append("Nog te doen (in deze volgorde, sla over wat al gelukt blijkt):")
    regels += ["  " + als_commando(s) for s in stappen[klaar:]]

    # Wat mogelijk al gebeurd is: bij een onderbreking telt de lopende stap mee.
    mogelijk = klaar + 1 if onderbroken else klaar
    regels.append("Terugdraaien:")
    # Voor de push naar main is origin/main precies de stand van voor de release (dat is
    # vooraf gecontroleerd). Reset daarnaartoe klopt dus ook als onbekend is of de commit
    # gelukt is; HEAD~1 zou dan een commit weggooien die er al was.
    if mogelijk <= PUSH_TAK:
        if mogelijk > TAG:
            regels.append(f"  git tag -d {versie}")
        if mogelijk > COMMIT:
            regels.append(f"  git reset --hard origin/{PAGES_TAK}   (haalt de releasecommit "
                          "weg als die er is; de werkkopie was schoon, dus er gaat niets "
                          "anders verloren)")
        else:
            regels.append(f"  git checkout HEAD -- {INDEX}")
    else:
        if klaar >= GH_RELEASE:
            # Ook na een foutmelding kan gh de release al (half) gemaakt hebben.
            regels.append(f"  kijk met gh release view {versie} --repo {repo} of de release "
                          f"bestaat; zo ja: gh release delete {versie} --repo {repo} --yes")
        if onderbroken and klaar == PUSH_TAK:
            regels.append(f"  is de push naar origin/{PAGES_TAK} niet gelukt: git tag -d "
                          f"{versie} en git reset --hard origin/{PAGES_TAK}; anders:")
        regels.append(f"  de releasecommit staat al op origin/{PAGES_TAK}; terugdraaien kan "
                      f"alleen met een nieuwe commit: git revert HEAD en "
                      f"git push origin {PAGES_TAK}")
        if mogelijk > PUSH_TAG:
            regels.append(f"  git push origin :refs/tags/{versie}")
        regels.append(f"  git tag -d {versie}")
    return "\n".join(regels)


def publiceer(versie, repo, pagina_pad, nieuwe_pagina, waarden) -> int:
    stappen = publicatiestappen(versie, repo)
    print(f"\nPlan voor {versie} (GitHub-repo {repo}):")
    print(f"  {INDEX} invullen: versie {waarden['versie']}, datum {waarden['datum']}, "
          f"grootte {waarden['grootte']}")
    for args in stappen:
        print("  " + als_commando(args))
    print(f"\nTyp {versie} om te publiceren (iets anders stopt zonder iets te doen): ",
          end="", flush=True)
    antwoord = sys.stdin.readline().strip()
    print()
    if antwoord != versie:
        return fout(f"bevestiging klopt niet (verwacht {versie}); er is niets gepubliceerd "
                    f"en {INDEX} is niet aangepast")
    # Er kan iets veranderd zijn terwijl de vraag openstond.
    controleer_schoon()

    klaar = 0
    try:
        schrijf_pagina(pagina_pad, nieuwe_pagina)
        print(f"{INDEX} ingevuld")
        for args in stappen:
            print(f"$ {als_commando(args)}", flush=True)
            uit = draai(args)
            if uit.stdout.strip():
                print(uit.stdout.rstrip())
            if uit.returncode != 0:
                return fout(f"stap mislukt: {als_commando(args)}\n{uit.stderr.strip()}\n"
                            + herstelhulp(versie, repo, stappen, klaar, onderbroken=False))
            klaar += 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        if klaar == 0 and pagina_pad.read_bytes() != nieuwe_pagina.encode("utf-8"):
            return fout("afgebroken voordat er iets veranderd is; er is niets gepubliceerd")
        return fout("afgebroken tijdens het publiceren\n"
                    + herstelhulp(versie, repo, stappen, klaar, onderbroken=True))
    print(f"{versie} is gepubliceerd")
    return 0


def lees_datum(tekst):
    if tekst is None:
        return datetime.date.today()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", tekst):
        raise ReleaseFout(f"--date moet de vorm JJJJ-MM-DD hebben, niet {tekst!r}")
    try:
        return datetime.date.fromisoformat(tekst)
    except ValueError:
        raise ReleaseFout(f"--date is geen bestaande datum: {tekst}") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Bouwt dist/buildflow.zip, zet de release op de pagina en publiceert "
                    "na bevestiging.")
    parser.add_argument("--dry-run", action="store_true",
                        help="niets publiceren; zonder --version alleen de zip bouwen")
    parser.add_argument("--version", help="releaseversie, bijvoorbeeld v1.0.0; vult "
                                          "versie, datum en grootte in index.html in")
    parser.add_argument("--date", help="releasedatum JJJJ-MM-DD (standaard vandaag)")
    parser.add_argument("--publish", action="store_true",
                        help="na bevestiging committen, taggen, pushen en de GitHub "
                             "Release maken")
    parser.add_argument("--src", help="skillmap (standaard BUILDFLOW_SKILL_SRC of "
                                      "../skill-buildflow/skills/buildflow)")
    args = parser.parse_args(argv)

    if args.publish and args.dry_run:
        return fout("--publish en --dry-run gaan niet samen")
    if args.version is None:
        if args.publish:
            return fout("--publish heeft --version nodig, bijvoorbeeld --version v1.0.0")
        if not args.dry_run:
            return fout("geef --version om een release te maken, of --dry-run om alleen "
                        "de zip te bouwen")
    elif not VERSIE_PATROON.fullmatch(args.version):
        return fout(f"versie moet de vorm vX.Y.Z hebben (bijvoorbeeld v1.0.0), "
                    f"niet {args.version!r}")

    try:
        dag = lees_datum(args.date)
        src = kies_src(args.src)
        if not src.is_dir():
            return fout(f"skillmap bestaat niet: {src}")
        license_pad = REPO / "LICENSE"
        if not license_pad.is_file():
            return fout(f"LICENSE ontbreekt in de repo-root: {license_pad}")
        pagina_pad = REPO / INDEX
        if args.version and not pagina_pad.is_file():
            return fout(f"{INDEX} ontbreekt in de repo-root: {pagina_pad}")
        repo = None
        if args.publish:
            repo = controleer_werkkopie()
            controleer_nieuwe_versie(args.version, repo)

        namen = bouw_zip(src, license_pad, REPO / ZIP_PAD)
        grootte = (REPO / ZIP_PAD).stat().st_size
        print(f"{ZIP_PAD} ({grootte} bytes, {len(namen)} bestanden) uit {src}")
        for naam in namen:
            print(f"  {ZIP_MAP}/{naam}")
        if args.version is None:
            return 0

        waarden = {"versie": args.version, "datum": nl_datum(dag), "grootte": kb(grootte)}
        nieuwe_pagina = vul_pagina_in(pagina_pad.read_bytes().decode("utf-8"), waarden)
        if args.publish:
            return publiceer(args.version, repo, pagina_pad, nieuwe_pagina, waarden)
        veranderd = schrijf_pagina(pagina_pad, nieuwe_pagina)
        print(f"{INDEX}: versie {waarden['versie']}, datum {waarden['datum']}, "
              f"grootte {waarden['grootte']}"
              + ("" if veranderd else " (stond er al, niets veranderd)"))
        return 0
    except (BronFout, ReleaseFout) as e:
        return fout(str(e))
    except (OSError, UnicodeDecodeError) as e:
        return fout(f"onverwachte fout: {e}")
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return fout("afgebroken; er is niets gepubliceerd")


if __name__ == "__main__":
    sys.exit(main())
