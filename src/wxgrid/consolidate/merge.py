"""Merged view: one series per site and variable, built by source priority.

The highest-priority series of a site is the primary. A lower-priority series fills only
days where nothing of higher priority exists. Each filler is compared directly with the
primary on unflagged values; with at least `min_overlap_days` of overlap it must have
best lag 0 and r >= `r_min` at lag 0, or it is excluded. Fillers with too little overlap
to test are used but reported as "untested" in merge_fillers.csv, so the user can see
which fills rest on no evidence. With `merge.extend_after_primary`, an excluded filler
still supplies days after the primary's last date, flagged `unharmonised_source`.
Every merged value keeps its series_id.
"""

import numpy as np
import pandas as pd

from .crosswalk import pair_stats, passes, summarise


def sites_table(stations, series, root, priority):
    st = stations.copy()
    st["site_root"] = st["station_key"].map(root)
    rank = {s: k for k, s in enumerate(priority)}
    # A station's rank is that of its best-priority series source; the site's
    # representative station is the best-ranked one, then the one with the longest record.
    s_rank = series.assign(_r=series["source"].map(lambda s: rank.get(s, len(rank)))).groupby("station_key")["_r"].min()
    st["_rank"] = st["station_key"].map(s_rank).fillna(len(rank))
    st["_n"] = st["station_key"].map(series.groupby("station_key")["n_values"].sum()).fillna(0)
    st = st.sort_values(["site_root", "_rank", "_n"], ascending=[True, True, False])
    rep = st.drop_duplicates("site_root")
    order = {r: f"S{k + 1:05d}" for k, r in enumerate(sorted(rep["site_root"]))}
    st["site_id"] = st["site_root"].map(order)
    members = st.groupby("site_id").agg(station_keys=("station_key", lambda x: ";".join(x)),
                                        sources=("source", lambda x: ";".join(sorted(set(x)))))
    sites = rep.assign(site_id=rep["site_root"].map(order)).set_index("site_id")[
        ["name", "lat", "lon", "elev_m", "country", "wmo_id", "station_key"]].rename(
        columns={"station_key": "representative_station"}).join(members).reset_index()
    return sites.sort_values("site_id"), dict(zip(st["station_key"], st["site_id"]))


def merged(obs, series, site_of, cfg, variable):
    """Return (merged long table, filler report) for one variable."""
    cw, m = cfg["crosswalk"], cfg["merge"]
    rank = {s: k for k, s in enumerate(m["priority"])}
    ser = series[series["variable"] == variable].copy()
    # sources left out of this variable's merged view (still in the observations)
    ser = ser[~ser["source"].isin(m.get("exclude_sources", {}).get(variable, []))]
    if ser.empty:
        return pd.DataFrame(), pd.DataFrame()
    ser["site_id"] = ser["station_key"].map(site_of)
    ser["_rank"] = ser["source"].map(lambda s: rank.get(s, len(rank)))
    ser = ser.sort_values(["site_id", "_rank", "n_values"], ascending=[True, True, False])
    ser["order"] = ser.groupby("site_id").cumcount()

    # Test every filler directly against its site's primary on unflagged values.
    clean = obs[obs["flag"].eq("")]
    fillers = ser[ser["order"] > 0]
    need = set(fillers["series_id"]) | set(ser.loc[ser["site_id"].isin(fillers["site_id"]) & (ser["order"] == 0), "series_id"])
    vals = {sid: g.set_index("date")["value"] for sid, g in clean[clean["series_id"].isin(need)].groupby("series_id")}
    primary = ser[ser["order"] == 0].set_index("site_id")["series_id"]
    report, excluded = [], set()
    for _, s in fillers.iterrows():
        p = primary[s["site_id"]]
        row = dict(site_id=s["site_id"], primary=p, filler=s["series_id"], status="untested")
        if p in vals and s["series_id"] in vals:
            row.update(summarise(pair_stats(vals[p], vals[s["series_id"]], cw.get("lags", [-1, 0, 1]), cw["equal_tol"])))
            if row["n_overlap"] >= cw["min_overlap_days"]:
                row["status"] = "pass" if passes(row, cw) else "fail"
        if row["status"] == "fail":
            excluded.add(s["series_id"])
        report.append(row)

    use = ser[~ser["series_id"].isin(excluded)]
    if "label" in obs:  # day-label collisions: two values claim one date, use neither
        obs = obs[obs["label"].ne("collision")]
    # the same for duplicates inside a source (values can conflict, e.g. 2 vs 32 mm), and
    # for values the QC excluded (zero-filled blocks, copied data, codes)
    obs = obs[~obs["flag"].fillna("").str.contains("src_duplicate|qc_excluded")]
    o = obs[obs["series_id"].isin(use["series_id"])].merge(use[["series_id", "site_id", "order"]], on="series_id")
    if m.get("extend_after_primary") and excluded:
        # A failed filler may still extend the site past the end of its primary series:
        # those days have no better source. Flagged so the possible break stays visible.
        last = ser[ser["order"] == 0].set_index("site_id")["last"]
        ext = obs[obs["series_id"].isin(excluded)].merge(ser[["series_id", "site_id", "order"]], on="series_id")
        ext = ext[ext["date"] > ext["site_id"].map(last)]
        ext["order"] = ext["order"] + len(ser) + 1  # after every passed or untested filler (review fix 3)
        ext = ext.assign(flag=np.where(ext["flag"].fillna("").eq(""), "unharmonised_source",
                                       ext["flag"].fillna("") + ";unharmonised_source"))
        o = pd.concat([o, ext], ignore_index=True)
    o = o.sort_values(["site_id", "date", "order"]).drop_duplicates(["site_id", "date"], keep="first")
    cols = ["site_id", "date", "value", "flag", "series_id"] + [c for c in ("label", "date_raw") if c in o]
    return o[cols].reset_index(drop=True), pd.DataFrame(report)
