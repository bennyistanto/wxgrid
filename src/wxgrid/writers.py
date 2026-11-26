"""Write compiled tables (gzipped CSV) and merged series (CF-1.8 timeSeries NetCDF)."""

from datetime import datetime, timezone

import netCDF4
import numpy as np
import pandas as pd

from . import __version__
from .schema import VARIABLES


def write_csv(df, path):
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, compression="gzip" if str(path).endswith(".gz") else None)


def write_merged_netcdf(merged, sites, variable, path, start, cfg, day_convention):
    """One file per variable. dims (station, time); values float32, source index int16."""
    if merged.empty:
        return
    meta = VARIABLES[variable]
    s = sites[sites["site_id"].isin(merged["site_id"].unique())].reset_index(drop=True)
    t0 = pd.Timestamp(start)
    m = merged[merged["date"] >= t0]
    t1 = m["date"].max()
    times = pd.date_range(t0, t1, freq="D")
    si = pd.Index(s["site_id"]).get_indexer(m["site_id"])
    ti = ((m["date"] - t0).dt.days).to_numpy()
    series_codes, series_idx = np.unique(m["series_id"].to_numpy(), return_inverse=True)

    val = np.full((len(s), len(times)), np.nan, dtype="float32")
    src = np.full((len(s), len(times)), -1, dtype="int16")
    flg = np.zeros((len(s), len(times)), dtype="int8")
    val[si, ti] = m["value"].to_numpy(dtype="float32")
    src[si, ti] = series_idx.astype("int16")
    flg[si, ti] = m["flag"].fillna("").ne("").to_numpy(dtype="int8")

    with netCDF4.Dataset(path, "w", format="NETCDF4") as nc:
        nc.Conventions = "CF-1.8"
        nc.featureType = "timeSeries"
        nc.title = f"Merged daily station series: {meta['long_name']}"
        # sources read by `post_forms` list their workbooks under `books` instead of one `path`
        where = lambda x: x.get("path") or ", ".join(b.get("path", b.get("glob", "")) for b in x.get("books", []))
        nc.source = "; ".join(f"{x['name']} ({where(x)})" for x in cfg["sources"])
        nc.history = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ} wxgrid {__version__} consolidate {cfg['_path']}"
        nc.references = "; ".join(sorted({x.get('citation', '') for x in cfg["sources"] if x.get('citation')}))
        nc.comment = ("Merged view: highest-priority series per site, lower-priority series fill gaps only. "
                      "Provenance per value in variable source_series. See series.csv.gz and crosswalk files.")
        nc.createDimension("station", len(s))
        nc.createDimension("time", len(times))
        nc.createDimension("n_series", len(series_codes))
        v = nc.createVariable("station_id", str, ("station",))
        v.cf_role = "timeseries_id"
        v[:] = s["site_id"].to_numpy(dtype=object)
        v = nc.createVariable("station_name", str, ("station",))
        v.long_name = "station name"
        v[:] = s["name"].astype(str).to_numpy(dtype=object)
        for name, col, units, std in [("lat", "lat", "degrees_north", "latitude"),
                                      ("lon", "lon", "degrees_east", "longitude"),
                                      ("alt", "elev_m", "m", "height")]:
            v = nc.createVariable(name, "f8", ("station",))
            v.units, v.standard_name = units, std
            v[:] = s[col].to_numpy(dtype="f8")
        v = nc.createVariable("time", "i4", ("time",))
        v.units = f"days since {t0:%Y-%m-%d}"
        v.calendar = "standard"
        v.standard_name = "time"
        v.long_name = f"date label of the daily value ({day_convention})"
        v[:] = np.arange(len(times), dtype="i4")
        v = nc.createVariable(variable, "f4", ("station", "time"), zlib=True, complevel=4, fill_value=np.float32(np.nan))
        v.units, v.long_name = meta["units"], meta["long_name"]
        if meta.get("standard_name"):   # some elements (e.g. radiation) have no clean CF name
            v.standard_name = meta["standard_name"]
        if meta.get("cell_methods"):
            v.cell_methods = meta["cell_methods"]
        v.coordinates = "time lat lon alt station_id"
        v[:] = val
        v = nc.createVariable(f"{variable}_flag", "i1", ("station", "time"), zlib=True, complevel=4)
        v.long_name = "1 = value carries a plausibility or source flag (see observations table)"
        v.flag_values, v.flag_meanings = np.array([0, 1], dtype="i1"), "ok flagged"
        v[:] = flg
        if "label" in m:
            codes = {"": 0, "verified": 1, "interpolated": 2, "uncertain": 3, "unverified": 4}
            lab = np.zeros((len(s), len(times)), dtype="int8")
            lab[si, ti] = m["label"].fillna("").map(codes).fillna(0).to_numpy(dtype="int8")
            v = nc.createVariable(f"{variable}_label", "i1", ("station", "time"), zlib=True, complevel=4)
            v.long_name = "day-label status of the value (date shifted to the target convention when verified/interpolated)"
            v.flag_values = np.array([0, 1, 2, 3, 4], dtype="i1")
            v.flag_meanings = "not_assessed verified interpolated uncertain unverified"
            v[:] = lab
        v = nc.createVariable("source_series", "i2", ("station", "time"), zlib=True, complevel=4, fill_value=np.int16(-1))
        v.long_name = "index into series_id: which source series supplied the value"
        v[:] = src
        v = nc.createVariable("series_id", str, ("n_series",))
        v[:] = series_codes.astype(object)
