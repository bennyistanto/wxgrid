"""Evidence for the review pairs on WMO 97146 (F72): chind:97146 vs sacad_synop:997146 and ghcnd:ID000097146, 26 km apart.

Prints every station carrying WMO 97146 or lying within 30 km, their positions and sources, where chind's position comes
from (`_wmo_catalogue.csv`), and RR agreement (r at lags -1..+1, equal wet days, total ratio) between all pairs.
Reads F:/temp/station/compiled/ only.
Usage: python tools/check_wmo_97146.py
"""
import math
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
C = "F:/temp/station/compiled/"


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


st = pd.read_csv(C + "stations.csv.gz")
ref = st[st.station_key == "chind:97146"].iloc[0]
st["d_chind"] = [km(ref.lat, ref.lon, a, b) for a, b in zip(st.lat, st.lon)]
syn = st[st.station_key == "sacad_synop:997146"].iloc[0]
st["d_synop"] = [km(syn.lat, syn.lon, a, b) for a, b in zip(st.lat, st.lon)]
pick = st[(st.wmo_id.astype(str).str.replace(".0", "", regex=False) == "97146") | (st.d_chind <= 30) | (st.d_synop <= 30)]
pd.set_option("display.width", 250)
print(pick[["station_key", "name", "lat", "lon", "elev_m", "wmo_id", "site_id", "d_chind", "d_synop"]].round(3).to_string(index=False))
cat = pd.read_csv("F:/temp/station/additional-sources/_wmo_catalogue.csv")
print("\n_wmo_catalogue row for 97146:", cat[cat.wmo == 97146].to_dict("records"))
se = pd.read_csv(C + "series.csv.gz")
ids = se[se.station_key.isin(pick.station_key) & (se.variable == "RR")][["series_id", "station_key", "first", "last", "n_values"]]
print("\nRR series:\n" + ids.to_string(index=False))
ob = pd.concat(c[c.series_id.isin(ids.series_id)] for c in pd.read_csv(C + "observations_RR.csv.gz", usecols=["series_id", "date", "value", "flag"],
                                                                     chunksize=3_000_000, dtype={"flag": str}))
ob = ob[~ob.flag.fillna("").str.contains("src_duplicate|qc_excluded|collision")].dropna(subset=["value"])
ob["date"] = pd.to_datetime(ob.date)
W = ob.pivot_table(index="date", columns="series_id", values="value", aggfunc="first")
print("\nRR agreement on corrected dates (n, r at lags -1/0/+1, equal wet days at best lag, total ratio):")
cols = list(W.columns)
for i, a in enumerate(cols):
    for b in cols[i + 1:]:
        out = {}
        for L in (-1, 0, 1):
            y = W[b].shift(-L)
            j = W[a].notna() & y.notna()
            if j.sum() < 100:
                continue
            x, yy = W[a][j], y[j]
            wet = (x >= 1) | (yy >= 1)
            out[L] = (int(j.sum()), np.corrcoef(x, yy)[0, 1], float(((x - yy).abs() <= 0.5)[wet].mean()), yy.sum() / x.sum())
        if out:
            bl = max(out, key=lambda k: out[k][1])
            print(f"  {a} vs {b}: n {out[bl][0]}, r " + " / ".join(f"{out[k][1]:.2f}" if k in out else "-" for k in (-1, 0, 1))
                  + f", best lag {bl:+d}, equal wet {out[bl][2]:.2f}, ratio {out[bl][3]:.2f}")
