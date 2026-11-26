"""Reader for a single long-format .xls sheet: one row per station-day, a column per
variable, the station id in a column, and coordinates resolved from a catalogue CSV
(id -> lat, lon, elev, name). This fits the BMKG F-KLIM dumps such as
`CH_IND/Fklim_Sumatera.xls` (sheet `All`: Nosta, Station, Year, Month, Date, Tavg, Tx,
Tm, Rainfall, Duration, PPP, Rh..., wind), where `Nosta` is the WMO number.

Config example:

    - name: fklim_sumatera
      reader: long_table_xls
      path: .../CH_IND/Fklim_Sumatera.xls
      sheet: All
      header_row: 3
      id_col: Nosta
      year_col: Year
      month_col: Month
      day_col: Date
      value_map: {Rainfall: RR, Tx: TX, Tm: TN, Tavg: TG, Rhavg: HU}
      missing_codes: [9999, 99999999]
      missing_codes_by_station: {96163: [999]}  # station-specific missing codes, every column
      unmeasurable_text: {Rainfall: [TTU]}      # per column: text kept as a row, no value, flag unmeasurable
      catalogue_csv: .../_wmo_catalogue.csv     # id (= Nosta) -> lat, lon, elev, name

Other text in a value column is counted per series (`n_unparsed`), not dropped silently.
"""

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox

from ..schema import VALUE_BOUNDS as BOUNDS


def read(src, bbox):
    sh = xlrd.open_workbook(src["path"]).sheet_by_name(src.get("sheet")) if src.get("sheet") \
        else xlrd.open_workbook(src["path"]).sheet_by_index(0)
    hr = src.get("header_row", 0)
    hdr = [str(sh.cell_value(hr, c)).strip() for c in range(sh.ncols)]
    idx = {h: i for i, h in enumerate(hdr)}
    i_id, i_y, i_m, i_d = (idx[src[k]] for k in ("id_col", "year_col", "month_col", "day_col"))
    vcols = {idx[col]: var for col, var in src["value_map"].items() if col in idx}
    missing = set(float(x) for x in src.get("missing_codes", []))
    miss_stn = {int(k): {float(x) for x in v} for k, v in (src.get("missing_codes_by_station") or {}).items()}
    n_miss = {}   # (wmo, varcode) -> count of missing-code cells
    unmeas_text = {idx[col]: {str(t).upper() for t in ts}
                   for col, ts in (src.get("unmeasurable_text") or {}).items() if col in idx}
    cat = pd.read_csv(src["catalogue_csv"]).set_index("wmo")
    ns = src.get("station_namespace", src["name"])

    recs = []   # (wmo, year, month, day, varcode, value, flag)
    unparsed = {}   # (wmo, varcode) -> count of text cells that are neither a value nor a listed code
    for r in range(hr + 1, sh.nrows):
        sid = sh.cell_value(r, i_id)
        if not isinstance(sid, (int, float)) or sid == "":
            continue
        wmo = int(sid)
        if wmo not in cat.index:
            continue
        try:
            y, m, d = int(sh.cell_value(r, i_y)), int(sh.cell_value(r, i_m)), int(sh.cell_value(r, i_d))
        except (TypeError, ValueError):
            continue
        for c, vc in vcols.items():
            v = sh.cell_value(r, c)
            if isinstance(v, str):
                t = v.strip()
                if not t:
                    continue
                if t.upper().rstrip(".") in unmeas_text.get(c, ()):   # e.g. TTU in F-KLIM rainfall (F63)
                    recs.append((wmo, y, m, d, vc, np.nan, "unmeasurable"))
                    continue
                try:
                    v = float(t.replace(",", "."))
                except ValueError:
                    unparsed[(wmo, vc)] = unparsed.get((wmo, vc), 0) + 1
                    continue
            if not isinstance(v, (int, float)):
                continue
            if v in missing or v in miss_stn.get(wmo, ()):
                n_miss[(wmo, vc)] = n_miss.get((wmo, vc), 0) + 1
                continue
            lo, hi = BOUNDS.get(vc, (-1e9, 1e9))
            if lo <= v <= hi:
                recs.append((wmo, y, m, d, vc, float(v), ""))
    if not recs:
        raise ValueError(f"{src['name']}: no values read")
    df = pd.DataFrame(recs, columns=["wmo", "year", "month", "day", "var", "value", "flag"])
    df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=df.day), errors="coerce")
    df = df[df["date"].notna()]

    stations, series, obs = [], [], []
    for wmo, g in df.groupby("wmo"):
        c = cat.loc[wmo]
        if not in_bbox(float(c["lat"]), float(c["lon"]), bbox):
            continue
        key = f"{ns}:{wmo}"
        stations.append(dict(station_key=key, source=ns, network=src.get("network", ""),
                             source_station_id=str(wmo), name=str(c["name"]), lat=float(c["lat"]),
                             lon=float(c["lon"]), elev_m=float(c["elev"]) if pd.notna(c["elev"]) else np.nan,
                             country=src.get("country", "ID"), wmo_id=str(wmo)))
        for vc, gv in g.groupby("var"):
            # a measured value wins over an unmeasurable flag on the same date
            gv = gv.sort_values(["date", "flag"]).drop_duplicates("date").sort_values("date")
            n_un = int((gv["flag"] == "unmeasurable").sum())
            sidv = f"{src['name']}:{wmo}:{vc}"
            series.append(dict(series_id=sidv, station_key=key, source=src["name"], variable=vc,
                               units="", day_convention=src.get("day_convention", ""),
                               n_values=len(gv), n_missing_code=n_miss.get((wmo, vc), 0), n_unparsed=unparsed.get((wmo, vc), 0),
                               first=gv["date"].min(), last=gv["date"].max(),
                               note=f"WMO {wmo}" + (f"; unmeasurable {n_un}" if n_un else "")))
            obs.append(pd.DataFrame({"series_id": sidv, "date": gv["date"].values,
                                     "value": gv["value"].values, "flag": gv["flag"].values}))
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series")
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
