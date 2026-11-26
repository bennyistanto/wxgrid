"""pu_sihka /qc, question 1: zero months and zero runs that survived rules R1 and R2.

Months are calendar months of the compiled raw date (date_raw = the reader's re-dated date, the dates R2 was
tested on). A month is complete when every calendar day has a value; all-zero when complete and no value > 0.
For every surviving all-zero month:
  cpc        CPC-UNI monthly total at the post cell (NaN: sea cell, before 1979 or after 2025)
  nb_pu      median monthly total of PU posts within 25 km (complete, not all-zero months), as the builder
  nb_other   median monthly total of non-PU merged sites within 25 km (>= 28 days with values)
Classes: >= 100 by CPC or nb_pu (should be none after R2); 50-100 band; >= 100 only by nb_other (missed by R2
because CPC and PU neighbours were dry, missing or absent); dry.
Base rate test of the 100 mm threshold: share of complete months that are all zero by CPC band, PU (after R2)
vs non-PU merged sites (BMKG family, compendium, other posts) at their own CPC cells. If non-PU gauges are
almost never all-zero in a band where PU months still are, the PU excess there is likely missing data.
Zero runs: runs of consecutive dated zeros (no gap) >= 30 days; expected rain over the run from the CPC
1991-2020 daily climatology by calendar month at the post (wet season: >= 5 mm/day); CPC and PU-neighbour
totals during the run (wet: >= 3 mm/day).

Output: F:/temp/station/qc_pu_sihka/q1_zero_months.csv, q1_base_rates.csv, q1_zero_runs.csv; log q1.log
Usage: python tools/qc_pu_sihka_zeros.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)
NB_KM = 25.0
BANDS = [-0.1, 10, 25, 50, 75, 100, 150, 200, 1e6]


def monthly_table(o, key, date):
    o = o.assign(ym=o[date].dt.to_period("M"))
    m = o.groupby([key, "ym"], observed=True).agg(n_days=(date, "nunique"), total=("value", "sum"),
                                                   n_pos=("value", lambda v: int((v > 0).sum()))).reset_index()
    m["complete"] = m.n_days >= m.ym.dt.days_in_month
    m["all_zero"] = m.complete & (m.n_pos == 0)
    return m


def cpc_monthly(cpc, t, lat, lon):
    i, j = cpc.cell(lat, lon)
    s = pd.Series(cpc.P[:, i, j], index=t)
    g = s.groupby(s.index.to_period("M"))
    return g.sum(min_count=28).where(g.count() >= 28)


def med_of(d, ks, ym):
    v = [d[(q, ym)] for q in ks if (q, ym) in d]
    return (float(np.median(v)) if v else np.nan), len(v)


def main():
    o = c.pu_obs()
    o = o[o.value.notna()]
    st = c.pu_stations().set_index("station_key")
    mo = monthly_table(o, "series_id", "date_raw")
    mo["station_key"] = mo.series_id.astype(str).str.rsplit(":", n=2).str[0]
    cpc = c.CPCField()
    t = pd.date_range(cpc.t0, periods=cpc.nt, freq="D")
    cm = {sk: cpc_monthly(cpc, t, st.at[sk, "lat"], st.at[sk, "lon"]) for sk in st.index}
    mo["cpc"] = [float(cm[k].get(ym, np.nan)) for k, ym in zip(mo.station_key, mo.ym)]
    ok = mo[mo.complete & ~mo.all_zero].groupby(["station_key", "ym"]).total.max().to_dict()
    keys = list(st.index)
    la, lo = st.lat.values, st.lon.values
    nbp = {}
    for i, k in enumerate(keys):
        d = c.haversine_km(la[i], lo[i], la, lo)
        nbp[k] = [keys[j] for j in np.where((d <= NB_KM) & (np.arange(len(keys)) != i))[0]]
    m = c.merged()
    m = m[~m.series_id.astype(str).str.startswith("pu_sihka:") & m.value.notna()]
    sm = m.assign(ym=m.date.dt.to_period("M")).groupby(["site_id", "ym"], observed=True).agg(
        n=("value", "size"), total=("value", "sum"), npos=("value", lambda v: int((v > 0).sum()))).reset_index()
    sm["site_id"] = sm.site_id.astype(str)
    sx = c.site_xy().set_index("site_id")
    sm = sm[sm.site_id.isin(sx.index)]
    pu_sites = set(st.site_id.dropna())
    smd = sm[(sm.n >= 28) & ~sm.site_id.isin(pu_sites)].set_index(["site_id", "ym"]).total.to_dict()
    sids, sla, slo = sx.index.values, sx.lat.values, sx.lon.values
    nbo = {}
    for k in keys:
        d = c.haversine_km(st.at[k, "lat"], st.at[k, "lon"], sla, slo)
        nbo[k] = [s for s in sids[d <= NB_KM] if s not in pu_sites]
    z = mo[mo.all_zero].copy()
    r1 = [med_of(ok, nbp[k], ym) for k, ym in zip(z.station_key, z.ym)]
    r2 = [med_of(smd, nbo[k], ym) for k, ym in zip(z.station_key, z.ym)]
    z["nb_pu"], z["n_nb_pu"] = [a for a, b in r1], [b for a, b in r1]
    z["nb_other"], z["n_nb_other"] = [a for a, b in r2], [b for a, b in r2]
    a = np.fmax(z.cpc.fillna(-1), z.nb_pu.fillna(-1))
    z["cls"] = np.select([a >= 100, z.nb_other >= 100, a >= 50], ["ge100_cpc_or_pu", "ge100_other_sources_only", "band_50_100"], "dry")
    print("complete months", int(mo.complete.sum()), "; all-zero complete months surviving R1/R2:", len(z),
          "in", z.series_id.nunique(), "series;", int(z.ym.dt.year.ge(1979).sum()), "from 1979")
    print("classes:", z.cls.value_counts().to_dict())
    b = z[z.cls == "band_50_100"]
    print("band 50-100: CPC >= 50", int((b.cpc >= 50).sum()), "; PU neighbours >= 50", int((b.nb_pu >= 50).sum()),
          "; both", int(((b.cpc >= 50) & (b.nb_pu >= 50)).sum()), "; CPC 75-100", int(b.cpc.between(75, 100).sum()))
    g = z[z.cls == "ge100_other_sources_only"]
    print("missed by R2 (non-PU sites within 25 km >= 100 mm):", len(g), "; CPC missing", int(g.cpc.isna().sum()),
          "; no PU neighbour month", int(g.nb_pu.isna().sum()), "; CPC < 50", int((g.cpc < 50).sum()))
    print("dry class with no reference at all (CPC NaN, no PU or other neighbour):",
          int(((z.cls == "dry") & z.cpc.isna() & z.nb_pu.isna() & z.nb_other.isna()).sum()))
    print("surviving all-zero months by CPC band:", pd.cut(z.cpc, BANDS).value_counts().sort_index().to_dict(), "; CPC missing", int(z.cpc.isna().sum()))
    print("surviving all-zero months by calendar month:", z.ym.dt.month.value_counts().sort_index().to_dict())
    z.to_csv(OUT / "q1_zero_months.csv", index=False)

    pu_c = mo[mo.complete & mo.ym.dt.year.between(1979, 2025)].copy()
    sm["complete"] = sm.n >= sm.ym.dt.days_in_month
    sb = sm[sm.complete & sm.ym.dt.year.between(1979, 2025) & ~sm.site_id.isin(pu_sites)].copy()
    sb["all_zero"] = sb.npos == 0
    scm = {s: cpc_monthly(cpc, t, sx.at[s, "lat"], sx.at[s, "lon"]) for s in sb.site_id.unique()}
    sb["cpc"] = [float(scm[s].get(ym, np.nan)) for s, ym in zip(sb.site_id, sb.ym)]
    pre = pd.read_csv(f"{c.PU}/measure/m1_months.csv")
    pre = pre[(pre.n_days >= pre.days_in_month) & pre.ym.str[:4].astype(int).between(1979, 2025)]
    rows = []
    for nm, d in (("PU before R1/R2", pre), ("PU compiled", pu_c), ("non-PU sites", sb)):
        gg = d.groupby(pd.cut(d.cpc, BANDS), observed=False)["all_zero"].agg(["size", "sum"])
        for band, r in gg.iterrows():
            rows.append(dict(set=nm, cpc_band=str(band), months=int(r["size"]), all_zero=int(r["sum"]),
                             pct_all_zero=round(100 * r["sum"] / r["size"], 2) if r["size"] else np.nan))
    br = pd.DataFrame(rows)
    br.to_csv(OUT / "q1_base_rates.csv", index=False)
    print("percent of complete months all zero, by CPC monthly band (1979-2025; PU before R1/R2 from m1_months.csv):")
    print(br.pivot(index="cpc_band", columns="set", values="pct_all_zero").to_string())
    print(br.pivot(index="cpc_band", columns="set", values="months").to_string())
    nb = br[br.set == "non-PU sites"].set_index("cpc_band").pct_all_zero
    pc = br[br.set == "PU compiled"].set_index("cpc_band")
    print("PU compiled all-zero months in excess of the non-PU rate, by CPC band:", (pc.all_zero - pc.months * nb / 100).round(0).to_dict())
    runs(o, st, cpc, t, nbp)


def runs(o, st, cpc, t, nbp):
    o = o.sort_values(["series_id", "date_raw"]).drop_duplicates(["series_id", "date_raw"])
    o["station_key"] = o.series_id.astype(str).str.rsplit(":", n=2).str[0]
    o1 = o.drop_duplicates(["station_key", "date_raw"])
    wide = {k: g.set_index("date_raw").value for k, g in o1.groupby("station_key")}
    clim = {}
    rows = []
    for sid, g in o.groupby("series_id", observed=True):
        sk = str(sid).rsplit(":", 2)[0]
        d = g.date_raw.to_numpy()
        z = (g.value.to_numpy() == 0)
        brk = np.r_[True, (np.diff(d).astype("timedelta64[D]").astype(int) != 1) | (z[1:] != z[:-1])]
        rid = np.cumsum(brk)
        for k in np.unique(rid[z]):
            idx = np.where(rid == k)[0]
            if len(idx) < 30:
                continue
            d0, d1 = pd.Timestamp(d[idx[0]]), pd.Timestamp(d[idx[-1]])
            days = pd.date_range(d0, d1, freq="D")
            if sk not in clim:
                i, j = cpc.cell(st.at[sk, "lat"], st.at[sk, "lon"])
                s = pd.Series(cpc.P[:, i, j], index=t)
                s = s["1991":"2020"]
                clim[sk] = s.groupby(s.index.month).mean()
            exp = float(clim[sk].reindex(days.month).sum()) if clim[sk].notna().any() else np.nan
            ca = cpc.at(st.at[sk, "lat"], st.at[sk, "lon"], days, lag=0)
            cpc_sum = float(np.nansum(ca)) if np.isfinite(ca).mean() >= 0.9 else np.nan
            nbs = []
            for q in nbp[sk]:
                w = wide[q].reindex(days)
                if w.notna().mean() >= 0.9:
                    nbs.append(float(w.sum()))
            months = pd.period_range(d0, d1, freq="M")
            full = [p for p in months if p.start_time >= d0 and p.end_time.normalize() <= d1]
            rows.append(dict(series_id=sid, station_key=sk, start=d0.date(), end=d1.date(), days=len(idx), complete_months_inside=len(full),
                             expected_cpc_clim=round(exp, 1), cpc_sum=round(cpc_sum, 1) if np.isfinite(cpc_sum) else np.nan,
                             nb_pu_median=round(float(np.median(nbs)), 1) if nbs else np.nan, n_nb=len(nbs)))
    r = pd.DataFrame(rows)
    # wet season: CPC climatology over the run >= 5 mm/day (150 mm/month, the M1 wet-month mark);
    # refs wet: CPC or the PU-neighbour median >= 3 mm/day during the run (about 90 mm/month)
    r["wet_season"] = r.expected_cpc_clim / r.days >= 5
    r["wet_refs"] = (r.cpc_sum / r.days >= 3) | (r.nb_pu_median / r.days >= 3)
    r.to_csv(OUT / "q1_zero_runs.csv", index=False)
    print("zero runs >= 30 days (consecutive dated zeros):", len(r), "in", r.series_id.nunique(), "series; days", int(r.days.sum()))
    print("  in the wet season (CPC 1991-2020 climatology >= 5 mm/day over the run):", int(r.wet_season.sum()),
          "; of which CPC or PU neighbours had >= 3 mm/day during the run:", int((r.wet_season & r.wet_refs).sum()),
          "(days", int(r[r.wet_season & r.wet_refs].days.sum()), ")")
    print("  wet-season runs with no complete calendar month inside (R2 could not see them):", int((r.wet_season & (r.complete_months_inside == 0)).sum()),
          "; of those wet by refs:", int((r.wet_season & r.wet_refs & (r.complete_months_inside == 0)).sum()))
    print("  run length:", r.days.describe().round(0).to_dict())
    print(r[r.wet_season & r.wet_refs].sort_values("days", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
