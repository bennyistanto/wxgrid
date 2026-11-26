"""QC follow-up on copies found by tools/qc_phase2_audit.py (section 4, identical 7-day windows).

For each pair: share of equal values on days where either reads >= 1 mm, by year, at lag 0 and at
the lags the window test found; r with CPC-UNI per year for both members (station D <-> CPC D-1)
to tell which position fits the data; and how many merged_RR site-days each member supplies.
Run: python tools/qc_copy_checks.py
"""
import numpy as np
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250)
o = q.obs_rr(); m = q.merged_rr()
st = q.stations().set_index("station_key"); se = q.series().set_index("series_id")
cpc = q.CPCField()


def g(s, col="date_raw"):
    x = o[(o.series_id == s) & ~o.flag.astype(str).str.contains("src_duplicate")].set_index(col).value
    return x[~x.index.duplicated()]


def eq_by_year(a, b, lag=0):
    x, y = g(a), g(b)
    y = y.reindex(x.index + pd.Timedelta(days=lag)); y.index = x.index
    j = pd.concat([x, y], axis=1, keys=["a", "b"]).dropna()
    j = j[(j.a >= 1) | (j.b >= 1)]
    return (j.a == j.b).groupby(j.index.year).mean().round(2)


def cpc_r_by_year(s, lat=None, lon=None):
    x = g(s, "date")
    sk = se.loc[s, "station_key"]
    la, lo = (st.loc[sk, "lat"], st.loc[sk, "lon"]) if lat is None else (lat, lon)
    c = cpc.series(la, lo); c.index = c.index + pd.Timedelta(days=1)
    j = pd.concat([x, c.reindex(x.index)], axis=1).dropna()
    return j.groupby(j.index.year).apply(lambda d: round(d.corr().iloc[0, 1], 2) if len(d) > 60 else np.nan)


PAIRS = [("larantuka:Larantuka:RR", "bmkg_xlsx:97310:RR", [0, -365, -366, 10]),
         ("fklim_sumatera:96161:RR", "bmkg_xlsx:96167:RR", [0]),
         ("sumbar_daily:|Teluk_Bayur:RR", "bmkg_xlsx:96161:RR", [0]),
         ("sumbar_daily:|Sumpur_Kudus:RR", "sumbar_daily:|Kumanis:RR", [0]),
         ("sumbar_daily:50D|Rambatan:RR", "agro:RAMBATAN:RR", [0, -1]),
         ("sumbar_daily:36B|KPTP_Sitiung_P_Punjung_Sijunjung:RR", "agro:GUNUNGMEDAN:RR", [0, -1]),
         ("sumbar_daily:|Sukarami:RR", "agro:SUKARAMI:RR", [0, -1]),
         ("bmg_posts:Patas:RR", "asean_comp:5821480:RR", [0])]
for a, b, lags in PAIRS:
    print(f"\n{a}  vs  {b}  ({q.haversine_km(*st.loc[se.loc[a,'station_key'],['lat','lon']], *st.loc[se.loc[b,'station_key'],['lat','lon']]):.1f} km)")
    for L in lags:
        print(f"  equal share of wet days by year, lag {L:+d}: {eq_by_year(a, b, L).to_dict()}")
    print(f"  CPC r by year, {a.split(':')[0]} at own position: {cpc_r_by_year(a).to_dict()}")
    print(f"  CPC r by year, {a.split(':')[0]} at partner position: {cpc_r_by_year(a, *st.loc[se.loc[b,'station_key'],['lat','lon']]).to_dict()}")
    print(f"  CPC r by year, {b.split(':')[0]} at own position: {cpc_r_by_year(b).to_dict()}")
    for s in (a, b):
        mm = m[m.series_id == s]
        print(f"  merged_RR site-days from {s}: {len(mm)} at {mm.site_id.astype(str).unique().tolist()} ({mm.date.min()} - {mm.date.max()})")
