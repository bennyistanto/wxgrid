"""Measurements M1-M7 on the raw PU SIHKA rain-post publications (F67, F68), before any reader is written.

Reads F:/temp/station/pu_sihka/raw/ only. Writes tables and a log to F:/temp/station/pu_sihka/measure/.

  load  long table of every value (cache obs.pkl) and one row per publication (pubs.csv)
  M1    what 0 means: all-zero months and short files vs CPC and neighbouring posts
  M2    publications whose dates fall in another year than the catalogue says: copies or relabels?
  M3    coordinates (3+ text formats), per-post consistency, inside the domain; integration_id uniqueness
  M4    day key (00:00 UTC) vs CPC lag, by time zone
  M5    overlap with sources already in the build (stations.csv.gz, observations_RR.csv.gz)
  M6    provider day flags (note / status) vs CPC and neighbours
  M7    values above 500 mm

Usage: python tools/measure_pu_sihka.py [load|m1|m2|m3|m4|m5|m6|m7|all]
"""
from __future__ import annotations

import glob
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
RAW = Path("F:/temp/station/pu_sihka/raw")
OUT = Path("F:/temp/station/pu_sihka/measure")
CPC = "F:/temp/station/cpc/idn_cpc_1979_2025.nc"
COMPILED = Path("F:/temp/station/compiled")
BBOX = (90.0, -15.0, 145.0, 12.0)


# ---------------------------------------------------------------- parsing helpers
def parse_coord(c):
    """Return (lat, lon, how) from the `koordinat` text, or (nan, nan, reason)."""
    s = str(c or "").strip()
    if s in ("", "-", "0", "None"):
        return np.nan, np.nan, "none"
    m = re.match(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", s)
    if m:
        return float(m.group(2)), float(m.group(1)), "wkt"
    t = s.replace("⁰", "°").replace(",", ".")
    m = re.match(r"^\s*-?\s*(\d+\.\d+)\s*°?\s*([SNU]|LS|LU)?\s*-\s*(\d+\.\d+)\s*°?\s*(E|BT)?", t)
    if m:   # decimal degrees text, e.g. "- 8.82139° S - 120.965° E"
        la = float(m.group(1))
        north = (m.group(2) or "") in ("N", "U", "LU")
        return (la if north else -la), float(m.group(3)), "decimal text"
    north = bool(re.search(r"\bLU\b|LU\s*-", t))
    south = bool(re.search(r"\bLS\b|LS\s*-", t))
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    # expect deg min sec deg min sec (sec may be missing in one part)
    if len(nums) == 6:
        la = nums[0] + nums[1] / 60 + nums[2] / 3600
        lo = nums[3] + nums[4] / 60 + nums[5] / 3600
    elif len(nums) == 4:
        la, lo = nums[0] + nums[1] / 60, nums[2] + nums[3] / 60
    else:
        return np.nan, np.nan, f"unparsed ({len(nums)} numbers)"
    if not (north or south):
        how = "dms, no hemisphere (assumed S)"
    else:
        how = "dms"
    return (la if north else -la), lo, how


def parse_elev(e):
    s = str(e or "").strip()
    m = re.search(r"(-?\d+(?:[.,]\d+)?)", s)
    return float(m.group(1).replace(",", ".")) if m else np.nan


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p)
                                          * math.sin((d - b) * p / 2) ** 2))


# ---------------------------------------------------------------- load
def load(force=False):
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "obs.pkl").exists() and not force:
        return pd.read_pickle(OUT / "obs.pkl"), pd.read_csv(OUT / "pubs.csv")
    cat = json.loads(next(RAW.glob("catalogue_*.json")).read_text(encoding="utf-8"))
    meta = {d["pubId"]: dict(post_id=p["id"], integration_id=p.get("integration_id"), name=p["name"],
                              hidrologi_type=p.get("hidrologi_type"), unit=p.get("unit"), year_cat=int(d["year"]),
                              gauge=d["type"], year_status=d.get("status", ""))
            for p in cat for d in p["data"] if d.get("variable") == "Rainfall"}
    pubs, frames = [], []
    for f in sorted(glob.glob(str(RAW / "pub" / "*.json"))):
        pub = Path(f).stem
        j = json.loads(Path(f).read_text(encoding="utf-8"))
        h, b = j.get("head") or {}, j.get("body")
        la, lo, how = parse_coord(h.get("koordinat"))
        row = dict(pubId=pub, **meta[pub], head_name=h.get("nama_pos"), koordinat=h.get("koordinat"), lat=la, lon=lo,
                   coord_how=how, elev_m=parse_elev(h.get("elevesi")), elev_text=h.get("elevesi"),
                   provinsi=h.get("provinsi"), kabupaten=h.get("kabupaten"), kecamatan=h.get("kecamatan"),
                   tahun_pendirian=h.get("tahun_pendirian"), body_shape=type(b).__name__, n_keys=0, n_epoch=0)
        if isinstance(b, dict):
            ks = np.array([int(k) for k in b], dtype="int64")
            row["n_keys"], row["n_epoch"] = len(ks), int((ks < 86400 * 365).sum())
            v = list(b.values())
            d = pd.DataFrame(dict(pubId=pub, ts=ks, value=[x.get("value") for x in v],
                                  note=[x.get("note") for x in v], day_status=[x.get("status") for x in v]))
            d = d[d.ts >= 86400 * 365]
            d["date"] = pd.to_datetime(d.ts, unit="s")
            d["tod"] = d.ts % 86400
            frames.append(d.drop(columns="ts"))
        pubs.append(row)
    obs = pd.concat(frames, ignore_index=True)
    pubs = pd.DataFrame(pubs)
    obs.to_pickle(OUT / "obs.pkl")
    pubs.to_csv(OUT / "pubs.csv", index=False)
    return obs, pubs


def posts_table(pubs):
    """One position per post: the most common parsed coordinate; spread in km."""
    rows = []
    for pid, g in pubs.groupby("post_id"):
        c = g.dropna(subset=["lat"])
        if len(c):
            mode = c.groupby([c.lat.round(5), c.lon.round(5)]).size().idxmax()
            spread = max(km(mode[0], mode[1], a, b) for a, b in zip(c.lat, c.lon))
        else:
            mode, spread = (np.nan, np.nan), np.nan
        rows.append(dict(post_id=pid, integration_id=g.integration_id.iloc[0], name=g.name.iloc[0], unit=g.unit.iloc[0],
                         lat=mode[0], lon=mode[1], spread_km=spread, n_pubs=len(g), n_coord_pubs=len(c),
                         coord_how=";".join(sorted(set(c.coord_how))) if len(c) else "none",
                         elev_m=g.elev_m.dropna().median() if g.elev_m.notna().any() else np.nan,
                         years=f"{g.year_cat.min()}-{g.year_cat.max()}", gauges=";".join(sorted(set(g.gauge)))))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- M3
def m3(obs, pubs):
    print("== M3 coordinates and ids")
    print("per publication:", pubs.coord_how.value_counts().to_dict())
    print("unparsed:", pubs[pubs.coord_how.str.startswith("unparsed")].koordinat.tolist()[:10])
    p = posts_table(pubs)
    inb = p.lat.between(BBOX[1], BBOX[3]) & p.lon.between(BBOX[0], BBOX[2])
    print(f"posts {len(p)}; with a position {p.lat.notna().sum()}; inside the domain {inb.sum()}; outside: "
          f"{p[p.lat.notna() & ~inb][['name', 'lat', 'lon']].values.tolist()[:10]}")
    print("posts whose positions across years spread > 1 km:", int((p.spread_km > 1).sum()), "; > 10 km:", int((p.spread_km > 10).sum()))
    print(p[p.spread_km > 10][["name", "unit", "spread_km", "n_coord_pubs"]].sort_values("spread_km", ascending=False).head(15).to_string(index=False))
    d = p.integration_id.value_counts()
    print("integration_id: missing", int(p.integration_id.isna().sum()), "; shared by more than one post", int((d > 1).sum()),
          d[d > 1].head(5).to_dict())
    nm = p.name.str.upper().str.strip().value_counts()
    print("names shared by more than one post:", int((nm > 1).sum()))
    # land/sea: compare with CPC land? (not here) ; hemisphere assumption check
    a = pubs[pubs.coord_how.str.contains("assumed S", na=False)]
    print("no-hemisphere publications:", len(a), "provinces", a.provinsi.value_counts().to_dict())
    print("elevation given for posts:", int(p.elev_m.notna().sum()), "; range", p.elev_m.min(), p.elev_m.max())
    p.to_csv(OUT / "posts.csv", index=False)
    return p


# ---------------------------------------------------------------- shared: CPC at posts
def cpc_at(posts):
    import xarray as xr
    cpc = xr.open_dataset(CPC).precip
    out = {}
    for r in posts.dropna(subset=["lat"]).itertuples():
        out[r.post_id] = cpc.sel(lat=r.lat, lon=r.lon % 360 if cpc.lon.max() > 180 else r.lon, method="nearest").to_series()
    return out


def series_wide(obs, pubs, gauge="MANUAL"):
    """Daily value per post (one gauge type), dates as in the file."""
    o = obs.merge(pubs[["pubId", "post_id", "gauge", "year_cat"]], on="pubId")
    o = o[(o.gauge == gauge) & (o.date.dt.year == o.year_cat)]
    return o.pivot_table(index="date", columns="post_id", values="value", aggfunc="first")


# ---------------------------------------------------------------- M1
def monthly(obs, pubs):
    o = obs.merge(pubs[["pubId", "post_id", "gauge", "year_cat"]], on="pubId")
    o = o[o.date.dt.year == o.year_cat]
    o["ym"] = o.date.dt.to_period("M")
    g = o.groupby(["post_id", "gauge", "ym"])
    return g.agg(total=("value", "sum"), n_days=("value", "size"), n_pos=("value", lambda v: int((v > 0).sum()))).reset_index()


def m1(obs, pubs, posts):
    print("== M1 what 0 means")
    mo = monthly(obs, pubs)
    mo["days_in_month"] = mo.ym.dt.days_in_month
    mo["all_zero"] = (mo.n_pos == 0) & (mo.n_days >= mo.days_in_month)
    print(f"post-gauge-months {len(mo):,}; complete months {int((mo.n_days >= mo.days_in_month).sum()):,}; "
          f"all-zero complete months {int(mo.all_zero.sum()):,}; months with fewer days than the calendar {int((mo.n_days < mo.days_in_month).sum()):,}")
    # CPC monthly totals at each post (lag irrelevant at month scale)
    import xarray as xr
    cpc = xr.open_dataset(CPC).precip
    lon360 = float(cpc.lon.max()) > 180
    pos = posts.dropna(subset=["lat"]).set_index("post_id")
    cm = cpc.resample(time="MS").sum()
    vals = []
    for pid, g in mo.groupby("post_id"):
        if pid not in pos.index:
            continue
        s = cm.sel(lat=pos.at[pid, "lat"], lon=pos.at[pid, "lon"] % 360 if lon360 else pos.at[pid, "lon"], method="nearest").to_series()
        s.index = s.index.to_period("M")
        vals.append(g.assign(cpc=s.reindex(g.ym).to_numpy()))
    mo = pd.concat(vals, ignore_index=True)
    # CPC climatology per post and calendar month: wet-season month if >= 150 mm
    mo["cal"] = mo.ym.dt.month
    clim = mo.groupby(["post_id", "cal"]).cpc.transform("median")
    mo["wet_clim"] = clim >= 150
    # neighbours: other posts within 25 km, same month, not all-zero
    P = pos[["lat", "lon"]]
    nb = {}
    for a in P.itertuples():
        d = [(b.Index, km(a.lat, a.lon, b.lat, b.lon)) for b in P.itertuples() if b.Index != a.Index]
        nb[a.Index] = [x for x, dd in d if dd <= 25]
    ok = mo[~mo.all_zero & (mo.n_days >= mo.days_in_month)].groupby(["post_id", "ym"]).total.max()
    okd = ok.to_dict()
    mo["nb_median"] = [np.nanmedian([okd[(q, ym)] for q in nb.get(pid, []) if (q, ym) in okd]) if any((q, ym) in okd for q in nb.get(pid, [])) else np.nan
                       for pid, ym in zip(mo.post_id, mo.ym)]
    c = mo[mo.n_days >= mo.days_in_month]
    t = c.groupby("all_zero").agg(n=("cpc", "size"), cpc_median=("cpc", "median"), cpc_p25=("cpc", lambda x: x.quantile(.25)),
                                   frac_cpc_ge100=("cpc", lambda x: round(float((x >= 100).mean()), 3)),
                                   nb_n=("nb_median", lambda x: int(x.notna().sum())), nb_median=("nb_median", "median"))
    print("complete months, by all-zero (CPC monthly mm at the post; neighbour = median of posts within 25 km):")
    print(t.to_string())
    w = c[c.wet_clim].groupby("all_zero").agg(n=("cpc", "size"), cpc_median=("cpc", "median"), nb_median=("nb_median", "median"),
                                               frac_nb_ge100=("nb_median", lambda x: round(float((x >= 100).mean()), 3)))
    print("only climatologically wet months (CPC median >= 150 mm for that post and calendar month):")
    print(w.to_string())
    z = c[c.all_zero]
    sus = z[(z.cpc >= 100) | (z.nb_median >= 100)]
    print(f"all-zero months with CPC >= 100 mm or neighbours >= 100 mm: {len(sus):,} of {len(z):,}")
    # whole all-zero years
    yz = c.assign(y=c.ym.dt.year).groupby(["post_id", "gauge", "y"]).agg(m=("all_zero", "size"), z=("all_zero", "sum"))
    print("post-gauge-years with 12 complete months all zero:", int(((yz.m == 12) & (yz.z == 12)).sum()),
          "; with >= 6 all-zero months:", int((yz.z >= 6).sum()), "of", len(yz))
    # trailing zeros: all-zero months only at the end of a year (unfilled tail)
    def tail(g):
        g = g.sort_values("ym"); az = g.all_zero.to_numpy(); n = 0
        for x in az[::-1]:
            if not x: break
            n += 1
        return n
    tl = c.assign(y=c.ym.dt.year).groupby(["post_id", "gauge", "y"]).apply(tail)
    print("post-gauge-years ending with >= 3 all-zero months:", int((tl >= 3).sum()))
    # short files: which months are short
    s = mo[mo.n_days < mo.days_in_month]
    print("short months:", len(s), "; by missing days", (s.days_in_month - s.n_days).value_counts().head(8).to_dict())
    mo.to_csv(OUT / "m1_months.csv", index=False)
    return mo



# ---------------------------------------------------------------- M2
def m2(obs, pubs, posts):
    print("== M2 publications whose dates fall in another year than the catalogue says")
    yr = obs.groupby("pubId").date.agg(lambda d: d.dt.year.mode().iloc[0]).rename("year_body")
    p = pubs.set_index("pubId").join(yr)
    mm = p[p.year_body.notna() & (p.year_body != p.year_cat)]
    print("mismatched publications:", len(mm), "; body year - catalogue year:", (mm.year_body - mm.year_cat).value_counts().to_dict())
    vals = {k: g.set_index("date").value for k, g in obs.groupby("pubId")}
    rows = []
    for pub, r in mm.iterrows():
        sib = p[(p.post_id == r.post_id) & (p.index != pub)]
        a = vals[pub]
        best = (None, 0.0, 0, "")
        for s, q in sib.iterrows():
            b = vals.get(s)
            if b is None:
                continue
            j = a.index.intersection(b.index)
            if len(j) >= 300:
                eq = float((a[j] == b[j]).mean())
                if eq > best[1]:
                    best = (s, eq, len(j), f"{q.year_cat} {q.gauge}")
        rows.append(dict(pubId=pub, post_id=r.post_id, name=r["name"], gauge=r.gauge, year_cat=r.year_cat, year_body=r.year_body,
                         sibling=best[0], sibling_year_gauge=best[3], equal_frac=round(best[1], 3), n_common=best[2],
                         has_cat_year_elsewhere=bool(((p.post_id == r.post_id) & (p.year_body == r.year_cat) & (p.gauge == r.gauge)).any())))
    d = pd.DataFrame(rows)
    print("with a sibling publication of the same post covering the same dates:", int(d.sibling.notna().sum()))
    print("equal share with that sibling:", pd.cut(d.equal_frac, [-.01, .5, .9, .99, 1.0]).value_counts().sort_index().to_dict())
    print("no sibling for those dates (body year otherwise absent for this post and gauge):", int(d.sibling.isna().sum()))
    print("catalogue year present in another publication of the same post and gauge:", int(d.has_cat_year_elsewhere.sum()))
    d.to_csv(OUT / "m2_year_mismatch.csv", index=False)
    # duplicates among all publications of one post: identical bodies
    dup = 0
    for pid, g in p.groupby("post_id"):
        ids = list(g.index)
        for i in range(len(ids)):
            for k in range(i + 1, len(ids)):
                a, b = vals.get(ids[i]), vals.get(ids[k])
                if a is None or b is None:
                    continue
                j = a.index.intersection(b.index)
                if len(j) >= 300 and float((a[j] == b[j]).mean()) >= .99 and g.loc[ids[i], "gauge"] != g.loc[ids[k], "gauge"]:
                    dup += 1
    print("pairs of publications of one post with different gauge types but >= 99% equal values on >= 300 shared dates:", dup)
    return d



def m2b(obs, pubs, posts):
    """For each mismatched publication: daily r with CPC at the body dates vs re-dated to the catalogue year (same month-day)."""
    print("== M2b: which year do the mismatched publications belong to? (CPC daily r, best lag -1..+1)")
    import xarray as xr
    d = pd.read_csv(OUT / "m2_year_mismatch.csv")
    cpc = xr.open_dataset(CPC).precip
    lon360 = float(cpc.lon.max()) > 180
    pos = posts.dropna(subset=["lat"]).set_index("post_id")
    res = []
    for r in d.itertuples():
        if r.post_id not in pos.index:
            continue
        s = obs[obs.pubId == r.pubId].set_index("date").value
        c = cpc.sel(lat=pos.at[r.post_id, "lat"], lon=pos.at[r.post_id, "lon"] % 360 if lon360 else pos.at[r.post_id, "lon"], method="nearest").to_series()
        def best(idx):
            out = []
            for L in (-1, 0, 1):
                x = c.reindex(idx + pd.Timedelta(days=L)).to_numpy()
                m = ~np.isnan(x)
                out.append(np.corrcoef(s.to_numpy()[m], x[m])[0, 1] if m.sum() > 200 and s.std() > 0 else np.nan)
            return np.nanmax(out) if not all(np.isnan(out)) else np.nan
        dy = int(r.year_cat - r.year_body)
        shifted = pd.to_datetime([f"{x.year + dy}-{x.month:02d}-{min(x.day, 28) if x.month == 2 and x.day == 29 else x.day:02d}" for x in s.index])
        res.append(dict(pubId=r.pubId, name=r.name, year_cat=r.year_cat, year_body=r.year_body, equal_frac=r.equal_frac,
                        r_body=best(s.index), r_catalogue=best(shifted)))
    e = pd.DataFrame(res)
    e["verdict"] = np.where(e.r_catalogue - e.r_body >= 0.1, "catalogue year", np.where(e.r_body - e.r_catalogue >= 0.1, "body year", "undecided"))
    print(e.groupby(["verdict", pd.cut(e.equal_frac, [-.01, .5, .9, 1.0])]).size().to_string())
    print("median r body / catalogue:", round(e.r_body.median(), 2), round(e.r_catalogue.median(), 2))
    e.to_csv(OUT / "m2b_year_verdict.csv", index=False)



def tz_of(lat, lon):
    """Approximate Indonesian time zone from position: WIB west of 114.6E, WIT east of 125.5E, else WITA [approximation]."""
    return "WIB" if lon < 114.6 else ("WIT" if lon >= 125.5 else "WITA")


def m4(obs, pubs, posts):
    print("== M4 day key vs CPC. Key = 00:00 UTC of the date. Correctly labelled BMKG matches CPC at lag -1 (config daylabel, F38).")
    import xarray as xr
    cpc = xr.open_dataset(CPC).precip
    lon360 = float(cpc.lon.max()) > 180
    o = obs.merge(pubs[["pubId", "post_id", "gauge", "year_cat"]], on="pubId")
    o = o[o.date.dt.year == o.year_cat]
    pos = posts.dropna(subset=["lat"]).set_index("post_id")
    rows = []
    for (pid, gauge), g in o.groupby(["post_id", "gauge"]):
        if pid not in pos.index or len(g) < 300:
            continue
        s = g.drop_duplicates("date").set_index("date").value.sort_index()
        if s.std() == 0:
            continue
        c = cpc.sel(lat=pos.at[pid, "lat"], lon=pos.at[pid, "lon"] % 360 if lon360 else pos.at[pid, "lon"], method="nearest").to_series()
        r = {}
        for L in (-2, -1, 0, 1):
            x = c.reindex(s.index + pd.Timedelta(days=L)).to_numpy()
            m = ~np.isnan(x)
            r[L] = np.corrcoef(s.to_numpy()[m], x[m])[0, 1] if m.sum() > 200 else np.nan
        if all(np.isnan(v) for v in r.values()):
            continue
        bl = max(r, key=lambda k: -1 if np.isnan(r[k]) else r[k])
        srt = sorted([v for v in r.values() if not np.isnan(v)], reverse=True)
        rows.append(dict(post_id=pid, gauge=gauge, tz=tz_of(pos.at[pid, "lat"], pos.at[pid, "lon"]), n=len(s), best_lag=bl,
                         r_best=srt[0], margin=srt[0] - srt[1] if len(srt) > 1 else np.nan, **{f"r{k}": v for k, v in r.items()}))
    d = pd.DataFrame(rows)
    print("series", len(d))
    print("best lag by time zone (margin >= 0.05 only):")
    print(d[d.margin >= 0.05].groupby(["tz", "best_lag"]).size().unstack(fill_value=0).to_string())
    print("by gauge type:")
    print(d[d.margin >= 0.05].groupby(["gauge", "best_lag"]).size().unstack(fill_value=0).to_string())
    print("median r by lag:", d[["r-2", "r-1", "r0", "r1"]].median().round(3).to_dict())
    d.to_csv(OUT / "m4_lag.csv", index=False)



def m5(obs, pubs, posts):
    print("== M5 overlap with stations already in the build (within 5 km)")
    st = pd.read_csv(COMPILED / "stations.csv.gz")
    st = st.dropna(subset=["lat", "lon"])
    P = posts.dropna(subset=["lat"])
    pairs = []
    for a in P.itertuples():
        near = st[(st.lat - a.lat).abs().lt(0.05) & (st.lon - a.lon).abs().lt(0.05)]
        for b in near.itertuples():
            dk = km(a.lat, a.lon, b.lat, b.lon)
            if dk <= 5:
                pairs.append(dict(post_id=a.post_id, sihka_name=a.name, station_key=b.station_key, source=b.source, name=b.name, km=round(dk, 2)))
    pr = pd.DataFrame(pairs)
    print("SIHKA posts with a build station within 5 km:", pr.post_id.nunique(), "; pairs", len(pr), "; by source", pr.source.value_counts().to_dict())
    ser = pd.read_csv(COMPILED / "series.csv.gz", usecols=["series_id", "station_key", "variable"])
    ser = ser[(ser.variable == "RR") & ser.station_key.isin(pr.station_key)]
    ids = set(ser.series_id)
    ob = pd.concat(c[c.series_id.isin(ids)] for c in pd.read_csv(COMPILED / "observations_RR.csv.gz", usecols=["series_id", "date_raw", "value"],
                                                                  chunksize=2_000_000))
    ob["date_raw"] = pd.to_datetime(ob.date_raw)
    ob = ob.merge(ser[["series_id", "station_key"]], on="series_id")
    o = obs.merge(pubs[["pubId", "post_id", "gauge", "year_cat"]], on="pubId")
    o = o[(o.date.dt.year == o.year_cat)]
    sv = {k: g.drop_duplicates("date").set_index("date").value for k, g in o.groupby("post_id")}
    bv = {k: g.drop_duplicates("date_raw").set_index("date_raw").value for k, g in ob.groupby("station_key")}
    rows = []
    for r in pr.itertuples():
        a, b = sv.get(r.post_id), bv.get(r.station_key)
        if a is None or b is None:
            continue
        best = None
        for L in (-1, 0, 1):
            bb = b.copy(); bb.index = bb.index - pd.Timedelta(days=L)
            j = a.index.intersection(bb.index)
            if len(j) < 60:
                continue
            x, y = a[j], bb[j]
            keep = x.notna() & y.notna()
            x, y = x[keep], y[keep]
            if len(x) < 60:
                continue
            wet = (x > 0) | (y > 0)
            eq = float(((x - y).abs() <= 0.5)[wet].mean()) if wet.any() else np.nan
            rr = np.corrcoef(x, y)[0, 1] if x.std() > 0 and y.std() > 0 else np.nan
            if best is None or (not np.isnan(rr) and rr > best[2]):
                best = (L, len(j), rr, eq)
        if best:
            rows.append(dict(r._asdict(), lag=best[0], n_overlap=best[1], r=best[2], equal_wet=best[3]))
    d = pd.DataFrame(rows).drop(columns="Index")
    print("pairs with >= 60 shared days:", len(d))
    if len(d):
        print("equal share on wet days:", pd.cut(d.equal_wet, [-.01, .3, .6, .9, 1.0]).value_counts().sort_index().to_dict())
        print("r:", pd.cut(d.r, [-1, .3, .6, .8, 1.0]).value_counts().sort_index().to_dict())
        print(d.sort_values("equal_wet", ascending=False).head(15).to_string(index=False))
    pr.to_csv(OUT / "m5_pairs.csv", index=False)
    d.to_csv(OUT / "m5_overlap.csv", index=False)



def _with_refs(obs, pubs, posts):
    """Daily table (catalogue-year dates) with CPC at lag 0 (M4: most series match CPC day D) and the median of posts within 25 km."""
    import xarray as xr
    cpc = xr.open_dataset(CPC).precip
    lon360 = float(cpc.lon.max()) > 180
    o = obs.merge(pubs[["pubId", "post_id", "gauge", "year_cat"]], on="pubId")
    o = o[o.date.dt.year == o.year_cat].copy()
    pos = posts.dropna(subset=["lat"]).set_index("post_id")
    o = o[o.post_id.isin(pos.index)]
    parts = []
    for pid, g in o.groupby("post_id"):
        c = cpc.sel(lat=pos.at[pid, "lat"], lon=pos.at[pid, "lon"] % 360 if lon360 else pos.at[pid, "lon"], method="nearest").to_series()
        parts.append(g.assign(cpc=c.reindex(g.date).to_numpy()))
    o = pd.concat(parts)
    wide = o[o.gauge == "MANUAL"].pivot_table(index="date", columns="post_id", values="value", aggfunc="first")
    P = pos[["lat", "lon"]]
    nbm = {}
    for a in P.itertuples():
        q = [b.Index for b in P.itertuples() if b.Index != a.Index and abs(b.lat - a.lat) < .3 and abs(b.lon - a.lon) < .3
             and km(a.lat, a.lon, b.lat, b.lon) <= 25 and b.Index in wide]
        if q:
            nbm[a.Index] = wide[q].median(axis=1)
    o["nb_median"] = np.nan
    for pid, s in nbm.items():
        m = o.post_id == pid
        o.loc[m, "nb_median"] = s.reindex(o.loc[m, "date"]).to_numpy()
    return o


def m6(obs, pubs, posts):
    print("== M6 provider day flags (note / status) vs CPC and neighbours; M7 values above 500 mm")
    o = _with_refs(obs, pubs, posts)
    o.to_pickle(OUT / "daily_with_refs.pkl")
    lab = np.select([o.note.astype(str).str.contains("tidak realistis", case=False) | (o.day_status == "tidak_realistis"),
                     o.note.astype(str).str.contains("meragukan", case=False) | (o.day_status == "meragukan")],
                    ["unrealistic", "doubtful"], "none")
    o["prov"] = lab
    t = o.groupby("prov").agg(n=("value", "size"), posts=("post_id", "nunique"), value_median=("value", "median"),
                              frac_zero=("value", lambda v: round(float((v == 0).mean()), 3)), value_p99=("value", lambda v: v.quantile(.99)),
                              cpc_median=("cpc", "median"), nb_median=("nb_median", "median"))
    print(t.to_string())
    for k in ("doubtful", "unrealistic"):
        g = o[o.prov == k]
        print(f"{k}: share of all-zero... by month of the post: {g.groupby(['post_id', g.date.dt.to_period('M')]).size().describe().round(1).to_dict()}")
    big = o[o.value > 500].copy()
    big["nb_max"] = np.nan
    print(f"M7: values > 500 mm: {len(big)} at {big.post_id.nunique()} posts; provider flag {big.prov.value_counts().to_dict()}")
    print("CPC on those days:", big.cpc.describe().round(1).to_dict())
    print("neighbour median on those days:", big.nb_median.describe().round(1).to_dict())
    print("values:", sorted(big.value.astype(int).tolist())[-20:])
    big.merge(posts[["post_id", "name", "unit"]], on="post_id")[["name", "unit", "gauge", "date", "value", "note", "day_status", "cpc", "nb_median"]]         .to_csv(OUT / "m7_above_500.csv", index=False)
    o[o.prov != "none"].to_csv(OUT / "m6_provider_flags.csv.gz", index=False)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    obs, pubs = load(force=(what == "load"))
    print(f"loaded {len(obs):,} values from {len(pubs)} publications")
    posts = m3(obs, pubs) if what in ("m3", "all") or not (OUT / "posts.csv").exists() else pd.read_csv(OUT / "posts.csv")
    for k, fn in (("m1", m1), ("m2", m2), ("m2b", m2b), ("m4", m4), ("m5", m5), ("m6", m6)):
        if what in (k, "all"):
            fn(obs, pubs, posts)
