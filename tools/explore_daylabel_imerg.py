"""Per-series, per-year day-label test against IMERG Final daily (UTC days). Exploratory.

For every RR series in the compiled dataset with data in the IMERG period, take the
IMERG cell containing the station and compute, per calendar year (>= 200 paired days),
Pearson r between station value on date D and IMERG on UTC day D + lag, for
lag in -2..+1. The lag with the highest r is that year's label offset relative to UTC.

Expectation if a series is the 24 h total ending 07:00 local labelled with the end date:
best lag -1 (IMERG day D-1). Registry: BMKG Data Online FAQ (07:00 local), HBC
day-label (h = -23 against IMERG).

Run from the compiled output folder:
    python <repo>/tools/explore_daylabel_imerg.py F:/temp/hybrid-bias-correction/data/input/imergf/idn_imergf.nc4
Writes daylabel_imerg_by_year.csv there.
"""
import sys

import numpy as np
import pandas as pd
import xarray as xr

LAGS = [-2, -1, 0, 1]
imerg_path = sys.argv[1]

st = pd.read_csv("stations.csv.gz")
se = pd.read_csv("series.csv.gz", parse_dates=["first", "last"])
ser = se[(se.variable == "RR") & (se["last"] >= "2001-01-01")].merge(
    st[["station_key", "lat", "lon", "site_id"]], on="station_key")

ds = xr.open_dataset(imerg_path)
lat, lon = ds.lat.values, ds.lon.values
inside = ser.lat.between(lat.min() - 0.05, lat.max() + 0.05) & ser.lon.between(lon.min() - 0.05, lon.max() + 0.05)
ser = ser[inside].reset_index(drop=True)
ilat = np.abs(lat[None, :] - ser.lat.values[:, None]).argmin(1)
ilon = np.abs(lon[None, :] - ser.lon.values[:, None]).argmin(1)
cells = sorted(set(zip(ilat, ilon)))
cell_idx = {c: k for k, c in enumerate(cells)}
print(f"{len(ser)} series, {len(cells)} IMERG cells")

# IMERG point series, read year by year to bound memory
times = pd.DatetimeIndex(ds.time.values)
blocks = []
for yr in sorted(set(times.year)):
    sub = ds.precipitation.sel(time=str(yr)).values  # (t, lat, lon)
    blocks.append(sub[:, [c[0] for c in cells], [c[1] for c in cells]])
imerg = pd.DataFrame(np.concatenate(blocks), index=times)

need = set(ser.series_id)
o = pd.read_csv("observations_RR.csv.gz", usecols=["series_id", "date", "value", "flag"], dtype={"flag": str})
o = o[o.series_id.isin(need) & o.flag.isna() & (o.date >= "2000-12-29")]
o["date"] = pd.to_datetime(o["date"])

rows = []
for (sid, g) in o.groupby("series_id"):
    s = ser[ser.series_id == sid].iloc[0]
    im = imerg[cell_idx[(ilat[s.name], ilon[s.name])]]
    stn = g.set_index("date")["value"]
    for lag in LAGS:
        sat = im.copy()
        sat.index = sat.index - pd.Timedelta(days=lag)  # IMERG day D+lag aligned to station date D
        x, y = stn.align(sat, join="inner")
        df = pd.DataFrame({"x": x, "y": y}).dropna()
        for yr, d in df.groupby(df.index.year):
            if len(d) >= 200 and d.x.std() > 0 and d.y.std() > 0:
                rows.append(dict(series_id=sid, source=s.source, site_id=s.site_id, year=yr, lag=lag,
                                 n=len(d), r=d.x.corr(d.y)))
r = pd.DataFrame(rows)
r.to_csv("daylabel_imerg_by_year.csv", index=False)
best = r.loc[r.groupby(["series_id", "year"]).r.idxmax()]
print(best.groupby(["source", "lag"]).size().unstack(fill_value=0))
