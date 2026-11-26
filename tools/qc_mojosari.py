"""QC focus 2: agro:MOJOSARI:RR (1973-1994) correlates weakly with every neighbour. Why?

Uses raw form dates (date_raw) for every series so that day-label corrections do not mix in,
and repeats with the corrected dates. Per calendar year, Pearson r at lags -3..+3 between
agro Mojosari and: (a) CPC-UNI at its cell (raw station day D vs CPC day D+lag-1, so lag 0 = a
correctly labelled BMKG series, F38), (b) PU jatim:175_MOJOSARI, (c) PU jatim:93_PUDAKSARI,
(d) the daily mean of the long PU posts within 25 km (Mojosari, Pudaksari, Lengkong, Sidoarjo).
Lag k means agro value on day D is paired with partner day D+k. Also: pentad, dekad and monthly
totals (robust to day shifts), scale (ratio of means, wet-day frequency, annual totals), value
resolution, and a search for the best-matching series within 150 km (wrong position or swap).
Writes F:/temp/station/qc_phase2/mojosari_*.csv. Run: python tools/qc_mojosari.py
"""
import numpy as np
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
o = q.obs_rr()
st = q.stations().set_index("station_key"); se = q.series().set_index("series_id")
A = "agro:MOJOSARI:RR"
PART = {"pu_mojosari": "jatim:175_MOJOSARI:RR", "pu_pudaksari": "jatim:93_PUDAKSARI:RR",
        "pu_lengkong": "jatim:91_LENGKONG:RR", "pu_sidoarjo": "jatim:162_SIDOARJO:RR"}
BAD = "src_duplicate|qc_excluded"


def get(sid, col="date_raw"):
    g = o[(o.series_id == sid) & ~o.flag.astype(str).str.contains(BAD)]
    s = g.set_index(col).value
    return s[~s.index.duplicated()].asfreq("D")


lat, lon = st.loc[se.loc[A, "station_key"], ["lat", "lon"]]
cpc = q.CPCField().series(lat, lon)  # indexed by CPC day
for col in ["date_raw", "date"]:
    a = get(A, col)
    P = {k: get(v, col) for k, v in PART.items()}
    pu = pd.concat(list(P.values()), axis=1).mean(axis=1)
    rows = []
    for y in range(a.index.year.min(), a.index.year.max() + 1):
        ay = a[str(y)]
        rec = dict(year=y, n=int(ay.notna().sum()), mean=ay.mean(), wetfreq=(ay >= 1).mean())
        for name, ref in [("cpc", None), ("pu_mojosari", P["pu_mojosari"]), ("pu_pudaksari", P["pu_pudaksari"]),
                          ("pu_mean4", pu)]:
            best = (np.nan, None)
            for k in range(-3, 4):
                if name == "cpc":
                    b = cpc.reindex(ay.index + pd.Timedelta(days=k - 1)).values
                else:
                    b = ref.reindex(ay.index + pd.Timedelta(days=k)).values
                r, n = q.pearson(ay.values, b)
                rec[f"{name}_r{k:+d}"] = r
                if np.isfinite(r) and (best[1] is None or r > best[0]):
                    best = (r, k)
            rec[f"{name}_best"] = best[1]
            rec[f"{name}_rbest"] = best[0]
        rows.append(rec)
    Y = pd.DataFrame(rows)
    Y.to_csv(f"{q.OUT}/mojosari_by_year_{col}.csv", index=False)
    print(f"\n=== {col}: r by year (lag k = partner day D+k; for CPC, k=0 means CPC D-1) ===")
    cols = ["year", "n", "mean", "wetfreq"] + [f"{n}_{s}" for n in ["cpc", "pu_mojosari", "pu_mean4"]
                                               for s in ["r-1", "r+0", "r+1", "best", "rbest"]]
    print(Y[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))

a = get(A); pm = get(PART["pu_mojosari"]); pp = get(PART["pu_pudaksari"])
print("\nBenchmark 1979-1994 (raw dates), r vs CPC at lags -1/0/+1 (0 = CPC D-1):")
for nm, x in [("agro", a), ("pu_mojosari", pm), ("pu_pudaksari", pp)]:
    xs = x["1979":"1994"]
    out = [q.pearson(xs.values, cpc.reindex(xs.index + pd.Timedelta(days=k - 1)).values)[0] for k in [-1, 0, 1]]
    print(f"  {nm:12s}: " + " ".join(f"{v:.2f}" for v in out))
for k in [-1, 0, 1]:
    xs = pm["1973":"1994"]
    print(f"  pu_mojosari vs pu_pudaksari lag {k:+d}: {q.pearson(xs.values, pp.reindex(xs.index + pd.Timedelta(days=k)).values)[0]:.2f}")


def agg(x, f):
    g = x.resample(f)
    return g.sum(min_count=1).where(g.count() >= {"MS": 25, "5D": 5, "10D": 9}[f])


print("\nAggregated r (month needs >= 25 values, pentad 5, dekad 9):")
cc = cpc.copy(); cc.index = cc.index + pd.Timedelta(days=1)  # CPC D-1 -> station D
for f in ["5D", "10D", "MS"]:
    xa = agg(a["1973":"1994"], f)
    res = [f"agro~{nm} {q.pearson(xa.values, agg(x['1973':'1994'], f).reindex(xa.index).values)[0]:.2f}"
           for nm, x in [("pu_moj", pm), ("pu_pud", pp)]]
    xa79 = agg(a["1979":"1994"], f)
    res.append(f"agro~cpc {q.pearson(xa79.values, cc['1979':'1994'].resample(f).sum().reindex(xa79.index).values)[0]:.2f}")
    xp = agg(pm["1979":"1994"], f)
    res.append(f"pu_moj~cpc {q.pearson(xp.values, cc['1979':'1994'].resample(f).sum().reindex(xp.index).values)[0]:.2f}")
    xq = agg(pm["1973":"1994"], f)
    res.append(f"pu_moj~pu_pud {q.pearson(xq.values, agg(pp['1973':'1994'], f).reindex(xq.index).values)[0]:.2f}")
    print(f"  {f:4s}: " + ", ".join(res))

print("\nScale, common days 1973-1994 (all three present):")
j = pd.concat([a, pm, pp], axis=1, keys=["agro", "pu_moj", "pu_pud"])["1973":"1994"].dropna()
print(f"  n={len(j)} mean mm/d: " + ", ".join(f"{c} {j[c].mean():.2f}" for c in j))
print("  wet-day freq >= 1 mm: " + ", ".join(f"{c} {(j[c] >= 1).mean():.3f}" for c in j))
print("  p95 / max: " + ", ".join(f"{c} {j[c].quantile(.95):.0f}/{j[c].max():.0f}" for c in j))
ann = pd.concat([x["1973":"1994"].resample("YS").agg(["sum", "count"]) for x in [a, pm, pp]], axis=1,
                keys=["agro", "pu_moj", "pu_pud"])
ann.index = ann.index.year
print("  annual totals (sum, count):"); print(ann.round(0).to_string())
v = a.dropna(); v = v[v > 0]
print(f"  agro value resolution: integer {np.isclose(v % 1, 0).mean():.2f}, x.5 {np.isclose(v % 1, .5).mean():.2f}, "
      f"multiple of 5 {np.isclose(v % 5, 0).mean():.2f}")
mc = pd.concat([x["1973":"1994"].groupby(x["1973":"1994"].index.month).mean() for x in [a, pm, pp]], axis=1,
               keys=["agro", "pu_moj", "pu_pud"])
print("  mean mm/day by calendar month:"); print(mc.T.round(1).to_string())

ser = q.series(); stt = q.stations()
r = ser[ser.variable == "RR"].merge(stt[["station_key", "lat", "lon"]], on="station_key")
r["d"] = q.haversine_km(lat, lon, r.lat.values, r.lon.values)
r = r[(r.d <= 150) & (r.series_id != A) & (r["first"] <= "1994-12-31") & (r["last"] >= "1973-01-01")]
dist = r.set_index("series_id").d
res = []
sub = o[o.series_id.isin(r.series_id) & ~o.flag.astype(str).str.contains(BAD)]
for sid, g in sub.groupby("series_id", observed=True):
    s = g.set_index("date_raw").value; s = s[~s.index.duplicated()]
    best = (-9, None, 0)
    for k in [-1, 0, 1]:
        rr, n = q.pearson(a.values, s.reindex(a.index + pd.Timedelta(days=k)).values)
        if n >= 1000 and np.isfinite(rr) and rr > best[0]:
            best = (rr, k, n)
    if best[1] is not None:
        res.append((sid, round(float(dist[sid]), 1), best[1], best[0], best[2]))
B = pd.DataFrame(res, columns=["series_id", "dist_km", "best_lag", "r", "n"]).sort_values("r", ascending=False)
B.to_csv(f"{q.OUT}/mojosari_best_partners.csv", index=False)
print("\nBest-matching series within 150 km (raw dates, >= 1000 common days):")
print(B.head(12).to_string(index=False, float_format=lambda x: f"{x:.2f}"))

# per-month best lag (raw dates) against the PU mean (posts with data that day), wet months only
print("\nPer-month best lag vs PU mean of 4 posts (raw dates; months with >= 25 pairs and >= 5 agro wet days;"
      " decided = best r exceeds runner-up by >= 0.1):")
a = get(A); P = {k: get(v) for k, v in PART.items()}
zy = pd.read_csv(f"{q.OUT}/jatim_zero_years.csv")  # from tools/qc_jatim_zero_years.py
for k, v in PART.items():
    bad = zy[zy.series_id == v].year.values
    P[k] = P[k].where(~P[k].index.year.isin(bad))  # mask zero-filled years
pu = pd.concat(list(P.values()), axis=1).mean(axis=1)
tally = []
for per, ay in a.groupby(a.index.to_period("M")):
    if ay.notna().sum() < 25 or (ay >= 1).sum() < 5:
        continue
    rs = {k: q.pearson(ay.values, pu.reindex(ay.index + pd.Timedelta(days=k)).values) for k in range(-2, 3)}
    rs = {k: v[0] for k, v in rs.items() if v[1] >= 25 and np.isfinite(v[0])}
    if len(rs) < 5:
        continue
    srt = sorted(rs.items(), key=lambda x: -x[1])
    tally.append((per.year, srt[0][0] if srt[0][1] - srt[1][1] >= 0.1 else "undecided"))
T = pd.crosstab(pd.Series([t[0] for t in tally], name="year"), pd.Series([str(t[1]) for t in tally], name="best_lag"))
T.loc["all"] = T.sum()
print(T.to_string())
