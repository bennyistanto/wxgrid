import json

import numpy as np
import pandas as pd

from wxgrid.readers import pu_sihka as ps


def test_parse_coord_formats():
    la, lo, how = ps.parse_coord("POINT(106.313123 -6.644992)")
    assert (round(la, 6), round(lo, 6), how) == (-6.644992, 106.313123, "wkt")
    la, lo, how = ps.parse_coord("03° 45' 20.9'' LS - 121° 55' 04.5'' BT")
    assert how == "dms" and abs(la + 3.75581) < 1e-4 and abs(lo - 121.91792) < 1e-4
    la, lo, _ = ps.parse_coord("00° 47' 26.9'' LU - 127° 22' 29.7'' BT")
    assert la > 0
    la, lo, how = ps.parse_coord("07⁰ 41' 53.0'' 112⁰ 12' 52.3\"")
    assert how.startswith("dms, no hemisphere") and la < 0
    la, lo, how = ps.parse_coord("- 8,82139° S - 120,965° E")
    assert how == "decimal text" and abs(la + 8.82139) < 1e-6 and abs(lo - 120.965) < 1e-6
    for s in ("", "-", "0", None):
        assert np.isnan(ps.parse_coord(s)[0])


def test_parse_elev():
    assert ps.parse_elev("268 mdpl") == 268 and ps.parse_elev("+ 54 m") == 54 and np.isnan(ps.parse_elev("-"))


def test_redate_drops_feb29_in_common_year():
    new, keep = ps.redate(pd.to_datetime(["2020-02-28", "2020-02-29", "2020-03-01"]), 2021)
    assert keep.tolist() == [True, False, True]
    assert [d.strftime("%Y-%m-%d") for d in new] == ["2021-02-28", "2021-03-01"]


def _ts(d):
    return str(int(pd.Timestamp(d).timestamp()))


def _fixture(tmp_path):
    raw = tmp_path / "raw"
    (raw / "pub").mkdir(parents=True)
    cat = [dict(id="post-a", integration_id="06.01", name="ALPHA", hidrologi_type="CURAH HUJAN", unit="BWS X",
                data=[dict(pubId="p1", type="MANUAL", variable="Rainfall", year="2021", status="Baik"),
                      dict(pubId="p2", type="MANUAL", variable="Rainfall", year="2022", status="Baik"),
                      dict(pubId="p3", type="TELEMETRI", variable="Rainfall", year="2022", status="Baik"),
                      dict(pubId="p4", type="MANUAL", variable="Water Level", year="2022", status="Baik"),
                      dict(pubId="p5", type="MANUAL", variable="Rainfall", year="2023", status="Baik")])]
    (raw / "catalogue_2026-11-25.json").write_text(json.dumps(cat), encoding="utf-8")
    head = {"koordinat": "07° 30' 00'' LS - 112° 30' 00'' BT", "elevesi": "21 mdpl", "nama_pos": "Alpha"}
    # p1: catalogue 2021 but stamped 2022 (R3: re-date), stray Unix-0 key, one doubtful day
    b1 = {"0": {"value": 0, "note": None}, _ts("2022-01-01"): {"value": 5, "note": None},
          _ts("2022-01-02"): {"value": 7, "note": "data meragukan"}}
    # p2: January 2022 all zero (R2 decision drops it); 1 Feb unrealistic
    b2 = {_ts(f"2022-01-{d:02d}"): {"value": 0, "note": None} for d in range(1, 32)}
    b2[_ts("2022-02-01")] = {"value": 900, "note": None, "status": "tidak_realistis"}
    b3 = {_ts("2022-03-01"): {"value": 3, "note": ""}}
    b5 = {_ts("2023-01-01"): {"value": 4, "note": None}}   # listed as a copy: skipped
    for k, b in (("p1", b1), ("p2", b2), ("p3", b3), ("p5", b5)):
        (raw / "pub" / f"{k}.json").write_text(json.dumps({"head": head, "body": b}), encoding="utf-8")
    dec = pd.DataFrame([dict(kind="zero_month_missing", pubId="", integration_id="06.01", gauge="MANUAL", period="2022-01", evidence="x"),
                        dict(kind="copy", pubId="p5", integration_id="06.01", gauge="MANUAL", period="", evidence="x")])
    dec.to_csv(tmp_path / "dec.csv", index=False)
    return dict(name="pu_sihka", reader="pu_sihka", path=str(raw), decisions=str(tmp_path / "dec.csv"), units="mm")


def test_read_applies_rules(tmp_path):
    st, se, ob = ps.read(_fixture(tmp_path), [90, -15, 145, 12])
    assert len(st) == 1 and st.station_key.iloc[0] == "pu_sihka:06.01" and st.elev_m.iloc[0] == 21
    assert sorted(se.series_id) == ["pu_sihka:06.01:MANUAL:RR", "pu_sihka:06.01:TELEMETRI:RR"]
    m = ob[ob.series_id == "pu_sihka:06.01:MANUAL:RR"].set_index("date")
    # p1 re-dated to 2021, Unix-0 key gone; January 2022 zeros dropped; copy p5 skipped
    assert [d.strftime("%Y-%m-%d") for d in m.index] == ["2021-01-01", "2021-01-02", "2022-02-01"]
    assert m.flag.tolist() == ["", "src_suspect", "src_unrealistic"]
    man = se.set_index("series_id").loc["pu_sihka:06.01:MANUAL:RR"]
    assert man.n_missing_code == 31


def test_coordinates_override(tmp_path):
    src = _fixture(tmp_path)
    src["coordinates_override"] = {"06.01": {"lat": -7.0, "lon": 140.0, "note": "test"}}
    st, _, _ = ps.read(src, [90, -15, 145, 12])
    assert (st.lat.iloc[0], st.lon.iloc[0]) == (-7.0, 140.0)


def test_coordinates_override_csv_and_approx(tmp_path):
    src = _fixture(tmp_path)
    pd.DataFrame([dict(integration_id="06.01", lat=-7.1, lon=112.1, approx=1, note="register")]).to_csv(tmp_path / "pos.csv", index=False)
    src["coordinates_override_csv"] = str(tmp_path / "pos.csv")
    st, _, ob = ps.read(src, [90, -15, 145, 12])
    assert (st.lat.iloc[0], st.lon.iloc[0]) == (-7.1, 112.1)
    assert ob.flag.str.contains("coord_approx").all()
    assert "src_suspect;coord_approx" in set(ob.flag)
    src["coordinates_override"] = {"06.01": {"lat": -7.0, "lon": 140.0, "note": "config wins"}}
    st, _, ob = ps.read(src, [90, -15, 145, 12])
    assert (st.lat.iloc[0], st.lon.iloc[0]) == (-7.0, 140.0) and not ob.flag.str.contains("coord_approx").any()
