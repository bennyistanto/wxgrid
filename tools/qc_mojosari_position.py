"""QC agro:MOJOSARI, question 3 (position and elevation).

  1. candidate positions: build (BMKG catalogue 12175A), the sheet header (7 30 S, 112 28 E,
     "30 m", Kabupaten "Malang"), the gazetteer town point (from _agro_station_catalogue.csv),
     and jatim:175_MOJOSARI; distances between them; station elevations within 10 km of each;
  2. correlation-distance triangulation: for a 0.02 deg grid of candidate points within 0.3 deg,
     fit r_i = c * exp(-d_i / L) (c, L free, least squares) to the partners' r and record the
     misfit; the best point is where the misfit is smallest. Partners: RR series within 60 km
     of the build position with >= 1000 common days 1973-1994, distinct sites, copies (>= 50%
     equal wet values) removed. agro r at lag +1 (its best lag, form dates); control: the same
     for jatim:175_MOJOSARI at lag 0 (excluding agro:MOJOSARI from its partners).
No DEM is on disk (F:/temp searched 2026-11-25), so DEM elevation is not tested.
Outputs: F:/temp/station/qc_mojosari/position_*.csv. Run: python tools/qc_mojosari_position.py
"""
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
o = q.obs_ejava(); meta = q.rr_meta().set_index("series_id")
cat = pd.read_csv("F:/temp/station/additional-sources/_agro_station_catalogue.csv").set_index("station").loc["Mojosari"]
P = {"build (BMKG cat 12175A)": (meta.loc[q.A, "lat"], meta.loc[q.A, "lon"]),
     "sheet header 7 30 S 112 28 E": (-7.5, 112 + 28 / 60),
     "gazetteer Mojosari town": (cat.gaz_lat, cat.gaz_lon),
     "jatim:175_MOJOSARI": (meta.loc["jatim:175_MOJOSARI:RR", "lat"], meta.loc["jatim:175_MOJOSARI:RR", "lon"]),
     "jatim:93_PUDAKSARI": (meta.loc["jatim:93_PUDAKSARI:RR", "lat"], meta.loc["jatim:93_PUDAKSARI:RR", "lon"])}
names = list(P)
Dm = pd.DataFrame([[q.haversine_km(*P[i], *P[j]) for j in names] for i in names], index=names, columns=names)
Dm.to_csv(f"{q.OUT}/position_candidate_distances.csv")
print("=== distances between candidate positions (km) ===")
print(Dm.round(1).to_string())
st = q.stations()
st = st[st.lat.between(-8.2, -6.8) & st.lon.between(111.8, 113.3)]
print("\n=== station elevations (stations.csv.gz) within 10 km of each candidate ===")
rows = []
for nme, (la, lo) in P.items():
    d = q.haversine_km(la, lo, st.lat.values, st.lon.values)
    s = st[(d <= 10)].assign(d_km=d[d <= 10])
    for r in s.itertuples():
        rows.append(dict(candidate=nme, station=r.station_key, name=r.name, d_km=r.d_km, elev_m=r.elev_m))
E = pd.DataFrame(rows)
E.to_csv(f"{q.OUT}/position_nearby_elevations.csv", index=False)
print(E.sort_values(["candidate", "d_km"]).to_string(index=False, float_format=lambda x: f"{x:.1f}"))

idx = pd.date_range("1973-01-01", "1994-12-31")


def partner_r(target, lag, col):
    t = q.daily(o, target, col=col).reindex(idx)
    la, lo = meta.loc[target, ["lat", "lon"]]
    rows = []
    for s in meta.index:
        if s == target or meta.loc[s, "site_id"] == meta.loc[target, "site_id"] or s == q.A:
            continue
        d = float(q.haversine_km(la, lo, meta.loc[s, "lat"], meta.loc[s, "lon"]))
        if d > 60:
            continue
        x = q.daily(o, s, unmeasurable_as=0.0)
        if x.empty:
            continue
        b = x.reindex(idx + pd.Timedelta(days=lag)).values
        ok = np.isfinite(t.values) & np.isfinite(b)
        if ok.sum() < 1000:
            continue
        w = ok & ((t.values > 0) | (b > 0))
        if (t.values[w] == b[w]).mean() >= 0.5:
            continue
        rows.append(dict(series=s, site=meta.loc[s, "site_id"], lat=meta.loc[s, "lat"], lon=meta.loc[s, "lon"],
                         r=float(np.corrcoef(t.values[ok], b[ok])[0, 1]), n=int(ok.sum())))
    R = pd.DataFrame(rows).sort_values("r", ascending=False).drop_duplicates("site")
    return R


def triang(R, la0, lo0):
    f = lambda d, c, L: c * np.exp(-d / L)
    out = []
    for la in np.arange(la0 - 0.3, la0 + 0.3001, 0.02):
        for lo in np.arange(lo0 - 0.3, lo0 + 0.3001, 0.02):
            d = q.haversine_km(la, lo, R.lat.values, R.lon.values)
            try:
                p, _ = curve_fit(f, d, R.r.values, p0=(0.5, 50), bounds=([0, 1], [1, 2000]))
                sse = float(((R.r.values - f(d, *p)) ** 2).sum())
            except RuntimeError:
                continue
            out.append(dict(lat=la, lon=lo, sse=sse, c=p[0], L=p[1]))
    return pd.DataFrame(out).sort_values("sse")


res = []
for target, lag, col in [(q.A, 1, "date_raw"), ("jatim:175_MOJOSARI:RR", 0, "date")]:
    R = partner_r(target, lag, col)
    R.to_csv(f"{q.OUT}/position_partners_{target.split(':')[1]}.csv", index=False)
    la0, lo0 = meta.loc[target, ["lat", "lon"]]
    T = triang(R, la0, lo0)
    T.to_csv(f"{q.OUT}/position_triangulation_{target.split(':')[1]}.csv", index=False)
    b = T.iloc[0]
    at0 = T.assign(dd=(T.lat - la0) ** 2 + (T.lon - lo0) ** 2).sort_values("dd").iloc[0]
    near = T[T.sse <= b.sse * 1.10]
    res.append(dict(target=target, lag=lag, n_partners=len(R), best_lat=b.lat, best_lon=b.lon,
                    best_shift_km=float(q.haversine_km(la0, lo0, b.lat, b.lon)), sse_best=b.sse, sse_at_listed=at0.sse,
                    c_best=b.c, L_best=b.L, c_listed=at0.c, L_listed=at0.L,
                    n_points_within_10pct=len(near),
                    max_km_within_10pct=float(q.haversine_km(la0, lo0, near.lat.values, near.lon.values).max())))
    print(f"\n{target} (lag {lag}): {len(R)} partners; top 8 by r:")
    print(R.head(8).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
Res = pd.DataFrame(res)
Res.to_csv(f"{q.OUT}/position_summary.csv", index=False)
print("\n=== correlation-distance triangulation ===")
print(Res.T.to_string())

T = pd.read_csv(f"{q.OUT}/position_triangulation_MOJOSARI.csv")
print("\nagro misfit at the candidate positions (nearest grid point), relative to the best point:")
for nme, (la, lo) in P.items():
    t = T.assign(dd=(T.lat - la) ** 2 + (T.lon - lo) ** 2).sort_values("dd").iloc[0]
    print(f"  {nme:32s} sse {t.sse:.4f} ({t.sse / T.sse.min():.2f} x best)")
