"""Zoekt in alles wat GitHub Pages publiceert naar persoonlijke gegevens, alleen met de stdlib.

Gepubliceerd is alles wat git bijhoudt of straks bijhoudt (ook nieuwe bestanden die nog niet
zijn toegevoegd, maar niet wat .gitignore uitsluit), behalve .buildflow/ en tests/. Gezocht wordt naar
persoonlijke paden (/Users/, /private/tmp, /home/), e-mailadressen en sessie-id's in
UUID-vorm. Binaire bestanden worden als bytes gelezen, want ook een plaatje kan een pad
bevatten.

Los draaien: python3 tests/check_privacy.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NIET_GEPUBLICEERD = (".buildflow/", "tests/")

# Regels die bewust mogen blijven staan, als (pad relatief aan de repo met /, stuk tekst).
# Nu leeg.
TOEGESTAAN = ()

PATRONEN = [
    ("persoonlijk pad", re.compile(rb"/Users/[^\s\"'<>]*|/private/tmp\b[^\s\"'<>]*"
                                   rb"|/home/[^\s\"'<>]*")),
    # Het domein moet eindigen op een tld van letters, anders telt het niet. Zo matcht een
    # Google Fonts-url met 'wght@100..125' niet: na de @ komt een cijfer.
    ("e-mailadres", re.compile(rb"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+"
                               rb"(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")),
    ("sessie-id", re.compile(rb"(?<![0-9A-Fa-f-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                             rb"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Fa-f-])")),
]


# Een git-remote over SSH, zoals git@github.com:eigenaar/repo.git, is geen e-mailadres.
SSH_REMOTE = re.compile(rb"git@[A-Za-z0-9.-]+\.[A-Za-z]{2,}:[\w.-]+/[\w.-]+")


def gepubliceerde_bestanden(root=ROOT):
    """Paden relatief aan root: bijgehouden en nieuwe niet-genegeerde bestanden, zonder
    .buildflow/ en tests/."""
    paden = set()
    for extra in ([], ["--others", "--exclude-standard"]):
        uit = subprocess.run(["git", "ls-files", "-z", *extra], cwd=root,
                             capture_output=True, check=True)
        paden.update(p.decode("utf-8") for p in uit.stdout.split(b"\0") if p)
    return sorted(p for p in paden if not p.startswith(NIET_GEPUBLICEERD)
                  and os.path.isfile(os.path.join(root, p)))


def _is_ssh_remote(regel, m):
    for r in SSH_REMOTE.finditer(regel):
        if r.start() == m.start() and r.end() >= m.end():
            return True
    return False


def scan_bestand(pad, root=ROOT):
    """Geeft meldingen als 'bestand:regel: soort: gevonden tekst'.

    TOEGESTAAN wordt vergeleken met het pad relatief aan root.
    """
    with open(pad, "rb") as f:
        inhoud = f.read()
    rel = os.path.relpath(os.path.abspath(pad), os.path.abspath(root)).replace(os.sep, "/")
    meldingen = []
    for nr, regel in enumerate(inhoud.split(b"\n"), 1):
        for soort, patroon in PATRONEN:
            for m in patroon.finditer(regel):
                gevonden = m.group(0).decode("utf-8", "replace")
                if (rel, gevonden) in TOEGESTAAN:
                    continue
                if soort == "e-mailadres" and _is_ssh_remote(regel, m):
                    continue
                meldingen.append(f"{pad}:{nr}: {soort}: {gevonden}")
    return meldingen


if __name__ == "__main__":
    alles = []
    for p in gepubliceerde_bestanden():
        alles += scan_bestand(os.path.join(ROOT, p))
    print("\n".join(alles) or "ok")
    sys.exit(1 if alles else 0)
