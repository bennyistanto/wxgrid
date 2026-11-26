"""Which position is right where a PU SIHKA post and the PU register disagree by more than 1 km (F77)?

Inputs: F:/temp/station/pu_sihka/measure/pu_positions_for_register.csv (tools/export_pu_positions.py) and
register_far_matches_2026-11-26.txt (tools/compare_pu_register.js, read in a browser tab). Read only.
For each pair it reports:
  copy      the SIHKA position is shared (< 50 m) with another PU post in the build, or sits on another register post
  land      whether each position is on land (E:/temp/idn-bnd/idn_bnd_adm0.shp)
  office    whether the SIHKA unit and the register's river-basin office agree
  r         mean daily-rainfall correlation of the post with its 5 nearest other gauges (any source, >= 300 common
            days, < 40 km, PU posts at the same position excluded), around each candidate position
and writes the table to F:/temp/station/pu_sihka/measure/register_far_assessment.csv.
Usage: python tools/measure_pu_register.py
"""
import math
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

sys.stdout.reconfigure(encoding="utf-8")
M = "F:/temp/station/pu_sihka/measure/"
C = "F:/temp/station/compiled/"


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


lines = [ln for ln in open(M + "register_far_matches_2026-11-26.txt", encoding="utf-8") if ln.strip()]
balai = dict(x.split("=", 1) for x in lines[3].split(":", 1)[1].strip().split(";"))
far = pd.DataFrame([ln.rstrip("\n").split("|") for ln in lines if not ln.startswith("#")],
                   columns=["i", "reg_id", "reg_lat", "reg_lon", "balai", "near_id", "near_name"])
far = far.astype({"i": int, "reg_lat": float, "reg_lon": float})
far["reg_office"] = far.balai.map(balai)
pu = pd.read_csv(M + "pu_positions_for_register.csv", index_col="i")
far = far.join(pu, on="i")
far["d_km"] = [km(a, b, c, d) for a, b, c, d in zip(far.lat, far.lon, far.reg_lat, far.reg_lon)]

# copy: SIHKA position shared with another PU post
far["ours_shared_with"] = [";".join(pu[(pu.index != i) & (abs(pu.lat - la) < 5e-4) & (abs(pu.lon - lo) < 5e-4)].cat_name)
                           for i, la, lo in zip(far.i, far.lat, far.lon)]
norm = lambda s: str(s).upper().replace("BALAI BESAR WILAYAH SUNGAI", "BBWS").replace("BALAI WILAYAH SUNGAI", "BWS").replace(".", "").strip()
far["office_agree"] = [norm(u) == norm(r) for u, r in zip(far.unit, far.reg_office)]

idn = gpd.read_file("E:/temp/idn-bnd/idn_bnd_adm0.shp").to_crs(4326).union_all()
far["ours_land"] = [idn.contains(Point(lo, la)) for la, lo in zip(far.lat, far.lon)]
far["reg_land"] = [idn.contains(Point(lo, la)) for la, lo in zip(far.reg_lat, far.reg_lon)]

# rainfall agreement around each candidate position
st = pd.read_csv(C + "stations.csv.gz")
se = pd.read_csv(C + "series.csv.gz", usecols=["series_id", "station_key", "variable", "n_values"])
se = se[(se.variable == "RR") & (se.n_values >= 300)]
st = st[st.station_key.isin(se.station_key)]
need, pick = set(), {}
for r in far.itertuples():
    own = se[se.station_key == r.station_key].series_id.tolist()
    shared = set(pu[(abs(pu.lat - r.lat) < 5e-4) & (abs(pu.lon - r.lon) < 5e-4)].station_key)
    for tag, la, lo in (("ours", r.lat, r.lon), ("reg", r.reg_lat, r.reg_lon)):
        o = st[~st.station_key.isin(shared | {r.station_key})].copy()
        o = o[(abs(o.lat - la) < 0.4) & (abs(o.lon - lo) < 0.4)]
        o["d"] = [km(la, lo, a, b) for a, b in zip(o.lat, o.lon)]
        o = o[o.d < 40].nsmallest(8, "d")
        ids = se[se.station_key.isin(o.station_key)].series_id.tolist()
        pick[(r.i, tag)] = (own, ids)
        need |= set(own) | set(ids)
ob = pd.concat(c[c.series_id.isin(need)] for c in pd.read_csv(C + "observations_RR.csv.gz", usecols=["series_id", "date", "value", "flag"],
                                                             chunksize=3_000_000, dtype={"flag": str}))
ob = ob[~ob.flag.fillna("").str.contains("qc_excluded|src_duplicate|collision|src_unrealistic")].dropna(subset=["value"])
W = ob.pivot_table(index="date", columns="series_id", values="value", aggfunc="first")


def mean_r(own, ids):
    if not own or own[0] not in W:
        return np.nan, 0
    x = W[own[0]]
    rs = []
    for s in ids:
        if s not in W:
            continue
        j = x.notna() & W[s].notna()
        if j.sum() >= 300:
            rs.append(np.corrcoef(x[j], W[s][j])[0, 1])
        if len(rs) == 5:
            break
    return (float(np.mean(rs)) if rs else np.nan), len(rs)


for tag in ("ours", "reg"):
    v = [mean_r(*pick[(i, tag)]) for i in far.i]
    far[f"r_{tag}"] = [a for a, _ in v]
    far[f"n_{tag}"] = [b for _, b in v]

far = far.sort_values("d_km", ascending=False)
cols = ["i", "station_key", "cat_name", "unit", "lat", "lon", "reg_id", "reg_lat", "reg_lon", "reg_office", "d_km", "ours_shared_with",
        "near_name", "office_agree", "ours_land", "reg_land", "r_ours", "n_ours", "r_reg", "n_reg"]
far[cols].to_csv(M + "register_far_assessment.csv", index=False)
pd.set_option("display.width", 260, "display.max_rows", 300, "display.max_colwidth", 28)
b = pd.cut(far.d_km, [1, 5, 25, 1e4], labels=["1-5 km", "5-25 km", "> 25 km"])
print(f"pairs {len(far)}; by distance {b.value_counts().to_dict()}")
print(f"SIHKA position shared with another PU post: {(far.ours_shared_with != '').sum()}; office disagrees: {(~far.office_agree).sum()}")
print(f"SIHKA position at sea: {(~far.ours_land).sum()}; register at sea: {(~far.reg_land).sum()}")
ok = far.r_ours.notna() & far.r_reg.notna()
dr = far.r_reg - far.r_ours
for lab, m in (("all > 1 km", ok), ("> 5 km", ok & (far.d_km > 5))):
    print(f"r neighbours ({lab}, n {m.sum()}): SIHKA {far.r_ours[m].mean():.3f}, register {far.r_reg[m].mean():.3f}; "
          f"register better by > 0.05 in {(dr[m] > 0.05).sum()}, SIHKA better by > 0.05 in {(dr[m] < -0.05).sum()}")
print(far[far.d_km > 5][["i", "cat_name", "unit", "reg_office", "d_km", "ours_shared_with", "ours_land", "reg_land", "r_ours", "r_reg"]]
      .round(3).to_string(index=False))
