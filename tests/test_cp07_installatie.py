"""cp07: de gebouwde zip installeren zoals een nieuwe gebruiker dat doet, in een lege HOME.

De zip wordt gebouwd met scripts/release.py --dry-run uit de echte skillbron, in een
tijdelijke kopie van de repo-indeling (zoals in cp05 en cp06), met gh/git-stubs op PATH.
Daarna voeren de tests de commando's uit die op de pagina staan, gelezen uit index.html,
zodat een wijziging op de pagina deze test raakt.

Veiligheid: elk commando draait met een expliciete cwd en een HOME die allebei onder de
tijdelijke map van het systeem liggen. De omgeving wordt vanaf nul opgebouwd (alleen PATH,
HOME, LANG en wat de test zelf zet), zodat CLAUDE_PROJECT_DIR, BUILDFLOW_ROOT en dergelijke
uit de shell van de ontwikkelaar niet meedoen. Alles wordt na afloop opgeruimd.

Ontbreekt unzip op het systeem, dan zet de test een klein unzip-script vooraan op PATH dat
met zipfile hetzelfde doet voor 'unzip -o <zip> -d <map>'. De commando's zelf blijven gelijk.
"""
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tests.check_facts import skill_bron
from tests.check_site import INDEX, ROOT, lees

SCRIPT = os.path.join(ROOT, "scripts", "release.py")
LICENSE = os.path.join(ROOT, "LICENSE")
ECHTE_SKILLS = os.path.join(os.path.expanduser("~"), ".claude", "skills")

VERWACHT = ("SKILL.md", "scripts/bf.py", "scripts/gate_hook.py", "references",
            "assets/viewer.html")

UNZIP_VERVANGER = r'''#!{python}
import os, sys, zipfile
args = sys.argv[1:]
if "-o" in args:
    args.remove("-o")
doel = "."
if "-d" in args:
    i = args.index("-d")
    doel = args[i + 1]
    del args[i:i + 2]
with zipfile.ZipFile(args[0]) as z:
    z.extractall(doel)
'''

PYTHON_LOGGER = '#!/bin/sh\necho "$@" >> "{log}"\nexec "{python}" "$@"\n'


# ---------- veiligheid ----------

def tijdelijke_basis():
    return os.path.realpath(tempfile.gettempdir())


def eis_tijdelijk(pad):
    """Stop meteen als een pad leeg is of niet onder de tijdelijke map van het systeem valt."""
    if not pad or not str(pad).strip():
        raise AssertionError("leeg pad voor cwd of HOME")
    echt = os.path.realpath(pad)
    basis = tijdelijke_basis()
    if not echt.startswith(basis + os.sep):
        raise AssertionError(f"{echt} ligt niet onder de tijdelijke map {basis}")
    if echt == os.path.realpath(os.path.expanduser("~")):
        raise AssertionError(f"{echt} is de echte homemap")
    return echt


def maak_uitvoerbaar(pad):
    os.chmod(pad, os.stat(pad).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def schrijf(pad, inhoud):
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "w", encoding="utf-8") as f:
        f.write(inhoud)
    return pad


# ---------- de pagina ----------

def codeblokken():
    tekst = lees(INDEX)
    return [html.unescape(b) for b in re.findall(r"<pre><code>(.*?)</code></pre>", tekst, re.S)]


def home_uitpakblok():
    """Het blok met 'mkdir -p ~/.claude/skills' en de unzip-regel uit de installatiestappen."""
    for blok in codeblokken():
        if "unzip" in blok and "~/.claude/skills" in blok:
            return blok.strip()
    raise AssertionError("geen codeblok met unzip naar ~/.claude/skills in index.html")


def doctorregel_home():
    for blok in codeblokken():
        b = blok.strip()
        if b.startswith("python3") and "bf.py doctor" in b and "~/.claude/skills" in b:
            return b
    raise AssertionError("geen codeblok 'python3 ~/.claude/skills/.../bf.py doctor' in index.html")


def projectblok():
    for blok in codeblokken():
        if "unzip" in blok and ".claude/skills" in blok and "~/.claude" not in blok:
            return [r.strip() for r in blok.strip().splitlines() if r.strip()]
    raise AssertionError("geen codeblok voor de installatie in een project in index.html")


# ---------- SKILL.md ----------

def hookregels(skill_md):
    return re.findall(r"^\s*command:\s*'(.*)'\s*$", skill_md, re.M)


def stop_hookregel(skill_md):
    m = re.search(r"^hooks:\n(.*?)^---", skill_md, re.M | re.S)
    if not m:
        raise AssertionError("geen hooks in de frontmatter van SKILL.md")
    stop = re.search(r"^\s+Stop:\n(.*?)(?=^\s+\w+:\n|\Z)", m.group(1), re.M | re.S)
    if not stop:
        raise AssertionError("geen Stop-hook in de frontmatter van SKILL.md")
    regels = hookregels(stop.group(1))
    if not regels:
        raise AssertionError("de Stop-hook in SKILL.md heeft geen command-regel")
    return regels[0]


def eerste_hookpad(regel):
    m = re.search(r'f="([^"]+)"', regel)
    if not m:
        raise AssertionError(f"geen f=\"...\" in de hook-regel: {regel}")
    return m.group(1)


def snapshot(map_):
    uit = {}
    if not os.path.isdir(map_):
        return uit
    uit["."] = os.stat(map_).st_mtime_ns
    for wortel, mappen, namen in os.walk(map_):
        for naam in mappen + namen:
            pad = os.path.join(wortel, naam)
            try:
                st = os.lstat(pad)
            except FileNotFoundError:
                continue
            uit[os.path.relpath(pad, map_)] = (st.st_size, st.st_mtime_ns)
    return uit


def bestanden_in(map_):
    uit = {}
    for wortel, _, namen in os.walk(map_):
        for naam in namen:
            pad = os.path.join(wortel, naam)
            with open(pad, "rb") as f:
                uit[os.path.relpath(pad, map_).replace(os.sep, "/")] = \
                    hashlib.sha256(f.read()).hexdigest()
    return uit


class InstallatieBasis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.klas_tmp = eis_tijdelijk(tempfile.mkdtemp(prefix="bf-cp07-zip-"))
        try:
            cls.zip = cls.bouw_zip(cls.klas_tmp)
        except Exception:
            shutil.rmtree(cls.klas_tmp, True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.klas_tmp, True)

    @classmethod
    def bouw_zip(cls, tmp):
        bron = skill_bron()
        if not os.path.isfile(os.path.join(bron, "SKILL.md")):
            raise unittest.SkipTest(f"skillbron niet gevonden: {bron}")
        assert os.path.isfile(SCRIPT), "scripts/release.py bestaat niet"
        repo = eis_tijdelijk(os.path.join(tmp, "repo"))
        os.makedirs(os.path.join(repo, "scripts"))
        shutil.copy2(SCRIPT, os.path.join(repo, "scripts", "release.py"))
        shutil.copy2(LICENSE, os.path.join(repo, "LICENSE"))
        fakebin = os.path.join(tmp, "fakebin")
        for naam in ("gh", "git"):
            maak_uitvoerbaar(schrijf(os.path.join(fakebin, naam),
                                     f'#!/bin/sh\necho "{naam} $*" >> "{tmp}/aanroepen.log"\n'
                                     "exit 0\n"))
        env = {"PATH": fakebin + os.pathsep + os.environ.get("PATH", ""),
               "HOME": eis_tijdelijk(os.path.join(tmp, "bouwhome")), "LANG": "en_US.UTF-8"}
        os.makedirs(env["HOME"])
        uit = subprocess.run([sys.executable, os.path.join("scripts", "release.py"),
                              "--dry-run", "--src", bron],
                             cwd=repo, env=env, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=120)
        assert uit.returncode == 0, uit.stderr
        zip_ = os.path.join(repo, "dist", "buildflow.zip")
        assert os.path.isfile(zip_), "release.py --dry-run maakte geen dist/buildflow.zip"
        return zip_

    def setUp(self):
        self.tmp = eis_tijdelijk(tempfile.mkdtemp(prefix="bf-cp07-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.map_("home")
        self.downloads = self.map_("downloads")
        self.project = self.map_("project")
        shutil.copy2(self.zip, os.path.join(self.downloads, "buildflow.zip"))
        self.fakebin = self.map_("fakebin")
        self.pylog = os.path.join(self.tmp, "python3.log")
        echte_python = shutil.which("python3") or sys.executable
        maak_uitvoerbaar(schrijf(os.path.join(self.fakebin, "python3"),
                                 PYTHON_LOGGER.format(log=self.pylog, python=echte_python)))
        if not shutil.which("unzip"):
            maak_uitvoerbaar(schrijf(os.path.join(self.fakebin, "unzip"),
                                     UNZIP_VERVANGER.format(python=sys.executable)))

    def map_(self, naam):
        pad = eis_tijdelijk(os.path.join(self.tmp, naam))
        os.makedirs(pad)
        return pad

    def omgeving(self, **extra):
        env = {"PATH": self.fakebin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": eis_tijdelijk(self.home), "LANG": "en_US.UTF-8",
               "TMPDIR": eis_tijdelijk(self.tmp)}
        env.update(extra)
        return env

    def sh(self, commando, cwd, invoer="", **extra):
        cwd = eis_tijdelijk(cwd)
        return subprocess.run(["/bin/sh", "-c", commando], cwd=cwd, env=self.omgeving(**extra),
                              input=invoer, capture_output=True, text=True, timeout=120)

    def installeer_home(self):
        uit = self.sh(home_uitpakblok(), self.downloads)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        return uit

    def skillmap_home(self):
        return os.path.join(self.home, ".claude", "skills", "buildflow")

    def hookregel(self, skillmap):
        with open(os.path.join(skillmap, "SKILL.md"), encoding="utf-8") as f:
            return stop_hookregel(f.read())

    def hook_invoer(self):
        return json.dumps({"session_id": "cp07-test", "hook_event_name": "Stop",
                           "cwd": self.project, "stop_hook_active": False})

    def python_aanroepen(self):
        if not os.path.isfile(self.pylog):
            return ""
        with open(self.pylog, encoding="utf-8") as f:
            return f.read()


class HomeInstallatie(InstallatieBasis):
    def test_uitpakcommando_van_de_pagina_installeert_de_skill_in_een_lege_home(self):
        blok = home_uitpakblok()
        self.assertIn("mkdir -p ~/.claude/skills", blok)
        self.assertIn("unzip -o buildflow.zip -d ~/.claude/skills", blok)
        self.assertEqual(os.listdir(self.home), [])
        self.installeer_home()
        for rel in VERWACHT:
            pad = os.path.join(self.skillmap_home(), *rel.split("/"))
            self.assertTrue(os.path.exists(pad), f"{rel} ontbreekt na het uitpakken: {pad}")
        self.assertTrue(os.listdir(os.path.join(self.skillmap_home(), "references")),
                        "references/ is leeg")
        self.assertEqual(os.listdir(os.path.join(self.home, ".claude", "skills")), ["buildflow"])

    def test_uitpakpad_is_het_eerste_pad_dat_de_hook_zoekt(self):
        self.installeer_home()
        regel = self.hookregel(self.skillmap_home())
        pad = eerste_hookpad(regel)
        self.assertEqual(pad, "$HOME/.claude/skills/buildflow/scripts/gate_hook.py")
        echt = pad.replace("$HOME", self.home)
        self.assertTrue(os.path.isfile(echt), f"{echt} bestaat niet na het uitpakken")

    def test_nogmaals_uitpakken_over_bestaande_installatie_werkt_zonder_vragen(self):
        self.installeer_home()
        # een aangepast bestand moet terugkomen zoals het in de zip staat
        with open(os.path.join(self.skillmap_home(), "SKILL.md"), "a", encoding="utf-8") as f:
            f.write("\nlokaal aangepast\n")
        uit = subprocess.run(["/bin/sh", "-c", home_uitpakblok()],
                             cwd=eis_tijdelijk(self.downloads), env=self.omgeving(),
                             stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=120)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        uitgepakt = bestanden_in(os.path.join(self.home, ".claude", "skills"))
        with zipfile.ZipFile(self.zip) as z:
            inzip = {n: hashlib.sha256(z.read(n)).hexdigest()
                     for n in z.namelist() if not n.endswith("/")}
        self.assertEqual(uitgepakt, inzip)

    def test_bf_doctor_in_lege_projectmap_eindigt_met_0_en_meldt_no_active_run(self):
        self.installeer_home()
        regel = doctorregel_home()
        self.assertEqual(regel, "python3 ~/.claude/skills/buildflow/scripts/bf.py doctor")
        uit = self.sh(regel, self.project)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertIn("no active run", uit.stdout)
        self.assertIn(f"skill dir: {self.skillmap_home()}", uit.stdout,
                      "doctor draaide niet uit de installatie in de tijdelijke HOME")

    def test_hookregel_uit_skill_md_eindigt_met_0_zonder_actieve_run(self):
        self.installeer_home()
        regel = self.hookregel(self.skillmap_home())
        uit = self.sh(regel, self.project, invoer=self.hook_invoer(),
                      CLAUDE_PROJECT_DIR=self.project)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        verwacht = os.path.join(self.skillmap_home(), "scripts", "gate_hook.py")
        self.assertIn(verwacht, self.python_aanroepen(),
                      "de hook draaide gate_hook.py niet uit de HOME-installatie")
        self.assertFalse(os.path.exists(os.path.join(self.project, ".buildflow")),
                         "de hook maakte iets aan in een project zonder run")


class ProjectInstallatie(InstallatieBasis):
    def test_projectblok_van_de_pagina_installeert_en_doctor_draait(self):
        regels = projectblok()
        self.assertTrue(regels[0].startswith("cd "), regels[0])
        curl = [r for r in regels if r.startswith("curl ")]
        self.assertEqual(len(curl), 1, regels)
        self.assertIn("-o buildflow.zip", curl[0])
        # cd vervangen door een expliciete cwd, curl door de gebouwde zip op dezelfde plek
        shutil.copy2(self.zip, os.path.join(self.project, "buildflow.zip"))
        rest = [r for r in regels[1:] if not r.startswith("curl ")]
        uit = self.sh(" && ".join(rest), self.project)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        skillmap = os.path.join(self.project, ".claude", "skills", "buildflow")
        for rel in VERWACHT:
            self.assertTrue(os.path.exists(os.path.join(skillmap, *rel.split("/"))), rel)
        self.assertFalse(os.path.exists(os.path.join(self.project, "buildflow.zip")),
                         "rm buildflow.zip uit het blok is niet uitgevoerd")
        self.assertIn("no active run", uit.stdout)
        self.assertEqual(os.listdir(self.home), [], "de projectinstallatie schreef in HOME")

    def test_hookregel_eindigt_met_0_bij_projectinstallatie_zonder_home_installatie(self):
        with zipfile.ZipFile(self.zip) as z:
            z.extractall(os.path.join(self.project, ".claude", "skills"))
        skillmap = os.path.join(self.project, ".claude", "skills", "buildflow")
        regel = self.hookregel(skillmap)
        self.assertEqual(os.listdir(self.home), [])
        uit = self.sh(regel, self.project, invoer=self.hook_invoer(),
                      CLAUDE_PROJECT_DIR=self.project)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertIn(os.path.join(skillmap, "scripts", "gate_hook.py"), self.python_aanroepen(),
                      "de hook draaide gate_hook.py niet uit de projectmap")


class Isolatie(InstallatieBasis):
    def test_installatie_raakt_de_echte_claude_skills_niet(self):
        voor = snapshot(ECHTE_SKILLS)
        self.installeer_home()
        self.sh(doctorregel_home(), self.project)
        self.sh(self.hookregel(self.skillmap_home()), self.project, invoer=self.hook_invoer(),
                CLAUDE_PROJECT_DIR=self.project)
        shutil.copy2(self.zip, os.path.join(self.project, "buildflow.zip"))
        rest = [r for r in projectblok()[1:] if not r.startswith("curl ")]
        self.sh(" && ".join(rest), self.project)
        self.assertEqual(snapshot(ECHTE_SKILLS), voor, "de echte ~/.claude/skills is veranderd")
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude", "skills", "buildflow")),
                        "de installatie belandde niet in de tijdelijke HOME")


if __name__ == "__main__":
    unittest.main()
