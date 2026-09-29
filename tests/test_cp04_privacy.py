"""cp04: niets wat GitHub Pages publiceert bevat persoonlijke paden, e-mailadressen of sessie-id's.

De scan staat in tests/check_privacy.py.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.check_site import ROOT
from tests import check_privacy


class Gepubliceerd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bestanden = check_privacy.gepubliceerde_bestanden(ROOT)

    def rel(self, pad):
        return os.path.relpath(os.path.join(ROOT, pad), ROOT).replace(os.sep, "/")

    def test_bestandenlijst_is_wat_pages_publiceert(self):
        rel = {self.rel(p) for p in self.bestanden}
        for moet in ("index.html", "assets/site.css", "assets/site.js", "README.md"):
            self.assertIn(moet, rel)
        for p in rel:
            self.assertFalse(p.startswith(("tests/", ".buildflow/")), p)

    def test_geen_bestand_bevat_iets_persoonlijks(self):
        meldingen = []
        for pad in self.bestanden:
            meldingen += check_privacy.scan_bestand(os.path.join(ROOT, self.rel(pad)))
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_toegestane_uitzonderingen_zijn_nu_leeg(self):
        self.assertEqual(list(check_privacy.TOEGESTAAN), [])


class ScanSlaatAan(unittest.TestCase):
    def setUp(self):
        self.map = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.map)

    def schrijf(self, naam, inhoud, modus="w"):
        pad = os.path.join(self.map, naam)
        with open(pad, modus, **({} if "b" in modus else {"encoding": "utf-8"})) as f:
            f.write(inhoud)
        return pad

    def test_pad_email_en_sessie_id(self):
        pad = self.schrijf("nep.html", "regel een\nzie /Users/iemand/x\n"
                           "mail iemand@voorbeeld.nl\n"
                           "sessie 3f2b8c1e-1234-4abc-9def-0123456789ab\n")
        meldingen = check_privacy.scan_bestand(pad)
        tekst = "\n".join(meldingen)
        self.assertIn("/Users/", tekst)
        self.assertIn("iemand@voorbeeld.nl", tekst)
        self.assertIn("3f2b8c1e-1234-4abc-9def-0123456789ab", tekst)
        self.assertIn("nep.html", tekst, "melding noemt het bestand niet")
        self.assertTrue(any(":2" in m or "regel 2" in m for m in meldingen),
                        f"melding noemt de regel niet: {meldingen}")

    def test_andere_paden(self):
        for stuk in ("/private/tmp/claude/x", "/home/iemand/y"):
            with self.subTest(stuk=stuk):
                pad = self.schrijf("a.txt", f"kijk in {stuk}\n")
                self.assertTrue(check_privacy.scan_bestand(pad), stuk)

    def test_schoon_bestand(self):
        pad = self.schrijf("ok.html", "<p>Pak uit in ~/.claude/skills</p>\n")
        self.assertEqual(check_privacy.scan_bestand(pad), [])

    def test_ssh_remote_is_geen_email(self):
        pad = self.schrijf("r.txt", "git remote add origin git@github.com:eigenaar/repo.git\n"
                           "of git@gitlab.example.org:groep/sub-repo\n")
        self.assertEqual(check_privacy.scan_bestand(pad), [])

    def test_email_naast_of_op_de_plek_van_een_remote_blijft_een_melding(self):
        for regel in ("mail git@voorbeeld.nl gewoon", "iemand@github.com:eigenaar/repo.git",
                      "jan-git@github.com:eigenaar/repo.git",
                      "git@github.com:eigenaar/repo.git en iemand@voorbeeld.nl"):
            with self.subTest(regel=regel):
                pad = self.schrijf("e.txt", regel + "\n")
                self.assertTrue(check_privacy.scan_bestand(pad), regel)

    def test_toegestaan_gaat_op_het_pad_in_de_repo(self):
        os.makedirs(os.path.join(self.map, "a"))
        os.makedirs(os.path.join(self.map, "b"))
        goed = self.schrijf(os.path.join("a", "x.html"), "zie /Users/iemand/x\n")
        ander = self.schrijf(os.path.join("b", "x.html"), "zie /Users/iemand/x\n")
        with mock.patch.object(check_privacy, "TOEGESTAAN", (("a/x.html", "/Users/iemand/x"),)):
            self.assertEqual(check_privacy.scan_bestand(goed, root=self.map), [])
            self.assertTrue(check_privacy.scan_bestand(ander, root=self.map),
                            "zelfde bestandsnaam in een andere map mag niet meeliften")
        self.assertTrue(check_privacy.scan_bestand(goed, root=self.map))

    def test_binair_bestand_met_pad(self):
        pad = self.schrijf("plaatje.png", b"\x89PNG\r\n\x1a\n\x00\xff/Users/iemand/x\x00", "wb")
        self.assertTrue(check_privacy.scan_bestand(pad))


class NieuweBestanden(unittest.TestCase):
    """Nog niet toegevoegde bestanden worden ook gepubliceerd zodra ze gecommit zijn."""

    def setUp(self):
        self.map = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.map)
        git = ["git", "-C", self.map]
        subprocess.run(git + ["init", "-q"], check=True)
        for naam, inhoud in (("oud.html", "schoon\n"), (".gitignore", "genegeerd.txt\n")):
            with open(os.path.join(self.map, naam), "w", encoding="utf-8") as f:
                f.write(inhoud)
        subprocess.run(git + ["add", "oud.html", ".gitignore"], check=True)
        os.makedirs(os.path.join(self.map, "tests"))
        for naam in ("nieuw.html", "genegeerd.txt", os.path.join("tests", "t.py")):
            with open(os.path.join(self.map, naam), "w", encoding="utf-8") as f:
                f.write("zie /Users/iemand/x\n")

    def test_niet_toegevoegd_bestand_telt_mee(self):
        paden = check_privacy.gepubliceerde_bestanden(self.map)
        self.assertEqual(paden, [".gitignore", "nieuw.html", "oud.html"])
        meldingen = []
        for p in paden:
            meldingen += check_privacy.scan_bestand(os.path.join(self.map, p), root=self.map)
        self.assertTrue(any("nieuw.html" in m for m in meldingen), meldingen)


if __name__ == "__main__":
    unittest.main()
