"""Tests for the post_forms reader (phase-2 rain-post forms, F57 cell coding)."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxgrid.readers import post_forms  # noqa: E402

BBOX = [90, -15, 145, 12]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MEI", "JUN", "JUL", "AGUST", "SEP", "OKT", "NOP", "DES"]


def _catalogue(tmp_path, source, keys):
    rows = [dict(source=source, post_key=k, name=k, lat=-8.5, lon=116.0, elev=10, coord_source="test") for k in keys]
    p = tmp_path / "cat.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)


def test_coder_follows_measured_conventions():
    c = post_forms.Coder({"dash_value": 0.0, "zero_is_trace": True, "missing_text": ["X", "R"],
                          "missing_codes": [999], "unmeasurable_codes": [888]}, 2000)
    assert c(" - ")[:2] == (0.0, "")                 # dash = dry day
    v, f, _ = c(0.0)
    assert pd.isna(v) and f == "unmeasurable"        # 0 = trace rain day
    assert c("X")[0] is None and c("r")[0] is None   # no data
    assert c(999.0)[0] is None                       # missing code
    assert c(888.0)[1] == "unmeasurable"
    assert c("12,5")[0] == 12.5                      # number stored as text
    assert c(2500.0)[2] == "out_of_range"
    assert c("TTU")[2] == "unparsed"               # not listed: counted, no row


def test_coder_unmeasurable_text():
    # TTU / TU = "Tidak Terukur" = 8888 (user 2026-11-25, F63)
    c = post_forms.Coder({"missing_text": ["X"], "unmeasurable_text": ["TTU", "TU"]}, 2000)
    for raw in ("TTU", "ttu.", " TU "):
        v, f, k = c(raw)
        assert pd.isna(v) and f == "unmeasurable" and k == "unmeasurable_text"
    assert c("X")[2] == "missing_text"


def test_month_labels():
    assert [post_forms.month_of(m) for m in ("JAN", "Peb", "Agust", "Januari", "DESEMBER", "JUMLAH", "Desa", "TGL")] == \
        [1, 2, 8, 1, 12, None, None, None]


class _Sheet:
    """xlwt-like write(r, c, v) on an openpyxl sheet (xlwt is not installed here)."""

    def __init__(self, ws):
        self.ws = ws

    def write(self, r, c, v):
        self.ws.cell(r + 1, c + 1, v)


def _book(title):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = title
    return wb, _Sheet(wb.active)


def test_day_month_blocks_and_dash_month(tmp_path):
    wb, sh = _book("71 - 72")
    r = 0
    for year in (1971, 1972):
        sh.write(r, 0, f"Tahun     :  {year}")
        r += 1
        sh.write(r, 0, "Tanggal")
        for c, m in enumerate(MONTHS, 1):
            sh.write(r, c, m)
        r += 1
        for d in range(1, 32):
            sh.write(r, 0, d)
            for c in range(1, 13):
                if year == 1971 and c == 1:
                    sh.write(r, c, 5.0 if d == 1 else (0.0 if d == 2 else ("X" if d == 3 else "-")))
                else:
                    sh.write(r, c, "-")        # every other month entirely "-"
            r += 1
        sh.write(r, 0, "HH")
        r += 2
    f = tmp_path / "form.xlsx"
    wb.save(f)
    src = {"name": "t", "catalogue_csv": _catalogue(tmp_path, "t", ["P1"]),
           "codes": {"dash_value": 0.0, "zero_is_trace": True, "missing_text": ["X"]},
           "books": [{"post_key": "P1", "layout": "day_month", "path": str(f)}]}
    st, se, ob = post_forms.read(src, BBOX)
    ob["date"] = pd.to_datetime(ob["date"])
    one = lambda d: ob[ob.date == d].iloc[0]
    assert one("1971-01-01").value == 5.0 and one("1971-01-01").flag == ""
    assert pd.isna(one("1971-01-02").value) and one("1971-01-02").flag == "unmeasurable"
    assert (ob.date == "1971-01-03").sum() == 0                     # X = no data
    assert one("1971-01-04").value == 0.0 and one("1971-01-04").flag == ""   # dash in an active month
    assert one("1971-02-10").flag == "dash_month"                    # month entirely "-"
    assert (ob.date == "1971-02-30").sum() == 0 and ob.date.dt.year.max() == 1972
    assert int(se.n_missing_code.iloc[0]) == 1


def test_dash_month_missing_drops_unreported_months(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2005"
    for mi, m in enumerate(("JAN", "FEB")):
        base = 1 + mi * 6
        ws.cell(base, 2, m); ws.cell(base, 3, 2005)
        ws.cell(base + 1, 2, "NO"); ws.cell(base + 1, 3, "LOKASI POS")
        for d in range(1, 32):
            ws.cell(base + 2, 3 + d, d)
        ws.cell(base + 2, 3 + 36, "HARI HJN")
        ws.cell(base + 3, 2, 1); ws.cell(base + 3, 3, "Post A")
        for d in range(1, 32):
            ws.cell(base + 3, 3 + d, (7 if d == 1 else "-") if m == "JAN" else "-")
    f = tmp_path / "s.xlsx"
    wb.save(f)
    src = {"name": "t", "catalogue_csv": _catalogue(tmp_path, "t", ["D|Post A"]),
           "codes": {"dash_value": 0.0, "zero_is_trace": True, "dash_month": "missing"},
           "books": [{"post_prefix": "D|", "layout": "post_rows", "path": str(f)}]}
    st, se, ob = post_forms.read(src, BBOX)
    ob["date"] = pd.to_datetime(ob["date"])
    assert ob.date.dt.month.unique().tolist() == [1]                 # February (all "-") dropped
    assert len(ob) == 31 and ob[ob.date == "2005-01-01"].value.iloc[0] == 7
    assert int(se.n_missing_code.iloc[0]) == 28


def test_station_month_rows_codes_and_keys(tmp_path):
    wb, sh = _book("x")
    for c, h in enumerate(["Nosta", "Sta", "Year", "Month"] + [f"R{d}" for d in range(1, 32)]):
        sh.write(0, c, h)
    row = ["43F", "Bandar Buat", 1991, 2, 3.0, 999.0, 888.0] + [0.0] * 25 + [4.0, 4.0, 4.0]
    for c, v in enumerate(row):
        sh.write(1, c, v)
    f = tmp_path / "d.xlsx"
    wb.save(f)
    src = {"name": "t", "catalogue_csv": _catalogue(tmp_path, "t", ["43F|Bandar Buat"]),
           "codes": {"missing_codes": [999], "unmeasurable_codes": [888]},
           "books": [{"post_key": "", "layout": "station_month_rows", "path": str(f)}]}
    st, se, ob = post_forms.read(src, BBOX)
    ob["date"] = pd.to_datetime(ob["date"])
    assert st.source_station_id.tolist() == ["43F|Bandar Buat"]
    assert ob[ob.date == "1991-02-01"].value.iloc[0] == 3.0
    assert (ob.date == "1991-02-02").sum() == 0                      # 999 missing
    assert ob[ob.date == "1991-02-03"].flag.iloc[0] == "unmeasurable"
    assert ob.date.max() == pd.Timestamp("1991-02-28")              # 29-31 Feb not dated
    assert int(se.n_unparsed.iloc[0]) == 3                           # values on impossible dates counted


def test_dash_month_ignores_blank_days_and_counts_bbox_and_wmo(tmp_path):
    wb, sh = _book("2002")
    sh.write(0, 0, "Tahun : 2002")
    sh.write(1, 0, "TGL")
    for c, m in enumerate(MONTHS, 1):
        sh.write(1, c, m)
    for d in range(1, 32):
        sh.write(1 + d, 0, d)
        for c in range(1, 13):
            if c == 1:
                sh.write(1 + d, c, 3.0)
            elif c == 10:
                sh.write(1 + d, c, "-" if d <= 23 else None)   # October: 23 "-" then blank
            else:
                sh.write(1 + d, c, "-")
    f = tmp_path / "f.xlsx"
    wb.save(f)
    cat = pd.DataFrame([dict(source="t", post_key="P1", name="P1", lat=-8.5, lon=116.0, elev=1, coord_source="x"),
                        dict(source="t", post_key="FAR", name="FAR", lat=-91.0, lon=101.3, elev=1, coord_source="x")])
    cat.to_csv(tmp_path / "c.csv", index=False)
    src = {"name": "t", "catalogue_csv": str(tmp_path / "c.csv"),
           "codes": {"dash_value": 0.0, "zero_is_trace": True},
           "books": [{"post_key": "P1", "layout": "day_month", "path": str(f)},
                     {"post_key": "FAR", "layout": "day_month", "path": str(f)}]}
    st, se, ob = post_forms.read(src, BBOX)
    ob["date"] = pd.to_datetime(ob["date"])
    octo = ob[(ob.date.dt.month == 10)]
    assert len(octo) == 23 and (octo.flag == "dash_month").all()     # blanks do not break the month
    assert st.station_key.tolist() == ["t:P1"]                         # lat -91 rejected, not silently
    assert post_forms.WMO_RE.fullmatch("96167") and not post_forms.WMO_RE.fullmatch("43F")
