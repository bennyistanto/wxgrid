"""Sort the PU SIHKA vs register position disagreements (> 1 km, F77) into evidence classes.

Reads F:/temp/station/pu_sihka/measure/register_far_assessment.csv (tools/measure_pu_register.py) and
register_far_nearest_km_2026-11-26.txt; writes register_far_classes.csv. Read only. Classes, first that applies:
  name_collision     SIHKA unit and register office differ: two different posts share a name; the SIHKA position is kept
  ours_at_sea        the SIHKA position is off land, the register's is on land
  ours_copied        the SIHKA position is another post's: shared (< 50 m) with another PU post in the build, or < 50 m
                     from a different register post
  one_coordinate     one coordinate agrees within 0.002 deg and the other differs by > 0.04 deg (a typing slip on one side)
  register_better_r  daily-rainfall r with nearby gauges higher at the register position by > 0.05
  ours_better_r      higher at the SIHKA position by > 0.05
  unresolved         nothing decisive
Usage: python tools/classify_pu_register.py
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
M = "F:/temp/station/pu_sihka/measure/"
a = pd.read_csv(M + "register_far_assessment.csv", keep_default_na=False, na_values=[""])
nd = dict(x.split("|") for x in open(M + "register_far_nearest_km_2026-11-26.txt", encoding="utf-8").read().split("\n")[1].split(";"))
a["near_km"] = a.i.astype(str).map(nd).astype(float)
dlat, dlon = (a.lat - a.reg_lat).abs(), (a.lon - a.reg_lon).abs()
dr = a.r_reg - a.r_ours


def cls(k):
    r = a.loc[k]
    if not r.office_agree:
        return "name_collision"
    if not r.ours_land and r.reg_land:
        return "ours_at_sea"
    if (isinstance(r.ours_shared_with, str) and r.ours_shared_with) or r.near_km < 0.05:
        return "ours_copied"
    if (dlat[k] < 0.002 and dlon[k] > 0.04) or (dlon[k] < 0.002 and dlat[k] > 0.04):
        return "one_coordinate"
    if dr[k] > 0.05:
        return "register_better_r"
    if dr[k] < -0.05:
        return "ours_better_r"
    return "unresolved"


a["cls"] = [cls(k) for k in a.index]
a["band"] = pd.cut(a.d_km, [1, 5, 25, 1e4], labels=["1-5 km", "5-25 km", "> 25 km"])
a.to_csv(M + "register_far_classes.csv", index=False)
print(pd.crosstab(a.cls, a.band, margins=True).to_string())
pd.set_option("display.width", 220, "display.max_rows", 300)
for c in ["name_collision", "ours_at_sea", "ours_copied", "one_coordinate", "ours_better_r"]:
    s = a[a.cls == c]
    print(f"\n{c} ({len(s)}): " + "; ".join(f"{n} {d:.1f} km" + (f" r {ro:.2f}/{rr:.2f}" if pd.notna(ro) and pd.notna(rr) else "")
                                    for n, d, ro, rr in zip(s.cat_name, s.d_km, s.r_ours, s.r_reg)))
