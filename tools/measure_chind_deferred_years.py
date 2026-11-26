"""CH_IND year files the `chind` reader skips (1990-1993, 1997; F49): how much would they add?

Parses `1990.xls`..`1993.xls` and `1997.xls` from CH_IND.zip with the layout fixes a reader change would need
(full WMO numbers in NOSTA / NOMOR; 1997 data on the second sheet, ids and years as text, two-digit years),
keeps stations in the `chind` catalogue (`_wmo_catalogue.csv`), and compares every value with the BMKG
workbooks (`bmkg_xlsx`, same WMO, date as written) in the compiled observations.
Usage: python tools/measure_chind_deferred_years.py
"""
import re
import sys
import zipfile

import numpy as np
import pandas as pd
import xlrd

sys.stdout.reconfigure(encoding="utf-8")
Z = "F:/temp/station/additional-sources/DATA IKLIM/CH_IND.zip"
CAT = pd.read_csv("F:/temp/station/additional-sources/_wmo_catalogue.csv").set_index("wmo")
FILES = ["1990.xls", "1991.xls", "1992.xls", "1993.xls", "1997.xls"]
norm = lambda s: re.sub(r"[ .]", "", str(s).strip().upper())


def num(v):
    try:
        return float(str(v).strip())
    except ValueError:
        return None


z = zipfile.ZipFile(Z)
mem = {n.split("/")[-1]: n for n in z.namelist()}
rows, codes = [], {"9999": 0, "8888": 0, "text": 0}
for f in FILES:
    wb = xlrd.open_workbook(file_contents=z.read(mem[f]))
    for sh in wb.sheets():
        if sh.nrows < 2:
            continue
        hdr = [norm(sh.cell_value(0, c)) for c in range(sh.ncols)]
        idc = next((hdr.index(h) for h in ("NOMOR", "NOSTA") if h in hdr), None)
        if idc is None or "TAHUN" not in hdr:
            continue
        iy, im = hdr.index("TAHUN"), hdr.index("BULAN")
        days = [(c, int(h[1:])) for c, h in enumerate(hdr) if re.fullmatch(r"R\d+", h)]
        for r in range(1, sh.nrows):
            sid, y, m = num(sh.cell_value(r, idc)), num(sh.cell_value(r, iy)), num(sh.cell_value(r, im))
            if sid is None or y is None or m is None:
                continue
            wmo = int(sid) if sid >= 90000 else 96000 + int(sid)
            y = int(y) + (1900 if y < 100 else 0)
            for c, d in days:
                v = num(sh.cell_value(r, c))
                if v is None:
                    if str(sh.cell_value(r, c)).strip():
                        codes["text"] += 1
                    continue
                if v == 9999:
                    codes["9999"] += 1
                    continue
                if v == 8888:
                    codes["8888"] += 1
                try:
                    rows.append((f, wmo, pd.Timestamp(y, int(m), d), v))
                except ValueError:
                    pass
k = pd.DataFrame(rows, columns=["file", "wmo", "date", "value"])
print("cells:", codes, "| values incl. 8888:", len(k))
k["in_cat"] = k.wmo.isin(CAT.index)
print("by file: values, stations, in catalogue:")
print(k.groupby("file").agg(values=("value", "size"), stations=("wmo", "nunique"), in_cat=("in_cat", "mean")).round(3).to_string())
k = k[k.in_cat & (k.value != 8888)].drop_duplicates(["wmo", "date"])
# BMKG workbooks, same WMO
se = pd.read_csv("F:/temp/station/compiled/series.csv.gz", usecols=["series_id", "station_key", "source", "variable"])
se = se[(se.source == "bmkg_xlsx") & (se.variable == "RR")]
se["wmo"] = se.station_key.str.split(":").str[1].astype(int)
ob = pd.concat(c[c.series_id.isin(se.series_id) & (c.date_raw >= "1990-01-01") & (c.date_raw <= "1997-12-31")]
               for c in pd.read_csv("F:/temp/station/compiled/observations_RR.csv.gz", usecols=["series_id", "date_raw", "value"], chunksize=3_000_000))
ob = ob.merge(se[["series_id", "wmo"]]).assign(date=lambda d: pd.to_datetime(d.date_raw)).drop_duplicates(["wmo", "date"])
j = k.merge(ob[["wmo", "date", "value"]], on=["wmo", "date"], how="left", suffixes=("", "_wb"))
j["in_wb"] = j.value_wb.notna()
wet = (j.value > 0) | (j.value_wb > 0)
print(f"\nstations in catalogue: {j.wmo.nunique()}; with a BMKG workbook: {j[j.wmo.isin(se.wmo)].wmo.nunique()}")
print(f"values {len(j):,}; the workbook has the same station-day: {j.in_wb.mean():.3f}; new station-days: {(~j.in_wb).sum():,}")
b = j[j.in_wb]
print(f"where both: equal within 0.05 mm {((b.value - b.value_wb).abs() <= 0.05).mean():.3f}; on wet days {((b.value - b.value_wb).abs() <= 0.05)[wet[j.in_wb]].mean():.3f}; "
      f"r {np.corrcoef(b.value, b.value_wb)[0, 1]:.3f}")
print("new station-days by year:", j[~j.in_wb].date.dt.year.value_counts().sort_index().to_dict())

# lag check: CH_IND day D against the workbook day D+L, per file
for f in FILES:
    a = k[k.file == f].set_index(["wmo", "date"]).value
    out = []
    for L in (-1, 0, 1):
        o2 = ob.assign(date=ob.date - pd.Timedelta(days=L)).set_index(["wmo", "date"]).value
        jj = pd.concat([a, o2], axis=1, join="inner").dropna()
        jj.columns = ["c", "w"]
        w = (jj.c > 0) | (jj.w > 0)
        out.append(f"lag {L:+d}: n {len(jj):,} r {np.corrcoef(jj.c, jj.w)[0, 1]:.2f} wet-equal {((jj.c - jj.w).abs() <= 0.05)[w].mean():.2f}")
    print(f, " | ".join(out))
