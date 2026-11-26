"""Classify each disagreeing station-year between two sheet versions (from agro_stage_c):

  swap      - TX of one version equals TN of the other on most days (columns swapped)
  shift(k)  - one version equals the other shifted by k days (k in -3..+3, excluding 0)
  edits     - versions agree on >= 80% of days; the rest differ (corrections or typos)
  different - none of the above (different data)

For every station-year with disagreements, the two largest sheets holding it are compared.
Run: python tools/agro_stage_c_classify.py -> _agro_conflict_types.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
B = Path("F:/temp/station/additional-sources")
D = pd.read_csv(B / "_agro_conflicts.csv", parse_dates=["date"])
R = pd.read_csv(B / "_agro_raw_records.csv.gz", parse_dates=["date"])
Z = pd.read_csv(B / "_agro_sheet_resolution.csv")
Z = Z[Z["status"] != "unresolved"]
R = R.merge(Z[["file", "sheet", "station", "year", "parsed_year"]], on=["file", "sheet"], how="inner")
sh = (R["year"] - R["parsed_year"]).astype(int)
R["date"] = [d + pd.DateOffset(years=int(s)) if s else d for d, s in zip(R["date"], sh)]
R = R.dropna(subset=["value"])
R["y"] = R["date"].dt.year

rows = []
for (st, y), _ in D.groupby(["station", D["date"].dt.year]):
    sub = R[(R["station"] == st) & (R["y"] == y)]
    sizes = sub.groupby(["file", "sheet"]).size().sort_values(ascending=False)
    if len(sizes) < 2:
        continue
    (fa, sa), (fb, sb) = sizes.index[0], sizes.index[1]
    A = sub[(sub["file"] == fa) & (sub["sheet"] == sa)].pivot_table(index="date", columns="var", values="value", aggfunc="first")
    Bv = sub[(sub["file"] == fb) & (sub["sheet"] == sb)].pivot_table(index="date", columns="var", values="value", aggfunc="first")
    common = [v for v in A.columns if v in Bv.columns]

    def agree(a, b):
        j = a.dropna().index.intersection(b.dropna().index)
        return (np.isclose(a[j], b[j]).mean(), len(j)) if len(j) >= 20 else (np.nan, len(j))
    per_var = {v: agree(A[v], Bv[v]) for v in common}
    eq0 = np.nanmean([x[0] for x in per_var.values()]) if per_var else np.nan
    kind, detail = "different", ""
    if "TX" in common and "TN" in common:
        s1, _ = agree(A["TX"], Bv["TN"]); s2, _ = agree(A["TN"], Bv["TX"])
        if s1 >= 0.8 and s2 >= 0.8:
            kind, detail = "swap", f"TX<->TN {s1:.0%}/{s2:.0%}"
    if kind == "different":
        best = (eq0, 0)
        for k in (-3, -2, -1, 1, 2, 3):
            vals = []
            for v in common:
                b = Bv[v].copy(); b.index = b.index + pd.Timedelta(days=k)
                vals.append(agree(A[v], b)[0])
            m = np.nanmean(vals) if vals else np.nan
            if not np.isnan(m) and m > best[0] + 0.3:
                best = (m, k)
        if best[1] != 0 and best[0] >= 0.8:
            kind, detail = f"shift({best[1]:+d})", f"{best[0]:.0%} equal after shift"
        elif eq0 >= 0.8:
            low = {v: round(x[0], 2) for v, x in per_var.items() if not np.isnan(x[0]) and x[0] < 0.95}
            kind, detail = "edits", f"vars below 95%: {low}"
    # within-variable swaps of RH07 / RH13
    if kind in ("edits", "different") and "HU07" in common and "HU13" in common:
        s1, _ = agree(A["HU07"], Bv["HU13"]); s2, _ = agree(A["HU13"], Bv["HU07"])
        if s1 >= 0.8 and s2 >= 0.8:
            detail += f"; RH07<->RH13 swapped {s1:.0%}"
    n_dis = int(((D["station"] == st) & (D["date"].dt.year == y)).sum())
    rows.append(dict(station=st, year=y, n_disagree=n_dis, a=f"{fa}[{sa}]", b=f"{fb}[{sb}]",
                     agree_lag0=round(eq0, 3) if not np.isnan(eq0) else np.nan, type=kind, detail=detail))
T = pd.DataFrame(rows).sort_values("n_disagree", ascending=False)
T.to_csv(B / "_agro_conflict_types.csv", index=False)
pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 60); pd.set_option("display.max_rows", 100)
print(T.groupby(T["type"].str.replace(r"\(.*\)", "(k)", regex=True))["n_disagree"].agg(["size", "sum"]).to_string())
print()
print(T.head(30).to_string(index=False))
