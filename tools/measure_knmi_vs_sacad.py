"""Does SACA&D already hold the KNMI Dutch-era daily rainfall (F28)? Measured before any KNMI reader is written.

Reads the daily KNMI workbooks in F:/temp/station/knmi/ (read-only):
  station-month rows x day columns: `CH  sumatra.xls`, `CH 1898-1907.xls` (Sheet1), `CH Jawa.xls` (one sheet per station)
  per-year sheets with station blocks of day rows x month columns (Jan-Jul, day, Aug-Dec): `Sumatera 1880-1897.xls`
Cell coding (F28): number = mm; "-" = dry (Java sheets); "n.w." / "Geen waarnemingen..." = missing; blank = dry or missing
(not decidable from the cell). Only days with rain > 0 are compared, so the blank question does not affect the match.

For every KNMI station, every SACA&D RR series in the compiled observations (sacad_nonblend, sacad2013_extra; date_raw,
before 1950) is compared on the KNMI rain days at lags -1, 0, +1: share of those days where SACA&D has a value, and share
where it equals the KNMI value within 0.5 mm. The best series is the one with the most equal days.
Output: F:/temp/station/knmi_measure/knmi_daily.csv.gz, knmi_vs_sacad.csv and a printed table.
Usage: python tools/measure_knmi_vs_sacad.py
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

sys.stdout.reconfigure(encoding="utf-8")
D = Path("F:/temp/station/knmi")
OUT = Path("F:/temp/station/knmi_measure")
C = Path("F:/temp/station/compiled")
MONTHS = {m: i + 1 for i, m in enumerate(["januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
                                          "september", "oktober", "november", "desember"])}
MISSING = ("n.w", "geen waarnemingen")


def cell(v):
    """-> (value, code): value in mm, 0.0 for '-', None for blank or missing."""
    if isinstance(v, (int, float)) and v != "":
        return float(v), "num"
    s = str(v).strip().lower().replace("`", "")
    if s == "":
        return None, "blank"
    if s.startswith(MISSING):
        return None, "missing"
    if s.strip("-") == "":
        return 0.0, "dash"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\D?", s)
    if m:
        return float(m.group(1)), "num_text"
    return None, "other"


def month_of(v):
    return MONTHS.get(str(v).strip().lower()[:9].rstrip(), MONTHS.get(str(v).strip().lower()))


def station_month_rows(path, sheets=None):
    wb = xlrd.open_workbook(str(path))
    for sh in wb.sheets():
        if sheets and sh.name not in sheets:
            continue
        hdr = next((r for r in range(min(5, sh.nrows)) if str(sh.cell_value(r, 1)).strip().lower() == "stasiun"), None)
        if hdr is None or sh.ncols < 38:
            continue
        name = year = None
        for r in range(hdr + 1, sh.nrows):
            if str(sh.cell_value(r, 1)).strip():
                name = str(sh.cell_value(r, 1)).strip()
            y = sh.cell_value(r, 5)
            if isinstance(y, float) and 1800 < y < 2000:
                year = int(y)
            mo = month_of(sh.cell_value(r, 6))
            if not (name and year and mo):
                continue
            for d in range(1, 32):
                v, code = cell(sh.cell_value(r, 6 + d))
                yield path.name, sh.name, name, year, mo, d, v, code


def sumatera_blocks(path):
    wb = xlrd.open_workbook(str(path))
    for sh in wb.sheets():
        try:
            year = int(float(sh.cell_value(0, 0)))
        except ValueError:
            continue
        name = None
        for r in range(sh.nrows):
            if str(sh.cell_value(r, 6)).strip().lower() == "januari":
                name = str(sh.cell_value(r, 1)).strip()
                continue
            day = sh.cell_value(r, 5)
            if not (name and isinstance(day, float) and 1 <= day <= 31):
                continue
            for k, col in enumerate(list(range(6, 13)) + list(range(14, 19))):
                v, code = cell(sh.cell_value(r, col))
                yield path.name, sh.name, name, year, k + 1, int(day), v, code


def load_knmi():
    rows = list(station_month_rows(D / "CH  sumatra.xls")) + list(station_month_rows(D / "CH 1898-1907.xls", {"Sheet1"})) \
        + list(station_month_rows(D / "CH Jawa.xls")) + list(sumatera_blocks(D / "Sumatera 1880-1897.xls"))
    k = pd.DataFrame(rows, columns=["file", "sheet", "station", "year", "month", "day", "value", "code"])
    k["date"] = pd.to_datetime(dict(year=k.year, month=k.month, day=k.day), errors="coerce")
    return k[k.date.notna()]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    k = load_knmi()
    k.to_csv(OUT / "knmi_daily.csv.gz", index=False)
    k["skey"] = k.file + "|" + k.station
    print(f"KNMI daily cells {len(k):,}; codes {k.code.value_counts().to_dict()}")
    print(f"stations {k.skey.nunique()} ({k.station.nunique()} names); years {k.year.min()}-{k.year.max()}; rain days > 0: {(k.value > 0).sum():,}")
    wet = k[k.value > 0]
    # SACA&D series before 1950
    se = pd.read_csv(C / "series.csv.gz", usecols=["series_id", "station_key", "source", "variable"])
    se = se[(se.variable == "RR") & se.source.isin(["sacad_nonblend", "sacad2013_extra"])]
    st = pd.read_csv(C / "stations.csv.gz", usecols=["station_key", "name", "lat", "lon"]).set_index("station_key")
    ob = pd.concat(c[c.series_id.isin(se.series_id) & (c.date_raw < "1950-01-01")]
                   for c in pd.read_csv(C / "observations_RR.csv.gz", usecols=["series_id", "date_raw", "value"], chunksize=3_000_000))
    ob["date_raw"] = pd.to_datetime(ob.date_raw)
    sv = {sid: g.dropna(subset=["value"]).drop_duplicates("date_raw").set_index("date_raw").value for sid, g in ob.groupby("series_id")}
    print(f"SACA&D RR series with values before 1950: {len(sv)}")
    rows = []
    for key, g in wet.groupby("skey"):
        x = g.drop_duplicates("date").set_index("date").value
        best = None
        for sid, s in sv.items():
            if s.index.max() < x.index.min() or s.index.min() > x.index.max():
                continue
            for L in (-1, 0, 1):
                y = s.reindex(x.index + pd.Timedelta(days=L))
                have = y.notna().to_numpy()
                if have.sum() < 30:
                    continue
                eq = (np.abs(y.to_numpy()[have] - x.to_numpy()[have]) <= 0.5).sum()
                if best is None or eq > best[3]:
                    best = (sid, L, int(have.sum()), int(eq))
        sk = se.set_index("series_id").station_key.get(best[0]) if best else None
        rows.append(dict(knmi_station=key, n_rain_days=len(x), first=x.index.min().date(), last=x.index.max().date(),
                         sacad_series=best[0] if best else "", sacad_name=st.name.get(sk, "") if sk else "",
                         lag=best[1] if best else np.nan, sacad_has_value=best[2] if best else 0, equal=best[3] if best else 0))
    r = pd.DataFrame(rows)
    r["share_held"] = (r.sacad_has_value / r.n_rain_days).round(3)
    r["share_equal"] = (r.equal / r.n_rain_days).round(3)
    r["verdict"] = np.select([r.share_equal >= 0.8, r.share_equal >= 0.3], ["in SACA&D", "partly in SACA&D"], "not in SACA&D")
    r.sort_values("share_equal", ascending=False).to_csv(OUT / "knmi_vs_sacad.csv", index=False)
    pd.set_option("display.width", 250)
    print(r.sort_values("share_equal", ascending=False).to_string(index=False, max_colwidth=40))
    print("\nverdict:", r.verdict.value_counts().to_dict())
    print("rain days by verdict:", r.groupby("verdict").n_rain_days.sum().to_dict())
    not_in = r[r.verdict != "in SACA&D"]
    print(f"KNMI rain days not matched by SACA&D: {(not_in.n_rain_days - not_in.equal).sum():,} of {r.n_rain_days.sum():,}")


if __name__ == "__main__":
    main()
