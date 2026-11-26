"""QC focus 1: bmg_posts months coded entirely "-" (flag dash_month): dry or unreported?

For every (series, form month) with flag dash_month in observations_RR:
- CPC-UNI month total and wet days (>= 1 mm) at the station cell (station date D <-> CPC D-1, F38)
- CPC percentile of that total among the same calendar month at that cell, 1979-2025
- neighbours in merged_RR within 50 km (other sites, >= 25 values that month incl. unmeasurable
  as 0): count, median and max month total, and how many are >= 50 mm
- the post's own median total for that calendar month in non-dash months (>= 25 values)
- whether the month reaches merged_RR from this series
Calibration from the post's own reported (non-dash) months with >= 25 values: share of months
with total < 5 mm per CPC month-total bin. It says how often this post reports a near-dry month
when CPC is wet.
Verdict (provisional thresholds, same spirit as temp/qc/qc_05_zeros.py):
  unreported:  >= 2 neighbours with median >= 50 mm unless CPC < 20 mm (CPC veto), or
               CPC >= 100 mm unless >= 2 neighbours have median < 30 mm
  dry:         >= 2 neighbours with median < 30 mm and CPC < 100 mm (or no CPC), or
               < 2 neighbours and CPC < 50 mm
  no_evidence: < 2 neighbours and no CPC (before 1979)
  ambiguous:   otherwise (mostly CPC or neighbours at 30-100 mm)
Writes F:/temp/station/qc_phase2/dash_months.csv. Run: python tools/qc_dash_months.py
"""
import numpy as np
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
o = q.obs_rr()
st = q.stations().set_index("station_key")
se = q.series().set_index("series_id")
sites = q.sites().set_index("site_id")
m = q.merged_rr()

b = o[o.series_id.astype(str).str.startswith("bmg_posts:")].copy()
b["sid"] = b.series_id.astype(str)
b["ym"] = b.date_raw.dt.to_period("M")
b["is_dash"] = b.flag.astype(str).str.contains("dash_month")
b["v0"] = b.value.fillna(0.0)  # unmeasurable counted as 0 in totals

# own month table
own = b.groupby(["sid", "ym"]).agg(n=("v0", "size"), tot=("v0", "sum"), dash=("is_dash", "any")).reset_index()
own["cal"] = own.ym.dt.month

# merged site-month totals
m["ym"] = m.date.dt.to_period("M")
m["v0"] = m.value.fillna(0.0)
sm = m.groupby(["site_id", "ym"], observed=True).agg(n=("v0", "size"), tot=("v0", "sum")).reset_index()
sm = sm[sm.n >= 25]
sm_idx = sm.set_index(["site_id", "ym"]).tot
lat = sites.lat.values; lon = sites.lon.values
cpc = q.CPCField()
in_merged = m[m.series_id.astype(str).str.startswith("bmg_posts:")].groupby(
    [m.series_id.astype(str), "ym"], observed=True).size()

rows = []
for sid, g in own[own.dash].groupby("sid"):
    sk = se.loc[sid, "station_key"]; la, lo = st.loc[sk, "lat"], st.loc[sk, "lon"]; site = st.loc[sk, "site_id"]
    d = q.haversine_km(la, lo, lat, lon)
    nbr = [(s, dd) for s, dd in zip(sites.index, d) if dd <= 50 and s != site]
    cs = cpc.series(la, lo)
    cs.index = cs.index + pd.Timedelta(days=1)  # CPC day D-1 -> station date D
    cm = cs.groupby(cs.index.to_period("M")).agg(["sum", lambda x: (x >= 1).sum()])
    cm.columns = ["cpc", "cpc_wet"]
    cm["cal"] = cm.index.month
    nondash = own[(own.sid == sid) & ~own.dash & (own.n >= 25)]
    for r in g.itertuples():
        cpc_t = cm.cpc.get(r.ym, np.nan); cpc_w = cm.cpc_wet.get(r.ym, np.nan)
        same = cm[cm.cal == r.cal].cpc
        pct = (same < cpc_t).mean() * 100 if np.isfinite(cpc_t) else np.nan
        nv = []
        for s, dd in nbr:
            v = sm_idx.get((s, r.ym))
            if v is not None:
                nv.append((s, dd, v))
        nt = np.array([x[2] for x in nv])
        ownmed = nondash[nondash.cal == r.cal].tot.median()
        rows.append(dict(series_id=sid, month=str(r.ym), n_days=r.n, cpc_mm=cpc_t, cpc_wet_days=cpc_w,
                         cpc_pct_calmonth=pct, n_nbr=len(nt), nbr_median_mm=np.median(nt) if len(nt) else np.nan,
                         nbr_max_mm=nt.max() if len(nt) else np.nan, nbr_ge50=int((nt >= 50).sum()),
                         nbr_nearest=(f"{min(nv, key=lambda x: x[1])[0]}@{min(nv, key=lambda x: x[1])[1]:.0f}km="
                                      f"{min(nv, key=lambda x: x[1])[2]:.0f}") if nv else "",
                         own_median_calmonth_mm=ownmed,
                         in_merged_days=int(in_merged.get((sid, r.ym), 0))))
R = pd.DataFrame(rows)
nm = R.nbr_median_mm; ok2 = R.n_nbr >= 2; c = R.cpc_mm
unrep = (ok2 & (nm >= 50) & ~(c < 20)) | ((c >= 100) & ~(ok2 & (nm < 30)))
dry = (ok2 & (nm < 30) & ~(c >= 100)) | (~ok2 & (c < 50))
noev = ~ok2 & c.isna()
R["verdict"] = np.select([unrep, dry, noev], ["unreported", "dry", "no_evidence"], "ambiguous")

# calibration: own non-dash months, share < 5 mm by CPC bin
cal = []
for sid, g in own[~own.dash & (own.n >= 25)].groupby("sid"):
    sk = se.loc[sid, "station_key"]
    cs = cpc.series(st.loc[sk, "lat"], st.loc[sk, "lon"]); cs.index = cs.index + pd.Timedelta(days=1)
    cm = cs.groupby(cs.index.to_period("M")).sum()
    g = g.assign(cpc=g.ym.map(cm)).dropna(subset=["cpc"])
    g["bin"] = pd.cut(g.cpc, [-1, 50, 100, 200, 5000], labels=["<50", "50-100", "100-200", ">=200"])
    for bn, h in g.groupby("bin", observed=True):
        cal.append((sid, bn, len(h), (h.tot < 5).mean()))
C = pd.DataFrame(cal, columns=["series_id", "cpc_bin", "n_months", "share_lt5mm"])
C.to_csv(f"{q.OUT}/dash_months_calibration.csv", index=False)
print("Own reported months: share with total < 5 mm by CPC month-total bin")
print(C.pivot(index="series_id", columns="cpc_bin", values="share_lt5mm").round(2).to_string())
print(C.pivot(index="series_id", columns="cpc_bin", values="n_months").to_string())
R.to_csv(f"{q.OUT}/dash_months.csv", index=False)

print("dash_month months per series and verdict:")
print(pd.crosstab(R.series_id, R.verdict, margins=True))
print("\nflagged days reaching merged_RR, by verdict:")
print(R.groupby("verdict")[["n_days", "in_merged_days"]].sum())
print("\nCPC month total in dash months: median by series")
print(R.groupby("series_id").cpc_mm.describe(percentiles=[.5, .9]).round(1))
print("\nnon-dry months:")
c = ["series_id", "month", "n_days", "cpc_mm", "cpc_pct_calmonth", "n_nbr", "nbr_median_mm",
     "nbr_max_mm", "nbr_nearest", "own_median_calmonth_mm", "in_merged_days", "verdict"]
print(R[R.verdict.isin(["unreported", "ambiguous"])][c].sort_values(["series_id", "month"]).to_string(index=False, float_format=lambda x: f"{x:.0f}"))
