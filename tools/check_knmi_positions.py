"""Evidence for the KNMI station positions marked [to verify] (F74): Medan I / Medan, Medan II, Tanjung Karang.

For each KNMI station: its site, years, annual mean and wet-day share by period, and daily RR agreement
(r at lags -1/0/+1, share of equal wet days, total ratio) with every other gauge within 60 km that overlaps it by
>= 200 days, plus the two Medan KNMI series with each other. Medan I (1880-1897) and Medan (1898-1916) share the key
MEDAN, so the Medan series is split at 1898 to test whether both halves relate to the neighbours the same way.
Reads F:/temp/station/compiled/ only. Usage: python tools/check_knmi_positions.py
"""
import math
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
C = "F:/temp/station/compiled/"


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


st = pd.read_csv(C + "stations.csv.gz")
se = pd.read_csv(C + "series.csv.gz", usecols=["series_id", "station_key", "variable", "first", "last", "n_values"])
se = se[se.variable == "RR"]
kn = st[st.source == "knmi"]
print(kn[["station_key", "name", "lat", "lon", "site_id"]].to_string(index=False))
sites = st[st.site_id.isin(kn.site_id)].groupby("site_id").station_key.apply(list)
print("\nsites holding KNMI stations with other members:", {k: v for k, v in sites.items() if len(v) > 1})

focus = ["knmi:MEDAN", "knmi:MEDAN_II", "knmi:TANJUNG_KARANG"]
early = se[pd.to_datetime(se["first"]) < "1917-01-01"]
cand = {}
for k in focus:
    r = st[st.station_key == k].iloc[0]
    o = st[st.station_key.isin(early.station_key) & (st.station_key != k)].copy()
    o["d"] = [km(r.lat, r.lon, a, b) for a, b in zip(o.lat, o.lon)]
    cand[k] = o[o.d <= 60].sort_values("d")
    print(f"\n{k}: gauges within 60 km with data before 1917:\n" + cand[k][["station_key", "name", "lat", "lon", "d", "site_id"]].round(3).to_string(index=False))

ids = set(se[se.station_key.isin(set(focus) | set().union(*[set(c.station_key) for c in cand.values()]))].series_id)
ob = pd.concat(c[c.series_id.isin(ids)] for c in pd.read_csv(C + "observations_RR.csv.gz", usecols=["series_id", "date", "value", "flag"],
                                                             chunksize=3_000_000, dtype={"flag": str}))
ob = ob[~ob.flag.fillna("").str.contains("qc_excluded|src_duplicate|collision")].dropna(subset=["value"])
ob["date"] = pd.to_datetime(ob.date)
ob = ob[ob.date < "1920-01-01"]
W = ob.pivot_table(index="date", columns="series_id", values="value", aggfunc="first")
if "knmi:MEDAN:RR" in W:
    W["MEDAN_I(<1898)"] = W["knmi:MEDAN:RR"].where(W.index < "1898-01-01")
    W["MEDAN(>=1898)"] = W["knmi:MEDAN:RR"].where(W.index >= "1898-01-01")

print("\nPer series before 1920: years, mean annual total (complete years), wet-day share (>= 1 mm)")
for c in W.columns:
    x = W[c].dropna()
    if x.empty:
        continue
    yr = x.groupby(x.index.year)
    full = yr.count() >= 330
    ann = yr.sum()[full].mean() if full.any() else np.nan
    print(f"  {c}: {x.index.min().date()}..{x.index.max().date()}, n {len(x)}, annual {ann:.0f} mm, wet {(x >= 1).mean():.2f}")


def agree(a, b):
    out = {}
    for L in (-1, 0, 1):
        y = W[b].shift(-L)
        j = W[a].notna() & y.notna()
        if j.sum() < 200:
            continue
        x, yy = W[a][j], y[j]
        wet = (x >= 1) | (yy >= 1)
        out[L] = (int(j.sum()), np.corrcoef(x, yy)[0, 1], float(((x - yy).abs() <= 0.5)[wet].mean()), yy.sum() / x.sum())
    if not out:
        return None
    bl = max(out, key=lambda k: out[k][1])
    return f"n {out[bl][0]}, r " + " / ".join(f"{out[k][1]:.2f}" if k in out else "-" for k in (-1, 0, 1)) + \
           f", best lag {bl:+d}, equal wet {out[bl][2]:.2f}, ratio {out[bl][3]:.2f}"


print("\nDaily agreement (r at lags -1/0/+1):")
heads = {"knmi:MEDAN": ["MEDAN_I(<1898)", "MEDAN(>=1898)", "knmi:MEDAN_II:RR"], "knmi:MEDAN_II": ["knmi:MEDAN_II:RR"],
         "knmi:TANJUNG_KARANG": ["knmi:TANJUNG_KARANG:RR"]}
done = set()
for k, cols in heads.items():
    others = [s for s in W.columns if s.count(":") >= 2 and ":".join(s.split(":")[:2]) in set(cand[k].station_key)]
    for a in cols:
        for b in others + [c for c in cols if c != a]:
            if a not in W or b not in W or (b, a) in done:
                continue
            done.add((a, b))
            res = agree(a, b)
            if res:
                print(f"  {a} vs {b}: {res}")
