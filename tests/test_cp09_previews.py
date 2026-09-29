"""cp09: echte screenshots van de voorbeeldrun in de previews, en een kloppend linkvoorbeeld.

De afmetingen komen uit tests/check_site.py: png_afmetingen. Die lezer wordt hieronder
apart getoetst (PngLezer), ook op kapotte en onechte PNG's.

Deze tests kunnen niet zien wát er op een screenshot staat. Een verkeerd plaatje met de
goede naam en maat komt er dus doorheen. Dat controleert de UI-gate, samen met wat alleen
in de browser of met het oog te zien is:
- elk screenshot toont de pagina waar zijn link naartoe gaat (viewer-brief.png de viewer
  bij de briefstop, final.png het eindrapport, enzovoort), en de alt beschrijft wat erop
  staat;
- de plaatjes in #voorbeeld en in de open fases zijn scherp en in verhouding, op desktop
  en op 640px of smaller;
- op geen screenshot staat zichtbaar een persoonlijk pad of e-mailadres;
- de voettekst op og.png is leesbaar en het woordmerk heeft de goede spatiëring;
- laadt een preview-plaatje niet (404), dan vervangt assets/site.js het door het
  .leeg-blok met de bestandsnaam, en de link blijft werken.
"""
import os
import re
import struct
import tempfile
import unittest
import zlib

from tests import check_privacy, check_site
from tests.check_site import INDEX, ROOT, Pagina, lees

SITE_URL = "https://joepvanabeelen.github.io/buildflow-website/"
PREVIEWS = os.path.join(ROOT, "assets", "previews")
SCREENSHOTS = ["viewer-brief", "viewer-design", "viewer-plan", "cp01", "final"]
# De screenshots zijn op 1x gemaakt (Playwright, viewport 1200x800). Op 2x zouden ze
# ruim over het maximum hieronder gaan.
SCHAAL = 1
SCREENSHOT_MAAT = (1200 * SCHAAL, 800 * SCHAAL)
OG_MAAT = (1200, 630)
# De schijf is bijna vol en de pagina moet licht blijven: elk plaatje blijft hieronder.
MAX_BYTES = 250 * 1024
# Een echte screenshot van een pagina met tekst is nooit zo klein; kleiner wijst op een
# leeg of effen plaatje.
MIN_BYTES = 8 * 1024
FASES = {"fase-brief": "viewer-brief", "fase-design": "viewer-design",
         "fase-plan": "viewer-plan", "fase-bouwen": "cp01", "fase-review": "final"}

PNG_SIGNATUUR = b"\x89PNG\r\n\x1a\n"


def png_header(pad):
    """(breedte, hoogte) via de gedeelde lezer in check_site."""
    return check_site.png_afmetingen(pad)


def maak_png(chunks=()):
    """Een geldige 1x1-PNG met extra chunks (soort, data) vóór IDAT."""
    def chunk(soort, data):
        return (struct.pack(">I", len(data)) + soort + data
                + struct.pack(">I", zlib.crc32(soort + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    uit = PNG_SIGNATUUR + chunk(b"IHDR", ihdr)
    for soort, data in chunks:
        uit += chunk(soort, data)
    return uit + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b"")


def lokaal_pad(src):
    if src.startswith(SITE_URL):
        src = src[len(SITE_URL):]
    return os.path.join(ROOT, re.split(r"[?#]", src)[0].lstrip("/"))


class Bestanden(unittest.TestCase):
    def test_previews_bevat_de_vijf_screenshots_en_og_als_geldige_png(self):
        for naam in SCREENSHOTS + ["og"]:
            pad = os.path.join(PREVIEWS, naam + ".png")
            with self.subTest(naam=naam):
                self.assertTrue(os.path.isfile(pad), f"assets/previews/{naam}.png ontbreekt")
                png_header(pad)

    def test_screenshots_zijn_1200x800_en_og_is_1200x630(self):
        for naam in SCREENSHOTS:
            pad = os.path.join(PREVIEWS, naam + ".png")
            with self.subTest(naam=naam):
                self.assertTrue(os.path.isfile(pad), f"assets/previews/{naam}.png ontbreekt")
                self.assertEqual(png_header(pad), SCREENSHOT_MAAT)
        self.assertEqual(png_header(os.path.join(PREVIEWS, "og.png")), OG_MAAT)

    def test_screenshots_hebben_een_redelijke_bestandsgrootte(self):
        for naam in SCREENSHOTS + ["og"]:
            pad = os.path.join(PREVIEWS, naam + ".png")
            with self.subTest(naam=naam):
                self.assertTrue(os.path.isfile(pad), f"assets/previews/{naam}.png ontbreekt")
                grootte = os.path.getsize(pad)
                self.assertLess(grootte, MAX_BYTES, f"{naam}.png is {grootte} bytes")
                self.assertGreater(grootte, MIN_BYTES,
                                   f"{naam}.png is {grootte} bytes, lijkt leeg")


class Pagina_(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = lees(INDEX)
        cls.pagina = Pagina(cls.html)
        cls.previews = [e for e in cls.pagina.elementen()
                        if e.tag == "a" and "preview" in e.classes]

    def imgs(self, el):
        return [e for e in el.iter() if e.tag == "img"]

    def sectie(self, id_):
        gevonden = [e for e in self.pagina.elementen() if e.attrs.get("id") == id_]
        self.assertEqual(len(gevonden), 1, f"verwacht precies één #{id_}")
        return gevonden[0]

    def test_er_zijn_previews(self):
        self.assertGreaterEqual(len(self.previews), 10)

    def test_elke_preview_heeft_precies_een_img_in_assets_previews(self):
        for p in self.previews:
            with self.subTest(href=p.attrs.get("href")):
                imgs = self.imgs(p)
                self.assertEqual(len(imgs), 1, "preview zonder (of met meer dan één) <img>")
                self.assertRegex(imgs[0].attrs.get("src", ""),
                                 r"^assets/previews/[a-z0-9-]+\.png$")

    def test_elke_preview_linkt_naar_het_bestand_van_zijn_screenshot(self):
        for p in self.previews:
            href = p.attrs.get("href", "")
            with self.subTest(href=href):
                m = re.fullmatch(r"voorbeeld/([a-z0-9-]+)\.html", href)
                self.assertTrue(m, f"preview linkt niet naar een voorbeeld/-bestand: {href}")
                self.assertTrue(os.path.isfile(os.path.join(ROOT, href)), href)
                imgs = self.imgs(p)
                self.assertEqual(len(imgs), 1)
                self.assertEqual(imgs[0].attrs.get("src"),
                                 f"assets/previews/{m.group(1)}.png")

    def test_voorbeeldsectie_toont_alle_vijf_screenshots(self):
        sectie = self.sectie("voorbeeld")
        srcs = {i.attrs.get("src") for p in sectie.iter()
                if p.tag == "a" and "preview" in p.classes for i in self.imgs(p)}
        self.assertEqual(srcs, {f"assets/previews/{n}.png" for n in SCREENSHOTS})

    def test_elke_fase_toont_het_screenshot_van_zijn_stop(self):
        for fase, naam in FASES.items():
            with self.subTest(fase=fase):
                el = self.sectie(fase)
                srcs = [i.attrs.get("src") for p in el.iter()
                        if p.tag == "a" and "preview" in p.classes for i in self.imgs(p)]
                self.assertEqual(srcs, [f"assets/previews/{naam}.png"])

    def test_img_heeft_nederlandse_alt_kloppende_maat_en_lazy_loading(self):
        for p in self.previews:
            imgs = self.imgs(p)
            with self.subTest(href=p.attrs.get("href")):
                self.assertEqual(len(imgs), 1)
                img = imgs[0]
                src = img.attrs.get("src", "")
                alt = (img.attrs.get("alt") or "").strip()
                stam = os.path.splitext(os.path.basename(src))[0]
                self.assertGreaterEqual(len(alt.split()), 4, f"alt te kort: {alt!r}")
                self.assertNotRegex(alt.lower(), r"\.(png|html)\b|screenshot van " + re.escape(stam))
                self.assertNotEqual(alt.lower(), stam.lower())
                self.assertNotRegex(alt.lower(), r"\b(the|of|with|and)\b",
                                    f"alt lijkt Engels: {alt!r}")
                self.assertEqual(img.attrs.get("loading"), "lazy")
                pad = lokaal_pad(src)
                self.assertTrue(os.path.isfile(pad), f"{src} bestaat niet")
                breedte, hoogte = png_header(pad)
                self.assertEqual(img.attrs.get("width"), str(breedte))
                self.assertEqual(img.attrs.get("height"), str(hoogte))

    def test_alt_herhaalt_de_linktitel_niet(self):
        for p in self.previews:
            titel = " ".join(b.alle_tekst() for b in p.iter() if b.tag == "b").strip()
            with self.subTest(href=p.attrs.get("href")):
                self.assertTrue(titel, "preview zonder titel in <b>")
                alt = " ".join((self.imgs(p)[0].attrs.get("alt") or "").split())
                self.assertNotIn(titel.lower(), alt.lower(),
                                 "de alt herhaalt de linktitel in plaats van het plaatje te beschrijven")

    def alts(self, naam):
        return {i.attrs.get("alt", "") for p in self.previews for i in self.imgs(p)
                if i.attrs.get("src") == f"assets/previews/{naam}.png"}

    def test_alt_van_final_zegt_dat_de_run_op_review_wacht(self):
        # Op final.png staat 'Wacht op jouw review' en Review is nog niet klaar.
        for alt in self.alts("final"):
            self.assertRegex(alt.lower(), r"wacht op jouw review")
            self.assertNotRegex(alt.lower(), r"alle fases (zijn )?klaar")

    def test_alt_van_viewer_design_noemt_de_lichte_stand(self):
        # Op viewer-design.png staat het prototype van het donkere thema in zijn lichte stand.
        for alt in self.alts("viewer-design"):
            self.assertRegex(alt.lower(), r"\bprototype\b")
            self.assertRegex(alt.lower(), r"\blichte stand\b")

    def test_verschillende_screenshots_hebben_verschillende_alt(self):
        alt_per_src = {}
        for p in self.previews:
            for img in self.imgs(p):
                alt_per_src.setdefault(img.attrs.get("src"), set()).add(img.attrs.get("alt"))
        self.assertEqual(len(alt_per_src), len(SCREENSHOTS))
        srcs = list(alt_per_src)
        for i, a in enumerate(srcs):
            for b in srcs[i + 1:]:
                self.assertFalse(alt_per_src[a] & alt_per_src[b],
                                 f"{a} en {b} delen dezelfde alt")

    def test_geen_leeg_blok_waar_een_plaatje_staat(self):
        for p in self.previews:
            with self.subTest(href=p.attrs.get("href")):
                self.assertTrue(self.imgs(p), "preview heeft nog geen <img>")
                leeg = [e for e in p.iter() if {"leeg", "kan-leeg", "mock"} & set(e.classes)]
                self.assertEqual(leeg, [], "het .leeg-blok staat nog naast het plaatje")

    def test_leeg_blijft_als_terugval_in_de_css(self):
        css = re.sub(r"/\*.*?\*/", "", lees(check_site.CSS), flags=re.S)
        self.assertRegex(css, r"(^|[}\s,])\.preview\s+\.leeg\s*\{")
        self.assertRegex(css, r"(^|[}\s,])\.leeg\s*\{")

    def test_site_js_vervangt_een_kapot_previewplaatje_door_het_leeg_blok(self):
        # Alleen een statische controle; het echte gedrag (404 -> .leeg) toetst de UI-gate.
        js = re.sub(r"/\*.*?\*/|//[^\n]*", "", lees(os.path.join(ROOT, "assets", "site.js")),
                    flags=re.S)
        self.assertRegex(js, r"querySelectorAll\(\s*[\"']\.preview img[\"']\s*\)")
        self.assertRegex(js, r"addEventListener\(\s*[\"']error[\"']")
        self.assertRegex(js, r"className\s*=\s*[\"']leeg[\"']")
        self.assertRegex(js, r"Nog geen afbeelding")
        html = lees(INDEX)
        self.assertNotRegex(html, r"\sonerror\s*=", "geen inline onerror-handlers")

    def test_check_site_vindt_geen_img_met_verkeerde_maat_op_de_pagina(self):
        self.assertEqual(check_site.controleer_img_maten(self.html), [])

    def test_check_site_meldt_img_met_verkeerde_maat(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "x.png"), "wb") as f:
                f.write(maak_png())
            with open(os.path.join(tmp, "kapot.png"), "wb") as f:
                f.write(b"geen png")
            goed = '<img src="x.png" width="1" height="1" alt="a">'
            self.assertEqual(check_site.controleer_img_maten(goed, root=tmp), [])
            for fout in ['<img src="x.png" width="2" height="1" alt="a">',
                         '<img src="x.png" width="1" alt="a">',
                         '<img src="/x.png?v=2" width="1" height="3" alt="a">',
                         '<img src="kapot.png" width="1" height="1" alt="a">']:
                with self.subTest(html=fout):
                    self.assertEqual(len(check_site.controleer_img_maten(fout, root=tmp)), 1)

    def test_elk_plaatje_waar_de_pagina_naar_verwijst_bestaat_en_is_klein_genoeg(self):
        srcs = [e.attrs["src"] for e in self.pagina.elementen()
                if e.tag == "img" and e.attrs.get("src")
                and not e.attrs["src"].startswith("data:")]
        srcs += [e.attrs["content"] for e in self.pagina.elementen()
                 if e.tag == "meta" and e.attrs.get("property") == "og:image"]
        self.assertGreaterEqual(len(srcs), 11, "verwacht tien previews en og:image")
        for src in srcs:
            with self.subTest(src=src):
                pad = lokaal_pad(src)
                self.assertTrue(os.path.isfile(pad), f"{src} bestaat niet")
                self.assertLess(os.path.getsize(pad), MAX_BYTES)


class OgTags(unittest.TestCase):
    """Openstaand uit cp02: de og:image-gegevens kloppen met het echte og.png."""

    @classmethod
    def setUpClass(cls):
        head = [e for e in Pagina(lees(INDEX)).elementen() if e.tag == "head"][0]
        cls.metas = [e for e in head.iter() if e.tag == "meta"]

    def prop(self, naam):
        gevonden = [e.attrs.get("content") for e in self.metas
                    if e.attrs.get("property") == naam]
        self.assertEqual(len(gevonden), 1, f"verwacht precies één <meta property={naam}>")
        return gevonden[0]

    def test_og_tags_gebruiken_property_en_niet_name(self):
        verkeerd = [e.attrs["name"] for e in self.metas
                    if (e.attrs.get("name") or "").startswith("og:")]
        self.assertEqual(verkeerd, [])

    def test_og_image_maat_klopt_met_og_png(self):
        breedte, hoogte = png_header(lokaal_pad(self.prop("og:image")))
        self.assertEqual((breedte, hoogte), OG_MAAT)
        self.assertEqual(self.prop("og:image:width"), str(breedte))
        self.assertEqual(self.prop("og:image:height"), str(hoogte))

    def test_og_image_type_is_png(self):
        self.assertEqual(self.prop("og:image:type"), "image/png")

    def test_og_image_alt_is_beschrijvend(self):
        alt = (self.prop("og:image:alt") or "").strip()
        self.assertGreaterEqual(len(alt.split()), 5)
        self.assertNotIn(".png", alt.lower())


class PngLezer(unittest.TestCase):
    """De helper in check_site: png_afmetingen(pad) -> (breedte, hoogte), ValueError bij onzin."""

    def lezer(self):
        lezer = getattr(check_site, "png_afmetingen", None)
        self.assertTrue(callable(lezer), "tests/check_site.py mist png_afmetingen(pad)")
        return lezer

    def tijdelijk(self, inhoud):
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        f.write(inhoud)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_leest_de_maat_van_een_echte_png(self):
        pad = self.tijdelijk(maak_png())
        self.assertEqual(self.lezer()(pad), (1, 1))

    def test_leest_de_maat_van_og_png(self):
        self.assertEqual(self.lezer()(os.path.join(PREVIEWS, "og.png")), OG_MAAT)

    def test_weigert_png_met_kapotte_ihdr_crc(self):
        png = bytearray(maak_png())
        png[29] ^= 0xFF
        pad = self.tijdelijk(bytes(png))
        with self.assertRaises(ValueError):
            self.lezer()(pad)

    def test_weigert_jpeg_met_png_extensie(self):
        pad = self.tijdelijk(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 40)
        with self.assertRaises(ValueError):
            self.lezer()(pad)

    def test_weigert_leeg_bestand(self):
        pad = self.tijdelijk(b"")
        with self.assertRaises(ValueError):
            self.lezer()(pad)

    def test_weigert_afgekapte_png(self):
        pad = self.tijdelijk(maak_png()[:20])
        with self.assertRaises(ValueError):
            self.lezer()(pad)


class Privacy(unittest.TestCase):
    def test_pngs_worden_gepubliceerd_en_dus_gescand(self):
        gepubliceerd = set(check_privacy.gepubliceerde_bestanden(ROOT))
        for naam in SCREENSHOTS + ["og"]:
            with self.subTest(naam=naam):
                self.assertIn(f"assets/previews/{naam}.png", gepubliceerd)

    def test_pngs_bevatten_niets_persoonlijks(self):
        meldingen = []
        for naam in SCREENSHOTS + ["og"]:
            pad = os.path.join(PREVIEWS, naam + ".png")
            self.assertTrue(os.path.isfile(pad), f"assets/previews/{naam}.png ontbreekt")
            meldingen += check_privacy.scan_bestand(pad)
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_scan_vindt_pad_in_gewone_tekstchunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = os.path.join(tmp, "x.png")
            with open(pad, "wb") as f:
                f.write(maak_png([(b"tEXt", b"Comment\x00/Users/iemand/project")]))
            self.assertTrue(check_privacy.scan_bestand(pad, root=tmp))

    def test_scan_vindt_pad_in_gecomprimeerde_tekstchunk(self):
        # zTXt en gecomprimeerde iTXt zijn als ruwe bytes niet leesbaar; de scan moet ze
        # uitpakken, anders glipt een pad in de metadata erdoor.
        with tempfile.TemporaryDirectory() as tmp:
            for soort, data in [
                (b"zTXt", b"Comment\x00\x00" + zlib.compress(b"/Users/iemand/project")),
                (b"iTXt", b"Comment\x00\x01\x00\x00\x00"
                          + zlib.compress(b"iemand@voorbeeld.nl")),
            ]:
                with self.subTest(chunk=soort.decode()):
                    pad = os.path.join(tmp, soort.decode() + ".png")
                    with open(pad, "wb") as f:
                        f.write(maak_png([(soort, data)]))
                    self.assertTrue(check_privacy.scan_bestand(pad, root=tmp),
                                    f"persoonlijke gegevens in {soort.decode()} niet gevonden")


    def schrijf_png(self, tmp, naam, chunks):
        pad = os.path.join(tmp, naam)
        with open(pad, "wb") as f:
            f.write(maak_png(chunks))
        return pad

    def test_zip_bom_in_tekstchunk_wordt_niet_helemaal_uitgepakt_en_is_een_melding(self):
        # 64 MB nullen, gecomprimeerd tot zo'n 64 kB. Onbeperkt uitpakken zou 64 MB kosten.
        bom = zlib.compress(b"\0" * (64 * 1024 * 1024), 9)
        self.assertLess(len(bom), 128 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            for soort, data in [(b"zTXt", b"Comment\x00\x00" + bom),
                                (b"iTXt", b"Comment\x00\x01\x00\x00\x00" + bom)]:
                with self.subTest(chunk=soort.decode()):
                    pad = self.schrijf_png(tmp, soort.decode() + ".png", [(soort, data)])
                    meldingen = check_privacy.scan_bestand(pad, root=tmp)
                    self.assertEqual(len(meldingen), 1, meldingen)
                    self.assertIn(f"(PNG-tekstchunk {soort.decode()})", meldingen[0])
                    self.assertIn("meer dan", meldingen[0])

    def test_uitpakken_stopt_bij_het_maximum(self):
        tekst, probleem = check_privacy._pak_uit(zlib.compress(b"a" * 5000), maximum=1000)
        self.assertEqual(len(tekst), 1000)
        self.assertTrue(probleem)
        tekst, probleem = check_privacy._pak_uit(zlib.compress(b"a" * 1000), maximum=1000)
        self.assertEqual((len(tekst), probleem), (1000, None))

    def kapotte_stroom(self, begin):
        """zlib-data die eerst `begin` netjes geeft en daarna kapot is."""
        c = zlib.compressobj()
        return c.compress(begin) + c.flush(zlib.Z_FULL_FLUSH) + b"\xff\xff\xff\xff"

    def test_kapotte_tekstchunk_is_een_melding_en_het_leesbare_deel_wordt_gescand(self):
        data = self.kapotte_stroom(b"/Users/iemand/project en iemand@voorbeeld.nl ")
        with tempfile.TemporaryDirectory() as tmp:
            for soort, chunk in [(b"zTXt", b"Comment\x00\x00" + data),
                                 (b"iTXt", b"Comment\x00\x01\x00\x00\x00" + data)]:
                with self.subTest(chunk=soort.decode()):
                    pad = self.schrijf_png(tmp, soort.decode() + ".png", [(soort, chunk)])
                    tekst = "\n".join(check_privacy.scan_bestand(pad, root=tmp))
                    self.assertIn("onleesbare gecomprimeerde tekst", tekst)
                    self.assertIn("persoonlijk pad: /Users/iemand/project", tekst)
                    self.assertIn("e-mailadres: iemand@voorbeeld.nl", tekst)

    def test_afgekapte_tekstchunk_is_een_melding(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = self.schrijf_png(tmp, "x.png", [
                (b"zTXt", b"Comment\x00\x00" + zlib.compress(b"gewone tekst" * 50)[:-6])])
            meldingen = check_privacy.scan_bestand(pad, root=tmp)
            self.assertEqual(len(meldingen), 1, meldingen)
            self.assertIn("afgekapt", meldingen[0])

    def test_nette_tekstchunks_geven_geen_melding(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = self.schrijf_png(tmp, "x.png", [
                (b"tEXt", b"Software\x00Playwright"),
                (b"zTXt", b"Comment\x00\x00" + zlib.compress(b"gewone tekst")),
                (b"iTXt", b"Comment\x00\x01\x00nl\x00\x00" + zlib.compress(b"hallo"))])
            self.assertEqual(check_privacy.scan_bestand(pad, root=tmp), [])

    def test_melding_in_png_noemt_de_chunk_en_geen_regelnummer(self):
        with tempfile.TemporaryDirectory() as tmp:
            for soort, data in [
                (b"tEXt", b"Comment\x00/Users/iemand/project"),
                (b"zTXt", b"Comment\x00\x00" + zlib.compress(b"/Users/iemand/project")),
                (b"iTXt", b"Comment\x00\x00\x00\x00/Users/iemand/project"),
            ]:
                with self.subTest(chunk=soort.decode()):
                    pad = self.schrijf_png(tmp, soort.decode() + ".png", [(soort, data)])
                    meldingen = check_privacy.scan_bestand(pad, root=tmp)
                    self.assertEqual(meldingen, [
                        f"{pad} (PNG-tekstchunk {soort.decode()}): "
                        "persoonlijk pad: /Users/iemand/project"])

    def test_pad_in_een_andere_chunk_of_na_iend_wordt_ook_gevonden(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = self.schrijf_png(tmp, "x.png", [(b"prIv", b"/home/iemand/x")])
            with open(pad, "ab") as f:
                f.write(b"iemand@voorbeeld.nl")
            tekst = "\n".join(check_privacy.scan_bestand(pad, root=tmp))
            self.assertIn("(PNG-chunk prIv): persoonlijk pad: /home/iemand/x", tekst)
            self.assertIn("(PNG, na de laatste hele chunk): e-mailadres: iemand@voorbeeld.nl", tekst)


if __name__ == "__main__":
    unittest.main()
