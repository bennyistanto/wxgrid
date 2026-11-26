"""Parsers for the remaining daily layouts in `Data Stasiun` (see F55 ledger):

- parse_mau:      FLORES/MAU7879..MAU8889 (Maumere), a running day counter that is 305 on
                  1 November of the first year; month labels are checked against it.
- parse_day_month_grid: FLORES WMILOK90/91, WBL90-91, MPA-9091 (Tgl rows x month columns,
                  possibly two year blocks stacked).
- parse_sikka:    FLORES/SIKKA.XLS (TGL, Bulan "Okt'90", rain, sunshine h, Tmax, Tmin, ...).
- parse_day_year_grid: BEKASI/H-319996.XLS (Bulan, Tgl, Hari ke, one column per year).
- parse_bmg_forms: BMG-JKT/BMG8194.XLS (monthly blocks "JANUARI 1981" with Tanggal rows).
- parse_radiation_matrix: JAKENAN1.XLS style (365 day rows x year columns, then summaries).

Each returns (DataFrame[date, var, value, flag], meta) or (None, reason). Values outside the
element bounds are dropped and counted; columns without a confirmed meaning are listed in
meta["unmapped"], not guessed.
"""
import re

import pandas as pd

from .agro_sheets import TRACE, _month, _num

BOUNDS = {"RR": (0, 2000), "TX": (0, 50), "TN": (-5, 45), "TG": (-5, 45), "HU": (0, 100), "EV": (0, 50),
          "RA": (0, 1200), "SS": (0, 24), "SSP": (0, 100)}


def _finish(recs, meta):
    if not recs:
        return None, "no values"
    df = pd.DataFrame(recs, columns=["date", "var", "value", "flag"])
    dup = df.duplicated(["date", "var"], keep="first")
    df = df[~dup]
    lo = df["var"].map(lambda v: BOUNDS.get(v, (-1e9, 1e9))[0])
    hi = df["var"].map(lambda v: BOUNDS.get(v, (-1e9, 1e9))[1])
    oob = df["value"].notna() & ((df["value"] < lo) | (df["value"] > hi))
    meta.update(n_dup=int(dup.sum()), n_out_of_bounds=int(oob.sum()),
                years=sorted(df["date"].dt.year.unique().tolist()))
    return df[~oob], meta


def _val(raw, var):
    if var == "RR" and isinstance(raw, str) and raw.strip().upper() in TRACE:
        return float("nan"), "unmeasurable"
    v = _num(raw)
    return (v, "") if v is not None else (None, "")


def parse_mau(sh, start_year):
    hdr = [str(sh.cell_value(0, c)).strip().upper() for c in range(sh.ncols)]
    cmap = {}
    for c, h in enumerate(hdr):
        if h == "CH":
            cmap[c] = "RR"
        elif h.startswith("MAKS"):
            cmap[c] = "TX"
        elif h.startswith("MIN"):
            cmap[c] = "TN"
        elif h == "LP":
            cmap[c] = "SS"
    # radiation: of "Rad" and "R (Kal/cm2)" use the one whose values look like daily cal/cm2
    rad_cols = [c for c, h in enumerate(hdr) if h == "RAD" or h.startswith("R (KAL")]
    best = None
    for c in rad_cols:
        v = pd.Series([_num(sh.cell_value(r, c)) for r in range(1, sh.nrows)]).dropna()
        if len(v) > 30 and 100 <= v.median() <= 900:
            if best is None or hdr[c].startswith("R (KAL"):
                best = c
    if best is not None:
        cmap[best] = "RA"
    meta = dict(cmap={c: v for c, v in cmap.items()}, rad_column=hdr[best] if best is not None else "",
                unmapped=[h for c, h in enumerate(hdr) if h and c not in cmap and c != 0 and h != "BULAN"])
    base = pd.Timestamp(year=start_year, month=11, day=1)
    recs, mism = [], 0
    for r in range(1, sh.nrows):
        n = _num(sh.cell_value(r, 0))
        if n is None or not 305 <= n <= 672:
            continue
        date = base + pd.Timedelta(days=int(n) - 305)
        m = _month(sh.cell_value(r, 1))
        if m and m != date.month:
            mism += 1
        for c, var in cmap.items():
            v, fl = _val(sh.cell_value(r, c), var)
            if v is not None:
                recs.append((date, var, v, fl))
    meta["month_label_mismatches"] = mism
    return _finish(recs, meta)


def parse_day_month_grid(sh, years):
    """Tgl rows x Jan..Des columns; each 'Tgl' header row starts a block; block k gets years[k]."""
    blocks = [r for r in range(sh.nrows) if str(sh.cell_value(r, 0)).strip().upper().startswith("TGL")]
    recs, meta = [], dict(blocks=len(blocks), unmapped=[])
    for k, h in enumerate(blocks):
        if k >= len(years):
            meta.setdefault("notes", []).append(f"block {k + 1} has no year")
            continue
        y = years[k]
        months = {c: _month(sh.cell_value(h, c)) for c in range(1, sh.ncols)}
        end = blocks[k + 1] if k + 1 < len(blocks) else sh.nrows
        for r in range(h + 1, end):
            d = _num(sh.cell_value(r, 0))
            if d is None or not 1 <= d <= 31:
                continue
            for c, m in months.items():
                if not m:
                    continue
                try:
                    date = pd.Timestamp(year=y, month=m, day=int(d))
                except ValueError:
                    continue
                v, fl = _val(sh.cell_value(r, c), "RR")
                if v is not None:
                    recs.append((date, "RR", v, fl))
    return _finish(recs, meta)


def parse_sikka(sh):
    # rows: TGL | Bulan ("Okt'90") | CH | Lama Penyinaran | Suhu Maks | Min | Kec. Angin | RH Pagi | Siang | Penguapan
    cmap = {2: "RR", 3: "SS", 4: "TX", 5: "TN", 9: "EV"}
    meta = dict(cmap=cmap, unmapped=["Kec. Angin (labelled m/s, values up to ~116: unit unclear)",
                                     "RH pagi", "RH siang"])
    recs, y, m = [], None, None
    for r in range(sh.nrows):
        lab = str(sh.cell_value(r, 1)).strip()
        mm = re.match(r"([A-Za-z]+)\W*(\d{2})$", lab)
        if mm and _month(mm.group(1)):
            m, y = _month(mm.group(1)), 1900 + int(mm.group(2))
        d = _num(sh.cell_value(r, 0))
        if d is None or not 1 <= d <= 31 or y is None:
            continue
        try:
            date = pd.Timestamp(year=y, month=m, day=int(d))
        except ValueError:
            continue
        for c, var in cmap.items():
            if c < sh.ncols:
                v, fl = _val(sh.cell_value(r, c), var)
                if v is not None:
                    recs.append((date, var, v, fl))
    return _finish(recs, meta)


def parse_day_year_grid(sh):
    """Bulan | Tgl | Hari ke | <year> | <year> ...; date from month label + Tgl."""
    h = next(r for r in range(min(5, sh.nrows)) if str(sh.cell_value(r, 0)).strip().upper().startswith("BULAN"))
    ycols = {c: int(sh.cell_value(h, c)) for c in range(3, sh.ncols) if isinstance(sh.cell_value(h, c), float)}
    recs, m, unplaced = [], None, 0
    for r in range(h + 1, sh.nrows):
        mm = _month(sh.cell_value(r, 0))
        if mm:
            m = mm
        d = _num(sh.cell_value(r, 1))
        if d is None:
            if any(_num(sh.cell_value(r, c)) is not None for c in ycols):
                unplaced += 1   # e.g. the 'hari ke 366' row with no month/day
            continue
        for c, y in ycols.items():
            try:
                date = pd.Timestamp(year=y, month=m, day=int(d))
            except (ValueError, TypeError):
                continue
            v, fl = _val(sh.cell_value(r, c), "RR")
            if v is not None:
                recs.append((date, "RR", v, fl))
    return _finish(recs, dict(years_cols=list(ycols.values()), unplaced_rows=unplaced, unmapped=[]))


def parse_bmg_forms(sh):
    """Monthly blocks: a title row holding 'JANUARI 1981' etc., then a 'Tanggal' header row."""
    recs, meta = [], dict(unmapped=["T07", "T13", "T18"], blocks=0)
    r = 0
    while r < sh.nrows:
        row = [str(sh.cell_value(r, c)).strip() for c in range(sh.ncols)]
        if row and row[0].upper().startswith("TANGGAL"):
            title = " ".join(str(sh.cell_value(r - 1, c)) for c in range(sh.ncols)) if r > 0 else ""
            mt = re.search(r"([A-Za-z]{3,})\s+(\d[\d\s]{3,8})", title)
            m = _month(mt.group(1)) if mt else None
            y = int(re.sub(r"\s", "", mt.group(2))[:4]) if mt else None
            labs = [x.upper() for x in row]
            cmap = {}
            for c, l in enumerate(labs):
                if l.startswith("RERATA"):
                    cmap[c] = "TG"
                elif l == "MAX":
                    cmap[c] = "TX"
                elif l == "MIN":
                    cmap[c] = "TN"
                elif l.startswith("HUJAN"):
                    cmap[c] = "RR"
                elif l.startswith("AN MTH") or "%" in l:
                    cmap[c] = "SSP"
                elif l.startswith("EVAPORASI"):
                    cmap[c] = "EV"
            meta["blocks"] += 1
            r += 1
            while r < sh.nrows:
                d = sh.cell_value(r, 0)
                if isinstance(d, str) and d.strip().upper().startswith(("TANGGAL",)):
                    break
                nxt = " ".join(str(sh.cell_value(r, c)) for c in range(sh.ncols)).upper()
                if "TEMPERATU" in nxt:
                    break
                if isinstance(d, float) and 1 <= d <= 31 and m and y:
                    try:
                        date = pd.Timestamp(year=y, month=m, day=int(d))
                    except ValueError:
                        date = None
                    if date is not None:
                        for c, var in cmap.items():
                            v, fl = _val(sh.cell_value(r, c), var)
                            if v is not None:
                                recs.append((date, var, v, fl))
                r += 1
            continue
        r += 1
    return _finish(recs, meta)


def parse_radiation_matrix(sh, years, leap_rule):
    """Rows 1..365 are days of the year; columns are `years` (header row 0 when present).
    leap_rule (per year): 'drop_dec31' (row 60 is 1 March) or 'drop_feb29' (row 60 is 29 Feb).
    Rows after the 365th (max / min summaries) are ignored."""
    first = 1 if all(isinstance(sh.cell_value(0, c), float) and sh.cell_value(0, c) > 1900
                     for c in range(len(years))) else 0
    recs = []
    for j, y in enumerate(years):
        leap = pd.Timestamp(year=y, month=12, day=31).dayofyear == 366
        for i in range(365):
            r = first + i
            if r >= sh.nrows:
                break
            doy = i + 1
            if leap and leap_rule.get(y) == "drop_feb29" and doy >= 60:
                doy += 1
            date = pd.Timestamp(year=y, month=1, day=1) + pd.Timedelta(days=doy - 1)
            v = _num(sh.cell_value(r, j))
            if v is not None:
                recs.append((date, "RA", v, ""))
    return _finish(recs, dict(unmapped=[], first_row=first))
