"""Reader for GHCN-Daily station files (.dly) plus ghcnd-stations.txt.

Format per the GHCN-Daily readme (section III): one line per station, month and element;
31 day slots of VALUE(5) MFLAG(1) QFLAG(1) SFLAG(1); -9999 missing. PRCP and TMAX/TMIN/
TAVG are in tenths (mm, degC). Only the .dly files present in `path` are read, so the
download decides the domain; the bbox still applies.

Each (station, element, source flag) becomes its own series, because the source flag
says where the value came from (e.g. "S" = Global Summary of the Day from GTS synoptic
reports, "I" = international collection) and the day convention can differ by source.
A non-blank QFLAG (failed a GHCN quality check) is kept and flagged `src_qflag_<X>`.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import in_bbox


def read_stations(path):
    return pd.read_fwf(path, colspecs=[(0, 11), (12, 20), (21, 30), (31, 37), (41, 71), (80, 85)],
                       names=["id", "lat", "lon", "elev_m", "name", "wmo_id"], dtype={"wmo_id": str})


def read_dly(path, elements):
    """Long table: id, element, date, value (raw integer units), qflag, sflag."""
    rows = []
    for line in open(path, encoding="ascii", errors="ignore"):
        el = line[17:21]
        if el not in elements:
            continue
        year, month = int(line[11:15]), int(line[15:17])
        for d in range(31):
            o = 21 + d * 8
            v = int(line[o:o + 5])
            if v == -9999:
                continue
            rows.append((line[:11], el, year, month, d + 1, v, line[o + 5], line[o + 6], line[o + 7]))
    df = pd.DataFrame(rows, columns=["id", "element", "year", "month", "day", "value", "mflag", "qflag", "sflag"])
    df["date"] = pd.to_datetime(df[["year", "month", "day"]], errors="coerce")
    return df.dropna(subset=["date"])


def read(src, bbox):
    elements = src["elements"]          # e.g. {PRCP: RR, TMAX: TX, ...}
    scale = src.get("scale", {})        # e.g. {PRCP: 0.1, ...}
    meta = read_stations(src["stations_file"]).set_index("id")
    stations, series, obs = [], [], []
    files = sorted(Path(src["path"]).glob("*.dly"))
    if not files:
        raise FileNotFoundError(f"no .dly files under {src['path']}")
    for f in files:
        sid = f.stem
        if sid not in meta.index:
            continue
        m = meta.loc[sid]
        if not in_bbox(m["lat"], m["lon"], bbox):
            continue
        key = f"{src['name']}:{sid}"
        wmo = "" if pd.isna(m["wmo_id"]) else str(m["wmo_id"]).strip()
        stations.append(dict(station_key=key, source=src["name"], network=src.get("network", "GHCN-Daily"),
                             source_station_id=sid, name=str(m["name"]).strip(), lat=float(m["lat"]),
                             lon=float(m["lon"]), elev_m=float(m["elev_m"]) if m["elev_m"] > -999 else np.nan,
                             country=sid[:2], wmo_id=wmo))
        df = read_dly(f, set(elements))
        # series per element, source flag and measurement flag: GSOD daily rain built from
        # four 6-h reports (MFLAG D) and of unknown completeness (blank) stay apart (review fix 9)
        for (el, sflag, mflag), g in df.groupby(["element", "sflag", "mflag"]):
            var = elements[el]
            series_id = f"{key}:{sflag.strip() or '_'}{mflag.strip()}:{var}"
            q = g["qflag"].str.strip()
            series.append(dict(series_id=series_id, station_key=key, source=src["name"], variable=var,
                               units=src.get("units", {}).get(el, ""),
                               day_convention=src.get("day_convention", {}).get(sflag.strip(), src.get("day_convention", {}).get("default", "")),
                               n_values=len(g), n_missing_code=0, n_unparsed=0,
                               first=g["date"].min(), last=g["date"].max(),
                               note=f"element {el}, source flag {sflag}, measurement flag {mflag.strip() or 'blank'}"))
            obs.append(pd.DataFrame({"series_id": series_id, "date": g["date"].values,
                                     "value": g["value"].to_numpy(float) * float(scale.get(el, 1.0)),
                                     "flag": np.where(q.ne(""), "src_qflag_" + q, "")}))
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series")
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
