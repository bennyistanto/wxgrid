"""Standard station QC of the phase-2 rain-post sources (bmg_posts, sumbar_daily, larantuka,
sumsel_posts; RR), read-only on F:/temp/station/compiled. Order follows Durre 2010 in spirit
(metadata, codes, accumulations, duplicates, zeros, outliers, day label, coverage); thresholds
are provisional and stated with each check.

 1 metadata     in Indonesia and on land (Natural Earth 10 m land), coordinate source from
                _post_catalogue.csv, identical coordinates under other keys, elevation missing or
                far from a station within 5 km. No DEM is on disk, so DEM elevation is not tested.
 2 sentinels    exact repeated values >= 50 mm whose count is >= 5 and >= 5x the mean count of
                the neighbouring integers (v-1, v+1); known codes 99/888/999/8888/9999 still present.
 3 accumulation value after a gap of >= 2 missing days vs the series' wet days after no gap
                (share above the no-gap wet p95); CPC test on post-gap values >= 20 mm (closer to
                CPC summed over gap + day than to CPC on the day).
 4 duplicates   7-day windows of identical values (0.1 mm) with >= 4 days >= 1 mm, matched against
                every RR series in observations_RR at any date offset; also repeated months within
                a series.
 5 zeros        runs of >= 20 consecutive 0.0 mm days: suspect if CPC mean >= 3 mm/d and CPC wet
                share >= 0.3, or >= 2 merged neighbours within 50 km with median mean >= 3 mm/d
                (same rule as temp/qc/qc_05_zeros.py).
 6 outliers     values >= 100 mm: isolated if CPC day < 5 mm and >= 2 neighbours within 25 km
                report that day with max < 10 mm; also count values > own p99.9 and > 300 mm.
 7 day label    daylabel_segments status/offset shares; r with CPC at lags -1/0/+1 on raw dates.
 8 coverage     n days, span, missing share, days reaching merged_RR, days that are the only
                value on that date within 25 km (unique contribution).
Writes F:/temp/station/qc_phase2/audit_*.csv. Run: python tools/qc_phase2_audit.py
"""
import numpy as np
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500); pd.set_option("display.max_colwidth", 60)
OUT = q.OUT
o = q.obs_rr()
st = q.stations(); se = q.series(); sites = q.sites().set_index("site_id")
o["sid"] = o.series_id.astype(str)
o["src"] = o.sid.str.split(":").str[0]
P2 = o[o.src.isin(q.PHASE2) & ~o.flag.astype(str).str.contains("src_duplicate")].copy()
P2 = P2.sort_values(["sid", "date_raw"])
ser2 = sorted(P2.sid.unique())
sk_of = se.set_index("series_id").station_key
stx = st.set_index("station_key")
lat_of = {s: stx.loc[sk_of[s], "lat"] for s in ser2}; lon_of = {s: stx.loc[sk_of[s], "lon"] for s in ser2}
site_of = {s: stx.loc[sk_of[s], "site_id"] for s in ser2}
cpc = q.CPCField()
TAB = {s: {} for s in ser2}

# ---------------- 1 metadata
import geopandas as gpd
from shapely.geometry import Point
land = gpd.read_file(r"C:\Users\benny\.local\share\cartopy\shapefiles\natural_earth\physical\ne_10m_land.shp").cx[94:142, -12:7]
landu = land.union_all()
coast = gpd.read_file(r"C:\Users\benny\.local\share\cartopy\shapefiles\natural_earth\physical\ne_10m_coastline.shp").cx[94:142, -12:7].union_all()
s2 = st[st.source.isin(q.PHASE2)].copy()
s2["in_idn_box"] = s2.lat.between(-11.5, 6.5) & s2.lon.between(94.5, 141.5)
s2["on_land"] = [landu.contains(Point(x, y)) for x, y in zip(s2.lon, s2.lat)]
s2["coast_km"] = [coast.distance(Point(x, y)) * 111.0 for x, y in zip(s2.lon, s2.lat)]
cat = pd.read_csv("F:/temp/station/additional-sources/_post_catalogue.csv")
cat["key"] = cat.post_key.astype(str)
s2["coord_source"] = ""
s2["coord_approx"] = ""
for i, r in s2.iterrows():
    k = r.source_station_id if isinstance(r.source_station_id, str) else ""
    c = cat[(cat.post_key.astype(str) == k) | (cat.post_key.astype(str) == r.station_key.split(":", 1)[1])]
    if len(c):
        s2.at[i, "coord_source"] = str(c.coord_source.iloc[0])[:60]; s2.at[i, "coord_approx"] = str(c.coord_approx.iloc[0])
same = st.groupby([st.lat.round(4), st.lon.round(4)]).station_key.apply(list)
s2["same_coords_as"] = [";".join(k for k in same.get((round(a, 4), round(b, 4)), []) if k != sk) for sk, a, b in zip(s2.station_key, s2.lat, s2.lon)]
d = q.haversine_km(s2.lat.values[:, None], s2.lon.values[:, None], st.lat.values[None, :], st.lon.values[None, :])
near = []
for i, (sk, el) in enumerate(zip(s2.station_key, s2.elev_m)):
    j = np.where((d[i] <= 5) & (st.station_key.values != sk) & st.elev_m.notna().values)[0]
    if len(j) and np.isfinite(el):
        k = j[np.argmax(np.abs(st.elev_m.values[j] - el))]
        near.append((st.station_key.values[k], round(d[i, k], 1), st.elev_m.values[k] - el))
    else:
        near.append(("", np.nan, np.nan))
s2["elev_ref_station"] = [n[0] for n in near]; s2["elev_ref_km"] = [n[1] for n in near]; s2["elev_ref_minus_own_m"] = [n[2] for n in near]
s2.to_csv(f"{OUT}/audit_metadata.csv", index=False)
print("== 1 metadata ==")
print(f"stations {len(s2)}; outside Indonesia box {(~s2.in_idn_box).sum()}; not on NE10m land {(~s2.on_land).sum()}; elevation missing {s2.elev_m.isna().sum()}")
print(s2[~s2.on_land][["station_key", "lat", "lon", "coast_km"]].to_string(index=False))
print("identical coordinates under other keys:")
print(s2[s2.same_coords_as != ""][["station_key", "lat", "lon", "same_coords_as"]].to_string(index=False))
print("elevation differs by > 150 m from a station within 5 km:")
print(s2[s2.elev_ref_minus_own_m.abs() > 150][["station_key", "elev_m", "elev_ref_station", "elev_ref_km", "elev_ref_minus_own_m"]].to_string(index=False))
print("coordinate source approximate (catalogue coord_approx True):")
print(s2[s2.coord_approx == "True"][["station_key", "coord_source"]].to_string(index=False))

# ---------------- 2 sentinels
print("\n== 2 sentinels ==")
v = P2[P2.value.notna()]
rows = []
for src_, g in v.groupby("src"):
    cnt = g.value.round(1).value_counts()
    for val, n in cnt[cnt.index >= 50].items():
        nb = np.mean([cnt.get(round(val - 1, 1), 0), cnt.get(round(val + 1, 1), 0)])
        if n >= 5 and n >= 5 * max(nb, 0.2):
            rows.append((src_, val, int(n), nb, ";".join(g[g.value.round(1) == val].sid.value_counts().head(3).index)))
S = pd.DataFrame(rows, columns=["source", "value", "count", "mean_count_v-1_v+1", "top_series"])
S.to_csv(f"{OUT}/audit_sentinels.csv", index=False)
print("spiky repeated values >= 50 mm (count >= 5 and >= 5x neighbours v-1/v+1):")
print(S.to_string(index=False) if len(S) else "  none")
codes = [99, 99.9, 777, 888, 999, 999.9, 8888, 9999]
print("known code values still present as rain:", {c: int((v.value == c).sum()) for c in codes})
print("values > 300 mm by source:", v[v.value > 300].groupby("src").size().to_dict(), "; max:", v.groupby("src").value.max().to_dict())
print("flags by source:"); print(pd.crosstab(P2.src, P2.flag.astype(str)).to_string())
for s in ser2:
    TAB[s]["n_spike_code"] = int(v[(v.sid == s) & v.value.round(1).isin(S.value)].shape[0]) if len(S) else 0

# ---------------- 3 accumulations
print("\n== 3 accumulations ==")
P2["gap"] = ((P2.date_raw - P2.groupby("sid").date_raw.shift()).dt.days - 1).fillna(0).astype(int)
w = P2[P2.value >= 1.0]
rows = []
for s, g in w.groupby("sid"):
    base = g[g.gap == 0].value; post = g[g.gap >= 2]
    p95 = base.quantile(0.95) if len(base) >= 30 else np.nan
    rows.append((s, len(base), len(post), int((post.value >= p95).sum()) if np.isfinite(p95) else 0,
                 (post.value >= p95).mean() if len(post) and np.isfinite(p95) else np.nan,
                 post.value.mean() / base.mean() if len(post) and len(base) else np.nan, p95))
A = pd.DataFrame(rows, columns=["series_id", "n_wet_nogap", "n_wet_postgap", "n_big", "share_big", "ratio_mean", "p95_nogap"])
ev = P2[(P2.gap >= 2) & (P2.value >= 20) & (P2.date >= "1979-01-10")].copy()
ev["cpc_day"] = np.nan; ev["cpc_sum"] = np.nan
for s, g in ev.groupby("sid"):
    cs = cpc.series(lat_of[s], lon_of[s]); cs.index = cs.index + pd.Timedelta(days=1)
    cum = cs.cumsum()
    ev.loc[g.index, "cpc_day"] = cs.reindex(g.date).values
    ev.loc[g.index, "cpc_sum"] = cum.reindex(g.date).values - cum.reindex(g.date - pd.to_timedelta(g.gap + 1, unit="D")).values
ev["closer_to_sum"] = (ev.value - ev.cpc_sum).abs() < (ev.value - ev.cpc_day).abs()
ev2 = ev[(ev.cpc_sum - ev.cpc_day) >= 5]
A = A.merge(ev2.groupby("sid").agg(n_cpc_test=("value", "size"), n_closer_sum=("closer_to_sum", "sum")).rename_axis("series_id").reset_index(),
            on="series_id", how="left")
A["suspect"] = (A.n_wet_postgap >= 10) & (A.share_big >= 0.25) & (A.ratio_mean >= 1.5)
A.to_csv(f"{OUT}/audit_accumulation_by_series.csv", index=False)
ev.to_csv(f"{OUT}/audit_accumulation_events.csv", index=False)
A["src"] = A.series_id.str.split(":").str[0]
print("post-gap (>= 2 missing days) wet values above the series' no-gap p95 (about 0.05 expected):")
print(A.groupby("src").apply(lambda d: pd.Series(dict(series=len(d), postgap_wet=d.n_wet_postgap.sum(), big=d.n_big.sum(),
      share_big=d.n_big.sum() / max(1, d.n_wet_postgap.sum()), cpc_tested=d.n_cpc_test.sum(), closer_to_cpc_sum=d.n_closer_sum.sum(),
      suspect_series=int(d.suspect.sum())))).to_string())
print(A[A.suspect | (A.share_big >= 0.2) & (A.n_wet_postgap >= 5)].round(2).to_string(index=False))
for r in A.itertuples():
    TAB[r.series_id]["acc_postgap_wet"] = r.n_wet_postgap; TAB[r.series_id]["acc_big"] = r.n_big
    TAB[r.series_id]["acc_suspect"] = bool(r.suspect)
big = v[v.value > 250][["sid", "date_raw", "date", "value", "flag"]].copy()
mm_ = q.merged_rr()
mkey = set(zip(mm_.series_id.astype(str), mm_.date))
big["in_merged"] = [(a, b) in mkey for a, b in zip(big.sid, big.date)]
big["cpc_day"] = [cpc.at(lat_of[s], lon_of[s], [d])[0] for s, d in zip(big.sid, big.date)]
print("values > 250 mm:"); print(big.to_string(index=False))
for val in S.value:
    print(f"rows with value {val}:"); print(v[v.value.round(1) == val][["sid", "date_raw", "value"]].to_string(index=False))

# ---------------- 4 duplicates
print("\n== 4 duplicates ==")
allo = o[~o.flag.astype(str).str.contains("src_duplicate") & o.value.notna()][["sid", "date_raw", "value"]]
codes_, uniq = pd.factorize(allo.sid)
allo = allo.assign(c=codes_)
t0 = allo.date_raw.min()
allo["day"] = (allo.date_raw - t0).dt.days.astype(np.int64)
allo = allo.drop_duplicates(["c", "day"]).sort_values(["c", "day"])
W = 7
recs = []
for c, g in allo.groupby("c", sort=False):
    d0 = g.day.values; vv = np.round(g.value.values * 10).astype(np.int64)
    n = d0.max() - d0.min() + 1
    arr = np.full(n + W, -1, dtype=np.int64); arr[d0 - d0.min()] = vv
    if n < W:
        continue
    win = np.lib.stride_tricks.sliding_window_view(arr[:n], W)
    ok = (win >= 0).all(axis=1) & ((win >= 10).sum(axis=1) >= 4)
    if not ok.any():
        continue
    idx = np.where(ok)[0]
    h = np.zeros(len(idx), dtype=np.uint64)
    for k in range(W):
        h = h * np.uint64(1000003) + win[idx, k].astype(np.uint64)
    recs.append(pd.DataFrame({"h": h, "c": c, "day": idx + d0.min()}))
H = pd.concat(recs, ignore_index=True)
p2codes = [i for i, s in enumerate(uniq) if s.split(":")[0] in q.PHASE2]
hp = H[H.c.isin(p2codes)]
mt = hp.merge(H, on="h", suffixes=("", "_o"))
mt = mt[mt.c != mt.c_o]
mt["lag"] = mt.day_o - mt.day
pairs = mt.groupby(["c", "c_o", "lag"]).size().rename("n_windows").reset_index()
pairs = pairs[pairs.n_windows >= 3]
pairs["series_id"] = uniq[pairs.c]; pairs["other"] = uniq[pairs.c_o]
first = mt.groupby(["c", "c_o", "lag"]).day.agg(["min", "max"]).reset_index()
pairs = pairs.merge(first, on=["c", "c_o", "lag"])
pairs["from"] = (t0 + pd.to_timedelta(pairs["min"], unit="D")).dt.date; pairs["to"] = (t0 + pd.to_timedelta(pairs["max"] + W - 1, unit="D")).dt.date
skall = se.set_index("series_id").station_key
pairs["dist_km"] = [q.haversine_km(stx.loc[skall[a], "lat"], stx.loc[skall[a], "lon"], stx.loc[skall[b], "lat"], stx.loc[skall[b], "lon"])
                    for a, b in zip(pairs.series_id, pairs.other)]
# windows per series in total (denominator)
nwin = hp.groupby("c").size()
pairs["share_of_series_windows"] = pairs.n_windows / pairs.c.map(nwin)
pairs = pairs.drop(columns=["c", "c_o", "min", "max"]).sort_values("n_windows", ascending=False)
pairs.to_csv(f"{OUT}/audit_duplicate_windows.csv", index=False)
print("identical 7-day windows (>= 4 days >= 1 mm), phase-2 series vs any RR series, pairs with >= 3 windows:")
print(pairs.round(3).to_string(index=False))
# repeated months inside a series
rep = []
for s, g in P2[P2.value.notna()].groupby("sid"):
    g = g.assign(ym=g.date_raw.dt.to_period("M"))
    for ym, h in g.groupby("ym"):
        if len(h) >= 28 and (h.value >= 1).sum() >= 5:
            rep.append((s, str(ym), hash(tuple(np.round(h.sort_values("date_raw").value.values, 1)))))
R = pd.DataFrame(rep, columns=["sid", "ym", "h"])
R = R[R.duplicated(["sid", "h"], keep=False)]
print("months repeated within a series (>= 28 values, >= 5 wet days):", len(R))
print(R.groupby(["sid", "h"]).ym.apply(list).to_string() if len(R) else "")
for s in ser2:
    TAB[s]["dup_windows_max"] = int(pairs[pairs.series_id == s].n_windows.max()) if (pairs.series_id == s).any() else 0
    TAB[s]["dup_partner"] = ";".join(f"{r.other}@lag{r.lag}" for r in pairs[pairs.series_id == s].head(2).itertuples())

# ---------------- shared: merged neighbours
m = mm_
slat = sites.lat; slon = sites.lon
nb = {}
for s in ser2:
    dd = q.haversine_km(lat_of[s], lon_of[s], slat.values, slon.values)
    nb[s] = [(sid_, x) for sid_, x in zip(sites.index, dd) if x <= 50 and sid_ != site_of[s]]
need = sorted({x for s in ser2 for x, _ in nb[s]})
mn = m[m.site_id.astype(str).isin(need) & (m.date >= "1960-01-01")]
MX = mn.pivot_table(index="date", columns=mn.site_id.astype(str), values="value", aggfunc="first", observed=True)

# ---------------- 5 zeros
print("\n== 5 zero runs >= 20 d ==")
zr = []
for s, g in P2.groupby("sid"):
    x = g.set_index("date").value
    x = x[~x.index.duplicated()].asfreq("D")
    dm = g.set_index("date").flag.astype(str).str.contains("dash_month")
    dm = dm[~dm.index.duplicated()].reindex(x.index, fill_value=False)
    z = (x == 0).astype(np.int8).values
    dz = np.diff(np.concatenate([[0], z, [0]])); a_, b_ = np.where(dz == 1)[0], np.where(dz == -1)[0]
    cs = cpc.series(lat_of[s], lon_of[s]); cs.index = cs.index + pd.Timedelta(days=1)
    for i0, i1 in zip(a_, b_):
        if i1 - i0 < 20:
            continue
        dts = x.index[i0:i1]
        c = cs.reindex(dts)
        nbm = []
        for sid_, dist in nb[s]:
            if sid_ in MX.columns:
                y = MX[sid_].reindex(dts)
                if y.notna().mean() >= 0.5:
                    nbm.append(y.mean())
        zr.append(dict(series_id=s, start=dts[0].date(), end=dts[-1].date(), length=i1 - i0, dash_month_days=int(dm.iloc[i0:i1].sum()),
                       cpc_mean=c.mean(), cpc_wet_share=(c >= 1).mean() if c.notna().any() else np.nan,
                       n_nbr=len(nbm), nbr_median_mean=np.median(nbm) if nbm else np.nan))
Z = pd.DataFrame(zr)
Z["suspect"] = ((Z.cpc_mean >= 3) & (Z.cpc_wet_share >= 0.3)) | ((Z.n_nbr >= 2) & (Z.nbr_median_mean >= 3))
Z.to_csv(f"{OUT}/audit_zero_runs.csv", index=False)
Z["src"] = Z.series_id.str.split(":").str[0]
print(Z.groupby("src").agg(runs=("length", "size"), days=("length", "sum"), suspect_runs=("suspect", "sum"),
      suspect_days=("length", lambda L: int(L[Z.loc[L.index, "suspect"]].sum())),
      suspect_days_not_dash=("length", lambda L: int((L - Z.loc[L.index, "dash_month_days"])[Z.loc[L.index, "suspect"]].sum()))).to_string())
print(Z[Z.suspect].round(2).sort_values(["series_id", "start"]).to_string(index=False))
for s in ser2:
    zz = Z[(Z.series_id == s) & Z.suspect]
    TAB[s]["zero_suspect_runs"] = len(zz); TAB[s]["zero_suspect_days"] = int(zz.length.sum())

# ---------------- 6 outliers
print("\n== 6 outliers ==")
hv = P2[P2.value >= 100].copy()
rows = []
for r in hv.itertuples():
    cday = cpc.at(lat_of[r.sid], lon_of[r.sid], [r.date])[0]
    vals = []
    for sid_, dist in nb[r.sid]:
        if dist <= 25 and sid_ in MX.columns and r.date in MX.index:
            y = MX.at[r.date, sid_]
            if np.isfinite(y):
                vals.append(y)
    rows.append((r.sid, r.date.date(), r.value, str(r.flag), cday, len(vals), max(vals) if vals else np.nan))
OUTL = pd.DataFrame(rows, columns=["series_id", "date", "value", "flag", "cpc_day", "n_nbr25", "nbr_max"])
OUTL["isolated"] = (OUTL.cpc_day < 5) & (OUTL.n_nbr25 >= 2) & (OUTL.nbr_max < 10)
OUTL["cpc_dry_no_nbr"] = (OUTL.cpc_day < 1) & (OUTL.n_nbr25 < 2)
p999 = P2[P2.value >= 1].groupby("sid").value.quantile(0.999)
OUTL["above_own_p999"] = OUTL.value > OUTL.series_id.map(p999)
OUTL.to_csv(f"{OUT}/audit_outliers.csv", index=False)
OUTL["src"] = OUTL.series_id.str.split(":").str[0]
print(OUTL.groupby("src").agg(n_ge100=("value", "size"), isolated=("isolated", "sum"), cpc_dry_no_nbr=("cpc_dry_no_nbr", "sum"),
      above_own_p999=("above_own_p999", "sum")).to_string())
print(OUTL[OUTL.isolated | (OUTL.value > 300)].round(1).sort_values("value", ascending=False).to_string(index=False))
for s in ser2:
    TAB[s]["outlier_isolated"] = int(OUTL[(OUTL.series_id == s)].isolated.sum())

# ---------------- 7 day label
print("\n== 7 day label ==")
dl = pd.read_csv(f"{q.COMP}/daylabel_segments.csv")
dl = dl[dl.series_id.isin(ser2)].copy()
dl["days"] = (pd.to_datetime(dl.end) - pd.to_datetime(dl.start)).dt.days + 1
for s in ser2:
    g = dl[dl.series_id == s]; tot = g.days.sum()
    ver = g[g.status == "verified"]
    TAB[s]["dl_verified_share"] = ver.days.sum() / tot if tot else np.nan
    TAB[s]["dl_verified_offsets"] = ";".join(f"{int(k)}:{v / max(1, ver.days.sum()):.2f}" for k, v in ver.groupby("offset").days.sum().items())
    TAB[s]["dl_n_offset_changes"] = int((g.offset.diff().fillna(0) != 0).sum())
    x = P2[P2.sid == s].set_index("date_raw").value
    x = x[~x.index.duplicated()]
    x = x[x.index >= "1979-01-01"]
    cs = cpc.series(lat_of[s], lon_of[s])
    rr = {k: q.pearson(x.values, cs.reindex(x.index + pd.Timedelta(days=k - 1)).values)[0] for k in (-1, 0, 1, 2)}
    TAB[s]["cpc_r_raw_lag0"] = rr[0]; TAB[s]["cpc_best_raw_lag"] = max(rr, key=lambda k: -9 if not np.isfinite(rr[k]) else rr[k])
    TAB[s]["cpc_r_best"] = max(v for v in rr.values() if np.isfinite(v)) if any(np.isfinite(v) for v in rr.values()) else np.nan
dsum = dl.assign(src=dl.series_id.str.split(":").str[0]).groupby(["src", "status", "offset"]).days.sum().unstack(fill_value=0)
print("days by status and offset (date = date_raw + offset):"); print(dsum.to_string())

# ---------------- 8 coverage
print("\n== 8 coverage ==")
for s in ser2:
    x = P2[P2.sid == s]
    span = (x.date_raw.max() - x.date_raw.min()).days + 1
    TAB[s]["n_days"] = x.date_raw.nunique(); TAB[s]["first"] = x.date_raw.min().date(); TAB[s]["last"] = x.date_raw.max().date()
    TAB[s]["missing_pct_of_span"] = 100 * (1 - x.date_raw.nunique() / span)
    TAB[s]["n_dash_month"] = int(x.flag.astype(str).str.contains("dash_month").sum())
    TAB[s]["n_unmeasurable"] = int(x.flag.astype(str).str.contains("unmeasurable").sum())
    ms = m[m.series_id == s]
    TAB[s]["in_merged"] = len(ms)
    near25 = [sid_ for sid_, dd in nb[s] if dd <= 25 and sid_ in MX.columns]
    if len(ms):
        other = MX[near25].reindex(ms.date).notna().any(axis=1).values if near25 else np.zeros(len(ms), bool)
        TAB[s]["merged_unique_25km"] = int((~other).sum())
T = pd.DataFrame.from_dict(TAB, orient="index").rename_axis("series_id").reset_index()
T.to_csv(f"{OUT}/audit_series_table.csv", index=False)
mp = m[m.series_id.astype(str).str.split(":").str[0].isin(q.PHASE2)]
cnt = mp.groupby([mp.series_id.astype(str).str.split(":").str[0], "date"]).size().unstack(0).fillna(0)
cy = cnt.groupby(cnt.index.year).median()
cy.to_csv(f"{OUT}/audit_daily_site_count_by_year.csv")
print("median merged sites per day contributed by each phase-2 source, by year:"); print(cy.astype(int).to_string())
pd.set_option("display.max_columns", 40)
cols = ["series_id", "n_days", "first", "last", "missing_pct_of_span", "in_merged", "merged_unique_25km", "n_dash_month", "acc_big",
        "dup_windows_max", "zero_suspect_days", "outlier_isolated", "dl_verified_share", "cpc_r_raw_lag0", "cpc_best_raw_lag", "cpc_r_best"]
print(T[cols].round(2).to_string(index=False))
