# Huisstijl Bakkerij Korrel

Alle stijl staat in één bestand: `style.css`, rechtstreeks geladen door `index.html`. Geen buildstap, geen framework, geen componentbibliotheek, geen iconenset en geen webfont. Klassen en variabelen hebben Nederlandse namen (`kop`, `held`, `voet`, `--tekst`, `--lijn`); nieuwe onderdelen volgen dat.

## Tokens

CSS custom properties op `:root` in `style.css`. Regels gebruiken alleen `var(--...)`, er staan geen losse kleuren buiten `:root`. Houd dat zo.

| Variabele | Licht (bestaand) | Donker (nieuw) | Gebruik |
|---|---|---|---|
| `--bg` | `#fbf7f0` | `#1f1813` | achtergrond van `body` |
| `--tekst` | `#2b2118` | `#f3e9da` | lopende tekst, `nav a`, knoptekst |
| `--accent` | `#c2622d` | `#e08a5a` | `.logo`, `h2`, focusrand |
| `--lijn` | `#e3d8c7` | `#4a3b30` | randen van `.kop`, `h2`, `.voet`, knop |
| `--font` | `Georgia, "Times New Roman", serif` | gelijk | alles, ook knoppen (`font: inherit`) |

Het donkere palet is een tweede set waarden voor dezelfde variabelen, zodat de rest van de stylesheet niet verandert:

```css
:root { color-scheme: light; /* bestaande variabelen */ }
:root[data-thema="donker"] {
  color-scheme: dark;
  --bg: #1f1813;
  --tekst: #f3e9da;
  --accent: #e08a5a;
  --lijn: #4a3b30;
}
```

`color-scheme` zorgt dat de browser scrollbalken en standaardelementen in de juiste stand tekent.

Zonder JavaScript krijgt `<html>` geen `data-thema`. Dan volgt de site de systeeminstelling via een CSS-terugval:

```css
@media (prefers-color-scheme: dark) {
  :root:not([data-thema]) {
    color-scheme: dark;
    --bg: #1f1813;
    --tekst: #f3e9da;
    --accent: #e08a5a;
    --lijn: #4a3b30;
  }
}
```

De donkere waarden staan daardoor twee keer in `style.css`. Dat is bewust: CSS kan een blok niet onder twee voorwaarden tegelijk laten gelden zonder buildstap. De tabel hierboven is de bron. Wie een donkere waarde wijzigt, past beide blokken aan; zet in `style.css` bij beide blokken een korte opmerking die naar het andere verwijst.

### Contrast (WCAG 2.x, berekend)

| Paar | Licht | Donker | Eis |
|---|---|---|---|
| `--tekst` op `--bg` (tekst, `nav a`, knop) | 14,75:1 | 14,59:1 | 4,5:1, haalt het |
| `--accent` op `--bg` (`.logo`, `h2`, focusrand) | 3,87:1 | 6,64:1 | zie hieronder |
| `--lijn` op `--bg` (decoratieve randen, rustrand knop) | 1,32:1 | 1,64:1 | geen eis, alleen scheidingslijn |
| `--accent` op `--bg` (rand van ingedrukte knop) | 3,87:1 | 6,64:1 | 3:1 (niet-tekst), haalt het |

Het lichte accent haalt 4,5:1 niet. Voor `.logo` (1,25rem vet) en `h2` (1,5em vet) is dat binnen AA, want grote tekst vraagt 3:1. Gebruik het lichte accent dus niet voor gewone tekst of links in lopende tekst. Het donkere accent haalt 4,5:1 wel en mag overal.

De kleuren van het lichte thema veranderen niet. De kop wel, in beide thema's: door de knop en `flex-wrap` wordt hij hoger (zie "Component: themaknop").

## Typografie en ruimte

- `body`: `line-height: 1.6`, marge 0.
- `.held h1`: `2rem`, `line-height: 1.2`.
- `h2`: accentkleur, `border-bottom: 1px solid var(--lijn)`, `padding-bottom: 4px`.
- `.voet`: `.9rem`, gecentreerd.
- Ruimtematen in gebruik: 4px, 8px, 12px, 16px, 24px. 8px en 12px zijn nieuw met de themaknop: 8px voor de rij-afstand in een gewrapte kop en tussen icoon en woord, 12px voor de zijpadding van de knop, zodat de pilvorm compact blijft naast de nav. Randen zijn `1px solid var(--lijn)`; de enige uitzondering is de ingedrukte themaknop (`var(--accent)`).
- Maten die geen ruimte zijn: klikvlak minimaal 44×44px (WCAG 2.5.5-richtlijn voor aanraakdoelen), en `border-radius: 22px` (de helft van 44px, voor een pilvorm). Beide gelden alleen voor de themaknop.

## Layout en patronen

- `.kop`: flexbox, `justify-content: space-between`, `align-items: center`, `padding: 16px 24px`, lijn eronder. Bevat `.logo` (link, vet, `1.25rem`, accent, geen onderstreping) en `nav` met ankerlinks (`nav a`: tekstkleur, onderstreept, `margin-left: 16px`).
- `main`: `max-width: 720px`, gecentreerd, `padding: 24px`. Secties zijn `<section>` met een `h2`.
- `.held`: eerste sectie met `h1` en een alinea.
- Lijsten: gewone `<ul>` zonder eigen stijl.
- `.voet`: `padding: 24px`, lijn erboven.
- Breakpoints: er zijn er nog geen. De themaknop voegt geen breakpoint toe (zie hieronder).

## Component: themaknop

Nieuwe klasse `.themaknop`, één woord zoals `kop` en `voet`. Staat in `header.kop` direct na `<nav>`, dus rechts.

```html
<button type="button" class="themaknop" aria-pressed="false">
  <svg class="themaknop-maan" aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24"
       fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
  <span class="themaknop-woord">Donker</span>
</button>
```

Het is een aan/uit-knop. Woord en icoon zijn vast; alleen `aria-pressed` en de rand wisselen:

| Actief thema | `aria-pressed` | Zichtbaar woord | Icoon | Rand |
|---|---|---|---|---|
| licht | `false` | Donker | maan | `var(--lijn)` |
| donker | `true` | Donker | maan | `var(--accent)` |

De toegankelijke naam is "Donker", het zichtbare woord (geen `aria-label`). `aria-pressed` is de enige drager van de stand: een schermlezer meldt "Donker, schakelknop, ingedrukt" als het donkere thema aan staat. Er is één inline SVG (`.themaknop-maan`, een maansikkel als enkel pad) met `stroke="currentColor"`, zonder icoonwissel. Het woord staat in `<span class="themaknop-woord">`. Beide klassen zijn alleen haakjes voor tests en latere aanpassingen; ze krijgen geen eigen stijl, alle opmaak zit op `.themaknop`. Geen iconenset, geen teken uit een font; een tekstglyph als ☾ valt in Georgia terug op een ander lettertype en oogt dan per toestel anders.

Stijl, alleen met tokens:

```css
.kop { flex-wrap: wrap; gap: 8px 16px; }
.logo { white-space: nowrap; }
nav { margin-left: auto; white-space: nowrap; }
.themaknop {
  display: inline-flex; align-items: center; gap: 8px;
  min-height: 44px; min-width: 44px; padding: 0 12px;
  font: inherit; color: var(--tekst); background: transparent;
  border: 1px solid var(--lijn); border-radius: 22px; cursor: pointer;
}
:root[data-thema="donker"] .themaknop { border-color: var(--accent); }
.themaknop:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
:root:not([data-thema]) .themaknop { display: none; }
```

De ingedrukte stand hangt aan `data-thema` op `<html>` en niet aan `aria-pressed`. Het head-script zet dat attribuut al voor het tekenen, dus de rand klopt vanaf de eerste frame, ook voordat het script onderaan de body `aria-pressed` heeft gezet.

De rustrand in `--lijn` (1,32:1 licht, 1,64:1 donker) is decoratief. Het woord "Donker" maakt de knop herkenbaar als bedieningselement, niet de rand. De rand van de ingedrukte knop in `--accent` haalt 6,64:1 op de donkere achtergrond, ruim boven de 3:1 voor niet-tekstuele elementen. (Op de lichte achtergrond zou dezelfde rand 3,87:1 halen, maar in het lichte thema is de knop nooit ingedrukt.) De focusrand in `--accent` haalt 3:1 in beide thema's (3,87 en 6,64). Het klikvlak is minstens 44×44px.

Smalle schermen: de kop mag wrappen (`flex-wrap: wrap`); het woord blijft zichtbaar. Gekozen boven het verbergen van het woord, omdat de brief icoon plus woord vraagt en een los maan-icoon voor veel bezoekers niet duidelijk is. `nav { margin-left: auto }` houdt nav en knop rechts, ook op de tweede regel. Gemeten in Chromium met deze regels: op 1024px staat alles op één regel; op 360px staat het logo op regel 1 en nav plus knop rechts op regel 2 (geen horizontale scroll); op 320px komt de knop alleen op een derde regel, links uitgelijnd, nog steeds zonder overloop.

Dat de knop op 320px links staat, is een bewuste keuze. `.themaknop { margin-left: auto }` zou hem daar naar rechts duwen, maar breekt de bredere schermen: een flexregel met twee `auto`-marges verdeelt de vrije ruimte over beide. Op 1024px, en op elke breedte waar alles op één regel past, schuift de nav dan naar het midden, los van de knop: gemeten staat de nav met die regel op x=447-635, zonder op x=693-881, direct naast de knop. Een aparte breakpoint alleen voor 320px weegt daar niet tegen op.

Gevolg voor beide thema's, ook het lichte: de kop wordt hoger. Op 1024px gaat hij van 65px naar 77px (de knop is 44px hoog, de oude kop had alleen tekst). Op 360px wordt hij 117px, op 320px 151px.

## Themalogica

- Attribuut: `data-thema` op `<html>`, waarde `"licht"` of `"donker"`. CSS kijkt naar `"donker"` (thema en ingedrukte knop) en naar het ontbreken van het attribuut (geen JS).
- Opslag: `localStorage`, sleutel `korrel-thema`. Een bewaarde waarde telt alleen als die precies `"licht"` of `"donker"` is; alles anders (leeg, oud formaat, handmatig aangepast) wordt genegeerd.
- Beginstand: geldige bewaarde keuze als die er is, anders `matchMedia('(prefers-color-scheme: dark)')`. Een eigen keuze gaat altijd voor.
- Tegen flitsen: een klein inline `<script>` in de `<head>`, vóór `<link rel="stylesheet">`, leest de keuze en zet het attribuut voordat de pagina getekend wordt. Het lezen van `localStorage` staat daar in `try/catch`; faalt het, dan valt het script terug op `matchMedia` en zet het toch een attribuut.
- Knopstand: `aria-pressed` wordt gezet zodra de knop in de DOM staat, met een script onderaan `<body>` of een klein script direct na de knop (niet pas na `DOMContentLoaded`). Het uiterlijk hangt daar niet van af, zie hierboven.
- Klik: wissel het attribuut, zet `aria-pressed`, schrijf de keuze weg.
- Het wegschrijven naar `localStorage` staat ook in `try/catch`. Faalt het (privémodus, geblokkeerd), dan werkt de knop voor dit bezoek en wordt de keuze niet onthouden. Geen foutmelding.
- Geen overgangsanimatie: het thema wisselt direct.
- Zonder JavaScript: geen `data-thema`, de knop is verborgen en de site volgt de systeeminstelling via de CSS-terugval onder "Tokens".
- Buiten scope: reageren op een wijziging van de systeeminstelling tijdens een bezoek, en de keuze synchroniseren tussen open tabbladen. De nieuwe stand geldt bij het volgende laden van de pagina.

## Toon van UI-tekst

Nederlands, kort, gewone woorden, geen hoofdletters midden in zinnen. Knoppen krijgen één woord.
