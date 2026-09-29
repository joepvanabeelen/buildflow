"""cp08: de voorbeeldrun staat schoon in voorbeeld/, en scripts/sanitize_demo.py maakt hem schoon.

Contract voor het script (zoals deze tests het aanroepen):

    python3 scripts/sanitize_demo.py <invoermap> <uitvoermap>

De invoermap bevat de ruwe kopieën uit één run: viewer-brief.html, viewer-design.html,
viewer-plan.html, cp01.html en final.html zoals bf.py ze schrijft (viewer-sjabloon met
`window.BF = {...};`), plus de prototypepagina op het pad relatief aan de projectroot
waar design.prototype naar wijst (hier docs/design/prototype/index.html). Het script schrijft
alleen in de uitvoermap. Projectpaden worden ~/demo/<project>, sessie-id's en e-mailadressen
worden vervangen, en rel_root + design.prototype wijst daarna naar een bestand in de uitvoermap.

De scripttests draaien in tijdelijke mappen met een expliciete cwd en raken de repo niet aan.
Een los browsercriterium (geen consolefouten op de vijf pagina's, prototype laadt in
viewer-design.html) is niet zonder browser te toetsen en hoort bij de review/UI-controle.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from tests import check_privacy
from tests.check_site import INDEX, ROOT, Pagina, controleer_links, lees

SCRIPT = os.path.join(ROOT, "scripts", "sanitize_demo.py")
VOORBEELD = os.path.join(ROOT, "voorbeeld")
VIJF = ["viewer-brief.html", "viewer-design.html", "viewer-plan.html", "cp01.html", "final.html"]
VIEWERS = {"viewer-brief.html": None, "viewer-design.html": None, "viewer-plan.html": None,
           "cp01.html": "cp01", "final.html": "final"}

UUID_A = "3f2b8c1e-1234-4abc-9def-0123456789ab"
UUID_B = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
EMAIL = "iemand@voorbeeld.nl"
ROOT_USERS = "/Users/iemand/scratch/demo-app"
ROOT_TMP = "/private/tmp/claude-501/abc123/scratchpad/demo-app"
PROTO_REL = "docs/design/prototype/index.html"
PROTO_MERK = "PROTOTYPE-DEMO-KNOP-7f3a"

SCHUIF = ("rel_root", "prototype", "design_md", "design_ref")


# ---------------------------------------------------------------- helpers

def bf_delen(html):
    """Splitst een viewerbestand in (tekst voor de JSON, data, tekst na de JSON)."""
    m = re.search(r"window\.BF\s*=\s*", html)
    if not m:
        raise AssertionError("geen window.BF in het bestand")
    data, eind = json.JSONDecoder().raw_decode(html, m.end())
    return html[:m.end()], data, html[eind:]


def maak_viewer(data, titel="Demo knop"):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return ("<!doctype html>\n<html lang=\"nl\"><head><meta charset=\"utf-8\">\n"
            f"<title>{titel} · buildflow</title></head>\n<body>\n"
            "<p>Kosten $0.42 · actief 12m 30s · 17 tests</p>\n"
            "<script>\nwindow.BF = " + blob + ";\nlet D = window.BF;\n</script>\n</body></html>\n")


def nep_data(project_root, focus):
    return {
        "slug": "demo-knop", "title": "Demo knop", "lang": "nl", "focus": focus,
        "rel_root": "../../../" if focus else "../../",
        "project": {"root": project_root, "branch": "buildflow/demo-knop",
                    "prototype": PROTO_REL, "design_ref": "docs/design/design.md",
                    "dev_url": "http://localhost:8765/"},
        "sessions": [UUID_A],
        "stages": {"brief": {"file": project_root + "/.buildflow/demo-knop/brief.md"},
                   "design": {"status": "approved", "prototype": PROTO_REL,
                              "design_md": "docs/design/design.md",
                              "states": ["standaard", "leeg"]}},
        "brief_text": (f"Zie {project_root}/.buildflow/demo-knop/brief.md en mail {EMAIL}. "
                       f"sessie [{UUID_A}] en [{UUID_B}] klaar."),
        "checkpoints": [{"id": "cp01", "commit": "abc1234def", "author": f"Iemand <{EMAIL}>",
                         "gates": {"behavior": {"attempts": [
                             {"metrics": {"tests_total": 17, "tests_passed": 17}}]}}}],
        "cost": {"sessions": [UUID_A, UUID_B],
                 "transcript_files": [f"/Users/iemand/.claude/projects/-x/{UUID_A}.jsonl"],
                 "totals": {"usd": 0.42, "total_tokens": 123456},
                 "time": {"active_seconds": 750}},
        "summary_text": "Kosten $0.42, actief 12m 30s, 17 tests",
        "reports": {"cp01": {"html": "reports/cp01.html"}, "final": {"html": "reports/final.html"}},
    }


def schrijf(pad, tekst):
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "w", encoding="utf-8") as f:
        f.write(tekst)


def prive(tekst):
    b = tekst.encode("utf-8")
    return any(p.search(b) for _, p in check_privacy.PATRONEN)


def momentopname(map_):
    uit = {}
    for wortel, _, namen in os.walk(map_):
        for naam in namen:
            pad = os.path.join(wortel, naam)
            with open(pad, "rb") as f:
                uit[os.path.relpath(pad, map_)] = hashlib.sha256(f.read()).hexdigest()
    return uit


def prototype_doel(html_pad):
    """Het bestand waar de viewer het prototype vandaan laadt: rel_root + design.prototype."""
    _, d, _ = bf_delen(lees(html_pad))
    proto = ((d.get("stages") or {}).get("design") or {}).get("prototype") \
        or (d.get("project") or {}).get("prototype")
    if not proto:
        raise AssertionError(f"{html_pad}: geen design.prototype in window.BF")
    if re.match(r"^(https?:|/)", proto):
        raise AssertionError(f"prototype is geen relatief pad: {proto}")
    rel = (d.get("rel_root") or "") + proto
    return os.path.normpath(os.path.join(os.path.dirname(html_pad), rel.split("?")[0]))


def binnen(pad, map_):
    return os.path.commonpath([os.path.abspath(pad), os.path.abspath(map_)]) == os.path.abspath(map_)


# ---------------------------------------------------------------- het script, op nepinvoer

class Sanitize(unittest.TestCase):
    project_root = ROOT_USERS

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.invoer = os.path.join(self.tmp, "ruw")
        self.uitvoer = os.path.join(self.tmp, "voorbeeld")
        self.origineel = {}
        for naam, focus in VIEWERS.items():
            html = maak_viewer(nep_data(self.project_root, focus))
            self.origineel[naam] = html
            schrijf(os.path.join(self.invoer, naam), html)
        schrijf(os.path.join(self.invoer, *PROTO_REL.split("/")),
                f"<!doctype html><title>proto</title><p>{PROTO_MERK}</p>\n"
                f"<!-- gemaakt in {self.project_root} -->\n")

    def draai(self, *args):
        self.assertTrue(os.path.isfile(SCRIPT), "scripts/sanitize_demo.py ontbreekt")
        return subprocess.run([sys.executable, SCRIPT, *args], cwd=self.tmp,
                              capture_output=True, text=True, timeout=60)

    def draai_ok(self):
        r = self.draai(self.invoer, self.uitvoer)
        self.assertEqual(r.returncode, 0, f"script faalde:\n{r.stdout}\n{r.stderr}")
        return r

    def uit(self, naam):
        pad = os.path.join(self.uitvoer, naam)
        self.assertTrue(os.path.isfile(pad), f"{naam} niet in de uitvoermap")
        return lees(pad)

    def test_projectpaden_worden_demo_pad_en_json_blijft_geldig(self):
        self.draai_ok()
        for naam in VIJF:
            with self.subTest(naam=naam):
                html = self.uit(naam)
                self.assertNotIn("/Users/", html)
                self.assertNotIn("/private/tmp", html)
                _, d, _ = bf_delen(html)  # faalt als de ingebedde JSON kapot is
                self.assertEqual(d["project"]["root"], "~/demo/demo-app")
                self.assertEqual(d["stages"]["brief"]["file"],
                                 "~/demo/demo-app/.buildflow/demo-knop/brief.md")
                self.assertIn("~/demo/demo-app/.buildflow/demo-knop/brief.md", d["brief_text"])

    def test_sessie_ids_en_emailadressen_vervangen_en_consequent(self):
        self.draai_ok()
        for naam in VIJF:
            with self.subTest(naam=naam):
                html = self.uit(naam)
                self.assertNotIn(UUID_A, html)
                self.assertNotIn(UUID_B, html)
                self.assertNotIn(EMAIL, html)
                meldingen = check_privacy.scan_bestand(os.path.join(self.uitvoer, naam),
                                                       root=self.uitvoer)
                self.assertEqual(meldingen, [], "\n".join(meldingen))
                _, d, _ = bf_delen(html)
                a1, a2, b = d["sessions"][0], d["cost"]["sessions"][0], d["cost"]["sessions"][1]
                m = re.search(r"sessie \[(.*?)\] en \[(.*?)\] klaar", d["brief_text"])
                self.assertIsNotNone(m, d["brief_text"])
                self.assertEqual({a1, a2, m.group(1)}, {a1},
                                 "dezelfde sessie-id kreeg verschillende vervangingen")
                self.assertEqual(m.group(2), b)
                self.assertNotEqual(a1, b, "twee verschillende sessie-id's vielen samen")
                self.assertTrue(a1 and b, "sessie-id vervangen door een lege tekst")

    def test_prototypelink_wijst_naar_meegekopieerd_bestand(self):
        self.draai_ok()
        doel = prototype_doel(os.path.join(self.uitvoer, "viewer-design.html"))
        self.assertTrue(binnen(doel, self.uitvoer),
                        f"prototype wijst buiten de uitvoermap: {doel}")
        self.assertTrue(os.path.isfile(doel), f"prototype niet meegekopieerd: {doel}")
        self.assertIn(PROTO_MERK, lees(doel))

    def test_niets_persoonlijks_in_de_hele_uitvoermap(self):
        self.draai_ok()
        meldingen = []
        for rel in momentopname(self.uitvoer):
            meldingen += check_privacy.scan_bestand(os.path.join(self.uitvoer, rel),
                                                    root=self.uitvoer)
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_bedragen_tijden_en_testaantallen_ongemoeid(self):
        self.draai_ok()
        for naam in VIJF:
            with self.subTest(naam=naam):
                html = self.uit(naam)
                for stuk in ("$0.42", "12m 30s", "17 tests"):
                    self.assertIn(stuk, html)
                voor, d, na = bf_delen(html)
                o_voor, o, o_na = bf_delen(self.origineel[naam])
                self.assertEqual(voor, o_voor, "tekst voor window.BF is veranderd")
                self.assertEqual(na, o_na, "tekst na window.BF is veranderd")
                self.assertEqual(d["cost"]["totals"], o["cost"]["totals"])
                self.assertEqual(d["cost"]["time"], o["cost"]["time"])
                self.assertEqual(d["checkpoints"][0]["gates"], o["checkpoints"][0]["gates"])
                self.vergelijk(o, d, "BF")

    def vergelijk(self, orig, nieuw, pad):
        """Alles wat niets persoonlijks bevat en geen link is, blijft exact gelijk."""
        if isinstance(orig, dict):
            self.assertIsInstance(nieuw, dict, pad)
            self.assertEqual(sorted(orig), sorted(nieuw), f"sleutels anders bij {pad}")
            for k in orig:
                if k in SCHUIF:
                    continue
                self.vergelijk(orig[k], nieuw[k], f"{pad}.{k}")
        elif isinstance(orig, list):
            self.assertIsInstance(nieuw, list, pad)
            self.assertEqual(len(orig), len(nieuw), f"lengte anders bij {pad}")
            for i, (a, b) in enumerate(zip(orig, nieuw)):
                self.vergelijk(a, b, f"{pad}[{i}]")
        elif isinstance(orig, str) and prive(orig):
            return
        else:
            self.assertEqual(orig, nieuw, f"waarde veranderd bij {pad}")

    def test_ontbrekende_invoermap_faalt_en_schrijft_niets(self):
        weg = os.path.join(self.tmp, "bestaat-niet")
        r = self.draai(weg, self.uitvoer)
        self.assertNotEqual(r.returncode, 0, "script slaagde zonder invoermap")
        self.assertFalse(os.path.exists(self.uitvoer), "uitvoermap toch aangemaakt")
        self.assertIn("bestaat-niet", r.stdout + r.stderr, "foutmelding noemt de map niet")

    def test_ontbrekende_invoermap_laat_bestaande_uitvoer_staan(self):
        schrijf(os.path.join(self.uitvoer, "oud.html"), "oud\n")
        voor = momentopname(self.uitvoer)
        r = self.draai(os.path.join(self.tmp, "bestaat-niet"), self.uitvoer)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(momentopname(self.uitvoer), voor, "uitvoermap is gewijzigd")


class SanitizePrivateTmp(Sanitize):
    """Zelfde controles met het demoproject in de scratchpad (/private/tmp/...)."""
    project_root = ROOT_TMP


# ---------------------------------------------------------------- de echte voorbeeld/-map

class VoorbeeldMap(unittest.TestCase):
    def pad(self, naam):
        self.assertTrue(os.path.isdir(VOORBEELD), "voorbeeld/ bestaat nog niet")
        p = os.path.join(VOORBEELD, naam)
        self.assertTrue(os.path.isfile(p), f"voorbeeld/{naam} ontbreekt")
        return p

    def test_vijf_bestanden_en_prototype(self):
        for naam in VIJF:
            self.pad(naam)
        doel = prototype_doel(self.pad("viewer-design.html"))
        self.assertTrue(binnen(doel, VOORBEELD), f"prototype wijst buiten voorbeeld/: {doel}")
        self.assertTrue(os.path.isfile(doel), f"prototypepagina ontbreekt: {doel}")

    def test_bestanden_komen_uit_een_run_van_bf(self):
        slugs = set()
        for naam, focus in VIEWERS.items():
            with self.subTest(naam=naam):
                html = lees(self.pad(naam))
                self.assertRegex(html, r"<title>[^<]* · buildflow</title>",
                                 "geen buildflow-viewertitel")
                _, d, _ = bf_delen(html)
                for k in ("slug", "title", "project", "stages", "checkpoints"):
                    self.assertIn(k, d, f"window.BF mist {k}")
                self.assertEqual(d.get("focus"), focus)
                slugs.add(d["slug"])
        self.assertEqual(len(slugs), 1, f"bestanden uit verschillende runs: {slugs}")
        _, d, _ = bf_delen(lees(self.pad("final.html")))
        self.assertIn("final", d.get("reports") or {}, "final.html is geen eindrapport")
        self.assertIn("cp01", d.get("reports") or {}, "eindrapport kent cp01 niet")

    def test_privacyscan_dekt_voorbeeld(self):
        for naam in VIJF:
            self.pad(naam)
        bestanden = check_privacy.gepubliceerde_bestanden(ROOT)
        for naam in VIJF:
            self.assertIn(f"voorbeeld/{naam}", bestanden, "voorbeeld/ zit niet in de scan")
        meldingen = []
        for p in bestanden:
            if p.startswith("voorbeeld/"):
                meldingen += check_privacy.scan_bestand(os.path.join(ROOT, p))
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_alle_lokale_links_bestaan(self):
        self.assertTrue(os.path.isdir(VOORBEELD), "voorbeeld/ bestaat nog niet; "
                        "de linkcontrole zou de previewlinks nu overslaan")
        fouten = [f"index.html: {f}" for f in controleer_links(lees(INDEX), root=ROOT)]
        for wortel, _, namen in os.walk(VOORBEELD):
            for naam in namen:
                if naam.endswith(".html"):
                    pad = os.path.join(wortel, naam)
                    fouten += [f"{os.path.relpath(pad, ROOT)}: {f}"
                               for f in controleer_links(lees(pad), root=wortel)]
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_kosten_bij_voorbeeld_eerlijk(self):
        _, d, _ = bf_delen(lees(self.pad("final.html")))
        usd = ((d.get("cost") or {}).get("totals") or {}).get("usd")
        main = [e for e in Pagina(lees(INDEX)).elementen() if e.attrs.get("id") == "voorbeeld"]
        self.assertEqual(len(main), 1, "geen #voorbeeld op de pagina")
        tekst = " ".join(main[0].alle_tekst().split())
        bedragen = re.findall(r"[$€]\s?(\d[\d.,]*)", tekst)
        if not usd:
            self.assertEqual(bedragen, [], f"bedrag bij #voorbeeld terwijl de kosten "
                                           f"niet gemeten zijn: {bedragen}")
            zinnen = re.split(r"(?<=[.!?])\s+", tekst)
            self.assertTrue(any("kosten" in z.lower() and re.search(
                r"niet gemeten|geen|nul|ontbre", z.lower()) for z in zinnen),
                "#voorbeeld zegt niet dat de kosten niet gemeten zijn")
        else:
            gemeten = set()

            def verzamel(x):
                if isinstance(x, dict):
                    for k, v in x.items():
                        if k == "usd" and isinstance(v, (int, float)):
                            gemeten.add(round(v, 2))
                        verzamel(v)
                elif isinstance(x, list):
                    for v in x:
                        verzamel(v)
            verzamel(d.get("cost"))
            for b in bedragen:
                waarde = round(float(b.replace(",", "")), 2)
                self.assertIn(waarde, gemeten, f"bedrag ${b} komt niet uit final.html")


def vrije_poort():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class VoorbeeldServer(unittest.TestCase):
    def setUp(self):
        self.poort = vrije_poort()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.poort), "--bind", "127.0.0.1"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.proc.wait, 5)
        self.addCleanup(self.proc.terminate)
        eind = time.time() + 10
        while time.time() < eind:
            try:
                socket.create_connection(("127.0.0.1", self.poort), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        self.fail("http.server kwam niet op")

    def haal(self, pad):
        try:
            return urllib.request.urlopen(f"http://127.0.0.1:{self.poort}{pad}", timeout=5)
        except urllib.error.HTTPError as e:
            return e

    def test_vijf_pagina_en_prototype_geven_200(self):
        self.assertTrue(os.path.isdir(VOORBEELD), "voorbeeld/ bestaat nog niet")
        paden = [f"/voorbeeld/{n}" for n in VIJF]
        design = os.path.join(VOORBEELD, "viewer-design.html")
        if os.path.isfile(design):
            doel = prototype_doel(design)
            paden.append("/" + os.path.relpath(doel, ROOT).replace(os.sep, "/"))
        for pad in paden:
            with self.subTest(pad=pad):
                r = self.haal(pad)
                self.assertEqual(r.status, 200, pad)
                self.assertIn("text/html", r.headers.get("Content-Type", ""))


if __name__ == "__main__":
    unittest.main()
