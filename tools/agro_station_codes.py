"""Collect the station code ("No. Sta.") written in each parsed agro sheet and look it up
in the BMKG rain-post catalogue (POS-HUJAN, from STA-BMG.XLS), whose ids are a 2-digit
region prefix + the 3-digit code + optional letter (e.g. Jakenan 179 -> 10179).

Run: python tools/agro_station_codes.py   -> F:/temp/station/additional-sources/_agro_station_codes.csv
"""
import collections
import re
from pathlib import Path

import pandas as pd
import xlrd

B = Path("F:/temp/station/additional-sources")
S = pd.read_csv(B / "_agro_raw_sheets_coords.csv")
codes = collections.defaultdict(collections.Counter)
for (f, sn), st in S.groupby(["file", "sheet"])["station"].first().items():
    wb = xlrd.open_workbook(str(B / "Data Stasiun" / f), on_demand=True)
    sh = wb.sheet_by_name(sn)
    hrow = next((r for r in range(min(4, sh.nrows))
                 if any("LINTANG" in str(sh.cell_value(r, c)).upper() for c in range(sh.ncols))), 0)
    hdr = [re.sub(r"[^A-Z]", "", str(sh.cell_value(hrow, c)).upper()) for c in range(sh.ncols)]
    cc = next((i for i, h in enumerate(hdr) if h in ("NO", "NOSTA", "NOSTAT")), None)
    if cc is not None:
        for r in range(hrow + 1, min(hrow + 6, sh.nrows)):
            a = sh.cell_value(r, cc)
            b = sh.cell_value(r, cc + 1) if cc + 1 < sh.ncols else ""
            if a == "":
                continue
            a = str(int(a)) if isinstance(a, float) and a.is_integer() else str(a).strip()
            b = b.strip() if isinstance(b, str) and len(b.strip()) == 1 else ""
            if a.upper() not in ("STA", "STA.", "NO"):
                codes[st][(a + b).upper()] += 1
            break
    wb.release_resources()

P = pd.read_csv(B / "_poshujan_catalogue.csv", dtype={"id": str})
rows = []
for st in sorted(S["station"].dropna().unique()):
    c = codes.get(st, collections.Counter())
    hits = []
    for k, _ in c.most_common(3):
        m = re.match(r"(\d+)([A-Z]?)$", k)
        if not m:
            continue
        num, suf = m.group(1).zfill(3), m.group(2)
        for _, r in P[P["id"].str.match(rf"^\d{{2}}{num}{suf}$")].iterrows():
            hits.append(dict(code=k, cat_id=r["id"], cat_name=r["name"], cat_lat=r["lat"], cat_lon=r["lon"],
                             cat_elev=r["elev"]))
    rows.append(dict(station=st, codes=dict(c.most_common(4)), n_hits=len(hits),
                     hits="; ".join(f"{h['cat_id']} {h['cat_name']} ({h['cat_lat']:.3f},{h['cat_lon']:.3f})" for h in hits[:5])))
out = pd.DataFrame(rows)
out.to_csv(B / "_agro_station_codes.csv", index=False)
pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 140)
print(out.to_string(index=False))
