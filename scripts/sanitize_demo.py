#!/usr/bin/env python3
"""Maakt de ruwe kopieën van een buildflow-demorun schoon voor voorbeeld/.

    python3 scripts/sanitize_demo.py <invoermap> <uitvoermap>

De invoermap bevat de viewer- en rapportbestanden zoals bf.py ze schrijft (een html-sjabloon
met `window.BF = {...};`), plus eventuele andere bestanden van de run op hun pad relatief
aan de projectroot, zoals de prototypepagina waar design.prototype naar wijst (bijvoorbeeld
docs/design/prototypes/<slug>/index.html).

Wat het script doet:
- het projectpad (project.root) wordt overal ~/demo/<projectnaam>; andere persoonlijke paden
  (een thuismap onder Users of home, een map onder tmp of var/folders) worden ingekort tot iets
  onder ~, ook in een file://-url. Dat geldt ook voor de gecodeerde vormen: \\/ uit JSON, %2F
  uit een url en &#47;, &#x2F; of &sol; uit html. De mapnaam die Claude Code van een pad maakt
  (-Users-<naam>-...) wordt -demo-..., en de tijdelijke map claude-<uid> wordt claude;
- links naar een Claude Code-sessie (https://claude.ai/code/session_...) en de waarde van een
  Claude-Session:-regel worden [sessielink];
- sessie-id's worden sessie-1, sessie-2, ... (dezelfde id krijgt overal dezelfde vervanging);
- e-mailadressen worden [e-mailadres]; een retina-bestandsnaam (naam, @2x, dan .png) is geen e-mailadres;
- rel_root in window.BF wijst daarna naar de uitvoermap zelf, zodat relatieve links zoals
  design.prototype uitkomen bij de meegekopieerde bestanden;
- in meegekopieerde html-pagina's (zoals het prototype) wordt een lege link href="#"
  href="./", zodat de linkcontrole van de site er niet over struikelt. De link deed al niets;
- naast een gewone viewer (niet een rapport) komt een data.json met alleen `null`. Over http
  vraagt de viewer elke vier seconden data.json op om bij te werken. Een momentopname heeft
  geen live data: met `null` loopt die poging stil af, zonder 404 in de console en zonder
  dat de viewer zijn eigen gegevens overschrijft.

Links die de viewer zelf in JavaScript opbouwt, wijzen in een run naar bestanden die in een
losse momentopname niet bestaan. Het script past daarom deze vaste stukken van het sjabloon aan:
- "← Alle features" (rel_root + .buildflow/index.html) wijst naar ../index.html#voorbeeld, de
  sectie op de site waar de voorbeeldrun staat. Alleen als die index.html naast de uitvoermap
  staat; anders blijft de link zoals hij was;
- "Open volledige viewer" in een checkpointrapport (../viewer.html) wijst naar de meest
  gevorderde gewone viewer in de uitvoermap (hier viewer-plan.html);
- documentatiebestanden in de lijst bij "Documentatie van de feature" die niet in de invoer
  zitten, worden gewone tekst in plaats van een link. Een momentopname heeft de README's van
  het demoproject niet; een link zou een 404 geven, de bestandsnaam zelf zegt nog wel iets.
Staat er naast de uitvoermap een index.html met een <link rel="icon"> (de site zelf), dan
krijgt elke meegekopieerde html-pagina zonder icoon dat icoon. Zo vraagt de browser niet om
een /favicon.ico die er niet is.

Na het schoonmaken zoekt het script de hele uitvoer nog eens na, ook binaire bestanden (en in
een png de tekstblokken, ook gecomprimeerd). Staat er dan nog een persoonlijk pad, e-mailadres
sessie-id, sessielink of gecodeerde gebruikersmap (-Users-, claude-<uid>)
in, dan stopt het met een foutmelding en schrijft het niets.

Bedragen, tijden, testaantallen en de rest van de html blijven precies zoals ze waren.
Het script schrijft alleen in de uitvoermap. Alleen de stdlib.
"""
import json
import os
import re
import struct
import sys
import zlib

BF = re.compile(r"window\.BF\s*=\s*")
UUID = re.compile(r"(?<![0-9A-Fa-f-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                  r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Fa-f-])")
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+"
                   r"(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
# Een git-remote over SSH (git@github.com:eigenaar/repo.git) is geen e-mailadres.
SSH_REMOTE = re.compile(r"git@[A-Za-z0-9.-]+\.[A-Za-z]{2,}:[\w.-]+/[\w.-]+")
LEGE_LINK = re.compile(r"""href=(["'])#\1""")
HOME = re.compile(r"(?<![\w.~-])/(?:Users|home)/([^/\s\"'<>]+)")
# Een tijdelijke map, ook als file:///tmp/... (daar staat wel een / voor).
TMP = re.compile(r"(?:(?<=file://)|(?<![\w.~/-]))(?:/private)?/(?:tmp|var/folders)/[^\s\"'<>]*")
# Zoals Claude Code een pad als mapnaam schrijft: -Users-<naam>-projects-..., en de tijdelijke
# map per gebruiker claude-<uid>. De naam is het eerste stuk na -Users- of -home-.
GECODEERDE_NAAM = re.compile(r"(?<![A-Za-z0-9])-(?:Users|home)-([A-Za-z0-9_.]+)")
CLAUDE_UID = re.compile(r"(?<![A-Za-z0-9])claude-\d{3,}(?!\d)")
# Links naar een Claude Code-sessie en de trailer in commitberichten.
SESSIELINK = re.compile(r"https?://claude\.ai/code/session_[A-Za-z0-9]+")
SESSIE_TRAILER = re.compile(r"(Claude-Session:[ \t]*)(?!\[sessielink\])[^\s\"'<>]+")
# Dezelfde paden in gecodeerde vorm: \/ (JSON), %2F (url), &#47;, &#x2F; of &sol; (html).
SLASHES = (r"\\/", r"%2[fF]", r"&#(?:0*47|[xX]0*2[fF]);", r"&sol;")
SEGMENT = r"[A-Za-z0-9._~+@-]+"
GECODEERD = []
for sl in SLASHES:
    GECODEERD.append((re.compile(rf"{sl}(?:Users|home){sl}{SEGMENT}", re.I), None))
    GECODEERD.append((re.compile(rf"(?:{sl}private)?{sl}(?:tmp|var{sl}folders)(?:{sl}{SEGMENT})*",
                                 re.I), "tmp"))
# Een e-mailadres uit EMAIL is het niet als het een bestandsnaam is, zoals een retina-plaatje met @2x voor de extensie.
BESTAND_EXT = re.compile(r"\.(?:png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?|pdf|css|js|html?)$", re.I)
_SL_B = rb"(?:\\/|%2f|&#(?:0*47|x0*2f);|&sol;)"
# Wat na het schoonmaken nergens meer mag staan, als bytes, in welke codering dan ook.
# ~/tmp/... is de vervanging zelf en telt niet mee.
VERBODEN = [
    ("persoonlijk pad", re.compile(rb"/(?:Users|home)/|/private/(?:tmp|var)\b|/var/folders/"
                                   rb"|(?<!~)/tmp/")),
    ("gecodeerd persoonlijk pad", re.compile(
        rb"(?<!~)" + _SL_B + rb"(?:users|home|private|tmp|var" + _SL_B + rb"folders)" + _SL_B,
        re.I)),
    ("gecodeerde gebruikersmap", re.compile(rb"-Users-|(?<![A-Za-z0-9])claude-\d{3,}(?!\d)")),
    ("sessielink", re.compile(rb"claude\.ai/code/session_|Claude-Session:[ \t]*(?!\[sessielink\])\S")),
    ("e-mailadres", re.compile(EMAIL.pattern.encode())),
    ("sessie-id", re.compile(UUID.pattern.encode())),
]
SSH_REMOTE_B = re.compile(SSH_REMOTE.pattern.encode())
# Vaste stukken van het viewersjabloon (bf.py) met links die in een momentopname dood zijn.
TERUG_ALLE = '${esc((D.rel_root||"") + ".buildflow/index.html")}'
TERUG_VIEWER = 'href="../viewer.html"'
DOCLIJST = ('files.map(f=>`<div class="klein"><a href="${esc(relLink(f))}"><code>${esc(f)}</code>'
            '</a></div>`)')
ICOON = re.compile(r"""<link\b[^>]*\brel=(["'])(?:shortcut )?icon\1[^>]*>""", re.I)
PHASE_IDX = {"intake": 0, "brief": 1, "awaiting_brief_approval": 1, "design": 2,
             "awaiting_design_approval": 2, "planning": 3, "awaiting_plan_approval": 3,
             "building": 4, "documenting": 4, "awaiting_human_review": 5, "done": 6}
EMAIL_VERVANGING = "[e-mailadres]"


def fout(melding):
    print(f"sanitize_demo: {melding}", file=sys.stderr)
    sys.exit(2)


def lees(pad):
    with open(pad, "rb") as f:
        return f.read()


def als_tekst(inhoud):
    try:
        return inhoud.decode("utf-8")
    except UnicodeDecodeError:
        return None


def splits_bf(html):
    """(tekst voor de JSON, data, tekst na de JSON), of None als er geen window.BF in staat."""
    m = BF.search(html)
    if not m:
        return None
    try:
        data, eind = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError:
        return None
    return html[:m.end()], data, html[eind:]


def encodeer(pad):
    """Zoals Claude Code een projectpad als mapnaam schrijft: elk ander teken dan a-z0-9 wordt '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", pad)


class Schoonmaker:
    def __init__(self, projectroots, namen):
        self.sessies = {}
        # Langste eerst, zodat een root binnen een andere root niet half vervangen wordt.
        self.roots = []
        for root in sorted(set(projectroots), key=len, reverse=True):
            doel = "~/demo/" + (os.path.basename(root.rstrip("/")) or "project")
            varianten = {root}
            if root.startswith("/private/"):
                varianten.add(root[len("/private"):])
            elif root.startswith("/tmp/"):
                varianten.add("/private" + root)
            for v in varianten:
                self.roots.append((v, doel))
                self.roots.append((encodeer(v), "-demo-" + encodeer(os.path.basename(doel))))
        self.roots.sort(key=lambda x: len(x[0]), reverse=True)
        # Gebruikersnamen uit de thuismap: ook de gecodeerde vorm (-Users-<naam>) gaat eruit.
        self.namen = sorted(set(namen), key=len, reverse=True)

    def sessie(self, m):
        sleutel = m.group(0).lower()
        if sleutel not in self.sessies:
            self.sessies[sleutel] = f"sessie-{len(self.sessies) + 1}"
        return self.sessies[sleutel]

    @staticmethod
    def email(m):
        if BESTAND_EXT.search(m.group(0)):
            return m.group(0)
        regel = m.string
        for r in SSH_REMOTE.finditer(regel):
            if r.start() == m.start() and r.end() >= m.end():
                return m.group(0)
        return EMAIL_VERVANGING

    def tekst(self, s):
        for oud, nieuw in self.roots:
            s = s.replace(oud, nieuw)
        for naam in self.namen:
            for prefix in ("-Users-", "-home-"):
                s = s.replace(prefix + encodeer(naam), "-demo")
        s = GECODEERDE_NAAM.sub("-demo", s)
        s = CLAUDE_UID.sub("claude", s)
        s = SESSIELINK.sub("[sessielink]", s)
        s = SESSIE_TRAILER.sub(lambda m: m.group(1) + "[sessielink]", s)
        for patroon, soort in GECODEERD:
            s = patroon.sub(lambda m, soort=soort: self.gecodeerd(m.group(0), soort), s)
        s = HOME.sub("~", s)
        s = TMP.sub(lambda m: "~/tmp/" + os.path.basename(m.group(0).rstrip("/")), s)
        s = UUID.sub(self.sessie, s)
        s = EMAIL.sub(self.email, s)
        return s

    @staticmethod
    def gecodeerd(gevonden, soort):
        sl = re.match("|".join(SLASHES), gevonden).group(0)
        return "~" + (sl + "tmp" if soort else "")

    def data(self, x):
        if isinstance(x, dict):
            return {self.tekst(k) if isinstance(k, str) else k: self.data(v) for k, v in x.items()}
        if isinstance(x, list):
            return [self.data(v) for v in x]
        if isinstance(x, str):
            return self.tekst(x)
        return x


def alle_bestanden(map_):
    uit = []
    for wortel, mappen, namen in os.walk(map_):
        mappen.sort()
        for naam in sorted(namen):
            if naam == ".DS_Store":
                continue
            uit.append(os.path.relpath(os.path.join(wortel, naam), map_))
    # Viewerbestanden bovenaan in een vaste volgorde, zodat sessie-1 steeds dezelfde is.
    return sorted(uit, key=lambda p: (p.count(os.sep), p))


def png_teksten(inhoud):
    """De tekst uit de tEXt-, zTXt- en iTXt-blokken van een png, uitgepakt waar nodig."""
    if not inhoud.startswith(b"\x89PNG\r\n\x1a\n"):
        return []
    uit, i = [], 8
    while i + 8 <= len(inhoud):
        lengte, soort = struct.unpack(">I4s", inhoud[i:i + 8])
        blok = inhoud[i + 8:i + 8 + lengte]
        i += 12 + lengte
        try:
            if soort == b"tEXt":
                uit.append(blok)
            elif soort == b"zTXt":
                sleutel, rest = blok.split(b"\0", 1)
                uit.append(sleutel + b"\0" + zlib.decompress(rest[1:]))
            elif soort == b"iTXt":
                sleutel, rest = blok.split(b"\0", 1)
                gecomprimeerd, rest = rest[0], rest[2:]
                taal, vertaald, tekst = rest.split(b"\0", 2)
                uit.append(b"\0".join([sleutel, taal, vertaald,
                                       zlib.decompress(tekst) if gecomprimeerd else tekst]))
        except (ValueError, zlib.error):
            uit.append(blok)
        if soort == b"IEND":
            break
    return uit


def resten(rel, inhoud):
    """Persoonlijke gegevens die na het schoonmaken nog in een bestand staan."""
    meldingen = []
    for stuk in [inhoud] + png_teksten(inhoud):
        for soort, patroon in VERBODEN:
            for m in patroon.finditer(stuk):
                if soort == "e-mailadres" and BESTAND_EXT.search(m.group(0).decode("utf-8", "replace")):
                    continue
                if soort == "e-mailadres" and any(
                        r.start() == m.start() and r.end() >= m.end()
                        for r in SSH_REMOTE_B.finditer(stuk)):
                    continue
                meldingen.append(f"{rel}: {soort}: {m.group(0).decode('utf-8', 'replace')}")
    return meldingen


def doc_bestanden(data):
    """De bestanden die de viewer onder 'Documentatie van de feature' als link toont."""
    stages = data.get("stages") or {}
    design, docs = stages.get("design") or {}, stages.get("docs") or {}
    bestanden = []
    for cp in data.get("checkpoints") or []:
        for poging in ((cp.get("gates") or {}).get("docs") or {}).get("attempts") or []:
            bestanden += poging.get("files") or []
    for poging in docs.get("attempts") or []:
        bestanden += poging.get("files") or []
    bestanden += [design.get("design_md"), design.get("prototype")]
    return list(dict.fromkeys(f for f in bestanden if isinstance(f, str) and f))


def bestaat(rel_viewer, doel, uitvoer_rels):
    if re.match(r"^(https?:|/)", doel):
        return True
    pad = os.path.normpath(os.path.join(os.path.dirname(rel_viewer), doel.split("?")[0]
                                        .split("#")[0]))
    return pad in uitvoer_rels


def site_icoon(uitvoer):
    """Het icoon van de site: de <link rel="icon"> uit index.html naast de uitvoermap."""
    index = os.path.join(os.path.dirname(uitvoer), "index.html")
    if not os.path.isfile(index):
        return None, None
    with open(index, encoding="utf-8") as f:
        html = f.read()
    m = ICOON.search(html)
    return (m.group(0) if m else None), html


def pas_sjabloon_aan(rel, html, data, uitvoer_rels, laatste_viewer, site_html):
    """Maakt de vaste links in het viewersjabloon werkend voor een momentopname."""
    diepte = "../" * rel.count(os.sep)
    if TERUG_ALLE in html and site_html is not None and 'id="voorbeeld"' in site_html:
        html = html.replace(TERUG_ALLE, diepte + "../index.html#voorbeeld")
    if TERUG_VIEWER in html and laatste_viewer:
        html = html.replace(TERUG_VIEWER, f'href="{os.path.relpath(laatste_viewer, os.path.dirname(rel) or ".")}"')
    ontbreekt = [f for f in doc_bestanden(data)
                 if not bestaat(rel, (data.get("rel_root") or "") + f, uitvoer_rels)]
    if ontbreekt and DOCLIJST in html:
        lijst = json.dumps(ontbreekt, ensure_ascii=False).replace("</", "<\\/")
        html = html.replace(DOCLIJST, (
            f"files.map(f=>/*zonder-link*/{lijst}.includes(f)"
            f" ? `<div class=\"klein\"><code>${{esc(f)}}</code></div>` : "
            + DOCLIJST[len("files.map(f=>"):-1] + ")"))
    elif ontbreekt:
        print(f"  let op: {rel} linkt naar bestanden die er niet zijn: {', '.join(ontbreekt)}",
              file=sys.stderr)
    return html


def zet_icoon(html, icoon):
    if not icoon or ICOON.search(html) or "</head>" not in html:
        return html
    return html.replace("</head>", icoon + "\n</head>", 1)


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().split("\n\n")[0], file=sys.stderr)
        fout("gebruik: sanitize_demo.py <invoermap> <uitvoermap>")
    invoer, uitvoer = os.path.abspath(argv[1]), os.path.abspath(argv[2])
    if not os.path.isdir(invoer):
        fout(f"invoermap bestaat niet: {argv[1]}")
    if os.path.commonpath([invoer, uitvoer]) in (invoer, uitvoer):
        fout("invoer- en uitvoermap mogen niet in elkaar liggen")

    bestanden = alle_bestanden(invoer)
    inhoud = {rel: lees(os.path.join(invoer, rel)) for rel in bestanden}
    viewers, roots, namen = {}, [], []
    for rel, ruw in inhoud.items():
        tekst = als_tekst(ruw)
        if tekst is None:
            continue
        namen += HOME.findall(tekst) + GECODEERDE_NAAM.findall(tekst)
        if rel.endswith(".html"):
            delen = splits_bf(tekst)
            if delen:
                viewers[rel] = delen
                root = (delen[1].get("project") or {}).get("root")
                if isinstance(root, str) and root:
                    roots.append(root)
    if not viewers:
        fout(f"geen viewerbestanden (window.BF) gevonden in {argv[1]}")

    # Alles eerst in het geheugen: pas als de controle slaagt, wordt er iets geschreven.
    s = Schoonmaker(roots, namen)
    uit = {}
    live = {os.path.dirname(rel) for rel, (_, data, _) in viewers.items() if not data.get("focus")}
    for map_ in sorted(live):
        rel = os.path.join(map_, "data.json")
        if rel not in inhoud:
            uit[rel] = b"null\n"
    alle_rels = set(bestanden) | set(uit)
    gewoon = [(PHASE_IDX.get(d.get("phase"), 4), rel) for rel, (_, d, _) in viewers.items()
              if not d.get("focus")]
    laatste_viewer = max(gewoon)[1] if gewoon else None
    icoon, site_html = site_icoon(uitvoer)
    for rel in bestanden:
        if rel in viewers:
            voor, data, na = viewers[rel]
            data = s.data(data)
            data["rel_root"] = "../" * rel.count(os.sep)
            blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            voor = zet_icoon(s.tekst(voor), icoon)
            na = pas_sjabloon_aan(rel, s.tekst(na), data, alle_rels, laatste_viewer, site_html)
            uit[rel] = (voor + blob + na).encode("utf-8")
        else:
            tekst = als_tekst(inhoud[rel])
            if tekst is not None:
                tekst = s.tekst(tekst)
                if rel.endswith((".html", ".htm")):
                    tekst = LEGE_LINK.sub(lambda m: f"href={m.group(1)}./{m.group(1)}", tekst)
                    tekst = zet_icoon(tekst, icoon)
            uit[rel] = inhoud[rel] if tekst is None else tekst.encode("utf-8")

    meldingen = [m for rel in sorted(uit) for m in resten(rel, uit[rel])]
    if meldingen:
        print("\n".join(meldingen), file=sys.stderr)
        fout(f"na het schoonmaken staat er nog iets persoonlijks in {len(meldingen)} plek(ken); "
             f"er is niets geschreven naar {argv[2]}")

    for rel in sorted(uit, key=lambda p: (p.count(os.sep), p)):
        doel = os.path.join(uitvoer, rel)
        os.makedirs(os.path.dirname(doel), exist_ok=True)
        with open(doel, "wb") as f:
            f.write(uit[rel])
        print(f"  {rel}" + ("" if rel in inhoud else " (leeg, voor de viewer)"))
    print(f"{len(bestanden)} bestanden naar {argv[2]} "
          f"({len(viewers)} viewers, {len(s.sessies)} sessie-id's vervangen)")


if __name__ == "__main__":
    main(sys.argv)
