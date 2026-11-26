"""pu_sihka /qc, question 4b: gross position errors. For posts off land by > 1 km, in the wrong province, or
sharing a position with another post (q0_metadata.csv), plus the posts where another header position fit
better (q4_decisions.csv), test two kinds of alternative position:
  degree typo   the compiled minutes and seconds kept, the whole degree of latitude or longitude replaced
                by every value within 3 degrees of the median position of the posts of the same office
                (e.g. a longitude written 104 instead of 140)
  partners      the r-weighted centroid of the 3 best-correlated anchor series (only when the best r >= 0.5)
Each candidate is scored as in tools/qc_pu_sihka_positions.py: median distance to the 3 best-correlated
anchors (lags -1..+1, >= 200 shared days) and CPC r (best of lags -1..+1). A candidate must be on NE10m land.

Output: F:/temp/station/qc_pu_sihka/q4b_hypotheses.csv; log q4b.log
Usage: python tools/qc_pu_sihka_position_hypotheses.py
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402
from qc_pu_sihka_positions import best_r  # noqa: E402

OUT = Path(c.OUT)
NE = Path.home() / ".local/share/cartopy/shapefiles/natural_earth"


def main():
    st = pd.read_csv(OUT / "q0_metadata.csv").set_index("station_key")
    dec = pd.read_csv(OUT / "q4_decisions.csv")
    ev = set(st.index[~st.on_land & (st.coast_km > 1)]) | set(st.index[st.prov_match == "NO"]) | \
        set(st.index[st.same_position_as.notna()]) | set(dec.station_key[dec.verdict == "other candidate fits"])
    land = gpd.read_file(NE / "physical" / "ne_10m_land.shp").cx[90:145, -15:12].union_all()
    w, meta = c.panel()
    vals = w.to_numpy()
    meta["n"] = np.isfinite(vals).sum(0)
    main_col = meta[meta.kind == "pu"].sort_values("n", ascending=False).drop_duplicates("station_key").set_index("station_key").col
    good = st[(st.spread_km <= 1) & st.on_land & (st.prov_match != "NO") & st.same_position_as.isna()].index
    meta["anchor"] = (meta.kind == "site") | meta.station_key.isin(good)
    office = st.groupby("unit")[["lat", "lon"]].median()
    cpc = c.CPCField()
    days = w.index
    rows = []
    for sk in sorted(ev):
        if sk not in main_col.index:
            continue
        x = vals[:, meta.index[meta.col == main_col[sk]][0]]
        la0, lo0 = st.at[sk, "lat"], st.at[sk, "lon"]
        sp = st.at[sk, "same_position_as"]
        group = {g.split(" ")[0] for g in sp.split(";")} if isinstance(sp, str) else set()
        am = meta.anchor.values & (meta.station_key.values != sk) & ~meta.station_key.isin(group).values
        A = meta[am]
        r = best_r(x, vals[:, A.index.values])
        ok = np.isfinite(r)
        top = [t for t in np.argsort(np.where(ok, r, -9))[::-1][:3] if ok[t]]
        if not top:
            continue
        cands = [("compiled", la0, lo0)]
        olat, olon = office.loc[st.at[sk, "unit"]]
        fl, fo = abs(la0) % 1, lo0 % 1
        sgn = -1 if la0 < 0 else 1
        for dlat in range(int(abs(olat)) - 3, int(abs(olat)) + 4):
            if dlat >= 0 and dlat != int(abs(la0)):
                for s in (-1, 1):
                    cands.append(("lat degree %d (%s)" % (dlat, "S" if s < 0 else "N"), s * (dlat + fl), lo0))
        for dlon in range(int(olon) - 3, int(olon) + 4):
            if dlon != int(lo0):
                cands.append(("lon degree %d" % dlon, la0, dlon + fo))
        if r[top[0]] >= 0.5:
            wts = r[top]
            cands.append(("partners centroid", float(np.average(A.lat.values[top], weights=wts)), float(np.average(A.lon.values[top], weights=wts))))
        res = []
        for nm, la, lo in cands:
            if nm != "compiled" and nm != "partners centroid" and not land.contains(Point(lo, la)):
                continue
            # re-rank partners near this candidate too: score = median distance to the top 3 overall
            d = c.haversine_km(la, lo, A.lat.values[top], A.lon.values[top])
            crs = [c.pearson(x, cpc.at(la, lo, days, lag=L), min_n=200)[0] for L in (-1, 0, 1)]
            res.append(dict(station_key=sk, name=st.at[sk, "name"], unit=st.at[sk, "unit"], candidate=nm, lat=round(la, 5), lon=round(lo, 5),
                            km_from_compiled=round(float(c.haversine_km(la0, lo0, la, lo)), 1), median_km_top3=round(float(np.median(d)), 1),
                            cpc_r=round(float(np.nanmax(crs)), 3) if np.isfinite(crs).any() else np.nan, top_r=round(float(r[top[0]]), 2),
                            partners="; ".join("%s r=%.2f" % (A.station_key.values[t], r[t]) for t in top)))
        res = pd.DataFrame(res).sort_values("median_km_top3")
        res["rank"] = np.arange(1, len(res) + 1)
        rows.append(res)
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(OUT / "q4b_hypotheses.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 120)
    for sk, g in out.groupby("station_key"):
        comp = g[g.candidate == "compiled"].iloc[0]
        print("%s %s | compiled: top3 median %.0f km, CPC r %s | best: %s" % (sk, comp["name"], comp.median_km_top3, comp.cpc_r,
              "; ".join("%s (%.4f, %.4f) %.0f km from compiled, top3 %.0f km, CPC r %s" % (a.candidate, a.lat, a.lon, a.km_from_compiled, a.median_km_top3, a.cpc_r)
                        for a in g.head(3).itertuples())))
        print("    partners:", comp.partners)


if __name__ == "__main__":
    main()
