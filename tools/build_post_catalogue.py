"""Coordinates for the phase-2 rain posts (BMG/Data forms, Sumsel, West Sumatra).

Writes F:/temp/station/additional-sources/_post_catalogue.csv with one row per post key the
`post_forms` reader uses, and where each coordinate came from. Order of preference, per post:
  1. coordinates written in the post's own form (DMS text);
  2. the same post in a monthly station table of the same collection
     (`_NTB/CH_se-NTB.xls`, `_SUMBAR/Data Sumbar.XLS`, `CH_IND/catalog West Sumatera.xls`);
  3. the BMKG POS-HUJAN catalogue (`_poshujan_catalogue.csv`, from STA-BMG.XLS), matched by
     name within the province's region codes (Sumsel only: for West Sumatra, region 19 puts
     Sicincin at +0.55 deg, north of the equator, so it is not used); a post number written next to the name is a
     cross-check only (it disagrees for some posts, e.g. Sanna "191 e" vs catalogue 24191F).
Name matching: exact normalized name, else a single candidate with similarity >= 0.85
(difflib); a named sub-post such as "Indralaya (Camp 14)" never takes its parent's position.
Rows from 2 and 3 are marked coord_approx (degree-minute or coarser precision). Posts with no
coordinate are listed with an empty lat/lon and are skipped by the reader.

Usage: python tools/build_post_catalogue.py
"""
from __future__ import annotations

import difflib
import math
import re
import sys
from pathlib import Path

import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers import post_forms  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path("F:/temp/station/additional-sources")
OUT = ROOT / "_post_catalogue.csv"


def norm(s: str) -> str:
    s = str(s).upper()
    s = re.sub(r"\(.*?(\)|$)", " ", s)  # also an unclosed "(" (POS-HUJAN names are cut at 15 chars)
    s = s.split(",")[0]
    s = re.sub(r"\b(SMPK|SPP|BPP|SP|PTP|PU|UPP|KPTP|STA|POS)\b\.?", " ", s)
    return re.sub(r"[^A-Z]", "", s)


def km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    if any(pd.isna(x) for x in (la1, lo1, la2, lo2)):
        return float("nan")
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((la2 - la1) * p / 2) ** 2 +
                                          math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2))


def dms(deg, mi, sec=0.0, sign=-1):
    return sign * (float(deg) + float(mi) / 60 + float(sec) / 3600)


POS = pd.read_csv(ROOT / "_poshujan_catalogue.csv", dtype={"id": str})


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def sub_post(name: str) -> bool:
    """A named sub-post such as 'Indralaya (Camp 14)': never borrows its parent's coordinates."""
    return bool(re.search(r"\(.+\)", str(name)))


def best_match(name, table_keys):
    """Exact normalized name, else the single key with similarity >= 0.85. Returns key or None/'ambiguous:..'."""
    k = norm(name)
    if len(k) < 4 or sub_post(name):
        return None
    if k in table_keys:
        return k
    cand = [t for t in table_keys if len(t) >= 4 and similar(k, t) >= 0.85]
    if len(cand) == 1:
        return cand[0]
    return ("ambiguous:" + ";".join(cand)) if cand else None


def pos_by_name(name, regions):
    cand = POS[POS.id.str[:2].isin(regions)].copy()
    cand["k"] = cand.name.map(norm)
    m = best_match(name, set(cand.k))
    if m is None or m.startswith("ambiguous"):
        return m
    hit = cand[cand.k == m]
    return hit.iloc[0] if len(hit) == 1 else "ambiguous:" + ";".join(hit.id)


rows = []
# ---- 1. BMG/Data forms (coordinates read from the forms; see recheck dumps) ----
form = {
    "Lelogama": (dms(9, 42, 26.9), dms(123, 57, 14.8, +1), 872, "form: 09o 42' 26,9\" LS / 123o 57' 14,8\" BT", "470c"),
    "Oesao": (dms(10, 5, 51.1), dms(123, 50, 32.9, +1), 15, "form: 10o 05' 51,1\" LS / 123o 50' 32,9\" BT", "470f"),
    "Patas": (dms(8, 12, 44), dms(114, 47, 17, +1), 45, "form: 08 12 44 - 114 47 17 E (hemisphere S not written)", "437g"),
    "Pohsanten": (dms(8, 22, 8), dms(114, 40, 20, +1), None, "form: 08 22 08 S - 114 40 20 E", "437"),
}
pos_check = {"Patas": "34437G", "Pohsanten": "34437", "Batubassi": "33428", "Praya": "35451"}
for k, (lat, lon, el, how, no) in form.items():
    pc = POS.set_index("id").loc[pos_check[k]] if k in pos_check else None
    note = "" if pc is None else f"POS-HUJAN {pos_check[k]} {pc['name']} at {km((lat, lon), (pc.lat, pc.lon)):.1f} km"
    rows.append(dict(source="bmg_posts", post_key=k, name=k, post_no=no, lat=lat, lon=lon, elev=el,
                     coord_source=how, coord_approx=False, note=note))
# Praya: NTB monthly table '451 Praja 8 43 S 116 17 E 101 m' (form elevation 100 m, no coords)
pc = POS.set_index("id").loc["35451"]
lat, lon = dms(8, 43), dms(116, 17, 0, +1)
rows.append(dict(source="bmg_posts", post_key="Praya", name="Praya", post_no="451", lat=lat, lon=lon, elev=101,
                 coord_source="_NTB/CH_se-NTB.xls: 451 Praja 8 43 S 116 17 E 101 m", coord_approx=True,
                 note=f"POS-HUJAN 35451 {pc['name']} at {km((lat, lon), (pc.lat, pc.lon)):.1f} km"))
pc = POS.set_index("id").loc["33428"]
rows.append(dict(source="bmg_posts", post_key="Batubassi", name="Batubassi", post_no="428", lat=pc.lat, lon=pc.lon,
                 elev=pc.elev, coord_source="POS-HUJAN 33428 BATUBASSI", coord_approx=True, note="form gives no coordinates"))
rows.append(dict(source="bmg_posts", post_key="Peninjauan", name="Peninjauan", post_no="446a?", lat=None, lon=None,
                 elev=125, coord_source="", coord_approx=True,
                 note="no coordinates anywhere; form post no. 446a is MATARAM (PMG) in POS-HUJAN; skipped"))

# Larantuka (DATA IKLIM/_NTT/Larantuka(85-96)(harian).XLS): the 1985-1987 sheets give
# 8 36 35 S 122 54 55 E; 1988+ sheets carry Bogor/Muara template coordinates, but every year's
# rainfall fits CPC at Larantuka (r 0.28-0.81) and not at Bogor (<= 0.18), measured 2026-11-25.
rows.append(dict(source="ntt_larantuka", post_key="Larantuka", name="Larantuka", post_no="",
                 lat=dms(8, 36, 35), lon=dms(122, 54, 55, +1), elev=75,
                 coord_source="form 1985: 8 36 35 S 122 54 55 E, alt=75 m", coord_approx=False,
                 note="1988+ sheets: template coordinates 6 40 S 106 45 E ignored"))

# ---- 2. Sumsel posts (names from the unlocked workbooks; recheck dump) ----
cells = pd.read_csv("F:/temp/station/additional_recheck/dash_semantics_cells.csv.gz", usecols=["source", "post", "cls"])
ss = cells[cells.source.str.startswith("Sumsel")]
ss = ss.groupby(["source", "post"]).cls.apply(lambda c: int(c.isin(["pos", "zero"]).sum())).reset_index(name="nval")
for r in ss.itertuples():
    m = pos_by_name(r.post, ["24"])
    num = re.search(r",\s*(\d{2,3})\s*([a-zA-Z])?", r.post)
    numtxt = (num.group(1) + (num.group(2) or "").upper()) if num else ""
    base = dict(source="sumsel_posts", post_key=f"{r.source.split(':')[1]}|{r.post}", name=r.post, post_no=numtxt)
    if isinstance(m, pd.Series):
        chk = "" if not numtxt else ("number agrees" if m.id[2:] == numtxt else f"number in name {numtxt} != {m.id[2:]}")
        rows.append(dict(base, lat=m.lat, lon=m.lon, elev=m.elev, coord_source=f"POS-HUJAN {m.id} {m['name']}",
                         coord_approx=True, note=f"{chk}; {r.nval} values".strip("; ")))
    else:
        rows.append(dict(base, lat=None, lon=None, elev=None, coord_source="", coord_approx=True,
                         note=f"{m or 'no POS-HUJAN name match'}; {r.nval} values"))

# ---- 3. West Sumatra posts (d_rainfall_west_sumatera.xls) ----
wb = xlrd.open_workbook(str(ROOT / "DATA IKLIM/CH_IND/d_rainfall_west_sumatera.xls"))
sh = wb.sheet_by_index(0)
posts = {}
for r in range(1, sh.nrows):
    no, nm = post_forms.text(sh.cell_value(r, 0)), str(sh.cell_value(r, 1)).strip()
    no = re.sub(r"\.0$", "", no)   # same key rule as post_forms.lay_station_month_rows
    if nm and nm.upper() not in ("STA",):
        posts[(no, nm)] = posts.get((no, nm), 0) + 1
ds = xlrd.open_workbook(str(ROOT / "DATA IKLIM/_SUMBAR/Data Sumbar.XLS")).sheet_by_name("MONTHLY")
sumbar = {}
for r in range(1, ds.nrows):
    nm, no, la, lo, el = (ds.cell_value(r, c) for c in range(5))
    if isinstance(la, float) and isinstance(lo, float) and la != 0:
        sumbar.setdefault(norm(nm), (str(nm).strip(), str(no).strip(), la, lo, el if isinstance(el, float) else None))
cw = xlrd.open_workbook(str(ROOT / "DATA IKLIM/CH_IND/catalog West Sumatera.xls")).sheet_by_index(0)
catw = {}
for r in range(1, cw.nrows):
    nm, no, la, lo, el = (cw.cell_value(r, c) for c in range(5))
    if isinstance(la, float) and isinstance(lo, float) and la != 0:
        catw.setdefault(norm(nm), (str(nm).strip(), str(no).strip(), la, lo, el if isinstance(el, float) else None))
        catw.setdefault("NO:" + re.sub(r"[^0-9A-Z]", "", str(no).upper()), (str(nm).strip(), str(no).strip(), la, lo, el if isinstance(el, float) else None))
# A table position is valid only inside West Sumatra: Data Sumbar has SEI LANGSAT at lat -91
# (catalog West Sumatera: -0.91) and Peconina / Tanjung Barulak at 1.6 / 1.5 N (review 2026-11-25).
SUMBAR_BOX = (-3.6, 1.0, 98.5, 102.0)
inbox = lambda la, lo: SUMBAR_BOX[0] <= la <= SUMBAR_BOX[1] and SUMBAR_BOX[2] <= lo <= SUMBAR_BOX[3]
dec_path = ROOT / "_post_position_decisions.csv"   # tools/check_post_positions.py (neighbour rainfall)
decisions = pd.read_csv(dec_path).set_index("post_key") if dec_path.exists() else pd.DataFrame()
for (no, nm), n in sorted(posts.items(), key=lambda x: x[0][1]):
    nok = "NO:" + re.sub(r"[^0-9A-Z]", "", no.upper())
    cands = []   # (label, (name, no, lat, lon, elev))
    for tab, label in ((sumbar, "_SUMBAR/Data Sumbar.XLS"), (catw, "CH_IND/catalog West Sumatera.xls")):
        m = best_match(nm, {k for k in tab if not k.startswith("NO:")})
        if m and not m.startswith("ambiguous"):
            cands.append((f"{label} by name ({tab[m][0]} {tab[m][1]})", tab[m]))
    if not any("catalog West" in c[0] for c in cands) and no and nok in catw:
        cands.append((f"CH_IND/catalog West Sumatera.xls by Nosta {no} ({catw[nok][0]})", catw[nok]))
    rejected = [c for c in cands if not inbox(c[1][2], c[1][3])]
    valid = [c for c in cands if inbox(c[1][2], c[1][3])]
    base = dict(source="sumbar_daily", post_key=f"{no}|{nm}", name=nm, post_no=no)
    rej = "; ".join(f"rejected outside West Sumatra: {c[0]} lat {c[1][2]:g}" for c in rejected)
    pk = base["post_key"]
    dec = decisions.loc[pk] if pk in decisions.index and decisions.loc[pk, "how"] != "undecided" else None
    note = f"{n} station-months"
    if dec is not None:
        elev = next((c[1][4] for c in valid if c[1][4] is not None), None)
        rows.append(dict(base, lat=float(dec.lat), lon=float(dec.lon), elev=elev, coord_source=dec.how,
                         coord_approx=True, note="; ".join(x for x in (note, rej, f"evidence: {dec.evidence}") if x)))
        continue
    pos = {(round(c[1][2], 4), round(c[1][3], 4)) for c in valid}
    if len(valid) >= 2 and km(valid[0][1][2:4], valid[1][1][2:4]) > 5:
        rows.append(dict(base, lat=None, lon=None, elev=None, coord_source="", coord_approx=True,
                         note=f"skipped: tables disagree by {km(valid[0][1][2:4], valid[1][1][2:4]):.0f} km and the "
                              f"rainfall does not decide ({valid[0][0]} vs {valid[1][0]}); {note}"))
        continue
    if valid:
        c = valid[0]
        flag = "; positive latitude kept, sign not verified" if c[1][2] > 0 else ""
        rows.append(dict(base, lat=c[1][2], lon=c[1][3], elev=c[1][4], coord_source=c[0], coord_approx=True,
                         note="; ".join(x for x in (note + flag, rej) if x)))
    else:
        rows.append(dict(base, lat=None, lon=None, elev=None, coord_source="", coord_approx=True,
                         note="; ".join(x for x in (("skipped: no valid position" if rejected else "no match") + f"; {note}", rej) if x)))

df = pd.DataFrame(rows)
df.to_csv(OUT, index=False)
for s, g in df.groupby("source"):
    print(f"{s}: posts {len(g)}, with coordinates {int(g.lat.notna().sum())}, without {int(g.lat.isna().sum())}")
pd.set_option("display.width", 250)
print(df[["source", "post_key", "lat", "lon", "coord_source", "note"]].to_string(index=False, max_colwidth=60))
