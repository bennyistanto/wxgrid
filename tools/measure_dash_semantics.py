"""What does "-" mean in the not-yet-read daily rain-post forms? (plan assumption A1)

Read-only measurement over the recheck dumps (F:/temp/station/additional_recheck/dump).
For each source it parses the day cells and classifies them: positive number, zero, dash
("-"), X, blank, other text. It then measures three kinds of evidence:

  1. Internal consistency: where the form states a monthly rain-day count (Bajo "J L M H H",
     Batubassi 1994-2003, Sumsel "HARI HJN") or a monthly/dekad total, does it equal the
     count / sum of the positive days alone (dash = dry) or not?
  2. Month structure: share of months that are entirely dash, by calendar month. Dry-season
     all-dash months are plausible dry months; wet-season ones suggest "not reported".
  3. CPC-UNI 0.5 deg (1979+), for posts with coordinates in the form: CPC wet-day fraction
     (>= 1 mm) on positive days, zero days, dash days inside months that have values, and
     dash days inside all-dash months. Lag -1/0/+1 chosen per post by the highest CPC wet
     fraction on positive days.

Forms that carry a legend (Patas, Poh Santen, Peninjauan, Praya: "- : tidak ada hujan";
Batubassi 1976-1993: "- = tidak ada hujan, X = tidak ada data") are measured too, as the
calibration: there dash is known to mean no rain.

Output: F:/temp/station/additional_recheck/dash_semantics_*.csv and a printed summary.
Usage: python tools/measure_dash_semantics.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path("F:/temp/station/additional_recheck")
DUMP = OUT / "dump"
CPC = "F:/temp/station/cpc/idn_cpc_1979_2025.nc"
MONTHS = {"JAN": 1, "PEB": 2, "FEB": 2, "MAR": 3, "MRT": 3, "APR": 4, "APRIL": 4, "MEI": 5, "MAY": 5,
          "JUN": 6, "JUNI": 6, "JUL": 7, "JULI": 7, "AGS": 8, "AGT": 8, "AGU": 8, "AGUST": 8, "AGUSTUS": 8,
          "AUG": 8, "SEP": 9, "SEPT": 9, "OKT": 10, "OCT": 10, "NOP": 11, "NOV": 11, "DES": 12, "DEC": 12,
          "JANUARI": 1, "FEBRUARI": 2, "PEBRUARI": 2, "MARET": 3, "SEPTEMBER": 9, "OKTOBER": 10,
          "NOPEMBER": 11, "NOVEMBER": 11, "DESEMBER": 12}
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
# coordinates as written in the forms (deg, min, sec); S and E
COORDS = {
    "Lelogama": (-(9 + 42 / 60 + 26.9 / 3600), 123 + 57 / 60 + 14.8 / 3600),
    "Oesao": (-(10 + 5 / 60 + 51.1 / 3600), 123 + 50 / 60 + 32.9 / 3600),
    "Patas": (-(8 + 12 / 60 + 44 / 3600), 114 + 47 / 60 + 17 / 3600),
    "Pohsanten": (-(8 + 22 / 60 + 8 / 3600), 114 + 40 / 60 + 20 / 3600),
}


def sheets(fn):
    """Yield (sheet name, {row: [cells]}) from one dump file."""
    name, rows = None, {}
    for line in (DUMP / fn).open(encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("## SHEET "):
            if name is not None:
                yield name, rows
            name = eval(re.match(r"## SHEET (.*) state=", line).group(1))
            rows = {}
        elif line.startswith("r") and "\t" in line:
            r, rest = line.split("\t", 1)
            rows[int(r[1:])] = rest.split("\t")
    if name is not None:
        yield name, rows


def cls(v: str) -> str:
    s = v.strip()
    if s == "":
        return "blank"
    if s in ("-", "--", "_"):
        return "dash"
    if s.upper() == "X":
        return "X"
    if NUM.fullmatch(s):
        return "zero" if float(s.replace(",", ".")) == 0 else "pos"
    return "text"


def val(v):
    s = v.strip()
    return float(s.replace(",", ".")) if NUM.fullmatch(s) else np.nan


def month_of(tok: str):
    return MONTHS.get(re.sub(r"[^A-Z]", "", tok.upper()))


# ---------- parsers: each returns records (source, post, year, month, day, raw) ----------
def parse_day_month_blocks(source, post, fn, year_from_sheet=False):
    """Day rows x month columns under a 'TAHUN : yyyy' (or sheet-name year) block."""
    recs, checks = [], []
    for sh, rows in sheets(fn):
        rr = sorted(rows)
        year = None
        if year_from_sheet and re.fullmatch(r"\s*(19|20)\d\d\s*", sh):
            year = int(sh)
        mcols, i = None, 0
        while i < len(rr):
            cells = rows[rr[i]]
            txt = " ".join(cells)
            m = re.search(r"TAHUN\s*:?\s*((?:19|20)\d\d)", txt, re.I)
            if m:
                year = int(m.group(1))
            mc = {c: month_of(v) for c, v in enumerate(cells) if month_of(v)}
            if len(set(mc.values())) >= 12:
                mcols = mc
                i += 1
                continue
            if mcols and year and cells and re.fullmatch(r"\s*\d{1,2}\s*", cells[0] or "") and 1 <= int(cells[0]) <= 31:
                d = int(cells[0])
                for c, mo in mcols.items():
                    raw = cells[c] if c < len(cells) else ""
                    recs.append((source, post, year, mo, d, raw))
            elif mcols and year and cells and re.match(r"\s*(JUMLAH|JML)", cells[0] or "", re.I):
                checks.append((post, year, rr[i], {mo: (cells[c] if c < len(cells) else "") for c, mo in mcols.items()}))
            i += 1
    return recs, checks


def parse_year_month_rows(source, post, fn):
    """Rows TAHUN | BULAN | 1..31 | JLM CH | RATA | JLM HH ... (Bajo, Batubassi 1994-2003)."""
    recs, checks = [], []
    for sh, rows in sheets(fn):
        hdr = next((r for r in sorted(rows) if len(rows[r]) > 2 and rows[r][0].strip().upper() == "TAHUN"), None)
        if hdr is None:
            continue
        h = rows[hdr]
        dcol = {c: int(v) for c, v in enumerate(h) if re.fullmatch(r"\s*\d{1,2}\s*", v) and 1 <= int(v) <= 31}
        if len(dcol) < 28:  # day numbers on the next row
            h = rows.get(hdr + 1, [])
            dcol = {c: int(v) for c, v in enumerate(h) if re.fullmatch(r"\s*\d{1,2}\s*", v) and 1 <= int(v) <= 31}
        last = max(dcol)
        for r in sorted(rows):
            c = rows[r]
            if len(c) > 2 and re.fullmatch(r"\s*(19|20)\d\d\s*", c[0]) and re.fullmatch(r"\s*\d{1,2}\s*", c[1]):
                y, mo = int(c[0]), int(c[1])
                for col, d in dcol.items():
                    recs.append((source, post, y, mo, d, c[col] if col < len(c) else ""))
                tail = [x for x in c[last + 1:last + 4]]
                checks.append((post, y, mo, tail))  # JLM CH, RATA, JLM HH
    return recs, checks


def parse_sumsel(source, fn):
    """One sheet per year; month blocks titled 'JAN | yyyy'; post rows: No | name | 1..31 | D1 D2 D3 TOTAL | . | HARI HJN."""
    recs, checks = [], []
    for sh, rows in sheets(fn):
        if not re.fullmatch(r"(19|20)\d\d", sh.strip()):
            continue
        year = int(sh)
        month, dcol, hh = None, None, None
        for r in sorted(rows):
            c = rows[r]
            mo = next((month_of(v) for v in c[:4] if month_of(v)), None)
            if mo and any(re.fullmatch(r"(19|20)\d\d", v.strip()) for v in c[:6]):
                month = mo
                continue
            if "HARI HJN" in [v.strip() for v in c]:
                hh = [v.strip() for v in c].index("HARI HJN")
                dcol = {i: int(v) for i, v in enumerate(c) if re.fullmatch(r"\d{1,2}", v.strip()) and i < hh}
                continue
            if month and dcol and len(c) > 3 and re.fullmatch(r"\d{1,3}", c[1].strip()) and c[2].strip():
                post = c[2].strip()
                for i, d in dcol.items():
                    recs.append((source, post, year, month, d, c[i] if i < len(c) else ""))
                checks.append((post, year, month, c[hh] if hh < len(c) else "", c[hh - 2] if hh - 2 < len(c) else ""))
    return recs, checks


def parse_patrol(source, fn):
    """Sheet 'ts days': row of years; 'Jan' marks day 1 of each month down column 0."""
    recs = []
    post = None
    for sh, rows in sheets(fn):
        rr = sorted(rows)
        yr_row = next((r for r in rr[:6] if sum(bool(re.fullmatch(r"(19|20)\d\d", v.strip())) for v in rows[r]) >= 5), None)
        if yr_row is None:
            continue
        post = " ".join(rows[rr[0]]).strip()
        ycol = {c: int(v) for c, v in enumerate(rows[yr_row]) if re.fullmatch(r"(19|20)\d\d", v.strip())}
        month, day = 0, 0
        for r in rr:
            if r <= yr_row:
                continue
            c = rows[r]
            mo = month_of(c[0]) if c else None
            if mo:
                month, day = mo, 1
            elif month and c and re.fullmatch(r"\d{1,2}", c[0].strip()):
                day = int(c[0])
            else:
                continue
            for col, y in ycol.items():
                recs.append((source, post, y, month, day, c[col] if col < len(c) else ""))
        break
    return recs, []


# ---------- run ----------
def main():
    allrecs, chk_rows = [], []
    forms = [("Lelogama", "DATA_IKLIM_BMG_Data_Lelogama_NTT.xls.txt", True, "none"),
             ("Oesao", "DATA_IKLIM_BMG_Data_Oesao_NTT.xls.txt", True, "none"),
             ("Patas", "DATA_IKLIM_BMG_Data_PATAS_Bali.xls.txt", False, "dash=no rain"),
             ("Pohsanten", "DATA_IKLIM_BMG_Data_Pohsanten_Bali.xls.txt", False, "dash=no rain"),
             ("Peninjauan", "DATA_IKLIM_BMG_Data_PENINJAUAN_NTB.xls.txt", False, "dash=no rain"),
             ("Praya", "DATA_IKLIM_BMG_Data_PRAYA_NTB.xls.txt", False, "dash=no rain")]
    legend = {}
    for post, fn, ys, lg in forms:
        r, _ = parse_day_month_blocks("BMG/Data", post, fn, ys)
        allrecs += r
        legend[post] = lg
    for fn in sorted(p.name for p in DUMP.glob("DATA_IKLIM_BMG_Data_batubasih_19[78]*.txt")) + \
            sorted(p.name for p in DUMP.glob("DATA_IKLIM_BMG_Data_batubasih_199[0-3]*.txt")):
        r, _ = parse_day_month_blocks("BMG/Data", "Batubassi", fn, False)
        allrecs += r
    legend["Batubassi"] = "dash=no rain, X=no data"
    for post, fn in [("Bajo", "DATA_IKLIM_BMG_Data_Bajo_Sulsel.xls.txt"),
                     ("Batubassi9403", "DATA_IKLIM_BMG_Data_batubasih_1994_2003.xls.txt")]:
        r, c = parse_year_month_rows("BMG/Data", post, fn)
        allrecs += r
        legend[post] = "none" if post == "Bajo" else "see sheet"
        for (p, y, mo, tail) in c:
            chk_rows.append(dict(source=post, post=p, year=y, month=mo, total=tail[0] if tail else "",
                                 raindays=tail[2] if len(tail) > 2 else ""))
    for reg, fn in [("Banyuasin", "CH_Sumsel_BANYUASIN_BANYUASIN_nopassword.xlsx.txt"),
                    ("Muba", "CH_Sumsel_MUBA_Muba_nopassword.xlsx.txt"), ("OKI", "CH_Sumsel_OKI_OKI_nopassword.xlsx.txt")]:
        r, c = parse_sumsel("Sumsel:" + reg, fn)
        allrecs += r
        for (p, y, mo, hh, tot) in c:
            chk_rows.append(dict(source="Sumsel:" + reg, post=p, year=y, month=mo, total=tot, raindays=hh))
    for fn in sorted(p.name for p in DUMP.glob("DATA_IKLIM_PATROL_PJT_II_*.txt")):
        r, _ = parse_patrol("PATROL", fn)
        allrecs += r
    d = pd.DataFrame(allrecs, columns=["source", "post", "year", "month", "day", "raw"])
    d["cls"] = d.raw.map(cls)
    # drop impossible dates (day 31 in 30-day months etc.) only if blank/dash: keep counts honest
    d["date"] = pd.to_datetime(dict(year=d.year, month=d.month, day=d.day), errors="coerce")
    bad = d.date.isna()
    d["impossible_date"] = bad
    d.to_csv(OUT / "dash_semantics_cells.csv.gz", index=False)

    d["src"] = np.where(d.source.str.startswith("Sumsel"), d.source, np.where(d.source == "PATROL", "PATROL", d.post))
    grp = d[~bad].copy()
    print("== 1. cell classes per source (valid dates only)")
    tab = grp.pivot_table(index="src", columns="cls", values="raw", aggfunc="size", fill_value=0)
    print(tab.to_string())
    print("impossible dates holding a non-blank, non-dash value:",
          int((bad & ~d.cls.isin(["blank", "dash"])).sum()), "of", int(bad.sum()))

    # 2. month structure
    mo = grp.groupby(["src", "post", "year", "month"]).cls.agg(
        n="size", npos=lambda s: (s == "pos").sum(), nzero=lambda s: (s == "zero").sum(),
        ndash=lambda s: (s == "dash").sum(), nX=lambda s: (s == "X").sum(), nblank=lambda s: (s == "blank").sum())
    mo["all_dash"] = mo.ndash == mo.n
    print("\n== 2. share of months entirely dash, by calendar month (%)")
    s = mo.reset_index().groupby(["src", "month"]).all_dash.mean().unstack().mul(100).round(0)
    print(s.to_string())

    # 1b. stated rain days / totals
    if chk_rows:
        c = pd.DataFrame(chk_rows)
        key = grp.groupby(["source", "post", "year", "month"]).agg(
            npos=("cls", lambda s: (s == "pos").sum()), nzero=("cls", lambda s: (s == "zero").sum()),
            ndash=("cls", lambda s: (s == "dash").sum()), sumpos=("raw", lambda s: np.nansum([val(x) for x in s]))).reset_index()
        c["source2"] = c.source.where(c.source.str.startswith("Sumsel"), "BMG/Data")
        c["post2"] = c.post.where(c.source.str.startswith("Sumsel"), c.source)
        j = c.merge(key, left_on=["source2", "post2", "year", "month"], right_on=["source", "post", "year", "month"])
        j["hh"] = j.raindays.map(val)
        j["tot"] = j.total.map(val)
        j = j[j.hh.notna()]
        print("\n== 1b. stated rain days vs counts (months with a stated count)")
        for src, g in j.groupby("source_x"):
            act = g[g.npos + g.nzero > 0]
            print(f"  {src}: months {len(g)}, with any value {len(act)} | "
                  f"rain days == positive count: {(act.hh == act.npos).mean():.1%} | "
                  f"== positive+zero: {(act.hh == act.npos + act.nzero).mean():.1%} | "
                  f"== positive+dash: {(act.hh == act.npos + act.ndash).mean():.1%} | "
                  f"total == sum(values): {(np.isclose(act.tot, act.sumpos, atol=1)).mean():.1%}")
        j.to_csv(OUT / "dash_semantics_raindays.csv", index=False)

    # 1c. row-level rain-day checks where the count sits on the same row or in an HH row
    print("\n== 1c. stated rain days (HH) vs counts, per row or per month block")
    out = []
    # Bajo: each data row is one post-month (several unnamed posts are stacked), JLM HH 3 cells after day 31
    for sh, rows in sheets("DATA_IKLIM_BMG_Data_Bajo_Sulsel.xls.txt"):
        for r in sorted(rows):
            c = rows[r] + [""] * 40
            if re.fullmatch(r"\s*(19|20)\d\d\s*", c[0]):
                days = [cls(v) for v in c[2:33]]
                hh = val(c[35])
                if not np.isnan(hh):
                    out.append(dict(src="Bajo", npos=days.count("pos"), nzero=days.count("zero"),
                                    ndash=days.count("dash"), hh=hh))
    # day x month forms: 'HH' row per year block; counts over the day rows of that block
    for post, fn, ys in [("Lelogama", "DATA_IKLIM_BMG_Data_Lelogama_NTT.xls.txt", True),
                         ("Oesao", "DATA_IKLIM_BMG_Data_Oesao_NTT.xls.txt", True),
                         ("Patas", "DATA_IKLIM_BMG_Data_PATAS_Bali.xls.txt", False),
                         ("Pohsanten", "DATA_IKLIM_BMG_Data_Pohsanten_Bali.xls.txt", False),
                         ("Peninjauan", "DATA_IKLIM_BMG_Data_PENINJAUAN_NTB.xls.txt", False),
                         ("Praya", "DATA_IKLIM_BMG_Data_PRAYA_NTB.xls.txt", False)]:
        for sh, rows in sheets(fn):
            mcols, block = None, {}
            for r in sorted(rows):
                c = rows[r]
                mc = {i: month_of(v) for i, v in enumerate(c) if month_of(v)}
                if len(set(mc.values())) >= 12:
                    mcols, block = mc, {m: [] for m in mc.values()}
                    continue
                if not mcols or not c:
                    continue
                if re.fullmatch(r"\s*\d{1,2}\s*", c[0]) and 1 <= int(c[0]) <= 31:
                    for i, m in mcols.items():
                        block[m].append(cls(c[i]) if i < len(c) else "blank")
                elif re.match(r"\s*(HH|H\.H|HARI HUJAN|JML HARI|BANYAK HARI)", c[0], re.I):
                    for i, m in mcols.items():
                        hh = val(c[i]) if i < len(c) else np.nan
                        b = block.get(m, [])
                        if not np.isnan(hh) and b:
                            out.append(dict(src=post, npos=b.count("pos"), nzero=b.count("zero"),
                                            ndash=b.count("dash"), hh=hh))
                    mcols = None
    o = pd.DataFrame(out)
    if len(o):
        for src, g in o.groupby("src"):
            print(f"  {src}: month rows {len(g)} | HH == positive: {(g.hh == g.npos).mean():.1%} | "
                  f"HH == positive+zero: {(g.hh == g.npos + g.nzero).mean():.1%} | "
                  f"HH == positive+dash: {(g.hh == g.npos + g.ndash).mean():.1%} | "
                  f"months with dash>0 and HH == positive: {((g.ndash > 0) & (g.hh == g.npos)).sum()}/{(g.ndash > 0).sum()}")
        o.to_csv(OUT / "dash_semantics_hh_rows.csv", index=False)

    # 3. CPC
    print("\n== 3. CPC wet fraction (>= 1 mm), 1979+, by cell class (lag chosen per post)")
    cpc = xr.open_dataset(CPC).precip
    rows3 = []
    for post, (lat, lon) in COORDS.items():
        g = grp[(grp.post == post) & (grp.date >= "1979-01-01")].copy()
        if g.empty:
            continue
        ser = cpc.sel(lat=lat, lon=lon, method="nearest").to_series()
        allm = mo.reset_index()
        allm = allm[allm.post == post][["year", "month", "all_dash"]]
        g = g.merge(allm, on=["year", "month"])
        best = None
        for lag in (-1, 0, 1):
            w = ser.reindex(g.date + pd.Timedelta(days=lag)).to_numpy() >= 1
            fr = np.nanmean(w[(g.cls == "pos").to_numpy()])
            if best is None or fr > best[1]:
                best = (lag, fr)
        lag = best[0]
        cp = ser.reindex(g.date + pd.Timedelta(days=lag)).to_numpy()
        g["cpc"] = cp
        g["grp"] = np.where(g.cls == "dash", np.where(g.all_dash, "dash_alldash_month", "dash_in_active_month"), g.cls)
        for k, gg in g[g.cpc.notna()].groupby("grp"):
            rows3.append(dict(post=post, legend=legend.get(post), lag=lag, group=k, n=len(gg),
                              cpc_wet_frac=round(float((gg.cpc >= 1).mean()), 3), cpc_mean_mm=round(float(gg.cpc.mean()), 2)))
    r3 = pd.DataFrame(rows3)
    print(r3.to_string(index=False))
    r3.to_csv(OUT / "dash_semantics_cpc.csv", index=False)
    # all-dash months: CPC monthly total
    print("\n== 3b. CPC monthly total in all-dash months vs months with values (median mm)")
    for post, (lat, lon) in COORDS.items():
        ser = cpc.sel(lat=lat, lon=lon, method="nearest").to_series()
        mon = ser.resample("MS").sum()
        allm = mo.reset_index()
        allm = allm[(allm.post == post) & (allm.year >= 1979)].copy()
        allm["cpc_month"] = [mon.get(pd.Timestamp(int(y), int(m), 1), np.nan) for y, m in zip(allm.year, allm.month)]
        a, b = allm[allm.all_dash], allm[~allm.all_dash]
        wet = allm.month.isin([12, 1, 2, 3])
        print(f"  {post} ({legend.get(post)}): all-dash months {len(a)} median CPC {a.cpc_month.median():.0f} mm "
              f"(Dec-Mar: {int((a.all_dash & wet[a.index]).sum())}, median {a[wet[a.index]].cpc_month.median():.0f} mm) | "
              f"months with values {len(b)} median CPC {b.cpc_month.median():.0f} mm")


if __name__ == "__main__":
    main()
