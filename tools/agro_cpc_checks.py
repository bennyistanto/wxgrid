"""Rainfall-fingerprint checks for the agro collection against CPC-UNI daily (0.5 deg, 1979+).
Daily correlation of a sheet's rainfall with the CPC cell is taken as the best of lags
-1/0/+1 (the agro day convention is not documented). Four checks:

  A. location: per station, r at the catalogue cell vs the best cell within +-3 deg;
  B. identity: sheets whose name cell names a different station than the file -> r at both
     stations' catalogue cells, same year;
  C. year: sheets whose Tahun cell disagrees with the file/sheet name -> r for both years;
  D. copies: sheet pairs of the same year whose daily rainfall is identical on >= 90% of
     shared wet-or-dry days (>= 60 shared days).

Decision margins are reported, not hidden: a choice is called only when r >= 0.15 and the
margin over the alternative is >= 0.10; otherwise it is "ambiguous".

Run: python tools/agro_cpc_checks.py   (needs _agro_raw_records.csv.gz, _agro_raw_sheets_coords.csv,
     _agro_station_catalogue.csv, F:/temp/station/cpc/idn_cpc_1979_2025.nc)
"""
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agro_refs import *  # noqa: E402,F401,F403

series = {k: g.set_index("date")["value"] for k, g in R.groupby(["file", "sheet"])}

# A. location per station
outA = []
for st, g in S.groupby("station"):
    keys = [(f, sh) for f, sh in zip(g["file"], g["sheet"]) if (f, sh) in series]
    if not keys or st not in C.index:
        continue
    s = pd.concat([series[k] for k in keys])
    s = s[~s.index.duplicated()].sort_index()
    s = s[s.index >= "1979-01-01"]
    lat, lon = C.loc[st, "lat"], C.loc[st, "lon"]
    if len(s) < 300 or pd.isna(lat):
        outA.append(dict(station=st, n_days=len(s), note="too few days after 1979 or no coordinate"))
        continue
    i0, j0 = cell(lat, lon)
    r0, lag0, n0 = rbest(s, cpc_series(i0, j0))
    best = (r0, i0, j0)
    for i in range(max(0, i0 - 6), min(len(LATS), i0 + 7)):
        for j in range(max(0, j0 - 6), min(len(LONS), j0 + 7)):
            r, _, _ = rbest(s, cpc_series(i, j))
            if not np.isnan(r) and r > best[0]:
                best = (r, i, j)
    s_full = pd.concat([series[k] for k in keys]); s_full = s_full[~s_full.index.duplicated()].sort_index()
    nbr = rnb(s_full, lat, lon)
    outA.append(dict(station=st, n_days=n0, nb_r=round(nbr[0], 3) if not np.isnan(nbr[0]) else np.nan,
                     nb_site=nbr[1], nb_km=nbr[2], r_catalogue=round(r0, 3), lag=lag0,
                     r_best=round(best[0], 3), best_lat=float(LATS[best[1]]), best_lon=float(LONS[best[2]]),
                     best_km=round(km(lat, lon, LATS[best[1]], LONS[best[2]])), coord_source=C.loc[st, "coord_source"]))
A = pd.DataFrame(outA)

# alternative locations worth testing explicitly (sheet votes that disagree with the catalogue)
alts = {"Lampineung": (-1.083, 101.667), "Kendalpayak": (-9.083, 112.467), "Tamanbogo": (-6.033, 105.667),
        "Ngale": (-7.95, 111.433), "Pacet": (-6.75, 107.75), "Lanrang": (-5.0, 119.667)}
outA2 = []
for st, (la, lo) in alts.items():
    g = S[S["station"] == st]
    keys = [(f, sh) for f, sh in zip(g["file"], g["sheet"]) if (f, sh) in series]
    if not keys:
        continue
    s = pd.concat([series[k] for k in keys]); s = s[~s.index.duplicated()].sort_index()
    s = s[s.index >= "1979-01-01"]
    ra = rbest(s, cpc_series(*cell(C.loc[st, "lat"], C.loc[st, "lon"])))[0]
    rb = rbest(s, cpc_series(*cell(la, lo)))[0]
    s2 = pd.concat([series[k] for k in keys]); s2 = s2[~s2.index.duplicated()].sort_index()
    na = rnb(s2, C.loc[st, "lat"], C.loc[st, "lon"]); nb = rnb(s2, la, lo)
    outA2.append(dict(station=st, catalogue=(C.loc[st, "lat"], C.loc[st, "lon"]), cpc_r_catalogue=round(ra, 3),
                      sheet_vote=(la, lo), cpc_r_vote=round(rb, 3) if not np.isnan(rb) else np.nan,
                      nb_r_catalogue=na[0], nb_r_vote=nb[0],
                      verdict_cpc=decide(ra, rb, "catalogue", "sheet vote"),
                      verdict_nb=decide(na[0], nb[0], "catalogue", "sheet vote")))
A2 = pd.DataFrame(outA2)

# B. identity disputes
outB = []
for _, r in S.iterrows():
    fs, ns = r["station"], name_to_station(r["name_cell"])
    if not ns or ns == fs or (r["file"], r["sheet"]) not in series:
        continue
    s = series[(r["file"], r["sheet"])]
    s = s[s.index >= "1979-01-01"]
    ra = rbest(s, cpc_series(*cell(C.loc[fs, "lat"], C.loc[fs, "lon"])))[0] if len(s) else np.nan
    rb = rbest(s, cpc_series(*cell(C.loc[ns, "lat"], C.loc[ns, "lon"])))[0] if len(s) else np.nan
    s_all = series[(r["file"], r["sheet"])]
    na = rnb(s_all, C.loc[fs, "lat"], C.loc[fs, "lon"])
    nb = rnb(s_all, C.loc[ns, "lat"], C.loc[ns, "lon"])
    outB.append(dict(file=r["file"], sheet=r["sheet"], year=r["year"], file_station=fs, name_cell=r["name_cell"],
                     name_station=ns, cpc_r_file=round(ra, 3), cpc_r_name=round(rb, 3),
                     nb_r_file=round(na[0], 3) if not np.isnan(na[0]) else np.nan,
                     nb_r_name=round(nb[0], 3) if not np.isnan(nb[0]) else np.nan,
                     verdict_cpc=decide(ra, rb, fs, ns), verdict_nb=decide(na[0], nb[0], fs, ns)))
Bd = pd.DataFrame(outB)

# C. year conflicts
outC = []
for _, r in S[S["notes"].fillna("").str.contains("year conflict")].iterrows():
    k = (r["file"], r["sheet"])
    if k not in series or pd.isna(r["year_cell"]) or pd.isna(r["year_hint"]):
        continue
    s = series[k]; st = r["station"]
    ref = cpc_series(*cell(C.loc[st, "lat"], C.loc[st, "lon"]))
    ya, yb = int(r["year_cell"]), int(r["year_hint"])
    sa = s.copy()   # dated as parsed (year_cell)
    sb = s.copy(); sb.index = sb.index + pd.DateOffset(years=yb - ya)
    ra = rbest(sa[sa.index >= "1979-01-01"], ref)[0] if (sa.index >= "1979-01-01").any() else np.nan
    rb = rbest(sb[sb.index >= "1979-01-01"], ref)[0] if (sb.index >= "1979-01-01").any() else np.nan
    na = rnb(sa, C.loc[st, "lat"], C.loc[st, "lon"]); nb = rnb(sb, C.loc[st, "lat"], C.loc[st, "lon"])
    outC.append(dict(file=r["file"], sheet=r["sheet"], station=st, year_cell=ya, year_name=yb,
                     cpc_r_cell=round(ra, 3), cpc_r_name=round(rb, 3),
                     nb_r_cell=round(na[0], 3) if not np.isnan(na[0]) else np.nan,
                     nb_r_name=round(nb[0], 3) if not np.isnan(nb[0]) else np.nan,
                     verdict_cpc=decide(ra, rb, ya, yb), verdict_nb=decide(na[0], nb[0], ya, yb)))
Cy = pd.DataFrame(outC)

# D. copies between sheets of the same (parsed) year
outD = []
by_year = {}
for k, s in series.items():
    for y in s.index.year.unique():
        by_year.setdefault(int(y), []).append(k)
for y, ks in by_year.items():
    for a, b in itertools.combinations(ks, 2):
        sa, sb = series[a], series[b]
        sa = sa[sa.index.year == y]; sb = sb[sb.index.year == y]
        j = sa.index.intersection(sb.index)
        if len(j) < 60 or ((sa[j] > 0) | (sb[j] > 0)).sum() < 20:
            continue
        eq = (np.isclose(sa[j], sb[j])).mean()
        if eq >= 0.9:
            sta = S.loc[(S["file"] == a[0]) & (S["sheet"] == a[1]), "station"].iat[0]
            stb = S.loc[(S["file"] == b[0]) & (S["sheet"] == b[1]), "station"].iat[0]
            rec = dict(year=y, a=f"{a[0]}[{a[1]}]", station_a=sta, b=f"{b[0]}[{b[1]}]", station_b=stb,
                       shared_days=len(j), identical=round(eq, 3), cross_station=sta != stb)
            if sta != stb:
                ss = sa[sa.index.year == y]
                na = rnb(ss, C.loc[sta, "lat"], C.loc[sta, "lon"]); nb = rnb(ss, C.loc[stb, "lat"], C.loc[stb, "lon"])
                ca = rbest(ss, cpc_series(*cell(C.loc[sta, "lat"], C.loc[sta, "lon"])))[0] if y >= 1979 else np.nan
                cb = rbest(ss, cpc_series(*cell(C.loc[stb, "lat"], C.loc[stb, "lon"])))[0] if y >= 1979 else np.nan
                rec.update(nb_r_a=na[0], nb_r_b=nb[0], cpc_r_a=ca, cpc_r_b=cb,
                           belongs_to_nb=decide(na[0], nb[0], sta, stb), belongs_to_cpc=decide(ca, cb, sta, stb))
            outD.append(rec)
D = pd.DataFrame(outD)

for name, df in (("A_location", A), ("A2_alt_locations", A2), ("B_identity", Bd), ("C_year", Cy), ("D_copies", D)):
    df.to_csv(B / f"_agro_cpc_{name}.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200); pd.set_option("display.max_colwidth", 48)
print("A. location (r at catalogue cell vs best cell within +-3 deg)")
print(A.to_string(index=False))
print("\nA2. explicit alternative locations"); print(A2.to_string(index=False))
print("\nB. identity disputes:", len(Bd)); print(Bd.to_string(index=False) if len(Bd) else "")
print("\nC. year conflicts:", len(Cy)); print(Cy.to_string(index=False) if len(Cy) else "")
print("\nD. copies: total", len(D), "| cross-station", int(D["cross_station"].sum()) if len(D) else 0)
print(D[D["cross_station"]].to_string(index=False) if len(D) else "")
