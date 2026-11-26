"""Per-file ledger for F:/temp/station/additional-sources/Data Stasiun: every file, what it
holds, whether the agro reader extracts it, how many daily values per variable, and which
other files carry the same station-days. Read-only on the source folder.

Run: python tools/ledger_data_stasiun.py
Writes: F:/temp/station/additional-sources/_ledger_data_stasiun.csv
        F:/temp/station/additional-sources/_ledger_data_stasiun_overlap.csv
"""
import contextlib
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers import agro_grid  # noqa: E402

ROOT = Path("F:/temp/station/additional-sources/Data Stasiun")
OUT = ROOT.parent
VARS = ["RR", "TX", "TN", "TG", "HU", "HU07", "HU13", "RA", "EV", "SS", "FG"]
BBOX = [90, -15, 145, 12]


def snippet(sh, rows=4, cols=10):
    out = []
    for r in range(min(rows, sh.nrows)):
        cells = [str(sh.cell_value(r, c)).strip()[:12] for c in range(min(cols, sh.ncols))]
        cells = [c for c in cells if c]
        if cells:
            out.append(" | ".join(cells))
    return " // ".join(out)[:300]


rows, keys = [], {}
for f in sorted(ROOT.rglob("*")):
    if not f.is_file():
        continue
    rel = f.relative_to(ROOT).as_posix()
    rec = dict(file=rel, folder=rel.split("/")[0] if "/" in rel else "(root)",
               size_kb=round(f.stat().st_size / 1024), ext=f.suffix.upper().lstrip("."))
    if rec["ext"] == "ZIP":
        with zipfile.ZipFile(f) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
        rec.update(status="zip", n_sheets=len(names), layout="archive",
                   note=f"{len(names)} members; e.g. {', '.join(names[:4])}")
        rows.append(rec); continue
    if rec["ext"] == "CSV":
        txt = f.read_text(errors="replace").splitlines()
        rec.update(status="ok", n_sheets=1, layout="csv", note=" // ".join(txt[:4])[:300])
        rows.append(rec); continue
    try:
        wb = xlrd.open_workbook(str(f), on_demand=True)
    except Exception as e:
        rec.update(status="protected" if "encrypt" in str(e).lower() else "error", note=str(e)[:120])
        rows.append(rec); continue
    names = wb.sheet_names()
    sh0 = wb.sheet_by_index(0)
    rec.update(status="ok", n_sheets=len(names), sheets=", ".join(names[:6]) + (" ..." if len(names) > 6 else ""),
               note=snippet(sh0))
    wb.release_resources()
    # what the production agro reader extracts from this one file
    src = dict(name="agro", path=str(f.parent), glob=f.name, station_namespace="agro", network="ledger")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            st, se, ob = agro_grid.read(src, BBOX)
    except Exception as e:
        st, se, ob = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        rec["reader_error"] = str(e)[:120]
    if len(se):
        rec["layout"] = "agro-daily"
        rec["station"] = "; ".join(st["name"].astype(str))
        rec["lat"] = "; ".join(st["lat"].astype(str)); rec["lon"] = "; ".join(st["lon"].astype(str))
        rec["first"] = str(pd.to_datetime(se["first"]).min().date()); rec["last"] = str(pd.to_datetime(se["last"]).max().date())
        ob = ob.assign(var=ob["series_id"].str.split(":").str[-1],
                       stn=ob["series_id"].str.split(":").str[1])
        for v in VARS:
            rec[v] = int((ob["var"] == v).sum())
        rec["values_total"] = int(len(ob))
        keys[rel] = set(zip(ob["stn"], ob["date"].astype(str), ob["var"]))
    else:
        rec["layout"] = "not-agro"
    rows.append(rec)

led = pd.DataFrame(rows)
for v in VARS + ["values_total"]:
    if v not in led:
        led[v] = 0
    led[v] = led[v].fillna(0).astype(int)

# overlap: share of each file's station-day-values that also appear in another file
ov = []
files = list(keys)
for i, a in enumerate(files):
    best, best_n = "", 0
    for b in files:
        if a == b:
            continue
        n = len(keys[a] & keys[b])
        if n > best_n:
            best, best_n = b, n
    share = best_n / len(keys[a]) if keys[a] else 0
    led.loc[led["file"] == a, "overlaps_most_with"] = best
    led.loc[led["file"] == a, "overlap_share"] = round(share, 3)
    ov.append(dict(file=a, other=best, shared=best_n, share=round(share, 3)))

led.to_csv(OUT / "_ledger_data_stasiun.csv", index=False)
pd.DataFrame(ov).to_csv(OUT / "_ledger_data_stasiun_overlap.csv", index=False)

print("files:", len(led))
print(led.groupby(["folder"]).agg(files=("file", "size"), agro=("layout", lambda s: int((s == "agro-daily").sum())),
                                  values=("values_total", "sum")).to_string())
print("\nby status/layout:")
print(led.groupby(["status", "layout"], dropna=False).size().to_string())
