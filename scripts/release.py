#!/usr/bin/env python3
"""Bouwt dist/buildflow.zip uit de skillmap van buildflow.

De zip heeft bovenaan één map, buildflow/, met de skillbestanden en de LICENSE uit de root
van deze repo. Alleen wat op de allowlist staat gaat mee: SKILL.md, README.md, pricing.json,
scripts/*.py, references/*.md en assets/*. Cachebestanden (__pycache__, *.pyc) en verborgen
bestanden (alles wat met een punt begint, zoals .DS_Store) worden stil overgeslagen. Elk
ander bestand, een symlink ergens in de skillmap of een ontbrekend verplicht onderdeel
(SKILL.md, pricing.json, scripts/bf.py, scripts/gate_hook.py, references/*.md,
assets/viewer.html) laat de bouw stoppen met een foutmelding die de paden noemt. De volgorde in de zip ligt vast en alle
bestanden krijgen dezelfde tijdstempel, zodat twee builds van dezelfde bron gelijk zijn.

Gebruik:
    python3 scripts/release.py --dry-run [--src <skillmap>]

Zonder --src komt de skillmap uit BUILDFLOW_SKILL_SRC, en anders uit
../skill-buildflow/skills/buildflow naast deze repo. De skillmap wordt alleen gelezen.

--dry-run bouwt alleen de zip. Publiceren (GitHub Release, versie en datum op de pagina)
komt in een volgende stap; zonder --dry-run stopt het script daarom met een melding.
"""
import argparse
import os
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
VERPLICHT = ["SKILL.md", "pricing.json", "scripts/bf.py", "scripts/gate_hook.py",
             "assets/viewer.html"]
VERPLICHTE_MAPPEN = {"references": ".md"}


class BronFout(Exception):
    """De skillmap is niet geschikt om te verpakken."""


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
    for wortel, mappen, namen in os.walk(src):
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
    for wortel, mappen, namen in os.walk(src):
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
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def bouw_zip(src: Path, license_pad: Path, doel: Path):
    """Schrijft de zip via een tijdelijk bestand en geeft de lijst met paden in de zip."""
    bestanden = skillbestanden(src)
    inhoud = [(naam, bron.read_bytes()) for naam, bron in bestanden]
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bouwt dist/buildflow.zip uit de skillmap.")
    parser.add_argument("--dry-run", action="store_true",
                        help="alleen de zip bouwen, niets publiceren")
    parser.add_argument("--src", help="skillmap (standaard BUILDFLOW_SKILL_SRC of "
                                      "../skill-buildflow/skills/buildflow)")
    args = parser.parse_args(argv)

    if not args.dry_run:
        return fout("publiceren zit nog niet in dit script; gebruik --dry-run om alleen "
                    "de zip te bouwen")

    src = kies_src(args.src)
    if not src.is_dir():
        return fout(f"skillmap bestaat niet: {src}")
    license_pad = REPO / "LICENSE"
    if not license_pad.is_file():
        return fout(f"LICENSE ontbreekt in de repo-root: {license_pad}")

    try:
        namen = bouw_zip(src, license_pad, REPO / ZIP_PAD)
    except BronFout as e:
        return fout(str(e))
    grootte = (REPO / ZIP_PAD).stat().st_size
    print(f"{ZIP_PAD} ({grootte} bytes, {len(namen)} bestanden) uit {src}")
    for naam in namen:
        print(f"  {ZIP_MAP}/{naam}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
