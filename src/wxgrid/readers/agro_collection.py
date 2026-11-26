"""Reader for the whole agro-climate collection in `Data Stasiun` (findings F53-F56).

Inputs (paths in the source config):
  catalogue_csv   station -> lat, lon, elev, coordinate source, flag, wmo_id   (tools/agro_catalogue.py)
  resolution_csv  (file, sheet) -> station, year, status                    (tools/agro_resolve.py)
  ledger_csv      file -> category                                           (tools/ledger_classify.py)
  conflict_winners  {"Station YYYY": "file"} where a fingerprint picked a version (F56)

Steps:
  1. agro-layout sheets (agro_sheets.parse_sheet) placed by the resolution table; sheets marked
     "unresolved" are left out;
  2. long-format files (agro_long), Maumere MAU*, Flores grids, Bekasi grids, the Bandung
     forms and the Jakenan radiation matrix (agro_misc);
  3. per sheet and month, columns swapped against physics are put back (Tmax < Tmin on most
     days; RH07 < RH13 on >= 80% of days), flagged *_swapped_in_source;
  4. one value per station-day-variable: values that agree are merged; disagreements take the
     fingerprint winner for that station-year, else the METKLIM per-year file (user decision
     2026-10-08), else the first source, and are flagged "source_conflict".
Undated files (JAKENAN.XLS, 052X-ACC, LRNG81.CSV) only duplicate dated data (F56) and are
not read; SIKKA.XLS has no locatable station and is not read.
"""
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox
from .agro_long import parse_long_sheet
from .agro_misc import (parse_bmg_forms, parse_day_month_grid, parse_day_year_grid, parse_mau,
                        parse_radiation_matrix)
from .agro_sheets import parse_sheet, year_hint

LONG_FILES = {"KAMBARA.XLS": "Kambara", "METKLIM/BENKEL.XLS": "Bengkel"}
GRID_FILES = {"FLORES/WMILOK90.XLS": ("Watumilok", [1990]), "FLORES/WMILOK91.XLS": ("Watumilok", [1991]),
              "FLORES/WBL90-91.XLS": ("Wairbleler", [1990, 1991]), "FLORES/MPA-9091.XLS": ("Magepanda", [1990, 1991])}
BEKASI = {"32H99b": "Pondokbalas", "32H96a": "Rawamerta"}


def _kind(f):
    return "metklim" if f.startswith("METKLIM/") else "other"


def _fix_swaps(df):
    """Per month, put back Tmax/Tmin and RH07/RH13 that are swapped against physics."""
    if df.empty:
        return df
    df = df.copy()
    df["ym"] = df["date"].dt.to_period("M")
    for a, b, thr, flag in (("TX", "TN", 0.5, "tx_tn_swapped_in_source"),
                            ("HU07", "HU13", 0.8, "rh07_rh13_swapped_in_source")):
        p = df[df["var"].isin([a, b])].pivot_table(index="date", columns="var", values="value", aggfunc="first")
        if a not in p or b not in p:
            continue
        both = p.dropna(subset=[a, b])
        bad = (both[a] < both[b]).groupby(both.index.to_period("M")).mean()
        months = set(bad[bad > thr].index)
        if months:
            m = df["ym"].isin(months) & df["var"].isin([a, b])
            df.loc[m, "var"] = df.loc[m, "var"].map({a: b, b: a})
            df.loc[m, "flag"] = (df.loc[m, "flag"].fillna("") + ";" + flag).str.strip(";")
    return df.drop(columns="ym")


def _resolve(all_recs, winners):
    """One value per station-date-var under the conflict rule."""
    R = all_recs.dropna(subset=["value"]).copy()
    unm = all_recs[all_recs["value"].isna()]
    R["sy"] = R["station"] + " " + R["date"].dt.year.astype(str)
    R["win"] = [winners.get(sy) == f for sy, f in zip(R["sy"], R["file"])]
    R["met"] = R["file"].map(_kind) == "metklim"
    R = R.sort_values(["win", "met"], ascending=False, kind="stable")
    g = R.groupby(["station", "date", "var"])
    spread = g["value"].transform("max") - g["value"].transform("min")
    first = R[~R.duplicated(["station", "date", "var"])].copy()
    conflict = (spread > 1e-6).groupby([R["station"], R["date"], R["var"]]).any()
    key = list(zip(first["station"], first["date"], first["var"]))
    first["flag"] = [((fl + ";") if fl else "") + "source_conflict" if conflict.get(k, False) else fl
                     for fl, k in zip(first["flag"].fillna(""), key)]
    nsrc = g["file"].nunique()
    first["n_sources"] = [int(nsrc.get(k, 1)) for k in key]
    # unmeasurable (trace) markers survive only where no numeric value exists
    unm = unm[~unm.set_index(["station", "date", "var"]).index.isin(first.set_index(["station", "date", "var"]).index)]
    unm = unm.drop_duplicates(["station", "date", "var"]).assign(n_sources=1)
    return pd.concat([first.drop(columns=["sy", "win", "met"]), unm], ignore_index=True)


def read(src, bbox):
    root = Path(src["path"])
    cat = pd.read_csv(src["catalogue_csv"]).set_index("station")
    res = pd.read_csv(src["resolution_csv"]).set_index(["file", "sheet"])
    led = pd.read_csv(src["ledger_csv"])
    winners = src.get("conflict_winners", {}) or {}
    ns = src.get("station_namespace", src["name"])
    chunks, report = [], dict(sheets_used=0, sheets_unresolved=0, sheets_unplaced=0)

    # 1. agro-layout sheets
    for f in led[led["category"].isin(["agro-daily", "agro-variant"])]["file"]:
        wb = xlrd.open_workbook(str(root / f), on_demand=True)
        n_data = sum(1 for i in range(wb.nsheets) if wb.sheet_by_index(i).nrows >= 5)
        for si, sn in enumerate(wb.sheet_names()):
            sh = wb.sheet_by_index(si)
            df, meta = parse_sheet(sh, wb.datemode, year_hint=year_hint(f.split("/")[-1], sn, n_data))
            if df is None:
                continue
            if (f, sn) not in res.index:
                report["sheets_unplaced"] += 1
                continue
            r = res.loc[(f, sn)]
            if r["status"] == "unresolved" or pd.isna(r["station"]):
                report["sheets_unresolved"] += 1
                continue
            shift = int(r["year"]) - int(r["parsed_year"])
            if shift:
                df["date"] = df["date"] + pd.DateOffset(years=shift)
            chunks.append(_fix_swaps(df).assign(station=r["station"], file=f, sheet=sn))
            report["sheets_used"] += 1
        wb.release_resources()

    # 2. other layouts
    def first_sheet(f):
        wb = xlrd.open_workbook(str(root / f))
        return wb, next(wb.sheet_by_index(i) for i in range(wb.nsheets) if wb.sheet_by_index(i).nrows > 4)

    longs = dict(LONG_FILES)
    for x in os.listdir(root / "METKLIM"):
        if re.match(r"(MNG|MUNENG)", x.upper()):
            longs["METKLIM/" + x] = "Muneng"
    for f, st in longs.items():
        wb, sh = first_sheet(f)
        df, _ = parse_long_sheet(sh, wb.datemode)
        if df is not None:
            chunks.append(_fix_swaps(df).assign(station=st, file=f, sheet=sh.name))
    for x in sorted(os.listdir(root / "FLORES")):
        if x.upper().startswith("MAU") and x[3:7].isdigit():
            f = "FLORES/" + x
            wb, sh = first_sheet(f)
            df, _ = parse_mau(sh, 1900 + int(x[3:5]))
            if df is not None:
                chunks.append(_fix_swaps(df).assign(station="Maumere", file=f, sheet=sh.name))
    for f, (st, yrs) in GRID_FILES.items():
        wb, sh = first_sheet(f)
        df, _ = parse_day_month_grid(sh, yrs)
        if df is not None:
            chunks.append(df.assign(station=st, file=f, sheet=sh.name))
    wb = xlrd.open_workbook(str(root / "BEKASI/H-319996.XLS"))
    for i in range(wb.nsheets):
        sh = wb.sheet_by_index(i)
        if sh.name in BEKASI:
            df, _ = parse_day_year_grid(sh)
            if df is not None:
                chunks.append(df.assign(station=BEKASI[sh.name], file="BEKASI/H-319996.XLS", sheet=sh.name))
    wb = xlrd.open_workbook(str(root / "BMG-JKT/BMG8194.XLS"))
    for i in range(wb.nsheets):
        df, _ = parse_bmg_forms(wb.sheet_by_index(i))
        if df is not None:
            chunks.append(_fix_swaps(df).assign(station="Bandung (BMG-Jakarta file)", file="BMG-JKT/BMG8194.XLS",
                                               sheet=wb.sheet_by_index(i).name))
    sh = xlrd.open_workbook(str(root / "JAKENAN1.XLS")).sheet_by_index(0)
    years = [int(sh.cell_value(0, c)) for c in range(sh.ncols) if isinstance(sh.cell_value(0, c), float)]
    df, _ = parse_radiation_matrix(sh, years, src.get("jakenan_leap_rule", {}))
    if df is not None:
        chunks.append(df.assign(station="Jakenan", file="JAKENAN1.XLS", sheet=sh.name))

    allr = pd.concat(chunks, ignore_index=True)
    final = _resolve(allr, winners)
    report["values_in"] = int(allr["value"].notna().sum())
    report["values_out"] = int(len(final))
    report["source_conflict"] = int(final["flag"].fillna("").str.contains("source_conflict").sum())

    stations, series, obs = [], [], []
    for st, g in final.groupby("station"):
        if st not in cat.index:
            continue
        c = cat.loc[st]
        if pd.isna(c["lat"]) or not in_bbox(c["lat"], c["lon"], bbox):
            continue
        key = re.sub(r"[^A-Z0-9]", "", st.split(" (")[0].upper())
        skey = f"{ns}:{key}"
        wmo = c.get("wmo_id") if "wmo_id" in c and pd.notna(c.get("wmo_id")) else ""
        stations.append(dict(station_key=skey, source=ns, network=src.get("network", ""), source_station_id=key,
                             name=st, lat=float(c["lat"]), lon=float(c["lon"]),
                             elev_m=float(c["elev_m"]) if pd.notna(c.get("elev_m")) else np.nan,
                             country=src.get("country", "ID"), wmo_id=str(int(wmo)) if wmo != "" else ""))
        for var, gv in g.groupby("var"):
            gv = gv.sort_values("date")
            sid = f"{src['name']}:{key}:{var}"
            series.append(dict(series_id=sid, station_key=skey, source=src["name"], variable=var, units="",
                               day_convention=src.get("day_convention", ""), n_values=int(gv["value"].notna().sum()),
                               n_missing_code=0, n_unparsed=0, first=gv["date"].min(), last=gv["date"].max(),
                               note=f"{st}; coords: {c['coord_source']}" + (f" [{c['flag']}]" if pd.notna(c.get('flag')) and c.get('flag') else "")))
            obs.append(pd.DataFrame({"series_id": sid, "date": gv["date"].values, "value": gv["value"].values,
                                     "flag": gv["flag"].fillna("").values}))
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series; {report}")
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
