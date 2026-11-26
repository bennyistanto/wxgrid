"""Day-label correction: find, per series and period, how many days its date labels are
shifted from the target convention, and shift them.

Evidence, per 30-day block (window `window_days` centred on the block):
- gridded references, in config order (e.g. IMERG Final 2001+, then CPC-UNI 1979+): station
  date D against grid day D + lag; a correctly labelled series peaks at `target_lag`
  (IMERG -1, findings F19; CPC -1, F38). The first reference that decides a block wins;
  the others are kept in the block table as a cross-check.
- pairwise reference: another series at the same site from a trusted source (e.g.
  SACA&D non-blended, assumed correct, target lag 0). Used where no gridded evidence.
A block's lag counts only if its r beats the runner-up lag by `min_margin`.

offset = best_lag - target_lag; corrected date = raw date + offset (days).

Blocks become segments (runs of equal offset). Runs shorter than `min_run_blocks`, and
blocks with weak evidence, take the offset of their neighbours when both neighbours agree
within `max_interp_blocks` (`interpolated`), otherwise keep offset 0 (`uncertain`). Blocks no reference covers keep
offset 0 (`unverified`). Values are never dropped; `date_raw` keeps the original date and
`label` records the status. Two values landing on one date after a shift are both kept and
labelled `collision`; the merged view skips them.
"""

import numpy as np
import pandas as pd

STATUS = ["verified", "interpolated", "uncertain", "unverified"]


def rolling_corr(x, y, window, min_n):
    """Centred rolling Pearson r over aligned daily arrays with NaNs (pairwise complete)."""
    m = ~(np.isnan(x) | np.isnan(y))
    xs, ys = np.where(m, x, 0.0), np.where(m, y, 0.0)

    def rsum(a):
        c = np.concatenate([[0.0], np.cumsum(a)])
        h = window // 2
        idx = np.arange(len(a))
        lo, hi = np.clip(idx - h, 0, len(a)), np.clip(idx - h + window, 0, len(a))
        return c[hi] - c[lo]

    n, sx, sy = rsum(m.astype(float)), rsum(xs), rsum(ys)
    sxx, syy, sxy = rsum(xs * xs), rsum(ys * ys), rsum(xs * ys)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy - sx * sy / n
        vx, vy = sxx - sx * sx / n, syy - sy * sy / n
        r = cov / np.sqrt(vx * vy)
    r[(n < min_n) | (vx <= 1e-9) | (vy <= 1e-9)] = np.nan
    return r


def block_lags(stn, ref, lags, target_lag, cfg):
    """stn, ref: daily Series. Returns DataFrame per block: start, offset, margin, r."""
    idx = pd.date_range(stn.index.min(), stn.index.max(), freq="D")
    x = stn.reindex(idx).to_numpy(float)
    rs = []
    for lag in lags:
        y = ref.copy()
        y.index = y.index - pd.Timedelta(days=lag)   # ref day D+lag aligned to station date D
        rs.append(rolling_corr(x, y.reindex(idx).to_numpy(float), cfg["window_days"], cfg["min_pairs"]))
    R = np.vstack(rs)                                # (lags, days)
    step = cfg["step_days"]
    centres = np.arange(step // 2, len(idx), step)
    out = []
    for c in centres:
        col = R[:, c]
        if np.all(np.isnan(col)):
            out.append((idx[c - step // 2], np.nan, np.nan, np.nan))
            continue
        order = np.argsort(np.nan_to_num(col, nan=-np.inf))[::-1]
        best, second = col[order[0]], col[order[1]] if len(order) > 1 else np.nan
        # A lag only wins against a real runner-up: near a reference's start just one lag
        # may have enough pairs, and it would otherwise "win" at any r (review fix 4).
        margin = best - second
        off = lags[order[0]] - target_lag if (np.isfinite(margin) and margin >= cfg["min_margin"]) else np.nan
        out.append((idx[c - step // 2], off, margin, best))
    return pd.DataFrame(out, columns=["start", "offset", "margin", "r"])


def _segments(blocks, covered, cfg):
    """blocks: offset per block (NaN = weak); covered: bool per block (any reference)."""
    off = blocks.copy()
    # short runs are not trusted on their own
    run_id = (off != off.shift()).cumsum()
    run_len = off.groupby(run_id).transform("size")
    off[(run_len < cfg["min_run_blocks"]) & off.notna()] = np.nan
    status = pd.Series(np.where(off.notna(), "verified", np.where(covered, "uncertain", "unverified")), index=off.index)
    k = cfg.get("max_interp_blocks", 6)  # no interpolation across longer weak stretches (review fix 8)
    prev, nxt = off.ffill(limit=k), off.bfill(limit=k)
    fill = off.isna() & covered & prev.notna() & (prev == nxt)
    off[fill] = prev[fill]
    status[fill] = "interpolated"
    return off.fillna(0).astype(int), status


def detect(obs, series, stations, site_of, cfg, grid_refs=None):
    """Return (segments, blocks). Segments: series_id, start, end, offset, status, method.
    Blocks: per series and 30-day block, the offset each piece of evidence gave (NaN if
    undecided), so gridded references can be cross-checked against each other."""
    if isinstance(grid_refs, dict):
        grid_refs = [grid_refs]
    grid_refs = grid_refs or []
    dl = cfg["daylabel"]
    vars_ = set(dl.get("variables", ["RR"]))
    ser = series[series["variable"].isin(vars_)].set_index("series_id", drop=False)
    o = obs[obs["series_id"].isin(ser["series_id"]) & obs["flag"].eq("")]
    vals = {k: g.set_index("date")["value"].sort_index() for k, g in o.groupby("series_id")}
    vals = {k: v[~v.index.duplicated()] for k, v in vals.items()}
    site = ser["station_key"].map(site_of)
    trusted_ids = ser.index[ser["source"].isin(set(dl.get("pairwise_reference_sources", [])))]
    trusted = set(dl.get("pairwise_reference_sources", []))
    lags = dl.get("lags", [-2, -1, 0, 1])
    # Target lags are calibrated per country; elsewhere they say nothing (findings F39).
    countries = set(dl.get("countries", []))
    country = ser["station_key"].map(stations.set_index("station_key")["country"]) if countries else None
    span = obs[obs["series_id"].isin(ser["series_id"])].groupby("series_id")["date"].agg(["min", "max"])
    rows, diag = [], []
    for sid in ser["series_id"]:
        if sid not in span.index:
            continue
        if sid not in vals or len(vals[sid]) < dl["min_pairs"]:
            # too short to test: still labelled, never silently unassessed (review fix 11)
            rows.append(dict(series_id=sid, start=span.at[sid, "min"], end=span.at[sid, "max"], offset=0,
                             status="unverified", method="none: too few values"))
            continue
        s = vals[sid]
        if countries and country[sid] not in countries:
            rows.append(dict(series_id=sid, start=s.index.min(), end=s.index.max(), offset=0,
                             status="unverified", method="none: country outside calibration"))
            continue
        evid = []  # (method, block DataFrame)
        for g in grid_refs:  # config order = priority
            if sid in g["series_cell"]:
                ref = g["cells"][g["series_cell"][sid]]
                evid.append(("gridded:" + g["name"], block_lags(s, ref, lags, g["target_lag"], dl)))
        if ser.at[sid, "source"] not in trusted:
            refs = [r for r in trusted_ids[site[trusted_ids].eq(site[sid]).to_numpy()] if r != sid and r in vals]
            for r in refs:
                evid.append(("pairwise:" + r, block_lags(s, vals[r], [-1, 0, 1], 0, dl)))
        if not evid:
            rows.append(dict(series_id=sid, start=s.index.min(), end=s.index.max(), offset=0,
                             status="unverified", method="none"))
            continue
        # combine: first evidence with a decided offset wins per block (gridded first)
        base = evid[0][1][["start"]].copy()
        base["offset"], base["method"], base["covered"], base["covered_by"] = np.nan, "none", False, "none"
        for method, b in evid:
            b = b.set_index("start").reindex(base["start"]).reset_index()
            diag.append(pd.DataFrame({"series_id": sid, "start": b["start"], "method": method,
                                      "offset": b["offset"], "margin": b["margin"], "r": b["r"]}))
            take = base["offset"].isna() & b["offset"].notna()
            base.loc[take, "offset"] = b.loc[take, "offset"].to_numpy()
            base.loc[take, "method"] = method
            first_cover = ~base["covered"] & b["r"].notna().to_numpy()
            base.loc[first_cover, "covered_by"] = method
            base["covered"] |= b["r"].notna().to_numpy()
        off, status = _segments(base["offset"], base["covered"], dl)
        base["offset"], base["status"] = off.to_numpy(), status.to_numpy()
        # undecided blocks: credit the reference that covered them (review fix 6)
        undecided = base["method"].eq("none") & base["status"].ne("unverified")
        base.loc[undecided, "method"] = base.loc[undecided, "covered_by"]
        key = (base[["offset", "status", "method"]] != base[["offset", "status", "method"]].shift()).any(axis=1).cumsum()
        step = pd.Timedelta(days=dl["step_days"])
        for _, g in base.groupby(key):
            rows.append(dict(series_id=sid, start=g["start"].iloc[0], end=g["start"].iloc[-1] + step - pd.Timedelta(days=1),
                             offset=int(g["offset"].iloc[0]), status=g["status"].iloc[0], method=g["method"].iloc[0]))
        # cover flagged values outside the unflagged span too
        first_row = next(i for i in range(len(rows) - 1, -1, -1) if i == 0 or rows[i - 1]["series_id"] != sid)
        rows[first_row]["start"] = min(rows[first_row]["start"], span.at[sid, "min"])
        rows[-1]["end"] = max(rows[-1]["end"], span.at[sid, "max"])
    seg = pd.DataFrame(rows)
    blocks = pd.concat(diag, ignore_index=True) if diag else pd.DataFrame()
    return _apply_overrides(seg, dl.get("overrides", [])), blocks


def _apply_overrides(seg, overrides):
    for o in overrides:  # {series_id, start, end, offset}
        seg = pd.concat([seg, pd.DataFrame([dict(series_id=o["series_id"], start=pd.Timestamp(o["start"]),
                                                 end=pd.Timestamp(o["end"]), offset=int(o["offset"]),
                                                 status="verified", method="user")])], ignore_index=True)
    return seg


def apply(obs, seg):
    """Shift dates per segment. Adds date_raw and label; later segments (user) win."""
    out = obs.reset_index(drop=True)
    out["date_raw"] = out["date"]
    label = np.full(len(out), "", dtype=object)
    date = out["date"].to_numpy().copy()
    raw = out["date_raw"].to_numpy()
    pos = out.groupby("series_id").indices
    for sid, g in seg.groupby("series_id", sort=False):
        rows = pos.get(sid)
        if rows is None:
            continue
        d = raw[rows]
        for s in g.itertuples():
            hit = rows[(d >= np.datetime64(s.start)) & (d <= np.datetime64(s.end))]
            date[hit] = raw[hit] + np.timedelta64(int(s.offset), "D")
            label[hit] = s.status
    out["date"], out["label"] = date, label
    # only shift-induced clashes are collisions; duplicates in the source itself are
    # flagged src_duplicate at read time (review fix 5)
    dup = (out.duplicated(["series_id", "date"], keep=False) & out["label"].ne("")
           & ~out["flag"].fillna("").str.contains("src_duplicate"))
    out.loc[dup, "label"] = "collision"
    return out


def gridded_reference(series, stations, ref_cfg, cache_path=None):
    """Extract the reference grid at every station cell. Returns dict for detect()."""
    import xarray as xr

    st = stations.set_index("station_key")
    ser = series[series["variable"].eq("RR")].copy()
    ser = ser[ser["last"] >= pd.Timestamp(ref_cfg.get("start", "1900-01-01"))]
    ds = xr.open_dataset(ref_cfg["path"])
    lat, lon = ds["lat"].values, ds["lon"].values
    la, lo = ser["station_key"].map(st["lat"]).to_numpy(), ser["station_key"].map(st["lon"]).to_numpy()
    inside = (la >= lat.min() - 0.05) & (la <= lat.max() + 0.05) & (lo >= lon.min() - 0.05) & (lo <= lon.max() + 0.05)
    ser, la, lo = ser[inside], la[inside], lo[inside]
    ilat = np.abs(lat[None, :] - la[:, None]).argmin(1)
    ilon = np.abs(lon[None, :] - lo[:, None]).argmin(1)
    cells = sorted(set(zip(ilat.tolist(), ilon.tolist())))
    cached = pd.read_pickle(cache_path) if cache_path and cache_path.exists() else None
    if cached is not None and set(cached.columns) >= set(map(str, cells)):
        grid = cached
    else:
        times = pd.DatetimeIndex(ds["time"].values)
        blocks = [ds[ref_cfg["variable"]].sel(time=str(y)).values[:, [c[0] for c in cells], [c[1] for c in cells]]
                  for y in sorted(set(times.year))]
        grid = pd.DataFrame(np.concatenate(blocks), index=times, columns=[str(c) for c in cells])
        if cache_path:
            grid.to_pickle(cache_path)
    return dict(name=ref_cfg["name"], target_lag=ref_cfg["target_lag"],
                cells={str(c): grid[str(c)] for c in cells},
                series_cell={sid: str((a, b)) for sid, a, b in zip(ser["series_id"], ilat.tolist(), ilon.tolist())})
