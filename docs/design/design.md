# Design: buildflow website

Dit document beschrijft hoe de website voor de buildflow-skill eruitziet en werkt. De huisstijl komt uit één bestand: `assets/viewer.html` in de map van de skill. Dat is het template waar de viewer en alle rapporten uit komen, en de site moet daar zichtbaar bij horen. Deel 1 legt vast wat er in de viewer staat, met de exacte waarden. Deel 2 beschrijft wat de site daarbovenop nodig heeft, in dezelfde tokens en met dezelfde naamgeving. Deel 3 noemt wat in de viewer niet helemaal klopt en hoe de site daarmee omgaat.

Waar dit document "de viewer" zegt, bedoelt het `viewer.html` zoals die nu in de skill staat. Regelnummers verwijzen naar dat bestand.

## Uitgangspunten

De site is één pagina in gewone HTML, één CSS-bestand en een klein beetje vanilla JavaScript. Geen buildstap, geen framework, geen npm, geen libraries. De enige externe bron is Google Fonts, precies dezelfde link als in de viewer. Voorgestelde bestanden:

```
index.html
assets/site.css
assets/site.js
assets/previews/*.png      screenshots van de voorbeeldrun
voorbeeld/…                momentopnames van de viewer per stop en de echte rapporten van de voorbeeldrun
```

De site staat in de root van de repo (`index.html` en `assets/`), met een lege `.nojekyll` ernaast voor GitHub Pages. Het prototype staat in `docs/design/prototype/index.html`.

Een nieuwe stijl verzinnen is niet de bedoeling. Elke kleur, maat, radius en schaduw hieronder staat letterlijk in de viewer. Waar de site iets nieuws nodig heeft, is dat opgebouwd uit bestaande tokens en componenten, en dat staat er dan bij.

## Deel 1: de huisstijl uit de viewer

### Fonts

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900&family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&display=swap">
```

| Rol | Stack | Waar |
|---|---|---|
| Tekst | `'Source Sans 3','Segoe UI',system-ui,sans-serif` | `body` |
| Koppen | `'Archivo','Arial Narrow',system-ui,sans-serif` | `h1`–`h4`, `.display` |
| Labels, woordmerk, pillen, KPI-cijfers, tabelkoppen | `'Archivo',sans-serif` | `.eyebrow`, `.woordmerk`, `.pil`, `.kpi .w`, `.tabel th`, `.nr`, `.stap b` |
| Code | `ui-monospace,SFMono-Regular,Menlo,monospace` op `.86em` | `code`, `.mono` |

Archivo is een variabel font, en de viewer gebruikt de breedte-as via `font-stretch` (106% tot 125%) voor dat wat bredere, stevige karakter van de koppen.

### Kleur- en maattokens (`:root`, r. 10–15)

| Token | Waarde | Gebruik in de viewer |
|---|---|---|
| `--accent` | `#FFCE1F` | geel: knoppen, `.mark`, woordmerkbalk, harde schaduw, actieve stap |
| `--accent-zacht` | `#FFF1B8` | actieve navlink, `.chip.feedback` |
| `--accent-licht` | `#FFFAE6` | open checkpointkaart (`.cp-body`), `.chip.interrupted` |
| `--accent-diep` | `#8A6A00` | tekst op lichtgeel |
| `--zwart` | `#141412` | koppen, zwarte secties, footer, randen, focusring |
| `--inkt` | `#26251F` | lopende tekst |
| `--grijs` | `#686559` | secundaire tekst, eyebrows |
| `--grijs-licht` | `#9C998D` | uitgeschakeld, doorgestreept |
| `--lijn` | `#E7E4DB` | randen, scheidingslijnen |
| `--vlak` | `#F7F6F2` | lichte sectie, hover op navlinks |
| `--wit` | `#FFFFFF` | achtergrond, kaarten |
| `--fout` | `#B42318` | fout, blocker |
| `--fout-zacht` | `#FDECEA` | achtergrond van `.chip.failed` |
| `--radius` | `14px` | kaarten, prose, iframe |
| `--radius-s` | `8px` | tabellen, `.poging`, textarea |
| `--max` | `1200px` | breedte van `.wrap` |

Voor de donkere secties gebruikt de viewer ook een paar vaste kleuren zonder token:

| Waarde | Waar |
|---|---|
| `#EDEBE4` | tekst in `.sectie.zwart` |
| `#DAD7CD` | tekst in `.topbalk` |
| `#B9B6AB` | grijze tekst op zwart (`.sectie.zwart .grijs`, `.footer`, donkere KPI-labels) |
| `#1F1E1B` | kaart op zwart (`.kpi`, `.tabel`) |
| `#34322C` | rand van kaart op zwart |
| `#2A2925` | spoor van de balkgrafiek |
| `#fff` / `rgba(255,255,255,.96)` | tekst op zwart, header met blur |

Losse radii die niet via een token lopen: `999px` (pillen, knoppen, chips, `.nr`), `6px` (navlinks), `4px` (focusring, `.sev`, inline `code`), `3px` (rail, balken, checkbox).

### Typografie

| Element | Maat | Gewicht / breedte | Regelhoogte |
|---|---|---|---|
| `body` | `17px` (16px onder 640px) | 400 | 1.55 |
| `h1` | `clamp(2rem,1.4rem + 2.4vw,3.4rem)` | 800 / 108% | 1.04 |
| `h2` | `clamp(1.5rem,1.2rem + 1.2vw,2.2rem)` | 800 / 106% | 1.1 |
| `h3` | `1.2rem` | 750 | 1.25 |
| `h4` | `1rem` | 750 | – |
| `.lead` | `1.18rem` | – | 1.5 |
| `.eyebrow` | `.74rem`, hoofdletters, `letter-spacing:.14em` | 700 | – |
| `.klein` | `.9rem` | – | – |

Alle koppen krijgen `letter-spacing:-.01em` en `text-wrap:balance`.

### Componenten die de site overneemt

Dit zijn de componenten uit de viewer die de site letterlijk hergebruikt, met de markup zoals de viewer die schrijft.

**`.wrap`** is de container: `max-width:var(--max)`, `padding-inline:clamp(16px,4vw,40px)`. Elke sectie heeft er één.

**`.eyebrow`, `.mark`, `.lead`, `.grijs`, `.klein`** zijn de tekstutilities. `.mark` is de gele markeerstift onder een woord, gemaakt met `linear-gradient(transparent 58%,var(--accent) 58%)`. De viewer zet die alleen om de titel in de hero.

**`.topbalk`** is de dunne zwarte balk boven de header (`min-height:38px`, tekst `#DAD7CD`, `b` wit). Het deel met klasse `.upd` verdwijnt onder 640px.

**`.header` met `.woordmerk` en `.nav`**:

```html
<header class="header"><div class="wrap">
  <a class="woordmerk" href="#top"><b>build</b><span>flow</span></a>
  <nav class="nav"><a href="#brief">Brief</a>…</nav>
</div></header>
```

De header plakt bovenaan (`position:sticky`), is `rgba(255,255,255,.96)` met `backdrop-filter:blur(8px)` en een onderrand in `--lijn`. Het woordmerk is "build" in Archivo 900 op 125% breedte met een gele balk eronder (`b::after`, `height:.36em`), en "flow" in gewicht 500. De navlinks krijgen bij hover `--vlak` en in de actieve stand (`.actief`) `--accent-zacht` met een gele streep onderin (`box-shadow:inset 0 -2px 0 var(--accent)`). Onder 640px wordt de header statisch en de nav een horizontale strook die je kunt vegen, met een fade naar rechts (`mask-image:linear-gradient(to right,#000 82%,transparent)`) en zonder scrollbalk.

**`.pil`** is een label in hoofdletters: `.geel`, `.zwart` of `.rand` (omlijnd).

**`.knop`** is de pilvormige knop: geel standaard, `.zwart`, `.rand` (omlijnd, transparant) en `.klein` (compact). Bij hover schuift hij 1px omhoog (`transform:translateY(-1px)`, `transition:transform .15s ease`).

**`.sectie`** heeft verticale ruimte `clamp(40px,6vw,72px)` (36px onder 640px). `.sectie.vlak` is lichtgrijs, `.sectie.zwart` is zwart met lichte tekst, witte koppen, gele eyebrow en `#B9B6AB` voor `.grijs`. Donkere secties werken in de viewer alleen via deze modifier. Er is geen apart dark-mode-systeem.

**`.kop`** is de koprij van een sectie: eyebrow en h2 links, een korte grijze toelichting rechts (`max-width:60ch`), met `flex-wrap`.

**`.hero` en `.hero-grid`** vormen de openingssectie: twee kolommen in de verhouding 1.5 : 1, onder 820px één kolom.

**`.volgende`** is de kaart met 2px zwarte rand en harde gele schaduw `6px 6px 0 var(--accent)` (4px onder 640px). Dit is het meest herkenbare element van de stijl. De viewer gebruikt dezelfde schaduw op `.proto-frame` en een 4px-versie op de actieve checkpointkaart.

**`.kpis` en `.kpi`** zijn de cijfertegels. Het raster gaat van 7 naar 4 kolommen onder 1100px en naar 2 onder 640px. Op zwart wordt de tegel `#1F1E1B` met gele cijfers.

**`.stepper` en `.stap`** vormen de fasebalk: een `<ol>` met een dikke bovenrand per stap (5px). `.done` is zwart, `.current` geel, `.skipped` gestippeld met doorgestreepte naam. Zes kolommen, drie onder 820px.

**`.cp`, `.nr` en `.cp-body`** zijn de checkpointkaarten op `<details>/<summary>` met een rond genummerd badge (`.nr`, 36px, geel; zwart met gele cijfers als hij klaar is). Het open deel heeft `--accent-licht` als achtergrond.

**`.twee` en `.blok`** zijn het raster `repeat(auto-fit,minmax(260px,1fr))` met blokken met een h4 erboven.

**`.chip`** is een klein statuslabel: `passed`, `running`, `failed`, `interrupted` (gestippeld), `skipped` (doorgestreept) en `feedback`.

**`ul.check`** is een lijst met vierkantjes als bullet (`.done` vult ze zwart met een gele rand).

**`details.ctx`** is een uitklapblok met `+` en `–` rechts in de summary. Die gebruikt de site voor de vragen.

**`.proto-frame`** is een iframe met zwarte rand en harde gele schaduw.

**`.tabel` en `.tabel.stack`** zijn tabellen die onder 820px omklappen naar kaarten met labels uit `data-l`.

**`.footer`** is zwart met kleine grijze tekst, twee delen verdeeld over de breedte.

**`.toast`** is een zwarte pil onderaan in het midden die na een actie even verschijnt (`.aan`) en na 2,2 seconden weer verdwijnt.

**Focus** is voor elk element `outline:3px solid var(--zwart);outline-offset:3px;border-radius:4px`.

### Breakpoints

De viewer werkt met `max-width`-queries:

| Breedte | Wat er verandert |
|---|---|
| 1100px | KPI-raster van 7 naar 4 kolommen |
| 820px | hero één kolom, checkpointkop klapt om, tabellen worden kaarten, stepper naar 3 kolommen |
| 640px | body 16px, header statisch, nav als veegstrook, KPI's 2 kolommen, kleinere schaduw op `.volgende` en `.proto-frame` |
| print | header, nav, knoppen, feedback en toast weg; `<details>` altijd open |

De viewer is getest zonder horizontale scroll van 320 tot 1600px. Voor de site geldt dezelfde eis.

### JavaScript in de viewer

De viewer rendert alles zelf uit template-strings, met een eigen Markdown-omzetter en een vertaaltabel. De site heeft dat allemaal niet nodig: de HTML staat gewoon in `index.html`. Wat de site wel overneemt, is de manier van kopiëren: eerst `navigator.clipboard.writeText`, bij een fout een terugvaloptie, en een `.toast` als bevestiging (r. 638–649).

## Deel 2: wat de site nodig heeft

### Aanvulling op de tokens

`site.css` begint met de `:root` van de viewer, ongewijzigd. De vaste donkere kleuren krijgen in de site wel een naam, zodat ze niet op tien plekken los in de CSS staan. De waarden blijven precies zoals in de viewer:

```css
:root{
  /* letterlijk uit viewer.html */
  --accent:#FFCE1F; --accent-zacht:#FFF1B8; --accent-licht:#FFFAE6; --accent-diep:#8A6A00;
  --zwart:#141412; --inkt:#26251F; --grijs:#686559; --grijs-licht:#9C998D;
  --lijn:#E7E4DB; --vlak:#F7F6F2; --wit:#FFFFFF; --fout:#B42318; --fout-zacht:#FDECEA;
  --radius:14px; --radius-s:8px; --max:1200px;
  /* waarden die de viewer hardcodeert, hier met een naam */
  --zwart-tekst:#EDEBE4; --zwart-grijs:#B9B6AB; --zwart-kaart:#1F1E1B; --zwart-lijn:#34322C;
  --topbalk-tekst:#DAD7CD;
  --schaduw:6px 6px 0 var(--accent); --schaduw-s:4px 4px 0 var(--accent);
}
```

Er komt geen donkere modus via `prefers-color-scheme`. De viewer heeft die ook niet, en de site hoort er juist bij. Zet `<meta name="color-scheme" content="light">` in de head, zodat een browser in donkere modus formulierelementen en scrollbalken niet donker maakt. De favicon is een inline SVG-data-URI (zwart vierkant, gele balk, witte "b"), dus zonder extra bestand of request. Het donkere ritme komt uit `.sectie.zwart`, net als in de viewer.

Twee toevoegingen voor toegankelijkheid, allebei met bestaande tokens. Op zwart is de zwarte focusring onzichtbaar, dus daar wordt hij geel:

```css
.sectie.zwart :focus-visible,.footer :focus-visible,.topbalk :focus-visible,.code :focus-visible{outline-color:var(--accent)}
```

En `--grijs-licht` (#9C998D) haalt op wit maar 2,9:1 contrast. Op de site dus nooit voor tekst die je moet kunnen lezen. Gebruik `--grijs` (5,8:1 op wit, 5,4:1 op `--vlak`).

### Opbouw van de pagina

Van boven naar beneden, met de ids die de nav gebruikt:

| id | Sectie | Achtergrond | Navlabel |
|---|---|---|---|
| `top` | hero | wit | – |
| `waarde` | waarom je het gebruikt | `.sectie.vlak` | Waarde |
| `werking` | hoe het werkt: fases, stops en gates | `.sectie` | Hoe het werkt |
| `handleiding` | stap voor stap per fase | `.sectie.vlak` | Handleiding |
| `voorbeeld` | voorbeeldrun om door te klikken | `.sectie` | Voorbeeld |
| `installeren` | installeren | `.sectie.vlak` | Installeren |
| `download` | download van de release | `.sectie.zwart` | Download |
| `vragen` | beperkingen en veelgestelde vragen | `.sectie` | Vragen |
| – | footer | `.footer` | – |

Wit en `--vlak` wisselen elkaar af, zoals in de viewer. De enige zwarte sectie is de download, zodat die bij het scrollen opvalt en direct boven de footer een zwart blok vormt. Elke sectie begint met een `.kop`: eyebrow, h2 en rechts een korte grijze zin.

### Paginaschil

```html
<a class="overslaan" href="#inhoud">Naar de inhoud</a>
<div class="topbalk"><div class="wrap">
  <span>buildflow · <b data-release="versie">v1.0.0</b></span>
  <span class="upd">MIT-licentie · werkt in Claude Code</span>
</div></div>
<header class="header"><div class="wrap">
  <a class="woordmerk" href="#top" aria-label="buildflow, naar boven"><b>build</b><span>flow</span></a>
  <nav class="nav" aria-label="Secties">
    <a href="#waarde">Waarde</a><a href="#werking">Hoe het werkt</a><a href="#handleiding">Handleiding</a>
    <a href="#voorbeeld">Voorbeeld</a><a href="#installeren">Installeren</a><a href="#vragen">Vragen</a>
  </nav>
  <a class="knop klein kopknop" href="#download">Download</a>
</div></header>
<main id="inhoud">…</main>
```

Dit is de header van de viewer, met de phase-pil vervangen door een downloadknop. Het versienummer in de topbalk komt uit het releasescript (`data-release="versie"`, zie Download).

Nieuwe klassen in de schil:

`.overslaan` is een skiplink die pas zichtbaar wordt bij focus met het toetsenbord: een `.knop.zwart` linksboven (`position:absolute; left:16px; top:-60px`, bij `:focus` naar `top:8px`, `z-index:30`, boven de header).

`.kopknop` is de downloadknop rechts in de header. Die gebruikt `.knop.klein` zonder eigen stijl. Onder 640px verdwijnt hij (`display:none`), want dan staat de download al in de hero en is de nav een veegstrook.

De navlinks krijgen `.actief` als hun sectie in beeld is. De viewer heeft die stijl wel, maar zet de klasse nergens. `site.js` doet dat met een `IntersectionObserver` (`rootMargin:"-40% 0px -55% 0px"`), en de link krijgt ook `aria-current="true"`. Zonder JavaScript is er gewoon geen actieve link. De rest werkt dan nog.

Standen van de header:

| Stand | Gedrag |
|---|---|
| breed (> 820px) | woordmerk links, nav rechts (`margin-left:auto`), downloadknop helemaal rechts; sticky met blur |
| 641–820px | zoals breed; als de nav niet op één regel past, loopt hij door naar een tweede regel (`flex-wrap`, al in de viewer) |
| ≤ 640px | header statisch, nav als veegstrook onder het woordmerk, `.kopknop` weg, `section[id]{scroll-margin-top:0}` |
| hover / focus | navlink `--vlak`; focusring zwart, 3px |
| actief | `--accent-zacht` met gele streep onderin |

`section[id]{scroll-margin-top:84px}` uit de viewer blijft staan, zodat een ankerlink niet onder de sticky header valt. Zet op `html` ook `scroll-behavior:smooth`, binnen `@media (prefers-reduced-motion:no-preference)`.

### Hero

```html
<section class="hero" id="top"><div class="wrap">
  <div class="hero-grid">
    <div>
      <span class="eyebrow">Skill voor Claude Code</span>
      <h1>Grote features bouwen in <span class="mark">stappen die je kunt controleren</span></h1>
      <p class="lead">…</p>
      <div class="pillen"><span class="pil rand">Claude Code</span><span class="pil rand">python3</span><span class="pil rand">MIT</span></div>
      <p class="knoppen"><a class="knop" href="#download">Download de zip</a><a class="knop rand" href="#handleiding">Zo werkt het</a></p>
    </div>
    <div class="volgende">
      <span class="eyebrow">Zo begin je</span>
      <p>Pak de zip uit in je skills-map en start in Claude Code:</p>
      <div class="code">…<button class="kopieer">Kopieer</button></div>
    </div>
  </div>
  <ol class="stepper">…</ol>
</div></section>
```

Dit is de hero van de viewer. Links staan de titel met `.mark` en de lead. De lead noemt de gates zoals ze echt lopen: de tests en de review altijd, de UI-check tegen het prototype en de controle van de documentatie alleen als er iets op het scherm of in de docs verandert. Rechts staat de `.volgende`-kaart, die in de viewer de volgende stap toont en hier de eerste. Onder de hero staat de `.stepper` met de zes fases, als voorproefje van de sectie "Hoe het werkt". De stappen zonder stop krijgen hier `.done`, zodat de balk zwart is, en de stops krijgen een gele `.stop`-markering (zie hieronder). In `.volgende` staat de kopieerknop van `.code` boven het commando, zie bij Installeren.

Nieuw zijn `.pillen` en `.knoppen`. `.pillen` is een flexrij met pillen (`display:flex; flex-wrap:wrap; gap:6px; margin-top:18px`). `.knoppen` doet hetzelfde voor knoppen (`gap:10px; margin-top:22px`). Onder 640px worden de knoppen in `.knoppen` volle breedte (`flex:1 1 100%; justify-content:center`), zodat ze op een telefoon makkelijk te raken zijn.

### Waarde

Een `.twee`-raster met `.kaart`-blokken. Hoeveel het er worden, hangt af van wat er te zeggen valt. Het raster vult zich vanzelf, dus het ontwerp dwingt geen drie of vier af.

```html
<div class="twee">
  <article class="kaart">
    <h3>Je ziet elke stap voordat hij gebouwd wordt</h3>
    <p>…</p>
  </article>
</div>
```

`.kaart` is een nieuwe, algemene kaart, gemaakt als de `.kpi`-tegel: `background:var(--wit); border:1px solid var(--lijn); border-radius:var(--radius); padding:20px 22px`. Een `h3` erin krijgt `margin-bottom:8px`. In `.sectie.zwart` wordt de kaart `--zwart-kaart` met rand `--zwart-lijn`, net als de donkere `.kpi`.

Waar een claim een cijfer heeft (aantal gates, maximaal vier reviewrondes), kan een `.kpis`-rij met `.kpi`-tegels boven de kaarten staan. Gebruik dan echte waarden uit SKILL.md, geen voorbeeldcijfers. Kosten uit een voorbeeldrun horen hier niet thuis.

### Hoe het werkt: fases, stops en gates

Dit deel heeft drie lagen.

Bovenaan staat de fasebalk: een `.stepper` met zes `.stap`-items, dezelfde indeling als de viewer (Context, Brief, Design, Plan, Bouwen, Review). De stappen waar je zelf iets doet, krijgen `.stap.stop`: een gele bovenrand (`border-color:var(--accent)`) en onder de naam een `.pil.geel` met de tekst "stop". De andere stappen hebben de zwarte `.done`-rand. Zo zie je in één oogopslag waar Claude op jou wacht: drie of vier keer, want de designstop komt er alleen bij als de feature iets zichtbaars verandert. Met `--brief spec.md` vervalt de briefstop en met `--auto` blijven alleen de gates en de eindreview over; de site zegt dat kort als "met --brief of --auto minder". Design krijgt daarom "alleen bij UI" in de subtekst. Die stap is geen `.skipped`, want hij hoort wel in het verhaal. Met `--auto` blijft alleen de eindreview over; dat staat één keer in de tekst onder de handleiding (`#auto`), en andere plekken linken ernaar. De tekst in `.stap` gebruikt `--grijs` in plaats van `--grijs-licht` (contrastregel hierboven), en `.stap>span:not(.pil)` is een blok zodat de pil eronder valt.

```html
<ol class="stepper">
  <li class="stap done"><b>Context</b><span>Claude leest je project</span></li>
  <li class="stap stop"><b>Brief</b><span>jij keurt goed</span> <span class="pil geel">stop</span></li>
  …
</ol>
```

Daaronder staat een tussenkop `h3.sub-kop` ("De vier gates per checkpoint") en dan de gates, als `.cps`-lijst met `.kaart`-blokken die een `.nr` en een `h4` hebben. Het nummer is het gatenummer uit SKILL.md (1 gedrag, 2 UI, 3 review, 4 docs). De layout is die van de `.cp`-summary (`grid-template-columns:auto minmax(0,1fr)`), maar dan zonder uitklappen: een gate is kort genoeg om meteen te lezen. Naam: `.poort`.

```html
<div class="cps">
  <div class="kaart poort"><span class="nr">1</span><div><h4>Gedrag</h4><p>…</p></div></div>
</div>
```

`.poort` zet `display:grid; grid-template-columns:auto minmax(0,1fr); gap:16px; align-items:start`. Gates die alleen draaien als ze van toepassing zijn (UI, docs), krijgen een `.chip` "alleen als het zichtbaar is" of "alleen als er docs veranderen" naast de h4. Dat is de gewone `.chip` zonder statusklasse.

De derde laag is lopende tekst onder een tweede `h3.sub-kop`: hoe `bf.py` en de Stop-hook de regels afdwingen, en waar het idee vandaan komt (Shopify Helix, de AI Labs-video), met `.tekstlink`-links. Twee kleine hulpklassen: `.proza` houdt lopende tekst op `max-width:70ch` met 12px tussen alinea's, `.sub-kop` geeft een tussenkop `margin:40px 0 16px`.

### Stap-voor-stap-handleiding

Per fase één uitklapkaart. Dit is de `.cp`-kaart van de viewer, met dezelfde summary en hetzelfde nummer, zodat de handleiding eruitziet als een plan in de viewer. Binnenin staan twee blokken naast elkaar: wat je krijgt en wat je doet.

```html
<div class="cps">
  <details class="cp fase" id="fase-brief" open>
    <summary><span class="nr">1</span>
      <div><h3>Brief</h3><div class="sub">Claude brainstormt met je en schrijft brief.md</div></div>
      <span class="pil geel">stop</span>
    </summary>
    <div class="cp-body">
      <div class="twee">
        <div class="blok krijg"><h4>Wat je krijgt</h4><ul class="check">…</ul></div>
        <div class="blok doe"><h4>Wat je doet</h4><p>…</p></div>
      </div>
      <a class="preview klein" href="voorbeeld/viewer-brief.html">…</a>
    </div>
  </details>
</div>
```

Nieuwe klassen:

`.fase` zit bovenop `.cp` en voegt een `+`/`–`-teken rechts in de summary toe, net als `details.ctx` (`summary::after{content:'+'}` en `[open] summary::after{content:'–'}`, Archivo 800). De summary is een raster van vier kolommen: nummer, titel, pil (alleen bij een stop) en plusteken.

`.krijg` en `.doe` zijn de twee blokken. `.krijg` gebruikt `ul.check` voor de bestanden en schermen die je krijgt (`brief.md`, `design.md`, de viewer, het checkpointrapport, het eindrapport). `.doe` krijgt een gele streep links (`border-left:4px solid var(--accent); padding-left:14px`), omdat dat het deel is waar de lezer zelf aan zet is. Dat is het enige verschil met een gewoon `.blok`.

`.preview.klein` is een kleine versie van de preview uit de voorbeeldsectie (zie hieronder), met een maximale breedte van 360px.

Standen:

| Stand | Gedrag |
|---|---|
| gesloten | alleen de summary; `+` rechts |
| open | `.cp-body` met `--accent-licht` als achtergrond; `–` rechts |
| hover op summary | geen verandering; de hele summary is klikbaar (`cursor:pointer`, al in de viewer) |
| focus-visible | zwarte ring rond de summary |
| smal (≤ 820px) | drie kolommen; de pil schuift naar een tweede regel onder de titel, in de kolom van de titel; `+` blijft rechts op de eerste regel; `.twee` wordt één kolom zodra de blokken onder 260px zouden komen |
| print | alle fases open: `site.js` zet bij `beforeprint` elke dichte `details` open en bij `afterprint` weer dicht; de CSS zet `details::details-content{content-visibility:visible}`, omdat Chromium dichte details anders niet toont |

Standaard staat alleen de eerste fase open. Wie de handleiding helemaal wil lezen, klikt verder. Wie hem print, krijgt alles.

### Voorbeeldrun

Een raster van previews. De viewer is tijdens een run één bestand dat steeds wordt bijgewerkt, dus de voorbeeldrun bestaat uit momentopnames daarvan bij elke stop (`voorbeeld/viewer-brief.html`, `viewer-design.html`, `viewer-plan.html`) plus twee echte rapporten (`voorbeeld/cp01.html`, `voorbeeld/final.html`). De tekst op de site zegt dat ook zo. Elke preview is een screenshot met een link naar het bestand.

```html
<div class="previews">
  <a class="preview" href="voorbeeld/viewer-plan.html" target="_blank" rel="noopener">
    <img src="assets/previews/viewer.png" alt="De viewer tijdens de planstop, met vijf checkpoints" width="1200" height="800" loading="lazy">
    <span class="preview-tekst">
      <span class="eyebrow">viewer-plan.html</span>
      <b>De viewer bij de planstop</b>
      <span class="tekstlink">Open het bestand ↗</span>
    </span>
  </a>
</div>
```

`.previews` is `display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:28px`, dus ruimer dan `.twee`, omdat de schaduw ruimte nodig heeft.

`.preview` is een link als blok. Het plaatje krijgt de lijst van `.proto-frame`: `border:2px solid var(--zwart); border-radius:var(--radius); box-shadow:var(--schaduw); aspect-ratio:3/2; object-fit:cover; object-position:top; width:100%; display:block; background:var(--wit)`. Daaronder staat `.preview-tekst` met eyebrow (bestandsnaam), titel en een link.

Standen:

| Stand | Gedrag |
|---|---|
| normaal | harde gele schaduw 6px |
| hover | preview schuift 1px omhoog, zoals `.knop` (`transform:translateY(-1px)`); de `.tekstlink` krijgt een dikkere onderstreping |
| focus-visible | focusring om de hele link |
| smal (≤ 640px) | één kolom, schaduw 4px (`--schaduw-s`), net als `.volgende` en `.proto-frame` in de viewer |
| geen plaatje (fallback) | `.leeg`-blok uit de viewer met de bestandsnaam en de link, zodat de preview niet leeg is als een screenshot ontbreekt |

Een iframe met de echte viewer is overwogen, maar op een telefoon is een volledige viewer in een kader van 520px niet te lezen, en vijf iframes op één pagina laden traag. Het plaatje met een link naar het echte bestand werkt overal. De viewer en de rapporten zijn zelf al responsief, dus wie doorklikt, krijgt op een telefoon gewoon de mobiele versie.

### Installeren

De installatie is vier korte stappen met codeblokken: downloaden, uitpakken, `bf.py doctor` draaien en `/buildflow` starten. Elk codeblok heeft een kopieerknop.

```html
<ol class="stappen">
  <li><h3>Pak de zip uit in je skills-map</h3>
    <div class="code">
      <pre><code>mkdir -p ~/.claude/skills
unzip -o buildflow.zip -d ~/.claude/skills</code></pre>
      <button class="kopieer" type="button" aria-label="Kopieer de commando's">Kopieer</button>
    </div>
  </li>
</ol>
```

Overal op de site staat hetzelfde uitpakcommando: `unzip -o buildflow.zip -d ~/.claude/skills`, of met `.claude/skills` voor een installatie in één project. Bijwerken is de oude map weghalen en hetzelfde commando draaien; zo staat het ook bij de vragen. De hook gaat alleen af als `scripts/gate_hook.py` op `~/.claude/skills/buildflow/` of `<project>/.claude/skills/buildflow/` staat, en de site zegt dat bij de uitpakstap.

Eisen aan de zip, voor het releasescript: de zip heet `buildflow.zip` en heeft bovenaan precies één map, `buildflow/`. Daarin staan de bestanden van de skill (`SKILL.md`, `README.md`, `references/`, `scripts/`, `assets/`, `pricing.json`) en een `LICENSE` met de MIT-licentie. Geen `__pycache__`, `.DS_Store` of andere bestanden. Het script uploadt hem als asset van een GitHub Release, zodat `releases/latest/download/buildflow.zip` altijd naar de nieuwste versie wijst.

Over `bf.py doctor` zegt de site alleen wat het print: de map van de skill, de projectmap, de Python-versie, de modellen in `pricing.json` en "no active run" zolang er geen run is. Bij de startstap staat: "Zie je `/buildflow` niet, start dan een nieuwe sessie." 

Nieuwe klassen:

`.stappen` is een genummerde lijst met de `.nr`-badge als nummer. `list-style:none; counter-reset:stap; display:grid; gap:24px`. Elke `li` is een raster `auto minmax(0,1fr)` en `li::before` is de `.nr`: `content:counter(stap)`, 36px, geel, rond, Archivo 800. De stijl van `.nr` wordt hier dus via `::before` herhaald, omdat een telbaar nummer in CSS netter is dan een los span per stap.

`.code` is het codeblok, zwart zoals `.sectie.zwart`: `position:relative; background:var(--zwart); color:var(--zwart-tekst); border-radius:var(--radius-s); padding:16px 18px; padding-right:110px`. In `.volgende` en onder 640px staat de knop boven het commando (`padding-top:50px`, onder 640px `64px` omdat de knop daar 44px hoog is; `padding-right:18px`), anders blijft er te weinig breedte over voor het commando zelf. Inline `code` in lopende tekst krijgt `--vlak` als achtergrond, `--wit` in `.cp-body`, `--zwart-kaart` op zwart en binnen `.code pre` geen achtergrond. `pre` krijgt `overflow-x:auto; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9rem; line-height:1.6`. Commando's breken nooit af, want een afgebroken commando plak je verkeerd. Daarom scrollt het codeblok zelf horizontaal. De scrollbalk is dun en valt weg in het blok: `scrollbar-width:thin; scrollbar-color:var(--zwart-lijn) transparent`, bij hover `var(--accent)`, en voor WebKit `::-webkit-scrollbar{height:6px}` met een ronde thumb in dezelfde kleuren en een transparante track. Een native grijze balk hoort niet in de huisstijl. Dat is de enige plek op de pagina waar dat mag, en het is binnen het blok, niet de pagina. Een `$`-prompt komt er niet in, zodat kopiëren direct werkt.

`.kopieer` is de kopieerknop rechtsboven in `.code` (`position:absolute; top:10px; right:10px`). Hij gebruikt de stijl van `.knop.klein`, met de achtergrond op `--accent`.

| Stand | Gedrag |
|---|---|
| normaal | gele pilknop "Kopieer" |
| hover | 1px omhoog, zoals `.knop` |
| focus-visible | gele focusring, omdat het blok zwart is |
| gekopieerd | 2 seconden lang klasse `.gekopieerd`: achtergrond `--wit`, tekst `--zwart`, label "Gekopieerd ✓"; tegelijk de `.toast` met "Gekopieerd naar je klembord" |
| mislukt | geen klembord-API of geen toestemming: `site.js` selecteert de tekst in `pre` en toont de toast "Kopiëren lukte niet. De tekst is geselecteerd, druk op Cmd+C" |
| zonder JavaScript | de knop staat er niet; `site.js` voegt hem toe, zodat er geen dode knop blijft staan |
| smal (≤ 640px) | knop rechtsboven, boven het commando (`padding-top:64px; padding-right:18px`), knop `padding:6px 12px` en `min-height:44px`; de toast bij succes is dan alleen voor schermlezers (visueel verborgen), omdat de knop zelf al "Gekopieerd ✓" zegt en een toast op een telefoon over de tekst valt; de foutmelding blijft zichtbaar (`.toast.fout`) |

De `.toast` krijgt op de site `role="status"` en `aria-live="polite"`, zodat een schermlezer de bevestiging ook hoort.

Naast de stappen staat, in een hergebruikte `.hero-grid`, een klein `.kaart`-blok met wat je nodig hebt: Claude Code, `python3` 3.9 of nieuwer (alleen de standaardbibliotheek), git, en voor de UI-gate een browsertool (Playwright MCP of Claude in Chrome). Een tweede installatievariant (in het project zelf onder `.claude/skills/buildflow/`) komt in een `details.ctx` eronder, dicht, zodat de standaardroute kort blijft. Die variant downloadt de zip met dezelfde `curl` als stap 1, maar dan in de projectmap, pakt hem uit met `unzip -o buildflow.zip -d .claude/skills`, ruimt hem op met `rm buildflow.zip` en draait daarna `.claude/skills/buildflow/scripts/bf.py doctor` vanuit de projectmap. Zo hangt de variant niet af van waar je browser downloads neerzet.

### Download

De zwarte sectie.

```html
<section class="sectie zwart" id="download"><div class="wrap">
  <div class="kop"><div><span class="eyebrow">Release</span><h2>Download</h2></div><p class="grijs">…</p></div>
  <div class="download">
    <div class="kpis"><div class="kpi"><span class="w">v1.0.0</span><span class="l">versie</span></div>…</div>
    <p class="knoppen">
      <a class="knop" href="https://github.com/…/releases/latest/download/buildflow.zip">Download buildflow.zip</a>
      <a class="knop rand-licht" href="https://github.com/…/releases">Alle versies</a>
    </p>
    <p class="grijs klein voetnoot">MIT-licentie. De zip bevat alleen de skill en de LICENSE, geen cachebestanden of andere mappen.</p>
  </div>
</div></section>
```

`.download` is een kaart op zwart: `border:2px solid var(--accent); border-radius:var(--radius); padding:clamp(18px,3vw,28px)`. Het is de `.volgende`-kaart in negatief. Op zwart valt een gele schaduw weg, dus hier doet een gele rand hetzelfde werk. De `.kpis` erin tonen versie, datum en grootte, met de labels "versie", "uitgebracht" en "grootte van de zip" en de donkere KPI-stijl van de viewer. Omdat `.kpi .w` niet afbreekt, gebruikt `.download .kpis` een eigen raster `repeat(auto-fill,minmax(220px,1fr))` in plaats van de 7 kolommen, en `.download .kpi .w` een iets kleinere maat (`clamp(1.2rem,1rem + .6vw,1.5rem)`); anders liep een datum tussen 1100 en 1500px tegen de rand van de tegel. De waarden staan in de HTML met `data-release="versie|datum|grootte"`, zodat het releasescript weet wat het moet invullen.

`.knop.rand-licht` is nieuw en nodig omdat `.knop.rand` een zwarte lijn heeft die op zwart wegvalt: `background:transparent; color:#fff; box-shadow:inset 0 0 0 2px var(--zwart-grijs)`. Bij hover wordt de lijn `--accent`.

Versie, datum en grootte komen uit het releasescript. In de HTML staan ze als gewone tekst, zonder API-call naar GitHub.

De haken voor het releasescript zijn elementen met een `data-release`-attribuut. `data-release="versie"` staat op drie plekken: de `b` in de topbalk, de versietegel in `.download` en een `span` in de footer. Die drie moeten dezelfde tekst tonen; de tests controleren dat. `data-release="datum"` en `data-release="grootte"` staan alleen in de downloadkaart. Zolang er geen releasescript is, staat er "volgt" in plaats van een verzonnen datum of grootte; de tests controleren dat daar dan geen cijfer in staat. In het prototype staan voorbeeldwaarden met een `.proto-noot` erbij. De downloadlink is `releases/latest/download/buildflow.zip` en hoeft dus niet mee te veranderen.

### Vragen en beperkingen

Een `.kop` en daaronder een lijst `details.ctx`-blokken. Die markup en stijl bestaan al in de viewer, de site voegt alleen de klasse `.vraag` toe voor de tekst in het open deel.

```html
<details class="ctx vraag">
  <summary>Werkt het ook buiten Claude Code?</summary>
  <div class="antwoord"><p>…</p></div>
</details>
```

`.vraag summary` krijgt `flex-wrap:nowrap`, zodat het plusteken bij een vraag van twee regels rechts naast de tekst blijft. `.vraag .antwoord` neemt de rol over van `.prose` in `details.ctx`: `padding:0 18px 16px; max-width:70ch`, zonder de extra rand van `.prose`. Een `p` erin krijgt `margin-bottom:10px`.

Standen: dicht met `+`, open met `–` (al in de viewer). Focus-visible: ring om de summary. Print: alle vragen open, via dezelfde `beforeprint`-aanpak als de fases.

De beperkingen horen hier ook, en de meeste worden gewoon een vraag: alleen Claude Code, `python3` nodig, kosten zijn het API-equivalent tegen lijstprijs en dus niet wat je met een abonnement betaalt, en losse vragen stel je beter in een andere sessie, omdat alles in de run-sessie meetelt. Wie de pagina scant, vindt ze zo sneller dan in een aparte lijst. De kostenuitleg staat alleen hier (`#vraag-kosten`); de kaart in Waarde linkt ernaartoe. Hervatten na een onderbreking staat één keer bij de fase Bouwen (`#hervatten`). Alleen na een rate limit in een sessie die nog openstaat, is "ga verder" genoeg. Na een crash of in een nieuw proces typ je altijd opnieuw `/buildflow`: dat vindt de lopende run via `bf status`, vraagt of je wilt hervatten en zet de hooks en `allowed-tools` van de skill weer aan. `claude --continue` of `--resume` haalt het oude gesprek terug, maar ook dan typ je daarna `/buildflow`. De vraag over onderbrekingen linkt daarheen.

### Footer

De `.footer` uit de viewer, met links erin.

```html
<footer class="footer"><div class="wrap">
  <span>buildflow · checkpoints en gates voor Claude Code, naar Shopify's Helix</span>
  <span><a href="…">GitHub</a> · <a href="…/LICENSE">MIT-licentie</a> · <span data-release="versie">v1.0.0</span></span>
</div></footer>
```

Links in de footer krijgen `color:#fff`, met `text-decoration-color:var(--accent)`. Onder 640px zijn footer- en navlinks minstens 44px hoog (`min-height:44px; display:inline-flex; align-items:center`), net als `.kopieer`, en krijgt het woordmerk `padding-block:13px`, zodat alles met een duim te raken is. Bij focus is de ring geel (zie de toegankelijkheidsregel bovenaan). De footer van de viewer is Engels ("after Shopify's Helix"), die van de site Nederlands.

### Tekstlinks

`.tekstlink` is een losse link in lopende tekst. Het is de linkstijl van `.prose a` uit de viewer, los te gebruiken: `text-decoration-color:var(--accent); text-decoration-thickness:2px; text-underline-offset:2px`. Bij hover wordt de lijn 3px. Op zwart blijft de lijn geel en de tekst wit.

### JavaScript

`site.js` blijft klein en doet vier dingen. De pagina werkt zonder JavaScript ook, alleen zonder deze vier.

1. Kopieerknoppen toevoegen aan elk `.code`-blok en afhandelen (klembord, fallback met selectie, `.gekopieerd`, `.toast`).
2. De actieve navlink bijhouden met een `IntersectionObserver` (`.actief` en `aria-current`).
3. Bij een ankerlink naar een fase in de handleiding (`#fase-brief`) die fase openzetten.
4. Bij `beforeprint` alle dichte `details` openzetten en bij `afterprint` weer sluiten.

Geen `localStorage`, geen analytics, geen externe scripts.

### Breakpoints op de site

Dezelfde drie als de viewer plus print. Wat er op de site bij komt:

| Breedte | Nieuw gedrag |
|---|---|
| ≤ 820px | hero één kolom (viewer); `.fase`-summary klapt om; `.poort` blijft twee kolommen, want het nummer is smal |
| ≤ 640px | `.kopknop` weg; `.knoppen` volle breedte; `.previews` één kolom met 4px-schaduw; `.code` met de knop boven het commando; nav- en footerlinks 44px hoog; succestoast alleen voor schermlezers; `.download` 18px padding; `.stappen li` `gap:12px` |
| print | `.overslaan`, `.kopknop`, `.kopieer`, `.toast` en `.nav` weg; alle `details` open (zie JavaScript); `.sectie.zwart` wit met zwarte tekst om inkt te sparen |

Controleer de pagina op 320, 375, 768, 1100, 1200 en 1600px. Er mag nergens een horizontale scrollbalk op de pagina verschijnen, alleen binnen een `.code`-blok.

### Toon van de teksten op de pagina

Volg de learnings van deze feature: lopende zinnen, informeel-zakelijk Nederlands, zoals je het een collega uitlegt die Claude Code al kent. Geen marketingtaal, en volg de schrijfstijlregels in de learnings. Een paar voorbeelden van hoe de interface klinkt:

| Waar | Tekst |
|---|---|
| kopieerknop | Kopieer / Gekopieerd ✓ |
| toast | Gekopieerd naar je klembord |
| kopiëren mislukt | Kopiëren lukte niet. De tekst is geselecteerd, druk op Cmd+C. |
| previewlink | Open het bestand ↗ |
| skiplink | Naar de inhoud |
| stop-label | stop |
| handleiding, kopjes | Wat je krijgt / Wat je doet |

Koppen in zin-hoofdletters. Engelse termen die in de skill vastliggen (brief, checkpoint, gate, viewer) blijven Engels. Die vertalen maakt het alleen lastiger om de pagina naast de viewer te lezen.

## Overzicht van nieuwe componenten

| Klasse | Waarvoor | Hergebruikt |
|---|---|---|
| `.overslaan` | skiplink naar `#inhoud` | `.knop.zwart` |
| `.kopknop` | downloadknop in de header | `.knop.klein` |
| `.pillen`, `.knoppen` | rijen pillen en knoppen | `.pil`, `.knop` |
| `.kaart` | algemene witte kaart | maten van `.kpi` |
| `.stap.stop` | stap waar Claude op jou wacht | `.stepper`, `.stap`, `.pil.geel` |
| `.poort` | uitleg van één gate | `.kaart`, `.nr`, `.chip` |
| `.fase` | uitklapkaart per fase in de handleiding | `.cp`, `.nr`, `.cp-body`, `.twee`, `.blok` |
| `.krijg`, `.doe` | wat je krijgt / wat je doet | `.blok`, `ul.check` |
| `.previews`, `.preview` | screenshot met link naar het bestand | lijst van `.proto-frame`, `.eyebrow`, `.leeg` |
| `.proza`, `.sub-kop` | lopende tekst en tussenkop binnen een sectie | tekststijlen |
| `.stappen` | genummerde installatiestappen | stijl van `.nr` |
| `.code`, `.kopieer` | codeblok met kopieerknop | `.sectie.zwart`-kleuren, `.knop.klein`, `.toast` |
| `.download` | releasekaart op zwart | `.kpis`, `.kpi`, `.knop` |
| `.knop.rand-licht` | omlijnde knop op zwart | `.knop.rand` |
| `.vraag` | vraag en antwoord | `details.ctx` |
| `.tekstlink` | link in lopende tekst | `.prose a` |

## Deel 3: wat in de viewer niet helemaal klopt

Dit is wat bij het uitlezen van `viewer.html` opviel. De site lost het voor zichzelf op waar dat kan. De viewer zelf passen we in deze feature niet aan, dus dit is ook een lijstje voor later.

De focusring is altijd zwart (`outline:3px solid var(--zwart)`), ook in `.sectie.zwart`, `.topbalk` en `.footer`. Daar zie je hem niet. De viewer heeft in de zwarte kostensectie weinig om op te focussen, dus het valt er nauwelijks op. Op de site staan in de zwarte downloadsectie wel knoppen, dus daar is de ring geel gemaakt.

`--grijs-licht` (#9C998D) haalt op wit 2,9:1 en op `--vlak` 2,6:1. De viewer gebruikt die kleur voor tekst in de stepper (`.stap`) en voor `.chip.skipped`. Dat is onder de AA-norm van 4,5:1. `.chip.feedback` (`--accent-diep` op `--accent-zacht`) komt uit op 4,47:1, net te weinig voor tekst van .78rem.

Zes kleuren voor de donkere secties staan los in de CSS in plaats van als token: `#EDEBE4`, `#DAD7CD`, `#B9B6AB`, `#1F1E1B`, `#34322C` en `#2A2925`. Wit staat er soms als `var(--wit)` en soms als `#fff` of `rgba(255,255,255,.96)`. De site geeft ze een naam, met dezelfde waarden.

De radii lopen maar voor een deel via tokens. `--radius` en `--radius-s` bestaan, maar `999px`, `6px`, `4px` en `3px` staan los in de CSS. De harde schaduw komt in twee maten voor (6px en 4px) zonder token.

Het fontstack van Archivo is niet overal hetzelfde. Koppen krijgen `'Archivo','Arial Narrow',system-ui,sans-serif`, de meeste labels `'Archivo',sans-serif`, en `.sev` en het `+`-teken van `details.ctx` alleen `'Archivo'`, zonder terugvaloptie.

`.nav a.actief` heeft een stijl, maar geen enkele regel JavaScript zet die klasse. De viewer kent dus geen actieve navlink. Voor "aan" gebruikt de viewer ook twee woorden: `.actief` bij de nav en `.aan` bij `.statenrij .chip` en `.toast`.

De naamgeving is half Nederlands, half Engels. Componenten zijn Nederlands (`.knop`, `.pil`, `.sectie`, `.poging`), maar de standen komen rechtstreeks uit de data en zijn Engels (`.passed`, `.running`, `.in_progress`, `.done`, `.current`, `.skipped`). Ook `.hero`, `.header`, `.nav`, `.footer`, `.stepper` en `.prose` zijn Engels. De site volgt dezelfde lijn: nieuwe componenten krijgen een Nederlandse naam, bestaande klassen blijven zoals ze zijn.

`.klein` is twee dingen tegelijk: een tekstutility (`font-size:.9rem`) en een modifier van `.knop` (`.knop.klein`, `.86rem` en minder padding). Op een knop wint de modifier, dus het werkt, maar wie `.klein` los op een link zet, krijgt iets anders dan op een knop. Hetzelfde geldt voor `.zwart` als modifier van `.pil`, `.knop` en `.sectie`.

Er staan drie aparte `@media (max-width:820px)`-blokken achter elkaar. Dat werkt, maar het is lastig bijhouden. `site.css` gebruikt per breakpoint één blok.

`<html lang="en">` staat vast in het template. JavaScript zet de taal daarna op de goede waarde, maar zonder JavaScript of voor een crawler is een Nederlandse viewer als Engels gemarkeerd. De footer blijft altijd Engels ("after Shopify's Helix"), ook als de rest Nederlands is.

De `.toast` heeft geen `role="status"` of `aria-live`, dus een schermlezer hoort "Gekopieerd" niet. Het woordmerk heeft geen toegankelijke naam behalve de losse woorden "build" en "flow".

Er is geen donkere modus en ook geen `color-scheme`-declaratie. Dat is bewust of niet, dat staat nergens. De site kiest er bewust voor om licht te blijven en zegt dat met `<meta name="color-scheme" content="light">`.

`.kpi .w` heeft `white-space:nowrap`. Bij twee kolommen op 320px kan een lang bedrag of een lange duur net buiten de tegel lopen. In de site blijven de waarden kort (versie, datum, grootte), maar bij langere waarden is dit een aandachtspunt.

## Wijzigingen

- 2026-09-29 · Na de eerste design-review verwerkt: zip-indeling als eis voor het releasescript, `unzip -o` overal, downloadlink zonder versie, hervatten na een onderbreking, voorbeeldrun als momentopnames van de viewer, drie of vier stops, kopieerknop boven het commando in `.volgende` en op smal scherm, `.vraag summary` zonder afbreken, `.fase`-raster van vier kolommen, gates als `h4`, `.proza`/`.sub-kop`, eigen KPI-raster in `.download`, 44px-links op mobiel, succestoast op mobiel alleen voor schermlezers, favicon, printen met `beforeprint`.
- 2026-09-29 · Na de bouw van de pagina (cp01) bijgewerkt naar wat er staat: de site in de root van de repo, de lead met de gates zoals ze echt lopen, de teaminstallatie met `curl` in de projectmap en `rm buildflow.zip`, de labels "uitgebracht" en "grootte van de zip" in de downloadkaart, en de `data-release`-haken in topbalk, downloadkaart en footer.
