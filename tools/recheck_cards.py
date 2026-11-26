"""Print compact cards per workbook for labels starting with a prefix.

Sheets of one workbook that share a layout (first header rows with digits masked) are
collapsed into one card listing every sheet name and the years found, so nothing is hidden
but repeated per-year sheets take one line.

Usage: python tools/recheck_cards.py "<label prefix>" [header chars]
Reads F:/temp/station/additional_recheck/sheets_axes.csv.
"""
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
pref = sys.argv[1]
w = int(sys.argv[2]) if len(sys.argv) > 2 else 300
m = pd.read_csv("F:/temp/station/additional_recheck/sheets_axes.csv", dtype=str, keep_default_na=False)
m = m[m.label.str.startswith(pref)]


def sig(h: str) -> str:
    parts = h.split(" // ")[:4]
    return re.sub(r"\d+", "#", " // ".join(parts))[:160]


def years(r) -> str:
    out = []
    if r.year_axis:
        out.append(f"Y{r.y0}-{r.y1}(n{r.ny}@{r.year_axis})")
    if r.text_year:
        out.append(f"t{r.text_year}")
    if r.sheetname_years:
        out.append(f"s{r.sheetname_years}")
    return ",".join(out)


for label, g in m.groupby("label", sort=True):
    empty = g[(g.n_num == "0") & (g.n_str == "0") & (g.n_date == "0")]
    full = g.drop(empty.index)
    print(f"\n=== {label}  sheets={len(g)} empty={len(empty)}")
    full = full.assign(sig=full.header.map(sig))
    for s, gg in full.groupby("sig", sort=False):
        r = gg.iloc[0]
        ax = []
        if r.month_axis:
            ax.append(f"M@{r.month_axis}")
        if r.month_col_1_12:
            ax.append(f"m1-12@{r.month_col_1_12}")
        if r.day_run not in ("", "0", "1"):
            ax.append(f"D{r.day_run}@{r.day_run_where}")
        if r.date_min:
            ax.append(f"dates {r.date_min}..{r.date_max} step{r.date_step_days}")
        num = sum(int(x) for x in gg.n_num)
        numt = sum(int(float(x)) for x in gg.n_numtext)
        dash = sum(int(x) for x in gg.n_dash)
        names = ", ".join(f"{a}{'' if b == 'visible' else '(' + b + ')'}" for a, b in zip(gg.sheet, gg.state))
        ys = "; ".join(sorted(set(years(x) for x in gg.itertuples()) - {""}))
        print(f"  [{len(gg)} sheet(s): {names[:400]}]")
        print(f"     size~{r.used_rows}x{r.used_cols} num={num} numtext={numt} dash={dash} | {' '.join(ax)} | {ys[:300]}")
        print(f"     {r.header[:w]}")
