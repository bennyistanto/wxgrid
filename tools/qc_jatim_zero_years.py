"""QC side finding: whole calendar years of exactly 0.0 mm in jatim (East Java PU) series.

A series-year with >= 300 values that are all 0.0 mm is impossible for an East Java rain post
(annual totals there are 1,000-2,300 mm, see the same posts' other years). For each such year:
values, how many reach merged_RR from that series, the CPC-UNI total at the post's cell (1979+),
and the post's median annual total in non-zero years.
Writes F:/temp/station/qc_phase2/jatim_zero_years.csv. Run: python tools/qc_jatim_zero_years.py
"""
import numpy as np
import pandas as pd

import qc_phase2_common as q

o = q.obs_rr(); m = q.merged_rr()
st = q.stations().set_index("station_key"); se = q.series().set_index("series_id")
j = o[o.series_id.astype(str).str.startswith("jatim:")].copy()
j["sid"] = j.series_id.astype(str); j["y"] = j.date_raw.dt.year
g = j.groupby(["sid", "y"]).agg(n=("value", "size"), tot=("value", "sum"), nnan=("value", lambda x: x.isna().sum()))
z = g[(g.n >= 300) & (g.tot == 0)].reset_index()
mj = m[m.series_id.astype(str).str.startswith("jatim:")]
mj = mj.assign(sid=mj.series_id.astype(str), y=mj.date.dt.year).groupby(["sid", "y"]).size()
cpc = q.CPCField()
med = g[g.tot > 0].groupby("sid").tot.median()
rows = []
for r in z.itertuples():
    sk = se.loc[r.sid, "station_key"]
    cs = cpc.series(st.loc[sk, "lat"], st.loc[sk, "lon"])
    ct = cs[str(r.y)].sum() if r.y >= 1979 else np.nan
    rows.append((r.sid, r.y, r.n, int(mj.get((r.sid, r.y), 0)), ct, med.get(r.sid)))
R = pd.DataFrame(rows, columns=["series_id", "year", "n_values", "in_merged", "cpc_year_mm", "post_median_year_mm"])
R.to_csv(f"{q.OUT}/jatim_zero_years.csv", index=False)
print(f"all-zero series-years: {len(R)} in {R.series_id.nunique()} series; values {R.n_values.sum()}; reaching merged_RR {R.in_merged.sum()}")
print(R.groupby("series_id").agg(years=("year", "count"), first=("year", "min"), last=("year", "max"),
      in_merged=("in_merged", "sum"), cpc_median=("cpc_year_mm", "median"), post_median=("post_median_year_mm", "first")).to_string())
print("years:", R.groupby("series_id").year.apply(lambda x: ",".join(map(str, x))).to_string())
