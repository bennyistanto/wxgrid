"""Reader for station data held as long CSV tables: one station table plus one or more
data tables with a row per station-day (year/month/day or a date column) and one column
per variable. Everything about the layout comes from the config, e.g.:

    stations: {file: tbl_station_info.csv, id: Stn_ID, name: Stn_Name,
               lat: Lat_DD, lon: Long_DD, elev: Msl}
    tables:
      - file: tbl_Rainfall.csv
        id: STN_ID
        date: {year: YEAR, month: MONTH, day: DAY}     # or date: {column: DATE, format: "%Y-%m-%d"}
        values: {Rainfall: RR}
    scale: {Rainfall: 0.1}
    missing_codes: [-999]

IDs are read as text, so leading zeros survive. Values equal to a missing code are dropped
and counted per series; `unmeasurable_codes` keep the row without a value, flagged
`unmeasurable`; `suspect_values` (raw, per column) are kept and flagged `code_suspect`.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import in_bbox


def _dates(df, spec):
    if "column" in spec:
        return pd.to_datetime(df[spec["column"]].astype(str), format=spec.get("format"), errors="coerce")
    parts = pd.DataFrame({"year": df[spec["year"]], "month": df[spec["month"]], "day": df[spec["day"]]})
    return pd.to_datetime(parts.apply(pd.to_numeric, errors="coerce"), errors="coerce")


def read(src, bbox):
    root = Path(src["path"])
    s = src["stations"]
    meta = pd.read_csv(root / s["file"], dtype={s["id"]: str})
    meta = meta.dropna(subset=[s["lat"], s["lon"]])
    keep = [in_bbox(a, b, bbox) for a, b in zip(meta[s["lat"]], meta[s["lon"]])]
    meta = meta[keep].set_index(s["id"])
    missing = set(float(x) for x in src.get("missing_codes", []))
    unmeas = set(float(x) for x in src.get("unmeasurable_codes", []))  # kept, no value, flagged
    suspect = {k: set(float(x) for x in v) for k, v in src.get("suspect_values", {}).items()}
    scale = src.get("scale", {})

    series, obs, used = [], [], set()
    for t in src["tables"]:
        df = pd.read_csv(root / t["file"], dtype={t["id"]: str})
        df = df[df[t["id"]].isin(meta.index)]
        df["date"] = _dates(df, t["date"])
        df = df[df["date"].notna()]
        for col, var in t["values"].items():
            v = pd.to_numeric(df[col], errors="coerce")
            is_missing = v.isin(missing)
            is_unmeas = v.isin(unmeas)
            flag = pd.Series("", index=df.index)
            flag[is_unmeas] = "unmeasurable"
            flag[v.isin(suspect.get(col, set()))] = "code_suspect"
            d = df.assign(_v=v.mask(is_missing | is_unmeas), _m=is_missing, _f=flag, _keep=v.notna() & ~is_missing)
            for sid, g in d.groupby(t["id"]):
                ok = g["_keep"]
                if not ok.any():
                    continue
                key = f"{src['name']}:{sid}"
                series_id = f"{key}:{var}"
                used.add(sid)
                series.append(dict(series_id=series_id, station_key=key, source=src["name"], variable=var,
                                   units=src.get("units", {}).get(col, ""), day_convention=src.get("day_convention", ""),
                                   n_values=int(ok.sum()), n_missing_code=int(g["_m"].sum()), n_unparsed=0,
                                   first=g.loc[ok, "date"].min(), last=g.loc[ok, "date"].max(),
                                   note=f"{t['file']} column {col}"))
                obs.append(pd.DataFrame({"series_id": series_id, "date": g.loc[ok, "date"].values,
                                         "value": g.loc[ok, "_v"].to_numpy(float) * float(scale.get(col, 1.0)),
                                         "flag": g.loc[ok, "_f"].values}))
    m = meta.loc[sorted(used)]
    stations = pd.DataFrame(dict(
        station_key=[f"{src['name']}:{i}" for i in m.index], source=src["name"], network=src.get("network", ""),
        source_station_id=m.index, name=m[s["name"]].astype(str).str.strip().values,
        lat=m[s["lat"]].astype(float).values, lon=m[s["lon"]].astype(float).values,
        elev_m=pd.to_numeric(m[s["elev"]], errors="coerce").values if s.get("elev") else np.nan,
        country=src.get("country", ""), wmo_id=m[s["wmo"]].astype(str).values if s.get("wmo") else ""))
    print(f"  read {root}: {len(stations)} stations, {len(series)} series")
    return (stations, pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
