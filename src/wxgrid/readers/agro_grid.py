"""Reader for the agricultural-station climate sheets (`Data Stasiun/...`): one sheet per
station-year, a header block (Tahun, Hari, Kabupaten, No./Sta., Nama, Lintang, Bujur,
Elevasi) and daily multi-variable columns (CH, RHrata, Tmax, Tmin, Trata, SS, V, ...).

The files vary, so the reader locates things by content, not fixed offsets:

- Coordinate columns are found from the degree markers (the two cells reading `deg`), with
  the sign from the hemisphere letter in the data row (S/U for Lintang, E/T vs W/B for
  Bujur). Minutes >= 60 are treated as unreadable and dropped (the degree still places the
  station), flagged.
- Dates come in two encodings: month name in the "Hari" column with day-of-month below
  (variant A), or "Hari" as day-of-year 1..366 with the year as a date serial in "Tahun"
  (variant B). Both are handled.
- Variable columns are matched by the label row (CH->RR, RHrata->HU, Tmax->TX, Tmin->TN,
  Trata->TG, SS->SS, V->FG).

Monthly FLORES sheets and the non-standard files (no "Lintang" header) are skipped.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox
from .jatim_grid import MONTHS

VAR_MAP = {"CH": "RR", "RHRATA": "HU", "TMAX": "TX", "TMIN": "TN", "TRATA": "TG", "SS": "SS", "V": "FG",
           "E": "EV", "RAD": "RA", "RH07.00": "HU07", "RH13.00": "HU13", "RH07": "HU07", "RH13": "HU13"}
from ..schema import VALUE_BOUNDS as BOUNDS  # noqa: E402
SOUTH, WEST = {"S", "U"}, {"W", "B"}   # U = Utara? no: Lintang "U/S" = Utara/Selatan; here S = south


def _hemi_cols(sh, hrow):
    """Degree/min/hemisphere columns for lat and lon, from the unit rows under the header."""
    degs = []
    for c in range(sh.ncols):
        for r in (hrow + 1, hrow + 2, hrow):
            if r < sh.nrows and str(sh.cell_value(r, c)).strip() in ("°", "o", "O"):
                degs.append(c)
                break
    return degs[:2]


def _coord(sh, row, degc, sign_south_or_west):
    deg = sh.cell_value(row, degc)
    if not isinstance(deg, (int, float)):
        return np.nan, False
    mn = sh.cell_value(row, degc + 1) if degc + 1 < sh.ncols else 0
    approx = not (isinstance(mn, (int, float)) and 0 <= mn < 60)
    val = float(deg) + (0.0 if approx else float(mn) / 60.0)
    # hemisphere letter sits a column or two to the right of the degree
    hemi = ""
    for c in range(degc + 1, min(degc + 4, sh.ncols)):
        s = str(sh.cell_value(row, c)).strip().upper()
        if s in ("S", "U", "N", "E", "W", "T", "B"):
            hemi = s
            break
    neg = hemi in sign_south_or_west
    return (-val if neg else val), approx


def read(src, bbox):
    vmap = {k.upper(): v for k, v in src.get("var_map", VAR_MAP).items()}
    files = [f for f in sorted(Path(src["path"]).glob(src.get("glob", "**/*.XLS")))
             if f.suffix.lower() == ".xls" and "METKLIM" not in f.name.upper()]
    ns = src.get("station_namespace", src["name"])
    stns, recs = {}, {}
    for f in files:
        try:
            wb = xlrd.open_workbook(str(f))
        except Exception:
            continue
        for sh in wb.sheets():
            hrow = next((r for r in range(min(4, sh.nrows))
                         if "LINTANG" in [str(sh.cell_value(r, c)).strip().upper() for c in range(sh.ncols)]), None)
            if hrow is None:
                continue
            hdr = [str(sh.cell_value(hrow, c)).strip().upper() for c in range(sh.ncols)]
            try:
                i_year, i_hari = hdr.index("TAHUN"), hdr.index("HARI")
            except ValueError:
                continue
            i_name = hdr.index("NAMA") if "NAMA" in hdr else 5
            degs = _hemi_cols(sh, hrow)
            if len(degs) < 2:
                continue
            # variable columns: match only the row that holds "CH" (the variable-name row),
            # so the evaporation header "E" is not confused with the Bujur hemisphere "E"
            # that sits in the units row.
            var_rows = [r for r in (hrow, hrow + 1, hrow + 2)
                        if r < sh.nrows and "CH" in [str(sh.cell_value(r, c)).strip().upper() for c in range(sh.ncols)]]
            vcols = {}
            for r in var_rows or [hrow + 1]:
                for c in range(sh.ncols):
                    lab = str(sh.cell_value(r, c)).strip().upper()
                    if lab in vmap and c not in vcols:
                        vcols[c] = vmap[lab]
            if not vcols:
                continue
            # first data row = first row whose latitude-degree cell is a number (skips the
            # "Stasiun" sub-header rows); the station name and coordinates sit on it
            first = next((r for r in range(hrow + 1, sh.nrows)
                          if isinstance(sh.cell_value(r, degs[0]), (int, float))
                          and str(sh.cell_value(r, degs[0])).strip() != ""), None)
            if first is None:
                continue
            name = re.sub(r"\s+", " ", str(sh.cell_value(first, i_name)).strip())
            key = re.sub(r"[^A-Z0-9]", "", name.upper())
            if not key:
                continue
            if key not in stns:
                lat, la_ap = _coord(sh, first, degs[0], SOUTH)
                lon, lo_ap = _coord(sh, first, degs[1], WEST)
                stns[key] = dict(name=name, lat=lat, lon=lon, approx=la_ap or lo_ap, elev=np.nan)
                recs[key] = []
            # year: int, or an Excel date serial
            ycell = sh.cell_value(first, i_year)
            base_year = None
            if isinstance(ycell, (int, float)):
                base_year = int(ycell) if ycell <= 2100 else xlrd.xldate_as_datetime(ycell, wb.datemode).year
            # day-of-year (variant B) vs month-name (variant A)
            hari = [sh.cell_value(r, i_hari) for r in range(first, sh.nrows)]
            has_month = any(isinstance(h, str) and h.strip().upper()[:3] in MONTHS for h in hari)
            doy = max((h for h in hari if isinstance(h, (int, float))), default=0) > 31
            month, year, prev_day = 1, base_year, 0
            for r in range(first, sh.nrows):
                yv = sh.cell_value(r, i_year)
                if isinstance(yv, (int, float)) and yv > 0:
                    year = int(yv) if yv <= 2100 else xlrd.xldate_as_datetime(yv, wb.datemode).year
                if year is None or not (1900 <= year <= 2030):
                    continue
                h = sh.cell_value(r, i_hari)
                if has_month:
                    if isinstance(h, str) and h.strip().upper()[:3] in MONTHS:
                        month, day = MONTHS[h.strip().upper()[:3]], 1
                    elif isinstance(h, (int, float)) and 1 <= h <= 31:
                        day = int(h)
                    else:
                        continue
                    date = pd.Timestamp(year=year, month=month, day=day) if _valid(year, month, day) else None
                elif doy:
                    if not isinstance(h, (int, float)) or not (1 <= h <= 366):
                        continue
                    date = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=int(h) - 1)
                    if date.year != year:
                        continue
                else:
                    # sequential day-of-month with no month label: the month advances each
                    # time the day resets (handles e.g. SUKARAMI's "1-ian" first cell)
                    m = re.match(r"\s*(\d{1,2})", str(h))
                    if not m:
                        continue
                    day = int(m.group(1))
                    if not 1 <= day <= 31:
                        continue
                    if day <= prev_day:
                        month += 1
                    prev_day = day
                    if month > 12:
                        continue
                    date = pd.Timestamp(year=year, month=month, day=day) if _valid(year, month, day) else None
                if date is None:
                    continue
                for c, vc in vcols.items():
                    v = sh.cell_value(r, c)
                    if isinstance(v, str):
                        v = v.strip().replace(",", ".")
                        try:
                            v = float(v)
                        except ValueError:
                            continue
                    lo, hi = BOUNDS.get(vc, (-1e9, 1e9))
                    if isinstance(v, (int, float)) and lo <= v <= hi:
                        recs[key].append((date, vc, float(v)))

    stations, series, obs = [], [], []
    for key, meta in stns.items():
        if not recs[key] or pd.isna(meta["lat"]) or not in_bbox(meta["lat"], meta["lon"], bbox):
            continue
        skey = f"{ns}:{key}"
        df = pd.DataFrame(recs[key], columns=["date", "var", "value"])
        stations.append(dict(station_key=skey, source=ns, network=src.get("network", ""),
                             source_station_id=key, name=meta["name"], lat=round(meta["lat"], 4),
                             lon=round(meta["lon"], 4), elev_m=meta["elev"], country=src.get("country", "ID"),
                             wmo_id="", coord_approx=meta["approx"]))
        for vc, g in df.groupby("var"):
            g = g.drop_duplicates("date").sort_values("date")
            sidv = f"{src['name']}:{key}:{vc}"
            series.append(dict(series_id=sidv, station_key=skey, source=src["name"], variable=vc,
                               units="", day_convention=src.get("day_convention", ""),
                               n_values=len(g), n_missing_code=0, n_unparsed=0,
                               first=g["date"].min(), last=g["date"].max(), note=f"{meta['name']}"))
            obs.append(pd.DataFrame({"series_id": sidv, "date": g["date"].values, "value": g["value"].values,
                                     "flag": "coord_approx" if meta["approx"] and vc == "RR" else ""}))
    st = pd.DataFrame(stations)
    if "coord_approx" in st:
        st = st.drop(columns=["coord_approx"])
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series,"
          f" {sum(s['approx'] for s in stns.values() if s.get('approx'))} approx coords")
    return (st, pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))


def _valid(y, m, d):
    try:
        pd.Timestamp(year=y, month=m, day=d)
        return True
    except ValueError:
        return False
