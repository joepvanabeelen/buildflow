"""Zoekt in alles wat GitHub Pages publiceert naar persoonlijke gegevens, alleen met de stdlib.

Gepubliceerd is alles wat git bijhoudt of straks bijhoudt (ook nieuwe bestanden die nog niet
zijn toegevoegd, maar niet wat .gitignore uitsluit), behalve .buildflow/ en tests/. Gezocht wordt naar
persoonlijke paden (/Users/, /private/tmp, /home/), e-mailadressen en sessie-id's in
UUID-vorm. Binaire bestanden worden als bytes gelezen, want ook een plaatje kan een pad
bevatten; gecomprimeerde tekst in een PNG (zTXt, iTXt) wordt eerst uitgepakt, tot
hooguit 1 MB per chunk.

Los draaien: python3 tests/check_privacy.py
"""
import os
import re
import struct
import subprocess
import sys
import zlib

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


# Meer dan dit pakt de scan niet uit: een kleine chunk kan anders uitgroeien tot
# gigabytes (een zip-bom). Wat groter is, telt als melding.
MAX_UITGEPAKT = 1024 * 1024


def _pak_uit(data, maximum=MAX_UITGEPAKT, stap=4096):
    """Pakt zlib-data uit tot maximum bytes. Geeft (tekst, probleem of None).

    Bij een kapotte stroom gooit zlib de uitvoer van de laatste aanroep weg. Daarom gaat
    het na een fout nog een keer byte voor byte, zodat alles wat wel leesbaar was
    bewaard blijft en toch gescand wordt.
    """
    d = zlib.decompressobj()
    uit = bytearray()
    try:
        for i in range(0, len(data), stap):
            invoer = data[i:i + stap]
            while invoer:
                uit += d.decompress(invoer, maximum - len(uit) + 1)
                if len(uit) > maximum:
                    return bytes(uit[:maximum]), (f"uitgepakt meer dan {maximum} bytes, "
                                                  "niet verder gelezen")
                invoer = d.unconsumed_tail
            if d.eof:
                break
    except zlib.error:
        if stap > 1:
            return _pak_uit(data, maximum, stap=1)
        return bytes(uit), "onleesbare gecomprimeerde tekst"
    if not d.eof:
        return bytes(uit), "gecomprimeerde tekst is afgekapt"
    return bytes(uit), None


def _png_stukken(inhoud):
    """Deelt een PNG op in (label, bytes, probleem of None), of geeft None als het geen PNG is.

    Tekstchunks (tEXt, zTXt, iTXt) komen leesbaar terug, gecomprimeerde tekst uitgepakt:
    als ruwe bytes glipt een pad in zTXt of iTXt anders langs de scan. De overige chunks
    en alles na IEND komen als ruwe bytes mee, zodat geen byte ongescand blijft.
    """
    if not inhoud.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    uit, i = [], 8
    while i + 8 <= len(inhoud):
        lengte, soort = struct.unpack(">I4s", inhoud[i:i + 8])
        if i + 12 + lengte > len(inhoud):
            break  # chunk loopt voorbij het einde: de rest gaat hieronder ruw mee
        data = inhoud[i + 8:i + 8 + lengte]
        naam = soort.decode("latin-1")
        i += 12 + lengte
        probleem = None
        if soort == b"tEXt":
            tekst = data.replace(b"\0", b" ")
        elif soort == b"zTXt":
            sleutel, _, rest = data.partition(b"\0")
            tekst, probleem = _pak_uit(rest[1:])
            tekst = sleutel + b" " + tekst
        elif soort == b"iTXt":
            sleutel, _, rest = data.partition(b"\0")
            gecomprimeerd, rest = rest[:1], rest[2:]
            taal, _, rest = rest.partition(b"\0")
            vertaald, _, tekst = rest.partition(b"\0")
            if gecomprimeerd == b"\x01":
                tekst, probleem = _pak_uit(tekst)
            tekst = b" ".join([sleutel, taal, vertaald, tekst])
        else:
            uit.append((f"PNG-chunk {naam}", data, None))
            if soort == b"IEND":
                break
            continue
        uit.append((f"PNG-tekstchunk {naam}", tekst, probleem))
    if i < len(inhoud):
        uit.append(("PNG, na de laatste hele chunk", inhoud[i:], None))
    return uit


def _zoek(label, tekst, rel):
    meldingen = []
    for soort, patroon in PATRONEN:
        for m in patroon.finditer(tekst):
            gevonden = m.group(0).decode("utf-8", "replace")
            if (rel, gevonden) in TOEGESTAAN:
                continue
            if soort == "e-mailadres" and _is_ssh_remote(tekst, m):
                continue
            meldingen.append(f"{label}: {soort}: {gevonden}")
    return meldingen


def scan_bestand(pad, root=ROOT):
    """Geeft meldingen als 'bestand:regel: soort: gevonden tekst'.

    Bij een PNG staat er in plaats van een regelnummer in welk stuk het zit, zoals
    'x.png (PNG-tekstchunk zTXt): soort: tekst'. Een tekstchunk die niet (helemaal) uit
    te pakken is, geeft ook een melding; het leesbare deel wordt wel gescand.
    TOEGESTAAN wordt vergeleken met het pad relatief aan root.
    """
    with open(pad, "rb") as f:
        inhoud = f.read()
    rel = os.path.relpath(os.path.abspath(pad), os.path.abspath(root)).replace(os.sep, "/")
    stukken = _png_stukken(inhoud)
    if stukken is None:
        meldingen = []
        for nr, regel in enumerate(inhoud.split(b"\n"), 1):
            meldingen += _zoek(f"{pad}:{nr}", regel, rel)
        return meldingen
    meldingen = []
    for label, tekst, probleem in stukken:
        plek = f"{pad} ({label})"
        if probleem:
            meldingen.append(f"{plek}: {probleem}")
        meldingen += _zoek(plek, tekst, rel)
    return meldingen


if __name__ == "__main__":
    alles = []
    for p in gepubliceerde_bestanden():
        alles += scan_bestand(os.path.join(ROOT, p))
    print("\n".join(alles) or "ok")
    sys.exit(1 if alles else 0)
