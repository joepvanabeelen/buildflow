"""cp01: de pagina staat in de repo, zonder prototype-extra's."""
import os
import re
import shutil
import socket
import tempfile
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from collections import Counter

from tests.check_site import (CSS, INDEX, PROTOTYPE, ROOT, Pagina, controleer_links,
                              css_tokens, design_tokens, lees)

SECTIES = ["top", "waarde", "werking", "handleiding", "voorbeeld",
           "installeren", "download", "vragen"]


class Basis(unittest.TestCase):
    def index_html(self):
        self.assertTrue(os.path.isfile(INDEX), "index.html ontbreekt in de repo-root")
        return lees(INDEX)

    def site_css(self):
        self.assertTrue(os.path.isfile(CSS), "assets/site.css ontbreekt")
        return lees(CSS)

    def pagina(self):
        return Pagina(self.index_html())


class TestStructuur(Basis):
    def test_html_parseert_zonder_nestfouten(self):
        p = self.pagina()
        self.assertEqual(p.fouten, [], "HTML-nestfouten:\n" + "\n".join(p.fouten))

    def test_secties_in_volgorde_met_footer(self):
        p = self.pagina()
        mains = [e for e in p.elementen() if e.tag == "main"]
        self.assertEqual(len(mains), 1, "verwacht precies één <main>")
        main = mains[0]
        ids = [c.attrs.get("id") for c in main.children if c.tag == "section"]
        self.assertEqual(ids, SECTIES)
        broers = main.parent.children
        na_main = broers[broers.index(main) + 1:]
        self.assertIn("footer", [e.tag for e in na_main], "geen <footer> na </main>")

    def test_elke_sectie_heeft_kop_en_inhoud(self):
        main = [e for e in self.pagina().elementen() if e.tag == "main"][0]
        for sectie in [c for c in main.children if c.tag == "section"]:
            sid = sectie.attrs.get("id")
            kop = "h1" if sid == "top" else "h2"
            koppen = [e for e in sectie.iter() if e.tag == kop and e.alle_tekst().strip()]
            self.assertTrue(koppen, f"#{sid} heeft geen <{kop}> met tekst")
            tekst = " ".join(sectie.alle_tekst().split())
            kale = tekst.replace(" ".join(koppen[0].alle_tekst().split()), "", 1).strip()
            self.assertGreaterEqual(len(kale), 150,
                                    f"#{sid} bevat naast de kop nauwelijks tekst: {kale!r}")

    def test_parser_opent_zelfsluitende_gewone_tags(self):
        p = Pagina("<body><div/><p>x</p></body>")
        div = [e for e in p.elementen() if e.tag == "div"][0]
        self.assertIn("p", [c.tag for c in div.children], "<div/> wordt niet als open gezien")
        self.assertTrue(any("<div>" in f for f in p.fouten), p.fouten)
        p = Pagina('<body><svg viewBox="0 0 1 1"><path d="M0 0"/></svg><br/></body>')
        self.assertEqual(p.fouten, [], "zelfsluitend in svg of void-tag gaf een fout")

    def test_geen_dubbele_ids(self):
        ids = [e.attrs["id"] for e in self.pagina().elementen() if e.attrs.get("id")]
        dubbel = [i for i, n in Counter(ids).items() if n > 1]
        self.assertEqual(dubbel, [], f"dubbele id's: {dubbel}")

    def test_nojekyll_in_root(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, ".nojekyll")), ".nojekyll ontbreekt")


class TestLinks(Basis):
    def test_ankers_wijzen_naar_bestaande_ids(self):
        fouten = [f for f in controleer_links(self.index_html()) if not f.startswith("bestand")]
        self.assertEqual(fouten, [], "\n".join(fouten))
        # de belangrijkste doelen moeten ook echt als link voorkomen
        hrefs = {e.attrs.get("href") for e in self.pagina().elementen()}
        for doel in ["#inhoud", "#top", "#waarde", "#werking", "#handleiding",
                     "#voorbeeld", "#installeren", "#vragen", "#download"]:
            self.assertIn(doel, hrefs, f"geen link naar {doel}")

    def test_lokale_bestanden_bestaan(self):
        html = self.index_html()
        fouten = [f for f in controleer_links(html) if f.startswith("bestand")]
        self.assertEqual(fouten, [], "\n".join(fouten))
        self.assertIn('href="assets/site.css"', html)

    def test_linkcontrole_vangt_kapotte_links(self):
        html = ('<!doctype html><html><head><link rel="stylesheet" href="assets/weg.css">'
                '</head><body><a href="#bestaat-niet">x</a><a href="#">leeg</a></body></html>')
        fouten = controleer_links(html)
        self.assertTrue(any("#bestaat-niet" in f for f in fouten), fouten)
        self.assertTrue(any("assets/weg.css" in f for f in fouten), fouten)
        self.assertTrue(any("lege '#'" in f for f in fouten), fouten)


    def test_later_map_telt_mee_zodra_hij_bestaat(self):
        # voorbeeld/ komt in cp08; zodra de map er is, moet elke link erin kloppen.
        html = '<a href="voorbeeld/weg.html">x</a><a href="voorbeeld/er.html">y</a>'
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        self.assertEqual(controleer_links(html, root=tmp), [])
        os.mkdir(os.path.join(tmp, "voorbeeld"))
        open(os.path.join(tmp, "voorbeeld", "er.html"), "w").close()
        self.assertEqual(controleer_links(html, root=tmp),
                         ["bestand ontbreekt: voorbeeld/weg.html"])


class TestGeenPrototype(Basis):
    VERBODEN = ["proto-chrome", "statenrij", 'class="mock', ".mock", "proto-noot",
                "data-state", "?state=", "alleen-lang", "niet-lang"]

    def test_geen_prototype_extras(self):
        teksten = {"index.html": self.index_html(), "assets/site.css": self.site_css()}
        gevonden = [f"{naam}: {s}" for naam, t in teksten.items()
                    for s in self.VERBODEN if s in t]
        self.assertEqual(gevonden, [], "\n".join(gevonden))

    def test_previews_zonder_plaatje_tonen_leeg_blok(self):
        previews = [e for e in self.pagina().elementen() if "preview" in e.classes]
        self.assertTrue(previews, "geen .preview gevonden")
        for pv in previews:
            if any(e.tag == "img" for e in pv.iter()):
                continue
            leeg = [e for e in pv.iter() if "leeg" in e.classes]
            self.assertTrue(leeg, f"preview zonder img en zonder .leeg: {pv.attrs}")
            naam = leeg[0].alle_tekst()
            m = re.search(r"[\w.-]+\.html", naam)
            self.assertIsNotNone(m, f".leeg noemt geen bestandsnaam: {naam!r}")
            hrefs = [e.attrs.get("href") for e in pv.iter() if e.tag == "a"]
            self.assertIn(f"voorbeeld/{m.group(0)}", hrefs,
                          f"preview linkt niet naar voorbeeld/{m.group(0)}")


class TestRelease(Basis):
    def test_releasevelden_hebben_haken_en_geen_verzonnen_waarden(self):
        p = self.pagina()
        velden = [e for e in p.elementen() if e.attrs.get("data-release")]
        soorten = Counter(e.attrs["data-release"] for e in velden)
        self.assertEqual(set(soorten), {"versie", "datum", "grootte"})
        # versie in de topbalk, de downloadkaart en de footer
        self.assertGreaterEqual(soorten["versie"], 3, soorten)
        waarden = {e.alle_tekst().strip() for e in velden if e.attrs["data-release"] == "versie"}
        self.assertEqual(len(waarden), 1, f"versie verschilt per plek: {waarden}")
        for binnen in ("topbalk", "footer"):
            blok = [e for e in p.elementen() if binnen in e.classes][0]
            self.assertTrue([e for e in blok.iter() if e.attrs.get("data-release") == "versie"],
                            f"geen data-release=versie in .{binnen}")
        # zolang er geen releasescript is (cp06), mogen datum en grootte geen feiten verzinnen;
        # daarna vult scripts/release.py ze in en controleren de tests van cp06 de waarden
        if os.path.exists(os.path.join(ROOT, "scripts", "release.py")):
            return
        for e in velden:
            if e.attrs["data-release"] in ("datum", "grootte"):
                self.assertNotRegex(e.alle_tekst(), r"\d", "datum/grootte bevat een verzonnen waarde")


class TestStijl(Basis):
    def test_geen_style_blok_en_een_stylesheet(self):
        p = self.pagina()
        self.assertFalse([e for e in p.elementen() if e.tag == "style"], "<style> in index.html")
        kleur = re.compile(r"#[0-9a-fA-F]{3,8}|rgb|hsl|color|background|var\(--")
        met_kleur = [e.attrs["style"] for e in p.elementen()
                     if e.attrs.get("style") and kleur.search(e.attrs["style"])]
        self.assertEqual(met_kleur, [], f"style-attributen met kleur: {met_kleur}")
        sheets = [e.attrs.get("href", "") for e in p.elementen()
                  if e.tag == "link" and "stylesheet" in (e.attrs.get("rel") or "").split()]
        lokaal = [h for h in sheets if not h.startswith("https://fonts.googleapis.com/")]
        self.assertEqual(lokaal, ["assets/site.css"])

    def test_root_tokens_gelijk_aan_design(self):
        verwacht = design_tokens()
        self.assertTrue(verwacht, "geen :root-blok in design.md gevonden")
        self.assertEqual(verwacht.get("--accent"), "#FFCE1F")
        self.assertEqual(css_tokens(self.site_css()), verwacht)

    def test_tokens_dubbele_root_met_andere_waarde_faalt(self):
        with self.assertRaises(ValueError):
            css_tokens(":root{--accent:#FFCE1F}\nbody{}\n:root{--accent:#000}")
        self.assertEqual(css_tokens(":root{--a:1}:root{--a:1;--b:2}"), {"--a": "1", "--b": "2"})
        # site.css zelf mag geen tweede :root met afwijkende waarden hebben
        css_tokens(self.site_css())


def vrije_poort():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestServer(unittest.TestCase):
    def setUp(self):
        self.poort = vrije_poort()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.poort), "--bind", "127.0.0.1"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        eind = time.time() + 10
        while time.time() < eind:
            try:
                socket.create_connection(("127.0.0.1", self.poort), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        self.fail("http.server kwam niet op")

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)

    def haal(self, pad):
        try:
            return urllib.request.urlopen(f"http://127.0.0.1:{self.poort}{pad}", timeout=5)
        except urllib.error.HTTPError as e:
            return e

    def test_server_levert_pagina_en_css(self):
        titel = re.search(r"<title>(.*?)</title>", lees(PROTOTYPE), flags=re.S).group(1).strip()
        r = self.haal("/")
        self.assertEqual(r.status, 200)
        body = r.read().decode("utf-8")
        self.assertIn(f"<title>{titel}</title>", body, "/ toont niet de sitepagina")
        r = self.haal("/assets/site.css")
        self.assertEqual(r.status, 200, "/assets/site.css niet gevonden")
        self.assertTrue(r.headers.get("Content-Type", "").startswith("text/css"))


if __name__ == "__main__":
    unittest.main()
