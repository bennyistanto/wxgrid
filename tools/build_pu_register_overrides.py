"""Position table for PU SIHKA posts that disagree with the PU register by more than 1 km (F77, user 2026-11-26:
"Register, except 9").

Rule: a post matched by name to the register (`pch` or `pklim` layer) and > 1 km from it takes the register position,
except the name collision (Merangin: a different post) and the 8 posts where daily rainfall agrees better with
nearby gauges at the SIHKA position by > 0.05 (class `ours_better_r`): those keep the SIHKA position and are flagged
`coord_approx`. Config `coordinates_override` entries (the /qc fixes, F76) take precedence in the reader.
Inputs: F:/temp/station/pu_sihka/measure/register_far_classes.csv (tools/classify_pu_register.py),
register_pklim_far_matches_2026-11-26.txt, pu_positions_for_register.csv.
Writes F:/temp/station/pu_sihka/_register_positions.csv (integration_id, lat, lon, approx, note).
Usage: python tools/build_pu_register_overrides.py
"""
import sys

import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")
M = "F:/temp/station/pu_sihka/measure/"
OUT = "F:/temp/station/pu_sihka/_register_positions.csv"
cls = pd.read_csv(M + "register_far_classes.csv", keep_default_na=False, na_values=[""])
pu = pd.read_csv(M + "pu_positions_for_register.csv", index_col="i")
rows = []
for r in cls.itertuples():
    iid = r.station_key.split(":", 1)[1]
    if r.cls == "name_collision":
        continue
    if r.cls == "ours_better_r":
        rows.append(dict(integration_id=iid, lat=r.lat, lon=r.lon, approx=1,
                         note=f"register pch {r.reg_id} {r.d_km:.1f} km away; rainfall agrees better here (r {r.r_ours:.2f} vs {r.r_reg:.2f})"))
    else:
        rows.append(dict(integration_id=iid, lat=r.reg_lat, lon=r.reg_lon, approx=0,
                         note=f"register pch {r.reg_id} (read 2026-11-26); SIHKA header {r.lat:.5f}, {r.lon:.5f}, {r.d_km:.1f} km; {r.cls}"))
for ln in open(M + "register_pklim_far_matches_2026-11-26.txt", encoding="utf-8"):
    if ln.startswith("#") or not ln.strip():
        continue
    i, rid, name, la, lo, d = ln.strip().split("|")
    p = pu.loc[int(i)]
    rows.append(dict(integration_id=p.station_key.split(":", 1)[1], lat=float(la), lon=float(lo), approx=0,
                     note=f"register pklim {rid} {name} (read 2026-11-26); SIHKA header {p.lat:.5f}, {p.lon:.5f}, {float(d):.1f} km"))
out = pd.DataFrame(rows)
assert not out.integration_id.duplicated().any()
cfg = yaml.safe_load(open("configs/idn_bmkg_sacad.yaml", encoding="utf-8"))
manual = set(next(s for s in cfg["sources"] if s["name"] == "pu_sihka").get("coordinates_override", {}))
print(f"rows {len(out)}: register position {int((out.approx == 0).sum())}, kept and flagged coord_approx {int(out.approx.sum())}; "
      f"also in config overrides (config wins): {sorted(manual & set(out.integration_id))}")
out.to_csv(OUT, index=False)
print("wrote", OUT)
