"""cp02: tabicoon en linkvoorbeeld in de <head>."""
import os
import unittest
import urllib.parse
from html.parser import HTMLParser

from tests.check_site import INDEX, ROOT, Pagina, controleer_links, design_tokens, lees

SITE_URL = "https://joepvanabeelen.github.io/buildflow/"
OG_IMAGE = SITE_URL + "assets/previews/og.png"
META_NAMEN = ["og:title", "og:description", "og:type", "og:url", "og:locale",
              "og:image", "twitter:card"]


class SvgInhoud(HTMLParser):
    def __init__(self, svg):
        super().__init__(convert_charrefs=True)
        self.elementen = []  # (tag, attrs, tekst)
        self._open = []
        self.feed(svg)
        self.close()

    def handle_starttag(self, tag, attrs):
        item = [tag, dict(attrs), ""]
        self.elementen.append(item)
        self._open.append(item)

    def handle_startendtag(self, tag, attrs):
        self.elementen.append([tag, dict(attrs), ""])

    def handle_endtag(self, tag):
        if self._open and self._open[-1][0] == tag:
            self._open.pop()

    def handle_data(self, data):
        if self._open:
            self._open[-1][2] += data


class Head(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(INDEX), "index.html ontbreekt in de repo-root")
        self.html = lees(INDEX)
        heads = [e for e in Pagina(self.html).elementen() if e.tag == "head"]
        self.assertEqual(len(heads), 1, "verwacht precies één <head>")
        self.head = heads[0]

    def in_head(self, tag):
        return [e for e in self.head.iter() if e.tag == tag]

    def links(self, rel):
        return [e for e in self.in_head("link")
                if rel in (e.attrs.get("rel") or "").lower().split()]

    def metas(self, naam):
        return [e for e in self.in_head("meta")
                if (e.attrs.get("property") or e.attrs.get("name")) == naam]

    def meta(self, naam):
        gevonden = self.metas(naam)
        self.assertEqual(len(gevonden), 1,
                         f"verwacht precies één <meta> voor {naam}, gevonden: {len(gevonden)}")
        return (gevonden[0].attrs.get("content") or "").strip()


class TestFavicon(Head):
    def test_favicon_is_inline_svg_met_zwart_vierkant_gele_balk_witte_b(self):
        icons = self.links("icon")
        self.assertEqual(len(icons), 1, "verwacht precies één <link rel=icon> in de head")
        href = icons[0].attrs.get("href") or ""
        self.assertTrue(href.startswith("data:image/svg+xml"),
                        f"favicon is geen SVG-data-URI: {href[:60]!r}")
        data = href.split(",", 1)[1]
        svg = urllib.parse.unquote(data)
        els = SvgInhoud(svg).elementen
        zwart = (design_tokens() or {}).get("--zwart", "#141412").lower()

        def kleur(e):
            return (e[1].get("fill") or "").lower()

        self.assertTrue([e for e in els if e[0] == "rect" and kleur(e) in (zwart, "#141412")],
                        "geen zwart vierkant (rect met --zwart) in de favicon")
        self.assertTrue([e for e in els if kleur(e) == "#ffce1f"],
                        "geen gele balk (#FFCE1F) in de favicon")
        wit = ("#fff", "#ffffff", "white")
        self.assertTrue([e for e in els if e[0] == "text" and kleur(e) in wit
                         and e[2].strip() == "b"],
                        "geen witte tekst 'b' in de favicon")

    def test_geen_los_icoonbestand_nodig(self):
        for link in self.links("icon") + self.links("apple-touch-icon"):
            href = link.attrs.get("href") or ""
            self.assertTrue(href.startswith("data:"),
                            f"icoon verwijst naar een bestand: {href[:60]!r}")


class TestLinkvoorbeeld(Head):
    def test_og_en_twitter_tags_bestaan_eenmaal_en_niet_leeg(self):
        for naam in META_NAMEN:
            with self.subTest(meta=naam):
                self.assertTrue(self.meta(naam), f"{naam} heeft een lege content")
        self.assertEqual(self.meta("og:locale"), "nl_NL")
        self.assertEqual(self.meta("og:type"), "website")
        self.assertEqual(self.meta("twitter:card"), "summary_large_image")

    def test_og_url_en_canonical_zijn_de_site_url(self):
        self.assertEqual(self.meta("og:url"), SITE_URL)
        canon = self.links("canonical")
        self.assertEqual(len(canon), 1, "verwacht precies één <link rel=canonical>")
        self.assertEqual((canon[0].attrs.get("href") or "").strip(), SITE_URL)

    def test_og_image_is_absolute_url_naar_og_png(self):
        # Of het bestand bestaat, test cp09.
        self.assertEqual(self.meta("og:image"), OG_IMAGE)

    def test_title_en_og_title_bevatten_buildflow(self):
        titels = self.in_head("title")
        self.assertEqual(len(titels), 1, "verwacht precies één <title>")
        titel = titels[0].alle_tekst().strip()
        self.assertIn("buildflow", titel)
        self.assertIn("buildflow", self.meta("og:title"))


class TestCp01BlijftGroen(Head):
    def test_head_parseert_en_data_favicon_telt_niet_als_ontbrekend_bestand(self):
        self.assertEqual(Pagina(self.html).fouten, [])
        fouten = controleer_links(self.html, ROOT)
        self.assertEqual([f for f in fouten if "data:" in f], [])
        self.assertEqual(fouten, [], "\n".join(fouten))


if __name__ == "__main__":
    unittest.main()
