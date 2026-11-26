"""QC agro:MOJOSARI, question 2: is r low even at the best lag, compared with other East Java
station pairs at the same distance?

Baseline: every pair of RR series with stations in the East Java box (qc_mojosari_common.BOX),
different site_id, distance <= 50 km, >= 1000 common days in 1973-1994, pipeline dates
(column date), unmeasurable read as dry. Copies are removed: pairs whose values are equal on
>= 50% of common wet days at their best lag. Per pair: r at lag 0 and the best of lags -1..+1.
Distance bins 0-2, 2-5, 5-10, 10-15, 15-20, 20-30, 30-50 km: median and quartiles.
agro:MOJOSARI pairs are scored on its form dates at lag 0, at +1, and at its best of -2..+2,
and placed as a percentile in their bin (lag 0 baseline for lag 0, best-lag baseline for best).
Also: every pair in crosswalk_series.csv (whole build) where one side is an agro series and the
other is not: best_lag distribution (sign: agro day D vs partner day D+lag when agro is b).
Outputs: F:/temp/station/qc_mojosari/baseline_pairs.csv, baseline_bins.csv, baseline_agro_pairs.csv,
baseline_agro_network_lags.csv. Run: python tools/qc_mojosari_baseline.py
"""
import numpy as np
import pandas as pd

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
o = q.obs_ejava(); meta = q.rr_meta()
idx = pd.date_range("1973-01-01", "1994-12-31")
ids = [s for s in meta.series_id if s != q.A]
X = {}
for s in ids:
    x = q.daily(o, s, unmeasurable_as=0.0)
    x = x.reindex(idx)
    if x.notna().sum() >= 1000:
        X[s] = x.values.astype(float)
m = meta.set_index("series_id").loc[list(X)]
lat, lon = m.lat.values, m.lon.values
D = q.haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
keys = list(X)


def shifted(v, k):
    """value on day D+k aligned to day D."""
    out = np.full_like(v, np.nan)
    if k > 0:
        out[:-k] = v[k:]
    elif k < 0:
        out[-k:] = v[:k]
    else:
        out = v.copy()
    return out


rows = []
for i in range(len(keys)):
    for j in range(i + 1, len(keys)):
        if D[i, j] > 50 or m.site_id.iloc[i] == m.site_id.iloc[j]:
            continue
        a = X[keys[i]]
        rs, eqs, ns = {}, {}, {}
        for k in (-1, 0, 1):
            b = shifted(X[keys[j]], k)
            ok = np.isfinite(a) & np.isfinite(b)
            ns[k] = int(ok.sum())
            if ns[k] < 1000:
                rs[k] = np.nan; continue
            rs[k] = float(np.corrcoef(a[ok], b[ok])[0, 1])
            w = ok & ((a > 0) | (b > 0))
            eqs[k] = float((a[w] == b[w]).mean()) if w.any() else np.nan
        if not np.isfinite(rs[0]):
            continue
        kb = max((k for k in rs if np.isfinite(rs[k])), key=lambda k: rs[k])
        rows.append(dict(a=keys[i], b=keys[j], src_a=m.source.iloc[i], src_b=m.source.iloc[j], d_km=D[i, j],
                         n=ns[0], r0=rs[0], r_best=rs[kb], best_lag=kb, eq_best=eqs.get(kb, np.nan)))
P = pd.DataFrame(rows)
P["is_copy"] = P.eq_best >= 0.5
P.to_csv(f"{q.OUT}/baseline_pairs.csv", index=False)
print(f"pairs within 50 km: {len(P)}, copies removed: {int(P.is_copy.sum())}")
B = P[~P.is_copy].copy()
bins = [0, 2, 5, 10, 15, 20, 30, 50]
B["bin"] = pd.cut(B.d_km, bins)
S = B.groupby("bin", observed=True).agg(n_pairs=("r0", "size"), r0_q25=("r0", lambda x: x.quantile(.25)),
                                         r0_median=("r0", "median"), r0_q75=("r0", lambda x: x.quantile(.75)),
                                         rbest_median=("r_best", "median"), share_best_lag0=("best_lag", lambda x: (x == 0).mean()))
S.to_csv(f"{q.OUT}/baseline_bins.csv")
print("\n=== East Java baseline, pairs of distinct sites, copies removed (pipeline dates) ===")
print(S.to_string(float_format=lambda x: f"{x:.2f}"))
print("\nsame, excluding agro sources:")
Bn = B[(B.src_a != "agro") & (B.src_b != "agro")]
print(Bn.groupby("bin", observed=True).r0.describe()[["count", "25%", "50%", "75%"]].to_string(float_format=lambda x: f"{x:.2f}"))

# agro:MOJOSARI pairs
a0 = q.daily(o, q.A, col="date_raw").reindex(idx).values.astype(float)
mm = meta.set_index("series_id")
la, lo_ = mm.loc[q.A, ["lat", "lon"]]
rows = []
for s in keys:
    d = float(q.haversine_km(la, lo_, mm.loc[s, "lat"], mm.loc[s, "lon"]))
    if d > 50:
        continue
    rk = {}
    for k in range(-2, 3):
        b = shifted(X[s], k); ok = np.isfinite(a0) & np.isfinite(b)
        rk[k] = float(np.corrcoef(a0[ok], b[ok])[0, 1]) if ok.sum() >= 1000 else np.nan
    if not np.isfinite(rk[0]):
        continue
    kb = max(rk, key=lambda k: np.nan_to_num(rk[k], nan=-9))
    bn = pd.cut([d], bins)[0]
    ref = B[B.bin == bn]
    rows.append(dict(partner=s, d_km=d, r0=rk[0], r_plus1=rk[1], best_lag=kb, r_best=rk[kb],
                     pct_r0_in_bin=float((ref.r0 < rk[0]).mean()), pct_rbest_in_bin=float((ref.r_best < rk[kb]).mean()),
                     bin_median_r0=float(ref.r0.median()), bin_median_rbest=float(ref.r_best.median())))
AP = pd.DataFrame(rows).sort_values("d_km")
AP.to_csv(f"{q.OUT}/baseline_agro_pairs.csv", index=False)
print("\n=== agro:MOJOSARI (form dates) vs every series within 50 km: percentile within the distance bin ===")
print(AP.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
print(f"\nmedian percentile of agro pairs: r0 {AP.pct_r0_in_bin.median():.2f}, r at its best lag {AP.pct_rbest_in_bin.median():.2f}"
      f" (n pairs {len(AP)}); within 30 km: r0 {AP[AP.d_km <= 30].pct_r0_in_bin.median():.2f},"
      f" best {AP[AP.d_km <= 30].pct_rbest_in_bin.median():.2f}")

# agro network lags (whole build, crosswalk_series)
cw = pd.read_csv(f"{q.COMP}/crosswalk_series.csv")
ag_a = cw.series_a.str.startswith("agro:"); ag_b = cw.series_b.str.startswith("agro:")
x = cw[(ag_a ^ ag_b) & (cw.n_overlap >= 1000) & (cw.r_best >= 0.2)].copy()
x["agro"] = np.where(ag_b[x.index], x.series_b, x.series_a)
x["lag_agro"] = np.where(ag_b[x.index], x.best_lag, -x.best_lag)   # agro day D vs partner day D+lag
x.to_csv(f"{q.OUT}/baseline_agro_network_lags.csv", index=False)
print("\n=== agro series vs non-agro partners in crosswalk_series (n >= 1000, r_best >= 0.2): lag (agro D vs partner D+lag) ===")
print(pd.crosstab(x.agro, x.lag_agro).to_string())
