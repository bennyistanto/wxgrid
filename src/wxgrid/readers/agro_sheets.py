"""Sheet parser for the agro-climate daily forms in `Data Stasiun` (station-folder
compilations and the per-year METKLIM files). One parser covers the layout variants found
in the 2026-10-08 ledger (F55):

- header row = the row holding "Lintang"; column labels may sit on that row or the next
  (Tahun / Hari / Bulan / BLN / Kabupaten / No. Sta. / Nama / Elevasi / variables);
- variables are matched by normalised label (RH07 = RH0.7 = Rh07 = RH07.0 = RH (07.00) ...);
  labels with no confirmed meaning (P, Ept) are counted, not mapped;
- coordinates are collected as votes (numeric cells or text like 6deg 15' 0" S, T = east)
  from the Lintang / Bujur groups; the station catalogue decides the final position;
- dates: year from the Tahun column, else the caller's file/sheet year, else an Excel date
  serial; month names only from the date columns; day as day-of-month (month from names,
  else from day resets) or day-of-year when the day column exceeds 31.

Returns plain records; identity, coordinates and de-duplication are the caller's job.
"""
import re

import pandas as pd
import xlrd

MONTHS = {"JAN": 1, "PEB": 2, "FEB": 2, "MAR": 3, "APR": 4, "MEI": 5, "MAY": 5, "JUN": 6, "JUL": 7,
          "AGS": 8, "AGT": 8, "AGU": 8, "AUG": 8, "SEP": 9, "OKT": 10, "OCT": 10, "NOP": 11, "NOV": 11,
          "DES": 12, "DEC": 12}

# normalised label -> variable code
VAR_LABELS = {
    "CH": "RR",
    "TMAX": "TX", "TMIN": "TN", "TRATA": "TG",
    "RHRATA": "HU", "RHMAX": "HUX", "RHMIN": "HUN",
    "RH07": "HU07", "RH007": "HU07", "RH0700": "HU07", "RH070": "HU07", "RH7": "HU07",
    "RH13": "HU13", "RH1300": "HU13", "RH130": "HU13",
    "E": "EV",
    "V": "FG", "URATA": "FG",
    "RAD": "RA", "RADIASI": "RA",
    "SS": "SS",   # split into SS (hours) / SSP (percent) by value range, per sheet
    "ARAH": "DD",
}
UNMAPPED_KNOWN = {"P", "EPT"}   # present in sheets, meaning not confirmed [to verify]
BOUNDS = {"RR": (0, 2000), "TX": (0, 50), "TN": (-5, 45), "TG": (-5, 45), "HU": (0, 100), "HUX": (0, 100),
          "HUN": (0, 100), "HU07": (0, 100), "HU13": (0, 100), "EV": (0, 50), "FG": (0, 60), "RA": (0, 1200),
          "SS": (0, 24), "SSP": (0, 100), "DD": (0, 360)}
TRACE = {"TTU", "TTU.", "TT", "0*"}


def norm(label):
    s = str(label).upper()
    s = re.sub(r"[\s\.\(\)\-_:]", "", s)
    return s


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    s = re.sub(r"[°º'\"]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


MONTH_NAMES = {1: ("januari", "january"), 2: ("pebruari", "februari", "february"), 3: ("maret", "march"),
               4: ("april",), 5: ("mei", "may"), 6: ("juni", "june"), 7: ("juli", "july"),
               8: ("agustus", "august"), 9: ("september",), 10: ("oktober", "october"),
               11: ("nopember", "november"), 12: ("desember", "december")}
MONTH_TYPOS = {"ags": 8, "agt": 8, "agst": 8, "augs": 8, "aprl": 4, "oktb": 10, "desmber": 12, "sept": 9,
               "nop": 11, "peb": 2, "mart": 3, "mrt": 3, "novi": 11, "desi": 12}


def _month(v):
    """Month number for a month word (Indonesian or English, full or abbreviated, known typos).
    A word that merely starts like a month (e.g. the place name "Maros") is not a month."""
    if not isinstance(v, str):
        return None
    s = re.sub(r"[^a-z]", "", v.strip().lower())
    if len(s) < 3:
        return None
    if s in MONTH_TYPOS:
        return MONTH_TYPOS[s]
    for m, names in MONTH_NAMES.items():
        if any(n.startswith(s) for n in names):
            return m
    return None


def _find(labels_by_col, *names, startswith=False):
    for c, labs in labels_by_col.items():
        for lab in labs:
            if (lab.startswith(names) if startswith else lab in names):
                return c
    return None


def parse_sheet(sh, datemode, year_hint=None):
    """Parse one agro sheet. Returns (records, meta) or (None, reason)."""
    if sh.nrows < 5:
        return None, "empty"
    hrow = next((r for r in range(min(4, sh.nrows))
                 if any("LINTANG" in str(sh.cell_value(r, c)).upper() for c in range(sh.ncols))), None)
    if hrow is None:
        return None, "no Lintang header"
    hdr_rows = [r for r in (hrow, hrow + 1, hrow + 2) if r < sh.nrows]
    labels = {c: [norm(sh.cell_value(r, c)) for r in hdr_rows if norm(sh.cell_value(r, c))]
              for c in range(sh.ncols)}
    # variable-name row = the header-block row holding "CH"
    var_row = next((r for r in hdr_rows if any(norm(sh.cell_value(r, c)) == "CH" for c in range(sh.ncols))), None)
    if var_row is None:
        return None, "no CH column"
    vcols, unmapped = {}, []
    for c in range(sh.ncols):
        lab = norm(sh.cell_value(var_row, c))
        if not lab:
            continue
        if lab in VAR_LABELS:
            vcols[c] = VAR_LABELS[lab]
        elif lab in UNMAPPED_KNOWN:
            unmapped.append(lab)
    c_year = _find(labels, "TAHUN")
    c_day = _find(labels, "HARI", "TGL", "TANGGAL")
    c_mon = _find(labels, "BULAN", "BLN")
    c_name = _find(labels, "NAMA", "NAMASTASIUN", startswith=True)
    c_kab = _find(labels, "KABUPATEN")
    c_lat = _find(labels, "LINTANG", startswith=True)
    c_lon = _find(labels, "BUJUR", startswith=True)
    if c_day is None:
        # unlabelled day column: the first column right of BLN / Tahun holding 1, 2, 3 ...
        for base in (c_mon, c_year):
            if base is None:
                continue
            for c in (base + 1, base + 2):
                col = [sh.cell_value(r, c) for r in range(hrow + 1, min(hrow + 8, sh.nrows))]
                nums = [v for v in col if isinstance(v, float)]
                if len(nums) >= 3 and nums[:3] == sorted(nums[:3]) and nums[0] <= 2:
                    c_day = c
                    break
            if c_day is not None:
                break
    if c_day is None:
        return None, "no day column"
    date_cols = [c for c in (c_year, c_mon, c_day) if c is not None]

    # first data row: first row after the header block whose day cell is a number
    first = next((r for r in range(hrow + 1, sh.nrows)
                  if (isinstance(sh.cell_value(r, c_day), float))
                  or (isinstance(sh.cell_value(r, c_day), str) and _month(sh.cell_value(r, c_day)))), None)
    if first is None:
        return None, "no numeric day"

    meta = dict(name_cell="", kab_cell="", coord_votes=[], unmapped=unmapped, notes=[])
    # metadata cells: name / kabupaten from the first rows that carry them
    for r in range(hrow, min(first + 3, sh.nrows)):
        if c_name is not None and not meta["name_cell"]:
            v = str(sh.cell_value(r, c_name)).strip()
            if v and norm(v) not in ("STASIUN", "STA", "NAMA", "NAMASTASIUN"):
                meta["name_cell"] = v
        if c_kab is not None and not meta["kab_cell"]:
            v = str(sh.cell_value(r, c_kab)).strip()
            if v and norm(v) != "KABUPATEN":
                meta["kab_cell"] = v
    # coordinate votes
    for r in range(hrow, min(first + 3, sh.nrows)):
        vote = {}
        for key, c0, c1 in (("lat", c_lat, c_lon), ("lon", c_lon, None)):
            if c0 is None:
                continue
            end = c1 if c1 is not None and c1 > c0 else c0 + 4
            nums, hemi = [], ""
            for c in range(c0, min(end, sh.ncols)):
                v = sh.cell_value(r, c)
                if isinstance(v, str) and v.strip().upper() in ("S", "U", "N", "E", "T", "W", "B"):
                    hemi = v.strip().upper()
                    break
                n = _num(v)
                if n is not None:
                    nums.append(n)
            if nums:
                vote[key] = (nums + [0, 0])[:3] + [hemi]
        if "lat" in vote and "lon" in vote:
            meta["coord_votes"].append(vote)
            break

    # year
    year = None
    if c_year is not None:
        for r in range(hrow, min(first + 3, sh.nrows)):
            n = _num(sh.cell_value(r, c_year))
            if n is not None and 1900 <= n <= 2100:
                year = int(n)
                break
    meta["year_cell"] = year
    meta["year_hint"] = year_hint
    if year is not None and year_hint and year != year_hint:
        meta["notes"].append(f"year conflict: Tahun cell {year} vs name {year_hint}")
    if year is None and year_hint:
        year = year_hint
    if year is None:
        for c in (c_year, c_day):
            if c is None:
                continue
            v = sh.cell_value(first, c)
            if isinstance(v, float) and v > 3000:
                year = xlrd.xldate_as_datetime(v, datemode).year
                meta["notes"].append("year from date serial")
                break
    if year is None:
        return None, "no year"

    def _day(v):
        # a month name in the day cell marks day 1 of that month ("Jan" on the first row)
        if isinstance(v, str):
            w = re.sub(r"[^a-z]", "", v.strip().lower())
            if _month(v) or (3 <= len(w) <= 9 and w == v.strip().lower().replace(".", "")):
                return 1.0
            n = _num(v)
            return n if n is not None and n.is_integer() else None
        return _num(v)
    days = [_day(sh.cell_value(r, c_day)) for r in range(first, sh.nrows)]
    numeric_days = [d for d in days if d is not None]
    doy = bool(numeric_days) and max(d for d in numeric_days if d < 3000) > 31
    has_names = any(_month(sh.cell_value(r, c)) for r in range(first, sh.nrows) for c in date_cols)

    # pass 1: rows with year, day and any month label
    rows, last_d = [], 0
    for i, r in enumerate(range(first, sh.nrows)):
        if c_year is not None and i > 0:
            n = _num(sh.cell_value(r, c_year)) if not isinstance(sh.cell_value(r, c_year), str) else None
            if n is not None and 1900 <= n <= 2100 and int(n) != year:
                year = int(n)
                meta["notes"].append(f"year changes inside sheet to {year}")
        name_m = None
        for c in date_cols:
            m = _month(sh.cell_value(r, c))
            if m:
                name_m = m
        d = days[i]
        if d is None:
            continue
        if d >= 3000 and doy:
            # day-of-year sheets: a date serial is only meaningful as day 1 on the first row
            if i != 0:
                continue
            d = 1.0
        elif d >= 3000:
            # "1-Feb" typed into the day cell becomes an Excel date: its day and month are
            # the record's, its year is the typing year, so only day and month are used
            try:
                dt = xlrd.xldate_as_datetime(d, datemode)
            except Exception:
                continue
            d, name_m = float(dt.day), dt.month
        d = int(d)
        if last_d > 300 and d < last_d - 300:   # day-of-year numbering restarts: next year
            year += 1
            meta["notes"].append(f"day numbering restarts, assumed year {year}")
        last_d = d
        rows.append([r, year, d, name_m, None])

    # pass 2: dates. Day-of-year rows (day > 31) date themselves. Day-of-month rows are split
    # into month blocks at each day restart; 12 blocks in a year are Jan..Dec in order and the
    # labels are only cross-checked; with fewer blocks the labels place them.
    for yr in sorted({x[1] for x in rows}):
        dm = [x for x in rows if x[1] == yr and x[2] <= 31]
        has_doy = any(x[1] == yr and x[2] > 31 for x in rows)
        blocks, prev = [], 0
        for x in dm:
            if not blocks or x[2] <= prev:
                blocks.append([])
            blocks[-1].append(x)
            prev = x[2]
        if has_doy:
            # mixed sheet: day-of-month rows only before the day-of-year rows; label or sequence
            blocks_m = []
            m = 0
            for b in blocks:
                lab = next((x[3] for x in b if x[3] and x[2] <= 3), None)
                m = lab if lab and lab > m else m + 1
                blocks_m.append(m)
        elif len(blocks) == 12:
            blocks_m = list(range(1, 13))
            labs = [next((x[3] for x in b if x[3] and x[2] <= 3), None) for b in blocks]
            bad = [(i + 1, l) for i, l in enumerate(labs) if l and l != i + 1]
            if bad:
                meta["notes"].append(f"{yr}: 12 month blocks, labels disagree at {bad}; order kept")
        else:
            blocks_m, m = [], 0
            for b in blocks:
                lab = next((x[3] for x in b if x[3] and x[2] <= 3), None)
                seq = m + 1
                if lab and lab > m and lab != seq and seq <= 12:
                    # label and sequence disagree: the block's last day is evidence of its month
                    last = max(x[2] for x in b)
                    if last == pd.Period(f"{yr}-{seq:02d}").days_in_month != pd.Period(f"{yr}-{lab:02d}").days_in_month:
                        meta["notes"].append(f"{yr}: block of {last} days labelled {lab}, placed as {seq}")
                        lab = seq
                if lab and lab > m:
                    m = lab
                else:
                    if lab:
                        meta["notes"].append(f"{yr}: label {lab} out of order after month {m}; sequence used")
                    m += 1
                blocks_m.append(m)
            if len(blocks) > 12:
                meta["notes"].append(f"{yr}: {len(blocks)} month blocks; extra dropped")
        for b, m in zip(blocks, blocks_m):
            if m > 12:
                continue
            for x in b:
                try:
                    x[4] = pd.Timestamp(year=yr, month=m, day=x[2])
                except ValueError:
                    pass
        for x in rows:
            if x[1] == yr and x[2] > 31 and x[2] <= 366:
                dt = pd.Timestamp(year=yr, month=1, day=1) + pd.Timedelta(days=x[2] - 1)
                if dt.year == yr:
                    x[4] = dt

    recs = []
    for r, yr, d, name_m, date in rows:
        if date is None:
            continue
        for c, var in vcols.items():
            raw = sh.cell_value(r, c)
            if isinstance(raw, str):
                s = raw.strip().upper()
                if var == "RR" and s in TRACE:
                    recs.append((date, var, float("nan"), "unmeasurable"))
                    continue
            v = _num(raw)
            if v is None:
                continue
            recs.append((date, var, v, ""))
    if not recs:
        return None, "no values"
    df = pd.DataFrame(recs, columns=["date", "var", "value", "flag"])
    # sunshine: percent when any value exceeds 24
    ss = df["var"] == "SS"
    if ss.any() and df.loc[ss, "value"].max() > 24:
        df.loc[ss, "var"] = "SSP"
        meta["notes"].append("SS recorded as percent")
    # RH07 vs RH13 sanity: morning humidity is normally the higher of the two
    # the same date written twice in one sheet (count it; keep the first)
    dup = df.duplicated(["date", "var"], keep="first")
    meta["n_dup_dates"] = int(df.loc[dup, "date"].nunique())
    df = df[~dup]
    a = df[df["var"] == "HU07"].set_index("date")["value"]
    b = df[df["var"] == "HU13"].set_index("date")["value"]
    j = a.index.intersection(b.index)
    if len(j) > 30 and (a[j] < b[j]).mean() > 0.6:
        meta["notes"].append(f"RH07 < RH13 on {(a[j] < b[j]).mean():.0%} of days: labels possibly swapped")
    # bounds
    lo = df["var"].map(lambda v: BOUNDS.get(v, (-1e9, 1e9))[0])
    hi = df["var"].map(lambda v: BOUNDS.get(v, (-1e9, 1e9))[1])
    oob = df["value"].notna() & ((df["value"] < lo) | (df["value"] > hi))
    meta["n_out_of_bounds"] = int(oob.sum())
    df = df[~oob]
    meta["year"] = year
    meta["layout"] = "doy" if doy else ("month-names" if has_names else "day-resets")
    return df, meta


def year_from_name(name):
    """Year in a per-year file or sheet name: the part after the last dash, else trailing
    digits (052X-77, 175A-73, GTG81, PUSAKA73, C-1977, bb-85). Station codes before the dash
    (50D, 175A, 052X, CPS68) are not years; "50D-GAB", "MNG-1", "Sheet1" give none."""
    stem = name.rsplit(".", 1)[0].strip()
    if "-" in stem:
        tail = stem.rsplit("-", 1)[1]
    else:
        m_tail = re.search(r"(\d+)$", stem)
        tail = m_tail.group(1) if m_tail else ""
    m = re.match(r"^(19\d{2}|\d{2})[A-Z]?$", tail.strip(), re.I)
    if not m:
        return None
    y = int(m.group(1))
    if y < 100:
        y = 1900 + y if y >= 50 else None
    return y


def year_hint(file_name, sheet_name, n_data_sheets):
    """Year hint for a sheet: its own name first; the file name only for one-sheet files."""
    return year_from_name(sheet_name) or (year_from_name(file_name) if n_data_sheets == 1 else None)


def coord_from_vote(v):
    """(deg, min, sec, hemi) -> signed decimal degrees; None if minutes/seconds unreadable."""
    d, m, s, h = v
    if not (0 <= m < 60 and 0 <= s < 60):
        return None
    x = d + m / 60 + s / 3600
    return -x if h in ("S", "W", "B") else x
