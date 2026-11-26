"""QC agro:MOJOSARI, question 1 (day label): lag-dependent agreement per year and per month.

Agro variants (all on the date written in the form, i.e. date_raw):
  comp    the compiled series (METKLIM file wins on conflicts, so 1991-92 and parts of 1988-89
          are the METKLIM version)
  mjs     MOJOSARI/MJS73-94.XLS only (station-folder workbook), from qc_mojosari_raw.py cache
References: CPC-UNI at the agro cell (target convention: station D = CPC D-1), the 5 best
neighbours within 30 km (distinct sites, >= 1000 common days 1973-1994, ranked by best-lag r
with comp), and their daily mean (>= 2 present). Neighbours use the pipeline date (column
date), unmeasurable read as dry. Lag k: agro day D vs reference day D+k.
Outputs (F:/temp/station/qc_mojosari/):
  lag_by_year.csv       r and hit rate per year x lag x reference x variant
  lag_bootstrap.csv     per year: share of month-block bootstrap resamples won by each lag (vs nbr mean)
  lag_by_month.csv      per month: r at each lag vs nbr mean and vs CPC
  lag_segments.csv      piecewise-constant offset fitted by Viterbi over months (switch penalty)
  lag_version_blocks.csv  the blocks where MJS and METKLIM differ by one day: which fits better
Run: python tools/qc_mojosari_lag.py
"""
import numpy as np
import pandas as pd

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400); pd.set_option("display.max_columns", 60)
LAGS = range(-2, 3)
rng = np.random.default_rng(42)
o = q.obs_ejava(); meta = q.rr_meta().set_index("series_id")
lat, lon = meta.loc[q.A, ["lat", "lon"]]
comp = q.daily(o, q.A, col="date_raw")["1973":"1994"]
V = pd.read_pickle(f"{q.CACHE}/raw_versions.pkl")
mjs = pd.concat([s for (f, sn, y), s in V.items() if f.startswith("MOJOSARI/")]).sort_index()
mjs = mjs[~mjs.index.duplicated()].asfreq("D")
met = pd.concat([s for (f, sn, y), s in V.items() if f.startswith("METKLIM/")]).sort_index()
met = met[~met.index.duplicated()].asfreq("D")
cpc = q.CPCField().series(lat, lon)

# neighbour choice
meta["d_km"] = q.haversine_km(lat, lon, meta.lat.values, meta.lon.values)
cand = meta[(meta.d_km <= 30) & (meta.source != "agro")]
rows = []
for sid in cand.index:
    s = q.daily(o, sid, unmeasurable_as=0.0)
    if s.empty:
        continue
    best = max(((q.pearson(comp.values, q.lagged(s, comp.index, k)), k) for k in LAGS), key=lambda x: np.nan_to_num(x[0][0], nan=-9))
    (r, n), k = best
    rows.append(dict(series_id=sid, site_id=cand.loc[sid, "site_id"], name=cand.loc[sid, "name"], d_km=cand.loc[sid, "d_km"],
                     elev_m=cand.loc[sid, "elev_m"], n=n, best_lag=k, r_best=r,
                     r_lag0=q.pearson(comp.values, q.lagged(s, comp.index, 0))[0]))
C = pd.DataFrame(rows)
C = C[C.n >= 1000].sort_values("r_best", ascending=False)
C.to_csv(f"{q.OUT}/lag_neighbour_candidates.csv", index=False)
print("=== neighbours within 30 km, >= 1000 common days with comp (1973-1994) ===")
print(C.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
NB = C.drop_duplicates("site_id").head(5).series_id.tolist()
print("chosen:", NB)
N = {sid: q.daily(o, sid, unmeasurable_as=0.0) for sid in NB}
NB_raw = {sid: q.daily(o, sid, col="date_raw", unmeasurable_as=0.0) for sid in NB}
nbm = pd.concat(N.values(), axis=1)
nbmean = nbm.mean(axis=1).where(nbm.notna().sum(axis=1) >= 2)
nbr = pd.concat(NB_raw.values(), axis=1)
nbmean_raw = nbr.mean(axis=1).where(nbr.notna().sum(axis=1) >= 2)
REFS = {"cpc": cpc, "nbr_mean": nbmean, "nbr_mean_rawdates": nbmean_raw, **{f"nb:{k}": v for k, v in N.items()}}

# per year
rows = []
for vname, a in [("comp", comp), ("mjs", mjs)]:
    for y in range(1973, 1995):
        ay = a[a.index.year == y].dropna()
        if len(ay) < 60:
            continue
        for rn, ref in REFS.items():
            for k in LAGS:
                b = q.lagged(ref, ay.index, k)
                r, n = q.pearson(ay.values, b)
                h, h2 = q.hit_rate(ay.values, b)
                rows.append(dict(variant=vname, year=y, ref=rn, lag=k, r=r, n=n, hit=h, hit_rev=h2))
Y = pd.DataFrame(rows)
Y.to_csv(f"{q.OUT}/lag_by_year.csv", index=False)
Y["nb"] = Y.ref.str.startswith("nb:")
ind = Y[Y.nb].groupby(["variant", "year", "lag"]).agg(r=("r", "mean"), hit=("hit", "mean")).reset_index().assign(ref="nb5_mean_of_r")
Z = pd.concat([Y[~Y.nb], ind])
for vname in ["comp", "mjs"]:
    for metric in ["r", "hit"]:
        P = Z[Z.variant == vname].pivot_table(index="year", columns=["ref", "lag"], values=metric)
        P = P[[c for c in P.columns if c[0] in ("cpc", "nbr_mean", "nb5_mean_of_r")]]
        print(f"\n=== {vname}: {metric} by year and lag (agro D vs reference D+k) ===")
        print(P.to_string(float_format=lambda x: f"{x:.2f}"))
        best = {ref: P[ref].idxmax(axis=1) for ref in ("cpc", "nbr_mean", "nb5_mean_of_r")}
        print(f"best lag by {metric}:"); print(pd.DataFrame(best).T.to_string())

# all-years summary
rows = []
for vname, a in [("comp", comp), ("mjs", mjs)]:
    for rn in ["cpc", "nbr_mean", "nbr_mean_rawdates"]:
        for k in LAGS:
            ay = a["1979":] if rn == "cpc" else a
            b = q.lagged(REFS[rn], ay.index, k)
            r, n = q.pearson(ay.values, b); h, h2 = q.hit_rate(ay.values, b)
            rows.append(dict(variant=vname, ref=rn, lag=k, r=r, n=n, hit=h, hit_rev=h2))
S = pd.DataFrame(rows)
S.to_csv(f"{q.OUT}/lag_summary.csv", index=False)
print("\n=== all years: r / hit by lag ===")
print(S.pivot_table(index=["variant", "ref"], columns="lag", values=["r", "hit"]).to_string(float_format=lambda x: f"{x:.3f}"))

print("\n=== neighbour pairs, r by lag (pipeline dates, 1973-1994) ===")
for i in range(len(NB)):
    for j in range(i + 1, len(NB)):
        x = N[NB[i]]["1973":"1994"]
        print(f"  {NB[i]:28s} {NB[j]:28s} " + " ".join(f"{k:+d}:{q.pearson(x.values, q.lagged(N[NB[j]], x.index, k))[0]:.2f}" for k in LAGS))
for sid in NB:
    x = N[sid]["1979":"1994"]
    print(f"  {sid:28s} vs CPC " + " ".join(f"{k:+d}:{q.pearson(x.values, q.lagged(cpc, x.index, k))[0]:.2f}" for k in LAGS))

# bootstrap by month blocks vs nbr mean
rows = []
for vname, a in [("comp", comp), ("mjs", mjs)]:
    for y in range(1973, 1995):
        ay = a[a.index.year == y].dropna()
        if len(ay) < 60:
            continue
        months = [g for _, g in ay.groupby(ay.index.month) if len(g) >= 10]
        B = {k: [(g.values, q.lagged(nbmean, g.index, k)) for g in months] for k in LAGS}
        wins = {k: 0 for k in LAGS}
        for _ in range(300):
            pick = rng.integers(0, len(months), len(months))
            rs = {}
            for k in LAGS:
                xa = np.concatenate([B[k][p][0] for p in pick]); xb = np.concatenate([B[k][p][1] for p in pick])
                rs[k] = q.pearson(xa, xb)[0]
            wins[max(rs, key=lambda kk: np.nan_to_num(rs[kk], nan=-9))] += 1
        rows.append(dict(variant=vname, year=y, n_months=len(months), **{f"win{k:+d}": wins[k] / 300 for k in LAGS}))
Bt = pd.DataFrame(rows)
Bt.to_csv(f"{q.OUT}/lag_bootstrap.csv", index=False)
print("\n=== share of 300 month-block bootstrap resamples won by each lag (vs nbr mean) ===")
print(Bt.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

# per month and Viterbi segmentation
rows = []
for vname, a in [("comp", comp), ("mjs", mjs)]:
    ad = a.dropna()
    for per, g in ad.groupby(ad.index.to_period("M")):
        rec = dict(variant=vname, month=str(per), n=len(g), wet=int((g >= 1).sum()))
        for rn in ["nbr_mean", "cpc"]:
            for k in LAGS:
                r, n = q.pearson(g.values, q.lagged(REFS[rn], g.index, k))
                rec[f"{rn}_r{k:+d}"] = r
                rec[f"{rn}_n{k:+d}"] = n
        rows.append(rec)
M = pd.DataFrame(rows)
M.to_csv(f"{q.OUT}/lag_by_month.csv", index=False)


def zscore(X, ref, k):
    r = X[f"{ref}_r{k:+d}"].clip(-0.99, 0.99).fillna(0).values
    n = X[f"{ref}_n{k:+d}"].fillna(0).values
    return np.arctanh(r) * np.sqrt(np.maximum(n - 3, 1))


def viterbi(Mv, ref, penalty):
    """Months with >= 3 agro wet days and >= 20 pairs. Score = Fisher z * sqrt(n-3) of r at
    each lag; switching lag costs `penalty`. Returns months with the fitted lag."""
    ok = (Mv.wet >= 3) & (Mv[f"{ref}_n+0"] >= 20)
    X = Mv[ok].reset_index(drop=True)
    L = list(LAGS)
    sc = np.column_stack([zscore(X, ref, k) for k in L])
    D = np.zeros_like(sc); bp = np.zeros(sc.shape, int)
    D[0] = sc[0]
    for t in range(1, len(X)):
        for j in range(len(L)):
            c_ = D[t - 1] - penalty * (np.arange(len(L)) != j)
            bp[t, j] = int(np.argmax(c_)); D[t, j] = c_.max() + sc[t, j]
    path = [int(np.argmax(D[-1]))]
    for t in range(len(X) - 1, 0, -1):
        path.append(bp[t, path[-1]])
    path = path[::-1]
    X["lag"] = [L[j] for j in path]
    X["z_path"] = sc[np.arange(len(X)), path]
    X["z_lag0"] = sc[:, L.index(0)]; X["z_lag1"] = sc[:, L.index(1)]
    return X


segs = []
for vname in ["comp", "mjs"]:
    for ref in ["nbr_mean", "cpc"]:
        for pen in [3.0, 6.0]:
            X = viterbi(M[M.variant == vname].reset_index(drop=True), ref, pen)
            X["grp"] = (X.lag != X.lag.shift()).cumsum()
            for _, g in X.groupby("grp"):
                segs.append(dict(variant=vname, ref=ref, penalty=pen, start=g.month.iloc[0], end=g.month.iloc[-1],
                                 n_months=len(g), lag=int(g.lag.iloc[0]),
                                 z_gain_vs_lag0=float((g.z_path - g.z_lag0).sum()),
                                 z_gain_vs_lag1=float((g.z_path - g.z_lag1).sum())))
G = pd.DataFrame(segs)
G.to_csv(f"{q.OUT}/lag_segments.csv", index=False)
print("\n=== Viterbi offset segments over months (score = Fisher z x sqrt(n-3); switch penalty) ===")
print(G.to_string(index=False, float_format=lambda x: f"{x:.1f}"))

blocks = [("1988-01-01", "1988-01-31"), ("1989-06-01", "1989-12-31"), ("1991-01-01", "1991-09-30"), ("1992-01-01", "1992-09-30")]
rows = []
for s0, s1 in blocks:
    for vname, a in [("mjs", mjs), ("metklim", met)]:
        g = a[s0:s1].dropna()
        for rn in ["nbr_mean", "cpc"]:
            rec = dict(block=f"{s0}..{s1}", version=vname, ref=rn, n=len(g))
            for k in LAGS:
                rec[f"r{k:+d}"] = q.pearson(g.values, q.lagged(REFS[rn], g.index, k))[0]
            rows.append(rec)
VB = pd.DataFrame(rows)
VB.to_csv(f"{q.OUT}/lag_version_blocks.csv", index=False)
print("\n=== blocks where MJS73-94 and METKLIM differ by one day ===")
print(VB.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
