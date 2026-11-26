"""Shared references for the agro checks: CPC-UNI daily cells (0.5 deg, 1979+) and
neighbouring gauges (non-agro sites of the compiled merged rainfall, 1970-1996), with a
lag-tolerant (-1/0/+1 day) Pearson correlation and a margin-based decision rule.
Imported by tools/agro_cpc_checks.py and tools/agro_scan_year.py."""
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

B = Path("F:/temp/station/additional-sources")
R = pd.read_csv(B / "_agro_raw_records.csv.gz", parse_dates=["date"])
R = R[(R["var"] == "RR") & R["value"].notna()].drop_duplicates(["file", "sheet", "date"])
S = pd.read_csv(B / "_agro_raw_sheets_coords.csv")
S = S[S["status"] == "ok"]
C = pd.read_csv(B / "_agro_station_catalogue.csv").set_index("station")
cpc = xr.open_dataset("F:/temp/station/cpc/idn_cpc_1979_2025.nc")["precip"].sel(
    time=slice("1979-01-01", "1996-12-31")).load()
LATS, LONS = cpc["lat"].values, cpc["lon"].values


def cell(lat, lon):
    return int(np.abs(LATS - lat).argmin()), int(np.abs(LONS - lon).argmin())


def cpc_series(i, j):
    return pd.Series(cpc.values[:, i, j], index=pd.DatetimeIndex(cpc["time"].values))


def rbest(s, ref):
    """Best Pearson r of s (daily, date index) with ref over lags -1, 0, +1."""
    best = (np.nan, None, 0)
    for lag in (-1, 0, 1):
        x = ref.shift(-lag).reindex(s.index)
        ok = x.notna() & s.notna()
        if ok.sum() < 60:
            continue
        r = np.corrcoef(s[ok], x[ok])[0, 1]
        if np.isnan(best[0]) or r > best[0]:
            best = (r, lag, int(ok.sum()))
    return best


# neighbouring gauges (non-agro sources in the compiled merged rainfall), Indonesia, 1970-1996
_st = pd.read_csv("F:/temp/station/compiled/stations.csv.gz")
_st = _st[_st["site_id"].notna() & (_st["source"] != "agro")]
SITES = _st.groupby("site_id")[["lat", "lon"]].first()
_m = pd.read_csv("F:/temp/station/compiled/merged_RR.csv.gz", usecols=["site_id", "date", "value", "series_id"])
_m = _m[(~_m["series_id"].str.startswith("agro:")) & _m["site_id"].isin(SITES.index) & _m["value"].notna()]
_m = _m[(_m["date"] >= "1970-01-01") & (_m["date"] <= "1996-12-31")]
_m["date"] = pd.to_datetime(_m["date"])
NB = {sid: g.set_index("date")["value"] for sid, g in _m.groupby("site_id")}
del _m


def neighbours(lat, lon, radius_km=50):
    d = SITES.apply(lambda r: km(lat, lon, r["lat"], r["lon"]), axis=1)
    return [(sid, round(dd, 1)) for sid, dd in d[d <= radius_km].sort_values().items() if sid in NB]


def rnb(s, lat, lon):
    """Best r (lags -1/0/+1) with any neighbouring gauge within 50 km; (r, site, km)."""
    best = (np.nan, None, None)
    for sid, dd in neighbours(lat, lon):
        r = rbest(s, NB[sid])[0]
        if not np.isnan(r) and (np.isnan(best[0]) or r > best[0]):
            best = (r, sid, dd)
    return best


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


KEYS = {re.sub(r"[^A-Z]", "", s.upper())[:6]: s for s in C.index}


def name_to_station(n):
    k = re.sub(r"[^A-Z]", "", str(n).upper())
    if len(k) < 4:
        return None
    return next((s for kk, s in KEYS.items() if k.startswith(kk[:6]) or kk.startswith(k[:6])), None)


def decide(ra, rb, a, b):
    if np.isnan(ra) and np.isnan(rb):
        return "untestable"
    ra, rb = (-1 if np.isnan(ra) else ra), (-1 if np.isnan(rb) else rb)
    hi, lo, w = (ra, rb, a) if ra >= rb else (rb, ra, b)
    return w if hi >= 0.15 and hi - lo >= 0.10 else "ambiguous"


