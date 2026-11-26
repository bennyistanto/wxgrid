"""Station catalogue for the agro-climate collection (Data Stasiun). Coordinates per station
from, in order of preference:
  1. BMKG rain-post catalogue (POS-HUJAN, from STA-BMG.XLS) where the name, and where
     available the station code, match - checked against the gazetteer village;
  2. the sheets' own modal coordinate, if within 10 km of the gazetteer village;
  3. the gazetteer village (OpenStreetMap Nominatim), flagged approximate.
Every row records which source was used and how far the alternatives lie.

Gazetteer answers are cached in F:/temp/station/additional-sources/_gazetteer_cache.json
(queried once, 1 request per ~1.1 s, per the Nominatim usage policy).

Run: python tools/agro_catalogue.py  -> _agro_station_catalogue.csv
"""
import ast
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers.agro_sheets import coord_from_vote  # noqa: E402

B = Path("F:/temp/station/additional-sources")
CACHE = B / "_gazetteer_cache.json"

# station -> (gazetteer query, BMKG catalogue id candidate or None, evidence for that id)
STATIONS = {
    "Bandarbuat": ("Bandar Buat, Padang, Sumatera Barat", None, ""),
    "Bontobili": (["Bontobili, Gowa, Sulawesi Selatan", "Bonto Bili, Gowa", "Bontobili"], None, ""),
    "Cikeumeuh": ("Cikeumeuh, Bogor, Jawa Barat", None, ""),
    "Cimanggu": ("Cimanggu, Bogor, Jawa Barat", None, ""),
    "Cipanas": ("Cipanas, Cianjur, Jawa Barat", None, ""),
    "Genteng": ("Genteng, Banyuwangi, Jawa Timur", "16160", "name"),
    "Gunungmedan": (["Gunung Medan, Dharmasraya, Sumatera Barat", "Gunung Medan, Sitiung", "Gunungmedan, Sumatera Barat"], None, ""),
    "Handilmanarap": ("Handil Manarap, Banjar, Kalimantan Selatan", None, ""),
    "Jakenan": ("Jakenan, Pati, Jawa Tengah", "10179", "name+code 179"),
    "Jambegede": ("Jambegede, Malang, Jawa Timur", None, ""),
    "Kayuagung": ("Kayu Agung, Ogan Komering Ilir, Sumatera Selatan", "24193B", "name"),
    "Kendalpayak": ("Kendalpayak, Malang, Jawa Timur", None, ""),
    "Kuningan": ("Kuningan, Jawa Barat", "04068A", "name (KP) + code 68"),
    "Lampineung": (["Lampineung, Banda Aceh, Aceh", "Lampineung, Aceh", "Lampineung"], None, ""),
    "Lanrang": (["Lanrang, Sidenreng Rappang, Sulawesi Selatan", "Lanrang, Sidrap", "Lanrang, Sulawesi Selatan", "Lanrang", "Lanrang, Kulo"], None, ""),
    "Margahayu": (["Margahayu, Lembang, Bandung Barat, Jawa Barat", "Margahayu, Lembang", "Lembang, Bandung Barat"], "03154B", "name + code 154"),
    "Maros": ("Maros, Sulawesi Selatan", "33415", "code 415 only (catalogue name Solojirang)"),
    "Mojosari": ("Mojosari, Mojokerto, Jawa Timur", "12175A", "name (KP) + code 175A"),
    "Muara": ("Muara, Bogor, Jawa Barat", "02049A", "name"),
    "Muneng": ("Muneng, Probolinggo, Jawa Timur", "15146", "name"),
    "Ngale": ("Ngale, Ngawi, Jawa Timur", "13014A", "name"),
    "Pacet": ("Pacet, Cianjur, Jawa Barat", "03070", "name"),
    "Pusakanegara": (["Pusakanagara, Subang, Jawa Barat", "Pusakanegara, Subang", "Pusakanagara"], "02148A", "name"),
    "Rambatan": ("Rambatan, Tanah Datar, Sumatera Barat", None, ""),
    "Sukarami": (["Sukarami, Solok, Sumatera Barat", "Sukarami, Gunung Talang, Solok", "Sukarami, Kabupaten Solok", "Sukarame, Solok", "Sukarami, Sumatera Barat"], None, ""),
    "Sumani": ("Sumani, Solok, Sumatera Barat", None, ""),
    "Tamanbogo": ("Taman Bogo, Lampung Timur, Lampung", None, ""),
    # stations from the long-format and other layouts (F55 ledger)
    "Kambara": (["Kambara, Muna, Sulawesi Tenggara", "Kambara, Sulawesi Tenggara"], None, ""),
    "Bengkel": (["Bereng Bengkel, Palangka Raya, Kalimantan Tengah", "Bereng Bengkel"], None, ""),
    "Pondokbalas": (["Pondokbalas, Karawang, Jawa Barat", "Pondok Balas, Karawang"], "02099B", "name + code 99B (sheet 32H99b)"),
    "Rawamerta": (["Rawamerta, Karawang, Jawa Barat"], "02096A", "name + code 96A (sheet 32H96a)"),
    "Watumilok": (["Watumilok, Sikka, Nusa Tenggara Timur", "Watumilok"], None, ""),
    "Wairbleler": (["Wair Bleler, Sikka, Nusa Tenggara Timur", "Wairbleler", "Waibleler, Sikka"], None, ""),
    "Magepanda": (["Magepanda, Sikka, Nusa Tenggara Timur", "Magepanda"], None, ""),
}
# coordinates written in the files' own metadata (not template-prone single-station files)
SHEET_COORD = {"Kambara": (-(4 + 49 / 60), 122 + 25 / 60), "Bengkel": (-(2 + 11 / 60 + 14 / 3600), 114 + 4 / 60 + 47 / 3600)}
# stations whose data matched an existing WMO station day by day (see F56): use its record
WMO_MATCH = {"Maumere": (97300, "MAU* Tmax equal on 69% of days with BMKG 97300 (r 0.71); GHCN 97300 r 0.87"),
             "Bandung (BMG-Jakarta file)": (96783, "BMG8194 Tmax equal on 93%, rain 89% with BMKG 96783")}


def km(a, b, c, d):
    if any(pd.isna(x) for x in (a, b, c, d)):
        return float("nan")
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def gazetteer(q, cache):
    if q in cache:
        return cache[q]
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q + ", Indonesia", "format": "json", "limit": 3})
    req = urllib.request.Request(url, headers={"User-Agent": "wxgrid-station-catalogue/0.1 (research; low volume)"})
    time.sleep(1.1)
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        res = {"error": str(e)}
    cache[q] = res
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return res


cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
P = pd.read_csv(B / "_poshujan_catalogue.csv", dtype={"id": str}).set_index("id")
S = pd.read_csv(B / "_agro_raw_sheets_coords.csv")
S["lat"] = pd.to_numeric(S["lat"], errors="coerce"); S["lon"] = pd.to_numeric(S["lon"], errors="coerce")

rows = []
for st, (qs, aid, ev) in STATIONS.items():
    gz = None
    for q in (qs if isinstance(qs, list) else [qs]):
        g = gazetteer(q, cache)
        if isinstance(g, list) and g:
            gz = g[0]
            break
    glat, glon = (float(gz["lat"]), float(gz["lon"])) if gz else (float("nan"), float("nan"))
    v = S[(S["station"] == st)].dropna(subset=["lat", "lon"])
    vc = v.groupby([v["lat"].round(3), v["lon"].round(3)]).size().sort_values(ascending=False)
    if st in SHEET_COORD:
        vc = pd.Series({tuple(round(x, 4) for x in SHEET_COORD[st]): 1})
    # nearest sheet vote to the gazetteer village (votes are often template copies)
    best_vote, best_d = (float("nan"), float("nan")), float("nan")
    for (a, b), n in vc.items():
        d = km(a, b, glat, glon)
        if pd.isna(best_d) or d < best_d:
            best_vote, best_d = (a, b), d
    alat = alon = aelev = float("nan"); aname = ""
    if aid and aid in P.index:
        alat, alon, aelev, aname = P.loc[aid, "lat"], P.loc[aid, "lon"], P.loc[aid, "elev"], P.loc[aid, "name"]
    d_agency = km(alat, alon, glat, glon)
    if aid and not pd.isna(d_agency) and d_agency <= 15:
        lat, lon, src, flag = alat, alon, f"BMKG catalogue {aid} {aname} ({ev})", ""
    elif aid and not pd.isna(alat) and pd.isna(d_agency):
        lat, lon = alat, alon
        src, flag = f"BMKG catalogue {aid} {aname} ({ev}); no gazetteer check", ("" if "code" in ev else "name match only")
    elif not pd.isna(best_d) and best_d <= 10:
        lat, lon, src, flag = best_vote[0], best_vote[1], "sheet coordinate (within 10 km of village)", ""
    elif not gz and len(vc):
        lat, lon = vc.index[0]
        src, flag = "sheet modal coordinate", "unverified: no gazetteer or catalogue match"
    elif gz:
        lat, lon, src, flag = glat, glon, "gazetteer village centroid", "approximate"
        if aid and not pd.isna(d_agency):
            flag = f"approximate; catalogue {aid} lies {d_agency:.0f} km away"
    else:
        lat, lon, src, flag = float("nan"), float("nan"), "unresolved", "no coordinate"
    rows.append(dict(station=st, lat=round(lat, 4) if not pd.isna(lat) else lat,
                     lon=round(lon, 4) if not pd.isna(lon) else lon, elev_m=aelev, coord_source=src, flag=flag,
                     gazetteer=(gz["display_name"][:90] if gz else ""), gaz_lat=glat, gaz_lon=glon,
                     gaz_type=(f'{gz.get("class")}/{gz.get("type")}' if gz else ""),
                     agency_id=aid or "", agency_name=aname, agency_lat=alat, agency_lon=alon,
                     agency_km_from_village=round(d_agency, 1) if not pd.isna(d_agency) else "",
                     sheet_modal=f"{vc.index[0]}" if len(vc) else "", sheet_modal_n=int(vc.iloc[0]) if len(vc) else 0,
                     sheet_nearest=f"{best_vote}", sheet_nearest_km=round(best_d, 1) if not pd.isna(best_d) else ""))
W = pd.read_csv(B / "_wmo_catalogue.csv").set_index("wmo")
for st, (wmo, ev) in WMO_MATCH.items():
    w = W.loc[wmo]
    rows.append(dict(station=st, lat=round(w["lat"], 4), lon=round(w["lon"], 4), elev_m=w["elev"],
                     coord_source=f"WMO {wmo} {w['name']} (data identity: {ev})", flag="", wmo_id=wmo))
C = pd.DataFrame(rows)
nonplace = ~C["gaz_type"].str.split("/").str[0].isin(["place", "boundary", ""])
C.loc[nonplace, "flag"] = (C.loc[nonplace, "flag"].fillna("") + "; gazetteer hit is a " + C.loc[nonplace, "gaz_type"]).str.strip("; ")
C.to_csv(B / "_agro_station_catalogue.csv", index=False)
pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 60)
print(C[["station", "lat", "lon", "coord_source", "flag", "agency_km_from_village", "sheet_modal", "sheet_modal_n",
         "sheet_nearest_km"]].to_string(index=False))
print("\ngazetteer names:")
for _, r in C.iterrows():
    print(f"  {r.station:14s} {r.gazetteer}")
