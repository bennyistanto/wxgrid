"""Turn QC findings into an exclusion table for the consolidation pipeline (RR).

Decisions (user, 2026-10-07, after /qc):
- zero runs of >= 60 days that the QC marked suspect (CPC or neighbours wet) -> exclude
- data copied from another station (foreign periods)                        -> exclude
- 96655 Tjilik Riwut: the same April copied into 1989 and 1991-2010         -> exclude
- months duplicated within a series: every copy after the first             -> exclude
- compendium 200.0 mm that is also spatially or CPC isolated                -> exclude

Input: QC tables in <compiled>/qc/ (scripts in temp/qc/). Dates are in the target day
convention (merged view dates). Output: <compiled>/qc/exclusions_rr.csv with columns
series_id, start, end, rule, note. Values are flagged `qc_excluded`, never deleted.

Run: python tools/build_qc_exclusions.py F:/temp/station/compiled
"""

import sys
from pathlib import Path

import pandas as pd

root = Path(sys.argv[1]) / "qc"
rows = []

z = pd.read_csv(root / "qc_rr_zero_runs.csv")
z = z[z["suspect"].astype(bool) & (z["length"] >= 60)]
for r in z.itertuples():
    for sid in str(r.series_id).split(";"):
        rows.append((sid, r.start, r.end, "zero_run_60d", f"{r.length} d of 0 mm, CPC mean {r.cpc_mean:.1f} mm/d"))

FOREIGN = [  # QC report 2026-10-07, qc_03c_copy_location.py
    ("bmkg_xlsx:96037:RR", "1981-01-01", "1989-12-31", "identical to 96937 Tanjung Perak (Surabaya)"),
    ("bmkg_xlsx:97120:RR", "2007-01-01", "2008-12-31", "identical to 97142 Sangia Ni Bandera"),
    ("bmkg_xlsx:97694:RR", "2014-01-01", "2014-12-31", "identical to 97698 Dok II Jayapura"),
    ("bmkg_xlsx:96091:RR", "2000-01-01", "2000-12-31", "44% equal to 96179 Dabo; CPC fits Dabo"),
]
rows += [(s, a, b, "foreign_data", n) for s, a, b, n in FOREIGN]

for y in [1989] + list(range(1991, 2011)):
    rows.append(("bmkg_xlsx:96655:RR", f"{y}-04-01", f"{y}-04-30", "april_copy", "same April in 1989, 1991-2010"))

d = pd.read_csv(root / "qc_rr_duplicates_months_within_series.csv")
for r in d.itertuples():
    months = sorted(str(r.months).split(";"))
    for m in months[1:]:  # keep the first occurrence
        p = pd.Period(m, "M")
        rows.append((r.series_id, str(p.start_time.date()), str(p.end_time.date()), "dup_month_copy",
                     f"copy of {months[0]}"))

o = pd.read_csv(root / "qc_rr_outliers.csv")
o = o[(o["source"] == "asean_comp") & (o["value"] == 200.0) & (o["spatial_isolated"] | o["cpc_isolated"])]
rows += [(r.series_id, r.date, r.date, "code200_isolated", "compendium 200.0 mm, isolated") for r in o.itertuples()]

out = pd.DataFrame(rows, columns=["series_id", "start", "end", "rule", "note"]).drop_duplicates()
out.to_csv(root / "exclusions_rr.csv", index=False)
print(out.groupby("rule").agg(periods=("series_id", "size"), series=("series_id", "nunique")).to_string())
print("written", root / "exclusions_rr.csv")
