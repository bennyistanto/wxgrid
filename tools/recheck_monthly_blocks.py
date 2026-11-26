"""Measure the station-block monthly rainfall tables found by the recheck.

Layout (DATA IKLIM/_MALUKU, _NTB, _NTT CH_se-*.xls, sheet 'Sheet1'): a station row
  No Stasiun (number [+ sub-letter cell]) | Nama | lat deg | lat min | S | lon deg | lon min | E | elev | Tahun | n | J..D | Total
followed by rows that carry only Tahun | n | J..D | Total. "Tahun" is either a single year
(a real monthly series) or a period such as "1915-26" (a period average). This script
counts, per station, the single years and the period rows, so the two are not mixed up.

Reads the recheck dump (F:/temp/station/additional_recheck/dump). Read-only.
Output: F:/temp/station/additional_recheck/monthly_blocks.csv and a printed summary.
"""
import re
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DUMP = Path("F:/temp/station/additional_recheck/dump")
FILES = {
    "DATA IKLIM/_MALUKU/Maluku_Rata2.XLS": "DATA_IKLIM__MALUKU_Maluku_Rata2.XLS.txt",
    "DATA IKLIM/_NTB/CH_se-NTB.xls": "DATA_IKLIM__NTB_CH_se-NTB.xls.txt",
    "DATA IKLIM/_NTT/CH_se-NTT.XLS": "DATA_IKLIM__NTT_CH_se-NTT.XLS.txt",
}
recs = []
for label, fn in FILES.items():
    lines = (DUMP / fn).read_text(encoding="utf-8").splitlines()
    # only Sheet1 (the others are empty)
    start = next(i for i, l in enumerate(lines) if l.startswith("## SHEET 'Sheet1'"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## SHEET")), len(lines))
    rows = [l.split("\t")[1:] for l in lines[start + 1:end] if l.startswith("r")]
    hdr = rows[0]
    ycol = next(i for i, v in enumerate(hdr) if v.strip().lower() == "tahun")
    jan = ycol + 2
    station = None
    for r in rows[1:]:
        r = r + [""] * (jan + 14 - len(r))
        if re.fullmatch(r"\d+", r[0].strip()):  # a new station row: post number, optional sub-letter, name
            sub = r[1].strip() if re.fullmatch(r"[A-Za-z]", r[1].strip()) else ""
            name = next((x.strip() for x in r[1:4] if x.strip() and not re.fullmatch(r"[A-Za-z]", x.strip())), "")
            station = (r[0].strip() + sub, name, " ".join(x for x in r[2 if not sub else 3:ycol] if x))
        if station is None:
            continue
        t = r[ycol].strip()
        months = r[jan:jan + 12]
        nval = sum(bool(re.fullmatch(r"-?\d+(\.\d+)?", m.strip())) for m in months)
        if re.fullmatch(r"(18|19|20)\d\d", t):
            kind = "year"
        elif re.fullmatch(r"(18|19|20)\d\d\s*-\s*\d{2,4}", t):
            kind = "period"
        elif t == "":
            continue
        else:
            kind = "other:" + t[:15]
        recs.append(dict(file=label, no=station[0], name=station[1], coords=station[2], tahun=t, kind=kind,
                         n_months=nval))
d = pd.DataFrame(recs)
d.to_csv("F:/temp/station/additional_recheck/monthly_blocks.csv", index=False)
for f, g in d.groupby("file"):
    y = g[g.kind == "year"].copy()
    y["yr"] = y.tahun.astype(int)
    per_st = y.groupby(["no", "name"]).agg(y0=("yr", "min"), y1=("yr", "max"), years=("yr", "nunique"),
                                            months=("n_months", "sum"))
    print(f"\n{f}: stations {g[['no','name']].drop_duplicates().shape[0]}, "
          f"station-years {len(y)}, monthly values {int(y.n_months.sum())}, "
          f"period-average rows {int((g.kind=='period').sum())}, other rows {int(g.kind.str.startswith('other').sum())}")
    print(f"  years {y.yr.min()}-{y.yr.max()}; stations with data before 1900: "
          f"{int((per_st.y0 < 1900).sum())}; before 1941: {int((per_st.y0 < 1941).sum())}")
    print("  station-years by decade:", y.groupby(y.yr // 10 * 10).size().to_dict())
