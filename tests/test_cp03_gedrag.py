"""cp03: kopieerknoppen, actieve navlink en printen (statische controles).

Het gedrag in de browser zelf controleert de UI-gate; hier gaat het om wat er in de
bestanden staat: één extern script, geen dode knoppen zonder JavaScript, de teksten
uit design.md en de CSS voor alle standen.
"""
import os
import re
import shutil
import tempfile
import unittest

from tests.check_site import CSS, INDEX, ROOT, Pagina, controleer_links, lees

SITE_JS = os.path.join(ROOT, "assets", "site.js")

TEKSTEN = [
    "Kopieer",
    "Gekopieerd ✓",
    "Gekopieerd naar je klembord",
    "Kopiëren lukte niet. De tekst is geselecteerd, druk op Cmd+C",
    "navigator.clipboard",
    "beforeprint",
    "afterprint",
]


def css_regels(tekst):
    """Geeft [(media, selector, body)] voor alle regels, met @media-context ('' buiten)."""
    tekst = re.sub(r"/\*.*?\*/", "", tekst, flags=re.S)
    regels = []

    def lees_blok(i, media):
        while i < len(tekst):
            if tekst[i] == "}":
                return i + 1
            open_ = tekst.find("{", i)
            sluit = tekst.find("}", i)
            if open_ == -1 or (sluit != -1 and sluit < open_):
                if sluit == -1:
                    return len(tekst)
                return sluit + 1
            kop = " ".join(tekst[i:open_].split())
            if kop.startswith("@media") or kop.startswith("@supports"):
                i = lees_blok(open_ + 1, " ".join([media, kop]).strip())
                continue
            diepte, j = 1, open_ + 1
            while j < len(tekst) and diepte:
                diepte += {"{": 1, "}": -1}.get(tekst[j], 0)
                j += 1
            regels.append((media, kop, tekst[open_ + 1:j - 1]))
            i = j
        return i

    lees_blok(0, "")
    return regels


def selectors(regels, media_filter=None):
    uit = []
    for media, kop, body in regels:
        if media_filter is not None and not media_filter(media):
            continue
        for s in kop.split(","):
            uit.append((" ".join(s.split()), body))
    return uit


class Basis(unittest.TestCase):
    def pagina(self):
        self.assertTrue(os.path.isfile(INDEX), "index.html ontbreekt")
        return Pagina(lees(INDEX))

    def regels(self):
        self.assertTrue(os.path.isfile(CSS), "assets/site.css ontbreekt")
        return css_regels(lees(CSS))


class TestScript(Basis):
    def test_laadt_site_js_met_defer_zonder_inline_script(self):
        p = self.pagina()
        scripts = [e for e in p.elementen() if e.tag == "script"]
        # JSON-LD of andere data-blokken tellen niet als script
        scripts = [s for s in scripts
                   if (s.attrs.get("type") or "text/javascript").lower()
                   in ("text/javascript", "module", "application/javascript")]
        self.assertEqual(len(scripts), 1,
                         f"verwacht precies één <script>, gevonden: {len(scripts)}")
        s = scripts[0]
        self.assertEqual(s.attrs.get("src"), "assets/site.js",
                         f"script heeft src={s.attrs.get('src')!r}")
        self.assertIn("defer", s.attrs, "<script src=\"assets/site.js\"> mist defer")
        self.assertEqual(s.alle_tekst().strip(), "", "het script-element heeft inhoud")

    def test_geen_on_attributen(self):
        fout = [f"<{e.tag} {a}>" for e in self.pagina().elementen()
                for a in e.attrs if a.lower().startswith("on")]
        self.assertEqual(fout, [], "inline event-handlers: " + ", ".join(fout))

    def test_site_js_bevat_teksten_en_geen_standenkiezer(self):
        self.assertTrue(os.path.isfile(SITE_JS), "assets/site.js ontbreekt")
        js = lees(SITE_JS)
        ontbreekt = [t for t in TEKSTEN if t not in js]
        self.assertEqual(ontbreekt, [], f"niet in site.js: {ontbreekt}")
        self.assertNotIn("statenrij", js, "site.js bevat de standenkiezer (statenrij)")
        self.assertIsNone(
            re.search(r"""(get|has)\(\s*["']state["']\s*\)|[?&]state=""", js),
            "site.js leest 'state' uit de URL; dat hoort alleen bij het prototype")

    def test_site_js_wordt_gevonden_door_de_bestandscontrole(self):
        self.assertEqual([f for f in controleer_links(lees(INDEX))
                          if "site.js" in f], [])
        self.assertTrue(os.path.isfile(SITE_JS), "assets/site.js ontbreekt")

    def test_bestandscontrole_faalt_als_site_js_ontbreekt(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        html = '<script src="assets/site.js" defer></script>'
        self.assertEqual(controleer_links(html, root=tmp),
                         ["bestand ontbreekt: assets/site.js"])


class TestZonderJs(Basis):
    def test_geen_kopieerknop_in_html(self):
        html = lees(INDEX)
        self.assertIsNone(re.search(r'class="[^"]*\bkopieer\b', html),
                          "index.html bevat al een .kopieer; die hoort uit site.js te komen")
        p = self.pagina()
        codes = [e for e in p.elementen() if "code" in e.classes]
        self.assertTrue(codes, "geen .code-blokken gevonden")
        knoppen = [c for c in codes for e in c.iter() if e.tag == "button"]
        self.assertEqual(knoppen, [], "er staat een <button> in een .code-blok")

    def test_toast_met_role_status_en_aria_live(self):
        toasts = [e for e in self.pagina().elementen() if "toast" in e.classes]
        self.assertEqual(len(toasts), 1, f"verwacht één .toast, gevonden: {len(toasts)}")
        t = toasts[0]
        self.assertEqual(t.attrs.get("role"), "status")
        self.assertEqual(t.attrs.get("aria-live"), "polite")


class TestFases(Basis):
    def test_fases_hebben_ids_en_er_is_een_link_naar_een_fase(self):
        p = self.pagina()
        fases = [e for e in p.elementen() if e.tag == "details" and "fase" in e.classes]
        self.assertTrue(fases, "geen <details class=\"fase\"> gevonden")
        zonder = [e.attrs.get("id") for e in fases
                  if not (e.attrs.get("id") or "").startswith("fase-")]
        self.assertEqual(zonder, [], f"fase zonder id fase-*: {zonder}")
        ids = {e.attrs["id"] for e in fases}
        self.assertIn("fase-bouwen", ids)
        links = [e.attrs.get("href") for e in p.elementen()
                 if e.tag == "a" and (e.attrs.get("href") or "").lstrip("#") in ids
                 and (e.attrs.get("href") or "").startswith("#")]
        self.assertTrue(links, "geen interne link naar een fase (#fase-...)")


    def test_kapotte_hash_breekt_het_script_niet(self):
        js = lees(SITE_JS)
        self.assertIsNone(
            re.search(r"(?<!try \{ id = )decodeURIComponent\(", js),
            "decodeURIComponent staat buiten een try; #fase-%zz gooit dan een URIError")


class TestCss(Basis):
    def test_selectors_voor_kopieer_toast_en_nav(self):
        alle = {s for s, _ in selectors(self.regels())}
        for nodig in [".kopieer", ".gekopieerd", ".toast.fout", ".nav a.actief"]:
            gevonden = any(re.search(re.escape(nodig) + r"(?![\w-])", s) for s in alle)
            self.assertTrue(gevonden, f"geen CSS-regel voor {nodig}")

    def test_print_verbergt_kopieer_en_toast(self):
        verborgen = set()
        for s, body in selectors(self.regels(), lambda m: "print" in m):
            if re.search(r"display\s*:\s*none", body):
                verborgen.add(s)
        for nodig in [".kopieer", ".toast"]:
            self.assertIn(nodig, verborgen, f"@media print verbergt {nodig} niet")

    def test_smal_verbergt_succestoast_maar_niet_de_fout(self):
        smal = selectors(self.regels(),
                         lambda m: re.search(r"max-width\s*:\s*640px", m) is not None)
        verbergend = [s for s, body in smal
                      if re.search(r"\.toast(?![\w-])", s)
                      and (re.search(r"clip\s*:", body) or re.search(r"width\s*:\s*1px", body))]
        self.assertTrue(verbergend, "geen regel onder 640px die de succestoast visueel verbergt")
        for s in verbergend:
            self.assertIn(":not(.fout)", s,
                          f"{s} verbergt onder 640px ook .toast.fout")
