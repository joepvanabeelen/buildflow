"""cp11: main bevat alleen de skill, de website staat op branch site.

Groep 1 maakt met echte git een wegwerprepo in een tijdelijke map (zonder globale git-config)
en toetst release.py --skill-branch en maak_skillcommit: de commit bevat precies buildflow/
(gelijk aan de zip), README.md en LICENSE, en de werkkopie, index en branches blijven
ongemoeid. Groep 2 toetst met de stubs uit cp06 dat --publish de tag op de skillcommit zet
en site, main en de tag in één atomische push meestuurt. Groep 3 leest de echte repo: de
skillbranch (BUILDFLOW_SKILL_TAK, anders skill-main als die bestaat, anders main) bevat
alleen de skill en niets persoonlijks, en site bevat de website zonder buildflow/.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests import test_cp05_release as cp05
from tests import test_cp06_release as cp06
from tests import test_cp10_publiceren as cp10
from tests.check_site import ROOT

VERSIE = cp06.VERSIE
SKILLCOMMIT = "f" * 40
OUDE_MAIN = "d" * 40
TOEGESTAAN_OP_MAIN = {"README.md", "LICENSE"}
NOREPLY = "1+tester@users.noreply.github.com"


def schone_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL=NOREPLY,
               GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL=NOREPLY)
    return env


class Wegwerprepo(cp05.ReleaseBasis):
    """Echte git in een tijdelijke repo met het echte script, zonder stubs op PATH."""

    def setUp(self):
        super().setUp()
        self.maak_repo()
        shutil.copy2(os.path.join(ROOT, "scripts", "README-main.md"),
                     os.path.join(self.repo, "scripts", "README-main.md"))
        cp05.schrijf(self.repo, "index.html", "<!doctype html><title>site</title>\n")
        self.git("init", "-q", "-b", "site")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "site")

    def git(self, *args):
        uit = subprocess.run(["git", *args], cwd=self.repo, env=schone_env(),
                             capture_output=True, timeout=60)
        self.assertEqual(uit.returncode, 0, uit.stderr.decode())
        return uit.stdout.decode().strip()

    def skill_branch(self, naam="skill", *extra):
        env = schone_env()
        env.pop("BUILDFLOW_SKILL_SRC", None)
        return subprocess.run([sys.executable, "scripts/release.py", "--skill-branch", naam,
                               "--src", self.skill, *extra], cwd=self.repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def boom(self, ref):
        return sorted(self.git("ls-tree", "-r", "--name-only", ref).splitlines())

    def zipinhoud(self):
        with zipfile.ZipFile(self.zip) as z:
            return {i.filename: z.read(i) for i in z.infolist()}


class SkillBranch(Wegwerprepo):
    def test_branch_bevat_precies_zip_plus_readme_en_license(self):
        uit = self.skill_branch("skill", "-m", "alleen de skill")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        zipinhoud = self.zipinhoud()
        self.assertEqual(self.boom("skill"),
                         sorted(list(zipinhoud) + ["README.md", "LICENSE"]))
        for naam, data in zipinhoud.items():
            with self.subTest(naam=naam):
                blob = subprocess.run(["git", "show", f"skill:{naam}"], cwd=self.repo,
                                      capture_output=True, env=schone_env()).stdout
                self.assertEqual(blob, data)
        readme = subprocess.run(["git", "show", "skill:README.md"], cwd=self.repo,
                                capture_output=True, env=schone_env()).stdout
        with open(os.path.join(ROOT, "scripts", "README-main.md"), "rb") as f:
            self.assertEqual(readme, f.read())
        with open(cp05.LICENSE, "rb") as f:
            lic = f.read()
        self.assertEqual(subprocess.run(["git", "show", "skill:LICENSE"], cwd=self.repo,
                                        capture_output=True, env=schone_env()).stdout, lic)
        # geen ouder, het opgegeven bericht, auteur uit de git-config
        self.assertEqual(self.git("log", "--format=%P|%s|%ae", "skill"),
                         f"|alleen de skill|{NOREPLY}")

    def test_niets_van_de_site_of_ruis_op_de_skillbranch(self):
        self.assertEqual(self.skill_branch().returncode, 0)
        for pad in self.boom("skill"):
            with self.subTest(pad=pad):
                self.assertTrue(pad in TOEGESTAAN_OP_MAIN or pad.startswith("buildflow/"), pad)
                self.assertNotIn(".DS_Store", pad)
                self.assertFalse(pad.endswith(".pyc"), pad)

    def test_werkkopie_index_en_huidige_branch_blijven_ongemoeid(self):
        kop = self.git("rev-parse", "HEAD")
        self.assertEqual(self.skill_branch().returncode, 0)
        self.assertEqual(self.git("branch", "--show-current"), "site")
        self.assertEqual(self.git("rev-parse", "HEAD"), kop)
        # dist/ is niet gecommit en staat niet in .gitignore van deze wegwerprepo
        status = [r for r in self.git("status", "--porcelain").splitlines()
                  if not r.endswith("dist/")]
        self.assertEqual(status, [])
        self.assertEqual(self.boom("site"), self.boom(kop))

    def test_weigert_bestaande_branch_en_laat_hem_staan(self):
        kop = self.git("rev-parse", "HEAD")
        uit = self.skill_branch("site")
        self.assertNotEqual(uit.returncode, 0)
        self.assertIn("bestaat al", uit.stderr)
        self.assertEqual(self.git("rev-parse", "site"), kop)

    def test_weigert_samen_met_publish(self):
        env = schone_env()
        uit = subprocess.run([sys.executable, "scripts/release.py", "--skill-branch", "x",
                              "--version", VERSIE, "--publish", "--src", self.skill],
                             cwd=self.repo, env=env, capture_output=True, text=True,
                             timeout=60, input=VERSIE + "\n")
        self.assertNotEqual(uit.returncode, 0)
        self.assertNotIn("Traceback", uit.stderr)
        self.assertEqual(subprocess.run(["git", "rev-parse", "--verify", "--quiet", "x"],
                                        cwd=self.repo, env=env).returncode, 1)

    def test_skillcommit_met_ouder_komt_bovenop_die_ouder(self):
        self.assertEqual(self.skill_branch().returncode, 0)
        oud = self.git("rev-parse", "skill")
        release = cp06.importeer_release()
        bestanden = release.skillboom([("SKILL.md", b"nieuw\n")], b"# r\n", b"MIT\n")
        with mock.patch.object(release, "REPO", Path(self.repo)), \
                mock.patch.dict(os.environ, schone_env(), clear=True):
            nieuw = release.maak_skillcommit(bestanden, oud, "Release v9.9.9")
        self.assertEqual(self.git("log", "--format=%P|%s", "-1", nieuw),
                         f"{oud}|Release v9.9.9")
        self.assertEqual(self.boom(nieuw), ["LICENSE", "README.md", "buildflow/SKILL.md"])
        # alleen een commitobject: geen branch is verschoven
        self.assertEqual(self.git("rev-parse", "skill"), oud)


class PublicerenNaarTweeBranches(cp06.Cp06Basis):
    def publiceer(self, **kw):
        uit = self.release("--publish", invoer=VERSIE + "\n", **kw)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        return uit, self.logtekst().splitlines()

    def test_skillcommit_bovenop_origin_main_voor_iets_verandert(self):
        _, log = self.publiceer()
        commit_tree = [i for i, r in enumerate(log) if r.startswith("git commit-tree")]
        self.assertEqual(len(commit_tree), 1, log)
        self.assertIn(f"-p {OUDE_MAIN}", log[commit_tree[0]])
        self.assertIn(f"-m Release {VERSIE}", log[commit_tree[0]])
        schrijvend = [i for i, r in enumerate(log)
                      if r.split()[:2] in (["git", "add"], ["git", "commit"],
                                           ["git", "tag"], ["git", "push"])
                      and "--list" not in r]
        self.assertLess(commit_tree[0], min(schrijvend), log)

    def test_tag_staat_op_de_skillcommit_niet_op_site(self):
        _, log = self.publiceer()
        tag = [r for r in log if r.startswith(f"git tag -a {VERSIE}")]
        self.assertEqual(len(tag), 1, log)
        self.assertTrue(tag[0].endswith(SKILLCOMMIT), tag[0])

    def test_een_atomische_push_van_site_main_en_tag(self):
        _, log = self.publiceer()
        pushes = [r for r in log if r.startswith("git push")]
        self.assertEqual(pushes, [f"git push --atomic origin site {SKILLCOMMIT}:refs/heads/main "
                                  f"refs/tags/{VERSIE}"])
        self.assertNotIn("--force", pushes[0])

    def test_releasecommit_op_site_neemt_alleen_index_html_mee(self):
        _, log = self.publiceer()
        commit = [r for r in log if r.split()[:2] == ["git", "commit"]]
        self.assertEqual(len(commit), 1, log)
        self.assertTrue(commit[0].endswith("-- index.html"), commit[0])

    def test_plan_noemt_de_skillcommit_en_main(self):
        uit = self.release("--publish", invoer="nee\n")
        self.assertNotEqual(uit.returncode, 0)
        self.assertIn(f"skillcommit {SKILLCOMMIT[:12]} op main", uit.stdout)
        self.assertEqual(cp06.schrijvende_aanroepen(self.logtekst()), [], self.logtekst())

    def test_zonder_readme_voor_main_weigert_het_voor_de_vraag(self):
        self.zonder_main_readme = True
        uit = self.release("--publish", invoer=VERSIE + "\n")
        self.assertNotEqual(uit.returncode, 0)
        self.assertIn("README-main.md", uit.stderr)
        self.assertNotIn(f"Typ {VERSIE}", uit.stdout)
        self.assertEqual(cp06.schrijvende_aanroepen(self.logtekst()), [])


# ---------- groep 3: de echte repo ----------

def git(*args):
    return cp10.git(*args).decode("utf-8")


def ref_bestaat(ref):
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=ROOT,
                          capture_output=True).returncode == 0


def skill_tak():
    tak = os.environ.get("BUILDFLOW_SKILL_TAK")
    if tak:
        return tak
    return "skill-main" if ref_bestaat("refs/heads/skill-main") else "main"


class EchteTakken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(ROOT, ".git")):
            raise unittest.SkipTest("geen git-checkout")
        cls.tak = skill_tak()
        if not ref_bestaat(cls.tak):
            raise AssertionError(f"skillbranch {cls.tak} bestaat niet")

    def paden(self, ref):
        return git("ls-tree", "-r", "--name-only", ref).splitlines()

    def test_skillbranch_bevat_alleen_de_skill(self):
        paden = self.paden(self.tak)
        buiten = [p for p in paden
                  if p not in TOEGESTAAN_OP_MAIN and not p.startswith("buildflow/")]
        self.assertEqual(buiten, [], f"{self.tak} bevat meer dan de skill")
        for verplicht in ("README.md", "LICENSE", "buildflow/SKILL.md", "buildflow/LICENSE",
                          "buildflow/scripts/bf.py", "buildflow/assets/viewer.html"):
            self.assertIn(verplicht, paden)

    def test_hele_geschiedenis_van_de_skillbranch_bevat_alleen_de_skill(self):
        uit = git("log", self.tak, "--format=", "--name-only", "--no-renames")
        buiten = sorted({p for p in uit.splitlines() if p.strip()
                         and p not in TOEGESTAAN_OP_MAIN and not p.startswith("buildflow/")})
        self.assertEqual(buiten, [], "de geschiedenis van de skillbranch bevat de website "
                         "nog; main moet vervangen worden, niet aangevuld")

    def test_skill_op_de_branch_is_gelijk_aan_de_zip_uit_de_skillbron(self):
        src = os.environ.get("BUILDFLOW_SKILL_SRC") or os.path.join(
            os.path.dirname(ROOT), "skill-buildflow", "skills", "buildflow")
        if not os.path.isdir(src):
            self.skipTest(f"geen skillbron op {src}")
        release = cp06.importeer_release()
        with tempfile.TemporaryDirectory() as tmp:
            doel = Path(tmp) / "b.zip"
            release.bouw_zip(Path(src), Path(ROOT) / "LICENSE", doel)
            verwacht = {f"buildflow/{n}": d for n, d in release.zip_inhoud(doel)}
        op_tak = {p: cp10.git("show", f"{self.tak}:{p}") for p in self.paden(self.tak)
                  if p.startswith("buildflow/")}
        self.assertEqual(sorted(op_tak), sorted(verwacht))
        verschil = [p for p in verwacht if op_tak[p] != verwacht[p]]
        self.assertEqual(verschil, [], "wijkt af van de skillbron: " + ", ".join(verschil))

    def test_readme_en_license_van_main_komen_van_site(self):
        for pad, bron in (("README.md", "scripts/README-main.md"), ("LICENSE", "LICENSE")):
            with self.subTest(pad=pad):
                self.assertEqual(cp10.git("show", f"{self.tak}:{pad}"),
                                 cp10.git("show", f"HEAD:{bron}"))

    def test_privacyscan_over_de_skillbranch(self):
        meldingen = []
        for pad in self.paden(self.tak):
            meldingen += cp10.scan_inhoud(pad, cp10.git("show", f"{self.tak}:{pad}"))
        self.assertEqual(meldingen, [], "\n".join(meldingen))
        c = cp10.commits()
        self.assertEqual(cp10.metadata_fouten(c, cp10.taggers()), [])

    def test_site_bevat_de_website_zonder_skillmap(self):
        paden = self.paden("HEAD")
        self.assertIn("index.html", paden)
        self.assertIn(".nojekyll", paden)
        self.assertIn("scripts/README-main.md", paden)
        self.assertFalse([p for p in paden if p.startswith("buildflow/")])
        buiten = [p for p in paden if not cp10.in_publieke_set(p)]
        self.assertEqual(buiten, [])


if __name__ == "__main__":
    unittest.main()
