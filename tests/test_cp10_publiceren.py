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

Een kaal sessie-id (session_ plus minstens 20 tekens) en het sessie-id uit de omgeving zijn
overal een fout: in elke versie van elk bestand, in commit- en tagberichten en in de
werkkopie. In de werkkopie en in de berichten is daarnaast elke link naar claude.ai met het
pad /code/ (ook gecodeerd als \\/ of %2F) en elke Claude-Session-trailer met een waarde een
fout, hoe kort het id ook is. De enige uitzondering is het verzonnen id NEP_SESSIE. Testdata
met zo'n link of trailer wordt tijdens het draaien opgebouwd, zodat de scan er niet op
aanslaat. Waarom die twee brede patronen niet over oude blobs gaan, staat bij
sessie_en_skillrepo_fouten. De rapporttest schrijft de auteursregels en gevonden trailers daarnaast naar
stderr, zodat ze bij het draaien zichtbaar zijn.

De scan op de naam van de private skill-repo draait alleen als BUILDFLOW_SKILL_REPO gezet is
en wordt anders zichtbaar overgeslagen; de scan op sessie-id's draait altijd.

Groep 2 zijn live-tests tegen GitHub. Ze draaien alleen met BUILDFLOW_LIVE=1 en worden
anders overgeslagen met de reden 'BUILDFLOW_LIVE niet gezet', zonder één netwerkverzoek
of gh-aanroep. Ook met BUILDFLOW_LIVE=1 lezen ze alleen.
"""
import collections
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


def geschiedenis_blobs(cwd=ROOT, refs=("--all",)):
    """(pad, inhoud) voor elke blob in de geschiedenis van refs, standaard alle refs
    (branches, remotes, tags)."""
    paden = {}
    for regel in git("rev-list", *refs, "--objects", cwd=cwd).decode("utf-8").splitlines():
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


# Sessie-ids en de private skill-repo. Een kaal id (session_ plus minstens 20 tekens) is fout,
# behalve het verzonnen id dat de tests als voorbeeld gebruiken en voorvoegsels daarvan.
# SESSIE_LINK vindt een link naar claude.ai met het pad /code/, ook als de schuine strepen als
# \/ (JSON) of %2F (url) gecodeerd zijn. SESSIE_REGEL vindt een sessietrailer overal in een
# regel. Beide zijn fout hoe kort het id ook is; alleen het volledige verzonnen id mag, en
# achter de trailer ook de vervanging [sessielink] van sanitize_demo.py. Een trailer telt pas
# als er een waarde achter staat die met een letter, cijfer, _ of % begint, of als er niets
# achter staat: tekst die de trailer alleen noemt (tussen backticks of in een regex) is geen lek.
NEP_SESSIE = "session_01AbCdEfGhIjKlMnOpQrStUv"
SESSIE_ID = re.compile(rb"session_[A-Za-z0-9]{20,}")
SESSIE_LINK = re.compile(rb"claude\.ai(?:/|\\/|%2f)code(?:/|\\/|%2f)([^\s\"'<>()\\&%]*)", re.I)
SESSIE_REGEL = re.compile(rb"claude-session:[ \t]*([^\r\n]*)", re.I)
NEP_LINK = "https://claude.ai" + "/code/" + NEP_SESSIE
TRAILER_TOEGESTAAN = (NEP_SESSIE, NEP_LINK, "[sessielink]")
SESSIE_OMGEVING = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID",
                   "CLAUDE_CODE_BRIDGE_SESSION_ID")
SKILL_REPO_OMGEVING = "BUILDFLOW_SKILL_REPO"


def sessie_waarden(env=None):
    """(omschrijving, bytes, hoofdletters_negeren) voor het sessie-id van de draaiende sessie,
    ook zonder session_ en afgekapt tot de eerste 12 tekens, zoals in een verkorte trailer.

    De waarden komen uit de omgeving en staan dus zelf niet in de repo; de omschrijving noemt
    alleen de variabele, nooit de waarde.
    """
    env = os.environ if env is None else env
    uit = []
    for naam in SESSIE_OMGEVING:
        waarde = env.get(naam, "").strip()
        if len(waarde) < 8:
            continue
        kaal = waarde[len("session_"):] if waarde.startswith("session_") else waarde
        for w in {waarde, kaal[:12] if len(kaal) >= 12 else kaal}:
            uit.append((f"sessie-id uit {naam}", w.encode(), False))
    return uit


def skillrepo_waarden(env=None):
    """Zelfde vorm als sessie_waarden, voor de naam van de private skill-repo (met en zonder
    eigenaar) uit BUILDFLOW_SKILL_REPO. Leeg als die variabele niet gezet is."""
    env = os.environ if env is None else env
    repo = env.get(SKILL_REPO_OMGEVING, "").strip().strip("/")
    if not repo:
        return []
    return [(f"skill-repo uit {SKILL_REPO_OMGEVING}", w.lower().encode(), True)
            for w in {repo, repo.rsplit("/", 1)[-1]}]


def geheime_waarden(env=None):
    return sessie_waarden(env) + skillrepo_waarden(env)


def teksten_van(inhoud):
    """De ruwe bytes, plus de uitgepakte tekstchunks als het een PNG is."""
    stukken = check_privacy._png_stukken(inhoud) or []
    return [inhoud] + [tekst for _, tekst, _ in stukken]


def trailer_is_fout(waarde):
    waarde = waarde.strip()
    if not waarde:
        return True
    if not re.match(r"[A-Za-z0-9_%]", waarde):
        return False
    return waarde.split()[0].rstrip(".,;:!?") not in TRAILER_TOEGESTAAN


def sessie_en_skillrepo_fouten(bronnen, geheim, breed=True):
    """Meldingen voor (plek, bytes)-bronnen; toont nooit een gevonden waarde helemaal.

    breed=True (werkkopie, commit- en tagberichten): alle patronen. breed=False (oude blobs in
    de geschiedenis): alleen SESSIE_ID en de waarden uit de omgeving, want oude versies van
    scripts/sanitize_demo.py en de tests bevatten letterlijke links met korte, verzonnen id's
    en die geschiedenis herschrijven we niet opnieuw; een echt id is altijd 20+ tekens of staat
    in de omgeving, dus een echt lek wordt ook zo gevonden.
    """
    fouten = []
    for plek, inhoud in bronnen:
        for tekst in teksten_van(inhoud):
            for m in SESSIE_ID.finditer(tekst):
                gevonden = m.group(0).decode()
                if NEP_SESSIE.startswith(gevonden):
                    continue
                fouten.append(f"{plek}: sessie-id {gevonden[:14]}…")
            for m in SESSIE_LINK.finditer(tekst) if breed else ():
                if m.group(1).decode("utf-8", "replace").rstrip(".,;:!?") != NEP_SESSIE:
                    fouten.append(f"{plek}: link naar een Claude Code-sessie")
            for m in SESSIE_REGEL.finditer(tekst) if breed else ():
                if trailer_is_fout(m.group(1).decode("utf-8", "replace")):
                    fouten.append(f"{plek}: sessietrailer")
            klein = tekst.lower()
            for omschrijving, waarde, negeer in geheim:
                if waarde in (klein if negeer else tekst):
                    fouten.append(f"{plek}: {omschrijving}")
    return sorted(set(fouten))


def scan_sessies(geheim, cwd=ROOT, blobs=None):
    """Sessie- en skill-repo-meldingen voor een repo: oude blobs smal, berichten en werkkopie
    breed (zie sessie_en_skillrepo_fouten)."""
    blobs = geschiedenis_blobs(cwd) if blobs is None else blobs
    return sorted(set(
        sessie_en_skillrepo_fouten([(f"geschiedenis {p}", i) for p, i in blobs], geheim,
                                   breed=False)
        + sessie_en_skillrepo_fouten(berichten_als_bronnen(cwd) + werkkopie_bronnen(cwd),
                                     geheim)))


def berichten_als_bronnen(cwd=ROOT):
    """Commitberichten en tagberichten van alle refs als (plek, bytes)."""
    bronnen = [(f"commit {c['hash'][:12]}", c["bericht"].encode()) for c in commits(cwd)]
    uit = git("for-each-ref", "refs/tags", "--format=%(refname:short)%1f%(contents)%1e",
              cwd=cwd)
    for stuk in uit.split(b"\x1e"):
        naam, _, bericht = stuk.strip(b"\n").partition(b"\x1f")
        if naam:
            bronnen.append((f"tag {naam.decode()}", bericht))
    return bronnen


def werkkopie_bronnen(cwd=ROOT):
    """Elk getrackt bestand zoals het nu in de werkkopie staat, ook als het nog niet is
    gecommit."""
    bronnen = []
    for pad in git("ls-files", "-z", cwd=cwd).decode("utf-8").split("\0"):
        vol = os.path.join(cwd, pad)
        if pad and os.path.isfile(vol):
            with open(vol, "rb") as f:
                bronnen.append((f"werkkopie {pad}", f.read()))
    return bronnen


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
            if r.lower().startswith("claude-" + "session:")]


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
        # tests/ bevat bewust neppaden en nepadressen als testdata. Echte gegevens, sessie-ids
        # en de skill-repo worden ook in tests/ gezocht, door de twee tests hieronder.
        meldingen = []
        for pad, inhoud in self.blobs:
            if not pad.startswith("tests/"):
                meldingen += scan_inhoud(pad, inhoud)
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_geen_echte_gegevens_van_deze_machine_in_enig_bestand(self):
        paden = zoek_echte_gegevens(self.blobs, echte_gegevens())
        self.assertEqual(paden, [], "echte homemap of e-mailadres gevonden in (een oude "
                         "versie van): " + ", ".join(paden))

    def test_geen_sessie_ids_in_geschiedenis_berichten_of_werkkopie(self):
        """Draait altijd, ook zonder BUILDFLOW_SKILL_REPO. Ook tests/: elke versie van elk
        bestand op elke ref, de commit- en tagberichten en de werkkopie."""
        fouten = scan_sessies(sessie_waarden(), blobs=self.blobs)
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_geen_skillrepo_in_geschiedenis_berichten_of_werkkopie(self):
        """Slaat zichtbaar over als BUILDFLOW_SKILL_REPO niet gezet is."""
        geheim = skillrepo_waarden({SKILL_REPO_OMGEVING: skill_repo(self)})
        self.assertTrue(geheim)
        fouten = [f for f in scan_sessies(geheim, blobs=self.blobs)
                  if SKILL_REPO_OMGEVING in f]
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_auteurs_committers_en_taggers_zijn_github_noreply(self):
        fouten = metadata_fouten(self.commits, self.tags)
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_commitberichten_bevatten_niets_persoonlijks(self):
        fouten = bericht_fouten(self.commits)
        self.assertEqual(fouten, [], "\n".join(fouten))

    def test_rapport_auteursregels_en_claude_session_trailers(self):
        """Slaagt altijd en laat zien wat er staat; trailers zelf zijn een fout in
        test_geen_sessie_ids_in_geschiedenis_berichten_of_werkkopie."""
        auteurs = sorted({f"{c['an']} <{c['ae']}>" for c in self.commits}
                         | {f"{c['cn']} <{c['ce']}>" for c in self.commits})
        trailers = session_trailers(self.commits)
        tekst = [f"cp10 ter beoordeling: auteurs/committers in {len(self.commits)} commits:"]
        tekst += [f"  {a}" for a in auteurs]
        if trailers:
            tekst.append(f"cp10 ter beoordeling: {len(trailers)} commits met een "
                         "Claude-Session-trailer:")
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
                    f"{self.TRAILER} {self.URL}session_abc",
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

    # Nep-ids, links en trailers worden hier opgebouwd, zodat ze niet letterlijk in dit
    # bestand staan en de scan over de werkkopie er niet op aanslaat.
    LANG_ID = "session_" + "Qx7" * 8
    URL = "https://claude.ai" + "/code/"
    TRAILER = "Claude-" + "Session:"

    def plekken(self, bronnen):
        return sorted({f.split(":")[0] for f in sessie_en_skillrepo_fouten(bronnen, [])})

    def test_afgekapte_ids_in_link_of_trailer_worden_gevonden(self):
        bronnen = [("link-kort", f"zie {self.URL}session_ABCdef123 hier\n".encode()),
                   ("link-nep-afgekapt", f"'{self.URL}{NEP_SESSIE[:20]}'\n".encode()),
                   ("link-zonder-id", f"<a href=\"{self.URL}\">x</a>\n".encode()),
                   ("link-hoofdletters", f"{self.URL.upper()}session_x\n".encode()),
                   ("trailer-kort", f"x\n{self.TRAILER} 01AbCd\n".encode()),
                   ("trailer-nep-afgekapt", f"{self.TRAILER} {NEP_SESSIE[:20]}\n".encode()),
                   ("trailer-leeg", f"{self.TRAILER}\n".encode()),
                   ("trailer-kleine-letters", f"{self.TRAILER.lower()} abc\n".encode()),
                   ("nep-link", f"zie {self.URL}{NEP_SESSIE}.\n".encode()),
                   ("nep-trailer-link", f"{self.TRAILER} {self.URL}{NEP_SESSIE}\n".encode()),
                   ("nep-trailer-id", f"{self.TRAILER} {NEP_SESSIE}\n".encode()),
                   ("trailer-midden-in-regel", f"de waarde achter `{self.TRAILER}`\n".encode()),
                   ("schoon", b"claude.ai en code/ los van elkaar\n")]
        self.assertEqual(self.plekken(bronnen),
                         ["link-hoofdletters", "link-kort", "link-nep-afgekapt",
                          "link-zonder-id", "trailer-kleine-letters", "trailer-kort",
                          "trailer-leeg", "trailer-nep-afgekapt"])

    def test_verzonnen_id_met_extra_tekens_in_link_of_trailer_is_fout(self):
        bronnen = [("link", f"{self.URL}{NEP_SESSIE}Z\n".encode()),
                   ("trailer", f"{self.TRAILER} {NEP_SESSIE}Z\n".encode())]
        self.assertEqual(self.plekken(bronnen), ["link", "trailer"])

    def test_scope_brede_patronen_in_werkkopie_en_berichten_smalle_in_oude_blobs(self):
        import struct
        import zlib
        # Oude blobs: korte, verzonnen links en trailers (zoals in de oude testdata) tellen
        # niet, een lang id wel, ook in een PNG-tekstchunk.
        self.commit("tests/oud.py", f"u = '{self.URL}session_ab'\n{self.TRAILER} 01Ab\n"
                    .encode(), bericht="schoon")
        data = b"Comment\0\0" + zlib.compress(f"{self.URL}session_q".encode())
        png = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(data)) + b"zTXt" + data
               + b"\0\0\0\0")
        self.commit("assets/x.png", png, bericht="schoon")
        self.commit("tests/lang.py", f"id = '{self.LANG_ID}'\n".encode(), bericht="schoon")
        # Alles weer schoon in de werkkopie, zodat alleen de oude versies over zijn.
        for pad in ("tests/oud.py", "tests/lang.py", "assets/x.png"):
            self.g("rm", "-q", pad)
        self.g("commit", "-q", "-m", "schoon")
        # Een afgekapte link in een bericht en een afgekapte trailer in de werkkopie.
        self.commit("index.html", b"x\n", bericht=f"x\n\nzie {self.URL}{NEP_SESSIE[:20]}")
        with open(os.path.join(self.tmp, "index.html"), "w") as f:
            f.write(f"<p>{self.TRAILER} {NEP_SESSIE[:20]}</p>\n")
        fouten = scan_sessies([], cwd=self.tmp)
        plekken = collections.Counter(f.split(":")[0].split(" ")[0] + " "
                                      + f.split(":")[0].split(" ")[-1] for f in fouten)
        laatste = git("rev-parse", "HEAD", cwd=self.tmp).decode().strip()[:12]
        self.assertEqual(plekken, collections.Counter({
            "geschiedenis tests/lang.py": 1, f"commit {laatste}": 1,
            "werkkopie index.html": 1}), fouten)
        # Dezelfde korte link is in een blob wel fout als de brede scan erover gaat.
        self.assertEqual(len(sessie_en_skillrepo_fouten(
            [("x", f"{self.URL}session_ab".encode())], [], breed=True)), 1)

    def test_gecodeerde_links_en_trailer_midden_in_regel_worden_gevonden(self):
        json_url = self.URL.replace("/", "\\/")
        pct_url = urllib.parse.quote(self.URL, safe=":")
        bronnen = [("json", f'{{"u": "{json_url}session_ab"}}\n'.encode()),
                   ("json-hoofdletters", f'"{json_url.upper()}X"\n'.encode()),
                   ("pct", f"?next={pct_url}session_ab&x=1\n".encode()),
                   ("pct-klein", f"?next={pct_url.lower()}session_ab\n".encode()),
                   ("pct-nep", f"?next={pct_url}{NEP_SESSIE}&x=1\n".encode()),
                   ("trailer-midden", f"tekst {self.TRAILER} 01AbCd\n".encode()),
                   ("trailer-in-html", f"<p>{self.TRAILER.upper()} x</p>\n".encode()),
                   ("trailer-vervangen", f"{self.TRAILER} [sessielink]\n".encode()),
                   ("trailer-genoemd", f"de waarde achter `{self.TRAILER}` wordt\n".encode())]
        self.assertIn("%2F", pct_url)
        fouten = sessie_en_skillrepo_fouten(bronnen, [])
        self.assertEqual(collections.Counter(f.split(":")[0] for f in fouten),
                         collections.Counter({"json": 1, "json-hoofdletters": 1, "pct": 1,
                                              "pct-klein": 1, "trailer-midden": 1,
                                              "trailer-in-html": 1}), fouten)
        self.assertEqual(sessie_en_skillrepo_fouten(bronnen, [], breed=False), [])

    def test_skillrepo_test_slaat_zichtbaar_over_en_sessiescan_draait_zonder_variabele(self):
        env = {k: v for k, v in os.environ.items() if k != SKILL_REPO_OMGEVING}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(skillrepo_waarden(), [])
            with self.assertRaises(unittest.SkipTest) as ctx:
                skill_repo(self)
            self.assertIn(f"{SKILL_REPO_OMGEVING} niet gezet", str(ctx.exception))
            fouten = sessie_en_skillrepo_fouten([("x", f"{self.URL}session_a".encode())],
                                                geheime_waarden())
            self.assertEqual(len(fouten), 1, fouten)

    def test_lange_sessie_ids_worden_gevonden_ook_in_tests(self):
        bronnen = [("tests/a.py", f"url = '{self.URL}{self.LANG_ID}'\n".encode()),
                   ("README.md", f"{self.TRAILER} {self.LANG_ID}\n".encode()),
                   ("tests/b.py", b"kort = 'session_ABCdef123'\n"),
                   ("tests/c.py", f"nep = '{NEP_SESSIE}'\n".encode()),
                   ("tests/d.py", f"af = '{NEP_SESSIE[:20]}'\n".encode())]
        fouten = sessie_en_skillrepo_fouten(bronnen, [])
        # Per bron: het lange id zelf, plus de link of de trailer eromheen.
        self.assertEqual(collections.Counter(f.split(":")[0] for f in fouten),
                         collections.Counter({"README.md": 2, "tests/a.py": 2}), fouten)
        self.assertFalse(any(self.LANG_ID in f for f in fouten), "id helemaal getoond")

    def test_verzonnen_id_met_extra_tekens_is_geen_uitzondering(self):
        fouten = sessie_en_skillrepo_fouten([("x", (NEP_SESSIE + "Z").encode())], [])
        self.assertEqual(len(fouten), 1, fouten)

    def test_sessie_id_in_png_tekstchunk_wordt_gevonden(self):
        import struct
        import zlib
        data = b"Comment\0\0" + zlib.compress(self.LANG_ID.encode())
        chunk = struct.pack(">I", len(data)) + b"zTXt" + data + b"\0\0\0\0"
        png = b"\x89PNG\r\n\x1a\n" + chunk
        self.assertEqual(len(sessie_en_skillrepo_fouten([("a.png", png)], [])), 1)

    def test_sessie_id_en_skillrepo_uit_de_omgeving_worden_gevonden(self):
        kaal = "Zq" * 12
        env = {"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_" + kaal,
               "CLAUDE_CODE_SESSION_ID": "0f0f0f0f-aaaa-bbbb-cccc-121212121212",
               SKILL_REPO_OMGEVING: "iemand/Geheime-Skills"}
        geheim = geheime_waarden(env)
        bronnen = [("verkort", f"{self.TRAILER} {kaal[:12]}\n".encode()),
                   ("uuid", b"id 0f0f0f0f-aaaa-bbbb-cccc-121212121212\n"),
                   ("repo", b"zie github.com/iemand/geheime-skills\n"),
                   ("alleen-naam", b"de map GEHEIME-SKILLS\n"),
                   ("schoon", b"niets hier\n")]
        fouten = sessie_en_skillrepo_fouten(bronnen, geheim)
        self.assertEqual(sorted({f.split(":")[0] for f in fouten}),
                         ["alleen-naam", "repo", "uuid", "verkort"], fouten)
        self.assertFalse(any(kaal[:12] in f or "geheime" in f.lower() for f in fouten),
                         "de gevonden waarde hoort niet in de melding")
        self.assertEqual(geheime_waarden({}), [])

    def test_sessie_id_in_commitbericht_en_tag_wordt_gevonden(self):
        self.commit("index.html", b"x\n", bericht=f"x\n\n{self.TRAILER} {self.LANG_ID}")
        self.g("tag", "-a", "v0.0.1", "-m", f"zie {self.LANG_ID}")
        fouten = sessie_en_skillrepo_fouten(berichten_als_bronnen(self.tmp), [])
        # Commit: het id en de trailer; tag: alleen het id.
        self.assertEqual(collections.Counter(f.split(" ")[0] for f in fouten),
                         collections.Counter({"commit": 2, "tag": 1}), fouten)

    def test_werkkopie_wordt_gescand(self):
        self.commit("tests/a.py", b"schoon\n")
        with open(os.path.join(self.tmp, "tests", "a.py"), "w") as f:
            f.write(self.LANG_ID)
        fouten = sessie_en_skillrepo_fouten(werkkopie_bronnen(self.tmp), [])
        self.assertEqual(len(fouten), 1, fouten)
        self.assertIn("werkkopie tests/a.py", fouten[0])

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
    verzoek = urllib.request.Request(url, headers={"User-Agent": "buildflow-cp10"})
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def echte_release(versie=VERSIE):
    """Versie, datum en grootte van de gepubliceerde release, via de publieke GitHub-API.

    Met dezelfde notatie als release.py op de pagina zet: nl_datum voor publishedAt (in de
    lokale tijdzone, zoals release.py 'vandaag' bepaalt) en kb voor de grootte van
    buildflow.zip.
    """
    import datetime
    import json
    release = cp06.importeer_release()
    status, body = haal(f"https://api.github.com/repos/{REPO_NAAM}/releases/tags/{versie}")
    if status != 200:
        raise AssertionError(f"release {versie} opvragen gaf {status}")
    data = json.loads(body)
    zips = [a for a in data["assets"] if a["name"] == "buildflow.zip"]
    if len(zips) != 1:
        raise AssertionError(f"release {versie} heeft geen (unieke) buildflow.zip: "
                             f"{[a['name'] for a in data['assets']]}")
    gepubliceerd = datetime.datetime.fromisoformat(data["published_at"].replace("Z", "+00:00"))
    return sorted([("datum", release.nl_datum(gepubliceerd.astimezone().date())),
                   ("grootte", release.kb(zips[0]["size"])),
                   ("versie", data["tag_name"])])


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
        # Elke waarde op de live pagina hoort bij de echte release op GitHub.
        echt = dict(echte_release())
        for soort, waarde in release_waarden(live_html):
            with self.subTest(soort=soort):
                self.assertEqual(waarde, echt[soort],
                                 f"{soort} op de live pagina wijkt af van release {VERSIE}")
        self.assertEqual({s for s, _ in release_waarden(live_html)}, set(echt),
                         "de live pagina toont niet alle releasewaarden")

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


def skill_repo(test):
    """De naam van de private skill-repo uit de omgeving; die staat nergens in de repo."""
    repo = os.environ.get(SKILL_REPO_OMGEVING, "").strip().strip("/")
    if not repo:
        test.skipTest(f"{SKILL_REPO_OMGEVING} niet gezet; zet die op eigenaar/naam van de "
                      "private skill-repo om te toetsen dat hij privé blijft")
    if "/" not in repo:
        repo = f"{REPO_NAAM.split('/')[0]}/{repo}"
    return repo


class LiveRepos(LiveBasis):
    def test_buildflow_repo_is_openbaar(self):
        status, body = haal(f"https://api.github.com/repos/{REPO_NAAM}")
        self.assertEqual(status, 200)
        self.assertIn(b'"private": false', body.replace(b'"private":false', b'"private": false'))

    def test_skillrepo_is_anoniem_niet_te_zien(self):
        status, _ = haal(f"https://api.github.com/repos/{skill_repo(self)}")
        self.assertEqual(status, 404, "de skill-repo is zonder inloggen te zien")

    def gh(self, *args):
        if shutil.which("gh") is None:
            self.skipTest("gh ontbreekt")
        tmp = tempfile.mkdtemp(prefix="bf-cp10-gh-")
        self.addCleanup(shutil.rmtree, tmp, True)
        uit = subprocess.run(["gh", *args], cwd=tmp, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        return uit.stdout

    def test_skillrepo_is_private_volgens_gh(self):
        uit = self.gh("repo", "view", skill_repo(self), "--json", "visibility")
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
