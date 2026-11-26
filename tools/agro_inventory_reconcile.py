"""Stage E: reconcile the collection's own inventory (ALIST/LIST.XLS, status per station-year
as cell fill colour) with what the agro_collection reader extracts.

Legend (LIST.XLS rows 30-31): pink = SUDAH SELESAI (done), lavender = DATA TIDAK ADA (no data),
light yellow = DATA BELUM DIISI (not entered), cyan = DATA BELUM SELESAI (not finished).
Run: python tools/agro_inventory_reconcile.py -> _agro_inventory_reconcile.csv
"""
import sys
from pathlib import Path

import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid import config  # noqa: E402
from wxgrid.readers import READERS  # noqa: E402

B = Path("F:/temp/station/additional-sources")
wb = xlrd.open_workbook(str(B / "Data Stasiun/ALIST/LIST.XLS"), formatting_info=True)
sh = wb.sheet_by_index(0)
LEG = {45: "done", 46: "no data", 26: "not entered", 15: "not finished"}
years = {c: 1900 + int(sh.cell_value(2, c)) for c in range(2, sh.ncols) if isinstance(sh.cell_value(2, c), float)}
inv = []
for r in range(3, 30):
    st = str(sh.cell_value(r, 1)).strip()
    for c, y in years.items():
        idx = wb.xf_list[sh.cell_xf_index(r, c)].background.pattern_colour_index
        inv.append(dict(station=st, year=y, status=LEG.get(idx, f"colour {idx}")))
I = pd.DataFrame(inv)
I["station"] = I["station"].replace({"Gunungmedan": "Gunungmedan"})

c = config.load(str(Path(__file__).resolve().parents[1] / "configs/idn_bmkg_sacad.yaml"))
s = [x for x in c["sources"] if x["name"] == "agro"][0]
st, se, ob = READERS[s["reader"]](s, c["domain"]["bbox"])
ob["var"] = ob["series_id"].str.split(":").str[-1]
ob["key"] = ob["series_id"].str.split(":").str[1]
rr = ob[(ob["var"] == "RR") & ob["value"].notna()]
names = st.set_index("source_station_id")["name"].to_dict()
got = rr.groupby([rr["key"].map(names), pd.to_datetime(rr["date"]).dt.year]).size().rename("rr_days").reset_index()
got.columns = ["station", "year", "rr_days"]
M = I.merge(got, on=["station", "year"], how="left").fillna({"rr_days": 0})
M["have"] = pd.cut(M["rr_days"], [-1, 0, 299, 400], labels=["none", "partial", "full"])
M.to_csv(B / "_agro_inventory_reconcile.csv", index=False)
print("inventory station-years:", len(M))
print(pd.crosstab(M["status"], M["have"], margins=True).to_string())
miss = M[(M["status"] == "done") & (M["have"] == "none")]
print("\n'done' in the inventory but no rainfall extracted:", len(miss))
print(miss.groupby("station")["year"].apply(lambda s: ",".join(str(y)[2:] for y in sorted(s))).to_string())
extra = M[(M["status"].isin(["no data", "not entered"])) & (M["have"] == "full")]
print("\nmarked 'no data' / 'not entered' but a full year extracted:", len(extra))
print(extra.groupby("station")["year"].apply(lambda s: ",".join(str(y)[2:] for y in sorted(s))).to_string())
