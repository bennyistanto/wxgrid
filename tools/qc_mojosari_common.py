"""Shared loaders for the agro:MOJOSARI audit (tools/qc_mojosari_*.py). Read-only on compiled/.

Caches under F:/temp/station/qc_mojosari/cache (never in compiled/):
  obs_ejava.pkl  RR observations 1970-2000 of every series whose station lies in the East
                 Java box (lat -9.0..-6.5, lon 110.8..114.7), all columns.
CPC-UNI: station date D in the BMKG target convention matches CPC day D-1 (config daylabel
cpc_uni target_lag -1, F38). Here lag k always means: agro value on day D paired with the
reference on day D+k, where for CPC "day D+k" is CPC day D+k-1. So lag 0 = agro labelled like a
correctly labelled BMKG series; lag +1 = agro carries the label of the day before.
"""
import os

import numpy as np
import pandas as pd

COMP = "F:/temp/station/compiled"
OUT = "F:/temp/station/qc_mojosari"
CACHE = os.path.join(OUT, "cache")
CPC = "F:/temp/station/cpc/idn_cpc_1979_2025.nc"
A = "agro:MOJOSARI:RR"
BOX = dict(lat=(-9.0, -6.5), lon=(110.8, 114.7))
os.makedirs(CACHE, exist_ok=True)
BAD = "src_duplicate|qc_excluded"


def stations():
    return pd.read_csv(f"{COMP}/stations.csv.gz", dtype={"wmo_id": str, "source_station_id": str})


def series():
    return pd.read_csv(f"{COMP}/series.csv.gz")


def rr_meta():
    """RR series with station position, East Java box only."""
    se = series(); st = stations()
    r = se[se.variable == "RR"].merge(st[["station_key", "name", "lat", "lon", "elev_m", "site_id", "source"]],
                                      on="station_key", suffixes=("", "_st"))
    return r[r.lat.between(*BOX["lat"]) & r.lon.between(*BOX["lon"])].reset_index(drop=True)


def obs_ejava():
    p = os.path.join(CACHE, "obs_ejava.pkl")
    if os.path.exists(p) and os.path.getmtime(p) > os.path.getmtime(f"{COMP}/observations_RR.csv.gz"):
        return pd.read_pickle(p)
    ids = set(rr_meta().series_id)
    out = []
    for c in pd.read_csv(f"{COMP}/observations_RR.csv.gz", chunksize=2_000_000, low_memory=False,
                         dtype={"flag": str, "label": str}):
        c = c[c.series_id.isin(ids)]
        c = c[(c.date_raw >= "1970-01-01") & (c.date_raw <= "2000-12-31")]
        out.append(c)
    o = pd.concat(out)
    o["date"] = pd.to_datetime(o["date"]); o["date_raw"] = pd.to_datetime(o["date_raw"])
    o.to_pickle(p)
    return o


def daily(o, sid, col="date", drop_bad=True, unmeasurable_as=None):
    """Daily series (asfreq D) for one series_id. unmeasurable rows have NaN value; set
    unmeasurable_as=0.0 to read them as dry."""
    g = o[o.series_id == sid]
    if drop_bad:
        g = g[~g.flag.fillna("").str.contains(BAD)]
    s = g.set_index(col).value
    if unmeasurable_as is not None:
        um = g.flag.fillna("").str.contains("unmeasurable").values
        s = s.where(~um, unmeasurable_as)
    s = s[~s.index.duplicated()].sort_index()
    return s.asfreq("D") if len(s) else s


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


class CPCField:
    def __init__(self):
        import xarray as xr
        ds = xr.open_dataset(CPC)
        self.lat = ds.lat.values; self.lon = ds.lon.values
        self.t0 = pd.Timestamp(ds.time.values[0]); self.nt = ds.sizes["time"]
        self.P = ds.precip.values.astype(np.float32)

    def cell(self, lat, lon):
        return int(np.abs(self.lat - lat).argmin()), int(np.abs(self.lon - lon).argmin())

    def series(self, lat, lon):
        """CPC indexed by station day: value at D = CPC day D-1 (target convention)."""
        i, j = self.cell(lat, lon)
        return pd.Series(self.P[:, i, j], index=pd.date_range(self.t0, periods=self.nt, freq="D")
                         + pd.Timedelta(days=1))


def pearson(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return np.nan, int(m.sum())
    return float(np.corrcoef(a[m], b[m])[0, 1]), int(m.sum())


def lagged(ref, idx, k):
    """Reference values on day D+k for each D in idx."""
    return ref.reindex(idx + pd.Timedelta(days=k)).values


def hit_rate(a, b, thr=1.0):
    """P(reference wet | agro wet) and P(agro wet | reference wet) with wet = >= thr mm."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    aw = a[m] >= thr; bw = b[m] >= thr
    h = (aw & bw).sum() / aw.sum() if aw.sum() else np.nan
    h2 = (aw & bw).sum() / bw.sum() if bw.sum() else np.nan
    return h, h2
