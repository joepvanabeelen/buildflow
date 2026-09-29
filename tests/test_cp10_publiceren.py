"""cp10: controles vóór en na het publiceren.

Groep 1 draait altijd en heeft geen netwerk nodig:
- de privacyscan over de hele git-geschiedenis van alle branches: elke versie van elk
  bestand dat ooit is gecommit (ook binaire bestanden zoals PNG's), de auteurs, committers
  en taggers en de commitberichten;
- geen enkel pad in de geschiedenis valt buiten de publieke set;
- de herstelhulp van release.py na een onderbreking (open punten uit de review van cp06)
  en dat gh --repo uit de push-URL van origin komt. Die draaien met de gh- en git-stubs uit
  cp06 in een tijdelijke map; de echte gh of git publiceert nooit iets.

Git wordt hier alleen lezend aangeroepen in de repo (log, rev-list, cat-file, for-each-ref,
config --get). De tests die laten zien dat de scan echt aanslaat, maken een eigen
wegwerprepo in een tijdelijke map, met expliciete cwd en zonder de globale git-config.

Claude-Session-trailers in commitberichten zijn geen fout: Joep beslist of die mogen blijven.
De test die ze telt slaagt altijd en schrijft wat hij vond naar stderr, net als de
auteursregels, zodat ze bij het draaien zichtbaar zijn.

Groep 2 zijn live-tests tegen GitHub. Ze draaien alleen met BUILDFLOW_LIVE=1 en worden
anders overgeslagen met de reden 'BUILDFLOW_LIVE niet gezet', zonder één netwerkverzoek
of gh-aanroep. Ook met BUILDFLOW_LIVE=1 lezen ze alleen.
"""
import getpass
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from tests import check_privacy
from tests import test_cp06_release as cp06
from tests import test_cp07_installatie as cp07
from tests.check_site import INDEX, ROOT, Pagina, heeft_schema, lees

VERSIE = cp06.VERSIE
REPO_NAAM = "joepvanabeelen/buildflow"
LIVE_URL = "https://joepvanabeelen.github.io/buildflow/"
DOWNLOAD = cp06.DOWNLOAD
DIST_ZIP = os.path.join(ROOT, "dist", "buildflow.zip")
LIVE_REDEN = "BUILDFLOW_LIVE niet gezet; zet BUILDFLOW_LIVE=1 om tegen de live site te testen"

NOREPLY_GITHUB = re.compile(r"\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com")
EMAIL = dict(check_privacy.PATRONEN)["e-mailadres"]

# Wat publiek mag: de site, de voorbeeldrun, de ontwerpdocs, de scripts en de tests.
PUBLIEKE_MAPPEN = ("assets/", "voorbeeld/", "docs/design/", "scripts/", "tests/")
PUBLIEKE_BESTANDEN = {"index.html", "LICENSE", "README.md", ".gitignore", ".nojekyll"}
NOOIT = re.compile(r"(^|/)(\.buildflow|\.playwright-mcp|dist|__pycache__)(/|$)"
                   r"|(^|/)\.DS_Store$|\.pyc$")


# ---------- git, alleen lezend ----------

def git(*args, cwd=ROOT, env=None):
    uit = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env,
                         stdin=subprocess.DEVNULL, timeout=120)
    if uit.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} mislukte: "
                             f"{uit.stderr.decode('utf-8', 'replace')}")
    return uit.stdout


def geschiedenis_blobs(cwd=ROOT):
    """(pad, inhoud) voor elke blob in de geschiedenis van alle refs (branches, remotes, tags)."""
    paden = {}
    for regel in git("rev-list", "--all", "--objects", cwd=cwd).decode("utf-8").splitlines():
        sha, _, pad = regel.partition(" ")
        if pad:
            paden.setdefault(sha, pad)
    if not paden:
        return []
    invoer = "".join(f"{sha}\n" for sha in paden).encode()
    uit = subprocess.run(["git", "cat-file", "--batch"], cwd=cwd, input=invoer,
                         capture_output=True, timeout=120, check=True).stdout
    blobs, i = [], 0
    while i < len(uit):
        kop_eind = uit.index(b"\n", i)
        sha, soort, grootte = uit[i:kop_eind].decode().split()
        inhoud = uit[kop_eind + 1:kop_eind + 1 + int(grootte)]
        i = kop_eind + 1 + int(grootte) + 1
        if soort == "blob":
            blobs.append((paden[sha], inhoud))
    return blobs


def alle_paden(cwd=ROOT):
    """Elk bestandspad dat ooit in een commit op een ref stond."""
    uit = git("log", "--all", "--format=", "--name-only", "--no-renames", cwd=cwd)
    return sorted({p for p in uit.decode("utf-8").splitlines() if p.strip()})


def commits(cwd=ROOT):
    """Per commit: hash, auteur, committer (naam en e-mail) en het volledige bericht."""
    uit = git("log", "--all", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e", cwd=cwd)
    lijst = []
    for stuk in uit.decode("utf-8", "replace").split("\x1e"):
        velden = stuk.strip("\n").split("\x1f")
        if len(velden) == 6:
            lijst.append(dict(zip(("hash", "an", "ae", "cn", "ce", "bericht"), velden)))
    return lijst


def taggers(cwd=ROOT):
    uit = git("for-each-ref", "refs/tags",
              "--format=%(refname:short)%09%(taggername)%09%(taggeremail)", cwd=cwd)
    return [r.split("\t") for r in uit.decode("utf-8").splitlines() if r.strip()]


def scan_inhoud(pad, inhoud):
    """Zelfde scan als check_privacy.scan_bestand, maar op bytes uit git."""
    stukken = check_privacy._png_stukken(inhoud)
    if stukken is None:
        meldingen = []
        for nr, regel in enumerate(inhoud.split(b"\n"), 1):
            meldingen += check_privacy._zoek(f"{pad}:{nr}", regel, pad)
        return meldingen
    meldingen = []
    for label, tekst, probleem in stukken:
        if probleem:
            meldingen.append(f"{pad} ({label}): {probleem}")
        meldingen += check_privacy._zoek(f"{pad} ({label})", tekst, pad)
    return meldingen


def is_noreply(adres):
    return "noreply" in adres.lower()


def echte_gegevens():
    """Wat van deze machine nooit in de geschiedenis mag staan, als bytes (kleine letters).

    Wordt bij het draaien bepaald en staat dus zelf niet in de repo: de homemap, de
    gebruikersnaam als deel van een homepad en het e-mailadres uit de globale git-config
    (als dat geen noreply-adres is).
    """
    home = os.path.realpath(os.path.expanduser("~"))
    gebruiker = getpass.getuser()
    uit = {home.lower().encode(), f"/users/{gebruiker}/".lower().encode(),
           f"/home/{gebruiker}/".lower().encode()}
    tmp = tempfile.mkdtemp(prefix="bf-cp10-cfg-")
    try:
        r = subprocess.run(["git", "config", "--global", "--get", "user.email"], cwd=tmp,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        shutil.rmtree(tmp, True)
    adres = r.stdout.strip()
    if adres and not is_noreply(adres):
        uit.add(adres.lower().encode())
    return uit


def zoek_echte_gegevens(blobs, verboden):
    """Paden van blobs waarin iets uit verboden voorkomt; toont nooit het gevonden adres."""
    return sorted({pad for pad, inhoud in blobs
                   if any(v in inhoud.lower() for v in verboden)})


def in_publieke_set(pad):
    if NOOIT.search(pad):
        return False
    return pad in PUBLIEKE_BESTANDEN or pad.startswith(PUBLIEKE_MAPPEN)


def metadata_fouten(cs, tags):
    fouten = []
    for c in cs:
        for rol, naam, adres in (("auteur", c["an"], c["ae"]), ("committer", c["cn"], c["ce"])):
            if not NOREPLY_GITHUB.fullmatch(adres):
                fouten.append(f"{c['hash'][:12]} {rol}: e-mail is geen GitHub-noreply-adres")
            if "@" in naam:
                fouten.append(f"{c['hash'][:12]} {rol}: naam bevat een e-mailadres")
    for tag, naam, adres in tags:
        adres = adres.strip("<>")
        if adres and not NOREPLY_GITHUB.fullmatch(adres):
            fouten.append(f"tag {tag}: tagger-e-mail is geen GitHub-noreply-adres")
        if "@" in naam:
            fouten.append(f"tag {tag}: taggernaam bevat een e-mailadres")
    return fouten


def bericht_fouten(cs):
    fouten = []
    for c in cs:
        for nr, regel in enumerate(c["bericht"].splitlines(), 1):
            for m in check_privacy._zoek(f"{c['hash'][:12]} regel {nr}", regel.encode(), ""):
                soort, gevonden = m.split(": ")[1], m.split(": ", 2)[2]
                if soort == "e-mailadres" and is_noreply(gevonden):
                    continue
                fouten.append(m)
    return fouten


def session_trailers(cs):
    return [(c["hash"][:12], r.strip()) for c in cs for r in c["bericht"].splitlines()
            if r.lower().startswith("claude-session:")]


def meld(tekst):
    sys.stderr.write("\n" + tekst + "\n")


# ---------- groep 1: de geschiedenis ----------

class Geschiedenis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(ROOT, ".git")):
            raise unittest.SkipTest("geen git-checkout; de geschiedenis is niet te lezen")
        cls.blobs = geschiedenis_blobs()
        cls.paden = alle_paden()
        cls.commits = commits()
        cls.tags = taggers()

    def test_geschiedenis_is_gelezen(self):
        self.assertTrue(self.commits, "geen commits gevonden")
        self.assertTrue(any(p == "index.html" for p, _ in self.blobs),
                        "index.html staat niet tussen de blobs; de scan leest niets")

    def test_alle_paden_in_de_geschiedenis_horen_bij_de_publieke_set(self):
        buiten = [p for p in self.paden if not in_publieke_set(p)]
        self.assertEqual(buiten, [], "bestanden in de geschiedenis buiten de publieke set:\n"
                         + "\n".join(buiten))

    def test_niets_persoonlijks_in_bestanden_buiten_tests(self):
        # tests/ bevat bewust neppaden en nepadressen als testdata; die toetst de volgende test
        meldingen = []
        for pad, inhoud in self.blobs:
            if not pad.startswith("tests/"):
                meldingen += scan_inhoud(pad, inhoud)
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_geen_echte_gegevens_van_deze_machine_in_enig_bestand(self):
        paden = zoek_echte_gegevens(self.blobs, echte_gegevens())
        self.assertEqual(paden, [], "echte homemap of e-mailadres gevonden in (een oude "
                         "versie van): " + ", ".join(paden))

    def test_auteurs_committers_en_taggers_zijn_github_noreply(self):
        fouten = metadata_fouten(self.commits, self.tags)
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_commitberichten_bevatten_niets_persoonlijks(self):
        fouten = bericht_fouten(self.commits)
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_rapport_auteursregels_en_claude_session_trailers(self):
        """Geen fout: dit is ter beoordeling voor Joep vóór het publiceren."""
        auteurs = sorted({f"{c['an']} <{c['ae']}>" for c in self.commits}
                         | {f"{c['cn']} <{c['ce']}>" for c in self.commits})
        trailers = session_trailers(self.commits)
        tekst = [f"cp10 ter beoordeling: auteurs/committers in {len(self.commits)} commits:"]
        tekst += [f"  {a}" for a in auteurs]
        if trailers:
            tekst.append(f"cp10 ter beoordeling: {len(trailers)} commits met een "
                         "Claude-Session-trailer (niet als fout geteld):")
            tekst += [f"  {h} {t}" for h, t in trailers]
        else:
            tekst.append("cp10 ter beoordeling: geen Claude-Session-trailers")
        meld("\n".join(tekst))


class ScanSlaatAanOpGeschiedenis(unittest.TestCase):
    """Een wegwerprepo met een pad, adres en sessie-id in de geschiedenis: de scan vindt ze,
    ook als het bestand later is verwijderd of de commit op een andere branch staat."""

    NEP_THUIS = "/Users/iemand/geheim"
    NEP_ADRES = "iemand@voorbeeld.nl"

    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("git ontbreekt")
        self.tmp = tempfile.mkdtemp(prefix="bf-cp10-git-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp,
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "LANG": "C"}
        self.g("init", "-q", "-b", "main")

    def g(self, *args, auteur=("Nep", "1+nep@users.noreply.github.com")):
        env = dict(self.env, GIT_AUTHOR_NAME=auteur[0], GIT_AUTHOR_EMAIL=auteur[1],
                   GIT_COMMITTER_NAME=auteur[0], GIT_COMMITTER_EMAIL=auteur[1])
        return git(*args, cwd=self.tmp, env=env)

    def commit(self, pad, inhoud, bericht="x", **kw):
        vol = os.path.join(self.tmp, pad)
        os.makedirs(os.path.dirname(vol), exist_ok=True)
        with open(vol, "wb") as f:
            f.write(inhoud)
        self.g("add", "--", pad, **kw)
        self.g("commit", "-q", "-m", bericht, **kw)

    def test_verwijderd_bestand_op_andere_branch_wordt_gevonden(self):
        self.commit("index.html", b"<p>schoon</p>\n")
        self.g("switch", "-q", "-c", "zijtak")
        self.commit("notities.txt", f"zie {self.NEP_THUIS}/a.txt\n".encode())
        self.g("rm", "-q", "notities.txt")
        self.g("commit", "-q", "-m", "weg")
        self.g("switch", "-q", "main")
        meldingen = [m for p, i in geschiedenis_blobs(self.tmp) for m in scan_inhoud(p, i)]
        self.assertTrue(any(self.NEP_THUIS in m for m in meldingen), meldingen)
        self.assertIn("notities.txt", alle_paden(self.tmp))
        self.assertFalse(in_publieke_set("notities.txt"))

    def test_pad_in_png_tekstchunk_wordt_gevonden(self):
        import struct
        import zlib
        data = b"Comment\0\0" + zlib.compress(self.NEP_THUIS.encode())
        chunk = struct.pack(">I", len(data)) + b"zTXt" + data + b"\0\0\0\0"
        png = b"\x89PNG\r\n\x1a\n" + chunk + struct.pack(">I", 0) + b"IEND" + b"\0\0\0\0"
        self.commit("assets/x.png", png)
        meldingen = [m for p, i in geschiedenis_blobs(self.tmp) for m in scan_inhoud(p, i)]
        self.assertTrue(any(self.NEP_THUIS in m for m in meldingen), meldingen)

    def test_persoonlijke_auteur_en_adres_in_bericht_worden_gevonden(self):
        self.commit("index.html", b"x\n", bericht=f"mail {self.NEP_ADRES}\n\n"
                    "Co-Authored-By: Bot <noreply@anthropic.com>\n"
                    "Claude-Session: https://claude.ai/code/session_abc",
                    auteur=("Iemand", self.NEP_ADRES))
        cs = commits(self.tmp)
        fouten = metadata_fouten(cs, taggers(self.tmp))
        self.assertTrue(any("auteur" in f for f in fouten), fouten)
        self.assertTrue(any("committer" in f for f in fouten), fouten)
        berichten = bericht_fouten(cs)
        self.assertEqual(len(berichten), 1, berichten)
        self.assertIn(self.NEP_ADRES, berichten[0])
        self.assertEqual(len(session_trailers(cs)), 1)

    def test_tagger_met_persoonlijk_adres_wordt_gevonden(self):
        self.commit("index.html", b"x\n")
        self.g("tag", "-a", "v0.0.1", "-m", "t", auteur=("Iemand", self.NEP_ADRES))
        fouten = metadata_fouten(commits(self.tmp), taggers(self.tmp))
        self.assertTrue(any("tag v0.0.1" in f for f in fouten), fouten)

    def test_echte_gegevens_worden_gevonden_zonder_ze_te_tonen(self):
        verboden = {b"/users/iemand/", b"iemand@voorbeeld.nl"}
        blobs = [("tests/a.py", b"x = '/Users/Iemand/y'\n"), ("tests/b.py", b"schoon\n"),
                 ("README.md", b"mail IEMAND@voorbeeld.nl\n")]
        self.assertEqual(zoek_echte_gegevens(blobs, verboden), ["README.md", "tests/a.py"])

    def test_publieke_set(self):
        for pad in ("index.html", "assets/site.css", "voorbeeld/cp01.html", "tests/x.py",
                    "scripts/release.py", "docs/design/design.md", ".nojekyll"):
            with self.subTest(pad=pad):
                self.assertTrue(in_publieke_set(pad))
        for pad in (".buildflow/x/brief.md", "dist/buildflow.zip", ".DS_Store",
                    "assets/.DS_Store", "tests/__pycache__/a.pyc", ".playwright-mcp/s.png",
                    "notities.txt", "docs/intern.md"):
            with self.subTest(pad=pad):
                self.assertFalse(in_publieke_set(pad))


# ---------- groep 1: release.py na de review van cp06 ----------

class HerstelhulpCp06(cp06.Cp06Basis):
    """Open punten uit de review van cp06, met de stubs uit cp06 (niets wordt gepubliceerd)."""

    def publiceer(self, env):
        uit = self.release("--publish", env_extra=env, invoer=VERSIE + "\n")
        self.assertNotEqual(uit.returncode, 0, uit.stdout)
        self.assertGeenTraceback(uit)
        self.assertNotIn(f"{VERSIE} is gepubliceerd", uit.stdout)
        return uit

    def terugdraaien(self, uit):
        self.assertIn("Terugdraaien", uit.stderr, uit.stderr)
        return uit.stderr.split("Terugdraaien", 1)[1]

    def test_onderbroken_gh_release_create_noemt_gh_release_delete(self):
        uit = self.publiceer({"NEP_ONDERBREEK": "gh release create"})
        log = self.logtekst().splitlines()
        create = [r for r in log if r.startswith("gh release create")]
        self.assertEqual(len(create), 1, log)
        self.assertEqual(log[-1], create[0], "na de onderbreking is toch doorgegaan")
        terug = self.terugdraaien(uit)
        self.assertIn(f"gh release delete {VERSIE} --repo {REPO_NAAM}", terug,
                      "de release kan al bestaan; terugdraaien moet gh release delete noemen")

    def test_onderbroken_commit_raadt_reset_naar_origin_main_aan(self):
        uit = self.publiceer({"NEP_ONDERBREEK": "git commit"})
        log = self.logtekst().splitlines()
        self.assertTrue(log and log[-1].startswith("git commit"),
                        f"na de onderbreking is toch doorgegaan: {log}")
        terug = self.terugdraaien(uit)
        self.assertIn("git reset --hard origin/main", terug,
                      "of de commit gelukt is, is onbekend; reset naar origin/main klopt "
                      "in beide gevallen")
        self.assertNotIn("HEAD~1", terug,
                         "HEAD~1 gooit een commit weg die er al was als de releasecommit "
                         "niet gelukt is")
        self.assertNotIn("git revert", terug, "er is nog niets gepusht")
        self.assertNotIn("git push", terug, "er is nog niets gepusht")

    def test_gh_repo_komt_uit_de_push_url_van_origin(self):
        env = {"NEP_ORIGIN_URL": "https://github.com/iemand/alleen-fetch.git",
               "NEP_PUSH_URL": f"git@github.com:{REPO_NAAM}.git"}
        uit = self.release("--publish", env_extra=env, invoer=VERSIE + "\n")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        log = self.logtekst().splitlines()
        self.assertIn("git remote get-url --push origin", log, log)
        gh = [r.split() for r in log if r.startswith("gh ")]
        self.assertTrue(any(r[1:3] == ["release", "create"] for r in gh), gh)
        for r in gh:
            with self.subTest(aanroep=" ".join(r[:3])):
                self.assertIn("--repo", r)
                self.assertEqual(r[r.index("--repo") + 1], REPO_NAAM,
                                 "gh moet de repo gebruiken waar git naartoe pusht")
        self.assertNotIn("iemand/alleen-fetch", uit.stdout + uit.stderr)

    def test_publicatieplan_zonder_bevestiging_publiceert_niets(self):
        uit = self.release("--publish", invoer="ja\n")
        self.assertNotEqual(uit.returncode, 0)
        self.assertGeenTraceback(uit)
        self.assertIn("git push origin main", uit.stdout)
        self.assertIn(f"git tag -a {VERSIE}", uit.stdout)
        self.assertIn(f"gh release create {VERSIE} dist/buildflow.zip", uit.stdout)
        self.assertEqual(cp06.schrijvende_aanroepen(self.logtekst()), [], self.logtekst())


# ---------- groep 2: live, alleen met BUILDFLOW_LIVE=1 ----------

def live():
    return os.environ.get("BUILDFLOW_LIVE") == "1"


def eis_live():
    if not live():
        raise unittest.SkipTest(LIVE_REDEN)


def haal(url, timeout=30):
    """(status, bytes) na redirects, zonder token."""
    verzoek = urllib.request.Request(url, headers={"User-Agent": "buildflow-website-cp10"})
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def release_waarden(html):
    return sorted((e.attrs["data-release"], e.alle_tekst().strip())
                  for e in Pagina(html).elementen() if e.attrs.get("data-release"))


def lokale_links(html):
    uit = set()
    for e in Pagina(html).elementen():
        for attr in ("href", "src"):
            w = (e.attrs.get(attr) or "").strip()
            if not w or w.startswith("#") or heeft_schema(w):
                continue
            pad = re.split(r"[?#]", w)[0].lstrip("./")
            if pad:
                uit.add(pad)
    return uit


class LiveBasis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        eis_live()


class LiveSite(LiveBasis):
    def test_site_geeft_200_met_titel_en_releasewaarden_van_main(self):
        status, body = haal(LIVE_URL)
        self.assertEqual(status, 200)
        live_html = body.decode("utf-8")
        lokaal = git("show", "main:index.html").decode("utf-8")
        titel = re.search(r"<title>(.*?)</title>", lokaal, re.S).group(1)
        self.assertIn(titel, live_html)
        self.assertEqual(release_waarden(live_html), release_waarden(lokaal))
        self.assertNotIn("volgt", [w for _, w in release_waarden(live_html)],
                         "datum of grootte is niet ingevuld")

    def test_alle_links_naar_voorbeeld_en_assets_geven_200(self):
        html = lees(INDEX)
        paden = {p for p in lokale_links(html) if p.startswith(("voorbeeld/", "assets/"))}
        bijgehouden = git("ls-files", "voorbeeld", "assets").decode("utf-8").split()
        paden |= {p for p in bijgehouden if not os.path.basename(p).startswith(".")}
        self.assertTrue(paden)
        kapot = []
        for pad in sorted(paden):
            status, _ = haal(urllib.parse.urljoin(LIVE_URL, urllib.parse.quote(pad)))
            if status != 200:
                kapot.append(f"{pad}: {status}")
        self.assertEqual(kapot, [], "\n".join(kapot))


class LiveDownload(LiveBasis):
    def test_download_is_gelijk_aan_dist_zip(self):
        self.assertTrue(os.path.isfile(DIST_ZIP), "dist/buildflow.zip van de release ontbreekt")
        status, body = haal(DOWNLOAD, timeout=120)
        self.assertEqual(status, 200)
        with open(DIST_ZIP, "rb") as f:
            lokaal = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(hashlib.sha256(body).hexdigest(), lokaal)


class LiveDownloadZip:
    """Mixin voor de cp07-installatietests: de zip komt van de live release."""

    @classmethod
    def bouw_zip(cls, tmp):
        eis_live()
        status, body = haal(DOWNLOAD, timeout=120)
        if status != 200:
            raise AssertionError(f"download van {DOWNLOAD} gaf {status}")
        pad = os.path.join(tmp, "buildflow.zip")
        with open(pad, "wb") as f:
            f.write(body)
        return pad


class LiveHomeInstallatie(LiveDownloadZip, cp07.HomeInstallatie):
    pass


class LiveProjectInstallatie(LiveDownloadZip, cp07.ProjectInstallatie):
    pass


class LiveRepos(LiveBasis):
    def test_buildflow_website_is_openbaar(self):
        status, body = haal(f"https://api.github.com/repos/{REPO_NAAM}")
        self.assertEqual(status, 200)
        self.assertIn(b'"private": false', body.replace(b'"private":false', b'"private": false'))

    def test_claude_skills_is_anoniem_niet_te_zien(self):
        status, _ = haal("https://api.github.com/repos/joepvanabeelen/SKILLREPO")
        self.assertEqual(status, 404)

    def gh(self, *args):
        if shutil.which("gh") is None:
            self.skipTest("gh ontbreekt")
        tmp = tempfile.mkdtemp(prefix="bf-cp10-gh-")
        self.addCleanup(shutil.rmtree, tmp, True)
        uit = subprocess.run(["gh", *args], cwd=tmp, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        return uit.stdout

    def test_claude_skills_is_private_volgens_gh(self):
        uit = self.gh("repo", "view", "joepvanabeelen/SKILLREPO", "--json", "visibility")
        self.assertIn('"PRIVATE"', uit.replace(" ", ""))

    def test_pages_serveert_main_vanuit_de_root(self):
        uit = self.gh("api", f"repos/{REPO_NAAM}/pages", "--jq",
                      ".source.branch + \" \" + .source.path")
        self.assertEqual(uit.strip(), "main /")


LIVE_KLASSEN = (LiveSite, LiveDownload, LiveHomeInstallatie, LiveProjectInstallatie, LiveRepos)


class ZonderLive(unittest.TestCase):
    """Zonder BUILDFLOW_LIVE: alles overgeslagen met een duidelijke reden, geen netwerk, geen gh."""

    def test_live_tests_worden_overgeslagen_zonder_netwerk_of_gh(self):
        aanroepen = []

        def verboden(naam):
            def f(*a, **k):
                aanroepen.append((naam, a[:1]))
                raise AssertionError(f"{naam} aangeroepen zonder BUILDFLOW_LIVE")
            return f

        env = {k: v for k, v in os.environ.items() if k != "BUILDFLOW_LIVE"}
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(k)
                                   for k in LIVE_KLASSEN)
        resultaat = unittest.TestResult()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(urllib.request, "urlopen", verboden("urlopen")), \
                mock.patch.object(socket, "create_connection", verboden("socket")), \
                mock.patch.object(subprocess, "run", verboden("subprocess.run")), \
                mock.patch.object(subprocess, "Popen", verboden("subprocess.Popen")):
            suite.run(resultaat)
        self.assertEqual(aanroepen, [])
        self.assertEqual(resultaat.errors + resultaat.failures, [],
                         [t for _, t in resultaat.errors + resultaat.failures])
        self.assertEqual(len(resultaat.skipped), len(LIVE_KLASSEN),
                         "elke live-klasse hoort in setUpClass over te slaan")
        for _, reden in resultaat.skipped:
            self.assertIn("BUILDFLOW_LIVE niet gezet", reden)


if __name__ == "__main__":
    unittest.main()
