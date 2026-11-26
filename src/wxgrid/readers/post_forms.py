"""Reader for rain-post forms found in the 2026-11-24 recheck (findings F56-F58).

One module, five layouts, one cell coding. Each config `sources:` entry lists its workbooks
(`books`) with the layout and the post key; station coordinates come from a catalogue CSV
(`tools/build_post_catalogue.py`), never from per-sheet text, because template coordinates
are often copied between forms (F55, Larantuka 1988+).

Layouts
- `day_month`: day rows 1..31 x month columns (JAN..DES) under a "TAHUN : yyyy" block (or a
  year-named sheet); several year blocks per sheet allowed (BMG/Data Lelogama, Oesao, Patas,
  Poh Santen, Praya; Batubassi 1976-1993). JUMLAH / TOTAL / RATA2 / HH rows are ignored.
- `year_month_rows`: TAHUN | BULAN | 1..31 per row; the year is written on the first row of
  each year only; months as numbers or names (Batubassi 1994-2003).
- `post_rows`: one sheet per year; month blocks titled "JAN | yyyy"; rows No | post | 1..31 |
  dekad and month totals | HARI HJN (Sumsel unlocked workbooks).
- `station_month_rows`: Nosta | Sta | Year | Month | R1..R31 (West Sumatra 1991-2000).
- `agro_sheets`: the agro-climate form parsed by `agro_sheets.parse_sheet` (all variables)
  for a single-station workbook (Larantuka 1985-1996).

Cell coding (config `codes`, measured in F57)
- `dash_value` (e.g. 0.0): a "-" cell is a dry day. Omit it to treat "-" as missing.
- `zero_is_trace`: a 0 cell is an observed rain day too small to measure: no value, flag
  `unmeasurable` (as BMKG 8888).
- `missing_text` (X, R, ...), `missing_codes` (999), `unmeasurable_codes` (888); blank = missing.
- `unmeasurable_text` (TTU, TU): text for an observed rain day too small to measure, flag `unmeasurable`.
- A month whose every valid day is "-": `dash_month: flag` (default) keeps 0.0 with flag
  `dash_month`, for /qc to decide with CPC and neighbours (BMG/Data: CPC median 4 mm in such
  months, 21 of 314 above 100 mm); `dash_month: missing` drops them as unreported (Sumsel: CPC
  median 163 mm, 74% above 100 mm). Measured in F57 and F59.
Counts of every cell class are reported per series (`n_missing_code`, `n_unparsed`, note).
"""
from __future__ import annotations

import glob
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox
from ..schema import OBS_COLS, SERIES_COLS, STATION_COLS, VALUE_BOUNDS
from . import agro_sheets

MONTHS = {"JAN": 1, "PEB": 2, "FEB": 2, "MAR": 3, "MRT": 3, "APR": 4, "MEI": 5, "MAY": 5, "JUN": 6,
          "JUL": 7, "AGS": 8, "AGT": 8, "AGU": 8, "AUG": 8, "SEP": 9, "OKT": 10, "OCT": 10,
          "NOP": 11, "NOV": 11, "DES": 12, "DEC": 12}
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
DASHES = {"-", "--", "_", "–"}
NO_READING = {"blank", "missing_text", "missing_code", "dash_missing"}   # cells that carry no reading
WMO_RE = re.compile(r"9[67]\d{3}")   # a BMKG WMO index written as the post number (e.g. 96167)
YEAR_TXT = re.compile(r"TAHUN\s*:?\s*((?:19|20)\d\d)", re.I)


FULL_MONTHS = {"JANUARI", "JANUARY", "FEBRUARI", "PEBRUARI", "FEBRUARY", "MARET", "MARCH", "APRIL",
               "JUNI", "JUNE", "JULI", "JULY", "AGUST", "AGUSTUS", "AUGUST", "SEPT", "SEPTEMBER",
               "OKTOBER", "OCTOBER", "NOPEMBER", "NOVEMBER", "DESEMBER", "DECEMBER"}


def month_of(v):
    """Month number for a month label (JAN, Peb, Agust, Januari ...); None for anything else."""
    s = re.sub(r"[^A-Z]", "", str(v).upper())
    if s[:3] not in MONTHS:
        return None
    return MONTHS[s[:3]] if (len(s) <= 3 or s in FULL_MONTHS) else None


def text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def load_book(path: Path):
    """[(sheet name, rows)] with rows = list of lists of raw cell values (None for empty)."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        wb.close()
        return out
    wb = xlrd.open_workbook(str(path))
    out = []
    for sh in wb.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                row.append(None if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) else cell.value)
            rows.append(row)
        out.append((sh.name, rows))
    return out


class Coder:
    """Decode one day cell into (value, flag, kind). value None = no observation row."""

    def __init__(self, codes: dict, ceiling: float):
        self.dash = codes.get("dash_value")
        self.zero_trace = bool(codes.get("zero_is_trace", False))
        self.miss_txt = {s.upper() for s in codes.get("missing_text", [])}
        self.miss_codes = {float(x) for x in codes.get("missing_codes", [])}
        self.unmeas = {float(x) for x in codes.get("unmeasurable_codes", [])}
        self.unmeas_txt = {s.upper() for s in codes.get("unmeasurable_text", [])}
        self.ceiling = ceiling

    def __call__(self, v):
        if v is None:
            return None, "", "blank"
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                return None, "", "blank"
            if s in DASHES:
                return (float(self.dash), "", "dash") if self.dash is not None else (None, "", "dash_missing")
            if s.upper() in self.miss_txt:
                return None, "", "missing_text"
            if s.upper().rstrip(".") in self.unmeas_txt:
                return np.nan, "unmeasurable", "unmeasurable_text"
            if not NUM.fullmatch(s):
                return None, "", "unparsed"
            v = float(s.replace(",", "."))
        if not isinstance(v, (int, float)):
            return None, "", "unparsed"
        v = float(v)
        if v in self.miss_codes:
            return None, "", "missing_code"
        if v in self.unmeas:
            return np.nan, "unmeasurable", "unmeasurable_code"
        if v == 0 and self.zero_trace:
            return np.nan, "unmeasurable", "trace_zero"
        if 0 <= v <= self.ceiling:
            return v, "", "value"
        return None, "", "out_of_range"


# ---------------- layouts: each yields (post_key, year, month, day, raw cell) ----------------
def lay_day_month(sheets, book):
    for name, rows in sheets:
        year = int(name.strip()) if re.fullmatch(r"\s*(19|20)\d\d\s*", name) else None
        mcols = None
        for row in rows:
            t = [text(v) for v in row]
            m = YEAR_TXT.search(" ".join(t))
            if m:
                year = int(m.group(1))
            mc = {c: month_of(s) for c, s in enumerate(t) if month_of(s)}
            if len(set(mc.values())) >= 12:
                mcols = mc
                continue
            if mcols and year and t and re.fullmatch(r"\d{1,2}", t[0]) and 1 <= int(t[0]) <= 31:
                d = int(t[0])
                for c, mo in mcols.items():
                    yield book["post_key"], year, mo, d, row[c] if c < len(row) else None


def lay_year_month_rows(sheets, book):
    for name, rows in sheets:
        dcol, year = None, None
        for row in rows:
            t = [text(v) for v in row]
            days = {c: int(s) for c, s in enumerate(t) if re.fullmatch(r"\d{1,2}", s) and 1 <= int(s) <= 31}
            if dcol is None:
                if len(days) >= 28 and sorted(days.values())[:3] == [1, 2, 3]:
                    dcol = days
                continue
            if len(t) < 2:
                continue
            if re.fullmatch(r"(19|20)\d\d", t[0]):
                year = int(t[0])
            mo = int(t[1]) if re.fullmatch(r"\d{1,2}", t[1]) and 1 <= int(t[1]) <= 12 else month_of(t[1])
            if year and mo:
                for c, d in dcol.items():
                    yield book["post_key"], year, mo, d, row[c] if c < len(row) else None


def lay_post_rows(sheets, book):
    prefix = book.get("post_prefix", "")
    for name, rows in sheets:
        if not re.fullmatch(r"\s*(19|20)\d\d\s*", name):
            continue
        year, month, dcol = int(name), None, None
        for row in rows:
            t = [text(v) for v in row]
            mo = next((month_of(s) for s in t[:4] if month_of(s)), None)
            if mo and any(re.fullmatch(r"(19|20)\d\d", s) for s in t[:6]):
                month = mo
                continue
            if "HARI HJN" in t:
                hh = t.index("HARI HJN")
                dcol = {c: int(s) for c, s in enumerate(t) if c < hh and re.fullmatch(r"\d{1,2}", s)}
                continue
            if month and dcol and len(t) > 3 and re.fullmatch(r"\d{1,3}", t[1]) and t[2]:
                post = f"{prefix}{t[2]}"
                for c, d in dcol.items():
                    yield post, year, month, d, row[c] if c < len(row) else None


def lay_station_month_rows(sheets, book):
    for name, rows in sheets:
        hdr = None
        for row in rows:
            t = [text(v) for v in row]
            if hdr is None:
                u = [s.upper() for s in t]
                if "R1" in u:
                    hdr = {k: u.index(k) for k in ("NOSTA", "STA", "YEAR", "MONTH")}
                    r1 = u.index("R1")
                continue
            try:
                y, mo = int(float(t[hdr["YEAR"]])), int(float(t[hdr["MONTH"]]))
            except (ValueError, IndexError):
                continue  # repeated header rows, blank rows
            no = re.sub(r"\.0$", "", t[hdr["NOSTA"]])   # 43.0 -> 43; keeps 50.05 intact
            post = f"{no}|{t[hdr['STA']]}"
            for k in range(31):
                c = r1 + k
                yield post, y, mo, k + 1, row[c] if c < len(row) else None


LAYOUTS = {"day_month": lay_day_month, "year_month_rows": lay_year_month_rows, "post_rows": lay_post_rows,
           "station_month_rows": lay_station_month_rows}


def _books(src):
    for b in src["books"]:
        paths = [Path(b["path"])] if "path" in b else [Path(p) for p in sorted(glob.glob(b["glob"]))]
        for p in paths:
            yield p, b


def read(src, bbox):
    var = src.get("variable", "RR")
    ns = src.get("station_namespace", src["name"])
    cat = pd.read_csv(src["catalogue_csv"])
    cat = cat[cat.source == src.get("catalogue_source", src["name"])].set_index("post_key")
    coder = Coder(src.get("codes", {}), float(src.get("value_ceiling", VALUE_BOUNDS["RR"][1])))
    recs, kinds, agro = [], Counter(), []
    per_post_kinds: dict[str, Counter] = {}
    n_books = 0
    for path, book in _books(src):
        n_books += 1
        if book["layout"] == "agro_sheets":
            wb = xlrd.open_workbook(str(path))
            data = [sh for sh in wb.sheets() if sh.nrows >= 10]
            for sh in data:
                df, meta = agro_sheets.parse_sheet(sh, wb.datemode, agro_sheets.year_hint(path.name, sh.name, len(data)))
                if df is None or not len(df):
                    continue
                agro.append(df.assign(post=book["post_key"], sheet=sh.name))
            continue
        sheets = load_book(path)
        for post, y, mo, d, raw in LAYOUTS[book["layout"]](sheets, book):
            value, flag, kind = coder(raw)
            pk = per_post_kinds.setdefault(post, Counter())
            try:
                date = pd.Timestamp(y, mo, d)
            except ValueError:  # 30 Feb etc.: count what such cells held
                pk["impossible_date_" + ("empty" if kind in ("blank", "dash", "missing_text") else "value")] += 1
                continue
            pk[kind] += 1
            recs.append((post, date, value, flag, kind))
    stations, series, obs = [], [], []
    if recs:
        d = pd.DataFrame(recs, columns=["post", "date", "value", "flag", "kind"])
        d = d[d.value.notna() | (d.flag != "")]
        # whole month of "-" (on its valid days): keep 0.0, flag dash_month
        allc = pd.DataFrame(recs, columns=["post", "date", "value", "flag", "kind"])
        allc["ym"] = allc.date.dt.to_period("M")
        # judged on the days that hold a reading: blank / X / R / missing codes do not break a
        # month of "-" (review 2026-11-25: Patas 2002-10 had 23 "-" and 8 blank)
        obs_kinds = allc[~allc.kind.isin(NO_READING)]
        dm = obs_kinds.groupby(["post", "ym"]).kind.agg(lambda k: (k == "dash").all())
        dm = set(dm[dm].index)
        d["ym"] = d.date.dt.to_period("M")
        mask = pd.Series([(p, m) in dm for p, m in zip(d.post, d.ym)], index=d.index)
        if src.get("codes", {}).get("dash_month", "flag") == "missing":
            # unreported months written as "-" (Sumsel: CPC median 163 mm in such months, F59)
            for post, n in d[mask].groupby("post").size().items():
                per_post_kinds.setdefault(post, Counter())["dash_month_missing"] += int(n)
            d = d[~mask]
        else:
            d.loc[mask, "flag"] = "dash_month"
        for post, g in d.groupby("post"):
            if post not in cat.index or pd.isna(cat.loc[post, "lat"]):
                kinds["post_without_coordinates"] += 1
                kinds["values_skipped_no_coordinates"] += int(g.value.notna().sum())
                continue
            c = cat.loc[post]
            if not in_bbox(c.lat, c.lon, bbox):
                kinds["post_outside_bbox"] += 1
                kinds["values_skipped_outside_bbox"] += int(g.value.notna().sum())
                continue
            key = re.sub(r"[^A-Za-z0-9|._-]+", "_", post)
            skey, sid = f"{ns}:{key}", f"{src['name']}:{key}:{var}"
            no = post.split("|", 1)[0].strip()
            wmo = no if WMO_RE.fullmatch(no) else ""
            pk = per_post_kinds.get(post, Counter())
            stations.append(dict(station_key=skey, source=ns, network=src.get("network", ""), source_station_id=post,
                                 name=str(c["name"]), lat=float(c.lat), lon=float(c.lon),
                                 elev_m=float(c.elev) if pd.notna(c.elev) else np.nan,
                                 country=src.get("country", "ID"), wmo_id=wmo))
            series.append(dict(series_id=sid, station_key=skey, source=src["name"], variable=var,
                               units=src.get("units", "mm"), day_convention=src.get("day_convention", ""),
                               n_values=int(g.value.notna().sum()),
                               n_missing_code=int(pk["missing_code"] + pk["missing_text"] + pk["dash_missing"] + pk["dash_month_missing"]),
                               n_unparsed=int(pk["unparsed"] + pk["out_of_range"] + pk["impossible_date_value"]),
                               first=g.date.min(), last=g.date.max(),
                               note=f"{c['name']}; coords: {c.coord_source}; cells: "
                                    + ", ".join(f"{k}={v}" for k, v in sorted(pk.items()))))
            obs.append(pd.DataFrame({"series_id": sid, "date": g.date.values, "value": g.value.values, "flag": g.flag.values}))
    # agro layout: multi-variable, one station per post key
    if agro:
        a = pd.concat(agro, ignore_index=True)
        for post, g in a.groupby("post"):
            if post not in cat.index or pd.isna(cat.loc[post, "lat"]):
                continue
            c = cat.loc[post]
            key = re.sub(r"[^A-Za-z0-9|._-]+", "_", post)
            skey = f"{ns}:{key}"
            stations.append(dict(station_key=skey, source=ns, network=src.get("network", ""), source_station_id=post,
                                 name=str(c["name"]), lat=float(c.lat), lon=float(c.lon),
                                 elev_m=float(c.elev) if pd.notna(c.elev) else np.nan,
                                 country=src.get("country", "ID"), wmo_id=""))
            g = g.drop_duplicates(["date", "var"], keep="first")
            for v, gv in g.groupby("var"):
                sid = f"{src['name']}:{key}:{v}"
                series.append(dict(series_id=sid, station_key=skey, source=src["name"], variable=v,
                                   units="", day_convention=src.get("day_convention", ""),
                                   n_values=int(gv.value.notna().sum()), n_missing_code=0, n_unparsed=0,
                                   first=gv.date.min(), last=gv.date.max(),
                                   note=f"{c['name']}; coords: {c.coord_source}; sheets {gv.sheet.nunique()}"))
                obs.append(pd.DataFrame({"series_id": sid, "date": pd.to_datetime(gv.date).values,
                                         "value": gv.value.values, "flag": gv["flag"].fillna("").values}))
    print(f"  read {src['name']}: {n_books} workbooks, {len(stations)} stations, {len(series)} series"
          + (f" | skipped: {dict(kinds)}" if kinds else ""))
    st = pd.DataFrame(stations, columns=STATION_COLS)
    se = pd.DataFrame(series, columns=SERIES_COLS)
    ob = pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=OBS_COLS)
    return st, se, ob[OBS_COLS]
