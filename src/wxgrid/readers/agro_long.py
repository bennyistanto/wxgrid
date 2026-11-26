"""Parser for the long-format agro climate sheets in `Data Stasiun` (one row per day, explicit
year / month / day columns, optional "Tahun:1984" block markers): Muneng MNG-*.XLS,
METKLIM/BENKEL.XLS (Bengkel, Central Kalimantan) and KAMBARA.XLS (Muna, SE Sulawesi).

Columns are mapped from a composite label per column: the header row plus the sub-label /
units rows below it. Units decide the variable code where they matter: wind in km/day is
converted to mean m/s (/ 86.4, flagged "from_km_per_day"); sunshine in % goes to SSP, in
hours to SS. Columns with no confirmed meaning (EPT), water temperature in the pan, the
automatic-gauge daily total and hourly rainfall are counted and not mapped.
"""
import re

import pandas as pd

from .agro_sheets import TRACE, _month, _num

BOUNDS = {"RR": (0, 2000), "TX": (0, 50), "TN": (-5, 45), "TG": (-5, 45), "HU": (0, 100), "HU07": (0, 100),
          "HU13": (0, 100), "EV": (0, 50), "FG": (0, 60), "RA": (0, 1200), "SS": (0, 24), "SSP": (0, 100)}


def _n(s):
    return re.sub(r"[^A-Z0-9%/]", "", str(s).upper())


def _header_row(sh):
    for r in range(min(12, sh.nrows)):
        labs = [_n(sh.cell_value(r, c)) for c in range(sh.ncols)]
        if any(l in ("TGL", "HARI") for l in labs) and any(l in ("BULAN", "BLN") for l in labs):
            return r
    return None


def column_map(sh, h):
    """Composite labels from the header row and the two rows below it -> {col: (code, factor, flag)}."""
    rows = [r for r in (h, h + 1, h + 2) if r < sh.nrows]
    comp = {c: [_n(sh.cell_value(r, c)) for r in rows] for c in range(sh.ncols)}
    cmap, unmapped, ctx = {}, [], ""
    for c in range(sh.ncols):
        head, *below = comp[c]
        allp = [p for p in [head] + below if p]
        txt = " ".join(allp)
        if head:
            ctx = head
        if not allp or head in ("TAHUN", "BULAN", "BLN", "TGL", "HARI"):
            continue
        if head in ("CH",) or (head.startswith("HUJAN") and "HARIAN" in txt):
            cmap[c] = ("RR", 1.0, "")
        elif head.startswith("HUJAN"):
            unmapped.append("rain:" + (below[0] if below and below[0] else head))   # automatic / hourly
        elif head in ("RH7", "RH07"):
            cmap[c] = ("HU07", 1.0, "")
        elif head == "RH13":
            cmap[c] = ("HU13", 1.0, "")
        elif head == "MEAN" and ctx == "MEAN":        # the Mean right of RH13 (Muneng)
            cmap[c] = ("HU", 1.0, "")
        elif head in ("RH",) and "%" in txt:
            cmap[c] = ("HU", 1.0, "")
        elif head in ("PENGUAPAN",) or ("PAN" in txt and "ETP" in txt):
            cmap[c] = ("EV", 1.0, "")
        elif head in ("EPT", "ETP"):
            unmapped.append(head)
        elif head == "V":
            cmap[c] = ("FG", 1.0, "")
        elif head.startswith("KEC"):
            if "KM" in txt:
                cmap[c] = ("FG", 1 / 86.4, "from_km_per_day")
            else:
                cmap[c] = ("FG", 1.0, "")
        elif head.startswith("RAD"):
            cmap[c] = ("RA", 1.0, "")
        elif head == "SS" or (head.startswith("SINAR") and "%" not in txt):
            cmap[c] = ("SS", 1.0, "")
        elif head.startswith("SINAR"):
            cmap[c] = ("SSP", 1.0, "")
        elif head.startswith("TAIR") or head.startswith("TAI"):
            unmapped.append("water_temperature")
        elif "MAX" in below or head == "MAX":
            cmap[c] = ("TX", 1.0, "")
        elif "MIN" in below or head == "MIN":
            cmap[c] = ("TN", 1.0, "")
        elif ("MEAN" in below or "RATA2" in below) and not cmap.get(c):
            cmap[c] = ("TG", 1.0, "")
        elif head.startswith("TEMP") and not any(x in below for x in ("MAX", "MIN")):
            cmap[c] = ("TG", 1.0, "")
        elif head.startswith("TEMPERATU"):
            cmap[c] = ("TX", 1.0, "")                     # Bengkel: "Temperatur" over Max
        else:
            unmapped.append(head or "/".join(below))
    return cmap, unmapped


def _col_values(sh, c, rows):
    return pd.Series({r: _num(sh.cell_value(r, c)) for r in rows}).dropna()


def parse_long_sheet(sh, datemode, year_hint=None):
    h = _header_row(sh)
    if h is None:
        return None, "no Bulan/Tgl header"
    cmap, unmapped = column_map(sh, h)
    notes = []
    labs = [_n(sh.cell_value(h, c)) for c in range(sh.ncols)]
    c_year = labs.index("TAHUN") if "TAHUN" in labs else None
    c_mon = next(i for i, l in enumerate(labs) if l in ("BULAN", "BLN"))
    c_day = next(i for i, l in enumerate(labs) if l in ("TGL", "HARI"))
    data_rows = [r for r in range(h + 1, sh.nrows) if isinstance(sh.cell_value(r, c_day), float)]

    # a repeated "Max" label in the air-temperature triple: the later column is the mean when
    # its values lie between Min and Max on most days (MNG91.XLS units row "Max Min Max")
    tx = sorted(c for c, v in cmap.items() if v[0] == "TX")
    tn = next((c for c, v in cmap.items() if v[0] == "TN"), None)
    if len(tx) == 2 and tn is not None:
        va, vb, vn = (_col_values(sh, c, data_rows) for c in (tx[0], tx[1], tn))
        j = va.index.intersection(vb.index).intersection(vn.index)
        between = float(((vb[j] <= va[j]) & (vb[j] >= vn[j])).mean()) if len(j) else 0.0
        if between >= 0.8:
            cmap[tx[1]] = ("TG", 1.0, "")
            notes.append(f"second 'Max' column read as mean (between Min and Max on {between:.0%} of days)")

    year, month, recs, prev_d = year_hint, None, [], 0
    for r in range(sh.nrows):
        first = str(sh.cell_value(r, 0)).strip()
        m = re.match(r"(?i)tahun\s*:?\s*(\d{4})", first)
        if m:                                   # block marker "Tahun:1984"
            year, month = int(m.group(1)), None
            continue
        year_cell_here = False
        if c_year is not None:
            y = _num(sh.cell_value(r, c_year)) if not isinstance(sh.cell_value(r, c_year), str) else None
            if y is not None and 1900 <= y <= 2100:
                year, year_cell_here = int(y), True
        mm = _month(sh.cell_value(r, c_mon))
        if mm:
            if mm == 1 and month == 12 and not year_cell_here and year is not None:
                year += 1
                notes.append(f"Dec->Jan without a year cell: assumed {year}")
            month = mm
            prev_d = 0
        d = sh.cell_value(r, c_day)
        if not isinstance(d, float) or not 1 <= d <= 31 or year is None or month is None:
            continue
        if not mm and d <= prev_d and month is not None:   # day restarts with no month label
            month += 1
            if month > 12:
                month = 12
                continue
        prev_d = d
        try:
            date = pd.Timestamp(year=year, month=month, day=int(d))
        except ValueError:
            continue
        for c, (code, fac, flag) in cmap.items():
            raw = sh.cell_value(r, c)
            if code == "RR" and isinstance(raw, str) and raw.strip().upper() in TRACE:
                recs.append((date, code, float("nan"), "unmeasurable"))
                continue
            v = _num(raw)
            if v is None:
                continue
            recs.append((date, code, round(v * fac, 3), flag))
    if not recs:
        return None, "no values"
    df = pd.DataFrame(recs, columns=["date", "var", "value", "flag"])
    dup = df.duplicated(["date", "var"], keep="first")
    df = df[~dup]
    lo = df["var"].map(lambda v: BOUNDS.get(v, (-1e9, 1e9))[0])
    hi = df["var"].map(lambda v: BOUNDS.get(v, (-1e9, 1e9))[1])
    oob = df["value"].notna() & ((df["value"] < lo) | (df["value"] > hi))
    meta = dict(cmap={c: v[0] for c, v in cmap.items()}, unmapped=unmapped, n_dup=int(dup.sum()),
                n_out_of_bounds=int(oob.sum()), years=sorted(df["date"].dt.year.unique().tolist()), notes=notes)
    return df[~oob], meta
