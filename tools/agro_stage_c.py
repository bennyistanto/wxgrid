"""Stage C: after station/year resolution, measure how often the same station-day-variable
is written by more than one sheet, and how often those copies disagree. Sources are
classed as METKLIM per-year file, station-folder compilation, ALIST, root, or long-format.

Run: python tools/agro_stage_c.py -> _agro_conflicts.csv (every disagreeing value) and a summary
"""
import os
import re
import sys
from pathlib import Path

import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers.agro_long import parse_long_sheet  # noqa: E402

B = Path("F:/temp/station/additional-sources")
R = pd.read_csv(B / "_agro_raw_records.csv.gz", parse_dates=["date"])
Z = pd.read_csv(B / "_agro_sheet_resolution.csv")
Z = Z[Z["status"] != "unresolved"]
R = R.merge(Z[["file", "sheet", "station", "year", "parsed_year"]], on=["file", "sheet"], how="inner")
# shift dates to the resolved year (whole sheet moves together)
shift = (R["year"] - R["parsed_year"]).astype(int)
R["date"] = [d + pd.DateOffset(years=int(s)) if s else d for d, s in zip(R["date"], shift)]
R = R.drop(columns=["year", "parsed_year"])

# long-format Muneng files join the comparison (same station)
D = B / "Data Stasiun"
long_recs = []
for f in sorted("METKLIM/" + x for x in os.listdir(D / "METKLIM") if re.match(r"(MNG|MUNENG)", x.upper())):
    wb = xlrd.open_workbook(str(D / f))
    sh = next(wb.sheet_by_index(i) for i in range(wb.nsheets) if wb.sheet_by_index(i).nrows > 4)
    df, meta = parse_long_sheet(sh, wb.datemode)
    if df is not None:
        long_recs.append(df.assign(file=f, sheet=sh.name, station="Muneng"))
R = pd.concat([R] + long_recs, ignore_index=True)


def kind(f):
    if f.startswith("METKLIM/"):
        return "long" if re.match(r"METKLIM/(MNG|MUNENG)", f.upper()) else "metklim"
    if f.startswith("ALIST/"):
        return "alist"
    return "root" if "/" not in f else "folder"


R["kind"] = R["file"].map(kind)
R = R.dropna(subset=["value"])
g = R.groupby(["station", "date", "var"])
n_src = g["file"].transform("nunique")
multi = R[n_src > 1]
agg = multi.groupby(["station", "date", "var"]).agg(n=("value", "size"), vmin=("value", "min"), vmax=("value", "max"),
                                                   kinds=("kind", lambda s: "+".join(sorted(set(s)))),
                                                   files=("file", lambda s: " | ".join(sorted(set(s)))))
agg["agree"] = (agg["vmax"] - agg["vmin"]).abs() < 1e-6
print("station-day-values total:", R.groupby(["station", "date", "var"]).ngroups)
print("written by >1 sheet:", len(agg), f"({len(agg) / R.groupby(['station', 'date', 'var']).ngroups:.1%})")
print("of those, values agree:", int(agg["agree"].sum()), f"({agg['agree'].mean():.2%}) | disagree:", int((~agg['agree']).sum()))
dis = agg[~agg["agree"]].reset_index()
dis["absdiff"] = dis["vmax"] - dis["vmin"]
print("\ndisagreements by source pairing:", dis["kinds"].value_counts().to_dict())
print("disagreements by variable:", dis["var"].value_counts().to_dict())
print("disagreements by station:", dis["station"].value_counts().head(12).to_dict())
print("size of disagreement (abs diff) quantiles:", dis["absdiff"].quantile([.5, .9, .99]).round(2).to_dict())
# are disagreements concentrated in a few station-years (a whole sheet differing) or scattered?
dis["sy"] = dis["station"] + " " + dis["date"].dt.year.astype(str)
sy = dis.groupby("sy").size().sort_values(ascending=False)
print("station-years with disagreements:", len(sy), "| top 10:", sy.head(10).to_dict())
dis.to_csv(B / "_agro_conflicts.csv", index=False)
