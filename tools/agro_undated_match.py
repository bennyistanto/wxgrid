"""Date the undated files in Data Stasiun by matching them to dated series (user rule
2026-10-08: use an undated file only where it matches a dated record).

- JAKENAN.XLS (root, METKLIM): columns vs the year columns of JAKENAN1.XLS (dated header).
- METKLIM/052X-ACC.XLS: columns vs Kendalpayak radiation (RA) per year from the agro sheets.
- LRNG81.CSV: columns vs Lanrang variables, sliding the start date over 1979-1983.

A column is dated when >= 90% of >= 100 shared non-missing values are equal.
Run: python tools/agro_undated_match.py -> _agro_undated_matches.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers.agro_sheets import _num  # noqa: E402

B = Path("F:/temp/station/additional-sources")
D = B / "Data Stasiun"


def matrix(path, skip_header):
    sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
    r0 = 1 if skip_header else 0
    return pd.DataFrame([[_num(sh.cell_value(r, c)) for c in range(sh.ncols)] for r in range(r0, min(r0 + 365, sh.nrows))])


def eq_share(a, b):
    ok = ~(np.isnan(a) | np.isnan(b))
    return (np.isclose(a[ok], b[ok]).mean(), int(ok.sum())) if ok.sum() else (np.nan, 0)


out = []
# 1. JAKENAN.XLS vs JAKENAN1.XLS
sh1 = xlrd.open_workbook(str(D / "JAKENAN1.XLS")).sheet_by_index(0)
years1 = [int(sh1.cell_value(0, c)) for c in range(sh1.ncols)]
J1 = matrix(D / "JAKENAN1.XLS", True)
for f in ("JAKENAN.XLS", "METKLIM/JAKENAN.XLS", "METKLIM/JAKENAN1.XLS"):
    M = matrix(D / f, f.endswith("JAKENAN1.XLS"))
    for c in M.columns:
        best = max(((eq_share(M[c].values.astype(float), J1[k].values.astype(float)), years1[k]) for k in J1.columns),
                   key=lambda x: (x[0][0] if not np.isnan(x[0][0]) else -1))
        (sh_, n), y = best
        out.append(dict(file=f, column=int(c), matched="JAKENAN1.XLS", year=y if sh_ >= 0.9 and n >= 100 else None,
                        variable="RA", share_equal=round(sh_, 3), n=n))

# 2. 052X-ACC vs Kendalpayak RA by year (resolved agro records)
R = pd.read_csv(B / "_agro_raw_records.csv.gz", parse_dates=["date"])
Z = pd.read_csv(B / "_agro_sheet_resolution.csv"); Z = Z[Z["status"] != "unresolved"]
R = R.merge(Z[["file", "sheet", "station", "year", "parsed_year"]], on=["file", "sheet"])
shf = (R["year"] - R["parsed_year"]).astype(int)
R["date"] = [d + pd.DateOffset(years=int(s)) if s else d for d, s in zip(R["date"], shf)]
ka = R[(R["station"] == "Kendalpayak") & (R["var"] == "RA")].drop_duplicates("date").set_index("date")["value"]
A = matrix(D / "METKLIM/052X-ACC.XLS", False)
for c in A.columns:
    best = (np.nan, 0, None)
    for y in sorted(set(ka.index.year)):
        ref = ka[ka.index.year == y]
        v = pd.Series(ref.values, index=ref.index.dayofyear - 1).reindex(range(365)).values
        s, n = eq_share(A[c].values.astype(float), v.astype(float))
        if not np.isnan(s) and (np.isnan(best[0]) or s > best[0]):
            best = (s, n, y)
    out.append(dict(file="METKLIM/052X-ACC.XLS", column=int(c), matched="Kendalpayak RA",
                    year=best[2] if best[0] >= 0.9 and best[1] >= 100 else None, variable="RA",
                    share_equal=round(best[0], 3) if not np.isnan(best[0]) else np.nan, n=best[1]))

# 3. LRNG81.CSV vs Lanrang variables with a sliding start date
L = pd.read_csv(D / "LRNG81.CSV", header=None)
la = R[R["station"] == "Lanrang"].drop_duplicates(["date", "var"]).pivot_table(index="date", columns="var", values="value")
for c in L.columns:
    col = pd.to_numeric(L[c], errors="coerce").values.astype(float)
    best = (np.nan, 0, None, None)
    for var in la.columns:
        ref = la[var]
        for start in pd.date_range("1979-01-01", "1983-12-31", freq="D"):
            idx = pd.date_range(start, periods=len(col), freq="D")
            v = ref.reindex(idx).values.astype(float)
            ok = ~(np.isnan(col) | np.isnan(v))
            if ok.sum() < 100:
                continue
            s = np.isclose(col[ok], v[ok]).mean()
            if np.isnan(best[0]) or s > best[0]:
                best = (s, int(ok.sum()), var, start)
    out.append(dict(file="LRNG81.CSV", column=int(c), matched="Lanrang", variable=best[2],
                    year=str(best[3].date()) if best[3] is not None and best[0] >= 0.9 else None,
                    share_equal=round(best[0], 3) if not np.isnan(best[0]) else np.nan, n=best[1]))

O = pd.DataFrame(out)
O.to_csv(B / "_agro_undated_matches.csv", index=False)
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 100)
print(O.to_string(index=False))
