"""cp08 (review): elke link die een bezoeker in voorbeeld/ kan aanklikken, komt ergens uit.

De viewerpagina's bouwen hun links in JavaScript op uit window.BF. Een browser draait hier niet,
dus deze test doet na wat het sjabloon rendert en controleert of elk doel bestaat. Gedekt:

- de vaste sjabloonlinks: "← Alle features" (a.terug) en "Open volledige viewer" in een
  checkpointrapport (de knop met ${L.back});
- design: prototype (knop, statuschips, iframe) en designbestand (design_md of design_ref),
  zoals designSection() ze toont;
- checkpoint: het rapport (cp.report) in een gewone viewer;
- documentatie van de feature: elk bestand uit de docs-pogingen plus design_md en prototype,
  behalve de bestanden die het sjabloon als gewone tekst toont (lijst na /*zonder-link*/).

Niet gedekt: ankers binnen de pagina (#...), externe links (http/https, uit markdown) en de
overzichtspagina van alle runs (die zit niet in voorbeeld/).

De tweede helft toetst scripts/sanitize_demo.py op nepinvoer: sjabloonlinks, icoon,
gecodeerde paden en de weigering als er na het schoonmaken nog iets persoonlijks staat.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from tests.check_site import ROOT, lees
from tests.test_cp08_voorbeeld import (EMAIL, PROTO_REL, SCRIPT, UUID_A, VIEWERS, VIJF,
                                       VOORBEELD, bf_delen, momentopname, nep_data, schrijf)

PHASE_IDX = {"intake": 0, "brief": 1, "awaiting_brief_approval": 1, "design": 2,
             "awaiting_design_approval": 2, "planning": 3, "awaiting_plan_approval": 3,
             "building": 4, "documenting": 4, "awaiting_human_review": 5, "done": 6}

# Wat nergens in de uitvoer mag staan, ook niet gecodeerd.
PRIVE = re.compile(rb"/Users/|/home/[^\s\"'<>]|/private/(?:tmp|var)|/var/folders"
                   rb"|\\/Users\\/|%2FUsers%2F|&#47;Users|&#x2F;Users|\\/private\\/"
                   rb"|%2Fprivate%2F|%2Fvar%2Ffolders", re.I)


# ---------------------------------------------------------------- wat de viewer rendert

def js_href(href):
    """Het doel van een href uit het sjabloon, of None als het niet statisch te bepalen is."""
    m = re.fullmatch(r'\$\{esc\(\(D\.rel_root\|\|""\) \+ "([^"]+)"\)\}', href)
    if m:
        return ("rel_root", m.group(1))
    if "${" in href:
        return None
    return ("letterlijk", href)


def zichtbare_links(html):
    """(omschrijving, href) voor elke link die de pagina een bezoeker laat zien."""
    _, d, na = bf_delen(html)
    rel_root = d.get("rel_root") or ""
    focus = d.get("focus")
    stages = d.get("stages") or {}
    design, docs = stages.get("design") or {}, stages.get("docs") or {}
    project = d.get("project") or {}
    fase = PHASE_IDX.get(d.get("phase"), 4)
    links, zonder = [], []

    def rel(p):
        return p if re.match(r"^(https?:|/)", p) else rel_root + p

    def sjabloon(naam, patroon):
        m = re.search(patroon, na)
        if not m:
            raise AssertionError(f"sjabloonlink '{naam}' niet gevonden; is het sjabloon veranderd?")
        doel = js_href(m.group(1))
        if doel is None:
            raise AssertionError(f"sjabloonlink '{naam}' is niet statisch te controleren: {m.group(1)}")
        soort, waarde = doel
        links.append((naam, rel_root + waarde if soort == "rel_root" else waarde))

    sjabloon("← Alle features", r'<a class="terug" href="([^"]*)"')
    if focus and focus != "final":
        sjabloon("Open volledige viewer", r'<a class="knop rand klein" href="([^"]*)">\$\{L\.back\}')

    toon_design = not (focus and focus != "final") and (fase >= 2 or design.get("needed"))
    if toon_design:
        ref = project.get("design_ref")
        if design.get("status") == "not_needed":
            if ref:
                links.append(("designbestand", rel(ref)))
        else:
            proto = design.get("prototype") or project.get("prototype")
            if proto:
                links.append(("prototype", rel(proto)))
            if design.get("design_md") or ref:
                links.append(("designbestand", rel(design.get("design_md") or ref)))

    if not focus:
        for cp in d.get("checkpoints") or []:
            if cp.get("started_at") and cp.get("report"):
                links.append((f"rapport {cp['id']}", cp["report"]))

    if not (focus and focus != "final") and fase >= 4 and (docs.get("attempts") or d.get("phase") == "documenting"):
        m = re.search(r"/\*zonder-link\*/(\[[^\]]*\])", na)
        zonder = json.loads(m.group(1)) if m else []
        bestanden = []
        for cp in d.get("checkpoints") or []:
            for a in ((cp.get("gates") or {}).get("docs") or {}).get("attempts") or []:
                bestanden += a.get("files") or []
        for a in docs.get("attempts") or []:
            bestanden += a.get("files") or []
        bestanden += [design.get("design_md"), design.get("prototype")]
        for f in dict.fromkeys(b for b in bestanden if b):
            if f not in zonder:
                links.append((f"documentatie {f}", rel(f)))
    return links, zonder


def doelpad(html_pad, href):
    pad = href.split("#")[0].split("?")[0]
    return os.path.normpath(os.path.join(os.path.dirname(html_pad), pad))


class VoorbeeldLinks(unittest.TestCase):
    def test_elke_zichtbare_link_bestaat(self):
        fouten, geteld = [], 0
        for naam in VIJF:
            pad = os.path.join(VOORBEELD, naam)
            links, _ = zichtbare_links(lees(pad))
            for omschrijving, href in links:
                geteld += 1
                if re.match(r"^https?:", href):
                    continue
                doel = doelpad(pad, href)
                if not os.path.isfile(doel):
                    fouten.append(f"{naam}: '{omschrijving}' -> {href} (bestaat niet)")
                    continue
                anker = href.split("#", 1)[1] if "#" in href else ""
                if anker and f'id="{anker}"' not in lees(doel):
                    fouten.append(f"{naam}: '{omschrijving}' -> {href} (anker ontbreekt)")
        self.assertEqual(fouten, [], "\n".join(fouten))
        self.assertGreaterEqual(geteld, 10, "te weinig links gevonden; klopt de nabootsing nog?")

    def test_terug_links_wijzen_naar_site_en_viewer(self):
        for naam in VIJF:
            with self.subTest(naam=naam):
                links = dict(zichtbare_links(lees(os.path.join(VOORBEELD, naam)))[0])
                self.assertEqual(links["← Alle features"], "../index.html#voorbeeld")
        links = dict(zichtbare_links(lees(os.path.join(VOORBEELD, "cp01.html")))[0])
        self.assertEqual(links["Open volledige viewer"], "viewer-plan.html")

    def test_ontbrekende_docs_zijn_tekst_en_niet_meer_dan_nodig(self):
        _, zonder = zichtbare_links(lees(os.path.join(VOORBEELD, "final.html")))
        self.assertIn("README.md", zonder)
        for f in zonder:
            self.assertFalse(os.path.exists(os.path.join(VOORBEELD, f)),
                             f"{f} bestaat wel maar wordt als tekst getoond")

    def test_paginas_hebben_een_icoon_zodat_er_geen_favicon_ico_nodig_is(self):
        for naam in VIJF + [PROTO_PAD]:
            with self.subTest(naam=naam):
                html = lees(os.path.join(VOORBEELD, naam))
                self.assertRegex(html, r'<link rel="icon" href="data:image/svg\+xml,')


PROTO_PAD = "docs/design/prototypes/donker-thema/index.html"


# ---------------------------------------------------------------- het script, op nepinvoer

SJABLOON = (
    '<a class="terug" href="${esc((D.rel_root||"") + ".buildflow/index.html")}">← ${esc(L.allRuns)}</a>\n'
    '${files.length ? `<div>${files.map(f=>`<div class="klein"><a href="${esc(relLink(f))}">'
    '<code>${esc(f)}</code></a></div>`).join("")}</div>` : ""}\n'
    'body = `<a class="knop rand klein" href="../viewer.html">${L.back}</a>`;\n')
ICOON = '<link rel="icon" href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E">'


def viewer_met_sjabloon(data):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return ("<!doctype html>\n<html lang=\"nl\"><head><meta charset=\"utf-8\">\n"
            "<title>Demo knop · buildflow</title></head>\n<body>\n<script>\nwindow.BF = " + blob
            + ";\n" + SJABLOON + "</script>\n</body></html>\n")


def png(chunks):
    def blok(soort, data):
        return struct.pack(">I", len(data)) + soort + data + struct.pack(
            ">I", zlib.crc32(soort + data) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + blok(b"IHDR", ihdr) + b"".join(blok(s, d) for s, d in chunks)
            + blok(b"IDAT", zlib.compress(b"\0\0")) + blok(b"IEND", b""))


class SanitizeLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.invoer = os.path.join(self.tmp, "ruw")
        self.uitvoer = os.path.join(self.tmp, "site", "voorbeeld")
        schrijf(os.path.join(self.tmp, "site", "index.html"),
                f"<!doctype html><head>{ICOON}</head><section id=\"voorbeeld\"></section>\n")
        fasen = {"viewer-brief.html": "awaiting_brief_approval",
                 "viewer-design.html": "awaiting_design_approval",
                 "viewer-plan.html": "awaiting_plan_approval", "cp01.html": "building",
                 "final.html": "awaiting_human_review"}
        for naam, focus in VIEWERS.items():
            d = nep_data("/Users/iemand/scratch/demo-app", focus)
            d["phase"] = fasen[naam]
            d["stages"]["docs"] = {"status": "passed", "attempts": [
                {"files": ["README.md", "docs/README.md", "docs/design/design.md"]}]}
            schrijf(os.path.join(self.invoer, naam), viewer_met_sjabloon(d))
        schrijf(os.path.join(self.invoer, *PROTO_REL.split("/")),
                "<!doctype html><html><head><title>proto</title></head><body></body></html>\n")
        schrijf(os.path.join(self.invoer, "docs", "design", "design.md"), "# design\n")

    def draai(self):
        return subprocess.run([sys.executable, SCRIPT, self.invoer, self.uitvoer], cwd=self.tmp,
                              capture_output=True, text=True, timeout=60)

    def draai_ok(self):
        r = self.draai()
        self.assertEqual(r.returncode, 0, f"script faalde:\n{r.stdout}\n{r.stderr}")

    def test_sjabloonlinks_wijzen_naar_bestaande_plekken(self):
        self.draai_ok()
        for naam in VIJF:
            with self.subTest(naam=naam):
                pad = os.path.join(self.uitvoer, naam)
                html = lees(pad)
                self.assertNotIn(".buildflow/index.html", html)
                self.assertNotIn("../viewer.html", html)
                self.assertIn('class="terug" href="../index.html#voorbeeld"', html)
                self.assertIn('href="viewer-plan.html">${L.back}', html,
                              "terugknop wijst niet naar de meest gevorderde viewer")

    def test_run_in_submap_van_voorbeeld_vindt_de_site_een_map_hoger(self):
        # Een tweede voorbeeld staat in voorbeeld/<run>/: index.html staat dan twee mappen hoger.
        self.uitvoer = os.path.join(self.tmp, "site", "voorbeeld", "tweede-run")
        self.draai_ok()
        for naam in VIJF:
            with self.subTest(naam=naam):
                html = lees(os.path.join(self.uitvoer, naam))
                self.assertIn('class="terug" href="../../index.html#voorbeeld"', html)
                self.assertEqual(html.count(ICOON), 1)
        proto = lees(os.path.join(self.uitvoer, *PROTO_REL.split("/")))
        self.assertEqual(proto.count(ICOON), 1)

    def test_zonder_site_index_blijft_de_overzichtslink_staan(self):
        os.remove(os.path.join(self.tmp, "site", "index.html"))
        self.draai_ok()
        html = lees(os.path.join(self.uitvoer, "final.html"))
        self.assertIn('.buildflow/index.html', html)
        self.assertNotIn('rel="icon"', html)

    def test_ontbrekende_docs_worden_tekst_bestaande_blijven_link(self):
        self.draai_ok()
        _, zonder = zichtbare_links(lees(os.path.join(self.uitvoer, "final.html")))
        self.assertEqual(sorted(zonder), ["README.md", "docs/README.md"])

    def test_icoon_van_de_site_in_elke_pagina(self):
        self.draai_ok()
        for naam in VIJF + [PROTO_REL]:
            with self.subTest(naam=naam):
                html = lees(os.path.join(self.uitvoer, naam))
                self.assertEqual(html.count(ICOON), 1)
                self.assertLess(html.index(ICOON), html.index("</head>"))

    def test_gecodeerde_paden_gaan_eruit(self):
        stukken = [r"\/Users\/iemand\/geheim", "%2FUsers%2Fiemand%2Fgeheim",
                   "%2fusers%2fiemand%2fgeheim", "&#47;Users&#47;iemand&#47;geheim",
                   "&#x2F;home&#x2F;iemand&#x2F;geheim", "/private/var/folders/ab/cd/T/x.txt",
                   "/var/folders/ab/cd/T/y.txt", r"\/private\/tmp\/claude-501\/z",
                   "%2Fprivate%2Ftmp%2Fz", "/private/tmp/q/r.txt"]
        schrijf(os.path.join(self.invoer, "notities.txt"), "\n".join(stukken) + "\n")
        pad = os.path.join(self.invoer, "viewer-brief.html")
        _, d, _ = bf_delen(lees(pad))
        d["brief_text"] = " ".join(stukken)
        schrijf(pad, viewer_met_sjabloon(d))
        self.draai_ok()
        for rel in momentopname(self.uitvoer):
            with open(os.path.join(self.uitvoer, rel), "rb") as f:
                inhoud = f.read()
            with self.subTest(rel=rel):
                self.assertIsNone(PRIVE.search(inhoud), PRIVE.search(inhoud))
                self.assertNotIn(b"iemand", inhoud)
        _, d, _ = bf_delen(lees(os.path.join(self.uitvoer, "viewer-brief.html")))
        self.assertIn("geheim", d["brief_text"], "meer weggehaald dan het pad")

    def alles_uit(self):
        uit = b""
        for rel in momentopname(self.uitvoer):
            with open(os.path.join(self.uitvoer, rel), "rb") as f:
                uit += f.read() + b"\n"
        return uit

    def test_tmp_paden_file_urls_en_claude_mapnamen_gaan_eruit(self):
        stukken = ["file:///tmp/claude-501/-Users-iemandx-projects/scratch/a.txt",
                   "/tmp/claude-501/-Users-iemandx-projects-foo",
                   "file:///private/var/folders/ab/cd/T/b.txt",
                   "file:///Users/iemandx/Desktop/c.txt",
                   "map -Users-iemandx-projects-demo-app los",
                   "&sol;Users&sol;iemandx&sol;d", "&#0047;tmp&#0047;claude-501&#0047;e",
                   "%2Ftmp%2Fclaude-501%2Ff"]
        schrijf(os.path.join(self.invoer, "notities.txt"), "\n".join(stukken) + "\n")
        pad = os.path.join(self.invoer, "viewer-brief.html")
        _, d, _ = bf_delen(lees(pad))
        d["brief_text"] = " ".join(stukken)
        schrijf(pad, viewer_met_sjabloon(d))
        self.draai_ok()
        alles = self.alles_uit()
        for verboden in (b"iemandx", b"claude-501", b"-Users-", b"file:///tmp", b"&sol;Users"):
            self.assertNotIn(verboden, alles)
        # De vervanging is ~ plus de gecodeerde slash; zonder ~ ervoor is het nog een echt pad.
        for verboden in (rb"(?<!~)&#0047;tmp", rb"(?<!~)%2Ftmp"):
            self.assertIsNone(re.search(verboden, alles), verboden)
        self.assertIsNone(re.search(rb"(?<!~)/tmp/", alles), "kaal /tmp/-pad bleef staan")
        self.assertIn(b"~/tmp/a.txt", alles, "bestandsnaam na de tijdelijke map is weg")

    def test_sessielinks_en_trailers_gaan_eruit(self):
        # Opgebouwd tijdens het draaien, zodat de privacyscan van cp10 er niet op aanslaat.
        url, trailer = "https://claude.ai" + "/code/", "Claude-" + "Session:"
        tekst = (f"Zie {url}session_01AbCdEfGhIjKlMnOpQrStUv voor de run.\n"
                 f"{trailer} {url}session_ABCdef123\n"
                 f"{trailer} 01AbCdEfGhIj\n")
        schrijf(os.path.join(self.invoer, "commit.txt"), tekst)
        self.draai_ok()
        uit = lees(os.path.join(self.uitvoer, "commit.txt"))
        self.assertNotIn("session_", uit)
        self.assertNotIn("01AbCdEfGhIj", uit)
        self.assertEqual(uit.count("[sessielink]"), 3)
        self.assertEqual(uit.count("Claude-Session: [sessielink]"), 2)

    def test_retina_bestandsnaam_is_geen_emailadres(self):
        schrijf(os.path.join(self.invoer, "logo.html"),
                '<img src="logo@2x.png" srcset="icon@3x.webp 3x"> mail iemand@voorbeeld.nl\n')
        self.draai_ok()
        uit = lees(os.path.join(self.uitvoer, "logo.html"))
        self.assertIn("logo@2x.png", uit)
        self.assertIn("icon@3x.webp", uit)
        self.assertNotIn("iemand@voorbeeld.nl", uit)

    def test_weigert_binair_bestand_met_tmp_pad_of_gecodeerde_gebruikersmap(self):
        self.weigert("a.bin", b"\x00\xff/tmp/claude-501/x\x00")
        self.weigert("b.bin", b"\x00\xff-Users-iemandx-projects\x00")
        url = b"https://claude.ai" + b"/code/"
        self.weigert("c.bin", b"\x00\xff" + url + b"session_01AbCdEfGhIj\x00")

    def weigert(self, bestand, inhoud):
        schrijf(os.path.join(self.uitvoer, "oud.html"), "oud\n")
        voor = momentopname(self.uitvoer)
        os.makedirs(os.path.dirname(os.path.join(self.invoer, bestand)), exist_ok=True)
        with open(os.path.join(self.invoer, bestand), "wb") as f:
            f.write(inhoud)
        r = self.draai()
        self.assertNotEqual(r.returncode, 0, f"script slaagde terwijl {bestand} een pad bevat")
        self.assertIn(bestand, r.stderr)
        self.assertEqual(momentopname(self.uitvoer), voor, "uitvoermap toch gewijzigd")

    def test_weigert_png_met_pad_in_tekstblok(self):
        self.weigert("shot.png", png([(b"tEXt", b"Comment\0/Users/iemand/Desktop/x.png")]))

    def test_weigert_png_met_pad_in_gecomprimeerd_tekstblok(self):
        self.weigert("shot.png", png([(b"zTXt", b"Comment\0\0" + zlib.compress(
            b"gemaakt in /private/var/folders/ab/T/x"))]))
        self.weigert("shot2.png", png([(b"iTXt", b"Comment\0\1\0\0\0" + zlib.compress(
            f"door {EMAIL}".encode()))]))

    def test_weigert_binair_bestand_met_sessie_id(self):
        self.weigert("data.bin", b"\x00\xff" + UUID_A.encode() + b"\x00")

    def test_schone_png_gaat_ongewijzigd_mee(self):
        inhoud = png([(b"tEXt", b"Software\0buildflow")])
        with open(os.path.join(self.invoer, "shot.png"), "wb") as f:
            f.write(inhoud)
        self.draai_ok()
        with open(os.path.join(self.uitvoer, "shot.png"), "rb") as f:
            self.assertEqual(f.read(), inhoud)


if __name__ == "__main__":
    unittest.main()
