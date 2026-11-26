"""Scan a sheet's daily rainfall against neighbouring gauges (and CPC from 1979) at several
candidate stations and every candidate year, to find where and when the data belong.
Also flags exact copies of the sheet in any other sheet, regardless of year.

Run: python tools/agro_scan_year.py "KUNINGAN/KNG73-86.XLS" "KNG-81" Kuningan Maros
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agro_refs import C, R, S, cell, cpc_series, rbest, rnb  # noqa: E402

f, sh, *stations = sys.argv[1:]
s = R[(R["file"] == f) & (R["sheet"] == sh)].set_index("date")["value"].sort_index()
y0 = int(pd.Series(s.index.year).mode().iat[0])
print(f"{f} [{sh}] parsed year {y0}, {len(s)} rain days, total {s.sum():.0f} mm")
rows = []
for st in stations:
    lat, lon = C.loc[st, "lat"], C.loc[st, "lon"]
    for y in range(1973, 1995):
        t = s.copy()
        t.index = t.index + pd.DateOffset(years=y - y0)
        nb = rnb(t, lat, lon)
        cp = rbest(t, cpc_series(*cell(lat, lon)))[0] if y >= 1979 else np.nan
        rows.append(dict(station=st, year=y, nb_r=nb[0], nb_site=nb[1], cpc_r=cp))
T = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(T.sort_values("nb_r", ascending=False).head(8).round(3).to_string(index=False))
# exact copies anywhere (match on month-day)
key = s.copy(); key.index = key.index.strftime("%m-%d")
hits = []
for (ff, ss), g in R.groupby(["file", "sheet"]):
    if (ff, ss) == (f, sh):
        continue
    o = g.set_index("date")["value"]; o.index = o.index.strftime("%m-%d")
    o = o[~o.index.duplicated()]
    j = key.index.intersection(o.index)
    if len(j) >= 60 and ((key[j] > 0) | (o[j] > 0)).sum() >= 20:
        eq = np.isclose(key[j], o[j]).mean()
        if eq >= 0.9:
            stn = S.loc[(S["file"] == ff) & (S["sheet"] == ss), "station"]
            hits.append((ff, ss, stn.iat[0] if len(stn) else "", int(g["date"].dt.year.mode()[0]), len(j), round(eq, 3)))
print("exact copies (any year):", hits if hits else "none")
