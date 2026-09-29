"""cp04: de zichtbare tekst van de pagina bevat geen AI-taal.

De controle zelf staat in tests/check_copy.py. Deze tests draaien hem op index.html en
op kleine snippets waar hij moet aanslaan, zodat een kapotte controle ook opvalt.
"""
import unittest

from tests.check_site import INDEX, lees
from tests import check_copy

# Minimaal wat de vermijdlijst moet vangen (uit ~/.claude/CLAUDE.md en de learnings).
# Ook verbogen vormen tellen: "naadloze" is net zo goed AI-taal als "naadloos".
VERPLICHT = [
    "bovendien", "daarnaast", "tevens", "voorts", "cruciaal", "cruciale", "essentieel",
    "essentiële", "naadloos", "naadloze", "robuust", "robuuste", "holistisch",
    "faciliteren", "faciliteert", "samenvattend", "kortom", "al met al", "in de kern",
    "op het gebied van", "een breed scala aan", "niet alleen",
    "het is belangrijk om op te merken",
]
# De Engelse vermijdlijst uit dezelfde schrijfstijl.
VERPLICHT_EN = [
    "delve", "tapestry", "testament", "pivotal", "crucial", "robust", "seamless",
    "seamlessly", "leverage", "leveraging", "utilize", "utilise", "landscape",
    "multifaceted", "holistic", "moreover", "furthermore", "game-changer", "cutting-edge",
    "transformative", "revolutionize", "unlock", "in the realm of", "not only",
    "it's important to note", "in conclusion", "in summary", "serves as", "boasts",
]


class ZichtbareTekst(unittest.TestCase):
    def test_pagina_bevat_geen_woord_uit_de_vermijdlijst(self):
        meldingen = check_copy.controleer_copy(lees(INDEX))
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_pagina_heeft_hooguit_een_handvol_gedachtestreepjes(self):
        tekst = check_copy.zichtbare_tekst(lees(INDEX))
        self.assertGreater(len(tekst), 2000, "zichtbare tekst lijkt leeg")
        self.assertLessEqual(check_copy.MAX_STREEPJES, 5)
        self.assertLessEqual(tekst.count("—"), check_copy.MAX_STREEPJES)
        self.assertLessEqual(check_copy.tel_streepjes(tekst), check_copy.MAX_STREEPJES)


class ControleSlaatAan(unittest.TestCase):
    def test_elk_verplicht_woord_wordt_gemeld(self):
        for woord in VERPLICHT:
            with self.subTest(woord=woord):
                zin = f"Dit is {woord} een goede aanpak."
                meldingen = check_copy.controleer_copy(f"<p>{zin}</p>")
                self.assertTrue(meldingen, f"'{woord}' niet gemeld")
                self.assertTrue(any(woord.lower() in m.lower() for m in meldingen),
                                f"melding noemt het woord niet: {meldingen}")

    def test_elk_engels_woord_wordt_gemeld(self):
        for woord in VERPLICHT_EN:
            with self.subTest(woord=woord):
                meldingen = check_copy.controleer_copy(f"<p>This is {woord} a plan.</p>")
                self.assertTrue(any(woord.lower() in m.lower() for m in meldingen),
                                f"'{woord}' niet gemeld: {meldingen}")

    def test_engelse_woorden_alleen_op_woordgrens(self):
        # 'robuustheid', 'landscaper' en 'unlockable' zijn andere woorden;
        # 'unlocked' is wel een vorm van 'unlock'.
        for tekst in ("robuustheid", "landscaper", "tapestryx", "unlockable", "boastful"):
            with self.subTest(tekst=tekst):
                self.assertEqual(check_copy.controleer_copy(f"<p>Een {tekst} hier.</p>"), [])
        self.assertTrue(check_copy.controleer_copy("<p>We unlocked it.</p>"))

    def test_additionally_aan_het_begin_van_een_zin(self):
        self.assertTrue(check_copy.controleer_copy("<p>Done. Additionally, more.</p>"))

    def test_meta_en_title_tellen_mee(self):
        for tag in ('<meta name="description" content="Een robuuste aanpak.">',
                    '<meta property="og:title" content="Naadloos bouwen">',
                    '<meta property="og:description" content="Bovendien snel.">',
                    '<meta name="twitter:title" content="A seamless build">',
                    '<meta name="twitter:description" content="Leverage the flow.">',
                    '<meta property="og:image:alt" content="Een cruciaal plaatje">',
                    '<title>Kortom buildflow</title>'):
            with self.subTest(tag=tag):
                html = f"<html><head>{tag}</head><body><p>Schoon.</p></body></html>"
                self.assertTrue(check_copy.controleer_copy(html), f"{tag} niet gecontroleerd")

    def test_meta_zonder_zichtbare_tekst_telt_niet(self):
        html = ('<head><meta property="og:url" content="https://x.nl/robuust">'
                '<meta name="viewport" content="robust"></head><p>Schoon.</p>')
        self.assertEqual(check_copy.controleer_copy(html), [])

    def test_meta_van_de_echte_pagina_zit_in_de_tekst(self):
        tekst = check_copy.zichtbare_tekst(lees(INDEX))
        self.assertIn("opknipt in kleine checkpoints. Elke stap gaat langs tests", tekst)
        self.assertIn("Uitleg, handleiding, installatie en download", tekst)

    def test_en_streepjes_met_spaties_tellen_mee(self):
        zes = "<p>Een – twee – drie – vier – vijf – zes – klaar.</p>"
        self.assertTrue(any("6" in m for m in check_copy.controleer_copy(zes)))
        gemengd = "<p>Een — twee — drie – vier – vijf — zes – klaar.</p>"
        self.assertTrue(any("6" in m for m in check_copy.controleer_copy(gemengd)))
        bereik = "<p>" + " ".join(f"{i}–{i + 1}" for i in range(10)) + " keer.</p>"
        self.assertEqual(check_copy.controleer_copy(bereik), [])

    def test_hoofdletters_maken_niet_uit_en_de_melding_noemt_de_zin(self):
        meldingen = check_copy.controleer_copy("<p>Kort gezegd. Bovendien is dit fijn.</p>")
        self.assertTrue(any("bovendien" in m.lower() for m in meldingen), meldingen)
        self.assertTrue(any("is dit fijn" in m for m in meldingen),
                        f"melding noemt de zin niet: {meldingen}")

    def test_snippet_met_twee_woorden_en_zes_streepjes(self):
        html = ("<p>Bovendien is dit naadloos. Een — twee — drie — vier — vijf — zes — "
                "klaar.</p><p><code>robuust</code></p>")
        meldingen = check_copy.controleer_copy(html)
        tekst = " ".join(meldingen).lower()
        self.assertIn("bovendien", tekst)
        self.assertIn("naadloos", tekst)
        self.assertTrue(any("6" in m and ("streep" in m.lower() or "—" in m)
                            for m in meldingen),
                        f"streepjesaantal niet gemeld: {meldingen}")
        self.assertNotIn("robuust", tekst, "woord binnen <code> telt niet")

    def test_vijf_streepjes_mag(self):
        html = "<p>Een — twee — drie — vier — vijf — klaar.</p>"
        self.assertEqual(check_copy.controleer_copy(html), [])

    def test_echter_aan_het_begin_van_een_zin(self):
        self.assertTrue(check_copy.controleer_copy("<p>Het werkt. Echter, niet altijd.</p>"))
        self.assertTrue(check_copy.controleer_copy("<p>Echter werkt het niet.</p>"))
        self.assertEqual(check_copy.controleer_copy("<p>Het werkt echter niet altijd.</p>"), [])

    def test_wat_niet_zichtbaar_is_telt_niet(self):
        html = ("<script>var robuust = 1;</script><style>.naadloos{}</style>"
                "<pre>bovendien</pre><a href='/kortom' class='tevens'>link</a>"
                "<!-- daarnaast --><p>Gewone tekst.</p>")
        self.assertEqual(check_copy.controleer_copy(html), [])

    def test_alt_title_en_aria_label_tellen_wel(self):
        for attr in ("alt", "title", "aria-label"):
            with self.subTest(attr=attr):
                html = f'<p>Tekst <img {attr}="een robuust plaatje" src="x.png"></p>'
                meldingen = check_copy.controleer_copy(html)
                self.assertTrue(any("robuust" in m.lower() for m in meldingen),
                                f"{attr} niet meegenomen: {meldingen}")

    def test_woordgrens(self):
        # 'kern' en 'robuustheid' zijn geen hits op 'in de kern' en geen woord uit de lijst.
        self.assertEqual(check_copy.controleer_copy("<p>Het kernwoord staat voorop.</p>"), [])


if __name__ == "__main__":
    unittest.main()
