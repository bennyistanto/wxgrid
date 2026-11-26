"""Second pass over the recheck dumps: find time axes in every worksheet.

Reads F:/temp/station/additional_recheck/dump/*.txt (written by recheck_additional.py) and,
per worksheet, measures:
  * year axis: the column (first 6) or row (first 40) holding the most distinct integer
    years 1850-2030 that are non-decreasing in reading order (rainfall totals in the same
    range are scattered, so they rarely form a sorted run); also every "TAHUN/YEAR <yyyy>" text
    year anywhere in the sheet and a year in the sheet name.
  * month axis: 12 distinct month names (Indonesian or English) in one row or one column.
  * day axis: longest 1..n run in a column or row (from sheets.csv).
  * date cells: Excel dates, min/max and the most common step between sorted distinct dates.
  * long-format month column: a column next to the year axis with values 1..12.
Output: F:/temp/station/additional_recheck/sheets_axes.csv
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

OUT = Path("F:/temp/station/additional_recheck")
MONTHS = {
    "JAN": 1, "JANUARI": 1, "JANUARY": 1, "FEB": 2, "PEB": 2, "FEBRUARI": 2, "PEBRUARI": 2, "FEBRUARY": 2,
    "MAR": 3, "MARET": 3, "MARCH": 3, "APR": 4, "APRIL": 4, "MEI": 5, "MAY": 5, "JUN": 6, "JUNI": 6, "JUNE": 6,
    "JUL": 7, "JULI": 7, "JULY": 7, "AGU": 8, "AGT": 8, "AGS": 8, "AGUS": 8, "AGUSTUS": 8, "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "OKT": 10, "OCT": 10, "OKTOBER": 10, "OCTOBER": 10,
    "NOP": 11, "NOV": 11, "NOPEMBER": 11, "NOVEMBER": 11, "DES": 12, "DEC": 12, "DESEMBER": 12, "DECEMBER": 12,
}
YEAR_TXT = re.compile(r"(?:TAHUN|THN|YEAR|TH\.?)\s*[:.]?\s*(1[89]\d\d|20[0-3]\d)", re.I)
YEAR_RE = re.compile(r"(?<!\d)(1[89]\d\d|20[0-3]\d)(?!\d)")
NUMLIKE = re.compile(r"-?\d+(?:[.,]\d+)?")


def parse_dump(p: Path):
    """Yield (workbook label, sheet name, rows) where rows is {r: [cell strings]}."""
    label, sheet, rows = None, None, {}
    for line in p.open(encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("# WORKBOOK "):
            label = line[len("# WORKBOOK "):]
        elif line.startswith("## SHEET "):
            if sheet is not None:
                yield label, sheet, rows
            m = re.match(r"## SHEET (.*) state=", line)
            sheet = eval(m.group(1))  # repr written by the dump step of this tool
            rows = {}
        elif line.startswith("r") and "\t" in line:
            r, rest = line.split("\t", 1)
            rows[int(r[1:])] = rest.split("\t")
    if sheet is not None:
        yield label, sheet, rows


def as_year(s: str):
    if re.fullmatch(r"(1[89]\d\d|20[0-3]\d)", s):
        return int(s)
    return None


def sorted_run_years(vals: list[int]) -> list[int]:
    """Longest non-decreasing subsequence of years in reading order (greedy over runs)."""
    best, cur = [], []
    for y in vals:
        if not cur or y >= cur[-1]:
            cur.append(y)
        else:
            if len(set(cur)) > len(set(best)):
                best = cur
            cur = [y]
    if len(set(cur)) > len(set(best)):
        best = cur
    return best


def analyse(rows: dict[int, list[str]]) -> dict:
    nr = max(rows) + 1 if rows else 0
    res = dict(year_axis="", y0="", y1="", ny=0, text_year="", month_axis="", month_col_1_12="",
               date_step_days="", n_dates=0)
    allv = [v for r in rows for v in rows[r] if v != ""]
    res["n_numlike"] = sum(bool(NUMLIKE.fullmatch(v.strip())) for v in allv)  # numeric cells + numbers stored as text
    res["n_dash"] = sum(v.strip() in ("-", "--", "x", "X") for v in allv)
    # year axis in columns 0..5
    best = (0, "", [])
    for c in range(6):
        vals = [as_year(rows[r][c]) for r in sorted(rows) if c < len(rows[r])]
        vals = [v for v in vals if v]
        run = sorted_run_years(vals)
        if len(set(run)) > best[0]:
            best = (len(set(run)), f"col{c}", run)
    for r in sorted(rows)[:40]:
        vals = [as_year(v) for v in rows[r]]
        vals = [v for v in vals if v]
        run = sorted_run_years(vals)
        if len(set(run)) > best[0]:
            best = (len(set(run)), f"row{r}", run)
    if best[0] >= 2:
        res.update(year_axis=best[1], y0=min(best[2]), y1=max(best[2]), ny=best[0])
    # text year in first 15 rows
    ty = set()
    for r in sorted(rows):  # every row: multi-year block sheets repeat "Tahun : yyyy" per block
        for v in rows[r]:
            for y in YEAR_TXT.findall(v):
                ty.add(int(y))
    res["text_year"] = ";".join(map(str, sorted(ty)))
    # month axis
    for r in sorted(rows)[:60]:
        ms = {MONTHS.get(re.sub(r"[^A-Z]", "", v.upper())) for v in rows[r]} - {None}
        if len(ms) >= 12:
            res["month_axis"] = f"row{r}"
            break
    if not res["month_axis"]:
        for c in range(8):
            ms = {MONTHS.get(re.sub(r"[^A-Z]", "", rows[r][c].upper())) for r in rows if c < len(rows[r])} - {None}
            if len(ms) >= 12:
                res["month_axis"] = f"col{c}"
                break
    # long format: a column holding only 1..12 repeated, many rows
    for c in range(8):
        vals = [rows[r][c] for r in rows if c < len(rows[r]) and rows[r][c] != ""]
        ints = [int(v) for v in vals if re.fullmatch(r"\d{1,2}", v)]
        if len(ints) >= 24 and set(ints) == set(range(1, 13)) and len(ints) >= 0.8 * len(vals):
            res["month_col_1_12"] = f"col{c}"
            break
    # date cells
    ds = sorted({v[2:12] for r in rows for v in rows[r] if v.startswith("D:")})
    res["n_dates"] = len(ds)
    if len(ds) >= 3:
        d = pd.to_datetime(pd.Series(ds), errors="coerce").dropna().sort_values()
        steps = d.diff().dt.days.dropna()
        if len(steps):
            res["date_step_days"] = int(Counter(steps).most_common(1)[0][0])
    return res


def main():
    s = pd.read_csv(OUT / "sheets_unique.csv")
    keep = set(zip(s.label, s.sheet.astype(str)))
    recs = []
    for p in sorted((OUT / "dump").glob("*.txt")):
        for label, sheet, rows in parse_dump(p):
            if (label, str(sheet)) not in keep:
                continue
            recs.append(dict(label=label, sheet=str(sheet), **analyse(rows)))
    a = pd.DataFrame(recs)
    s["sheet"] = s.sheet.astype(str)
    m = s.merge(a, on=["label", "sheet"], how="left", validate="one_to_one")
    m["n_numtext"] = (m.n_numlike - m.n_num).clip(lower=0)
    m.to_csv(OUT / "sheets_axes.csv", index=False)
    print("sheets:", len(m), "| analysed:", m.year_axis.notna().sum())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
