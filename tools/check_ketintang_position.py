"""After the Ketintang override (F65): position, site, summary diff vs `_before_ketintang/`, and RR correlation with posts within 12 km.
Usage: python tools/check_ketintang_position.py"""
import json
import math

import pandas as pd

C = "F:/temp/station/compiled/"
KEY = "jatim:158_KETINTANG"


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


s = pd.read_csv(C + "stations.csv.gz")
old = pd.read_csv(C + "_before_ketintang/stations.csv.gz")
k = s[s.station_key == KEY].iloc[0]
print("now:", k.lat, k.lon, k.site_id, "| before:", old[old.station_key == KEY][["lat", "lon", "site_id"]].values.tolist())
m = s.merge(old[["station_key", "lat", "lon"]], on="station_key", suffixes=("", "_old"))
print("stations with a changed position:", m[(m.lat != m.lat_old) | (m.lon != m.lon_old)].station_key.tolist())
a, b = json.load(open(C + "summary.json")), json.load(open(C + "_before_ketintang/summary.json"))


def flat(d, p=""):
    for x, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, p + x + ".")
        else:
            yield p + x, v


fa, fb = dict(flat(a)), dict(flat(b))
print("summary changes:", {x: (fb.get(x), fa[x]) for x in fa if fa[x] != fb.get(x) and "time" not in x and "date" not in x})
sa, sb = pd.read_csv(C + "sites.csv"), pd.read_csv(C + "_before_ketintang/sites.csv")
print("sites:", len(sb), "->", len(sa))
print("Ketintang site row now:", sa[sa.site_id == k.site_id].to_dict("records"))
s["d"] = [km(k.lat, k.lon, la, lo) for la, lo in zip(s.lat, s.lon)]
near = s[(s.d <= 12) & (s.station_key != KEY)].sort_values("d")
ser = pd.read_csv(C + "series.csv.gz")
ser = ser[ser.variable == "RR"]
ids = ser[ser.station_key.isin([KEY] + near.station_key.tolist())][["series_id", "station_key"]]
obs = pd.concat(c[c.series_id.isin(ids.series_id)] for c in pd.read_csv(C + "observations_RR.csv.gz", usecols=["series_id", "date", "value"], chunksize=2_000_000))
obs = obs.merge(ids, on="series_id")
w = obs.pivot_table(index="date", columns="station_key", values="value", aggfunc="first")
rows = []
for q, dq in zip(near.station_key, near.d):
    if q in w:
        x = w[[KEY, q]].dropna()
        if len(x) >= 300:
            rows.append((q, round(dq, 1), len(x), round(x[KEY].corr(x[q]), 2),
                         round(km(old[old.station_key == KEY].lat.iloc[0], old[old.station_key == KEY].lon.iloc[0],
                                  *s[s.station_key == q][["lat", "lon"]].iloc[0]), 1)))
print(pd.DataFrame(rows, columns=["neighbour", "km_new", "n", "r", "km_sheet_pos"]).to_string(index=False))
