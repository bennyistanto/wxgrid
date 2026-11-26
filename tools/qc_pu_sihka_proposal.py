"""pu_sihka /qc, question 7: proposal tables (proposals only; nothing is adopted or applied).

Reads the q*.csv tables of tools/qc_pu_sihka_{metadata,positions,position_hypotheses,zeros,values,scale,copies}.py
and writes, in the format of config qc.exclusions (series_id, start, end, rule, flag, note; dates in the
compiled corrected `date` convention, because the pipeline applies exclusions after the day-label step):

  qc_excluded (would corrupt a grid)
    scale_x10            series-years whose totals are about 10x CPC and the PU neighbours (q2b_scale.csv)
    scale_suspect        series-year total > 4x CPC with a daily rain share or totals that no neighbour shows
    zero_filled_year     series-year total < 0.25x CPC and < 0.25x the PU-neighbour median (q2b_scale.csv)
    gt500_unsupported    values > 500 mm whose references (CPC D-1..D+1, neighbours) are < 25% of the value
    copy_of_other_post   a publication-year equal (>= 90% of wet days) to another post; the side that fits its
                         own CPC cell and neighbours worse (q6_copy_sides.csv); both sides when undecided and > 25 km apart
    zero_run_wet_season  zero runs >= 30 days in the wet season while CPC (>= 3 mm/day and PU neighbours >= 1.5
                         mm/day or none) or PU neighbours (>= 3 mm/day) were wet (q1_zero_runs.csv)
    zero_month_two_refs  surviving all-zero months with CPC >= 50 and PU neighbours >= 50 mm, or >= 100 mm at
                         non-PU sites (q1_zero_months.csv)
    position_unresolved  whole series of posts whose position is in the sea or a placeholder and no candidate
                         fits (q0, q4, q4b)
  review flags (value stays in merged views)
    zero_month_suspect   other surviving all-zero months in the 50-100 mm band
    isolated_extreme     >= 100 mm while CPC 3-day max and every neighbour < 10 mm (q36_value_flags.csv)
    suspect_accumulation >= own p95 after >= 2 missing days with references < 25% of the value
    copy_suspect         copy pair-years, undecided, <= 25 km apart (both sides)
Positions: proposed_positions_pu_sihka.csv (station_key, name, lat, lon, proposed_lat, proposed_lon, km, evidence).
Per-series table: q7_series_table.csv.

Output: F:/temp/station/qc_pu_sihka/proposed_exclusions_pu_sihka.csv, proposed_positions_pu_sihka.csv,
        q7_series_table.csv; log q7.log
Usage: python tools/qc_pu_sihka_proposal.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)


def to_rows(o, sel, rule, flag, note):
    """Selected PU value rows (mask on o, sorted by series and date) -> exclusion rows in corrected dates,
    one row per run of selected values with no unselected value of the same series in between."""
    rows = []
    d = o.assign(sel=sel)
    for sid, g in d[d.series_id.isin(d.series_id[d.sel].unique())].groupby("series_id", observed=True):
        g = g.sort_values("date")
        run = (g.sel != g.sel.shift()).cumsum()
        for _, h in g[g.sel].groupby(run[g.sel]):
            rows.append(dict(series_id=sid, start=h.date.min().date(), end=h.date.max().date(), rule=rule, flag=flag,
                             note=f"{note(h) if callable(note) else note}; raw {h.date_raw.min().date()}..{h.date_raw.max().date()}; {len(h)} values"))
    return rows


UNRESOLVED = {  # position in the sea or a shared placeholder, and no candidate fits (q0_metadata, q4_decisions, q4b_hypotheses)
    "pu_sihka:06.13.05150160003": "PATAPPA DATA: 35 km off the coast; IMERG and CPC cells NaN; rainfall fits 55-61 km away (lon 120 or partner centroid), not decisive",
    "pu_sihka:06.13.06021590001": "PCH MEKARSARI OPYANG: 18.8 km off the coast; best r 0.21",
    "pu_sihka:06.13.05160090002": "KASIWIANG: 17.6 km off the coast in the Gulf of Bone; best r 0.30",
    "pu_sihka:06.13.04090020025": "BATU TANGGA: same position as Mangunang, Kambat, Mo'ui (placeholder); best r 0.23",
    "pu_sihka:06.13.04090020027": "MANGUNANG: same position as Batu Tangga, Kambat, Mo'ui (placeholder); best r 0.31",
    "pu_sihka:06.13.04090020028": "KAMBAT: same position as Batu Tangga, Mangunang, Mo'ui (placeholder); best r 0.33",
    "pu_sihka:06.13.04090020044": "MO'UI: same position as Batu Tangga, Mangunang, Kambat (placeholder); best r 0.32",
    "pu_sihka:06.13.02120010026": "SAPURAN: same position as Arjowinangun (0.01 km), which fits there; Sapuran best r 0.36, top-3 partners 98-203 km away",
}
OVERRIDES = [  # (station_key, proposed lat, lon, evidence) from q4b_hypotheses.csv / q4_candidates.csv
    ("pu_sihka:06.13.07040090003", -2.81381, 140.08747,
     "longitude degree 104 -> 140 (BWS Papua, header province Papua): top-3 partners 26 km vs 4,004 km, CPC r 0.415 vs 0.083 (q4b)"),
    ("pu_sihka:06.13.05160380012", -4.31336, 119.87111,
     "longitude degree 116 -> 119 (compiled point is 77 km off Sulawesi in the Makassar Strait): top-3 partners 30 km vs 334 km, CPC r 0.337 vs NaN (q4b)"),
    ("pu_sihka:06.13.05150090002", -4.00014, 119.72550,
     "header 2025 (WKT) instead of the 2020-2022 DMS header, which is the position of Watang Gilireng (0.01 km): top-3 partners 11 km vs 59 km, CPC r 0.417 vs 0.312 (q4)"),
]


def main():
    o = c.pu_obs()
    o = o[o.value.notna()].sort_values(["series_id", "date"]).reset_index(drop=True)
    o["sid"] = o.series_id.astype(str)
    o["y"] = o.date_raw.dt.year
    o["ym"] = o.date_raw.dt.to_period("M").astype(str)
    st = pd.read_csv(OUT / "q0_metadata.csv").set_index("station_key")
    rows = []
    # scale and zero-filled years
    sc = pd.read_csv(OUT / "q2b_scale.csv")
    x10 = sc[(sc.ratio_cpc >= 5) & (sc.ratio_nb >= 5) & (sc.p99 > 300)]
    sus = sc[(sc.ratio_cpc > 4) & (sc.ratio_nb > 4) & ~sc.index.isin(x10.index)]
    zf = sc[(sc.ratio_cpc < 0.25) & (sc.ratio_nb < 0.25)]
    for tab, rule in ((x10, "scale_x10"), (sus, "scale_suspect"), (zf, "zero_filled_year")):
        for r in tab.itertuples():
            m = (o.sid == r.sid) & (o.y == r.y)
            rows += to_rows(o, m, rule, "qc_excluded", f"{r.name} {r.y}: total {r.total:.0f} mm, CPC {r.cpc:.0f}, PU-neighbour median sum {r.nb:.0f}, wet-day p99 {r.p99:.0f}")
    scaled = set(zip(x10.sid, x10.y)) | set(zip(sus.sid, sus.y))
    # values > 500 mm
    b = pd.read_csv(OUT / "q2_above_500.csv", parse_dates=["date_raw"])
    b = b[np.array([(s, d.year) not in scaled for s, d in zip(b.sid, b.date_raw)]) & (b.ref_max.fillna(0) < 0.25 * b.value).to_numpy()]
    key = set(zip(b.sid, b.date_raw))
    m = pd.Series([(s, d) in key for s, d in zip(o.sid, o.date_raw)])
    rows += to_rows(o, m.values, "gt500_unsupported", "qc_excluded", lambda h: f"{h.value.iloc[0]:.0f} mm, references < 25% of it (q2_above_500.csv)")
    # copies
    cs = pd.read_csv(OUT / "q6_copy_sides.csv")
    for r in cs.itertuples():
        if r.original != "undecided":
            sides, flag, rule = [r.copy], "qc_excluded", "copy_of_other_post"
        elif r.km > 25:
            sides, flag, rule = [r.a, r.b], "qc_excluded", "copy_of_other_post"
        else:
            sides, flag, rule = [r.a, r.b], "copy_suspect", "copy_suspect"
        for s in sides:
            m = (o.sid == s) & (o.y == r.year)
            rows += to_rows(o, m, rule, flag, f"{r.year} equal to {r.name_b if s == r.a else r.name_a} on {r.equal_frac:.0%} of {r.n_wet} wet days, {r.km:.0f} km apart; original {r.original}")
    # zero runs
    zr = pd.read_csv(OUT / "q1_zero_runs.csv", parse_dates=["start", "end"])
    cd, nd = zr.cpc_sum / zr.days, zr.nb_pu_median / zr.days
    zr = zr[(zr.expected_cpc_clim / zr.days >= 5) & (((cd >= 3) & (nd.isna() | (nd >= 1.5))) | (nd >= 3))]
    for r in zr.itertuples():
        m = (o.sid == r.series_id) & o.date_raw.between(r.start, r.end)
        rows += to_rows(o, m, "zero_run_wet_season", "qc_excluded", f"{r.days} d of 0 mm in the wet season (CPC climatology {r.expected_cpc_clim / r.days:.1f} mm/d); CPC {r.cpc_sum / r.days:.1f} mm/d, PU neighbours {r.nb_pu_median / r.days:.1f} mm/d")
    # zero months
    zm = pd.read_csv(OUT / "q1_zero_months.csv")
    two = (zm.cls == "ge100_other_sources_only") | ((zm.cpc >= 50) & (zm.nb_pu >= 50))
    for tab, rule, flag in ((zm[two], "zero_month_two_refs", "qc_excluded"),
                            (zm[(zm.cls == "band_50_100") & ~two], "zero_month_suspect", "zero_month_suspect")):
        for r in tab.itertuples():
            m = (o.sid == r.series_id) & (o.ym == r.ym)
            rows += to_rows(o, m, rule, flag, f"all-zero month {r.ym}; CPC {r.cpc:.0f} mm, PU neighbours {r.nb_pu:.0f} mm ({r.n_nb_pu}), non-PU sites {r.nb_other:.0f} mm ({r.n_nb_other})")
    # unresolved positions: whole series
    for sk, why in UNRESOLVED.items():
        m = o.station_key.astype(str) == sk
        rows += to_rows(o, m, "position_unresolved", "qc_excluded", why)
    # review flags on single values
    v = pd.read_csv(OUT / "q36_value_flags.csv", parse_dates=["date_raw"])
    v["ref_max"] = v[["cpc3max", "pu_max3", "site_max4"]].max(axis=1)
    for col, rule, cond in (("isolated_extreme", "isolated_extreme", v.isolated_extreme),
                            ("accumulation_after_gap", "suspect_accumulation", v.accumulation_after_gap & (v.ref_max.fillna(0) < 0.25 * v.value))):
        key = set(zip(v.sid[cond], v.date_raw[cond]))
        m = pd.Series([(s, d) in key for s, d in zip(o.sid, o.date_raw)])
        rows += to_rows(o, m.values, rule, rule, lambda h: f"{h.value.iloc[0]:.0f} mm (q36_value_flags.csv)")
    ex = pd.DataFrame(rows)
    ex.to_csv(OUT / "proposed_exclusions_pu_sihka.csv", index=False)
    summarise(o, ex, st)


def hits(o, ex):
    """Per exclusion row: which value rows of o it matches (series and corrected date range)."""
    pos = o.groupby("sid").indices
    dates = o.date.to_numpy()
    out = []
    for r in ex.itertuples():
        idx = pos.get(r.series_id)
        if idx is None:
            continue
        d = dates[idx]
        k = idx[(d >= np.datetime64(pd.Timestamp(r.start))) & (d <= np.datetime64(pd.Timestamp(r.end)))]
        out.append(pd.DataFrame({"row": k, "rule": r.rule, "flag": r.flag}))
    return pd.concat(out, ignore_index=True)


def summarise(o, ex, st):
    h = hits(o, ex)
    print("proposed exclusion rows:", len(ex), "; by rule (rows, distinct values):")
    t = h.groupby(["flag", "rule"]).row.agg(["size", "nunique"])
    t["rows"] = ex.groupby(["flag", "rule"]).size()
    t["series"] = h.assign(sid=o.sid.values[h.row]).groupby(["flag", "rule"]).sid.nunique()
    print(t.to_string())
    exc = h[h.flag == "qc_excluded"].row.unique()
    print("distinct values proposed qc_excluded:", len(exc), "of", len(o), f"({100 * len(exc) / len(o):.2f}%)",
          "; in series", o.sid.iloc[exc].nunique())
    rev = np.setdiff1d(h[h.flag != "qc_excluded"].row.unique(), exc)
    print("distinct values with a review flag only:", len(rev))
    # positions
    pr = []
    for sk, la, lo, ev in OVERRIDES:
        pr.append(dict(station_key=sk, name=st.at[sk, "name"], unit=st.at[sk, "unit"], lat=st.at[sk, "lat"], lon=st.at[sk, "lon"],
                       proposed_lat=la, proposed_lon=lo, km=round(float(c.haversine_km(st.at[sk, "lat"], st.at[sk, "lon"], la, lo)), 1),
                       proposal="move", evidence=ev))
    for sk, why in UNRESOLVED.items():
        pr.append(dict(station_key=sk, name=st.at[sk, "name"], unit=st.at[sk, "unit"], lat=st.at[sk, "lat"], lon=st.at[sk, "lon"],
                       proposal="exclude until a position is known (register comparison not done: HTTP 403)", evidence=why))
    pr.append(dict(station_key="pu_sihka:06.13.05060040001", name=st.at["pu_sihka:06.13.05060040001", "name"], unit="BWS SULAWESI II",
                   lat=st.at["pu_sihka:06.13.05060040001", "lat"], lon=st.at["pu_sihka:06.13.05060040001", "lon"], proposal="keep",
                   evidence="the 2019 header (158 km away) seemed to fit the rainfall only because the 2019 publication is a copy of Pontolo Molingkapoto (q6); excluded as copy_of_other_post"))
    shared = st[st.same_position_as.notna() & ~st.index.isin(list(UNRESOLVED) + [x[0] for x in OVERRIDES])]
    for sk, r in shared.iterrows():
        pr.append(dict(station_key=sk, name=r["name"], unit=r.unit, lat=r.lat, lon=r.lon, proposal="review (shared position)",
                       evidence="same position as " + r.same_position_as + "; rainfall does not decide (q4_decisions.csv)"))
    pd.DataFrame(pr).to_csv(OUT / "proposed_positions_pu_sihka.csv", index=False)
    print("proposed positions rows:", len(pr), pd.DataFrame(pr).proposal.value_counts().to_dict())
    # per-series table
    cov = pd.read_csv(OUT / "q8_coverage_series.csv").set_index("series_id")
    f = o.flag.astype(str)
    tab = cov[["n_values", "first", "last", "missing_pct_in_span", "n_dropped_R1R2"]].copy()
    for k in ("src_suspect", "src_unrealistic", "above_max", "src_duplicate"):
        tab["n_" + k] = o[f.str.contains(k)].groupby("sid").size().reindex(tab.index).fillna(0).astype(int)
    tab["n_label_unverified"] = o[o.label.astype(str) == "unverified"].groupby("sid").size().reindex(tab.index).fillna(0).astype(int)
    hh = h.assign(sid=o.sid.values[h.row])
    pv = hh.groupby(["sid", "rule"]).row.nunique().unstack(fill_value=0)
    tab = tab.join(pv.add_prefix("prop_"), how="left").fillna(0)
    tab["n_proposed_excluded"] = hh[hh.flag == "qc_excluded"].groupby("sid").row.nunique().reindex(tab.index).fillna(0).astype(int)
    tab["station_key"] = tab.index.str.rsplit(":", n=2).str[0]
    tab["name"] = tab.station_key.map(st["name"])
    tab["position_issue"] = tab.station_key.map(lambda k: "move" if k in [x[0] for x in OVERRIDES] else "unresolved" if k in UNRESOLVED
                                               else "shared" if isinstance(st.at[k, "same_position_as"], str) else
                                               "off land" if not st.at[k, "on_land"] else "")
    tab.to_csv(OUT / "q7_series_table.csv")
    print("series with any proposed exclusion:", int((tab.n_proposed_excluded > 0).sum()))
    pd.set_option("display.width", 250)
    cols = ["name", "n_values", "missing_pct_in_span", "n_src_suspect", "n_src_unrealistic", "n_proposed_excluded", "position_issue"]
    print(tab.sort_values("n_proposed_excluded", ascending=False)[cols].head(40).to_string())


if __name__ == "__main__":
    main()
