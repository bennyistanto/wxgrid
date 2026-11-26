"""QC agro:MOJOSARI, question 6: evaluate day-label options and write proposals (not adopted).

Options, each as a per-day offset (corrected date = form date + offset, the pipeline rule):
  raw       offset 0 everywhere (form dates)
  build     the dates the build gives now (column date, from daylabel_segments.csv)
  uniform   +1 everywhere
  seg6      Viterbi segments, penalty 6 (tools/qc_mojosari_lag.py, lag_segments.csv)
  seg3      Viterbi segments, penalty 3
Scored against the 5 neighbours (pipeline dates) and CPC: r with the neighbour mean, mean of
individual r, hit rate (agro >= 1 mm and neighbour mean >= 1 mm), split by period.
Boundaries of seg6 are refined with a centred 61-day rolling r (lag +2 minus lag +1).
Writes proposals (NOT applied): F:/temp/station/qc_mojosari/proposed_daylabel_mojosari.csv and
proposed_flags_mojosari.csv. Run: python tools/qc_mojosari_proposal.py
"""
import numpy as np
import pandas as pd

import qc_mojosari_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
o = q.obs_ejava(); meta = q.rr_meta().set_index("series_id")
lat, lon = meta.loc[q.A, ["lat", "lon"]]
raw = q.daily(o, q.A, col="date_raw")["1973":"1994"]
build = q.daily(o, q.A, col="date")
C = pd.read_csv(f"{q.OUT}/lag_neighbour_candidates.csv")
NB = C.drop_duplicates("site_id").head(5).series_id.tolist()
N = pd.concat([q.daily(o, s, unmeasurable_as=0.0) for s in NB], axis=1, keys=NB)
nbmean = N.mean(axis=1).where(N.notna().sum(axis=1) >= 2)
cpc = q.CPCField().series(lat, lon)
G = pd.read_csv(f"{q.OUT}/lag_segments.csv")


def seg_offsets(pen):
    g = G[(G.variant == "comp") & (G.ref == "nbr_mean") & (G.penalty == pen)].reset_index(drop=True)
    off = pd.Series(np.nan, index=raw.index)
    for i, r in g.iterrows():
        s0 = pd.Period(r.start).start_time if i else raw.index[0]
        s1 = (pd.Period(g.start[i + 1]).start_time - pd.Timedelta(days=1)) if i + 1 < len(g) else raw.index[-1]
        off[s0:s1] = r.lag
    return off.fillna(1).astype(int)


def shift(a, off):
    s = pd.Series(a.values, index=a.index + pd.to_timedelta(off.reindex(a.index).values, unit="D"))
    s = s[~s.index.duplicated(keep=False)]
    return s.sort_index()


# refine seg6 boundaries
rr = {}
for k in (1, 2):
    b = nbmean.reindex(raw.index + pd.Timedelta(days=k)).values
    x = pd.DataFrame({"a": raw.values, "b": b}, index=raw.index)
    rr[k] = x.a.rolling(61, center=True, min_periods=30).corr(x.b)
diff = (rr[2] - rr[1])
print("=== 61-day rolling r(lag +2) - r(lag +1) vs nbr mean, monthly means around the seg6 boundaries ===")
for s0, s1 in [("1980-10", "1981-12"), ("1983-09", "1984-08")]:
    print(diff[s0:s1].resample("MS").mean().round(2).to_string())
s6 = seg_offsets(6.0)
b6 = s6.diff().fillna(0) != 0
cand = {}
for d in s6.index[b6]:
    w = diff[d - pd.Timedelta(days=60): d + pd.Timedelta(days=60)]
    sgn = np.sign(s6[d] - s6[d - pd.Timedelta(days=1)])
    # first day from which the rolling difference stays on the new side for 30 days
    side = (w * sgn > 0).astype(int)
    run = side[::-1].rolling(30, min_periods=30).min()[::-1]
    first = run[run == 1].index.min()
    cand[d] = first
print("seg6 boundaries (month start) and refined first day:", {str(k.date()): (str(v.date()) if pd.notna(v) else None) for k, v in cand.items()})

opts = {"raw": raw, "build": build, "uniform+1": shift(raw, pd.Series(1, index=raw.index)),
        "seg6": shift(raw, s6), "seg3": shift(raw, seg_offsets(3.0))}
periods = [("1973", "1994"), ("1976", "1980"), ("1981-06", "1984-02"), ("1984-03", "1988-03"), ("1986-03", "1988-03"), ("1988-04", "1994")]
rows = []
for nme, s in opts.items():
    for p0, p1 in periods:
        x = s[p0:p1]
        r, n = q.pearson(x.values, nbmean.reindex(x.index).values)
        h, _ = q.hit_rate(x.values, nbmean.reindex(x.index).values)
        ind = [q.pearson(x.values, N[c].reindex(x.index).values)[0] for c in N]
        x79 = x["1979":]
        rc = q.pearson(x79.values, cpc.reindex(x79.index).values)[0] if len(x79) else np.nan
        rows.append(dict(option=nme, period=f"{p0}..{p1}", n=n, r_nbr_mean=r, mean_r_individual=np.nanmean(ind),
                         r_pu_mojosari=ind[0], r_pudaksari=ind[1], hit=h, r_cpc=rc))
Ev = pd.DataFrame(rows)
Ev.to_csv(f"{q.OUT}/proposal_evaluation.csv", index=False)
print("\n=== day-label options scored against neighbours (pipeline dates) and CPC ===")
print(Ev.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

# ---- the proposal: seg3 boundaries, short or single-reference pieces folded or marked ----
PROP = [  # start, end, offset, status, evidence
    ("1973-01-01", "1976-10-31", 1, "neighbours_only", "1973 one neighbour (nb r +1 0.37 vs 0 0.04); 1976 bootstrap +1 0.98; no CPC before 1979"),
    ("1976-11-01", "1977-05-31", 0, "neighbours_only", "seg3 only (Viterbi penalty 3); r nbr mean 0.56 at 0 vs 0.26 at +1; 1977 bootstrap 0 0.62 / +1 0.38; no CPC"),
    ("1977-06-01", "1981-06-08", 1, "supported", "seg3 and seg6; 1980 bootstrap +1 1.00; CPC 1980-81 Viterbi +1/+2"),
    ("1981-06-09", "1984-02-29", 2, "supported", "seg3 and seg6 (+2); bootstrap 1982 0.89, 1983 1.00; CPC r +2 0.217 vs +1 0.170; start refined by 61-day rolling r, end uncertain Jan-Apr 1984"),
    ("1984-03-01", "1986-02-28", 1, "supported", "seg3 and seg6; bootstrap 1985 +1 0.95"),
    ("1986-03-01", "1988-03-31", 0, "supported", "seg3 (neighbours) and CPC independently: CPC r 0.280 at 0 vs 0.175 at +1; bootstrap 1986 0 0.64, 1987 +1 0.56"),
    ("1988-04-01", "1994-12-31", 1, "supported", "seg3 and seg6 +1 (1988-04..05 +2 in seg3 folded in); bootstrap 1991-93 +1 >= 0.96"),
]
off = pd.Series(np.nan, index=raw.index)
for s0, s1, k, _, _ in PROP:
    off[s0:s1] = k
prop = shift(raw, off.astype(int))
rows = []
for nme, s in [("raw", raw), ("build", build), ("uniform+1", opts["uniform+1"]), ("proposed", prop)]:
    for s0, s1, k, st_, _ in [("1973-01-01", "1994-12-31", None, "all", "")] + PROP:
        x = s[s0:s1]
        r, n = q.pearson(x.values, nbmean.reindex(x.index).values)
        x79 = x["1979":]
        rc = q.pearson(x79.values, cpc.reindex(x79.index).values)[0] if len(x79) > 30 else np.nan
        rows.append(dict(option=nme, segment=f"{s0}..{s1}", offset=k, n=n, r_nbr_mean=r,
                         mean_r_individual=np.nanmean([q.pearson(x.values, N[c].reindex(x.index).values)[0] for c in N]), r_cpc=rc))
Pe = pd.DataFrame(rows)
Pe.to_csv(f"{q.OUT}/proposal_segments_scored.csv", index=False)
print("\n=== proposal scored per segment (CPC is independent of the neighbour-fitted segments) ===")
print(Pe.pivot_table(index="segment", columns="option", values=["r_nbr_mean", "r_cpc"]).to_string(float_format=lambda x: f"{x:.3f}"))

pd.DataFrame([dict(series_id=q.A, start=s0, end=s1, offset=k, status=st_, evidence=ev,
                   script="tools/qc_mojosari_lag.py + tools/qc_mojosari_proposal.py") for s0, s1, k, st_, ev in PROP]
             ).to_csv(f"{q.OUT}/proposed_daylabel_mojosari.csv", index=False)

FL = [
    ("1994-11-17", "1994-11-17", "suspect_value", "flag; exclude from daily grid pending a check of the paper form",
     "360 mm in both MJS73-94 and METKLIM 175A-94; series max, 4x the wet-day p99 (90 mm); largest neighbour value 1973-1994 is 274 (PU Mojosari), next 149; neighbours max 37 / 2 / 0 on D-1 / D / D+1, CPC 46 on D-1 (tools/qc_mojosari_scale.py)"),
    ("1973-03-07", "1973-03-07", "suspect_accumulation", "flag; review",
     "100 mm right after a '*' cell; the one neighbour with data has 0-2 mm on D-1..D+2 (tools/qc_mojosari_scale.py, qc_mojosari_raw.py)"),
    ("1988-06-01", "1988-06-30", "zero_month_suspect", "flag; review (dry-season month)", "agro 0 mm, neighbour mean 77 mm with 6 days >= 5 mm (tools/qc_mojosari_copies.py)"),
    ("1989-07-01", "1989-07-31", "zero_month_suspect", "flag; review (dry-season month)", "agro 0 mm, neighbour mean 92 mm with 6 days >= 5 mm (tools/qc_mojosari_copies.py)"),
    ("1986-11-24", "1986-12-27", "zero_run_wet_season", "flag; review", "34 zero days in Nov-Dec, neighbour mean 117 mm with 12 days >= 5 mm (tools/qc_mojosari_copies.py)"),
    ("1973-01-01", "1973-12-31", "day_label_unverified", "low weight or exclude from daily grid",
     "only one neighbour reports in 1973 (PU all-zero sheets dropped, F64), no CPC; 13 '*' cells (tools/qc_mojosari_lag.py, qc_mojosari_raw.py)"),
    ("1984-01-01", "1984-04-30", "day_label_uncertain", "flag; boundary between +2 and +1 not resolved",
     "61-day rolling r(+2) - r(+1) changes sign three times in Jan-Apr 1984 (tools/qc_mojosari_proposal.py)"),
]
pd.DataFrame([dict(series_id=q.A, start=a_, end=b_, flag=f, proposed_action=act, evidence=ev) for a_, b_, f, act, ev in FL]
             ).to_csv(f"{q.OUT}/proposed_flags_mojosari.csv", index=False)
print("\nwrote proposed_daylabel_mojosari.csv and proposed_flags_mojosari.csv (proposals, not applied)")
