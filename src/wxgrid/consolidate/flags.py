"""Non-destructive plausibility flags. Values are never removed here; full QC is /qc.

Bounds come from the config (`flag_bounds`) and are provisional screening limits, not
climatological claims.
"""

import pandas as pd


def _add(flag, mask, code):
    """Append `code` to the flag string where `mask` is True."""
    flag = flag.copy()
    hit = mask & flag.ne("")
    flag[hit] = flag[hit] + ";" + code
    flag[mask & ~hit] = code
    return flag


def flag_duplicates(obs):
    """Two values for one series and date in the source itself: keep both, flag both."""
    out = obs.copy()
    dup = out.duplicated(["series_id", "date"], keep=False)
    out["flag"] = _add(out["flag"].fillna(""), dup, "src_duplicate")
    return out


def apply_exclusions(obs, table):
    """table: series_id, start, end (dates in the obs `date` convention), rule, optional flag.
    Matching values are kept and flagged `qc_excluded`; merged views leave them out.
    A row whose `flag` is set to another code (e.g. `qc_review`) adds that flag instead and the
    value stays in merged views."""
    out = obs.reset_index(drop=True)
    table = table.copy()
    table["flag"] = table["flag"].fillna("qc_excluded") if "flag" in table else "qc_excluded"
    pos = out.groupby("series_id").indices
    dates = out["date"].to_numpy()
    flag = out["flag"].fillna("")
    for code, tc in table.groupby("flag"):
        hit = pd.Series(False, index=out.index)
        for sid, g in tc.groupby("series_id"):
            rows = pos.get(sid)
            if rows is None:
                continue
            d = dates[rows]
            for r in g.itertuples():
                m = (d >= pd.Timestamp(r.start).to_datetime64()) & (d <= pd.Timestamp(r.end).to_datetime64())
                hit.iloc[rows[m]] = True
        flag = _add(flag, hit, code)
    out["flag"] = flag
    return out


def apply_bounds(obs, series, bounds):
    """obs: series_id, date, value, flag. Adds below_min / above_max per variable."""
    var = obs["series_id"].map(series.set_index("series_id")["variable"])
    lo = var.map({k: v[0] for k, v in bounds.items()})
    hi = var.map({k: v[1] for k, v in bounds.items()})
    flag = obs["flag"].fillna("")
    flag = _add(flag, obs["value"] < lo, "below_min")
    flag = _add(flag, obs["value"] > hi, "above_max")
    out = obs.copy()
    out["flag"] = flag
    return out
