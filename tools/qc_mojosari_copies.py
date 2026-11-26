"""QC agro:MOJOSARI, question 5 (data quality): copies, constant runs, zero runs, filled values.

  1. within-series copies: every pair of calendar months (>= 5 wet days in one of them) compared
     day-of-month by day-of-month at shifts -3..+3; fraction equal on the union of wet days;
  2. copies from another station: per year, fraction of equal values on the union of wet days
     (>= 20 such days) at shifts -3..+3 against every RR series in the East Java box and every
     agro series in the build (agro sheets were sometimes filed under the wrong station, F55);
  3. constant runs: the same positive value on >= 3 consecutive days;
  4. zero runs: exact-zero runs >= 10 days that touch Nov-Apr, with the neighbour-mean total
     during the run; months with agro total 0 while the neighbour mean has >= 50 mm.
Neighbours: the 5 of tools/qc_mojosari_lag.py. Agro on form dates (date_raw).
Outputs: F:/temp/station/qc_mojosari/copies_*.csv. Run: python tools/qc_mojosari_copies.py
"""
import os

import numpy as np
import pandas as pd

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
o = q.obs_ejava()
a = q.daily(o, q.A, col="date_raw")["1973":"1994"]
C = pd.read_csv(f"{q.OUT}/lag_neighbour_candidates.csv")
NB = C.drop_duplicates("site_id").head(5).series_id.tolist()
N = pd.concat([q.daily(o, s, unmeasurable_as=0.0) for s in NB], axis=1, keys=NB).reindex(a.index)
nbmean = N.mean(axis=1).where(N.notna().sum(axis=1) >= 2)

# 1. within-series month copies
ad = a.dropna()
months = {str(p): g for p, g in ad.groupby(ad.index.to_period("M"))}
vec = {}
for p, g in months.items():
    v = np.full(31, np.nan); v[g.index.day.values - 1] = g.values; vec[p] = v
keys = [k for k in vec if np.nansum(vec[k] >= 1) >= 5]
rows = []
allk = list(vec)
for i, k1 in enumerate(keys):
    for k2 in allk:
        if k2 <= k1 and k2 in keys:
            continue
        if k1 == k2:
            continue
        for s in range(-3, 4):
            x = vec[k1]; y = np.roll(vec[k2], -s)
            if s > 0:
                y[-s:] = np.nan
            elif s < 0:
                y[:-s] = np.nan
            ok = np.isfinite(x) & np.isfinite(y) & ((x > 0) | (y > 0))
            if ok.sum() >= 5:
                f = float((x[ok] == y[ok]).mean())
                if f >= 0.6:
                    rows.append(dict(month_a=k1, month_b=k2, shift=s, n_wet_union=int(ok.sum()), equal_frac=f))
W = pd.DataFrame(rows, columns=["month_a", "month_b", "shift", "n_wet_union", "equal_frac"])
W.to_csv(f"{q.OUT}/copies_within_series.csv", index=False)
print(f"=== within-series: month pairs with >= 60% equal wet values (>= 5 wet days): {len(W)} ===")
print(W.sort_values("equal_frac", ascending=False).head(20).to_string(index=False))

# 2. copies from other stations
p = os.path.join(q.CACHE, "obs_agro_all.pkl")
if os.path.exists(p) and os.path.getmtime(p) > os.path.getmtime(f"{q.COMP}/observations_RR.csv.gz"):
    ag = pd.read_pickle(p)
else:
    ag = pd.concat([c[c.series_id.str.startswith("agro:")] for c in
                    pd.read_csv(f"{q.COMP}/observations_RR.csv.gz", chunksize=2_000_000, low_memory=False, dtype={"flag": str, "label": str})])
    ag["date"] = pd.to_datetime(ag["date"]); ag["date_raw"] = pd.to_datetime(ag["date_raw"]); ag.to_pickle(p)
others = {s: q.daily(o, s, col="date_raw", unmeasurable_as=0.0) for s in o.series_id.unique() if s != q.A}
others.update({s: q.daily(ag, s, col="date_raw", unmeasurable_as=0.0) for s in ag.series_id.unique() if s != q.A})
rows = []
for y in sorted(set(ad.index.year)):
    x = ad[ad.index.year == y]
    for sid, s in others.items():
        if s.empty:
            continue
        best = (0, None, 0)
        for k in range(-3, 4):
            b = s.reindex(x.index + pd.Timedelta(days=k)).values
            ok = np.isfinite(b) & ((x.values > 0) | (b > 0))
            if ok.sum() >= 20:
                f = float((x.values[ok] == b[ok]).mean())
                if f > best[0]:
                    best = (f, k, int(ok.sum()))
        if best[1] is not None:
            rows.append(dict(year=y, other=sid, equal_frac=best[0], shift=best[1], n_wet_union=best[2]))
X = pd.DataFrame(rows)
X.to_csv(f"{q.OUT}/copies_other_stations.csv", index=False)
print("\n=== other stations: highest equal fraction on union of wet days per year (top 3 per year) ===")
print(X.sort_values(["year", "equal_frac"], ascending=[True, False]).groupby("year").head(3).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
print("max over all years and series:", X.equal_frac.max().round(3), "; pairs >= 0.5:", int((X.equal_frac >= 0.5).sum()))

# 3. constant runs of a positive value
v = a.values; rows = []
i = 0
while i < len(v):
    if np.isfinite(v[i]) and v[i] > 0:
        j = i
        while j + 1 < len(v) and v[j + 1] == v[i]:
            j += 1
        if j - i + 1 >= 3:
            rows.append(dict(start=a.index[i].date(), days=j - i + 1, value=v[i]))
        i = j + 1
    else:
        i += 1
K = pd.DataFrame(rows, columns=["start", "days", "value"])
K.to_csv(f"{q.OUT}/copies_constant_runs.csv", index=False)
print(f"\n=== constant positive runs >= 3 days: {len(K)} ===")
print(K.to_string(index=False))
pairs = (a.shift(1) == a) & (a > 0)
print(f"days equal to the day before and > 0: {int(pairs.sum())} of {int((a > 0).sum())} wet days")
for s in NB:
    x = q.daily(o, s, unmeasurable_as=0.0)["1973":"1994"]
    pp = (x.shift(1) == x) & (x > 0)
    print(f"  {s}: {int(pp.sum())} of {int((x > 0).sum())}")

# 4. zero runs and zero months
z = (a == 0)
grp = (z != z.shift()).cumsum()
rows = []
for _, g in a[z].groupby(grp[z]):
    if len(g) < 10:
        continue
    ms = set(g.index.month)
    if not ms & {11, 12, 1, 2, 3, 4}:
        continue
    nb = nbmean.reindex(g.index)
    rows.append(dict(start=g.index[0].date(), end=g.index[-1].date(), days=len(g), wet_season_days=int(g.index.month.isin([11, 12, 1, 2, 3, 4]).sum()),
                     nbr_total=float(nb.sum()), nbr_days_ge5=int((nb >= 5).sum()), nbr_cover=int(nb.notna().sum())))
Zr = pd.DataFrame(rows)
Zr.to_csv(f"{q.OUT}/copies_zero_runs.csv", index=False)
print("\n=== exact-zero runs >= 10 days touching Nov-Apr ===")
print(Zr.sort_values("nbr_total", ascending=False).to_string(index=False, float_format=lambda x: f"{x:.0f}"))
mon = pd.DataFrame({"agro": a, "nbr": nbmean}).dropna()
g = mon.groupby(mon.index.to_period("M"))
T = pd.DataFrame({"n": g.size(), "agro": g.agro.sum(), "nbr": g.nbr.sum(), "nbr_days_ge5": g.nbr.apply(lambda s: int((s >= 5).sum()))})
Zm = T[(T.agro == 0) & (T.nbr >= 50) & (T.n >= 25)]
Zm.to_csv(f"{q.OUT}/copies_zero_months.csv")
print("\n=== months with agro total 0 while neighbour mean >= 50 mm ===")
print(Zm.to_string(float_format=lambda x: f"{x:.0f}"))
# how often do the neighbours themselves show such a month (each vs the mean of the other four)?
cnt = {}
for s in N.columns:
    oth = N.drop(columns=s)
    mm = pd.DataFrame({"x": N[s], "o": oth.mean(axis=1).where(oth.notna().sum(axis=1) >= 2)}).dropna()
    gg = mm.groupby(mm.index.to_period("M"))
    t = pd.DataFrame({"n": gg.size(), "x": gg.x.sum(), "o": gg.o.sum()})
    t = t[t.n >= 25]
    cnt[s] = (int(((t.x == 0) & (t.o >= 50)).sum()), len(t))
print("neighbours, months with total 0 while the other four have >= 50 mm (count, months):", cnt)

# calibration of zero runs: each neighbour vs the mean of the other four, same rule
print("\n=== zero runs >= 10 days touching Nov-Apr with the reference mean >= 75 mm during the run ===")
def zero_runs(x, ref):
    zz = (x == 0); gp = (zz != zz.shift()).cumsum(); out = []
    for _, g in x[zz].groupby(gp[zz]):
        if len(g) >= 10 and set(g.index.month) & {11, 12, 1, 2, 3, 4}:
            out.append(float(ref.reindex(g.index).sum()))
    return out
za = zero_runs(a, nbmean)
print(f"  agro: {sum(t >= 75 for t in za)} runs (of {len(za)}), agro years with data {a.notna().sum() / 365.25:.1f}")
for s in N.columns:
    oth = N.drop(columns=s)
    om = oth.mean(axis=1).where(oth.notna().sum(axis=1) >= 2)
    zs = zero_runs(N[s], om)
    print(f"  {s}: {sum(t >= 75 for t in zs)} runs (of {len(zs)}), years with data {N[s].notna().sum() / 365.25:.1f}")
