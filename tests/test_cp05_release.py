"""cp05: scripts/release.py bouwt dist/buildflow.zip uit de skillmap, in --dry-run zonder te publiceren.

Elke test draait het script in een tijdelijke kopie van de repo-indeling
(<tmp>/repo/scripts/release.py en <tmp>/repo/LICENSE), zodat dist/ in de tijdelijke map
belandt en de echte repo niet wordt aangeraakt. Het script moet dus op zichzelf staan en
de repo-root afleiden uit zijn eigen plek of de werkmap (die zijn hier gelijk).

Er wordt niets gepubliceerd: gh en git staan als stubs vooraan op PATH en loggen alleen.
"""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tests.check_site import ROOT

SCRIPT = os.path.join(ROOT, "scripts", "release.py")
LICENSE = os.path.join(ROOT, "LICENSE")

NEP_SKILL = {
    "SKILL.md": "---\nname: buildflow\n---\n# buildflow\n",
    "README.md": "# buildflow\n",
    "pricing.json": "{}\n",
    "references/a.md": "# a\n",
    "scripts/bf.py": "print('bf')\n",
    "scripts/gate_hook.py": "print('hook')\n",
    "assets/viewer.html": "<!doctype html><title>v</title>\n",
}
RUIS = {
    "scripts/__pycache__/bf.cpython-312.pyc": b"\x00pyc",
    "scripts/oud.pyc": b"\x00pyc",
    ".DS_Store": b"\x00ds",
    "assets/.DS_Store": b"\x00ds",
    ".hidden": b"geheim\n",
}


def schrijf(basis, rel, inhoud):
    pad = os.path.join(basis, *rel.split("/"))
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "wb") as f:
        f.write(inhoud if isinstance(inhoud, bytes) else inhoud.encode("utf-8"))
    return pad


def snapshot(map_):
    uit = {}
    for wortel, _, namen in os.walk(map_):
        for naam in namen:
            pad = os.path.join(wortel, naam)
            st = os.stat(pad)
            with open(pad, "rb") as f:
                uit[os.path.relpath(pad, map_)] = (st.st_size, st.st_mtime_ns,
                                                    hashlib.sha256(f.read()).hexdigest())
    return uit


class ReleaseBasis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bf-cp05-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        self.skill = os.path.join(self.tmp, "nepskill")
        for rel, inhoud in {**NEP_SKILL, **RUIS}.items():
            schrijf(self.skill, rel, inhoud)
        self.zip = os.path.join(self.repo, "dist", "buildflow.zip")
        # gh- en git-stubs die alleen hun argumenten loggen
        self.fakebin = os.path.join(self.tmp, "fakebin")
        self.log = os.path.join(self.tmp, "aanroepen.log")
        for naam in ("gh", "git"):
            pad = schrijf(self.fakebin, naam,
                          f'#!/bin/sh\necho "{naam} $*" >> "{self.log}"\nexit 0\n')
            os.chmod(pad, os.stat(pad).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def maak_repo(self):
        """Tijdelijke repo-indeling met een kopie van het echte script en de echte LICENSE."""
        self.assertTrue(os.path.isfile(SCRIPT), "scripts/release.py bestaat niet")
        self.assertTrue(os.path.isfile(LICENSE), "LICENSE in de repo-root bestaat niet")
        if not os.path.isdir(self.repo):
            os.makedirs(os.path.join(self.repo, "scripts"))
            shutil.copy2(SCRIPT, os.path.join(self.repo, "scripts", "release.py"))
            shutil.copy2(LICENSE, os.path.join(self.repo, "LICENSE"))

    def draai(self, *args, env_extra=None):
        self.maak_repo()
        env = {k: v for k, v in os.environ.items() if k != "BUILDFLOW_SKILL_SRC"}
        env["PATH"] = self.fakebin + os.pathsep + env.get("PATH", "")
        env.update(env_extra or {})
        return subprocess.run([sys.executable, os.path.join("scripts", "release.py"), *args],
                              cwd=self.repo, env=env, capture_output=True, text=True,
                              timeout=60)

    def bouw(self, *extra):
        uit = self.draai("--dry-run", "--src", self.skill, *extra)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertTrue(os.path.isfile(self.zip), "dist/buildflow.zip is niet gemaakt")
        return uit

    def namen(self):
        with zipfile.ZipFile(self.zip) as z:
            return z.namelist()


class Bouwen(ReleaseBasis):
    def test_dry_run_met_src_schrijft_zip_en_print_pad_grootte_en_bestanden(self):
        uit = self.bouw()
        self.assertIn(os.path.join("dist", "buildflow.zip"), uit.stdout)
        self.assertRegex(uit.stdout, r"\d[\d.,]*\s*(bytes|B|kB|KB)\b")
        for rel in NEP_SKILL:
            self.assertIn(rel, uit.stdout, f"{rel} ontbreekt in de bestandslijst op stdout")
        self.assertIn("LICENSE", uit.stdout)

    def test_zonder_src_gebruikt_buildflow_skill_src(self):
        uit = self.draai("--dry-run", env_extra={"BUILDFLOW_SKILL_SRC": self.skill})
        self.assertEqual(uit.returncode, 0, uit.stderr)
        namen = self.namen()
        for rel in NEP_SKILL:
            self.assertIn("buildflow/" + rel, namen)

    def test_zonder_src_en_variabele_valt_terug_op_skill_buildflow_naast_de_repo(self):
        standaard = os.path.join(self.tmp, "skill-buildflow", "skills", "buildflow")
        for rel, inhoud in NEP_SKILL.items():
            schrijf(standaard, rel, inhoud)
        schrijf(standaard, "references/alleen-in-standaard.md", "# s\n")
        uit = self.draai("--dry-run")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertIn("buildflow/references/alleen-in-standaard.md", self.namen())

    def test_niet_bestaande_skillmap_geeft_fout_en_geen_zip(self):
        weg = os.path.join(self.tmp, "bestaat-niet")
        uit = self.draai("--dry-run", "--src", weg)
        self.assertNotEqual(uit.returncode, 0)
        self.assertIn(weg, uit.stderr)
        self.assertGeenZip()

    def test_skillmap_zonder_skill_md_geeft_fout_en_geen_zip(self):
        leeg = os.path.join(self.tmp, "leeg")
        schrijf(leeg, "README.md", "# geen skill\n")
        uit = self.draai("--dry-run", "--src", leeg)
        self.assertNotEqual(uit.returncode, 0)
        self.assertIn(leeg, uit.stderr)
        self.assertGeenZip()

    def assertGeenZip(self):
        dist = os.path.join(self.repo, "dist")
        rest = os.listdir(dist) if os.path.isdir(dist) else []
        self.assertEqual(rest, [], f"er is iets achtergebleven in dist/: {rest}")

    def test_twee_keer_bouwen_geeft_dezelfde_lijst_en_overschrijft(self):
        self.bouw()
        eerste = sorted(self.namen())
        with open(self.zip, "ab") as f:  # oude zip herkenbaar maken
            f.write(b"oud")
        self.bouw()
        self.assertEqual(sorted(self.namen()), eerste)
        with open(self.zip, "rb") as f:
            self.assertFalse(f.read().endswith(b"oud"), "de oude zip is niet overschreven")


class Inhoud(ReleaseBasis):
    def test_precies_een_map_buildflow_met_verwachte_inhoud(self):
        self.bouw()
        namen = self.namen()
        for n in namen:
            self.assertTrue(n.startswith("buildflow/"), n)
        for rel in ("SKILL.md", "README.md", "pricing.json", "LICENSE"):
            self.assertIn("buildflow/" + rel, namen)
        for map_ in ("references/", "scripts/", "assets/"):
            self.assertTrue(any(n.startswith("buildflow/" + map_) and n != "buildflow/" + map_
                                for n in namen), f"buildflow/{map_} ontbreekt of is leeg")

    def test_sluit_cache_en_verborgen_bestanden_uit(self):
        self.bouw()
        for n in self.namen():
            delen = [d for d in n.split("/") if d]
            self.assertNotIn("__pycache__", delen, n)
            self.assertFalse(n.endswith(".pyc"), n)
            self.assertNotIn(".DS_Store", delen, n)
            self.assertFalse(any(d.startswith(".") for d in delen), n)

    def test_license_in_zip_is_gelijk_aan_repo_license(self):
        self.bouw()
        with zipfile.ZipFile(self.zip) as z, open(LICENSE, "rb") as f:
            self.assertEqual(z.read("buildflow/LICENSE"), f.read())

    def test_license_in_skillmap_overschrijft_repo_license_niet(self):
        schrijf(self.skill, "LICENSE", "Andere licentie, niet MIT.\n")
        self.bouw()
        namen = self.namen()
        self.assertEqual(namen.count("buildflow/LICENSE"), 1)
        with zipfile.ZipFile(self.zip) as z, open(LICENSE, "rb") as f:
            self.assertEqual(z.read("buildflow/LICENSE"), f.read())


class ExacteInhoud(ReleaseBasis):
    VERWACHT = {"buildflow/" + rel for rel in NEP_SKILL} | {"buildflow/LICENSE"}

    def test_zip_bevat_precies_de_verwachte_bestanden(self):
        self.bouw()
        namen = self.namen()
        self.assertEqual(len(namen), len(set(namen)), f"dubbele namen: {namen}")
        self.assertEqual(set(namen), self.VERWACHT)

    def test_zip_is_leesbaar_voor_iedereen_0644(self):
        self.bouw()
        self.assertEqual(stat.S_IMODE(os.stat(self.zip).st_mode), 0o644)


class Weigeren(ReleaseBasis):
    """Situaties waarin het script moet stoppen zonder zip."""

    def weigert(self, *namen_in_fout):
        uit = self.draai("--dry-run", "--src", self.skill)
        self.assertNotEqual(uit.returncode, 0, "bouw had geweigerd moeten worden")
        for naam in namen_in_fout:
            self.assertIn(naam, uit.stderr)
        dist = os.path.join(self.repo, "dist")
        rest = os.listdir(dist) if os.path.isdir(dist) else []
        self.assertEqual(rest, [], f"er is iets achtergebleven in dist/: {rest}")
        return uit

    def test_symlink_naar_prive_bestand_buiten_de_skill_wordt_geweigerd(self):
        prive = schrijf(self.tmp, "prive/geheim.md", "GEHEIME INHOUD\n")
        link = os.path.join(self.skill, "references", "lek.md")
        os.symlink(prive, link)
        self.weigert(link)

    def test_symlink_naar_map_wordt_geweigerd(self):
        schrijf(self.tmp, "prive/map/x.md", "GEHEIM\n")
        link = os.path.join(self.skill, "references", "extra")
        os.symlink(os.path.join(self.tmp, "prive", "map"), link)
        self.weigert(link)

    def test_symlink_op_verplichte_plek_wordt_geweigerd(self):
        pad = os.path.join(self.skill, "pricing.json")
        echt = schrijf(self.tmp, "elders/pricing.json", "{}\n")
        os.remove(pad)
        os.symlink(echt, pad)
        self.weigert(pad)

    def test_bestand_buiten_allowlist_wordt_geweigerd_met_naam(self):
        schrijf(self.skill, "notities.txt", "privé\n")
        schrijf(self.skill, "scripts/sub/x.py", "x\n")
        schrijf(self.skill, "references/plaatje.png", b"\x89PNG")
        self.weigert("notities.txt", "scripts/sub/x.py", "references/plaatje.png")

    def test_ontbrekende_verplichte_onderdelen_worden_genoemd(self):
        for rel in ("SKILL.md", "pricing.json", "scripts/bf.py", "scripts/gate_hook.py",
                    "assets/viewer.html"):
            with self.subTest(rel=rel):
                pad = os.path.join(self.skill, *rel.split("/"))
                with open(pad, "rb") as f:
                    bewaard = f.read()
                os.remove(pad)
                try:
                    self.weigert(rel)
                finally:
                    schrijf(self.skill, rel, bewaard)

    def test_references_zonder_md_wordt_geweigerd(self):
        os.remove(os.path.join(self.skill, "references", "a.md"))
        self.weigert("references")


class ZonderBijwerkingen(ReleaseBasis):
    def test_skillmap_is_na_bouwen_ongewijzigd(self):
        voor = snapshot(self.skill)
        self.bouw()
        self.assertEqual(snapshot(self.skill), voor)

    def test_dry_run_roept_geen_gh_en_geen_git_aan(self):
        self.bouw()
        inhoud = ""
        if os.path.exists(self.log):
            with open(self.log, encoding="utf-8") as f:
                inhoud = f.read()
        self.assertEqual(inhoud, "", f"gh/git aangeroepen:\n{inhoud}")


    def test_zonder_dry_run_stopt_zonder_zip_en_zonder_gh_of_git(self):
        uit = self.draai("--src", self.skill)
        self.assertNotEqual(uit.returncode, 0)
        self.assertIn("--dry-run", uit.stderr)
        dist = os.path.join(self.repo, "dist")
        self.assertFalse(os.path.exists(dist), "zonder --dry-run is dist/ aangemaakt")
        inhoud = ""
        if os.path.exists(self.log):
            with open(self.log, encoding="utf-8") as f:
                inhoud = f.read()
        self.assertEqual(inhoud, "", f"gh/git aangeroepen:\n{inhoud}")


class EchteSkill(unittest.TestCase):
    """De echte skillmap moet door de allowlist en de verplichte-onderdelencheck komen."""

    def test_echte_skillmap_levert_alle_verwachte_bestanden(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        try:
            import release
        finally:
            sys.path.pop(0)
        if not release.STANDAARD_SRC.is_dir():
            self.skipTest(f"skillmap niet gevonden: {release.STANDAARD_SRC}")
        namen = [n for n, _ in release.skillbestanden(release.STANDAARD_SRC)]
        for rel in ("SKILL.md", "README.md", "pricing.json", "scripts/bf.py",
                    "scripts/gate_hook.py", "assets/viewer.html",
                    "references/gate-review.md"):
            self.assertIn(rel, namen)
        self.assertFalse(any("__pycache__" in n or n.endswith(".pyc") for n in namen), namen)


class RepoBestanden(unittest.TestCase):
    def test_license_is_mit_met_copyrightregel(self):
        self.assertTrue(os.path.isfile(LICENSE), "LICENSE in de repo-root bestaat niet")
        with open(LICENSE, encoding="utf-8") as f:
            tekst = f.read()
        self.assertTrue(tekst.startswith("MIT License"), tekst[:40])
        self.assertIn("Copyright (c) 2026 Joep van Abeelen", tekst)

    def test_dist_staat_in_gitignore(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            regels = [r.strip() for r in f]
        self.assertTrue({"dist/", "/dist/"} & set(regels), "geen regel dist/ in .gitignore")
        uit = subprocess.run(["git", "check-ignore", "-q", "dist/buildflow.zip"], cwd=ROOT)
        self.assertEqual(uit.returncode, 0, "git negeert dist/buildflow.zip niet")


if __name__ == "__main__":
    unittest.main()
