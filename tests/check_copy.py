"""Controleert de zichtbare tekst van de pagina op AI-taal, alleen met de stdlib.

De vermijdlijst komt uit de schrijfstijl in ~/.claude/CLAUDE.md (Nederlands en Engels) en de
learnings van dit project. Tekst in <script>, <style>, <code>, <pre> en commentaar telt niet
mee; alt, title en aria-label wel, want die leest of hoort een bezoeker ook. Hetzelfde geldt
voor de <title> en de beschrijvingen in <meta> die zoekmachines en previews tonen.

Los draaien: python3 tests/check_copy.py
"""
import os
import re
import sys
from html.parser import HTMLParser

INDEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")

# Hooguit een handvol gedachtestreepjes op de hele pagina. Een en-streepje met spaties
# eromheen (" – ") telt ook, een en-streepje in een bereik als 1–2 niet.
MAX_STREEPJES = 5

# Elk patroon is een regex zonder woordgrenzen; die komen er in _PATRONEN omheen.
# Verbogen vormen staan erbij: "naadloze" is net zo goed AI-taal als "naadloos".
VERMIJD = [
    "bovendien", "daarnaast", "tevens", "voorts",
    "niet alleen", "het is belangrijk om op te merken", r"het is (?:essentieel|cruciaal)",
    "samenvattend", "kortom", "al met al", "in de kern", "op het gebied van",
    "een breed scala aan", r"spel(?:en|t) een (?:cruciale|belangrijke) rol",
    r"in het (?:huidige|steeds veranderende) landschap",
    r"naadlo(?:os|ze)", r"robuuste?", r"holistische?", r"cruci(?:aal|ale)",
    r"essenti(?:eel|[eë]le)", r"faciliteer\w*", r"faciliteren", r"faciliteert",
    r"optimaliseren", "inzetten op", "koers zetten naar",
]
# Engelse lijst uit dezelfde schrijfstijl, met verbogen vormen.
VERMIJD_EN = [
    r"delv(?:e|es|ed|ing)", "tapestry", "testament", "pivotal", "crucial(?:ly)?",
    r"robust(?:ly|ness)?", r"seamless(?:ly)?", r"leverag(?:e|es|ed|ing)",
    r"utili[sz](?:e|es|ed|ing)", r"landscapes?", "multifaceted", r"holistic(?:ally)?",
    "moreover", "furthermore", r"game[- ]changers?", "cutting[- ]edge", "transformative",
    r"revolutioni[sz](?:e|es|ed|ing)", r"unlock(?:s|ed|ing)?", "in the realm of",
    r"it'?s important to note", r"in today'?s (?:fast-paced|ever-evolving) world",
    "in conclusion", "in summary", r"not only", r"boasts?", r"serves as",
]
VERMIJD = VERMIJD + VERMIJD_EN
_PATRONEN = [(p, re.compile(r"(?<!\w)(?:" + p + r")(?!\w)", re.I)) for p in VERMIJD]
# "Echter" en "additionally" mogen midden in een zin, niet als eerste woord.
_ECHTER = re.compile(r"(?:^|[.!?:]\s+)(echter|additionally)\b", re.I)
# <meta> met tekst die een bezoeker ziet in zoekresultaten en previews.
_META_TEKST = {"description", "og:title", "og:description", "og:image:alt", "og:site_name",
               "twitter:title", "twitter:description", "twitter:image:alt"}

_OVERSLAAN = {"script", "style", "code", "pre", "template", "noscript"}
_ATTRS = ("alt", "title", "aria-label")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}


class _Tekst(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stukken = []
        self.stack = []

    def _verborgen(self):
        return any(t in _OVERSLAAN for t in self.stack)

    def _attrs(self, attrs):
        if self._verborgen():
            return
        for naam, waarde in attrs:
            if naam in _ATTRS and waarde:
                self.stukken.append(waarde)

    def _meta(self, tag, attrs):
        if tag != "meta":
            return
        a = dict(attrs)
        sleutel = (a.get("name") or a.get("property") or "").lower()
        if sleutel in _META_TEKST and a.get("content"):
            self.stukken.append(" " + a["content"] + " . ")

    def handle_starttag(self, tag, attrs):
        self._meta(tag, attrs)
        self._attrs(attrs)
        if tag not in _VOID:
            self.stack.append(tag)
        else:
            self.stukken.append(" ")

    def handle_startendtag(self, tag, attrs):
        self._meta(tag, attrs)
        self._attrs(attrs)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        # blokgrens: zinnen uit verschillende elementen niet aan elkaar plakken
        self.stukken.append(" ")

    def handle_data(self, data):
        if not self._verborgen():
            self.stukken.append(data)


def zichtbare_tekst(html):
    parser = _Tekst()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.stukken).split())


def _zin(tekst, start, eind):
    begin = max(tekst.rfind(t, 0, start) for t in ".!?") + 1
    einden = [i for i in (tekst.find(t, eind) for t in ".!?") if i != -1]
    stop = min(einden) + 1 if einden else len(tekst)
    return tekst[begin:stop].strip()


def tel_streepjes(tekst):
    return tekst.count("—") + tekst.count(" – ")


def controleer_copy(html):
    """Geeft een lijst meldingen; leeg betekent dat de tekst schoon is."""
    tekst = zichtbare_tekst(html)
    meldingen = []
    for _, patroon in _PATRONEN:
        for m in patroon.finditer(tekst):
            meldingen.append(f"'{m.group(0).lower()}' in: {_zin(tekst, m.start(), m.end())}")
    for m in _ECHTER.finditer(tekst):
        meldingen.append(f"'{m.group(1).lower()}' aan het begin van een zin in: "
                         f"{_zin(tekst, m.start(1), m.end(1))}")
    streepjes = tel_streepjes(tekst)
    if streepjes > MAX_STREEPJES:
        meldingen.append(f"{streepjes} gedachtestreepjes (— of ' – '), hooguit {MAX_STREEPJES}")
    return meldingen


if __name__ == "__main__":
    with open(INDEX, encoding="utf-8") as f:
        uit = controleer_copy(f.read())
    print("\n".join(uit) or "ok")
    sys.exit(1 if uit else 0)
