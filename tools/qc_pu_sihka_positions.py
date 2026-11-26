"""pu_sihka /qc, question 4: which position fits the rainfall, and how far is each post from the PU register.

1. Register: the public PU dashboard list of rain posts (Pos Curah Hujan), fetched ONCE per run into
   memory from REGISTER_URL with a generic User-Agent; the response is never written to disk (user rule,
   2026-11-25). Each compiled post is matched by normalised name (exact; else one register post of the
   same river-basin office with name similarity >= 0.88); several hits: same office first, then nearest.
   Output keeps register id, name, office and the distance only; register coordinates are written only
   for candidate rows of the posts evaluated in step 2 and for proposals.
2. Rainfall fit (method of tools/check_post_positions.py): for each post to evaluate, candidate positions
   are its distinct header positions (pubs.csv, clustered at 0.5 km) and the register position. The post's
   main series (most values, unflagged, raw dates) is correlated (best of lags -1, 0, +1, >= 200 shared
   days) with anchor series: PU posts with one position (spread <= 1 km), on land, in the right province and
   not sharing a position with another post, plus every non-PU merged site. Each candidate is scored by the
   median distance to the 3 best-correlated anchors and by Spearman rho of r against distance over all
   anchors with r; CPC r (best lag -1..+1) at the candidate is added. Decided when the best candidate is
   >= 10 km closer to the top-3 than the runner-up and the top partner has r >= 0.5.
Posts evaluated: header spread > 10 km (posts.csv), off land > 1 km, province mismatch, shared position
(q0_metadata.csv from tools/qc_pu_sihka_metadata.py), register distance > 10 km.

Output (F:/temp/station/qc_pu_sihka/): q4_register_match.csv, q4_candidates.csv, q4_decisions.csv, log q4.log
Usage: python tools/qc_pu_sihka_positions.py [--mock | --no-register]
  --mock         register built from the SIHKA posts (test of the code, no request)
  --no-register  no request; rainfall fit of header candidates only
Run log 2026-11-25: the single register request (generic User-Agent, Accept json) returned HTTP 403
(48 bytes); no second request was made, so the register comparison is not done [to verify].
"""
import difflib
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)
REGISTER_URL = "https://pdsda.sda.pu.go.id/landing-page/peta-informatif/titik?jenis=pch&page=1"
UA = "wxgrid-research-script/0.1"
DROP = r"\b(PCH|POS CURAH HUJAN|POS HUJAN|POS|CH|ARR|ARG|STA|STASIUN|PH|MRG|DAS)\b"


def nname(s):
    s = str(s or "").upper()
    s = re.sub(DROP, " ", s.replace(".", " "))
    return re.sub(r"[^A-Z0-9]", "", s)


def nname_nopar(s):
    return nname(re.sub(r"[(].*?([)]|$)", " ", str(s or "")))


def nunit(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def fetch_register():
    import requests
    r = requests.get(REGISTER_URL, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=120)
    print("register request: HTTP", r.status_code, "; bytes", len(r.content))
    if r.status_code != 200:
        return None
    return r.json()


def find_records(j):
    """Locate the list of post records in an unknown JSON layout."""
    if j is None:
        return [], {"failed": True}
    if isinstance(j, list) and j and isinstance(j[0], dict):
        return j, {}
    if isinstance(j, dict):
        info = {k: v for k, v in j.items() if not isinstance(v, (list, dict))}
        for k, v in j.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and ("nama" in v[0] or "lat" in v[0]):
                return v, info
            if isinstance(v, dict):
                rec, inf = find_records(v)
                if rec:
                    info.update(inf)
                    return rec, info
    return [], {}


def mock_register():
    p = pd.read_csv(f"{c.PU}/measure/posts.csv").dropna(subset=["lat"])
    p = p.sample(frac=0.9, random_state=1)
    jit = np.random.default_rng(1).normal(0, 0.01, (len(p), 2))
    return [dict(id=i, nama=r.name, lat=str(r.lat + a), lng=str(r.lon + b), balai=r.unit, ws="", das="", prov="")
            for i, (r, (a, b)) in enumerate(zip(p.itertuples(), jit))]


def match_register(st, reg):
    reg = reg.copy()
    reg["n1"], reg["n2"], reg["u"] = reg.nama.map(nname), reg.nama.map(nname_nopar), reg.balai.map(nunit)
    by1 = reg.groupby("n1").indices
    by2 = reg.groupby("n2").indices
    rows = []
    for r in st.itertuples():
        a, b, u = nname(r.name), nname_nopar(r.name), nunit(r.unit)
        hit = sorted(set(by1.get(a, [])) | set(by2.get(b, [])) | set(by1.get(b, [])) | set(by2.get(a, [])))
        how = "exact name"
        if not hit and len(a) >= 4:
            same = np.where(reg.u.values == u)[0]
            sc = [(difflib.SequenceMatcher(None, a, reg.n1.values[i]).ratio(), i) for i in same]
            good = [i for s, i in sc if s >= 0.88]
            if len(good) == 1:
                hit, how = good, "similar name, same office"
        if not hit:
            rows.append(dict(station_key=r.station_key, name=r.name, unit=r.unit, match="none"))
            continue
        cand = reg.iloc[hit]
        d = c.haversine_km(r.lat, r.lon, cand.lat.values, cand.lng.values)
        same_u = cand.u.values == u
        order = np.lexsort((d, ~same_u))
        k = order[0]
        rows.append(dict(station_key=r.station_key, name=r.name, unit=r.unit, match=how, n_hits=len(hit),
                         reg_id=cand.id.values[k], reg_name=cand.nama.values[k], reg_balai=cand.balai.values[k],
                         same_office=bool(same_u[k]), dist_km=round(float(d[k]), 3),
                         _lat=float(cand.lat.values[k]), _lon=float(cand.lng.values[k])))
    return pd.DataFrame(rows)


def best_r(x, Y, lags=(-1, 0, 1), min_n=200):
    """x: 1-D array (days), Y: 2-D (days, k). Max over lags of pairwise-complete Pearson r (x at day t vs
    Y at day t+L); NaN if fewer than min_n pairs."""
    idx = np.where(np.isfinite(x))[0]
    best = np.full(Y.shape[1], np.nan)
    for L in lags:
        j = idx + L
        ok = (j >= 0) & (j < len(Y))
        xs, Ys = x[idx[ok]].astype(float), Y[j[ok]].astype(float)
        m = np.isfinite(Ys)
        n = m.sum(0)
        X = np.where(m, xs[:, None], 0.0)
        Z = np.where(m, Ys, 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            sx, sy = X.sum(0), Z.sum(0)
            cov = (X * Z).sum(0) - sx * sy / n
            vx = (X * X).sum(0) - sx * sx / n
            vy = (Z * Z).sum(0) - sy * sy / n
            r = cov / np.sqrt(vx * vy)
        r[(n < min_n) | (vx <= 1e-9) | (vy <= 1e-9)] = np.nan
        best = np.fmax(best, r)
    return best


def header_candidates(pubs, iid):
    g = pubs[(pubs.integration_id == iid)].dropna(subset=["lat"])
    out = []
    for r in g.sort_values("year_cat").itertuples():
        for o in out:
            if c.haversine_km(o["lat"], o["lon"], r.lat, r.lon) <= 0.5:
                o["years"].append(int(r.year_cat))
                break
        else:
            out.append(dict(lat=r.lat, lon=r.lon, years=[int(r.year_cat)], how=r.coord_how))
    return [dict(cand="header " + ",".join(map(str, sorted(set(o["years"])))) + " (" + o["how"] + ")", lat=o["lat"], lon=o["lon"]) for o in out]


def main(mock=False, no_register=False):
    st = pd.read_csv(OUT / "q0_metadata.csv")
    pubs = pd.read_csv(f"{c.PU}/measure/pubs.csv")
    if mock:
        recs, info = mock_register(), {"mock": True}
    elif no_register:
        recs, info = [], {"skipped": "--no-register (2026-11-25 request returned HTTP 403)"}
    else:
        recs, info = find_records(fetch_register())
    reg = pd.DataFrame(recs, columns=None if recs else ["id", "nama", "lat", "lng", "balai", "ws", "das", "prov"])
    print("register records:", len(reg), "; fields", list(reg.columns), "; top-level info", info)
    reg["lat"] = pd.to_numeric(reg.lat, errors="coerce")
    reg["lng"] = pd.to_numeric(reg.lng, errors="coerce")
    reg = reg.dropna(subset=["lat", "lng"]).reset_index(drop=True)
    print("register records with numeric coordinates:", len(reg), "; distinct offices", reg.balai.nunique())
    if len(reg):
        mt = match_register(st, reg)
        print("compiled posts matched to the register:", mt.match.value_counts().to_dict())
        m = mt[mt.match != "none"]
        print("distance compiled position -> register (km):",
              pd.cut(m.dist_km, [-0.001, 0.1, 0.5, 1, 5, 10, 50, 1e5]).value_counts().sort_index().to_dict())
        print("matched in another office than the compiled unit:", int((~m.same_office.astype(bool)).sum()))
        mt.drop(columns=["_lat", "_lon"], errors="ignore").to_csv(OUT / "q4_register_match.csv", index=False)
        show = ["station_key", "name", "unit", "reg_name", "reg_balai", "dist_km"]
        pd.set_option("display.width", 250)
        pd.set_option("display.max_colwidth", 200)
        print(m[m.dist_km > 10].sort_values("dist_km", ascending=False)[show].to_string(index=False))

        regpos = m.set_index("station_key")[["_lat", "_lon", "dist_km", "reg_name"]]
    else:
        print("no register records: register comparison skipped [to verify]")
        regpos = pd.DataFrame(columns=["_lat", "_lon", "dist_km", "reg_name"])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 200)
    st = st.set_index("station_key")
    ev = set(st.index[st.spread_km > 10]) | set(st.index[~st.on_land & (st.coast_km > 1)]) | \
        set(st.index[st.prov_match == "NO"]) | set(st.index[st.same_position_as.notna()]) | set(regpos.index[regpos.dist_km > 10])
    print("posts to evaluate:", len(ev))
    w, meta = c.panel()
    vals = w.to_numpy()
    meta["n"] = np.isfinite(vals).sum(0)
    main_col = meta[meta.kind == "pu"].sort_values("n", ascending=False).drop_duplicates("station_key").set_index("station_key").col
    good = st[(st.spread_km <= 1) & st.on_land & (st.prov_match != "NO") & st.same_position_as.isna()].index
    meta["anchor"] = (meta.kind == "site") | meta.station_key.isin(good)
    cpc = c.CPCField()
    days = w.index
    rows, dec = [], []
    for sk in sorted(ev):
        if sk not in main_col.index:
            continue
        col = main_col[sk]
        x = vals[:, meta.index[meta.col == col][0]]
        cand = header_candidates(pubs, st.at[sk, "source_station_id"])
        if sk in regpos.index:
            cand.append(dict(cand="register (" + str(regpos.at[sk, "reg_name"]) + ")", lat=regpos.at[sk, "_lat"], lon=regpos.at[sk, "_lon"]))
        cand.append(dict(cand="compiled", lat=st.at[sk, "lat"], lon=st.at[sk, "lon"]))
        sp = st.at[sk, "same_position_as"]
        group = {g.split(" ")[0] for g in sp.split(";")} if isinstance(sp, str) else set()
        near_any = np.zeros(len(meta), bool)
        for cd in cand:
            near_any |= c.haversine_km(cd["lat"], cd["lon"], meta.lat.values, meta.lon.values) <= 300
        am = meta.anchor.values & near_any & (meta.station_key.values != sk) & ~meta.station_key.isin(group).values
        A = meta[am]
        r = best_r(x, vals[:, A.index.values])
        ok = np.isfinite(r)
        top = [t for t in np.argsort(np.where(ok, r, -9))[::-1][:3] if ok[t]]
        partners = "; ".join("%s r=%.2f" % (A.station_key.values[t], r[t]) for t in top)
        top_r = float(r[top[0]]) if top else np.nan
        for cd in cand:
            d = c.haversine_km(cd["lat"], cd["lon"], A.lat.values, A.lon.values)
            med = float(np.median(d[top])) if top else np.nan
            rho = spearmanr(r[ok], d[ok]).statistic if ok.sum() >= 10 else np.nan
            crs = [c.pearson(x, cpc.at(cd["lat"], cd["lon"], days, lag=L), min_n=200)[0] for L in (-1, 0, 1)]
            cr = np.nanmax(crs) if np.isfinite(crs).any() else np.nan
            rows.append(dict(station_key=sk, name=st.at[sk, "name"], unit=st.at[sk, "unit"], candidate=cd["cand"],
                             lat=round(cd["lat"], 5), lon=round(cd["lon"], 5),
                             km_from_compiled=round(float(c.haversine_km(st.at[sk, "lat"], st.at[sk, "lon"], cd["lat"], cd["lon"])), 2),
                             median_km_top3=round(med, 1), rho_r_vs_km=round(float(rho), 3) if np.isfinite(rho) else np.nan,
                             cpc_r=round(float(cr), 3) if np.isfinite(cr) else np.nan, n_anchor_r=int(ok.sum()),
                             top_r=round(top_r, 2) if np.isfinite(top_r) else np.nan, partners=partners))
    cd = pd.DataFrame(rows)
    cd.to_csv(OUT / "q4_candidates.csv", index=False)
    for sk, g in cd.groupby("station_key"):
        comp = g[g.candidate == "compiled"].iloc[0]
        g = g[g.candidate != "compiled"]
        u = g.assign(k=list(zip(g.lat.round(3), g.lon.round(3)))).drop_duplicates("k").sort_values("median_km_top3")
        verdict, best = "undecided", None
        if len(u) >= 2 and np.isfinite(u.median_km_top3.iloc[0]) and u.median_km_top3.iloc[1] - u.median_km_top3.iloc[0] >= 10 \
                and comp.top_r >= 0.5:
            best = u.iloc[0]
            verdict = "compiled fits" if best.km_from_compiled <= 0.5 else "other candidate fits"
        elif len(u) == 1:
            verdict = "single candidate"
        dec.append(dict(station_key=sk, name=comp["name"], unit=comp.unit, verdict=verdict,
                        best=None if best is None else best.candidate, best_lat=None if best is None else best.lat,
                        best_lon=None if best is None else best.lon,
                        best_km_from_compiled=None if best is None else best.km_from_compiled,
                        compiled_median_km_top3=comp.median_km_top3, best_median_km_top3=None if best is None else best.median_km_top3,
                        compiled_cpc_r=comp.cpc_r, top_r=comp.top_r, n_candidates=len(u), partners=comp.partners,
                        options="; ".join("%s %.0f km (CPC r %.2f)" % (a.candidate, a.median_km_top3, a.cpc_r) for a in u.itertuples())))
    dd = pd.DataFrame(dec)
    dd.to_csv(OUT / "q4_decisions.csv", index=False)
    print("verdicts:", dd.verdict.value_counts().to_dict())
    print(dd[["station_key", "name", "verdict", "best_km_from_compiled", "compiled_median_km_top3", "best_median_km_top3", "top_r", "options"]].to_string(index=False))


if __name__ == "__main__":
    main(mock="--mock" in sys.argv, no_register="--no-register" in sys.argv)
