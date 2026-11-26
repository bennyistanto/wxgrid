"""Full read-only recheck of every Excel workbook under F:/temp/station/additional-sources.

Walks every folder to the deepest level, opens every .xls / .xls1 / .xlsx file and every
Excel member inside every .zip, and for EVERY worksheet:
  * writes the complete cell grid to a text dump (one file per workbook), and
  * writes one row of measured features to a summary CSV.

Nothing is inferred here; the features are counts and ranges read from the cells, so the
classification step can be checked against the dump.

Outputs (outside the source folder):
  F:/temp/station/additional_recheck/files.csv     one row per file or zip member
  F:/temp/station/additional_recheck/sheets.csv    one row per worksheet
  F:/temp/station/additional_recheck/dump/*.txt    full cell content per workbook

Usage: python tools/recheck_additional.py
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

import openpyxl
import xlrd

ROOT = Path("F:/temp/station/additional-sources")
OUT = Path("F:/temp/station/additional_recheck")
DUMP = OUT / "dump"
EXCEL_EXT = (".xls", ".xls1", ".xlsx", ".xlsm")

MONTH_TOKENS = {
    1: ("JAN", "JANUARI", "JANUARY"), 2: ("FEB", "PEB", "FEBRUARI", "PEBRUARI", "FEBRUARY"),
    3: ("MAR", "MARET", "MARCH"), 4: ("APR", "APRIL"), 5: ("MEI", "MAY"),
    6: ("JUN", "JUNI", "JUNE"), 7: ("JUL", "JULI", "JULY"),
    8: ("AGU", "AGT", "AGS", "AGUS", "AGUSTUS", "AUG", "AUGUST"),
    9: ("SEP", "SEPT", "SEPTEMBER"), 10: ("OKT", "OCT", "OKTOBER", "OCTOBER"),
    11: ("NOP", "NOV", "NOPEMBER", "NOVEMBER"), 12: ("DES", "DEC", "DESEMBER", "DECEMBER"),
}
TOKEN_TO_MONTH = {t: m for m, ts in MONTH_TOKENS.items() for t in ts}
KEYWORDS = [
    "harian", "bulanan", "dasarian", "dekade", "tahunan", "rata", "jumlah", "normal",
    "curah hujan", "hujan", "ch", "rr", "rain", "suhu", "temp", "tmax", "tmin", "lembab", "rh",
    "tekanan", "angin", "wind", "penguapan", "evap", "radiasi", "penyinaran", "matahari",
    "lintang", "bujur", "elevasi", "tinggi", "nosta", "no sta", "stasiun", "pos", "wmo",
    "synop", "metar", "upper", "pilot", "temp ",
]
YEAR_RE = re.compile(r"(?<!\d)(1[89]\d\d|20[0-3]\d)(?!\d)")


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def magic(b: bytes) -> str:
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "OLE"
    if b[:2] == b"PK":
        return "ZIP"
    return "OTHER:" + repr(b[:16])


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{v:.6g}"
    if isinstance(v, (dt.datetime, dt.date)):
        return "D:" + v.isoformat()[:19]
    s = str(v).replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")
    return s


class SheetGrid:
    """A worksheet as rows of (python value, kind) with kind in n(umber) s(tring) d(ate) b(ool) e(rror)."""

    def __init__(self, name: str, state: str, rows: list[list[tuple]]):
        self.name, self.state, self.rows = name, state, rows


def read_xls(data: bytes) -> list[SheetGrid]:
    wb = xlrd.open_workbook(file_contents=data, on_demand=True)
    out = []
    for i, name in enumerate(wb.sheet_names()):
        sh = wb.sheet_by_index(i)
        state = {0: "visible", 1: "hidden", 2: "veryhidden"}.get(getattr(sh, "visibility", 0), "?")
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                t = cell.ctype
                if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append((None, ""))
                elif t == xlrd.XL_CELL_NUMBER:
                    row.append((float(cell.value), "n"))
                elif t == xlrd.XL_CELL_DATE:
                    try:
                        row.append((xlrd.xldate_as_datetime(cell.value, wb.datemode), "d"))
                    except Exception:
                        row.append((float(cell.value), "n"))
                elif t == xlrd.XL_CELL_BOOLEAN:
                    row.append((bool(cell.value), "b"))
                elif t == xlrd.XL_CELL_ERROR:
                    row.append((xlrd.error_text_from_code.get(cell.value, "#ERR"), "e"))
                else:
                    s = str(cell.value)
                    row.append((s, "s") if s.strip() else (None, ""))
            rows.append(row)
        out.append(SheetGrid(name, state, rows))
        wb.unload_sheet(i)
    extra = wb.nsheets - len(wb.sheet_names()) if hasattr(wb, "nsheets") else 0
    wb.release_resources()
    if extra > 0:
        out.append(SheetGrid(f"<{extra} non-worksheet sheet(s)>", "n/a", []))
    return out


def read_xlsx(data: bytes) -> list[SheetGrid]:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=False, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            row = []
            for v in r:
                if v is None or (isinstance(v, str) and not v.strip()):
                    row.append((None, ""))
                elif isinstance(v, bool):
                    row.append((v, "b"))
                elif isinstance(v, (int, float)):
                    row.append((float(v), "n"))
                elif isinstance(v, (dt.datetime, dt.date)):
                    row.append((v if isinstance(v, dt.datetime) else dt.datetime(v.year, v.month, v.day), "d"))
                elif isinstance(v, dt.time):
                    row.append((str(v), "s"))
                else:
                    row.append((str(v), "s"))
            rows.append(row)
        out.append(SheetGrid(ws.title, ws.sheet_state, rows))
    if wb.chartsheets:
        out.append(SheetGrid(f"<{len(wb.chartsheets)} chart sheet(s)>", "n/a", []))
    return out


def find_day_runs(rows) -> tuple[int, str]:
    """Longest run of consecutive integers starting at 1 (1,2,3,...) down a column or along a row.
    31 = a full day axis; 12 = possibly a month axis; 36 = dekads; 366/365 = day of year."""
    best, where = 0, ""
    nr = len(rows)
    nc = max((len(r) for r in rows), default=0)
    # columns (first 40 columns)
    for c in range(min(nc, 40)):
        run = 0
        for r in range(nr):
            v, k = rows[r][c] if c < len(rows[r]) else (None, "")
            if k == "n" and v == run + 1:
                run += 1
                if run > best:
                    best, where = run, f"col{c}"
            elif k == "n" and v == 1:
                run = 1
            elif k == "":
                continue  # blank rows inside an axis are tolerated
            else:
                run = 0
    # rows (first 60 rows)
    for r in range(min(nr, 60)):
        run = 0
        for c, (v, k) in enumerate(rows[r]):
            if k == "n" and v == run + 1:
                run += 1
                if run > best:
                    best, where = run, f"row{r}"
            elif k == "n" and v == 1:
                run = 1
            elif k == "":
                continue
            else:
                run = 0
    return best, where


def features(g: SheetGrid) -> dict:
    rows = g.rows
    nr = len(rows)
    nc = max((len(r) for r in rows), default=0)
    n_num = n_str = n_date = 0
    year_cells = []           # numeric cells holding an integer 1850..2030
    text_years = set()        # years mentioned inside text cells
    months_seen = set()
    kw = set()
    dates = []
    num_vals = []
    last_row = last_col = -1
    for r, row in enumerate(rows):
        for c, (v, k) in enumerate(row):
            if not k:
                continue
            last_row, last_col = max(last_row, r), max(last_col, c)
            if k == "n":
                n_num += 1
                num_vals.append(v)
                if float(v).is_integer() and 1850 <= v <= 2030:
                    year_cells.append(int(v))
            elif k == "d":
                n_date += 1
                dates.append(v)
            elif k == "s":
                n_str += 1
                s = v.strip()
                for y in YEAR_RE.findall(s):
                    text_years.add(int(y))
                up = re.sub(r"[^A-Z ]", " ", s.upper())
                for tok in up.split():
                    if tok in TOKEN_TO_MONTH:
                        months_seen.add(TOKEN_TO_MONTH[tok])
                low = " " + s.lower() + " "
                for w in KEYWORDS:
                    if (len(w) <= 3 and re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low)) or (len(w) > 3 and w in low):
                        kw.add(w.strip())
    run, run_where = find_day_runs(rows)
    # header text: first 15 non-empty rows, cells joined
    head = []
    for row in rows:
        cells = [fmt(v) for v, k in row[:30] if k]
        if cells:
            head.append(" | ".join(cells))
        if len(head) >= 15:
            break
    sheet_years = sorted(set(int(y) for y in YEAR_RE.findall(g.name)))
    return dict(
        sheet=g.name, state=g.state, nrows=nr, ncols=nc, used_rows=last_row + 1, used_cols=last_col + 1,
        n_num=n_num, n_str=n_str, n_date=n_date,
        num_min=f"{min(num_vals):.6g}" if num_vals else "", num_max=f"{max(num_vals):.6g}" if num_vals else "",
        n_year_cells=len(year_cells),
        year_cell_min=min(year_cells) if year_cells else "", year_cell_max=max(year_cells) if year_cells else "",
        year_cell_distinct=len(set(year_cells)),
        text_years=";".join(map(str, sorted(text_years)))[:300],
        sheetname_years=";".join(map(str, sheet_years)),
        date_min=min(dates).isoformat()[:10] if dates else "", date_max=max(dates).isoformat()[:10] if dates else "",
        months_named=len(months_seen), day_run=run, day_run_where=run_where,
        keywords=";".join(sorted(kw)), header=" // ".join(head)[:1500],
    )


def dump_workbook(label: str, sheets: list[SheetGrid]) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)[:180]
    p = DUMP / f"{safe}.txt"
    with p.open("w", encoding="utf-8") as f:
        f.write(f"# WORKBOOK {label}\n")
        for g in sheets:
            f.write(f"\n## SHEET {g.name!r} state={g.state} rows={len(g.rows)}\n")
            for r, row in enumerate(g.rows):
                cells = [fmt(v) for v, k in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    f.write(f"r{r}\t" + "\t".join(cells) + "\n")
    return p


def open_any(data: bytes, name: str) -> tuple[str, list[SheetGrid] | None]:
    m = magic(data)
    try:
        if m == "OLE":
            return "ok-xls", read_xls(data)
        if m == "ZIP":
            return "ok-xlsx", read_xlsx(data)
        # text / HTML saved with an Excel extension
        return f"not-excel {m}", None
    except xlrd.biffh.XLRDError as e:
        msg = str(e)
        return ("protected" if "encrypt" in msg.lower() else f"error: {msg[:120]}"), None
    except Exception as e:
        return f"error: {type(e).__name__}: {str(e)[:120]}", None


def main() -> None:
    DUMP.mkdir(parents=True, exist_ok=True)
    file_rows, sheet_rows = [], []
    targets = []  # (label, container, member, bytes-loader)
    all_files = sorted(p for p in ROOT.rglob("*") if p.is_file())
    for p in all_files:
        rel = p.relative_to(ROOT).as_posix()
        if p.name.startswith("_") and p.parent == ROOT:
            continue  # derived tables written by the pipeline tools, not source data
        ext = p.suffix.lower()
        if ext in EXCEL_EXT:
            targets.append((rel, rel, "", p.read_bytes))
        elif ext == ".zip":
            with zipfile.ZipFile(p) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    mext = Path(info.filename).suffix.lower()
                    file_rows.append(dict(label=f"{rel}!{info.filename}", container=rel, member=info.filename,
                                          size=info.file_size, md5="", magic="", status="zip-member-listed",
                                          crc=f"{info.CRC:08x}", n_sheets="", zip_date="%04d-%02d-%02d" % info.date_time[:3]))
                    if mext in EXCEL_EXT:
                        targets.append((f"{rel}!{info.filename}", rel, info.filename,
                                        (lambda pp=p, nm=info.filename: zipfile.ZipFile(pp).read(nm))))
        else:
            b = p.read_bytes()
            file_rows.append(dict(label=rel, container=rel, member="", size=len(b), md5=md5_bytes(b),
                                  magic=magic(b[:16]), status=f"non-excel {ext or '(none)'}", crc="", n_sheets="",
                                  zip_date=""))
    print(f"excel targets: {len(targets)}", flush=True)
    for i, (label, container, member, loader) in enumerate(targets, 1):
        data = loader()
        status, sheets = open_any(data, label)
        fr = dict(label=label, container=container, member=member, size=len(data), md5=md5_bytes(data),
                  magic=magic(data[:16]), status=status, crc="", n_sheets=len(sheets) if sheets else "", zip_date="")
        if member:  # replace the listing row for this member with the opened one
            file_rows = [r for r in file_rows if r["label"] != label]
        file_rows.append(fr)
        if sheets:
            dump_workbook(label, sheets)
            for g in sheets:
                f = features(g)
                sheet_rows.append(dict(label=label, **f))
        if i % 50 == 0:
            print(f"  {i}/{len(targets)}", flush=True)
    with (OUT / "files.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(file_rows[0].keys()))
        w.writeheader(); w.writerows(file_rows)
    with (OUT / "sheets.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sheet_rows[0].keys()))
        w.writeheader(); w.writerows(sheet_rows)
    from collections import Counter
    st = Counter(r["status"].split(":")[0] for r in file_rows)
    print("files/members by status:", dict(st))
    print("worksheets:", len(sheet_rows))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
