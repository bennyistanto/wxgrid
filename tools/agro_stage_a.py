"""Stage A: run the generalised agro sheet parser over every agro-layout file in Data Stasiun
and save raw records with file/sheet provenance. Identity is NOT resolved here.

Run: python tools/agro_stage_a.py
Writes F:/temp/station/additional-sources/_agro_raw_records.csv.gz and _agro_raw_sheets.csv
"""
import re
import sys
from pathlib import Path

import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers.agro_sheets import parse_sheet, year_from_name  # noqa: E402

ROOT = Path("F:/temp/station/additional-sources/Data Stasiun")
OUT = ROOT.parent
LED = pd.read_csv(OUT / "_ledger_data_stasiun_final.csv")
files = LED[LED["category"].isin(["agro-daily", "agro-variant"])]["file"].tolist()


recs, sheets = [], []
for f in files:
    wb = xlrd.open_workbook(str(ROOT / f), on_demand=True)
    # a file with one data sheet is a one-year file (052X-77, LNRNG-73, MAROS91); a multi-sheet
    # file is a compilation whose name is a range (BDB77-94, MRA80&81), so its name gives no year
    n_data_sheets = sum(1 for i in range(wb.nsheets) if wb.sheet_by_index(i).nrows >= 5)
    fy = year_from_name(f.split("/")[-1]) if n_data_sheets == 1 else None
    for si, sn in enumerate(wb.sheet_names()):
        sh = wb.sheet_by_index(si)
        hint = year_from_name(sn) or fy   # == year_hint(file, sheet, n_data_sheets)
        df, meta = parse_sheet(sh, wb.datemode, year_hint=hint)
        row = dict(file=f, sheet=sn, nrows=sh.nrows, file_year=fy, sheet_year=year_from_name(sn))
        if df is None:
            row.update(status="skip", reason=meta)
        else:
            v = meta["coord_votes"][0] if meta["coord_votes"] else None
            row.update(status="ok", year=meta["year"], layout=meta["layout"], name_cell=meta["name_cell"],
                       kab_cell=meta["kab_cell"], n_values=len(df),
                       n_days=df["date"].nunique(), vars=",".join(sorted(df["var"].unique())),
                       unmapped=",".join(meta["unmapped"]), notes="; ".join(meta["notes"]),
                       n_oob=meta["n_out_of_bounds"], n_dup_dates=meta["n_dup_dates"],
                       year_cell=meta.get("year_cell"), year_hint=meta.get("year_hint"),
                       lat_vote=str(v["lat"]) if v else "", lon_vote=str(v["lon"]) if v else "")
            recs.append(df.assign(file=f, sheet=sn))
        sheets.append(row)
    wb.release_resources()

S = pd.DataFrame(sheets)
R = pd.concat(recs, ignore_index=True)
S.to_csv(OUT / "_agro_raw_sheets.csv", index=False)
R.to_csv(OUT / "_agro_raw_records.csv.gz", index=False)
ok = S[S["status"] == "ok"]
print("files:", len(files), "| sheets:", len(S), "| parsed:", len(ok), "| skipped:", int((S["status"] == "skip").sum()))
print("skip reasons:", S[S["status"] == "skip"]["reason"].value_counts().to_dict())
print("layouts:", ok["layout"].value_counts().to_dict())
print("records:", len(R), "| by var:", R["var"].value_counts().to_dict())
print("files with zero parsed sheets:", sorted(set(files) - set(ok["file"])))
print("sheets with notes:", ok[ok["notes"].fillna("") != ""]["notes"].value_counts().head(10).to_dict())
print("unmapped labels:", ok["unmapped"].fillna("").str.split(",").explode().value_counts().drop("", errors="ignore").to_dict())
print("sheets with repeated dates:", int((ok["n_dup_dates"] > 0).sum()), "| total repeated dates:", int(ok["n_dup_dates"].sum()))
print("year conflicts (Tahun cell vs file/sheet name):", int(ok["notes"].fillna("").str.contains("year conflict").sum()))
print("year distribution:", ok["year"].value_counts().sort_index().to_dict())

# station identity from folder / file-name prefix (ledger) and coordinate votes in degrees
import ast  # noqa: E402
from wxgrid.readers.agro_sheets import coord_from_vote  # noqa: E402
F = pd.read_csv(OUT / "_ledger_data_stasiun_final.csv")[["file", "station"]]
SC = S.merge(F, on="file", how="left")


def _conv(v):
    if not isinstance(v, str) or not v:
        return None
    try:
        return coord_from_vote(ast.literal_eval(v))
    except Exception:
        return None


SC["lat"] = SC["lat_vote"].map(_conv)
SC["lon"] = SC["lon_vote"].map(_conv)
SC.to_csv(OUT / "_agro_raw_sheets_coords.csv", index=False)
print("wrote _agro_raw_sheets_coords.csv")
