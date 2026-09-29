"""Controles op de statische site, alleen met de stdlib.

Gebruikt door de tests; kan ook los draaien: python3 tests/check_site.py
"""
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
CSS = os.path.join(ROOT, "assets", "site.css")
DESIGN_MD = os.path.join(ROOT, "docs", "design", "design.md")
PROTOTYPE = os.path.join(ROOT, "docs", "design", "prototype", "index.html")

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr"}
# Lokale verwijzingen onder deze mappen horen bij een later checkpoint (voorbeeld/: cp08).
# Ze worden alleen overgeslagen zolang de map nog niet bestaat. Staat de map er, dan moet
# elke link erin kloppen.
LATER = ("voorbeeld/",)
# Binnen svg en math telt <x/> wel als zelfsluitend (foreign content in HTML5).
FOREIGN = {"svg", "math"}


def lees(pad):
    with open(pad, encoding="utf-8") as f:
        return f.read()


class Element:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self.text = []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def iter(self):
        yield self
        for c in self.children:
            yield from c.iter()

    def alle_tekst(self):
        return "".join(self.text) + "".join(c.alle_tekst() for c in self.children)


class Pagina(HTMLParser):
    """Bouwt een simpele boom en houdt nestfouten bij."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", [], None)
        self.stack = [self.root]
        self.fouten = []
        self.feed(html)
        self.close()
        for el in self.stack[1:]:
            self.fouten.append(f"niet gesloten: <{el.tag}>")

    def handle_starttag(self, tag, attrs):
        el = Element(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        # HTML5 negeert de slash bij gewone elementen: <div/> opent een <div>.
        # Alleen void-elementen en elementen in svg/math zijn echt zelfsluitend.
        if tag in VOID or any(e.tag in FOREIGN for e in self.stack):
            el = Element(tag, attrs, self.stack[-1])
            self.stack[-1].children.append(el)
        else:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        top = self.stack[-1]
        if len(self.stack) > 1 and top.tag == tag:
            self.stack.pop()
            return
        self.fouten.append(
            f"</{tag}> sluit <{top.tag}> (regel {self.getpos()[0]})")
        # herstel: pop tot het passende element als dat bestaat
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].text.append(data)

    def elementen(self):
        return list(self.root.iter())[1:]


def heeft_schema(url):
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url)) or url.startswith("//")


def controleer_links(html, root=ROOT):
    """Geeft een lijst foutmeldingen voor kapotte #ankers en ontbrekende lokale bestanden."""
    pagina = Pagina(html)
    fouten = []
    ids = {el.attrs["id"] for el in pagina.elementen() if el.attrs.get("id")}
    for el in pagina.elementen():
        for attr in ("href", "src"):
            waarde = el.attrs.get(attr)
            if waarde is None:
                continue
            waarde = waarde.strip()
            if waarde.startswith("#"):
                doel = waarde[1:]
                if not doel:
                    fouten.append(f"lege '#' in <{el.tag} {attr}>")
                elif doel not in ids:
                    fouten.append(f"anker zonder doel: {waarde}")
                continue
            if not waarde or heeft_schema(waarde):
                continue
            pad = re.split(r"[?#]", waarde)[0]
            if not pad:
                continue
            later = next((m for m in LATER if pad.startswith(m)), None)
            if later and not os.path.isdir(os.path.join(root, later)):
                continue
            if not os.path.exists(os.path.join(root, pad.lstrip("/"))):
                fouten.append(f"bestand ontbreekt: {pad}")
    return fouten


def css_tokens(tekst):
    """Zet de :root{...}-blokken om in {naam: waarde}, zonder commentaar.

    Een token dat in twee :root-blokken een andere waarde krijgt, geeft een ValueError:
    dan is niet meer te zeggen welke waarde de pagina echt gebruikt.
    """
    tekst = re.sub(r"/\*.*?\*/", "", tekst, flags=re.S)
    blokken = re.findall(r"(?<![\w-]):root\s*\{(.*?)\}", tekst, flags=re.S)
    if not blokken:
        return None
    paren = {}
    for blok in blokken:
        for decl in blok.split(";"):
            if ":" not in decl:
                continue
            naam, waarde = decl.split(":", 1)
            naam, waarde = naam.strip(), " ".join(waarde.split())
            if naam in paren and paren[naam] != waarde:
                raise ValueError(f"{naam} staat twee keer in :root, als "
                                 f"{paren[naam]!r} en als {waarde!r}")
            paren[naam] = waarde
    return paren


def design_tokens(design_md=DESIGN_MD):
    for blok in re.findall(r"```css\n(.*?)```", lees(design_md), flags=re.S):
        if ":root" in blok:
            return css_tokens(blok)
    return None


if __name__ == "__main__":
    html = lees(INDEX)
    fouten = Pagina(html).fouten + controleer_links(html)
    print("\n".join(fouten) or "ok")
    sys.exit(1 if fouten else 0)
