"""Compact list of the PU SIHKA station positions in the build, for the register comparison (F77).

Writes F:/temp/station/pu_sihka/measure/pu_positions_for_register.csv (index, station_key, catalogue name, unit,
position used) and prints the same rows as `i|name|lat|lon` lines, pasted into `tools/compare_pu_register.js`, which runs
in a browser tab on pdsda.sda.pu.go.id (the register refuses scripted requests, HTTP 403, F73).
Names are the SIHKA catalogue names (closer to the register's than the publication headers).
Usage: python tools/export_pu_positions.py
"""
import glob
import json
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
st = pd.read_csv("F:/temp/station/compiled/stations.csv.gz")
p = st[st.source == "pu_sihka"].copy()
cat = json.load(open(sorted(glob.glob("F:/temp/station/pu_sihka/raw/catalogue_*.json"))[-1], encoding="utf-8"))
names = {c["integration_id"]: (c["name"], c.get("unit") or "") for c in cat}
p["cat_name"] = [names.get(k, (n, ""))[0] for k, n in zip(p.source_station_id, p.name)]
p["unit"] = [names.get(k, ("", ""))[1] for k in p.source_station_id]
p = p.sort_values("station_key").reset_index(drop=True)
p.index.name = "i"
p[["station_key", "cat_name", "unit", "name", "lat", "lon", "site_id"]].to_csv(
    "F:/temp/station/pu_sihka/measure/pu_positions_for_register.csv")
print("\n".join(f"{i}|{str(r.cat_name).replace('|', ' ').strip()}|{r.lat:.5f}|{r.lon:.5f}" for i, r in p.iterrows()))
