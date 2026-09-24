/* MADE — seeded generative plates.
   Verbatim port of rng()/plate()/plateDraw() from the original dc export
   ("MADE Site.dc.html"). Deterministic SVG data-URLs from a seed string. */
(function () {
  "use strict";

  function rng(seed) {
    let s = 2166136261;
    for (const c of String(seed)) s = ((s ^ c.charCodeAt(0)) * 16777619) >>> 0;
    return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }

  const _plates = {};

  function plate(seed, w, h) {
    const key = seed + "|" + w + "x" + h;
    if (_plates[key]) return _plates[key];
    return (_plates[key] = plateDraw(seed, w, h));
  }

  function plateDraw(seed, w, h) {
    const r = rng(seed);
    const ink = "#201f1d", gold = "#b68235";
    const f = n => n.toFixed(1);
    let g = "";
    const n = 16 + Math.floor(r() * 12);
    for (let i = 0; i < n; i++) {
      const x = (i + 0.5) * (w / n) + (r() - 0.5) * 5;
      g += '<line x1="' + f(x) + '" y1="0" x2="' + f(x) + '" y2="' + h + '" stroke="' + ink + '" stroke-width="0.5" opacity="' + (0.04 + r() * 0.09).toFixed(3) + '"/>';
    }
    const cx = w * (0.24 + r() * 0.5), cy = h * (0.28 + r() * 0.46);
    const rings = 6 + Math.floor(r() * 6);
    const span = Math.max(w, h) * (0.42 + r() * 0.34);
    for (let i = 1; i <= rings; i++) {
      g += '<circle cx="' + f(cx) + '" cy="' + f(cy) + '" r="' + f((i / rings) * span) + '" fill="none" stroke="' + ink + '" stroke-width="0.6" opacity="' + (0.16 - i * 0.008).toFixed(3) + '"/>';
    }
    const spokes = 3 + Math.floor(r() * 5);
    for (let i = 0; i < spokes; i++) {
      const a = r() * Math.PI * 2, L = span * (0.9 + r() * 0.7);
      g += '<line x1="' + f(cx) + '" y1="' + f(cy) + '" x2="' + f(cx + Math.cos(a) * L) + '" y2="' + f(cy + Math.sin(a) * L) + '" stroke="' + ink + '" stroke-width="0.6" opacity="0.17"/>';
    }
    const bands = 1 + Math.floor(r() * 3);
    for (let i = 0; i < bands; i++) {
      const y = h * (0.12 + r() * 0.76);
      g += '<line x1="0" y1="' + f(y) + '" x2="' + w + '" y2="' + f(y) + '" stroke="' + ink + '" stroke-width="0.6" opacity="0.2"/>';
    }
    const ga = r() * Math.PI * 2;
    g += '<path d="M ' + f(cx + Math.cos(ga) * span * 0.7) + ' ' + f(cy + Math.sin(ga) * span * 0.7) +
      ' A ' + f(span * 0.7) + ' ' + f(span * 0.7) + ' 0 0 1 ' +
      f(cx + Math.cos(ga + 1.5) * span * 0.7) + ' ' + f(cy + Math.sin(ga + 1.5) * span * 0.7) +
      '" fill="none" stroke="' + gold + '" stroke-width="1.4" opacity="0.85"/>';
    const marks = 2 + Math.floor(r() * 3);
    for (let i = 0; i < marks; i++) {
      const mx = w * (0.1 + r() * 0.8), my = h * (0.1 + r() * 0.8), s = 4 + r() * 7;
      if (r() < 0.5) g += '<rect x="' + f(mx) + '" y="' + f(my) + '" width="' + f(s) + '" height="' + f(s) + '" fill="none" stroke="' + gold + '" stroke-width="1" opacity="0.8"/>';
      else g += '<circle cx="' + f(mx) + '" cy="' + f(my) + '" r="' + f(s * 0.32) + '" fill="' + gold + '" opacity="0.75"/>';
    }
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '">' +
      '<rect width="' + w + '" height="' + h + '" fill="#f3f2f2"/>' + g + '</svg>';
    // No ";utf8" parameter — a semicolon here would be read as a declaration
    // separator when this URL is inlined in a style attribute.
    return "data:image/svg+xml," + encodeURIComponent(svg);
  }

  function apply(root) {
    const els = (root || document).querySelectorAll("[data-plate-seed]");
    for (const el of els) {
      const seed = el.getAttribute("data-plate-seed");
      const w = parseInt(el.getAttribute("data-plate-w"), 10);
      const h = parseInt(el.getAttribute("data-plate-h"), 10);
      if (!seed || !w || !h) continue;
      el.style.backgroundColor = "#f3f2f2";
      el.style.backgroundImage = 'url("' + plate(seed, w, h) + '")';
      el.style.backgroundSize = "cover";
      el.style.backgroundPosition = "center";
    }
  }

  window.MADE_PLATES = { plate: plate, rng: rng, plateDraw: plateDraw, apply: apply };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { apply(document); });
  } else {
    apply(document);
  }
})();
