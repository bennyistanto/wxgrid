"""QC agro:MOJOSARI, question 1 at day resolution: event matching and an offset HMM.

For every agro day D with >= 10 mm (compiled series, form date), find which neighbour-mean day
D+k (k = -2..+2) holds the most rain (needs >= 3 of the 5 days present and the maximum >= 2 mm).
That argmax is one noisy vote for the offset. A 5-state HMM (state = offset) with emission
P(vote = state) = p_hit (estimated from the data at the global best offset), the rest spread
evenly, and a switch probability per event, is decoded by Viterbi. Segments are reported with
their first and last event dates; the boundary between segments is only known to lie between
two events.
Also: votes split by day of month (1-10, 11-20, 21-31) and around months whose sheet has a
missing day row (raw_month_layout.csv), to test row slips inside a month.
Neighbours: the same 5 as tools/qc_mojosari_lag.py (read from lag_neighbour_candidates.csv).
Outputs: F:/temp/station/qc_mojosari/events_votes.csv, events_segments.csv.
Run: python tools/qc_mojosari_events.py
"""
import numpy as np
import pandas as pd

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
LAGS = list(range(-2, 3))
o = q.obs_ejava()
comp = q.daily(o, q.A, col="date_raw")["1973":"1994"]
C = pd.read_csv(f"{q.OUT}/lag_neighbour_candidates.csv")
NB = C.drop_duplicates("site_id").head(5).series_id.tolist()
nbm = pd.concat([q.daily(o, s, unmeasurable_as=0.0) for s in NB], axis=1)
nbmean = nbm.mean(axis=1).where(nbm.notna().sum(axis=1) >= 2)

ev = comp[comp >= 10].index
rows = []
for d in ev:
    w = np.array([nbmean.get(d + pd.Timedelta(days=k), np.nan) for k in LAGS], float)
    if np.isfinite(w).sum() < 3 or np.nanmax(w) < 2:
        continue
    rows.append(dict(date=d, agro=comp[d], vote=LAGS[int(np.nanargmax(w))], **{f"nb{k:+d}": w[i] for i, k in enumerate(LAGS)}))
E = pd.DataFrame(rows)
E.to_csv(f"{q.OUT}/events_votes.csv", index=False)
print(f"events (agro >= 10 mm with neighbour data): {len(E)}")
print("vote shares all years:", E.vote.value_counts(normalize=True).sort_index().round(3).to_dict())
E["year"] = E.date.dt.year
print("\nvote shares by year:")
print(pd.crosstab(E.year, E.vote, normalize="index").round(2).assign(n=E.groupby("year").size()).to_string())

E["dom"] = pd.cut(E.date.dt.day, [0, 10, 20, 31], labels=["1-10", "11-20", "21-31"])
print("\nvote shares by day of month:")
print(pd.crosstab(E.dom, E.vote, normalize="index").round(2).assign(n=E.groupby("dom", observed=True).size()).to_string())

# months with a missing day row in the sheet that the build used (MJS73-94 or METKLIM per year)
L = pd.read_csv(f"{q.OUT}/raw_month_layout.csv")
L = L[(L.rows > 0) & (L.rows < L.days_in_month)]
rows = []
for r in L.itertuples():
    miss = [int(x) for x in str(r.missing_days).split()]
    sub = E[(E.date.dt.year == r.year) & (E.date.dt.month == r.month)]
    for x in sub.itertuples():
        rows.append(dict(file=r.file, year=r.year, month=r.month, missing=r.missing_days,
                         side="before" if x.date.day < min(miss) else "after", vote=x.vote))
Lm = pd.DataFrame(rows).drop_duplicates()
if len(Lm):
    print("\nvotes in months with a missing day row, before vs after the first missing day:")
    print(pd.crosstab([Lm.file.str.split("/").str[0], Lm.side], Lm.vote).to_string())

# HMM
p_hit = float((E.vote == 1).mean())
print(f"\nemission p_hit = share of votes at the global best offset (+1) = {p_hit:.3f}")
for p_switch in [0.01, 0.003]:
    lo_hit, lo_miss, lo_sw, lo_stay = np.log(p_hit), np.log((1 - p_hit) / 4), np.log(p_switch / 4), np.log(1 - p_switch)
    n, S = len(E), len(LAGS)
    em = np.where(np.array(E.vote)[:, None] == np.array(LAGS)[None, :], lo_hit, lo_miss)
    trans = np.full((S, S), lo_sw); np.fill_diagonal(trans, lo_stay)
    D = np.zeros((n, S)); bp = np.zeros((n, S), int)
    D[0] = em[0]
    for t in range(1, n):
        x = D[t - 1][:, None] + trans
        bp[t] = x.argmax(axis=0); D[t] = x.max(axis=0) + em[t]
    path = [int(D[-1].argmax())]
    for t in range(n - 1, 0, -1):
        path.append(bp[t, path[-1]])
    E[f"state_{p_switch}"] = [LAGS[j] for j in path[::-1]]
segs = []
for p_switch in [0.01, 0.003]:
    col = f"state_{p_switch}"
    g = (E[col] != E[col].shift()).cumsum()
    for _, s in E.groupby(g):
        segs.append(dict(p_switch=p_switch, offset=int(s[col].iloc[0]), first_event=s.date.iloc[0].date(),
                         last_event=s.date.iloc[-1].date(), n_events=len(s),
                         share_votes_offset=round(float((s.vote == s[col].iloc[0]).mean()), 2),
                         share_votes_plus1=round(float((s.vote == 1).mean()), 2),
                         share_votes_0=round(float((s.vote == 0).mean()), 2)))
G = pd.DataFrame(segs)
G.to_csv(f"{q.OUT}/events_segments.csv", index=False)
print("\nHMM segments (Viterbi):")
print(G.to_string(index=False))

# calibration: each neighbour against the mean of the other four (pipeline dates), same rules
print("\n=== calibration: each neighbour vs mean of the other 4 neighbours (1973-1994) ===")
rows = []
for s in NB:
    x = q.daily(o, s, unmeasurable_as=0.0)["1973":"1994"]
    others = nbm[[c for c, sid in zip(nbm.columns, NB) if sid != s]] if False else pd.concat(
        [q.daily(o, t, unmeasurable_as=0.0) for t in NB if t != s], axis=1)
    om = others.mean(axis=1).where(others.notna().sum(axis=1) >= 2)
    votes = []
    for d in x[x >= 10].index:
        w = np.array([om.get(d + pd.Timedelta(days=k), np.nan) for k in LAGS], float)
        if np.isfinite(w).sum() < 3 or np.nanmax(w) < 2:
            continue
        votes.append(LAGS[int(np.nanargmax(w))])
    v = pd.Series(votes)
    rs = {k: q.pearson(x.values, q.lagged(om, x.index, k))[0] for k in LAGS}
    yb = []
    for y in range(1973, 1995):
        xy = x[x.index.year == y].dropna()
        if len(xy) < 200:
            continue
        ry = {k: q.pearson(xy.values, q.lagged(om, xy.index, k))[0] for k in LAGS}
        if all(np.isfinite(list(ry.values()))):
            yb.append(max(ry, key=ry.get))
    yb = pd.Series(yb)
    rows.append(dict(series=s, n_events=len(v), **{f"vote{k:+d}": round(float((v == k).mean()), 3) for k in LAGS},
                     **{f"r{k:+d}": round(rs[k], 3) for k in LAGS},
                     years=len(yb), years_best_lag0=int((yb == 0).sum())))
x = comp
rs = {k: q.pearson(x.values, q.lagged(nbmean, x.index, k))[0] for k in LAGS}
rows.append(dict(series="agro:MOJOSARI:RR (vs mean of 5)", n_events=len(E),
                 **{f"vote{k:+d}": round(float((E.vote == k).mean()), 3) for k in LAGS},
                 **{f"r{k:+d}": round(rs[k], 3) for k in LAGS}))
K = pd.DataFrame(rows)
K.to_csv(f"{q.OUT}/events_calibration.csv", index=False)
print(K.to_string(index=False))
