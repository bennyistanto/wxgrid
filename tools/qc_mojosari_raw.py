"""QC agro:MOJOSARI, raw layer: every sheet that the agro reader files under Mojosari.

Read-only on the raw workbooks. For each (file, sheet) in the agro resolution table with
station Mojosari:
  1. raw CH cell inventory: numeric (zero / positive), blank, dash, other text, large values
     (>= 300, e.g. 8888, 9999), decimals; header metadata (Kabupaten, No. Sta, Elevasi) and
     coordinate votes;
  2. row layout: day rows per month vs the calendar (missing or extra day rows inside a month
     shift every later value of that month by one day if the clerk skipped or repeated a row);
  3. versions of the same year (MJS73-94.XLS sheet vs METKLIM/175A-YY.XLS vs ALIST) compared
     at day shifts -3..+3 (fraction of equal values on common wet days);
  4. which version the compiled series (date_raw) holds.
Dates come from the project parser (wxgrid.readers.agro_sheets.parse_sheet), so they are the
dates the build uses.
Writes F:/temp/station/qc_mojosari/raw_*.csv. Run: python tools/qc_mojosari_raw.py
"""
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd
import xlrd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from wxgrid.readers.agro_sheets import norm, parse_sheet, year_hint  # noqa: E402

ROOT = "F:/temp/station/additional-sources/Data Stasiun"
RES = "F:/temp/station/additional-sources/_agro_sheet_resolution.csv"
OUT = "F:/temp/station/qc_mojosari"
COMP = "F:/temp/station/compiled"
os.makedirs(OUT + "/cache", exist_ok=True)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300); pd.set_option("display.max_columns", 40)

res = pd.read_csv(RES)
res = res[res.station == "Mojosari"]


def ch_column(sh):
    hrow = next(r for r in range(min(4, sh.nrows))
                if any("LINTANG" in str(sh.cell_value(r, c)).upper() for c in range(sh.ncols)))
    for r in (hrow, hrow + 1, hrow + 2):
        for c in range(sh.ncols):
            if norm(sh.cell_value(r, c)) == "CH":
                return hrow, r, c
    return hrow, None, None


inv, layout, versions = [], [], {}
for (f, sn), r in res.set_index(["file", "sheet"]).iterrows():
    wb = xlrd.open_workbook(os.path.join(ROOT, f))
    sh = wb.sheet_by_name(sn)
    n_data = sum(1 for i in range(wb.nsheets) if wb.sheet_by_index(i).nrows >= 5)
    df, meta = parse_sheet(sh, wb.datemode, year_hint=year_hint(f.split("/")[-1], sn, n_data))
    if df is None:
        print("unparsed", f, sn, meta); continue
    shift = int(r["year"]) - int(r["parsed_year"])
    if shift:
        df["date"] = df["date"] + pd.DateOffset(years=shift)
    rr = df[df["var"] == "RR"].set_index("date")["value"]
    versions[(f, sn, int(r["year"]))] = rr
    hrow, vrow, c = ch_column(sh)
    cells = Counter(); big = Counter(); text = Counter(); dec = 0; pos = []
    first = vrow + 1
    while first < sh.nrows and not isinstance(sh.cell_value(first, c), float) and str(sh.cell_value(first, c)).strip() in ("", "mm"):
        first += 1
    for rr_ in range(first, sh.nrows):
        v = sh.cell_value(rr_, c)
        t = sh.cell_type(rr_, c)
        if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) or (isinstance(v, str) and not v.strip()):
            cells["blank"] += 1
        elif isinstance(v, float):
            if v == 0:
                cells["zero"] += 1
            elif v > 0:
                cells["positive"] += 1; pos.append(v)
                if v % 1:
                    dec += 1
                if v >= 300:
                    big[v] += 1
            else:
                cells["negative"] += 1
        else:
            s = str(v).strip()
            cells["dash" if s == "-" else "text"] += 1
            if s != "-":
                text[s] += 1
    hdr = {}
    for lab in ("Kabupaten", "No.", "Sta.", "Elevasi"):
        for cc in range(sh.ncols):
            if norm(sh.cell_value(hrow, cc)).startswith(norm(lab)):
                vv = next((sh.cell_value(x, cc) for x in range(hrow + 1, min(hrow + 5, sh.nrows))
                           if str(sh.cell_value(x, cc)).strip()), "")
                hdr[lab] = str(vv).strip()
                break
    votes = meta.get("coord_votes", [])
    inv.append(dict(file=f, sheet=sn, year=int(r["year"]), rows_parsed=len(rr), n_value=int(rr.notna().sum()),
                    **{k: cells.get(k, 0) for k in ["zero", "positive", "blank", "dash", "text", "negative"]},
                    decimals=dec, big=dict(big) or "", text_codes=dict(text) or "",
                    max=max(pos) if pos else np.nan, kab=hdr.get("Kabupaten"),
                    no=str(hdr.get("No.", "")) + str(hdr.get("Sta.", "")),
                    elev=hdr.get("Elevasi"), coord_votes=str(Counter(map(str, votes)).most_common(2)),
                    notes="; ".join(meta.get("notes", []))))
    idx = pd.DatetimeIndex(rr.index)
    yr = int(r["year"])
    for m in range(1, 13):
        dm = pd.Period(f"{yr}-{m:02d}").days_in_month
        got = idx[idx.month == m]
        if len(got) != dm:
            missing = sorted(set(range(1, dm + 1)) - set(got.day))
            layout.append(dict(file=f, sheet=sn, year=yr, month=m, rows=len(got), days_in_month=dm,
                               missing_days=" ".join(map(str, missing))))

INV = pd.DataFrame(inv).sort_values(["year", "file"])
INV.to_csv(f"{OUT}/raw_sheet_inventory.csv", index=False)
print("=== raw CH cells per sheet (data rows) ===")
print(INV.drop(columns=["notes"]).to_string(index=False))
print("\nnotes:")
for a in INV.itertuples():
    if a.notes:
        print(" ", a.file, a.sheet, a.notes)
L = pd.DataFrame(layout)
L.to_csv(f"{OUT}/raw_month_layout.csv", index=False)
print("\n=== months whose parsed day rows differ from the calendar ===")
print(L.to_string(index=False) if len(L) else "none")

rows = []
for yr in sorted({k[2] for k in versions}):
    ks = [k for k in versions if k[2] == yr]
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            a, b = versions[ks[i]], versions[ks[j]]
            rec = dict(year=yr, a=f"{ks[i][0]}[{ks[i][1]}]", b=f"{ks[j][0]}[{ks[j][1]}]")
            for k in range(-3, 4):
                bb = b.copy(); bb.index = bb.index - pd.Timedelta(days=k)   # b day D+k vs a day D
                jn = pd.concat([a, bb], axis=1, keys=["a", "b"]).dropna()
                jw = jn[(jn.a > 0) | (jn.b > 0)]
                rec[f"eq{k:+d}"] = round(float((jw.a == jw.b).mean()), 3) if len(jw) else np.nan
            rec["n_common"] = int(len(pd.concat([a, b], axis=1).dropna()))
            rows.append(rec)
V = pd.DataFrame(rows)
V.to_csv(f"{OUT}/raw_version_compare.csv", index=False)
print("\n=== same-year versions: fraction equal on common wet days, b day D+k vs a day D ===")
print(V.to_string(index=False))

it = pd.read_csv(f"{COMP}/observations_RR.csv.gz", chunksize=2_000_000, parse_dates=["date", "date_raw"])
o = pd.concat([c[c.series_id == "agro:MOJOSARI:RR"] for c in it])
o.to_pickle(f"{OUT}/cache/obs_agro_mojosari.pkl")
comp = o.set_index("date_raw").value
print("\ncompiled agro:MOJOSARI:RR rows", len(o), "flags:", o.flag.fillna("").value_counts().to_dict(),
      "labels:", o.label.fillna("").value_counts().to_dict())
rows = []
for (f, sn, yr), s in versions.items():
    c = comp[str(yr)]
    j = pd.concat([c, s], axis=1, keys=["c", "s"]).dropna()
    rows.append(dict(year=yr, version=f"{f}[{sn}]", n=len(j), equal=round(float((j.c == j.s).mean()), 3) if len(j) else np.nan))
W = pd.DataFrame(rows).sort_values(["year", "version"])
W.to_csv(f"{OUT}/raw_compiled_vs_version.csv", index=False)
print("\n=== compiled (date_raw) vs each version, fraction equal ===")
print(W.to_string(index=False))
sc = o[o.flag.fillna("").str.contains("source_conflict")]
print("\nsource_conflict days by year:", sc.date_raw.dt.year.value_counts().sort_index().to_dict())
pd.to_pickle(versions, f"{OUT}/cache/raw_versions.pkl")   # {(file, sheet, year): RR series by parsed date}

# context of the raw "*" and "ND" cells and of values >= 150 (MJS73-94.XLS and METKLIM)
rows = []
for (f, sn), r in res.set_index(["file", "sheet"]).iterrows():
    if f.startswith("ALIST"):
        continue
    wb = xlrd.open_workbook(os.path.join(ROOT, f)); sh = wb.sheet_by_name(sn)
    hrow, vrow, c = ch_column(sh)
    col = [sh.cell_value(x, c) for x in range(vrow + 1, sh.nrows)]
    for i, v in enumerate(col):
        if isinstance(v, str) and v.strip() in ("*", "ND"):
            nxt = next((x for x in col[i + 1:] if not (isinstance(x, str))), None)
            if i == 0 or not (isinstance(col[i - 1], str) and col[i - 1].strip() == v.strip()):
                run = 1
                while i + run < len(col) and isinstance(col[i + run], str) and col[i + run].strip() == v.strip():
                    run += 1
                rows.append(dict(file=f, sheet=sn, year=int(r["year"]), row=vrow + 1 + i, code=v.strip(), run=run,
                                 prev=col[i - 1] if i else None, next_value=nxt))
S = pd.DataFrame(rows)
S.to_csv(f"{OUT}/raw_code_runs.csv", index=False)
print("\n=== runs of '*' / 'ND' cells in the CH column (value after the run) ===")
print(S.to_string(index=False))
