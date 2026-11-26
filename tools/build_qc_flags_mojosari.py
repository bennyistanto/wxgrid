"""Turn the agro:MOJOSARI /qc proposal (2026-11-25, F66) into a QC table for the pipeline.

Input:  F:/temp/station/qc_mojosari/proposed_flags_mojosari.csv (dates on the form, i.e. date_raw)
        F:/temp/station/qc_mojosari/proposed_daylabel_mojosari.csv (offsets per raw-date segment;
        the same rows are in config daylabel.overrides)
Output: F:/temp/station/compiled/qc/flags_rr_mojosari.csv with series_id, start, end, rule, flag, note,
        dates in the corrected convention (date = date_raw + offset), as `qc.exclusions` expects.

User decision 2026-11-25 ("adopt both"):
- 1994-11-17 (360 mm, suspect_value)  -> flag qc_excluded (left out of merged views)
- every other proposed row             -> flag = its proposal code, value kept in merged views;
  gridding decides (1973 day_label_unverified is the "low weight or exclude" case: no weighting exists yet)

Usage: python tools/build_qc_flags_mojosari.py
"""
from pathlib import Path

import pandas as pd

Q = Path("F:/temp/station/qc_mojosari")
OUT = Path("F:/temp/station/compiled/qc/flags_rr_mojosari.csv")
EXCLUDE = {"suspect_value"}

seg = pd.read_csv(Q / "proposed_daylabel_mojosari.csv", parse_dates=["start", "end"])
prop = pd.read_csv(Q / "proposed_flags_mojosari.csv", parse_dates=["start", "end"])


def corrected(sid, days):
    s = seg[seg.series_id == sid]
    off = [int(s[(s.start <= d) & (s.end >= d)].offset.iloc[0]) for d in days]
    return [d + pd.Timedelta(days=o) for d, o in zip(days, off)]


rows = []
for r in prop.itertuples():
    days = corrected(r.series_id, list(pd.date_range(r.start, r.end)))
    rows.append(dict(series_id=r.series_id, start=min(days).date(), end=max(days).date(), rule=r.flag,
                     flag="qc_excluded" if r.flag in EXCLUDE else r.flag,
                     note=f"raw {r.start.date()}..{r.end.date()}; {r.proposed_action}"))
out = pd.DataFrame(rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
out.to_csv(OUT, index=False)
print(out.to_string(index=False))
