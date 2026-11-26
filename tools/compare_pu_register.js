// Compare the PU SIHKA positions in the build with the PU rain-post register (F77).
// Run in a browser tab on https://pdsda.sda.pu.go.id/landing-page/peta-informatif (the register refuses scripted
// requests, HTTP 403, F73). First set window._pu to the `i|name|lat|lon;...` string printed by
// tools/export_pu_positions.py (coordinates cut to 4 decimals), then run this file. Read only.
// Matching is by name only (the register carries no SIHKA integration_id): names are upper-cased, office codes
// such as "-R.067" / "-PH.143" and the words POS, CURAH, HUJAN, PCH, ARR, MRG, DAS, CH, AWS ... are removed, and
// a bracketed name counts as an alternative name. Among same-name register posts the nearest is taken.
const reg = (await (await fetch("https://pdsda.sda.pu.go.id/landing-page/peta-informatif/titik?jenis=pch&page=1")).json()).data;
const pu = window._pu.split(";").filter(Boolean).map(r => { const [i, name, lat, lon] = r.split("|"); return { i: +i, name, lat: +lat, lon: +lon }; });
const WORDS = /\b(POS|CURAH|HUJAN|PCH|PCHT|ARR|ARL|MRG|DAS|STA|STASIUN|CH|MANUAL|KLIMATOLOGI|KLIMAT|TELEMETRI|AWS|AAWS)\b/g;
const strip = s => s.replace(/[-.\s]*\b(R|PH|RK)\.?\s*\d+[A-Z]?\s*$/, "").replace(WORDS, " ").replace(/[^A-Z0-9]/g, "");
const keys = s => {
  const u = String(s || "").toUpperCase().trim(), k = new Set([strip(u.replace(/[()]/g, " ")), strip(u.replace(/\(.*?\)/g, " "))]);
  const m = u.match(/\((.*?)\)/); if (m) k.add(strip(m[1]));
  return [...k].filter(x => x.length >= 3);
};
const km = (a, b, c, d) => { const p = Math.PI / 180, h = Math.sin((c - a) * p / 2) ** 2 + Math.cos(a * p) * Math.cos(c * p) * Math.sin((d - b) * p / 2) ** 2; return 12742 * Math.asin(Math.sqrt(h)); };
const idx = new Map();
reg.forEach((r, j) => keys(r.nama).forEach(k => { if (!idx.has(k)) idx.set(k, []); idx.get(k).push(j); }));
const res = pu.map(p => {
  const cand = [...new Set(keys(p.name).flatMap(k => idx.get(k) || []))];
  let best = null; for (const j of cand) { const d = km(p.lat, p.lon, reg[j].lat, reg[j].lng); if (!best || d < best.d) best = { j, d }; }
  let near = null; reg.forEach((r, j) => { const d = km(p.lat, p.lon, r.lat, r.lng); if (!near || d < near.d) near = { j, d }; });
  return { ...p, n_cand: cand.length, j: best?.j, d: best?.d, nj: near.j, nd: near.d };
});
const bins = { "same name, <= 0.1 km": 0, "0.1-1 km": 0, "1-5 km": 0, "5-25 km": 0, "> 25 km": 0, "no name match, register post <= 1 km": 0, "no name match, none <= 1 km": 0 };
for (const r of res) {
  if (r.j === undefined) bins[r.nd <= 1 ? "no name match, register post <= 1 km" : "no name match, none <= 1 km"]++;
  else bins[r.d <= 0.1 ? "same name, <= 0.1 km" : r.d <= 1 ? "0.1-1 km" : r.d <= 5 ? "1-5 km" : r.d <= 25 ? "5-25 km" : "> 25 km"]++;
}
const used = new Set(res.filter(r => r.j !== undefined).map(r => r.j));
const f = (x, n = 4) => x.toFixed(n), R = j => `${reg[j].id} ${reg[j].nama} (${f(reg[j].lat)}, ${f(reg[j].lng)}) ${reg[j].balai.replace("BALAI WILAYAH SUNGAI", "BWS").replace("BALAI BESAR WILAYAH SUNGAI", "BBWS")}`;
window._cmp = res;
({ register: reg.length, pu_posts: pu.length, bins, register_posts_matched: used.size,
   far: res.filter(r => r.j !== undefined && r.d > 1).sort((a, b) => b.d - a.d)
           .map(r => `${r.i} ${r.name} (${f(r.lat)}, ${f(r.lon)}) -> ${R(r.j)}: ${f(r.d, 1)} km; nearest any ${f(r.nd, 1)} km ${reg[r.nj].nama}`),
   unmatched: res.filter(r => r.j === undefined).map(r => `${r.i} ${r.name}: nearest ${reg[r.nj].nama} ${f(r.nd, 2)} km`) })
