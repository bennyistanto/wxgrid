"""Shared loaders for the phase-2 /qc audit (read-only on F:/temp/station/compiled).

Caches parsed tables as pickles under F:/temp/station/qc_phase2/cache (never in compiled/).
Used by tools/qc_phase2_audit.py, qc_dash_months.py, qc_mojosari.py, qc_chind_x.py.
"""
import os
import pickle

import numpy as np
import pandas as pd

COMP = "F:/temp/station/compiled"
OUT = "F:/temp/station/qc_phase2"
CACHE = os.path.join(OUT, "cache")
CPC = "F:/temp/station/cpc/idn_cpc_1979_2025.nc"
os.makedirs(CACHE, exist_ok=True)

PHASE2 = ["bmg_posts", "sumbar_daily", "larantuka", "sumsel_posts"]


def _cached(name, fn):
    p = os.path.join(CACHE, name + ".pkl")
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    obj = fn()
    with open(p, "wb") as f:
        pickle.dump(obj, f, protocol=5)
    return obj


def stations():
    return pd.read_csv(f"{COMP}/stations.csv.gz", dtype={"wmo_id": str, "source_station_id": str})


def series():
    return pd.read_csv(f"{COMP}/series.csv.gz")


def sites():
    return pd.read_csv(f"{COMP}/sites.csv", dtype={"wmo_id": str})


def obs_rr():
    """Full observations_RR (all sources), categorical ids."""
    def load():
        return pd.read_csv(
            f"{COMP}/observations_RR.csv.gz",
            dtype={"series_id": "category", "flag": "category", "label": "category", "value": "float64"},
            parse_dates=["date", "date_raw"])
    return _cached("obs_RR", load)


def merged_rr():
    def load():
        return pd.read_csv(
            f"{COMP}/merged_RR.csv.gz",
            dtype={"site_id": "category", "flag": "category", "series_id": "category",
                   "label": "category", "value": "float64"},
            parse_dates=["date", "date_raw"])
    return _cached("merged_RR", load)


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


class CPCField:
    """CPC-UNI daily at the nearest 0.5 deg cell. Station date D in the target convention
    (24 h ending 07:00 local, labelled with the end date) matches CPC day D-1
    (config daylabel.gridded_references cpc_uni target_lag -1, F38)."""
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

    def series(self, lat, lon):
        i, j = self.cell(lat, lon)
        return pd.Series(self.P[:, i, j], index=pd.date_range(self.t0, periods=self.nt, freq="D"))

    def at(self, lat, lon, dates, lag=-1):
        i, j = self.cell(lat, lon)
        k = (pd.DatetimeIndex(dates) - self.t0).days.values + lag
        out = np.full(len(k), np.nan, dtype=np.float32)
        ok = (k >= 0) & (k < self.nt)
        out[ok] = self.P[k[ok], i, j]
        return out


def pearson(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return np.nan, int(m.sum())
    return float(np.corrcoef(a[m], b[m])[0, 1]), int(m.sum())
