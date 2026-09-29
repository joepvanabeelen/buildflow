"""cp06: release.py vult versie, datum en grootte in op de pagina en publiceert pas na bevestiging.

Net als in cp05 draait het script in een tijdelijke kopie van de repo-indeling
(<tmp>/repo/scripts/release.py, LICENSE en index.html), zodat dist/ en de ingevulde pagina
in de tijdelijke map belanden en de echte repo niet wordt aangeraakt.

Er wordt niets gepubliceerd. gh en git staan als stubs vooraan op PATH; ze loggen hun
argumenten en geven alleen antwoord op leesvragen (bestaat de tag, bestaat de release).
Stdin krijgt altijd expliciete invoer (standaard leeg, dus EOF), zodat een bevestigingsvraag
nooit op de terminal van de ontwikkelaar wacht.

Afspraken die deze tests vastleggen:
- --date JJJJ-MM-DD zet de releasedatum vast (voor tests); zonder --date geldt vandaag.
- release.nl_datum(date) geeft '29 sep. 2026', los van de systeemlocale.
- release.kb(bytes) geeft de grootte in hele kB (1 kB = 1000 bytes, afgerond op het
  dichtstbijzijnde gehele getal), met minimaal '1 kB' voor een niet-lege zip.
"""
import datetime
import os
import re
import shutil
import stat
import sys
import subprocess
import unittest
import zipfile

from tests import test_cp05_release as cp05
from tests.check_site import INDEX, ROOT, Pagina, lees

SCRIPT = cp05.SCRIPT
VERSIE = "v1.0.0"
DATUM = "2026-09-29"
DATUM_NL = "29 sep. 2026"
DOWNLOAD = "https://github.com/joepvanabeelen/buildflow/releases/latest/download/buildflow.zip"

# Gedeeld stukje voor beide stubs: loggen, en een aanroep laten mislukken (NEP_FAAL) of
# onderbreken alsof de gebruiker Ctrl-C drukt (NEP_ONDERBREEK). Beide zijn een stuk tekst
# dat aan het begin van de gelogde regel moet staan, bv. "git push origin main".
STUB_KOP = r'''#!{python}
import fnmatch, os, signal, sys, time
args = sys.argv[1:]
regel = {naam!r} + " " + " ".join(args)
with open({log!r}, "a", encoding="utf-8") as f:
    f.write(regel + "\n")
faal = os.environ.get("NEP_FAAL", "")
if faal and regel.startswith(faal):
    print("nep-fout: " + regel, file=sys.stderr)
    sys.exit(1)
stop = os.environ.get("NEP_ONDERBREEK", "")
if stop and regel.startswith(stop):
    os.kill(os.getppid(), signal.SIGINT)
    time.sleep(10)
    sys.exit(130)
'''

# Standaard: op main, schone werkkopie, HEAD gelijk aan origin/main, origin op GitHub.
GIT_STUB = STUB_KOP + r'''
tag = os.environ.get("NEP_BESTAANDE_TAG", "")
cmd, rest = (args[0], args[1:]) if args else ("", [])
if cmd == "tag" and ("-l" in rest or "--list" in rest):
    patronen = [a for a in rest if not a.startswith("-")]
    if tag and any(fnmatch.fnmatch(tag, p) for p in patronen):
        print(tag)
elif cmd == "ls-remote":
    if tag and any(tag in a for a in rest):
        print("0" * 40 + "\trefs/tags/" + tag)
        sys.exit(0)
    sys.exit(2)
elif cmd == "branch" and "--show-current" in rest:
    print(os.environ.get("NEP_TAK", "main"))
elif cmd == "status":
    uit = os.environ.get("NEP_STATUS", "")
    if uit:
        print(uit)
elif cmd == "remote" and rest[:1] == ["get-url"] and rest[-1:] == ["origin"]:
    # fetch-URL (NEP_ORIGIN_URL) en push-URL (NEP_PUSH_URL, standaard gelijk aan de fetch-URL)
    fetch = os.environ.get("NEP_ORIGIN_URL",
                           "git@github.com:joepvanabeelen/buildflow.git")
    print(os.environ.get("NEP_PUSH_URL", fetch) if "--push" in rest else fetch)
elif cmd == "rev-parse":
    if rest == ["HEAD"]:
        print(os.environ.get("NEP_HEAD", "a" * 40))
    elif rest == ["refs/remotes/origin/main"]:
        print(os.environ.get("NEP_ORIGIN_MAIN", "a" * 40))
    else:
        print("onbekende rev-parse in stub: " + regel, file=sys.stderr)
        sys.exit(128)
sys.exit(0)
'''

GH_STUB = STUB_KOP + r'''
rel = os.environ.get("NEP_BESTAANDE_RELEASE", "")
if args[:2] == ["release", "view"]:
    if rel and rel in args[2:]:
        print("title:\t" + rel + "\ntag:\t" + rel)
        sys.exit(0)
    print("release not found", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
'''

RELEASE_VELD = re.compile(r'(<(\w+)[^>]*\sdata-release="[^"]*"[^>]*>)(.*?)(</\2>)', re.S)


def verwachte_kb(n):
    if n == 0:
        return "0 kB"
    return f"{max(1, int(n / 1000 + 0.5))} kB"


def importeer_release():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import release
    finally:
        sys.path.pop(0)
    return release


def zonder_releasetekst(html):
    return RELEASE_VELD.sub(lambda m: m.group(1) + m.group(4), html)


def schrijvende_aanroepen(log):
    """(soort, regel) voor elke aanroep die iets verandert of publiceert."""
    uit = []
    for regel in log.splitlines():
        delen = regel.split()
        if not delen:
            continue
        prog, args = delen[0], delen[1:]
        while args and args[0] in ("-C", "-c"):
            args = args[2:]
        if prog == "git" and args:
            cmd = args[0]
            if cmd in ("add", "commit", "push"):
                uit.append((cmd, regel))
            elif cmd == "tag" and len(args) > 1 and not {"-l", "--list"} & set(args):
                uit.append(("tag", regel))
        elif prog == "gh" and args[:1] == ["release"] and len(args) > 1 \
                and args[1] in ("create", "upload", "edit", "delete"):
            uit.append(("release " + args[1], regel))
    return uit


class Cp06Basis(cp05.ReleaseBasis):
    def setUp(self):
        super().setUp()
        # vervang de simpele stubs uit cp05 door stubs die leesvragen kunnen beantwoorden
        for naam, bron in (("git", GIT_STUB), ("gh", GH_STUB)):
            pad = cp05.schrijf(self.fakebin, naam,
                               bron.format(python=sys.executable, log=self.log, naam=naam))
            os.chmod(pad, 0o755)
        self.index = os.path.join(self.repo, "index.html")

    def maak_repo(self):
        super().maak_repo()
        if not os.path.isfile(self.index):
            shutil.copy2(INDEX, self.index)

    def draai(self, *args, env_extra=None, invoer=""):
        self.maak_repo()
        env = {k: v for k, v in os.environ.items()
               if k != "BUILDFLOW_SKILL_SRC" and not k.startswith("NEP_")}
        env["PATH"] = self.fakebin + os.pathsep + "/usr/bin:/bin"
        env.update(env_extra or {})
        return subprocess.run([sys.executable, os.path.join("scripts", "release.py"), *args],
                              cwd=self.repo, env=env, capture_output=True, text=True,
                              input=invoer, timeout=60)

    def release(self, *extra, **kw):
        return self.draai("--version", VERSIE, "--src", self.skill, "--date", DATUM, *extra, **kw)

    def pagina_html(self):
        with open(self.index, encoding="utf-8") as f:
            return f.read()

    def pagina_bytes(self):
        with open(self.index, "rb") as f:
            return f.read()

    def logtekst(self):
        if not os.path.exists(self.log):
            return ""
        with open(self.log, encoding="utf-8") as f:
            return f.read()

    def velden(self, html):
        return [e for e in Pagina(html).elementen() if e.attrs.get("data-release")]

    def assertKentOptie(self, optie):
        """Zonder deze optie slaagt een weigertest alleen omdat argparse de vlag niet kent."""
        uit = self.draai("--help")
        self.assertIn(optie, uit.stdout, f"release.py kent {optie} niet")

    def assertGeenTraceback(self, uit):
        self.assertNotIn("Traceback", uit.stderr, uit.stderr)


class Formatters(unittest.TestCase):
    def test_nederlandse_datum_los_van_locale(self):
        release = importeer_release()
        self.assertTrue(hasattr(release, "nl_datum"), "release.nl_datum ontbreekt")
        for dag, verwacht in ((datetime.date(2026, 9, 29), "29 sep. 2026"),
                              (datetime.date(2026, 5, 1), "1 mei 2026"),
                              (datetime.date(2026, 12, 31), "31 dec. 2026")):
            with self.subTest(dag=dag):
                self.assertEqual(release.nl_datum(dag), verwacht)

    def test_grootte_in_hele_kb_nooit_nul_voor_niet_lege_zip(self):
        release = importeer_release()
        self.assertTrue(hasattr(release, "kb"), "release.kb ontbreekt")
        for n, verwacht in ((0, "0 kB"), (1, "1 kB"), (512, "1 kB"), (1024, "1 kB"),
                            (1500, "2 kB"), (187_400, "187 kB")):
            with self.subTest(n=n):
                self.assertEqual(release.kb(n), verwacht)


class Paginastap(Cp06Basis):
    def test_version_vult_versie_datum_en_grootte_in_elk_veld(self):
        uit = self.release()
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertTrue(os.path.isfile(self.zip), "dist/buildflow.zip is niet gemaakt")
        grootte = verwachte_kb(os.path.getsize(self.zip))
        verwacht = {"versie": VERSIE, "datum": DATUM_NL, "grootte": grootte}
        velden = self.velden(self.pagina_html())
        self.assertGreaterEqual(len(velden), 5)
        for e in velden:
            soort = e.attrs["data-release"]
            with self.subTest(soort=soort):
                self.assertEqual(e.alle_tekst().strip(), verwacht[soort])

    def test_twee_keer_draaien_geeft_identieke_pagina(self):
        uit = self.release()
        self.assertEqual(uit.returncode, 0, uit.stderr)
        eerste = self.pagina_bytes()
        uit = self.release()
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertEqual(self.pagina_bytes(), eerste)

    def test_alleen_tekst_van_releasevelden_verandert(self):
        self.maak_repo()
        voor = self.pagina_html()
        uit = self.release()
        self.assertEqual(uit.returncode, 0, uit.stderr)
        na = self.pagina_html()
        self.assertNotEqual(na, voor, "index.html is niet ingevuld")
        self.assertEqual(zonder_releasetekst(na), zonder_releasetekst(voor),
                         "er is meer veranderd dan de tekst van data-release-elementen")
        self.assertEqual(Pagina(na).fouten, [])

    def test_ongeldige_versie_wordt_geweigerd_zonder_wijziging(self):
        self.assertKentOptie("--version")
        self.maak_repo()
        voor = self.pagina_bytes()
        for versie in ("1.0", "v1.0", "v1.0.0; rm", ""):
            with self.subTest(versie=versie):
                uit = self.draai("--version", versie, "--src", self.skill, "--date", DATUM)
                self.assertNotEqual(uit.returncode, 0)
                self.assertGeenTraceback(uit)
                self.assertEqual(self.pagina_bytes(), voor, "index.html is gewijzigd")
        self.assertEqual(self.logtekst(), "")

    def test_zonder_publish_geen_gh_of_git(self):
        uit = self.release()
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertEqual(self.logtekst(), "", f"gh/git aangeroepen:\n{self.logtekst()}")

    def test_downloadknoppen_blijven_naar_latest_wijzen_na_run(self):
        uit = self.release()
        self.assertEqual(uit.returncode, 0, uit.stderr)
        html = self.pagina_html()
        links = [e.attrs["href"] for e in Pagina(html).elementen()
                 if e.tag == "a" and "buildflow.zip" in (e.attrs.get("href") or "")]
        self.assertTrue(links, "geen downloadlink naar buildflow.zip")
        self.assertEqual(set(links), {DOWNLOAD})
        self.assertNotIn("releases/download/", html)

    def test_dry_run_laat_pagina_ongemoeid(self):
        self.maak_repo()
        voor = self.pagina_bytes()
        uit = self.draai("--dry-run", "--src", self.skill)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertEqual(self.pagina_bytes(), voor)


class Publiceren(Cp06Basis):
    def plan_in_stdout(self, uit):
        self.assertIn("index.html", uit.stdout)
        self.assertIn("tag", uit.stdout.lower())
        self.assertIn("push", uit.stdout.lower())
        self.assertIn(f"gh release create {VERSIE} dist/buildflow.zip", uit.stdout)

    def test_publish_toont_plan_en_voert_uit_na_letterlijke_bevestiging(self):
        uit = self.release("--publish", invoer=VERSIE + "\n")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.plan_in_stdout(uit)
        aanroepen = schrijvende_aanroepen(self.logtekst())
        soorten = [s for s, _ in aanroepen]
        # opeenvolgende gelijke soorten (bv. twee pushes) tellen als één stap
        stappen = [s for i, s in enumerate(soorten) if i == 0 or soorten[i - 1] != s]
        self.assertEqual([s for s in stappen if s != "add"],
                         ["commit", "tag", "push", "release create"], self.logtekst())
        if "add" in stappen:
            self.assertLess(stappen.index("add"), stappen.index("commit"))
        commit_regels = [r for s, r in aanroepen if s in ("add", "commit")]
        self.assertTrue(any("index.html" in r for r in commit_regels),
                        f"index.html wordt niet gecommit: {commit_regels}")
        self.assertTrue(any(VERSIE in r for s, r in aanroepen if s == "tag"))
        create = [r for s, r in aanroepen if s == "release create"][0]
        self.assertIn(VERSIE, create.split())
        self.assertTrue(any(a.endswith("dist/buildflow.zip") for a in create.split()), create)

    def test_publish_doet_niets_als_bevestiging_niet_klopt(self):
        for invoer in ("ja\n", "v1.0.1\n", "\n", ""):
            with self.subTest(invoer=invoer):
                if os.path.exists(self.log):
                    os.remove(self.log)
                uit = self.release("--publish", invoer=invoer)
                self.assertNotEqual(uit.returncode, 0)
                self.assertGeenTraceback(uit)
                self.plan_in_stdout(uit)
                self.assertEqual(schrijvende_aanroepen(self.logtekst()), [],
                                 self.logtekst())

    def test_publish_weigert_bestaande_tag_of_release(self):
        for env in ({"NEP_BESTAANDE_TAG": VERSIE}, {"NEP_BESTAANDE_RELEASE": VERSIE}):
            with self.subTest(env=env):
                if os.path.exists(self.log):
                    os.remove(self.log)
                self.maak_repo()
                voor = self.pagina_bytes()
                uit = self.release("--publish", env_extra=env, invoer=VERSIE + "\n")
                self.assertNotEqual(uit.returncode, 0)
                self.assertGeenTraceback(uit)
                self.assertIn(VERSIE, uit.stderr)
                self.assertNotEqual(self.logtekst(), "", "er is niet gecontroleerd of de "
                                    "versie al bestaat")
                self.assertEqual(schrijvende_aanroepen(self.logtekst()), [], self.logtekst())
                self.assertEqual(self.pagina_bytes(), voor, "index.html is toch ingevuld")

    def test_publish_zonder_version_wordt_geweigerd(self):
        self.assertKentOptie("--publish")
        uit = self.draai("--publish", "--src", self.skill, invoer=VERSIE + "\n")
        self.assertNotEqual(uit.returncode, 0)
        self.assertGeenTraceback(uit)
        self.assertEqual(schrijvende_aanroepen(self.logtekst()), [], self.logtekst())


class PublicerenVoorwaarden(Cp06Basis):
    """--publish weigert vóór de bevestigingsvraag als de werkkopie niet klopt."""

    def weigert_voor_vraag(self, env, *in_fout):
        if os.path.exists(self.log):
            os.remove(self.log)
        self.maak_repo()
        voor = self.pagina_bytes()
        uit = self.release("--publish", env_extra=env, invoer=VERSIE + "\n")
        self.assertNotEqual(uit.returncode, 0, uit.stdout)
        self.assertGeenTraceback(uit)
        self.assertNotIn(f"Typ {VERSIE}", uit.stdout, "de bevestigingsvraag is toch gesteld")
        for tekst in in_fout:
            self.assertIn(tekst, uit.stderr)
        self.assertEqual(schrijvende_aanroepen(self.logtekst()), [], self.logtekst())
        self.assertNotIn("gh release view", self.logtekst())
        self.assertEqual(self.pagina_bytes(), voor, "index.html is gewijzigd")
        self.assertFalse(os.path.exists(self.zip), "zip gebouwd terwijl publiceren weigert")
        return uit

    def test_weigert_andere_branch(self):
        self.weigert_voor_vraag({"NEP_TAK": "buildflow/buildflow-website"},
                                "main", "buildflow/buildflow-website")

    def test_weigert_detached_head(self):
        self.weigert_voor_vraag({"NEP_TAK": ""}, "main", "detached")

    def test_weigert_vuile_werkkopie(self):
        for status in (" M index.html", "?? notities.txt", "M  scripts/release.py"):
            with self.subTest(status=status):
                self.weigert_voor_vraag({"NEP_STATUS": status}, status.split()[-1])

    def test_weigert_achter_of_voor_op_origin(self):
        uit = self.weigert_voor_vraag({"NEP_ORIGIN_MAIN": "b" * 40}, "origin/main")
        # eerst ophalen, dan pas vergelijken
        log = self.logtekst().splitlines()
        self.assertIn("git fetch origin", log)
        vergelijk = [i for i, r in enumerate(log) if r.startswith("git rev-parse")]
        self.assertTrue(vergelijk)
        self.assertLess(log.index("git fetch origin"), min(vergelijk), log)
        self.weigert_voor_vraag({"NEP_HEAD": "c" * 40}, "origin/main")

    def test_weigert_als_fetch_mislukt(self):
        self.weigert_voor_vraag({"NEP_FAAL": "git fetch"}, "fetch")

    def test_weigert_origin_die_niet_op_github_staat(self):
        self.weigert_voor_vraag({"NEP_ORIGIN_URL": "https://gitlab.com/x/y.git"}, "GitHub")

    def test_gh_gebruikt_de_repo_van_origin(self):
        for url, repo in (("git@github.com:joepvanabeelen/buildflow.git",
                           "joepvanabeelen/buildflow"),
                          ("https://github.com/iemand/andere-repo.git", "iemand/andere-repo"),
                          ("https://github.com/iemand/zonder.git.suffix", "iemand/zonder.git.suffix")):
            with self.subTest(url=url):
                if os.path.exists(self.log):
                    os.remove(self.log)
                uit = self.release("--publish", env_extra={"NEP_ORIGIN_URL": url},
                                   invoer=VERSIE + "\n")
                self.assertEqual(uit.returncode, 0, uit.stderr)
                gh = [r.split() for r in self.logtekst().splitlines() if r.startswith("gh ")]
                self.assertTrue(any(r[1:3] == ["release", "view"] for r in gh), gh)
                self.assertTrue(any(r[1:3] == ["release", "create"] for r in gh), gh)
                for r in gh:
                    self.assertIn("--repo", r, r)
                    self.assertEqual(r[r.index("--repo") + 1], repo, r)

    def test_releasecommit_neemt_alleen_index_html_mee(self):
        uit = self.release("--publish", invoer=VERSIE + "\n")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        commit = [r for s, r in schrijvende_aanroepen(self.logtekst()) if s == "commit"]
        self.assertEqual(len(commit), 1, self.logtekst())
        args = commit[0].split()
        self.assertIn("--", args, "commit zonder pathspec neemt alles uit de index mee")
        self.assertEqual(args[args.index("--") + 1:], ["index.html"])
        self.assertNotIn("-a", args)
        self.assertNotIn("--all", args)


class PublicerenMislukt(Cp06Basis):
    """Een stap die mislukt of onderbroken wordt: melden wat klaar is, wat nog moet en hoe terug."""

    def publiceer(self, env):
        uit = self.release("--publish", env_extra=env, invoer=VERSIE + "\n")
        self.assertNotEqual(uit.returncode, 0, uit.stdout)
        self.assertGeenTraceback(uit)
        self.assertNotIn(f"{VERSIE} is gepubliceerd", uit.stdout)
        return uit

    def na_de_fout(self, uit, faalregel):
        """Het deel van stderr na de melding, en de aanroepen na de mislukte stap."""
        log = self.logtekst().splitlines()
        self.assertIn(faalregel, log)
        return log[log.index(faalregel) + 1:]

    def test_mislukte_push_stopt_en_geeft_rest_en_terugdraaien(self):
        uit = self.publiceer({"NEP_FAAL": "git push origin main"})
        self.assertEqual(self.na_de_fout(uit, "git push origin main"), [],
                         "na de mislukte push is toch doorgegaan")
        fouttekst = uit.stderr
        self.assertIn("git push origin main", fouttekst)
        # de overige stappen staan er als volledige commando's
        self.assertIn(f"git push origin {VERSIE}", fouttekst)
        self.assertRegex(fouttekst, rf"gh release create {VERSIE} dist/buildflow.zip --repo "
                                    r"joepvanabeelen/buildflow .*--title")
        # gelukt: commit en tag
        self.assertIn(f"git tag -a {VERSIE}", fouttekst)
        # terugdraaien: tag weg en commit weg (die is nog niet gepusht)
        self.assertIn(f"git tag -d {VERSIE}", fouttekst)
        # release.py raadt origin/main aan: dat klopt ook als onbekend is of de commit
        # gelukt is, HEAD~1 niet (cp10)
        self.assertIn("git reset --hard origin/main", fouttekst)
        self.assertNotIn("HEAD~1", fouttekst)

    def test_mislukte_tagpush_raadt_geen_reset_aan(self):
        uit = self.publiceer({"NEP_FAAL": f"git push origin {VERSIE}"})
        self.assertEqual(self.na_de_fout(uit, f"git push origin {VERSIE}"), [])
        self.assertIn(f"gh release create {VERSIE}", uit.stderr)
        self.assertNotIn("reset --hard", uit.stderr,
                         "de commit staat al op origin; reset --hard is dan fout advies")
        self.assertIn("git revert", uit.stderr)
        self.assertIn(f"git tag -d {VERSIE}", uit.stderr)

    def test_mislukte_gh_release_create(self):
        uit = self.publiceer({"NEP_FAAL": "gh release create"})
        self.assertIn("nep-fout", uit.stderr, "de fout van gh wordt niet getoond")
        self.assertRegex(uit.stderr, rf"(?s)Nog te doen.*gh release create {VERSIE} "
                                     r"dist/buildflow.zip --repo")
        te_doen = uit.stderr.split("Nog te doen", 1)[1].split("Terugdraaien", 1)[0]
        self.assertNotIn("git push", te_doen, "al gepushte stappen staan bij nog te doen")
        self.assertNotIn("reset --hard", uit.stderr)
        self.assertIn(f"git push origin :refs/tags/{VERSIE}", uit.stderr)

    def test_mislukte_commit_zet_alleen_de_pagina_terug(self):
        uit = self.publiceer({"NEP_FAAL": "git commit"})
        self.assertEqual(self.na_de_fout(uit, [r for r in self.logtekst().splitlines()
                                               if r.startswith("git commit")][0]), [])
        self.assertIn("git checkout HEAD -- index.html", uit.stderr)
        self.assertNotIn("git tag -d", uit.stderr)
        self.assertNotIn("reset --hard", uit.stderr)

    def test_onderbreking_meldt_de_echte_stand(self):
        uit = self.publiceer({"NEP_ONDERBREEK": "git push origin main"})
        self.assertEqual(self.na_de_fout(uit, "git push origin main"), [],
                         "na Ctrl-C is toch doorgegaan")
        self.assertNotIn("niets gepubliceerd", uit.stderr,
                         "na commit en tag is 'niets gepubliceerd' niet waar")
        self.assertRegex(uit.stderr, r"(?i)onderbroken|afgebroken")
        self.assertIn("git push origin main", uit.stderr.split("Nog te doen", 1)[1])
        self.assertIn(f"gh release create {VERSIE}", uit.stderr)
        self.assertIn(f"git tag -d {VERSIE}", uit.stderr)

    def test_onderbreking_bij_eerste_stap(self):
        uit = self.publiceer({"NEP_ONDERBREEK": "git add"})
        self.assertNotIn("niets gepubliceerd", uit.stderr)
        self.assertIn("git checkout HEAD -- index.html", uit.stderr)
        self.assertNotIn("git commit", "\n".join(self.na_de_fout(uit, "git add index.html")))


class Paginastructuur(unittest.TestCase):
    def test_releasevelden_in_topbalk_footer_en_downloadtegels(self):
        p = Pagina(lees(INDEX))
        els = p.elementen()

        def soorten_in(blok):
            return [e.attrs["data-release"] for e in blok.iter() if e.attrs.get("data-release")]

        topbalk = [e for e in els if "topbalk" in e.classes]
        footer = [e for e in els if e.tag == "footer"]
        self.assertTrue(topbalk and footer)
        self.assertIn("versie", soorten_in(topbalk[0]))
        self.assertIn("versie", soorten_in(footer[0]))
        download = [e for e in els if "download" in e.classes]
        self.assertTrue(download, "geen .download")
        kpis = [e for e in download[0].iter() if "kpi" in e.classes]
        tegels = [s for k in kpis for s in soorten_in(k)]
        self.assertEqual(sorted(tegels), ["datum", "grootte", "versie"])

    def test_downloadknoppen_wijzen_naar_latest(self):
        links = [e.attrs["href"] for e in Pagina(lees(INDEX)).elementen()
                 if e.tag == "a" and "buildflow.zip" in (e.attrs.get("href") or "")]
        self.assertTrue(links)
        self.assertEqual(set(links), {DOWNLOAD})


class OpenPuntenCp05(Cp06Basis):
    """Open punten uit de review van cp05: README verplicht, onleesbare bron, S_IFREG."""

    def weigert(self, *in_fout):
        uit = self.draai("--dry-run", "--src", self.skill)
        self.assertGeenTraceback(uit)
        self.assertNotEqual(uit.returncode, 0, "bouw had geweigerd moeten worden")
        for tekst in in_fout:
            self.assertIn(tekst, uit.stderr)
        dist = os.path.join(self.repo, "dist")
        rest = os.listdir(dist) if os.path.isdir(dist) else []
        self.assertEqual(rest, [], f"er is iets achtergebleven in dist/: {rest}")
        return uit

    def test_readme_is_verplicht(self):
        os.remove(os.path.join(self.skill, "README.md"))
        self.weigert("README.md")

    def onleesbaar(self, pad):
        if os.geteuid() == 0:
            self.skipTest("als root zijn onleesbare bestanden toch leesbaar")
        oud = stat.S_IMODE(os.stat(pad).st_mode)
        os.chmod(pad, 0)
        self.addCleanup(os.chmod, pad, oud)

    def test_onleesbaar_bestand_stopt_de_bouw_met_duidelijke_melding(self):
        pad = cp05.schrijf(self.skill, "references/b.md", "# b\n")
        self.onleesbaar(pad)
        uit = self.weigert(pad)
        self.assertRegex(uit.stderr, r"(?i)leesbaar|lezen|toegang|permission")

    def test_onleesbare_map_stopt_de_bouw_met_duidelijke_melding(self):
        cp05.schrijf(self.skill, "scripts/lib/x.py", "x\n")
        pad = os.path.join(self.skill, "scripts", "lib")
        self.onleesbaar(pad)
        uit = self.weigert(pad)
        self.assertRegex(uit.stderr, r"(?i)leesbaar|lezen|toegang|permission")

    def test_zip_items_zijn_gewone_bestanden_0644(self):
        self.bouw()
        with zipfile.ZipFile(self.zip) as z:
            for info in z.infolist():
                with self.subTest(naam=info.filename):
                    modus = info.external_attr >> 16
                    self.assertEqual(info.create_system, 3, "geen unix-attributen")
                    self.assertTrue(stat.S_ISREG(modus), f"geen S_IFREG: {oct(modus)}")
                    self.assertEqual(stat.S_IMODE(modus), 0o644)


if __name__ == "__main__":
    unittest.main()
