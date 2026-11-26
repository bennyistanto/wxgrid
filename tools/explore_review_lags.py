"""Per-year lag test for crosswalk pairs flagged needs_review (exploratory).

For every tested series pair of each review station pair, compute r at lags -1, 0, +1
per calendar year (>= 200 overlap days) and report the per-year best lag. A series whose
best lag changes over time has a time-varying day label, not a different gauge.
Run from the compiled output folder. Writes review_lag_by_year.csv there.
"""
import numpy as np
import pandas as pd

cw = pd.read_csv("crosswalk_stations.csv")
sp = pd.read_csv("crosswalk_series.csv")
rev = cw[cw.needs_review]
pairs = sp.merge(rev[["station_a", "station_b"]], on=["station_a", "station_b"])
pairs = pairs[pairs.n_overlap >= 365]
need = set(pairs.series_a) | set(pairs.series_b)
o = pd.read_csv("observations_RR.csv.gz", usecols=["series_id", "date", "value", "flag"])
o = o[o.series_id.isin(need) & o.flag.isna()]
o["date"] = pd.to_datetime(o["date"])
vals = {k: g.set_index("date")["value"] for k, g in o.groupby("series_id")}
rows = []
for _, p in pairs.iterrows():
    a, b = vals.get(p.series_a), vals.get(p.series_b)
    if a is None or b is None:
        continue
    for lag in (-1, 0, 1):
        bb = b.copy(); bb.index = bb.index + pd.Timedelta(days=lag)
        x, y = a.align(bb, join="inner")
        df = pd.DataFrame({"x": x, "y": y})
        for yr, g in df.groupby(df.index.year):
            if len(g) >= 200 and g.x.std() > 0 and g.y.std() > 0:
                rows.append(dict(station_a=p.station_a, station_b=p.station_b, series_a=p.series_a,
                                 series_b=p.series_b, year=yr, lag=lag, n=len(g), r=g.x.corr(g.y),
                                 equal=float((np.abs(g.x - g.y) <= 0.05).mean())))
r = pd.DataFrame(rows)
r.to_csv("review_lag_by_year.csv", index=False)
best = r.loc[r.groupby(["series_a", "series_b", "year"]).r.idxmax()]
summ = best.groupby(["station_a", "station_b", "series_a", "series_b"]).agg(
    years=("year", "size"), first=("year", "min"), last=("year", "max"),
    lag_m1=("lag", lambda s: int((s == -1).sum())), lag_0=("lag", lambda s: int((s == 0).sum())),
    lag_p1=("lag", lambda s: int((s == 1).sum())), r_med=("r", "median"), equal_med=("equal", "median")).reset_index()
summ.to_csv("review_lag_summary.csv", index=False)
print(summ.round(2).to_string(index=False))
