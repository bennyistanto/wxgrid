"""pu_sihka /qc, question 6: PU series that copy another PU series (same values on most wet days).

Per calendar year (raw dates, all values incl. provider-flagged), every pair of PU series is compared at
lags -1, 0, +1: wet days = days where both have a value and at least one is > 0; equal = |a - b| <= 0.5 mm.
A pair-year is a copy candidate when it has >= 30 wet days and >= 90% of them equal at one lag; pairs with
60-90% are listed as partial. Pairs of the same post (different gauge types) are reported apart.
Distance, river-basin office (unit) and the shared-position flag (q0_metadata.csv) are added.

Which side is the original: the copied year is correlated (best lag -1..+1, all days of the year) with CPC at
each post cell and with the median of each post own PU neighbours within 25 km (the partner excluded); the
side with the higher mean of the two r by >= 0.1 is taken as the original, otherwise undecided.

Output: F:/temp/station/qc_pu_sihka/q6_copy_pair_years.csv, q6_copy_pairs.csv, q6_copy_sides.csv; log q6.log
Usage: python tools/qc_pu_sihka_copies.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)


def main():
    o = c.pu_obs()
    o = o[o.value.notna()].drop_duplicates(["series_id", "date_raw"])
    o["sid"] = o.series_id.astype(str)
    md = pd.read_csv(OUT / "q0_metadata.csv").set_index("station_key")
    rows = []
    for y, g in o.groupby(o.date_raw.dt.year):
        w = g.pivot(index="date_raw", columns="sid", values="value").reindex(pd.date_range(f"{y}-01-01", f"{y}-12-31"))
        if w.shape[1] < 2:
            continue
        X = w.to_numpy(float)
        P = np.isfinite(X)
        X0 = np.where(P, X, -999.0)
        cols = list(w.columns)
        k = len(cols)
        for L in (-1, 0, 1):
            if L > 0:
                A, B, PA, PB = X0[:-L], X0[L:], P[:-L], P[L:]
            elif L < 0:
                A, B, PA, PB = X0[-L:], X0[:L], P[-L:], P[:L]
            else:
                A, B, PA, PB = X0, X0, P, P
            for i in range(k):
                both = PA[:, [i]] & PB
                wet = both & ((A[:, [i]] > 0) | (B > 0))
                nw = wet.sum(0)
                eq = (wet & (np.abs(A[:, [i]] - B) <= 0.5)).sum(0)
                for j in np.where((nw >= 30) & (eq >= 0.6 * nw))[0]:
                    if j == i or (L == 0 and j < i):
                        continue
                    rows.append(dict(year=y, a=cols[i], b=cols[j], lag=L, n_wet=int(nw[j]), n_equal=int(eq[j]), equal_frac=round(eq[j] / nw[j], 3)))
    d = pd.DataFrame(rows)
    d = d.sort_values("equal_frac", ascending=False).drop_duplicates(["year", "a", "b"])
    key = d.apply(lambda r: tuple(sorted([r.a, r.b])), axis=1)
    d["pair"] = key
    d = d.sort_values("equal_frac", ascending=False).drop_duplicates(["year", "pair"])
    d["sa"] = d.a.str.rsplit(":", n=2).str[0]
    d["sb"] = d.b.str.rsplit(":", n=2).str[0]
    d["same_post"] = d.sa == d.sb
    d["km"] = [round(float(c.haversine_km(md.at[a, "lat"], md.at[a, "lon"], md.at[b, "lat"], md.at[b, "lon"])), 2) for a, b in zip(d.sa, d.sb)]
    d["name_a"] = d.sa.map(md["name"])
    d["name_b"] = d.sb.map(md["name"])
    d["unit_a"] = d.sa.map(md["unit"])
    d["unit_b"] = d.sb.map(md["unit"])
    d["same_unit"] = d.unit_a == d.unit_b
    d = d.drop(columns="pair")
    d.to_csv(OUT / "q6_copy_pair_years.csv", index=False)
    cp = d[d.equal_frac >= 0.9]
    print("pair-years with >= 30 wet days and >= 60% equal:", len(d), "; >= 90% (copies):", len(cp))
    print("copies: same post (different gauge types)", int(cp.same_post.sum()), "; different posts", int((~cp.same_post).sum()),
          "; of which same office", int((~cp.same_post & cp.same_unit).sum()), "; different office", int((~cp.same_post & ~cp.same_unit).sum()))
    print("copies by lag:", cp.lag.value_counts().to_dict())
    p = d[~d.same_post].groupby(["sa", "sb"]).agg(name_a=("name_a", "first"), name_b=("name_b", "first"), unit_a=("unit_a", "first"),
                                                  unit_b=("unit_b", "first"), km=("km", "first"), years=("year", lambda v: ",".join(map(str, sorted(v)))),
                                                  n_years_ge90=("equal_frac", lambda v: int((v >= 0.9).sum())), max_equal=("equal_frac", "max"),
                                                  lags=("lag", lambda v: ",".join(map(str, sorted(set(v)))))).reset_index()
    p.to_csv(OUT / "q6_copy_pairs.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 60)
    print("different-post pairs with any copy year (>= 90%):", int((p.n_years_ge90 > 0).sum()))
    print(p[p.n_years_ge90 > 0].sort_values(["n_years_ge90", "max_equal"], ascending=False).to_string(index=False))
    print("partial (60-90%, no copy year):", int((p.n_years_ge90 == 0).sum()))
    print(p[p.n_years_ge90 == 0].sort_values("max_equal", ascending=False).head(15).to_string(index=False))
    which_is_original(d[(d.equal_frac >= 0.9) & ~d.same_post], md)
    sp = d[d.same_post]
    print("same-post pairs (gauge types):", sp.groupby(["sa"]).size().shape[0], "posts;", "pair-years", len(sp), "; >= 90%", int((sp.equal_frac >= 0.9).sum()))


def which_is_original(cp, md):
    w, meta = c.panel()
    vals = w.to_numpy()
    cpc = c.CPCField()
    o = c.pu_obs()
    o = o[o.value.notna()].drop_duplicates(["series_id", "date_raw"])
    rows = []
    for r in cp.itertuples():
        days = pd.date_range(f"{r.year}-01-01", f"{r.year}-12-31")
        x = o[(o.series_id == r.a) & (o.date_raw.dt.year == r.year)].set_index("date_raw").value.reindex(days).to_numpy(float)
        res = {}
        for side, sk, other in (("a", r.sa, r.sb), ("b", r.sb, r.sa)):
            la, lo = md.at[sk, "lat"], md.at[sk, "lon"]
            rc = [c.pearson(x, cpc.at(la, lo, days, lag=L), min_n=100)[0] for L in (-1, 0, 1)]
            rc = np.nanmax(rc) if np.isfinite(rc).any() else np.nan
            d = c.haversine_km(la, lo, meta.lat.values, meta.lon.values)
            sel = np.where((d <= 25) & (meta.kind.values == "pu") & ~meta.station_key.isin([sk, other]).values)[0]
            rn = np.nan
            if len(sel):
                k = w.index.get_indexer(days)
                okk = k >= 0
                with np.errstate(all="ignore"):
                    import warnings
                    warnings.simplefilter("ignore", RuntimeWarning)
                    m = np.full(len(days), np.nan)
                    m[okk] = np.nanmedian(vals[k[okk]][:, sel], axis=1)
                rn = c.pearson(x, m, min_n=100)[0]
            res[side] = (rc, rn, len(sel))
        sa = np.nanmean(res["a"][:2]) if np.isfinite(res["a"][:2]).any() else np.nan
        sb = np.nanmean(res["b"][:2]) if np.isfinite(res["b"][:2]).any() else np.nan
        orig = "undecided"
        if np.isfinite(sa) and np.isfinite(sb) and abs(sa - sb) >= 0.1:
            orig = r.sa if sa > sb else r.sb
        rows.append(dict(year=r.year, a=r.a, name_a=r.name_a, b=r.b, name_b=r.name_b, km=r.km, equal_frac=r.equal_frac, n_wet=r.n_wet,
                         r_cpc_a=res["a"][0], r_nb_a=res["a"][1], n_nb_a=res["a"][2], r_cpc_b=res["b"][0], r_nb_b=res["b"][1], n_nb_b=res["b"][2],
                         score_a=sa, score_b=sb, original=orig,
                         copy=(r.b if orig == r.sa else r.a if orig == r.sb else "both?")))
    s = pd.DataFrame(rows).round(3)
    s.to_csv(OUT / "q6_copy_sides.csv", index=False)
    print("copy pair-years:", len(s), "; original decided", int((s.original != "undecided").sum()), "; undecided", int((s.original == "undecided").sum()))
    print(s[["year", "name_a", "name_b", "km", "r_cpc_a", "r_nb_a", "r_cpc_b", "r_nb_b", "original"]].to_string(index=False))


if __name__ == "__main__":
    main()
