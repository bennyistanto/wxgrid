"""Evidence for the two crosswalk review pairs raised by the PU SIHKA rebuild (F69).

For each pair: positions, names, elevations; overlap; r at lags -1..+1 on corrected dates; share of equal
wet days; totals ratio; and, as a baseline, the same statistics of each member against other stations
within 25 km (is the pair more alike than ordinary neighbours?).
Reads F:/temp/station/compiled/ only.
Usage: python tools/check_review_pairs_sihka.py
"""
import math
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
C = "F:/temp/station/compiled/"
PAIRS = [("bmkg_xlsx:97052", "pu_sihka:06.13.05040600008"), ("asean_comp:5791130", "pu_sihka:06.13.02180340039")]


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


st = pd.read_csv(C + "stations.csv.gz")
se = pd.read_csv(C + "series.csv.gz", usecols=["series_id", "station_key", "variable", "first", "last"])
se = se[se.variable == "RR"]
S = st.set_index("station_key")
want = set()
near = {}
for a, b in PAIRS:
    la, lo = S.at[a, "lat"], S.at[a, "lon"]
    d = st.assign(d=[km(la, lo, x, y) for x, y in zip(st.lat, st.lon)])
    near[(a, b)] = d[(d.d <= 25) & ~d.station_key.isin([a, b])].sort_values("d")
    want |= {a, b} | set(near[(a, b)].station_key)
ids = se[se.station_key.isin(want)]
ob = pd.concat(c[c.series_id.isin(ids.series_id)] for c in pd.read_csv(C + "observations_RR.csv.gz", usecols=["series_id", "date", "value", "flag"],
                                                                     chunksize=2_000_000, dtype={"flag": str}))
ob = ob[~ob.flag.fillna("").str.contains("qc_excluded|src_duplicate|collision")].merge(ids[["series_id", "station_key"]])
ob["date"] = pd.to_datetime(ob.date)
W = ob.pivot_table(index="date", columns="station_key", values="value", aggfunc="first")


def stats(x, y):
    out = {}
    for L in (-1, 0, 1):
        yy = W[y].shift(-L)
        j = W[x].notna() & yy.notna()
        if j.sum() < 100:
            continue
        a, b = W[x][j], yy[j]
        wet = (a >= 1) | (b >= 1)
        out[L] = dict(n=int(j.sum()), r=float(np.corrcoef(a, b)[0, 1]), eq=float(((a - b).abs() <= 0.5)[wet].mean()), ratio=float(b.sum() / a.sum()) if a.sum() else np.nan)
    return out


for a, b in PAIRS:
    print(f"\n=== {a}  vs  {b}")
    for k in (a, b):
        r = S.loc[k]
        s = se[se.station_key == k]
        print(f"  {k}: {r['name']} | {r.lat:.4f}, {r.lon:.4f} | elev {r.elev_m} | series {s['first'].min()} .. {s['last'].max()}")
    print(f"  distance {km(S.at[a, 'lat'], S.at[a, 'lon'], S.at[b, 'lat'], S.at[b, 'lon']):.2f} km")
    for L, v in stats(a, b).items():
        print(f"  lag {L:+d}: n {v['n']}, r {v['r']:.2f}, equal wet days {v['eq']:.2f}, total ratio {v['ratio']:.2f}")
    print("  baseline: each member vs other stations within 25 km (best lag, >= 100 shared days)")
    for k in (a, b):
        rows = []
        for q, dq in zip(near[(a, b)].station_key, near[(a, b)].d):
            if q not in W or k not in W:
                continue
            s_ = stats(k, q)
            if s_:
                L, v = max(s_.items(), key=lambda kv: kv[1]["r"])
                rows.append((q, S.at[q, "name"], round(km(S.at[k, "lat"], S.at[k, "lon"], S.at[q, "lat"], S.at[q, "lon"]), 1), v["n"], round(v["r"], 2), L, round(v["eq"], 2)))
        rows.sort(key=lambda x: -x[4])
        print(f"   {k}:")
        for x in rows[:6]:
            print(f"     {x[0]} {x[1][:34]:34s} {x[2]:5.1f} km  n {x[3]:5d}  r {x[4]:.2f} (lag {x[5]:+d})  eq {x[6]:.2f}")
