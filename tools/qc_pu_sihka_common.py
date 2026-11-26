"""Shared loaders for the /qc audit of source `pu_sihka` (read-only on compiled/ and pu_sihka/).

Caches go to F:/temp/station/qc_pu_sihka/cache (never into compiled/ or pu_sihka/).
Used by tools/qc_pu_sihka_*.py.

  pu_obs()      observations_RR rows whose series_id starts with "pu_sihka:" (date, date_raw, value, flag, label)
  pu_stations() stations.csv.gz rows of source pu_sihka, with site_id
  merged()      merged_RR (all sites): site_id, date, value, flag, series_id, label
  site_xy()     sites.csv positions
  CPCField      CPC-UNI daily at the nearest 0.5 deg cell (from tools/qc_phase2_common.py)
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
COMP = "F:/temp/station/compiled"
PU = "F:/temp/station/pu_sihka"
OUT = "F:/temp/station/qc_pu_sihka"
CACHE = os.path.join(OUT, "cache")
CPC = "F:/temp/station/cpc/idn_cpc_1979_2025.nc"
os.makedirs(CACHE, exist_ok=True)


def _cached(name, fn):
    p = os.path.join(CACHE, name + ".pkl")
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    obj = fn()
    with open(p, "wb") as f:
        pickle.dump(obj, f, protocol=5)
    return obj


def pu_obs():
    def load():
        parts = []
        for c in pd.read_csv(f"{COMP}/observations_RR.csv.gz", chunksize=2_000_000,
                             dtype={"series_id": str, "flag": str, "label": str}, keep_default_na=False,
                             na_values={"value": [""]}):
            c = c[c.series_id.str.startswith("pu_sihka:")]
            if len(c):
                parts.append(c)
        o = pd.concat(parts, ignore_index=True)
        o["date"] = pd.to_datetime(o.date)
        o["date_raw"] = pd.to_datetime(o.date_raw)
        o["station_key"] = o.series_id.str.rsplit(":", n=2).str[0]
        o["gauge"] = o.series_id.str.split(":").str[2]
        for k in ("series_id", "station_key", "gauge", "flag", "label"):
            o[k] = o[k].astype("category")
        return o
    return _cached("pu_obs", load)


def stations():
    return pd.read_csv(f"{COMP}/stations.csv.gz", dtype={"wmo_id": str, "source_station_id": str})


def pu_stations():
    s = stations()
    return s[s.source == "pu_sihka"].reset_index(drop=True)


def series():
    return pd.read_csv(f"{COMP}/series.csv.gz")


def site_xy():
    return pd.read_csv(f"{COMP}/sites.csv", dtype={"wmo_id": str})


def merged():
    def load():
        parts = []
        for c in pd.read_csv(f"{COMP}/merged_RR.csv.gz", chunksize=3_000_000,
                             usecols=["site_id", "date", "value", "flag", "series_id"],
                             dtype={"site_id": str, "flag": str, "series_id": str}, keep_default_na=False,
                             na_values={"value": [""]}):
            c = c[c.date >= "1975-01-01"]
            parts.append(c)
        m = pd.concat(parts, ignore_index=True)
        m["date"] = pd.to_datetime(m.date)
        for k in ("site_id", "flag", "series_id"):
            m[k] = m[k].astype("category")
        return m
    return _cached("merged_1975", load)


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


class CPCField:
    """CPC-UNI daily at the nearest 0.5 deg cell. A series in the BMKG target convention matches
    CPC day D-1 (config daylabel cpc_uni target_lag -1, F38); PU raw dates mostly match CPC day D (F68 M4)."""
    def __init__(self):
        import xarray as xr
        ds = xr.open_dataset(CPC)
        self.lat = ds.lat.values
        self.lon = ds.lon.values
        self.t0 = pd.Timestamp(ds.time.values[0])
        self.nt = ds.sizes["time"]
        self.P = ds.precip.values.astype(np.float32)

    def cell(self, lat, lon):
        return int(np.abs(self.lat - lat).argmin()), int(np.abs(self.lon - lon).argmin())

    def at(self, lat, lon, dates, lag=0):
        i, j = self.cell(lat, lon)
        k = (pd.DatetimeIndex(dates) - self.t0).days.values + lag
        out = np.full(len(k), np.nan, dtype=np.float32)
        ok = (k >= 0) & (k < self.nt)
        out[ok] = self.P[k[ok], i, j]
        return out


def pearson(a, b, min_n=10):
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < min_n or a[m].std() == 0 or b[m].std() == 0:
        return np.nan, int(m.sum())
    return float(np.corrcoef(a[m], b[m])[0, 1]), int(m.sum())


def pu_wide(o=None, date_col="date_raw", flags_ok=("",)):
    """Daily wide table of PU MANUAL+other series by station_key (first value per date), raw dates by default."""
    o = pu_obs() if o is None else o
    if flags_ok is not None:
        o = o[o.flag.astype(str).isin(flags_ok)]
    return o.pivot_table(index=date_col, columns="series_id", values="value", aggfunc="first", observed=True)


def panel(start="1996-01-01"):
    """Daily wide panel for neighbour tests, unflagged values only, from `start`:
    columns "pu:<series_id>" (PU, raw dates: PU-PU comparisons share the PU key convention) and
    "site:<site_id>" (merged view of non-PU series, corrected dates; BMKG-convention data are one day
    later than most PU raw dates, F68 M4, so callers use lags -1..+1 or D-1..D+1 windows).
    Returns (wide DataFrame float32, meta DataFrame: col, kind, key, lat, lon, station_key, unit)."""
    def load():
        o = pu_obs()
        o = o[(o.flag.astype(str) == "") & (o.date_raw >= start)]
        w1 = o.pivot_table(index="date_raw", columns="series_id", values="value", aggfunc="first", observed=True)
        w1.columns = ["pu:" + str(x) for x in w1.columns]
        m = merged()
        m = m[(m.flag.astype(str) == "") & (m.date >= start) & ~m.series_id.astype(str).str.startswith("pu_sihka:")]
        w2 = m.pivot_table(index="date", columns="site_id", values="value", aggfunc="first", observed=True)
        w2.columns = ["site:" + str(x) for x in w2.columns]
        idx = pd.date_range(start, max(w1.index.max(), w2.index.max()), freq="D")
        w = pd.concat([w1.reindex(idx), w2.reindex(idx)], axis=1).astype("float32")
        st = pu_stations().set_index("station_key")
        posts = pd.read_csv(f"{PU}/measure/posts.csv").set_index("integration_id")
        meta = []
        for col in w1.columns:
            sid = col[3:]
            sk = sid.rsplit(":", 2)[0]
            meta.append(dict(col=col, kind="pu", key=sid, station_key=sk, lat=st.at[sk, "lat"], lon=st.at[sk, "lon"],
                             unit=posts.unit.get(st.at[sk, "source_station_id"], "")))
        sx = site_xy().set_index("site_id")
        for col in w2.columns:
            s = col[5:]
            meta.append(dict(col=col, kind="site", key=s, station_key=sx.at[s, "representative_station"],
                             lat=sx.at[s, "lat"], lon=sx.at[s, "lon"], unit=sx.at[s, "sources"]))
        return w, pd.DataFrame(meta)
    return _cached(f"panel_{start[:4]}", load)


def neighbours(meta, lat, lon, km, exclude_cols=()):
    d = haversine_km(lat, lon, meta.lat.values, meta.lon.values)
    m = (d <= km) & ~meta.col.isin(exclude_cols).values
    return meta.col.values[m], d[m]


def refs(nb_km=25.0):
    """Every PU value (pu_obs rows, raw dates) with reference values around its raw date D:
      cpc0, cpc3max      CPC at D and max over D-1..D+1 (PU raw D mostly matches CPC D, F68 M4)
      pu_med0            median of PU neighbours (<= nb_km, unflagged) on D
      pu_med3, pu_max3   median and max over PU neighbours of each neighbour's max over D-1..D+1; pu_n
      site_max4, site_n  max over non-PU merged sites (<= nb_km) of D-1..D+2 (their dates are BMKG-convention,
                         about one day later than PU raw dates)
    Cached as refs_<km>.pkl."""
    def load():
        o = pu_obs().reset_index(drop=True)
        w, meta = panel()
        vals = w.to_numpy()
        t0 = w.index[0]
        st = pu_stations().set_index("station_key")
        cpc = CPCField()
        out = {k: np.full(len(o), np.nan, dtype="float32") for k in
               ("cpc0", "cpc3max", "pu_med0", "pu_med3", "pu_max3", "pu_n", "site_max4", "site_n")}
        nd = len(w)

        def roll_max(a, lo, hi):
            r = np.full_like(a, np.nan)
            for L in range(lo, hi + 1):
                s = np.full_like(a, np.nan)
                if L >= 0:
                    s[:nd - L] = a[L:]
                else:
                    s[-L:] = a[:nd + L]
                r = np.fmax(r, s)
            return r
        for sk, idx in o.groupby("station_key", observed=True).indices.items():
            la, lo = st.at[sk, "lat"], st.at[sk, "lon"]
            d = pd.DatetimeIndex(o.date_raw.values[idx])
            out["cpc0"][idx] = cpc.at(la, lo, d, lag=0)
            out["cpc3max"][idx] = np.fmax(np.fmax(cpc.at(la, lo, d, lag=-1), cpc.at(la, lo, d, lag=0)), cpc.at(la, lo, d, lag=1))
            k = (d - t0).days.values
            okk = (k >= 0) & (k < nd)
            cols, _ = neighbours(meta, la, lo, nb_km)
            sel = meta.col.isin(cols).values & (meta.station_key.values != sk)
            pu = np.where(sel & (meta.kind.values == "pu"))[0]
            si = np.where(sel & (meta.kind.values == "site"))[0]
            ii = idx[okk]
            kk = k[okk]
            with np.errstate(all="ignore"):
                import warnings
                warnings.simplefilter("ignore", RuntimeWarning)
                if len(pu):
                    A = vals[:, pu]
                    A3 = roll_max(A, -1, 1)
                    out["pu_med0"][ii] = np.nanmedian(A[kk], axis=1)
                    out["pu_med3"][ii] = np.nanmedian(A3[kk], axis=1)
                    out["pu_max3"][ii] = np.nanmax(A3[kk], axis=1)
                    out["pu_n"][ii] = np.isfinite(A3[kk]).sum(1)
                if len(si):
                    B4 = roll_max(vals[:, si], -1, 2)
                    out["site_max4"][ii] = np.nanmax(B4[kk], axis=1)
                    out["site_n"][ii] = np.isfinite(B4[kk]).sum(1)
        r = o[["series_id", "station_key", "gauge", "date_raw", "date", "value", "flag", "label"]].copy()
        for k2, v in out.items():
            r[k2] = v
        return r
    return _cached(f"refs_{int(nb_km)}", load)
