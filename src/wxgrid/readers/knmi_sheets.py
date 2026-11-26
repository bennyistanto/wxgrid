"""KNMI Dutch-era daily rainfall sheets (F28, F71, F74): `F:/temp/station/knmi/`.

Two layouts, set per workbook in the config (`books`):
  station_month_rows  header row with `Stasiun`, `Tahun`, `Bulan`, then day columns 1..31; the station name and
                      the year are written only on the first row of their block (`CH  sumatra.xls`,
                      `CH 1898-1907.xls`, `CH Jawa.xls`)
  year_blocks         one sheet per year (year in A1); station blocks start on a row with `Januari` in column 7;
                      day rows hold the day in column 6, Jan-Jul in columns 7-13, the day again in 14, Aug-Dec
                      in 15-19 (`Sumatera 1880-1897.xls`)
Cell coding (measured, F74):
  number = mm; "-" = dry (0.0); "n.w." / "Geen waarnemingen ..." = missing (counted).
  blank: `blank: missing` books (`CH Jawa.xls`, which writes "-" for dry days) -> missing;
         `blank: dry_if_month_reported` books (the others, which never write "-") -> 0.0 mm when the station-month
         has at least one number, missing when the whole month is blank. Evidence: on KNMI Jakarta's blank days in
         reported months, SACA&D 180 Kemayoran has 0 mm on 84% and < 1 mm on 94% (F74).
Stations come from `stations_csv` (`tools/build_knmi_stations.py`): sheet name -> key, position, elevation; several
sheet names may share a key (e.g. `Medan I` and `Medan`). Names in `skip` (Jakarta: same record as SACA&D 180, F71)
and names absent from the table are not read; both are counted. Keys in `coord_approx` (e.g. MEDAN_II, whose
position is Medan's, F78) get the flag `coord_approx` on every value. No reference exists before 1979, so the day label
stays unverified; the KNMI day convention is not known [to verify].
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox

MONTHS = {m: i + 1 for i, m in enumerate(["januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
                                          "september", "oktober", "november", "desember"])}
MISSING_TEXT = ("n.w", "geen waarnemingen")


def cell(v):
    """-> (value, code): mm for 'num'; 0.0 for 'dash'; None for 'blank', 'missing', 'other'."""
    if isinstance(v, (int, float)) and v != "":
        return float(v), "num"
    s = str(v).strip().lower().replace("`", "")
    if s == "":
        return None, "blank"
    if s.startswith(MISSING_TEXT):
        return None, "missing"
    if s.strip("-") == "":
        return 0.0, "dash"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\D?", s)
    if m:
        return float(m.group(1)), "num"
    return None, "other"


def _month(v):
    s = str(v).strip().lower()
    return MONTHS.get(s) or next((n for k, n in MONTHS.items() if s and k.startswith(s[:3]) and len(s) >= 3), None)


def station_month_rows(book, sheets=None):
    """Yield (station, year, month, day, raw cell) from the station-month-row layout."""
    for sh in book.sheets():
        if sheets and sh.name.strip() not in {s.strip() for s in sheets}:
            continue
        hdr = next((r for r in range(min(6, sh.nrows)) if str(sh.cell_value(r, 1)).strip().lower() == "stasiun"), None)
        if hdr is None or sh.ncols < 38:
            continue
        name = year = None
        for r in range(hdr + 1, sh.nrows):
            if str(sh.cell_value(r, 1)).strip():
                name = str(sh.cell_value(r, 1)).strip()
            y = sh.cell_value(r, 5)
            if isinstance(y, float) and 1800 < y < 2000:
                year = int(y)
            mo = _month(sh.cell_value(r, 6))
            if not (name and year and mo):
                continue
            for d in range(1, 32):
                yield name, year, mo, d, sh.cell_value(r, 6 + d)


def year_blocks(book, sheets=None):
    """Yield (station, year, month, day, raw cell) from the per-year block layout."""
    for sh in book.sheets():
        try:
            year = int(float(sh.cell_value(0, 0)))
        except (ValueError, IndexError):
            continue
        name = None
        for r in range(sh.nrows):
            if str(sh.cell_value(r, 6)).strip().lower() == "januari":
                name = str(sh.cell_value(r, 1)).strip()
                continue
            day = sh.cell_value(r, 5)
            if not (name and isinstance(day, float) and 1 <= day <= 31):
                continue
            for k, col in enumerate(list(range(6, 13)) + list(range(14, 19))):
                yield name, year, k + 1, int(day), sh.cell_value(r, col)


LAYOUTS = {"station_month_rows": station_month_rows, "year_blocks": year_blocks}


def read(src, bbox):
    root = Path(src["path"])
    table = pd.read_csv(src["stations_csv"]).set_index("sheet_name")
    skip = {s.strip() for s in src.get("skip", [])}
    approx = {str(k) for k in src.get("coord_approx", [])}
    recs, counts, unknown = [], Counter(), Counter()
    for b in src["books"]:
        book = xlrd.open_workbook(str(root / b["path"]))
        cells = pd.DataFrame(list(LAYOUTS[b["layout"]](book, b.get("sheets"))),
                             columns=["name", "year", "month", "day", "raw"])
        if cells.empty:
            continue
        cells[["value", "code"]] = pd.DataFrame([cell(v) for v in cells.raw], index=cells.index)
        reported = cells.groupby(["name", "year", "month"]).code.transform(lambda c: c.isin(["num", "dash"]).any())
        if b.get("blank") == "dry_if_month_reported":
            dry = (cells.code == "blank") & reported
            cells.loc[dry, ["value", "code"]] = [0.0, "blank_dry"]
        elif b.get("blank") != "missing":
            raise ValueError(f"{src['name']}: book {b['path']} needs blank: missing | dry_if_month_reported")
        for k, n in cells.code.value_counts().items():
            counts[(b["path"], k)] += int(n)
        keep = cells[cells.value.notna()].copy()
        keep["date"] = pd.to_datetime(dict(year=keep.year, month=keep.month, day=keep.day), errors="coerce")
        counts[(b["path"], "invalid_date")] += int(keep.date.isna().sum())
        keep = keep[keep.date.notna()]
        for nm, g in keep.groupby("name"):
            if nm in skip:
                counts[(b["path"], f"skipped:{nm}")] += len(g)
                continue
            if nm not in table.index:
                unknown[nm] += int((g.value > 0).sum())
                continue
            recs.append(g.assign(key=table.at[nm, "key"], book=b["path"])[["key", "date", "value", "code", "book"]])
    if not recs:
        raise ValueError(f"{src['name']}: no values read")
    df = pd.concat(recs, ignore_index=True)
    meta = table.reset_index().drop_duplicates("key").set_index("key")
    stations, series, obs = [], [], []
    for key, g in df.groupby("key"):
        m = meta.loc[key]
        if not in_bbox(m.lat, m.lon, bbox):
            continue
        skey = f"{src['name']}:{key}"
        sid = f"{skey}:RR"
        g = g.sort_values("date")
        stations.append(dict(station_key=skey, source=src["name"], network=src.get("network", ""), source_station_id=key,
                             name=str(m.place), lat=float(m.lat), lon=float(m.lon),
                             elev_m=float(m.elev_m) if pd.notna(m.elev_m) else np.nan, country=src.get("country", "ID"), wmo_id=""))
        series.append(dict(series_id=sid, station_key=skey, source=src["name"], variable="RR", units="mm",
                           day_convention=src.get("day_convention", ""), n_values=len(g), n_missing_code=0, n_unparsed=0,
                           first=g.date.min(), last=g.date.max(),
                           note=f"{m.place}; position from {m.how}; books {', '.join(sorted(g.book.unique()))}; "
                                f"blank read as dry {int((g.code == 'blank_dry').sum())}"))
        obs.append(pd.DataFrame({"series_id": sid, "date": g.date.values, "value": g.value.values,
                                 "flag": "coord_approx" if key in approx else ""}))
    print(f"  read {root}: {len(stations)} stations; cells {dict(sorted(counts.items()))}; names not in the station table "
          f"(rain days): {dict(unknown)}")
    return pd.DataFrame(stations), pd.DataFrame(series), pd.concat(obs, ignore_index=True)
