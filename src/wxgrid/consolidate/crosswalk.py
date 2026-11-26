"""Station crosswalk: which stations from different sources are the same site.

Proposes relations for review; it never deletes a station or a series.

Per candidate pair (within `max_km`):
- distance, normalised-name similarity (rapidfuzz token_set_ratio), elevation difference;
- for the check variable (RR), every series pair is compared at lags -1, 0, +1 day:
  overlap days, Pearson r, share of exactly equal values, ratio of totals. A best lag
  other than 0 means the two sources label days differently.

Relations:
- `duplicate_data`: the best series pair is near-identical (equal share >= threshold);
- `same_site`: within `same_site_km`, or within `name_match_km` with similar names, or
  the same WMO station number;
- `colocated_same_source`: same provider, within `same_site_km`; never merged;
- `different_provider`: one station's source is in a `crosswalk.provider_groups` group and the
  other's is not in the same group (e.g. PU rain posts vs BMKG stations, user 2026-11-25); never
  merged automatically, however close, and not reviewed (a user `join` override still applies).
  Sources in `crosswalk.neutral_sources` (e.g. the ASEAN compendium, which carries both BMKG
  stations and rain posts) may join either side, but a site never holds stations of two camps.
  A source in `crosswalk.isolated_sources` (e.g. the KNMI Dutch-era sheets, user 2026-11-26) is
  `different_provider` to every other source, neutral ones included, so its stations stay their own
  sites unless a user `join` override says otherwise;
- `nearby`: anything else within `max_km`.
`needs_review` is set when a would-be merge has a non-zero best lag or low correlation.
Different WMO numbers make a pair `nearby` however close. An automatic join refused because
a stronger link already placed a station with another station of the same provider is
`superseded`, not reviewed; a refused user join stays in review. `decision` records
auto_join / user_join / user_separate / review / none; user decisions come from
`crosswalk.overrides` in the config.
"""

import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def norm_name(s, drop_words):
    s = re.sub(r"[^A-Z0-9 ]", " ", str(s).upper())
    for w in sorted(drop_words, key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(w.upper())}\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def candidate_pairs(stations, max_km):
    """Pairs within `max_km`, plus pairs sharing a WMO number at any distance (a source
    can carry stale coordinates for a station, findings F26)."""
    lat, lon = stations["lat"].to_numpy(), stations["lon"].to_numpy()
    d = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    w = stations["wmo_id"].astype(str).str.strip().replace({"nan": ""}).to_numpy()
    same_wmo = (w[:, None] == w[None, :]) & (w[:, None] != "")
    i, j = np.where(np.triu((d <= max_km) | same_wmo, k=1))
    return i, j, d[i, j]


def pair_stats(a, b, lags, equal_tol):
    """a, b: Series of values indexed by date. b is shifted by `lag` days before matching."""
    out = []
    for lag in lags:
        bb = b.copy()
        bb.index = bb.index + pd.Timedelta(days=lag)
        x, y = a.align(bb, join="inner")
        n = len(x)
        r = float(np.corrcoef(x, y)[0, 1]) if n >= 3 and x.std() > 0 and y.std() > 0 else np.nan
        eq = float((np.abs(x - y) <= equal_tol).mean()) if n else np.nan
        ratio = float(y.sum() / x.sum()) if n and x.sum() > 0 else np.nan
        out.append(dict(lag=lag, n_overlap=n, r=r, equal_frac=eq, ratio=ratio))
    return out


def summarise(stats):
    """Collapse per-lag stats to one row: lag-0 values, best lag by r, and per-lag r."""
    at0 = next(s for s in stats if s["lag"] == 0)
    top = max(stats, key=lambda s: np.nan_to_num(s["r"], nan=-np.inf))
    return dict(best_lag=top["lag"], n_overlap=at0["n_overlap"], r_lag0=at0["r"], r_best=top["r"],
                equal_frac_best=top["equal_frac"], ratio_best=top["ratio"],
                **{f"r_lag{s['lag']:+d}": s["r"] for s in stats})


def passes(row, cw):
    """Mergeable evidence: same day label (best lag 0) and r at lag 0 >= r_min."""
    return row["best_lag"] == 0 and row["r_lag0"] >= cw["r_min"]


class _Sites:
    """Union-find that refuses to join two components holding the same provider, two
    components that would put a user-separated pair into one site (separations hold
    transitively, not only for the direct pair), or two components whose providers are
    in different camps (`camp_of`: a provider group name, "" for any other source, None for
    a neutral source that may sit with either)."""

    def __init__(self, keys, source_of, separated=(), camp_of=None):
        self.parent = {k: k for k in keys}
        self.sources = {k: {source_of[k]} for k in keys}
        camp_of = camp_of or (lambda s: "")
        self.camps = {k: ({camp_of(source_of[k])} - {None}) for k in keys}
        self.members = {k: {k} for k in keys}
        self.apart = {}
        for a, b in separated:
            self.apart.setdefault(a, set()).add(b)
            self.apart.setdefault(b, set()).add(a)
        self.last_refusal = ""

    def find(self, k):
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if self.sources[ra] & self.sources[rb]:
            self.last_refusal = "would join two stations of one provider"
            return False
        if any(self.apart.get(m, set()) & self.members[rb] for m in self.members[ra]):
            self.last_refusal = "would join stations the user separated"
            return False
        if len(self.camps[ra] | self.camps[rb]) > 1:
            self.last_refusal = "would join stations of different provider groups"
            return False
        self.parent[rb] = ra
        self.sources[ra] |= self.sources.pop(rb)
        self.camps[ra] |= self.camps.pop(rb)
        self.members[ra] |= self.members.pop(rb)
        return True


def _apply_overrides(pairs, overrides, known=None):
    """User decisions from the config: `join` / `separate` lists of [station_a, station_b].
    They replace the automatic decision and clear needs_review. A station key that does not
    exist raises, so a typo cannot silently do nothing. A `separate` pair whose stations both
    exist but are no longer candidates (e.g. coordinates corrected since the decision) is
    already separate: it is skipped and returned as stale. A stale `join` still raises."""
    stale = []
    if not len(pairs):
        return stale
    key = {frozenset(k): i for i, k in enumerate(zip(pairs["station_a"], pairs["station_b"]))}
    for decision, items in (("user_join", overrides.get("join", [])), ("user_separate", overrides.get("separate", []))):
        for a, b in items:
            i = key.get(frozenset((a, b)))
            if i is None:
                if known is not None and decision == "user_separate" and a in known and b in known:
                    stale.append([a, b])
                    print(f"  [crosswalk] stale separate override (no longer a candidate pair): {a}, {b}")
                    continue
                raise ValueError(f"override pair not among candidate pairs: {a}, {b}")
            idx = pairs.index[i]
            pairs.at[idx, "decision"] = decision
            pairs.at[idx, "needs_review"] = False
            pairs.at[idx, "review_reason"] = ""
    return stale


def build(stations, series, obs, cfg):
    cw = cfg["crosswalk"]
    var, lags = cw["check_variable"], cw.get("lags", [-1, 0, 1])
    st = stations.reset_index(drop=True)
    i, j, dist = candidate_pairs(st, cw["max_km"])
    group_of = {s: g for g, members in (cw.get("provider_groups") or {}).items() for s in members}
    neutral = set(cw.get("neutral_sources") or [])
    isolated = set(cw.get("isolated_sources") or [])

    def camp_of(source):
        if source in isolated:
            return f"isolated:{source}"
        return None if source in neutral else group_of.get(source, "")

    # values of the check variable, per series, unflagged only
    ser = series[series["variable"] == var]
    o = obs[obs["series_id"].isin(ser["series_id"]) & obs["flag"].eq("")]
    vals = {sid: g.set_index("date")["value"] for sid, g in o.groupby("series_id")}
    by_station = ser.groupby("station_key")["series_id"].apply(list).to_dict()

    station_rows, series_rows = [], []
    for a, b, d in zip(i, j, dist):
        sa, sb = st.loc[a], st.loc[b]
        sim = fuzz.token_set_ratio(norm_name(sa["name"], cw["drop_words"]), norm_name(sb["name"], cw["drop_words"]))
        rows = []
        for x in by_station.get(sa["station_key"], []):
            for y in by_station.get(sb["station_key"], []):
                if x in vals and y in vals:
                    rows.append(dict(series_a=x, series_b=y, **summarise(pair_stats(vals[x], vals[y], lags, cw["equal_tol"]))))
        series_rows += [dict(station_a=sa["station_key"], station_b=sb["station_key"], **r) for r in rows]

        # Judge the station pair on its best evidence, not on its longest overlap: one
        # station can carry a matching participant series and a mismatched SYNOP series.
        tested = [r for r in rows if r["n_overlap"] >= cw["min_overlap_days"]]
        passing = [r for r in tested if passes(r, cw)]
        best = max(passing or tested or rows, key=lambda r: np.nan_to_num(r["r_lag0"], nan=-1), default=None)
        evidence = "pass" if passing else ("fail" if tested else "none")
        same_source = sa["source"] == sb["source"]
        wa, wb = str(sa["wmo_id"]).strip(), str(sb["wmo_id"]).strip()
        wmo = wa not in ("", "nan") and wa == wb
        # two different WMO numbers are two different stations, however close
        wmo_differs = wa not in ("", "nan") and wb not in ("", "nan") and wa != wb
        dup = any(r["equal_frac_best"] >= cw["duplicate_equal_frac"] for r in tested)
        ga, gb = camp_of(sa["source"]), camp_of(sb["source"])
        if same_source:
            rel = "colocated_same_source" if d <= cw["same_site_km"] else "nearby"
        elif sa["source"] in isolated or sb["source"] in isolated or (ga is not None and gb is not None and ga != gb):
            rel = "different_provider"
        elif wmo_differs:
            rel = "nearby"
        elif dup:
            rel = "duplicate_data"
        elif wmo or d <= cw["same_site_km"] or (d <= cw["name_match_km"] and sim >= cw["name_sim_min"]):
            rel = "same_site"
        else:
            rel = "nearby"
        # A shared WMO station number settles identity; disagreeing data at such a pair is
        # a day-label or reporting issue, handled by the merge filler test, not a reason to
        # keep the stations apart.
        far_wmo = wmo and d > cw["max_km"]
        if far_wmo and rel == "nearby":
            rel = "same_site"
        review = (rel in ("duplicate_data", "same_site") and evidence == "fail" and not wmo) or far_wmo
        reason = ""
        if far_wmo:
            reason = f"same WMO number but {d:.0f} km apart"
        elif review:
            reason = "best lag not 0" if best["best_lag"] != 0 else "low correlation at lag 0"
        station_rows.append(dict(
            station_a=sa["station_key"], station_b=sb["station_key"], name_a=sa["name"], name_b=sb["name"],
            dist_km=round(float(d), 3), name_sim=round(sim, 1),
            elev_diff_m=float(sb["elev_m"] - sa["elev_m"]) if pd.notna(sa["elev_m"]) and pd.notna(sb["elev_m"]) else np.nan,
            relation=rel, wmo_match=wmo, evidence=evidence, needs_review=bool(review), review_reason=reason,
            n_series_pairs=len(rows), n_tested=len(tested), n_passing=len(passing),
            **({k: best[k] for k in ("series_a", "series_b", "best_lag", "n_overlap", "r_lag0", "r_best",
                                     "equal_frac_best", "ratio_best")} if best else {})))
    pairs = pd.DataFrame(station_rows)
    pairs["decision"] = np.where(pairs["relation"].isin(["duplicate_data", "same_site"]) & ~pairs["needs_review"],
                                 "auto_join", np.where(pairs["needs_review"], "review", "none")) if len(pairs) else []
    stale = _apply_overrides(pairs, cw.get("overrides", {}), known=set(stations["station_key"]))
    pairs.attrs["stale_overrides"] = stale

    # Sites: join stations along accepted relations. Pairs with passing data evidence go
    # first, then by name similarity, then distance, so a co-located but differently
    # named station does not capture the wrong partner.
    sep = [tuple(p) for p in cw.get("overrides", {}).get("separate", [])]
    sites = _Sites(st["station_key"], dict(zip(st["station_key"], st["source"])), separated=sep, camp_of=camp_of)
    if len(pairs):
        ok = pairs["decision"].isin(["auto_join", "user_join"])
        # user decisions first, then WMO number match, then passing data evidence, then
        # name similarity, then distance
        order = pairs[ok].assign(_u=pairs["decision"].ne("user_join"), _w=~pairs["wmo_match"],
                                 _e=pairs["evidence"].ne("pass")).sort_values(
            ["_u", "_w", "_e", "name_sim", "dist_km"], ascending=[True, True, True, False, True]).index
        for idx in order:
            if not sites.union(pairs.at[idx, "station_a"], pairs.at[idx, "station_b"]):
                # A stronger link (user join, WMO match, or better evidence, all processed
                # earlier) already placed one of them with another station of this provider.
                # User joins that are refused stay in review; automatic ones are superseded.
                user = pairs.at[idx, "decision"] == "user_join"
                pairs.at[idx, "needs_review"] = bool(user)
                pairs.at[idx, "decision"] = "review" if user else "superseded"
                pairs.at[idx, "review_reason"] = sites.last_refusal
    root = {k: sites.find(k) for k in st["station_key"]}
    if len(pairs):
        # A review pair whose two stations ended up in one site anyway (through a shared
        # partner) needs no decision of its own.
        same = pairs["station_a"].map(root) == pairs["station_b"].map(root)
        hit = same & pairs["decision"].eq("review")
        pairs.loc[hit, ["decision", "needs_review", "review_reason"]] = ["joined_via_site", False, ""]
    return pairs, pd.DataFrame(series_rows), root
