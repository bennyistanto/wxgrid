"""Reader for BMKG Data Online daily workbooks (one .xlsx per station).

Layout, as delivered: a metadata block in the first rows (label in column B, value
after a colon in column C: ID WMO, Nama Stasiun, Lintang, Bujur, Elevasi), a header row
whose first cell is "Tanggal", daily rows with dates as DD-MM-YYYY, then legend rows at
the bottom. Codes follow the workbook legend ("Keterangan"): 9999 = "Tidak Ada Data"
(no measurement) is dropped and counted as missing; 8888 = "data tidak terukur" (not
measurable) is kept as a row with value `unmeasurable_value` (default empty) and flag
`unmeasurable`, so the day counts as observed by this station (findings F4, corrected).
"""

from pathlib import Path
import re

import numpy as np
import pandas as pd

from ..config import in_bbox
from ..schema import COMPASS

META_KEYS = {"ID WMO": "wmo_id", "Nama Stasiun": "name", "Lintang": "lat", "Bujur": "lon", "Elevasi": "elev_m"}


def _after_colon(x):
    m = re.search(r":\s*(.*)", str(x))
    return (m.group(1) if m else str(x)).strip()


def _parse_meta(raw):
    meta = {}
    for i in range(min(8, len(raw))):
        label = str(raw.iloc[i, 1]).strip()
        if label in META_KEYS:
            meta[META_KEYS[label]] = _after_colon(raw.iloc[i, 2])
    meta["wmo_id"] = "".join(re.findall(r"\d+", meta.get("wmo_id", "")))
    for k in ("lat", "lon", "elev_m"):
        try:
            meta[k] = float(meta[k])
        except (KeyError, ValueError):
            meta[k] = np.nan
    return meta


def _direction_to_degrees(col):
    """Compass text to degrees. 'C' (calm) and unknown codes become NaN."""
    text = col.astype(str).str.strip().str.upper()
    deg = text.map(COMPASS)
    calm = text.eq("C")
    unparsed = deg.isna() & ~calm & col.notna()
    return deg, calm, unparsed


def read_file(path):
    raw = pd.read_excel(path, header=None)
    meta = _parse_meta(raw)
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Tanggal"][0]
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    # Strict date parse: legend rows at the bottom become NaT and are dropped.
    df["date"] = pd.to_datetime(df["Tanggal"].astype(str).str.strip(), format="%d-%m-%Y", errors="coerce")
    df = df[df["date"].notna()]
    return meta, df


def read(src, bbox):
    missing = set(float(x) for x in src.get("missing_codes", []))
    varmap = src["variables"]
    stations, series, obs = [], [], []
    files = sorted(Path(src["path"]).glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"no .xlsx files under {src['path']}")
    for f in files:
        meta, df = read_file(f)
        if not in_bbox(meta["lat"], meta["lon"], bbox):
            continue
        sid = meta["wmo_id"] or f.stem
        key = f"{src['name']}:{sid}"
        stations.append(dict(station_key=key, source=src["name"], network=src.get("network", ""),
                             source_station_id=sid, name=meta.get("name", f.stem), lat=meta["lat"],
                             lon=meta["lon"], elev_m=meta["elev_m"], country=src.get("country", ""),
                             wmo_id=meta["wmo_id"], file=f.name))
        for col, var in varmap.items():
            if col not in df.columns:
                continue
            raw = df[col]
            flag = pd.Series("", index=df.index)
            if src.get("direction_text", {}).get(col):
                val, calm, unparsed = _direction_to_degrees(raw)
                flag[calm] = "calm"
                n_missing = 0
                keep = val.notna() | calm
            else:
                val = pd.to_numeric(raw, errors="coerce")
                unparsed = val.isna() & raw.notna() & raw.astype(str).str.strip().ne("")
                codes = missing | set(float(x) for x in src.get("missing_codes_by_column", {}).get(col, []))
                unmeas = set(float(x) for x in src.get("unmeasurable_codes", []))
                is_missing = val.isin(codes)
                is_unmeas = val.isin(unmeas) & ~is_missing
                n_missing = int(is_missing.sum())
                flag[is_unmeas] = "unmeasurable"
                keep = val.notna() & ~is_missing
                fill = src.get("unmeasurable_value")
                val = val.mask(is_missing).mask(is_unmeas, np.nan if fill is None else float(fill))
            series_id = f"{key}:{var}"
            sel = df.loc[keep, "date"]
            series.append(dict(series_id=series_id, station_key=key, source=src["name"], variable=var,
                               units=src.get("units", {}).get(col, ""), day_convention=src.get("day_convention", ""),
                               n_values=int(keep.sum()), n_missing_code=n_missing, n_unparsed=int(unparsed.sum()),
                               first=sel.min(), last=sel.max(), note=f"column {col}"))
            if keep.any():
                obs.append(pd.DataFrame({"series_id": series_id, "date": sel.values,
                                         "value": val[keep].astype(float).values, "flag": flag[keep].values}))
        print(f"  read {f.name}: {sid}")
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
