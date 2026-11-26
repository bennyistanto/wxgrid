"""What do the text codes TU and TTU mean in the national CH_IND daily rain sheets?

The `chind` reader (station_month_grid) skips any text cell, so these were dropped uncounted.
Here every day cell of the CH_IND year files (NO STA | STA | TAHUN | BULAN | R1..R31) is
classified (positive, zero, TU, TTU, 9999, 8888, other text), placed at the station's WMO
coordinates (_wmo_catalogue.csv, wmo = 96000 + NO STA), and compared with CPC-UNI daily rain
(1979+, lag chosen per station by the highest wet fraction on positive days).
If TU/TTU were "no rain", CPC would be as dry on those days as on zero days; if "no data",
CPC would look like all days; if "trace", wet but light.
Output: F:/temp/station/additional_recheck/tu_codes.csv and a printed table.
Usage: python tools/measure_tu_codes.py
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.stdout.reconfigure(encoding="utf-8")
DUMP = Path("F:/temp/station/additional_recheck/dump")
FILES = ["DATA_IKLIM_CH_IND_1995.XLS.txt", "DATA_IKLIM_CH_IND_1998.XLS.txt", "DATA_IKLIM_CH_IND_1999.xls.txt",
         "DATA_IKLIM_CH_IND_2000.xls.txt", "DATA_IKLIM_CH_IND_2001.xls.txt", "DATA_IKLIM_CH_IND_1996.xls.txt"]
cat = pd.read_csv("F:/temp/station/additional-sources/_wmo_catalogue.csv").set_index("wmo")
cpc = xr.open_dataset("F:/temp/station/cpc/idn_cpc_1979_2025.nc").precip


def cls(s):
    s = s.strip().upper().rstrip(".")
    if s == "":
        return "blank"
    if s in ("TU", "TTU", "TT", "X", "-"):
        return s
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        v = float(s)
        return {9999: "9999", 8888: "8888"}.get(v, "zero" if v == 0 else "pos")
    return "text"


rows = []
for fn in FILES:
    hdr = None
    for line in (DUMP / fn).open(encoding="utf-8"):
        if not line.startswith("r"):
            continue
        c = line.rstrip("\n").split("\t")[1:]
        u = [x.strip().upper().replace(" ", "") for x in c]
        if hdr is None:
            if "R1" in u:
                hdr = dict(id=next(i for i, x in enumerate(u) if x in ("NOSTA",)), y=u.index("TAHUN"), m=u.index("BULAN"), r1=u.index("R1"))
            continue
        try:
            no, y, m = int(float(c[hdr["id"]])), int(float(c[hdr["y"]])), int(float(c[hdr["m"]]))
        except (ValueError, IndexError):
            continue
        wmo = no if no > 90000 else 96000 + no
        for d in range(31):
            k = hdr["r1"] + d
            raw = c[k] if k < len(c) else ""
            try:
                date = pd.Timestamp(y, m, d + 1)
            except ValueError:
                continue
            rows.append((fn[18:-4], wmo, date, cls(raw), raw.strip()))
d = pd.DataFrame(rows, columns=["file", "wmo", "date", "cls", "raw"])
print("cells by class:", d.cls.value_counts().to_dict())
print("TU / TTU by file:", d[d.cls.isin(["TU", "TTU"])].groupby(["file", "cls"]).size().to_dict())
out = []
for wmo, g in d[d.cls.isin(["TU", "TTU", "zero", "pos", "9999", "8888", "-", "blank"])].groupby("wmo"):
    if wmo not in cat.index or not (g.cls == "TU").any() and not (g.cls == "TTU").any():
        continue
    ser = cpc.sel(lat=cat.loc[wmo, "lat"], lon=cat.loc[wmo, "lon"], method="nearest").to_series()
    best = max((-1, 0, 1), key=lambda L: np.nanmean(ser.reindex(g[g.cls == "pos"].date + pd.Timedelta(days=L)).to_numpy() >= 1))
    g = g.assign(cpc=ser.reindex(g.date + pd.Timedelta(days=best)).to_numpy())
    out.append(g.assign(lag=best))
o = pd.concat(out)
o = o[o.cpc.notna()]
t = o.groupby("cls").agg(n=("cpc", "size"), stations=("wmo", "nunique"), cpc_wet_frac=("cpc", lambda c: round(float((c >= 1).mean()), 3)),
                         cpc_mean_mm=("cpc", lambda c: round(float(c.mean()), 2)), cpc_median_mm=("cpc", lambda c: round(float(c.median()), 2)))
print("\nCPC on each cell class, at stations that use TU or TTU:")
print(t.to_string())
# do TU stations also write 0? (if TU were 'no rain', a station would rarely need both)
both = d.groupby("wmo").cls.agg(lambda c: ((c == "TU").sum(), (c == "zero").sum()))
both = pd.DataFrame(both.tolist(), index=both.index, columns=["tu", "zero"])
b = both[both.tu > 0]
print(f"\nstations with TU: {len(b)}; of those also writing 0: {(b.zero > 0).sum()}; median TU share of their TU+0 cells: "
      f"{(b.tu / (b.tu + b.zero)).median():.2f}")
t.to_csv("F:/temp/station/additional_recheck/tu_codes.csv")
