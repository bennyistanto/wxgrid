"""Before/after check for the PU register positions (F77): what moved, what it did to sites and day labels.

Compares F:/temp/station/compiled/_before_register/ (copied before the rebuild) with the current build.
Reports: PU stations moved and by how much; how many PU sites changed members; PU-PU / PU-jatim joins made or
broken; day-label status share for the moved posts' series; summary counts (stations, sites, needs_review).
Read only. Usage: python tools/check_register_adoption.py
"""
import json
import math
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
C = "F:/temp/station/compiled/"
B = C + "_before_register/"


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


s0, s1 = pd.read_csv(B + "stations.csv.gz"), pd.read_csv(C + "stations.csv.gz")
p = s0[s0.source == "pu_sihka"].merge(s1[s1.source == "pu_sihka"], on="station_key", suffixes=("_0", "_1"), how="outer", indicator=True)
print("PU stations before/after:", p._merge.value_counts().to_dict())
both = p[p._merge == "both"].copy()
both["moved_km"] = [km(a, b, c, d) for a, b, c, d in zip(both.lat_0, both.lon_0, both.lat_1, both.lon_1)]
mv = both[both.moved_km > 0.01]
print(f"moved {len(mv)}: median {mv.moved_km.median():.1f} km, > 5 km {int((mv.moved_km > 5).sum())}, > 25 km {int((mv.moved_km > 25).sum())}")

# site membership of PU stations
mem0 = s0.set_index("station_key").site_id
mem1 = s1.set_index("station_key").site_id
grp0 = s0.groupby("site_id").station_key.apply(frozenset)
grp1 = s1.groupby("site_id").station_key.apply(frozenset)
pu = set(p.station_key)
g0 = {grp0[mem0[k]] for k in pu if k in mem0.index}
g1 = {grp1[mem1[k]] for k in pu if k in mem1.index}
multi0 = {g for g in g0 if len(g) > 1}
multi1 = {g for g in g1 if len(g) > 1}
print(f"PU sites with > 1 station: before {len(multi0)}, after {len(multi1)}; joins made {len(multi1 - multi0)}, broken {len(multi0 - multi1)}")
for tag, gs in (("made", multi1 - multi0), ("broken", multi0 - multi1)):
    for g in sorted(gs, key=lambda x: sorted(x)):
        names = s1.set_index("station_key").name.reindex(sorted(g)).fillna("?")
        print(f"  {tag}: " + "; ".join(f"{k} ({n})" for k, n in names.items()))

# day labels for the moved posts
d0, d1 = pd.read_csv(B + "daylabel_segments.csv"), pd.read_csv(C + "daylabel_segments.csv")
ids = tuple(f"{k}:" for k in mv.station_key)
for tag, d in (("before", d0), ("after", d1)):
    x = d[d.series_id.str.startswith(ids)].copy()
    x["days"] = (pd.to_datetime(x.end) - pd.to_datetime(x.start)).dt.days + 1
    share = (x.groupby("status").days.sum() / x.days.sum()).round(3).to_dict()
    print(f"day-label status of moved posts' series, {tag}: {share}")

j0, j1 = json.load(open(B + "summary.json")), json.load(open(C + "summary.json"))
for k in ("n_stations", "n_sites", "n_series", "needs_review"):
    print(f"{k}: {j0[k]} -> {j1[k]}")
