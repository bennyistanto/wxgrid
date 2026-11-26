"""QC side finding: values flagged above_max (> 500 mm, config flag_bounds RR) still reach merged_RR.

Lists every merged_RR row whose flag contains above_max, and counts exact code-like values
(999, 888, 777, 9999, 8888) per series in observations_RR.
Run: python tools/qc_merged_above_max.py
"""
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 100)
m = q.merged_rr(); o = q.obs_rr()
a = m[m.flag.astype(str).str.contains("above_max")]
print(f"merged_RR rows flagged above_max: {len(a)} at {a.site_id.nunique()} sites")
print(a[["site_id", "date", "value", "flag", "series_id"]].sort_values("value").to_string(index=False))
c = o[o.value.isin([777, 888, 999, 8888, 9999])]
print("\ncode-like values in observations_RR by series and value:")
print(c.groupby([c.series_id.astype(str), "value"]).size().to_string())
