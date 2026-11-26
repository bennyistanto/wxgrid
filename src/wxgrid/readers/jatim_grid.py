"""Reader for the Dinas PU "one sheet per year, day rows x month columns" rainfall sheets
(`DATA CH JATIM/...`). Each sheet carries a header block (label in col A, value in col C):
NAMA STASIUN, Kode stasiun, Lintang Selatan, Bujur Timur, Elevasi, plus a grid headed by a
month row (JAN PEB MAR ... DES) with day numbers 1..31 down column A.

Coordinates are written as `DD.MM,mmm` (degrees . minutes , decimal-of-minute), e.g.
`07.26,591` = 7 deg 26.591 min, as text. Some sheets write decimal degrees instead: numeric
cells in the Pamekasan sheets (-7.1602 / 113.5764) and comma-free text at Botokan and
Ketintang (`07.49` / `112.68`, where 68 cannot be minutes); these are read as decimal degrees
(F65). Lintang Selatan is south (negative), Bujur Timur east (positive). Template
placeholders (0, 23) fail the range check; a post takes the first valid position across its
sheets. Config `coordinates_override` (station key -> lat, lon, note) replaces a position. Blank or "-" is missing; 0 is a dry day (rain < 0.5 mm, per the sheet notes).

One station per (name, code); sheets are years. Config example:

    - name: jatim
      reader: jatim_grid
      path: F:/temp/station/additional-sources/DATA CH JATIM
      glob: '**/*.xls'
      variable: RR
      units: mm
      station_namespace: jatim
      drop_all_zero_sheets: true   # a year sheet whose every value is 0 is an unfilled template

`drop_all_zero_sheets`: some posts carry whole year sheets of 0.0 (107 sheets, all complete
years, while the same posts total 1,100-1,900 mm in other years and CPC-UNI 1,200-1,750 mm;
F64). Such a sheet is dropped and counted in the series note and `n_missing_code`.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox

MONTHS = {"JAN": 1, "PEB": 2, "FEB": 2, "MAR": 3, "APR": 4, "MEI": 5, "MAY": 5, "JUN": 6,
          "JUL": 7, "AGS": 8, "AGT": 8, "SEP": 9, "OKT": 10, "OCT": 10,
          "NOP": 11, "NOV": 11, "DES": 12, "DEC": 12}
LABELS = {"NAMA STASIUN": "name", "KODE STASIUN": "code", "LINTANG SELATAN": "lat",
          "BUJUR TIMUR": "lon", "ELEVASI": "elev"}


def _dm(s, sign):
    """`DD.MM,mmm` (or with any separators) -> signed decimal degrees."""
    nums = re.findall(r"\d+", str(s))
    if len(nums) < 2:
        return np.nan
    deg = float(nums[0])
    minutes = float(nums[1] + ("." + nums[2] if len(nums) > 2 else ""))
    return sign * (deg + minutes / 60.0)


def _coord(v, sign, lo, hi):
    """Text with a comma = `DD.MM,mmm`; a number or comma-free text = decimal degrees.
    Returns (signed value, how) or (nan, "") when outside [lo, hi] in absolute value."""
    if isinstance(v, str) and "," in v:
        x, how = abs(_dm(v, 1)), "sheet DD.MM,mmm"
    else:
        try:
            x, how = abs(float(str(v).strip())), "sheet decimal degrees"
        except ValueError:
            return np.nan, ""
    return (sign * x, how) if lo <= x <= hi else (np.nan, "")


def _header_block(sh):
    out = {}
    for r in range(min(16, sh.nrows)):
        lab = str(sh.cell_value(r, 0)).strip().upper().rstrip(":").strip()
        key = LABELS.get(lab)
        if not key:
            continue
        val = next((sh.cell_value(r, c) for c in (2, 3, 1) if str(sh.cell_value(r, c)).strip() != ""), "")
        out[key] = val
    return out


def _sheet_year(sh):
    """Year from the sheet name (4-digit, or 2-digit: 50-99->19xx, 00-49->20xx), else from a
    'Tahun' cell in the header area."""
    m = re.search(r"(19|20)\d\d", sh.name)
    if m:
        return int(m.group(0))
    m = re.fullmatch(r"\D*(\d{2})\D*", sh.name)
    if m:
        y = int(m.group(1))
        return 1900 + y if y >= 50 else 2000 + y
    for r in range(min(10, sh.nrows)):
        for c in range(min(8, sh.ncols)):
            if str(sh.cell_value(r, c)).strip().upper().startswith("TAHUN"):
                for cc in range(c + 1, min(c + 3, sh.ncols)):
                    v = sh.cell_value(r, cc)
                    if isinstance(v, (int, float)) and 1900 <= v <= 2030:
                        return int(v)
    return None


def _month_row(sh):
    for r in range(min(25, sh.nrows)):
        hits = sum(1 for c in range(1, min(14, sh.ncols)) if str(sh.cell_value(r, c)).strip().upper()[:3] in MONTHS)
        if hits >= 6:
            return r
    return None


def read(src, bbox):
    var = src["variable"]
    ns = src.get("station_namespace", src["name"])
    files = sorted(Path(src["path"]).glob(src.get("glob", "**/*.xls")))
    stns = {}   # (name, code) -> meta
    recs = {}   # (name, code) -> list of (date, value)
    zero_sheets = {}   # key -> [sheets dropped, values dropped]
    for f in files:
        try:
            wb = xlrd.open_workbook(str(f))
        except Exception:
            continue
        for sh in wb.sheets():
            hb = _header_block(sh)
            if "name" not in hb:
                continue
            mr = _month_row(sh)
            if mr is None:
                continue
            name = re.sub(r"\s+", " ", str(hb["name"]).strip())
            code = re.sub(r"\s+", "", str(hb.get("code", "")).strip().replace(".0", ""))
            # unique, space-free station id: same post written two ways (e.g. "SIMO" / "S I M O",
            # same code) collapses to one key; different codes stay separate
            nm = re.sub(r"[^A-Z0-9]", "", name.upper())
            key = f"{code}_{nm}" if code else nm
            lat, how = _coord(hb.get("lat", ""), -1, 0.5, 12.0)   # Lintang Selatan: south
            lon, _ = _coord(hb.get("lon", ""), +1, 90.0, 145.0)   # Bujur Timur: east
            if np.isnan(lat) or np.isnan(lon):
                lat = lon = np.nan
            if key not in stns:
                elev = hb.get("elev", "")
                stns[key] = dict(name=name, code=code, lat=lat, lon=lon, how=how if not np.isnan(lat) else "",
                                 elev=float(elev) if isinstance(elev, (int, float)) else np.nan)
                recs[key] = []
                zero_sheets[key] = [0, 0]
            elif np.isnan(stns[key]["lat"]) and not np.isnan(lat):   # first valid position wins
                stns[key].update(lat=lat, lon=lon, how=how)
            mcol = {c: MONTHS[str(sh.cell_value(mr, c)).strip().upper()[:3]]
                    for c in range(1, min(14, sh.ncols)) if str(sh.cell_value(mr, c)).strip().upper()[:3] in MONTHS}
            yr = _sheet_year(sh)
            sheet_recs = []
            for r in range(mr + 1, sh.nrows):
                d = sh.cell_value(r, 0)
                if not isinstance(d, (int, float)) or not (1 <= int(d) <= 31):
                    continue
                day = int(d)
                ryr = yr
                if ryr is None:   # fall back to a Tahun cell if the sheet is not named by year
                    continue
                for c, mo in mcol.items():
                    v = sh.cell_value(r, c)
                    if isinstance(v, str):
                        v = v.strip().replace(",", ".")
                        if v in ("", "-"):
                            continue
                        try:
                            v = float(v)
                        except ValueError:
                            continue
                    if isinstance(v, (int, float)) and 0 <= v <= src.get("value_ceiling", 2000):
                        sheet_recs.append((ryr, mo, day, float(v)))
            if src.get("drop_all_zero_sheets") and sheet_recs and all(x[3] == 0 for x in sheet_recs):
                zero_sheets[key][0] += 1
                zero_sheets[key][1] += len(sheet_recs)
                continue
            recs[key].extend(sheet_recs)

    for key, ov in (src.get("coordinates_override") or {}).items():
        if key in stns:
            stns[key].update(lat=float(ov["lat"]), lon=float(ov["lon"]), how=f"override: {ov.get('note', '')}")
    stations, series, obs = [], [], []
    for key, meta in stns.items():
        if not recs[key] or pd.isna(meta["lat"]) or not in_bbox(meta["lat"], meta["lon"], bbox):
            continue
        skey = f"{ns}:{key}"
        series_id = f"{src['name']}:{key}:{var}"
        df = pd.DataFrame(recs[key], columns=["year", "month", "day", "value"])
        df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=df.day), errors="coerce")
        df = df[df["date"].notna()].drop_duplicates("date").sort_values("date")
        if df.empty:
            continue
        stations.append(dict(station_key=skey, source=ns, network=src.get("network", ""),
                             source_station_id=meta["code"] or key, name=meta["name"], lat=meta["lat"], lon=meta["lon"],
                             elev_m=meta["elev"], country=src.get("country", "ID"), wmo_id=""))
        series.append(dict(series_id=series_id, station_key=skey, source=src["name"], variable=var,
                           units=src.get("units", ""), day_convention=src.get("day_convention", ""),
                           n_values=len(df), n_missing_code=zero_sheets[key][1], n_unparsed=0,
                           first=df["date"].min(), last=df["date"].max(),
                           note=f"{meta['name']} ({meta['code']}); position {meta['how']}"
                           + (f"; all-zero sheets dropped {zero_sheets[key][0]}" if zero_sheets[key][0] else "")))
        obs.append(pd.DataFrame({"series_id": series_id, "date": df["date"].values, "value": df["value"].values, "flag": ""}))
    nz = sum(v[0] for v in zero_sheets.values())
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series; "
          f"all-zero sheets dropped {nz} ({sum(v[1] for v in zero_sheets.values())} values)")
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
