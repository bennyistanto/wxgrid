"""Are the candidate sets copies of each other? (plan assumption A5)

Read-only, over the recheck dumps (F:/temp/station/additional_recheck/dump). Pairs tested:
  1. INDRAMAYU I/<post>.xls day x year grid sheet  vs  <POST>/<post>_harian*.xls date series
  2. CH_IND/kompilasi_hujan1990-2001.xls  vs  the CH_IND year files 1990..2001.xls
  3. JATIM Mjr*/Pdk* decade files  vs  the plain decade files of the same post
  4. _SUMBAR/Data Sumbar.XLS MONTHLY  vs  CH_IND/m_rainfall wset sumatera.xls (sheet with the same layout)
For each pair: days (or months) present in both, share with equal values (|diff| <= 0.05),
and days present in only one side.
Output: F:/temp/station/additional_recheck/duplicates_*.csv and a printed summary.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from measure_dash_semantics import DUMP, OUT, cls, month_of, parse_patrol, sheets, val  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def compare(a: pd.Series, b: pd.Series, what: str) -> dict:
    a, b = a.dropna(), b.dropna()
    both = a.index.intersection(b.index)
    eq = (np.abs(a[both] - b[both]) <= 0.05)
    return dict(pair=what, n_a=len(a), n_b=len(b), both=len(both), equal_share=round(float(eq.mean()), 4) if len(both) else np.nan,
                only_a=len(a.index.difference(b.index)), only_b=len(b.index.difference(a.index)))


def harian_series(fn) -> pd.Series:
    """Date-indexed CH from a *_harian file: header row with 'CH'; date cells 'D:yyyy-mm-dd'."""
    out = {}
    for sh, rows in sheets(fn):
        chcol = None
        for r in sorted(rows):
            c = rows[r]
            if chcol is None:
                u = [v.strip().upper() for v in c]
                if "CH" in u:
                    chcol = u.index("CH")
                continue
            dc = next((i for i, v in enumerate(c) if v.startswith("D:")), None)
            if dc is None or chcol >= len(c):
                continue
            x = val(c[chcol])
            if not np.isnan(x):
                out[pd.Timestamp(c[dc][2:12])] = x
    return pd.Series(out, dtype=float).sort_index()


def grid_series(fn) -> pd.Series:
    recs, _ = parse_patrol("g", fn)
    d = pd.DataFrame(recs, columns=["s", "p", "year", "month", "day", "raw"])
    d["date"] = pd.to_datetime(dict(year=d.year, month=d.month, day=d.day), errors="coerce")
    d["v"] = d.raw.map(val)
    d = d.dropna(subset=["date", "v"])
    return d.groupby("date").v.first()


def station_month_rows(fn, year_hint=None) -> pd.Series:
    """(name, date) -> value from NOSTA | STA | TAHUN | BULAN | R1..R31 sheets."""
    out = {}
    for sh, rows in sheets(fn):
        hdr = next((r for r in sorted(rows)[:5] if any(v.strip().upper() in ("R1", "TGL1") for v in rows[r])), None)
        if hdr is None:
            continue
        h = [v.strip().upper() for v in rows[hdr]]
        try:
            r1 = h.index("R1")
        except ValueError:
            continue
        yc = next(i for i, v in enumerate(h) if v in ("TAHUN", "YEAR"))
        mc = next(i for i, v in enumerate(h) if v in ("BULAN", "MONTH"))
        sc = next((i for i, v in enumerate(h) if v in ("STA", "NOMOR")), 1)
        for r in sorted(rows):
            if r <= hdr:
                continue
            c = rows[r] + [""] * 40
            try:
                y, m = int(float(c[yc])), int(float(c[mc]))
            except ValueError:
                continue
            y = y + 1900 if y < 100 else y
            name = c[sc].strip().upper()
            for k in range(31):
                x = val(c[r1 + k])
                if not np.isnan(x):
                    try:
                        out[(name, pd.Timestamp(y, m, k + 1))] = x
                    except ValueError:
                        pass
    return pd.Series(out, dtype=float)


def main():
    res = []
    # 1. Indramayu
    pairs = [("BANGKIR", "BANGKIR", "BANGKIR_harian_66-02"), ("BONDAN", "BONDAN", "BONDAN_harian_79-02"),
             ("BULAK-KH", "BULAK", "BULAK_harian_70-02"), ("CIKEDUNG", "CIKEDUNG", "CIKEDUNG_harian_66-02"),
             ("Cidempet", "CIDEMPET", "CIDEMPET_harian_71-02"), ("INDRAMAYU", "INDRAMAYU", "INDRAMAYU_harian_79-02"),
             ("JATIBARANG", "JATIBARANG", "JATIBARANG_harian_79-02"), ("Juntinyuat_2", "JUNTINYUAT", "JUNTINYUAT_harian_79-02"),
             ("KEDOKAN_BUNDER", "KEDOKAN_BUNDER", "KEDOKAN_BUNDER_harian_79-02"), ("Krangkeng", "KRANGKENG", "KRANGKENG_harian_79-02"),
             ("LOHBENER", "RENTANG_LOHBENER", "RENTANG_LOHBENER_harian_79-02"), ("Losarang", "LOSARANG", "losarang_harian"),
             ("SUKA-DANA_2", "SUKADANA", "SUKADANA_harian_79-02"), ("SUMUR-WATU_2", "SUMURWATU", "Sumurwatu_harian"),
             ("Sudikampiran", "SUDIKAMPIRAN", "SUDIKAMPIRAN_harian_79-02"), ("Sudimampir_Lor", "SUDIMAMPIR", "SUDIMAMPIR_harian_79-02"),
             ("Tugu", "TUGU", "TUGU_harian_71-02"), ("ujungaris_2", "PANGAUBAN", "Ujungaris_harian")]
    for g, folder, h in pairs:
        fg = f"DATA_IKLIM_INDRAMAYU_I_{g}.xls.txt"
        fh = f"DATA_IKLIM_{folder}_{h}.xls.txt"
        if not (DUMP / fg).exists() or not (DUMP / fh).exists():
            res.append(dict(pair=f"Indramayu {g}", n_a=np.nan, note=f"missing dump {fg if not (DUMP / fg).exists() else fh}"))
            continue
        res.append(compare(grid_series(fg), harian_series(fh), f"Indramayu grid {g} vs {h}"))
    # 2. kompilasi vs year files
    k = station_month_rows("DATA_IKLIM_CH_IND_kompilasi_hujan1990-2001.xls.txt")
    yrs = pd.concat([station_month_rows(f"DATA_IKLIM_CH_IND_{y}.{ext}.txt")
                     for y, ext in [(1990, "xls"), (1991, "xls"), (1992, "xls"), (1993, "xls"), (1994, "xls"),
                                    (1995, "XLS"), (1996, "xls"), (1997, "xls"), (1998, "XLS"), (1999, "xls"),
                                    (2000, "xls"), (2001, "xls")]])
    yrs = yrs[~yrs.index.duplicated()]
    res.append(compare(k, yrs, "kompilasi_hujan1990-2001 vs CH_IND year files (name, date)"))
    # 3. JATIM prefixed copies (sheets are years; compare all day cells of the 10 year sheets)
    for a, b in [("DATA_CH_JATIM_MOJOKERTO_Mojosari_MjrMojosari00-09.xls.txt", "DATA_CH_JATIM_MOJOKERTO_Mojosari_Mojosari00-09.xls.txt"),
                 ("DATA_CH_JATIM_MOJOKERTO_PUDAKSARI_PdkPudaksari00-09.xls.txt", "DATA_CH_JATIM_MOJOKERTO_PUDAKSARI_Pudaksari00-09.xls.txt")]:
        ca = {(s, r, i): v for s, rows in sheets(a) for r, c in rows.items() for i, v in enumerate(c)}
        cb = {(s, r, i): v for s, rows in sheets(b) for r, c in rows.items() for i, v in enumerate(c)}
        keys = set(ca) | set(cb)
        same = sum(ca.get(x, "") == cb.get(x, "") for x in keys)
        res.append(dict(pair=f"{a.split('_')[-1]} vs {b.split('_')[-1]} (all cells)", both=len(keys),
                        equal_share=round(same / len(keys), 4)))
    # 4. Sumbar monthly
    def sumbar(fn, sheet):
        out = {}
        for s, rows in sheets(fn):
            if s != sheet:
                continue
            for r, c in rows.items():
                c = c + [""] * 20
                if re.fullmatch(r"(19|20)\d\d", c[5].strip()):
                    for m in range(12):
                        x = val(c[6 + m])
                        if not np.isnan(x):
                            out[(c[0].strip().upper(), int(c[5]), m + 1)] = x
        return pd.Series(out, dtype=float)
    sb = sumbar("DATA_IKLIM__SUMBAR_Data_Sumbar.XLS.txt", "MONTHLY")
    mw = None
    for s, rows in sheets("DATA_IKLIM_CH_IND_m_rainfall_wset_sumatera.xls.txt"):
        if any("Latitude" in v for v in rows.get(min(rows), [])):
            mw = sumbar("DATA_IKLIM_CH_IND_m_rainfall_wset_sumatera.xls.txt", s)
            break
    if mw is not None:
        res.append(compare(sb, mw, "Data Sumbar MONTHLY vs m_rainfall wset sumatera (station, year, month)"))
    r = pd.DataFrame(res)
    r.to_csv(OUT / "duplicates_additional.csv", index=False)
    pd.set_option("display.width", 220)
    print(r.to_string(index=False))


if __name__ == "__main__":
    main()
