import pandas as pd
import pytest

from wxgrid.consolidate.crosswalk import _apply_overrides


def _pairs():
    return pd.DataFrame({"station_a": ["s:1"], "station_b": ["s:2"], "decision": ["auto"],
                         "needs_review": [True], "review_reason": ["x"]})


def test_separate_applied():
    p = _pairs()
    assert _apply_overrides(p, {"separate": [["s:1", "s:2"]]}, known={"s:1", "s:2", "s:3"}) == []
    assert p.at[0, "decision"] == "user_separate" and not p.at[0, "needs_review"]


def test_stale_separate_is_skipped_and_reported():
    p = _pairs()
    stale = _apply_overrides(p, {"separate": [["s:1", "s:3"]]}, known={"s:1", "s:2", "s:3"})
    assert stale == [["s:1", "s:3"]]


def test_unknown_station_raises():
    with pytest.raises(ValueError):
        _apply_overrides(_pairs(), {"separate": [["s:1", "s:9"]]}, known={"s:1", "s:2"})


def test_stale_join_raises():
    with pytest.raises(ValueError):
        _apply_overrides(_pairs(), {"join": [["s:1", "s:3"]]}, known={"s:1", "s:2", "s:3"})


def test_separation_holds_transitively():
    from wxgrid.consolidate.crosswalk import _Sites
    s = _Sites(["a:1", "b:1", "c:1"], {"a:1": "a", "b:1": "b", "c:1": "c"}, separated=[("a:1", "c:1")])
    assert s.union("a:1", "b:1")
    assert not s.union("b:1", "c:1")          # would put a:1 and c:1 in one site
    assert s.last_refusal == "would join stations the user separated"


def test_provider_groups_keep_pu_apart_from_bmkg():
    import numpy as np
    from wxgrid.consolidate import crosswalk
    st = pd.DataFrame({"station_key": ["pu_sihka:1", "bmkg_xlsx:1", "jatim:1"], "source": ["pu_sihka", "bmkg_xlsx", "jatim"],
                       "name": ["ALPHA", "ALPHA", "ALPHA"], "lat": [-7.0, -7.0005, -7.0001], "lon": [112.0, 112.0005, 112.0001],
                       "elev_m": [np.nan] * 3, "wmo_id": [""] * 3})
    se = pd.DataFrame({"series_id": [k + ":RR" for k in st.station_key], "station_key": st.station_key, "variable": "RR"})
    ob = pd.DataFrame(columns=["series_id", "date", "value", "flag"])
    cfg = {"crosswalk": dict(check_variable="RR", max_km=10, same_site_km=1, name_match_km=5, name_sim_min=85, min_overlap_days=365,
                             duplicate_equal_frac=0.9, r_min=0.8, equal_tol=0.05, lags=[-1, 0, 1], drop_words=[],
                             provider_groups={"PU": ["pu_sihka", "jatim"]}),
           "merge": {"priority": ["bmkg_xlsx", "jatim", "pu_sihka"]}}
    pairs, _, root = crosswalk.build(st, se, ob, cfg)
    rel = {frozenset((a, b)): r for a, b, r in zip(pairs.station_a, pairs.station_b, pairs.relation)}
    assert rel[frozenset(("pu_sihka:1", "bmkg_xlsx:1"))] == "different_provider"
    assert rel[frozenset(("jatim:1", "bmkg_xlsx:1"))] == "different_provider"
    assert rel[frozenset(("pu_sihka:1", "jatim:1"))] == "same_site"
    assert root["pu_sihka:1"] == root["jatim:1"] != root["bmkg_xlsx:1"]
    assert not pairs.needs_review.any()


def test_neutral_source_joins_either_side_but_never_bridges():
    from wxgrid.consolidate.crosswalk import _Sites
    camp = {"pu_sihka": "PU", "jatim": "PU", "asean_comp": None}.get
    src = {"pu:1": "pu_sihka", "comp:1": "asean_comp", "bmkg:1": "bmkg_xlsx"}
    s = _Sites(list(src), src, camp_of=lambda x: camp(x, ""))
    assert s.union("pu:1", "comp:1")            # neutral joins PU
    assert not s.union("comp:1", "bmkg:1")      # but cannot then bring in BMKG
    assert s.last_refusal == "would join stations of different provider groups"
    s2 = _Sites(list(src), src, camp_of=lambda x: camp(x, ""))
    assert s2.union("comp:1", "bmkg:1")         # neutral joins BMKG too


def test_isolated_source_never_joins_other_sources():
    import numpy as np
    from wxgrid.consolidate import crosswalk
    st = pd.DataFrame({"station_key": ["knmi:A", "bmkg_xlsx:1", "asean_comp:1"], "source": ["knmi", "bmkg_xlsx", "asean_comp"],
                       "name": ["ALPHA"] * 3, "lat": [-7.0, -7.0005, -7.0001], "lon": [112.0, 112.0005, 112.0001],
                       "elev_m": [np.nan] * 3, "wmo_id": [""] * 3})
    se = pd.DataFrame({"series_id": [k + ":RR" for k in st.station_key], "station_key": st.station_key, "variable": "RR"})
    ob = pd.DataFrame(columns=["series_id", "date", "value", "flag"])
    cfg = {"crosswalk": dict(check_variable="RR", max_km=10, same_site_km=1, name_match_km=5, name_sim_min=85, min_overlap_days=365,
                             duplicate_equal_frac=0.9, r_min=0.8, equal_tol=0.05, lags=[-1, 0, 1], drop_words=[],
                             neutral_sources=["asean_comp"], isolated_sources=["knmi"]),
           "merge": {"priority": ["bmkg_xlsx", "knmi", "asean_comp"]}}
    pairs, _, root = crosswalk.build(st, se, ob, cfg)
    rel = {frozenset((a, b)): r for a, b, r in zip(pairs.station_a, pairs.station_b, pairs.relation)}
    assert rel[frozenset(("knmi:A", "bmkg_xlsx:1"))] == "different_provider"
    assert rel[frozenset(("knmi:A", "asean_comp:1"))] == "different_provider"     # neutral does not bridge either
    assert rel[frozenset(("bmkg_xlsx:1", "asean_comp:1"))] == "same_site"
    assert root["bmkg_xlsx:1"] == root["asean_comp:1"] != root["knmi:A"]
