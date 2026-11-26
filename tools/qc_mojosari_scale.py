"""QC agro:MOJOSARI, question 4 (scale and units) and accumulations / outliers.

Compares agro:MOJOSARI (form dates) with the 5 neighbours of tools/qc_mojosari_lag.py and CPC-UNI:
  - annual totals on days where agro and >= 2 neighbours report (neighbour mean), ratio per year
  - mean mm/day by calendar month, ratio agro / neighbour mean
  - wet-day frequency (>= 0.5 and >= 1 mm), wet-day intensity quantiles, maxima
  - value resolution: share integer, last-digit histogram of positive values, multiples of 5/10
  - monthly ratio agro / neighbour mean: months near x10 or x0.1 or inch scale
  - values >= 100 mm: neighbours and CPC on D-1..D+2
  - accumulation candidates: value after >= 1 missing day vs the station wet-day p90
Outputs: F:/temp/station/qc_mojosari/scale_*.csv. Run: python tools/qc_mojosari_scale.py
"""
import numpy as np
import pandas as pd

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300); pd.set_option("display.max_columns", 40)
o = q.obs_ejava(); meta = q.rr_meta().set_index("series_id")
lat, lon = meta.loc[q.A, ["lat", "lon"]]
a = q.daily(o, q.A, col="date_raw")["1973":"1994"]
C = pd.read_csv(f"{q.OUT}/lag_neighbour_candidates.csv")
NB = C.drop_duplicates("site_id").head(5).series_id.tolist()
N = pd.concat({s.split(":")[1]: q.daily(o, s, unmeasurable_as=0.0) for s in NB}, axis=1).reindex(a.index)
nbmean = N.mean(axis=1).where(N.notna().sum(axis=1) >= 2)
cpc = q.CPCField().series(lat, lon).reindex(a.index)

# annual totals on common days
J = pd.DataFrame({"agro": a, "nbr_mean": nbmean, "cpc": cpc})
rows = []
for y, g in J.groupby(J.index.year):
    c = g.dropna(subset=["agro", "nbr_mean"])
    rows.append(dict(year=y, n_agro=int(g.agro.notna().sum()), n_common=len(c), agro=c.agro.sum(), nbr_mean=c.nbr_mean.sum(),
                     ratio=c.agro.sum() / c.nbr_mean.sum() if c.nbr_mean.sum() else np.nan,
                     agro_full_year=g.agro.sum() if g.agro.notna().sum() >= 330 else np.nan,
                     cpc_same_days=g.dropna(subset=["agro"]).cpc.sum(min_count=1)))
Ann = pd.DataFrame(rows)
Ann.to_csv(f"{q.OUT}/scale_annual.csv", index=False)
print("=== annual totals (mm) on days with agro and >= 2 neighbours; CPC on agro days (1979+) ===")
print(Ann.to_string(index=False, float_format=lambda x: f"{x:.0f}" if abs(x) > 5 else f"{x:.2f}"))
c = J.dropna(subset=["agro", "nbr_mean"])
print(f"all years: agro {c.agro.mean():.2f} mm/d, nbr mean {c.nbr_mean.mean():.2f}, ratio {c.agro.sum() / c.nbr_mean.sum():.2f}")
cc = J["1979":].dropna()
print(f"1979+: agro {cc.agro.mean():.2f}, cpc {cc.cpc.mean():.2f}, ratio agro/cpc {cc.agro.sum() / cc.cpc.sum():.2f}")
print("ratio agro / each neighbour (on agro-nbr_mean common days, neighbour present):",
      {s: round(c.agro[N.loc[c.index, s].notna()].sum() / N.loc[c.index, s].dropna().sum(), 2) for s in N})

# monthly climatology
Mc = c.groupby(c.index.month)[["agro", "nbr_mean"]].mean()
Mc["ratio"] = Mc.agro / Mc.nbr_mean
Mc.to_csv(f"{q.OUT}/scale_month_climatology.csv")
print("\n=== mean mm/day by calendar month (common days) ===")
print(Mc.T.to_string(float_format=lambda x: f"{x:.2f}"))

# distribution
rows = []
for name, s in [("agro", a)] + [(k, N[k]) for k in N]:
    v = s.dropna(); w = v[v >= 1]
    pos = v[v > 0]
    ld = (pos.round().astype(int) % 10)
    rows.append(dict(series=name, n=len(v), wet05=(v >= 0.5).mean(), wet1=(v >= 1).mean(), share_0_lt1=((v > 0) & (v < 1)).mean(),
                     mean_wet=w.mean(), p50=w.quantile(.5), p90=w.quantile(.9), p99=w.quantile(.99), max=v.max(),
                     int_share=np.isclose(pos % 1, 0).mean(), mult5=np.isclose(pos % 5, 0).mean(), mult10=np.isclose(pos % 10, 0).mean(),
                     **{f"ld{d}": (ld == d).mean() for d in range(10)}))
Dd = pd.DataFrame(rows)
Dd.to_csv(f"{q.OUT}/scale_distribution.csv", index=False)
print("\n=== distribution (each series over its own 1973-1994 days); ld = last digit share of positive values ===")
print(Dd.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
pos5 = a.dropna(); pos5 = pos5[pos5 >= 10]
ld5 = (pos5.round().astype(int) % 10).value_counts().sort_index()
print("agro last digit of values >= 10 mm:", (ld5 / ld5.sum()).round(3).to_dict(), "n", len(pos5))
for k in N:
    p = N[k].dropna(); p = p[p >= 10]
    l = (p.round().astype(int) % 10).value_counts(normalize=True).sort_index()
    print(f"  {k} last digit of values >= 10 mm: share 0 = {l.get(0, 0):.3f}, share 5 = {l.get(5, 0):.3f}, n {len(p)}")

# monthly ratio, units / tenfold
mon = pd.DataFrame({"agro": a, "nbr": nbmean}).dropna()
g = mon.groupby(mon.index.to_period("M"))
Mr = pd.DataFrame({"n": g.size(), "agro": g.agro.sum(), "nbr": g.nbr.sum()})
Mr = Mr[Mr.n >= 25]
Mr["ratio"] = Mr.agro / Mr.nbr
wet = Mr[Mr.nbr >= 50]
print(f"\n=== monthly totals, months with >= 25 common days and nbr >= 50 mm: n {len(wet)} ===")
print("ratio quantiles:", wet.ratio.quantile([.05, .25, .5, .75, .95]).round(2).to_dict())
print("months with ratio >= 3 or <= 0.33:")
print(wet[(wet.ratio >= 3) | (wet.ratio <= 0.33)].round(1).to_string())
print("months near x10 (>= 6) or x0.1 (<= 0.17):", int(((wet.ratio >= 6) | (wet.ratio <= 0.17)).sum()))
print(f"monthly r (common-day totals) agro vs nbr mean: {q.pearson(Mr.agro, Mr.nbr)[0]:.2f}")
for k in N:
    oth = N.drop(columns=k)
    mm = pd.DataFrame({"x": N[k], "o": oth.mean(axis=1).where(oth.notna().sum(axis=1) >= 2)}).dropna()
    gg = mm.groupby(mm.index.to_period("M")); t = pd.DataFrame({"n": gg.size(), "x": gg.x.sum(), "o": gg.o.sum()})
    t = t[t.n >= 25]
    print(f"  monthly r {k} vs mean of other 4: {q.pearson(t.x, t.o)[0]:.2f}")
Mr.to_csv(f"{q.OUT}/scale_monthly_ratio.csv")

# large values
print("\n=== agro values >= 100 mm with neighbours (max) and CPC on D-1..D+2 ===")
rows = []
p = a[a > 0]
for d in a[a >= 100].index:
    rec = dict(date=d.date(), agro=a[d])
    for k in range(-1, 3):
        dd = d + pd.Timedelta(days=k)
        rec[f"nbmax{k:+d}"] = N.loc[dd].max() if dd in N.index else np.nan
        rec[f"cpc{k:+d}"] = cpc.get(dd, np.nan)
    rec["rank_pct"] = float((p < a[d]).mean())
    rows.append(rec)
Lg = pd.DataFrame(rows)
Lg.to_csv(f"{q.OUT}/scale_large_values.csv", index=False)
print(Lg.to_string(index=False, float_format=lambda x: f"{x:.0f}"))
p99 = a[a >= 1].quantile(.99)
print(f"agro wet-day p99 {p99:.0f} mm; neighbours max: {N.max().round(0).to_dict()}")

# accumulation candidates
miss = a.isna()
prev_run = miss.groupby((~miss).cumsum()).cumsum().shift(1).fillna(0)
p90 = a[a >= 1].quantile(.9)
after = (prev_run >= 1) & a.notna()
acc = a[after & (a >= p90)]
nm = a[(prev_run == 0) & a.notna()]
print(f"\n=== accumulations: agro >= p90 of wet days ({p90:.0f} mm) right after >= 1 missing day ===")
print(f"days right after a missing run: {int(after.sum())}; of those >= p90: {len(acc)}"
      f" ({len(acc) / max(1, int(after.sum())):.3f}); base rate on other days: {(nm >= p90).mean():.3f}")
A2 = pd.DataFrame({"date": acc.index.date, "value": acc.values, "missing_before": prev_run[acc.index].values,
                   "nbr_mean_same_day": nbmean.reindex(acc.index).values,
                   "nbr_sum_over_gap": [nbmean[d - pd.Timedelta(days=int(n)):d].sum() for d, n in zip(acc.index, prev_run[acc.index])]})
A2.to_csv(f"{q.OUT}/scale_accumulation_candidates.csv", index=False)
print(A2.to_string(index=False, float_format=lambda x: f"{x:.0f}"))
