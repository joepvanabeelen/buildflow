/* buildflow website: kopieerknoppen, actieve navlink, fases openen, previews zonder
   plaatje en printen.
   Zonder dit script werkt de pagina ook; het voegt alleen gemak toe. */
(function(){
  "use strict";

  var toastEl = document.getElementById("toast"), toastTimer;
  function toast(tekst, fout){
    if(!toastEl) return;
    toastEl.textContent = tekst;
    toastEl.classList.toggle("fout", !!fout);
    toastEl.classList.add("aan");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ toastEl.classList.remove("aan"); }, fout ? 5000 : 2200);
  }

  // 1. Kopieerknoppen in elk codeblok
  function kopieerNaarKlembord(tekst){
    if(navigator.clipboard && window.isSecureContext){
      return navigator.clipboard.writeText(tekst);
    }
    return Promise.reject(new Error("geen klembord"));
  }

  document.querySelectorAll(".code").forEach(function(blok){
    var pre = blok.querySelector("pre");
    if(!pre) return;
    var knop = document.createElement("button");
    knop.type = "button";
    knop.className = "kopieer";
    knop.textContent = "Kopieer";
    knop.setAttribute("aria-label", "Kopieer de commando's");
    blok.appendChild(knop);
    var terugTimer;

    knop.addEventListener("click", function(){
      var tekst = pre.textContent.replace(/\n$/, "");
      kopieerNaarKlembord(tekst).then(function(){
        knop.classList.add("gekopieerd");
        knop.textContent = "Gekopieerd ✓";
        toast("Gekopieerd naar je klembord");
        clearTimeout(terugTimer);
        terugTimer = setTimeout(function(){
          knop.classList.remove("gekopieerd");
          knop.textContent = "Kopieer";
        }, 2000);
      }, function(){
        clearTimeout(terugTimer);
        knop.classList.remove("gekopieerd");
        knop.textContent = "Kopieer";
        var bereik = document.createRange();
        bereik.selectNodeContents(pre);
        var selectie = window.getSelection();
        selectie.removeAllRanges();
        selectie.addRange(bereik);
        toast("Kopiëren lukte niet. De tekst is geselecteerd, druk op Cmd+C.", true);
      });
    });
  });

  // 2. Actieve navlink voor de sectie die in beeld is
  var links = {};
  document.querySelectorAll(".nav a[href^='#']").forEach(function(a){
    links[a.getAttribute("href").slice(1)] = a;
  });
  if("IntersectionObserver" in window){
    var io = new IntersectionObserver(function(items){
      items.forEach(function(it){
        if(!it.isIntersecting) return;
        Object.keys(links).forEach(function(id){
          var aan = id === it.target.id;
          links[id].classList.toggle("actief", aan);
          if(aan) links[id].setAttribute("aria-current", "true");
          else links[id].removeAttribute("aria-current");
        });
      });
    }, {rootMargin: "-40% 0px -55% 0px"});
    document.querySelectorAll("main section[id]").forEach(function(s){ io.observe(s); });
  }

  // 3. Een link naar iets in een uitklapblok (#fase-..., #hervatten, #vraag-...) zet dat blok
  //    en alle blokken eromheen open, en scrollt er dan naartoe
  function doelVanHash(){
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); }
    catch(e){ return null; } // kapotte hash zoals #fase-%zz: niets doen
    return id ? document.getElementById(id) : null;
  }
  function openDoel(scrollen){
    var doel = doelVanHash();
    if(!doel) return;
    for(var el = doel; el && el !== document.body; el = el.parentElement){
      if(el.tagName === "DETAILS") el.open = true;
    }
    if(scrollen) doel.scrollIntoView();
  }
  window.addEventListener("hashchange", function(){ openDoel(true); });
  // Staat de hash al op dat doel, dan komt er geen hashchange; open het dan bij de klik
  document.addEventListener("click", function(e){
    var a = e.target.closest && e.target.closest("a[href^='#']");
    if(a && location.hash === a.getAttribute("href")) openDoel(true);
  });
  // Bij herladen of terug/vooruit zet de browser de scrollpositie zelf terug; niet overschrijven
  var nav = window.performance && performance.getEntriesByType
    ? performance.getEntriesByType("navigation")[0] : null;
  var hersteld = history.scrollRestoration !== "manual" && nav
    && (nav.type === "reload" || nav.type === "back_forward");
  openDoel(!hersteld);

  // 4. Een preview waarvan het plaatje niet laadt, krijgt het .leeg-blok: de bestandsnaam en
  //    "Nog geen afbeelding". De link eromheen blijft werken.
  function toonLeeg(img){
    var preview = img.closest(".preview");
    if(!preview || !img.parentNode) return;
    var naam = (preview.getAttribute("href") || "").split("/").pop();
    var leeg = document.createElement("span");
    leeg.className = "leeg";
    var code = document.createElement("code");
    code.textContent = naam;
    var uitleg = document.createElement("span");
    uitleg.className = "klein";
    uitleg.textContent = "Nog geen afbeelding";
    leeg.appendChild(code);
    leeg.appendChild(uitleg);
    img.parentNode.replaceChild(leeg, img);
  }
  document.querySelectorAll(".preview img").forEach(function(img){
    img.addEventListener("error", function(){ toonLeeg(img); });
    // Al mislukt voordat dit script draaide: meteen vervangen
    if(img.complete && img.getAttribute("src") && img.naturalWidth === 0) toonLeeg(img);
  });

  // 5. Printen: alle uitklapblokken open, daarna weer zoals ze waren
  var dicht = null;
  window.addEventListener("beforeprint", function(){
    if(dicht) return; // tweede beforeprint zonder afterprint: de eerste lijst bewaren
    dicht = [].filter.call(document.querySelectorAll("main details:not([open])"), function(d){
      d.open = true;
      return true;
    });
  });
  window.addEventListener("afterprint", function(){
    (dicht || []).forEach(function(d){ d.open = false; });
    dicht = null;
  });
})();
