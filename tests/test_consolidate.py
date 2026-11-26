"""Unit tests for consolidation pieces that can fail silently. Run: python -m pytest tests"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxgrid.consolidate import crosswalk, flags  # noqa: E402
from wxgrid.readers import bmkg_xlsx, sacad_zip  # noqa: E402


def _rain(n=800, seed=0):
    rng = np.random.default_rng(seed)
    v = np.where(rng.random(n) < 0.4, rng.gamma(0.8, 15, n), 0.0)
    return pd.Series(v, index=pd.date_range("2000-01-01", periods=n, freq="D"))


def test_pair_stats_detects_one_day_label_shift():
    a = _rain()
    b = a.copy()
    b.index = b.index - pd.Timedelta(days=1)  # b labels each day one day earlier
    row = crosswalk.summarise(crosswalk.pair_stats(a, b, [-1, 0, 1], 0.05))
    assert row["best_lag"] == 1
    assert row["equal_frac_best"] == 1.0
    assert row["r_lag0"] < 0.3


def test_identical_series_pass():
    a = _rain()
    row = crosswalk.summarise(crosswalk.pair_stats(a, a.copy(), [-1, 0, 1], 0.05))
    assert row["best_lag"] == 0 and crosswalk.passes(row, {"r_min": 0.8})


def test_sites_refuse_two_stations_of_one_provider():
    s = crosswalk._Sites(["bmkg:1", "bmkg:2", "sacad:9"], {"bmkg:1": "bmkg", "bmkg:2": "bmkg", "sacad:9": "sacad"})
    assert s.union("bmkg:1", "sacad:9")
    assert not s.union("bmkg:2", "sacad:9")
    assert s.find("bmkg:2") != s.find("bmkg:1")


def test_flags_stack_and_keep_values():
    obs = pd.DataFrame({"series_id": ["x"] * 3, "date": pd.date_range("2000-01-01", periods=3),
                        "value": [-1.0, 10.0, 900.0], "flag": ["src_suspect", "", ""]})
    series = pd.DataFrame({"series_id": ["x"], "variable": ["RR"]})
    out = flags.apply_bounds(obs, series, {"RR": [0, 500]})
    assert out["flag"].tolist() == ["src_suspect;below_min", "", "above_max"]
    assert out["value"].tolist() == obs["value"].tolist()


def test_compass_text_to_degrees():
    deg, calm, unparsed = bmkg_xlsx._direction_to_degrees(pd.Series(["N ", "SW", "C", "XX", None]))
    assert deg.iloc[0] == 0.0 and deg.iloc[1] == 225.0
    assert calm.tolist() == [False, False, True, False, False]
    assert unparsed.tolist() == [False, False, False, True, False]


def test_sacad_meta_line_with_commas_and_tabs():
    line = "    7,  2025,\\tSTASIUN METEOROLOGI F. L TOBING, X\\t ,ID,+01:33:00,+098:52:48,  10, RR2,19660101"
    m = sacad_zip.CORE.search(line)
    assert m and m.group(1) == "ID"
    assert abs(sacad_zip._dms(m.group(2)) - 1.55) < 1e-9
    assert abs(sacad_zip._dms("-06:16:12") + 6.27) < 1e-9


def test_overrides_apply_and_reject_unknown_pairs():
    pairs = pd.DataFrame({"station_a": ["a:1", "a:2"], "station_b": ["b:1", "b:2"],
                          "needs_review": [True, True], "review_reason": ["x", "x"], "decision": ["review", "review"]})
    crosswalk._apply_overrides(pairs, {"join": [["b:1", "a:1"]], "separate": [["a:2", "b:2"]]})
    assert pairs["decision"].tolist() == ["user_join", "user_separate"]
    assert not pairs["needs_review"].any()
    try:
        crosswalk._apply_overrides(pairs, {"join": [["a:1", "b:9"]]})
        assert False, "unknown pair should raise"
    except ValueError:
        pass


def test_ghcnd_dly_line_parsing(tmp_path):
    from wxgrid.readers import ghcnd_dly
    slots = ["  123  S", "-9999   ", "   45 GI"] + ["-9999   "] * 28
    line = "IDM00096747" + "2020" + "01" + "PRCP" + "".join(slots) + "\n"
    f = tmp_path / "IDM00096747.dly"
    f.write_text(line)
    df = ghcnd_dly.read_dly(f, {"PRCP"})
    assert df["value"].tolist() == [123, 45]
    assert df["date"].dt.day.tolist() == [1, 3]
    assert df["sflag"].tolist() == ["S", "I"] and df["qflag"].tolist() == [" ", "G"]
    assert df["mflag"].tolist() == [" ", " "]


def test_failed_filler_only_extends_after_primary():
    from wxgrid.consolidate import merge
    a = _rain(800, seed=1)
    b = pd.Series(np.random.default_rng(2).permutation(a.values), index=a.index)  # unrelated
    b = pd.concat([b, pd.Series([5.0, 6.0], index=pd.date_range(a.index[-1] + pd.Timedelta(days=1), periods=2))])
    obs = pd.concat([pd.DataFrame({"series_id": "p", "date": a.index, "value": a.values, "flag": ""}),
                     pd.DataFrame({"series_id": "f", "date": b.index, "value": b.values, "flag": ""})])
    series = pd.DataFrame({"series_id": ["p", "f"], "station_key": ["s:1", "t:1"], "source": ["src1", "src2"],
                           "variable": ["RR", "RR"], "n_values": [800, 802], "last": [a.index[-1], b.index[-1]]})
    cfg = {"crosswalk": {"min_overlap_days": 365, "r_min": 0.8, "equal_tol": 0.05},
           "merge": {"priority": ["src1", "src2"], "extend_after_primary": True}}
    mv, rep = merge.merged(obs, series, {"s:1": "S1", "t:1": "S1"}, cfg, "RR")
    assert rep["status"].tolist() == ["fail"]
    ext = mv[mv["series_id"] == "f"]
    assert len(ext) == 2 and (ext["date"] > a.index[-1]).all()
    assert ext["flag"].eq("unharmonised_source").all()
    assert (mv[mv["date"] <= a.index[-1]]["series_id"] == "p").all()


def test_long_csv_keeps_leading_zeros_and_drops_codes(tmp_path):
    from wxgrid.readers import long_csv
    (tmp_path / "st.csv").write_text("Stn_ID,Stn_Name,Lat_DD,Long_DD,Msl\n0011170,A,0.05,111.67,47\n")
    (tmp_path / "rr.csv").write_text("STN_ID,YEAR,MONTH,DAY,Rainfall\n0011170,1980,1,1,125\n"
                                     "0011170,1980,1,2,-999\n0011170,1980,1,3,-333\n0011170,1980,2,30,5\n")
    src = {"name": "t", "path": str(tmp_path), "missing_codes": [-999, -333], "scale": {"Rainfall": 0.1},
           "stations": {"file": "st.csv", "id": "Stn_ID", "name": "Stn_Name", "lat": "Lat_DD", "lon": "Long_DD", "elev": "Msl"},
           "tables": [{"file": "rr.csv", "id": "STN_ID", "date": {"year": "YEAR", "month": "MONTH", "day": "DAY"},
                       "values": {"Rainfall": "RR"}}]}
    st, se, ob = long_csv.read(src, None)
    assert st["station_key"].tolist() == ["t:0011170"]
    assert ob["value"].tolist() == [12.5]
    assert se["n_missing_code"].tolist() == [2]


def test_daylabel_detects_switch_and_shifts_dates():
    from wxgrid.consolidate import daylabel
    n = 1500
    ref = _rain(n + 5, seed=7)
    # station: correct convention (matches ref at target lag -1) for the first 700 days,
    # then labelled one day early (matches ref at lag 0, so offset +1)
    dates = ref.index[1:n + 1]
    vals = np.where(np.arange(n) < 700, ref.shift(1).iloc[1:n + 1].values, ref.iloc[1:n + 1].values)
    stn = pd.Series(vals, index=dates)
    dl = {"window_days": 120, "step_days": 30, "min_pairs": 60, "min_margin": 0.1, "min_run_blocks": 2,
          "lags": [-2, -1, 0, 1], "variables": ["RR"], "pairwise_reference_sources": []}
    obs = pd.DataFrame({"series_id": "s", "date": stn.index, "value": stn.values, "flag": ""})
    series = pd.DataFrame({"series_id": ["s"], "station_key": ["k"], "source": ["x"], "variable": ["RR"]})
    grid = {"name": "g", "target_lag": -1, "cells": {"c": ref}, "series_cell": {"s": "c"}}
    seg, blocks = daylabel.detect(obs, series, None, {"k": "S1"}, {"daylabel": dl}, grid)
    assert len(blocks) > 0
    ver = seg[seg.status == "verified"]
    assert set(ver.offset) == {0, 1}
    switch = ver[ver.offset == 1].start.min()
    assert abs((switch - dates[700]).days) <= 45
    out = daylabel.apply(obs, seg)
    late = out[out.date_raw > dates[760]]
    assert (late.date - late.date_raw).dt.days.eq(1).all()


def test_block_needs_a_real_runner_up():
    from wxgrid.consolidate import daylabel
    rng = np.random.default_rng(3)
    stn = pd.Series(rng.gamma(0.5, 10, 400), index=pd.date_range("1978-01-01", periods=400))
    ref = pd.Series(rng.gamma(0.5, 10, 400), index=stn.index[46:].append(pd.date_range(stn.index[-1] + pd.Timedelta(days=1), periods=46)))
    dl = {"window_days": 120, "step_days": 30, "min_pairs": 60, "min_margin": 0.1}
    b = daylabel.block_lags(stn, ref, [-2, -1, 0, 1], -1, dl)
    first = b.iloc[1]  # window reaches the reference start: only some lags have 60 pairs
    assert np.isnan(first["offset"]) or np.isfinite(first["margin"])


def test_extension_ranks_after_untested_filler():
    from wxgrid.consolidate import merge
    a = _rain(800, seed=1)
    end = a.index[-1]
    b = pd.Series(np.random.default_rng(2).permutation(a.values), index=a.index)
    b = pd.concat([b, pd.Series([5.0], index=[end + pd.Timedelta(days=1)])])
    c = pd.Series([9.0], index=[end + pd.Timedelta(days=1)])
    obs = pd.concat([pd.DataFrame({"series_id": k, "date": s.index, "value": s.values, "flag": ""})
                     for k, s in [("p", a), ("f", b), ("u", c)]])
    series = pd.DataFrame({"series_id": ["p", "f", "u"], "station_key": ["s:1", "t:1", "u:1"],
                           "source": ["A", "B", "C"], "variable": ["RR"] * 3, "n_values": [800, 801, 1],
                           "last": [end, end + pd.Timedelta(days=1), end + pd.Timedelta(days=1)]})
    cfg = {"crosswalk": {"min_overlap_days": 365, "r_min": 0.8, "equal_tol": 0.05},
           "merge": {"priority": ["A", "B", "C"], "extend_after_primary": True}}
    mv, rep = merge.merged(obs, series, {"s:1": "S", "t:1": "S", "u:1": "S"}, cfg, "RR")
    day = mv[mv["date"] == end + pd.Timedelta(days=1)]
    assert day["series_id"].tolist() == ["u"]


def test_source_duplicates_are_not_collisions():
    from wxgrid.consolidate import daylabel, flags
    obs = pd.DataFrame({"series_id": ["s", "s", "s"], "date": pd.to_datetime(["2000-01-01", "2000-01-01", "2000-01-02"]),
                        "value": [2.0, 32.0, 1.0], "flag": ""})
    obs = flags.flag_duplicates(obs)
    seg = pd.DataFrame([dict(series_id="s", start=pd.Timestamp("2000-01-01"), end=pd.Timestamp("2000-01-02"),
                             offset=0, status="verified", method="x")])
    out = daylabel.apply(obs, seg)
    assert out["flag"].tolist()[:2] == ["src_duplicate", "src_duplicate"]
    assert "collision" not in out["label"].tolist()


def test_exclusions_flag_not_delete():
    obs = pd.DataFrame({"series_id": ["s"] * 4, "date": pd.date_range("2000-01-01", periods=4),
                        "value": [0.0, 0.0, 0.0, 5.0], "flag": ["", "", "above_max", ""]})
    table = pd.DataFrame({"series_id": ["s"], "start": ["2000-01-02"], "end": ["2000-01-03"], "rule": ["zero_run_60d"]})
    out = flags.apply_exclusions(obs, table)
    assert len(out) == 4
    assert out["flag"].tolist() == ["", "qc_excluded", "above_max;qc_excluded", ""]


def test_exclusions_review_flag_kept_in_merge():
    obs = pd.DataFrame({"series_id": ["s"] * 3, "date": pd.date_range("2000-01-01", periods=3),
                        "value": [1.0, 2.0, 3.0], "flag": ["", "", ""]})
    table = pd.DataFrame({"series_id": ["s", "s"], "start": ["2000-01-01", "2000-01-03"],
                          "end": ["2000-01-02", "2000-01-03"], "rule": ["a", "b"], "flag": ["qc_review", None]})
    out = flags.apply_exclusions(obs, table)
    assert out["flag"].tolist() == ["qc_review", "qc_review", "qc_excluded"]

def test_station_month_grid_maps_wmo_and_builds_dates(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    from wxgrid.readers import station_month_grid
    wb = xlwt.Workbook()
    sh = wb.add_sheet("2000")
    hdr = ["NO STA", "STA", "TAHUN", "BULAN"] + [f"R{d}" for d in range(1, 32)]
    for c, h in enumerate(hdr):
        sh.write(0, c, h)
    # one station-month: Jan 2000, day1=5, day2=8888 (unmeasurable), day3=9999 (missing), day31 invalid-for-Jan ok
    row = [73, "SIBOLGA", 2000, 1, 5.0, 8888.0, 9999.0] + [0.0] * 28
    for c, v in enumerate(row):
        sh.write(1, c, v)
    f = tmp_path / "2000.xls"
    wb.save(str(f))
    (tmp_path / "cat.csv").write_text("wmo,lat,lon,elev,name\n96073,1.55,98.88,3,SIBOLGA\n")
    src = {"name": "t", "path": str(tmp_path), "year_pattern": r"^(19|20)\d\d\.xls$", "id_col": "NO STA",
           "name_col": "STA", "year_col": "TAHUN", "month_col": "BULAN", "day_prefix": "R",
           "id_to_wmo_offset": 96000, "missing_codes": [9999], "unmeasurable_codes": [8888],
           "variable": "RR", "units": "mm", "station_namespace": "t",
           "catalogue_csv": str(tmp_path / "cat.csv")}
    st, se, ob = station_month_grid.read(src, [90, -15, 145, 12])
    assert st["wmo_id"].tolist() == ["96073"]
    assert ob[ob["date"] == "2000-01-01"]["value"].tolist() == [5.0]
    assert ob[ob["date"] == "2000-01-02"]["flag"].tolist() == ["unmeasurable"]
    assert (ob["date"] == "2000-01-03").sum() == 0  # 9999 dropped
    assert int(ob["value"].notna().sum()) == 29      # day1 + 28 zeros; day2 unmeasurable(NaN), day3 missing


def test_station_month_grid_variants_1990_and_1997(tmp_path, monkeypatch):
    """F72: full WMO numbers in NOSTA (1990-1993); 1997 = empty first sheet, `No. Sta`/`NOMOR`, text ids, 2-digit years."""
    from wxgrid.readers import station_month_grid as smg

    class Sheet:
        def __init__(self, rows):
            self.rows = rows
            self.nrows = len(rows)
            self.ncols = max((len(r) for r in rows), default=0)

        def cell_value(self, r, c):
            return self.rows[r][c] if c < len(self.rows[r]) else ""

    class Book:
        def __init__(self, sheets):
            self._s = sheets

        def sheets(self):
            return self._s

    head = ["NOSTA", "STA", "TAHUN", "BULAN", "R1", "R2"]
    books = {
        b"1990": Book([Sheet([head, [96001.0, "SABANG", 1990.0, 1.0, 5.0, 9999.0]])]),
        b"1994": Book([Sheet([head, [1.0, "SABANG", 1994.0, 1.0, 7.0, 8888.0]])]),
        b"1997": Book([Sheet([]), Sheet([["No. Sta", "NOMOR", "TAHUN", "BULAN", "R1", "R2"],
                                         ["001", "96001", "97", "01", "3.0", "0.0"]])]),
    }
    for y in ("1990", "1994", "1997"):
        (tmp_path / f"{y}.xls").write_bytes(y.encode())
    monkeypatch.setattr(smg.xlrd, "open_workbook", lambda file_contents=None, **k: books[file_contents])
    cat = tmp_path / "cat.csv"
    cat.write_text("wmo,lat,lon,elev,name\n96001,5.87,95.33,126,SABANG\n", encoding="utf-8")
    src = dict(name="chind", path=str(tmp_path), year_pattern=r"^(19|20)\d\d\.xls$", id_col=["NOMOR", "NO STA"], name_col="STA",
               year_col="TAHUN", month_col="BULAN", day_prefix="R", id_to_wmo_offset=96000, missing_codes=[9999],
               unmeasurable_codes=[8888], variable="RR", units="mm", catalogue_csv=str(cat))
    st, se, ob = smg.read(src, [90, -15, 145, 12])
    assert st.station_key.tolist() == ["chind:96001"]
    got = {d.strftime("%Y-%m-%d"): (v, f) for d, v, f in zip(ob.date, ob.value, ob.flag)}
    assert got["1990-01-01"][0] == 5.0 and "1990-01-02" not in got          # 9999 = missing
    assert got["1994-01-01"][0] == 7.0 and got["1994-01-02"][1] == "unmeasurable"
    assert got["1997-01-01"][0] == 3.0 and got["1997-01-02"][0] == 0.0       # text ids, 2-digit year, second sheet


def test_export_mirror_copies_release_files(tmp_path):
    from wxgrid.export import _mirror
    out = tmp_path / "export"
    out.mkdir()
    for s in ("long.csv.gz", "wide.csv.gz", "wide_source.csv.gz", "sites.csv", "README.md"):
        (out / f"p_{s}").write_text(s, encoding="utf-8")
    (out / "other_long.csv.gz").write_text("x", encoding="utf-8")
    _mirror(out, "p", tmp_path / "data")
    assert sorted(f.name for f in (tmp_path / "data").iterdir()) == sorted(f"p_{s}" for s in ("long.csv.gz", "wide.csv.gz", "wide_source.csv.gz", "sites.csv", "README.md"))
