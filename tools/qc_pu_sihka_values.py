"""pu_sihka /qc, questions 2 and 3 plus checks 2 (sentinel codes), 3 (accumulations) and 6 (outliers).

All on compiled PU values (raw dates) with the reference values of qc_pu_sihka_common.refs():
CPC at D and max over D-1..D+1, PU neighbours within 25 km (3-day max per neighbour; median and max),
non-PU merged sites within 25 km (max over D-1..D+2).
  sentinels     exact values >= 100 mm by frequency, and the share of each value relative to its neighbours
                (value - 1, value + 1): heaping or codes
  Q2 > 500 mm   each value with references, the post own 99th percentile, the days before and after
                (missing or not), and the value / 10 against the references (decimal-point hypothesis)
  Q2 = 100 mm   the 100 mm days against control values 95-99 and 101-105: share with dry references
                (CPC 3-day max < 5 mm and PU-neighbour 3-day max < 5 mm, or no neighbour), concentration
  Q3 flags      src_suspect, src_unrealistic vs unflagged: zero share, zero when CPC >= 10 mm, wet (>= 20 mm)
                when CPC < 1 mm, and per series daily r with CPC (best lag -1..+1) in flagged vs unflagged days
  accumulations value >= own 95th percentile of wet days directly after >= 2 missing days inside the series span
  outliers      value >= 100 mm while CPC 3-day max < 10 mm and every neighbour 3-day max < 10 mm (isolated);
                value > 3 x own 99.9th percentile of wet days
Output: F:/temp/station/qc_pu_sihka/q2_above_500.csv, q2_value_100.csv, q2_repeats.csv, q3_flags.csv,
        q3_flag_series.csv, q36_value_flags.csv (one row per flagged value: series_id, date_raw, value, flag kinds); log q2.log
Usage: python tools/qc_pu_sihka_values.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)


def prep():
    r = c.refs()
    r["flag"] = r.flag.astype(str)
    r["sid"] = r.series_id.astype(str)
    r = r[r.value.notna()].sort_values(["sid", "date_raw"]).reset_index(drop=True)
    r["refdry"] = (r.cpc3max.fillna(0) < 5) & (r.pu_max3.fillna(0) < 5) & (r.site_max4.fillna(0) < 5)
    r["has_ref"] = r.cpc3max.notna() | (r.pu_n > 0) | (r.site_n > 0)
    wet = r[r.value > 0]
    p95 = wet.groupby("sid").value.quantile(0.95)
    p99 = wet.groupby("sid").value.quantile(0.99)
    p999 = wet.groupby("sid").value.quantile(0.999)
    r["p99"] = r.sid.map(p99)
    # previous and next day in the same series
    same_prev = r.sid.eq(r.sid.shift())
    same_next = r.sid.eq(r.sid.shift(-1))
    gap_prev = np.where(same_prev, (r.date_raw - r.date_raw.shift()).dt.days - 1, -1)
    gap_next = np.where(same_next, (r.date_raw.shift(-1) - r.date_raw).dt.days - 1, -1)
    r["missing_before"] = gap_prev
    r["missing_after"] = gap_next
    r["prev_value"] = np.where(same_prev & (gap_prev == 0), r.value.shift(), np.nan)
    r["next_value"] = np.where(same_next & (gap_next == 0), r.value.shift(-1), np.nan)

    # ---------- sentinels / repeats
    vc = r[r.value >= 100].value.value_counts()
    rep = pd.DataFrame({"value": vc.index, "n": vc.values})
    allvc = r.value.value_counts()
    rep["n_minus1"] = rep.value.map(lambda v: int(allvc.get(v - 1, 0)))
    rep["n_plus1"] = rep.value.map(lambda v: int(allvc.get(v + 1, 0)))
    rep["heap_ratio"] = (rep.n / ((rep.n_minus1 + rep.n_plus1) / 2).replace(0, np.nan)).round(2)
    rep["n_posts"] = rep.value.map(r[r.value >= 100].groupby("value").sid.nunique())
    rep.sort_values("n", ascending=False).to_csv(OUT / "q2_repeats.csv", index=False)
    print("values >= 100 mm:", int((r.value >= 100).sum()), "; distinct", len(rep))
    print("most frequent exact values >= 100 mm (n, n at value-1, n at value+1, heap ratio, posts):")
    print(rep.sort_values("n", ascending=False).head(15).to_string(index=False))
    for v in (888, 999, 8888, 9999):
        print("value", v, ":", int((r.value == v).sum()))
    print("non-integer values:", int((r.value % 1 != 0).sum()), "; negative:", int((r.value < 0).sum()))
    return r, p95, p999


def ref_max(df):
    return np.fmax(np.fmax(df.cpc3max.fillna(-1), df.pu_max3.fillna(-1)), df.site_max4.fillna(-1)).replace(-1, np.nan)


def q2_big(r):
    b = r[r.value > 500].copy()
    b["ref_max"] = ref_max(b)
    b["ratio_ref"] = (b.ref_max / b.value).round(3)
    b["tenth"] = b.value / 10
    b["cls"] = np.select([~b.has_ref, b.ref_max >= 0.25 * b.value, (b.ref_max >= 0.4 * b.tenth) & (b.ref_max <= 2.5 * b.tenth) & (b.ref_max >= 10),
                          b.ref_max < 20],
                         ["no reference", "references large too", "fits value/10 (decimal slip?)", "isolated (refs < 20 mm)"], "refs moderate")
    st = c.pu_stations().set_index("station_key")
    b["name"] = b.station_key.astype(str).map(st["name"])
    cols = ["sid", "name", "date_raw", "value", "flag", "p99", "prev_value", "next_value", "missing_before", "missing_after",
            "cpc0", "cpc3max", "pu_med3", "pu_max3", "pu_n", "site_max4", "site_n", "ref_max", "cls"]
    b[cols].to_csv(OUT / "q2_above_500.csv", index=False)
    print("\n== Q2 values > 500 mm:", len(b), "at", b.sid.nunique(), "series; flags", b.flag.value_counts().to_dict())
    print("class:", b.cls.value_counts().to_dict())
    print("reference max (CPC 3-day, PU and other neighbours):", b.ref_max.describe().round(1).to_dict())
    print("own 99th percentile of wet days at those series:", b.groupby("sid").p99.first().describe().round(0).to_dict())
    print("by series:", b.groupby(["sid", "name"]).value.agg(["size", "min", "max"]).sort_values("size", ascending=False).to_string())
    print("missing day before or after:", int(((b.missing_before > 0) | (b.missing_after > 0)).sum()))
    print("values 500-1000 ending in 0:", int((b.value % 10 == 0).sum()), "of", len(b))


def q2_100(r):
    t = r[r.value.between(95, 105)].copy()
    t["grp"] = np.where(t.value == 100, "100", "95-99,101-105")
    t["ref_max"] = ref_max(t)
    g = t.groupby("grp").agg(n=("value", "size"), posts=("sid", "nunique"), flagged=("flag", lambda f: round(float((f != "").mean()), 3)),
                             no_ref=("has_ref", lambda h: int((~h).sum())), refs_dry=("refdry", lambda d: round(float(d.mean()), 3)),
                             cpc3_median=("cpc3max", "median"), pu_max3_median=("pu_max3", "median"), ref_max_median=("ref_max", "median"),
                             prev_zero=("prev_value", lambda v: round(float((v == 0).mean()), 3)),
                             missing_before=("missing_before", lambda v: round(float((v > 0).mean()), 3)))
    print("\n== Q2 exactly 100 mm vs values 95-99 and 101-105")
    print(g.to_string())
    h = t[t.value == 100]
    print("100 mm days:", len(h), "; per series top:", h.sid.value_counts().head(8).to_dict())
    print("100 mm by year:", h.date_raw.dt.year.value_counts().sort_index().to_dict())
    k = h.assign(ym=h.date_raw.dt.to_period("M")).groupby(["sid", "ym"]).size()
    print("series-months with >= 3 values of exactly 100:", int((k >= 3).sum()), "; values in them", int(k[k >= 3].sum()))
    print("100 mm with dry references (all < 5 mm):", int(h.refdry[h.has_ref].sum()), "of", int(h.has_ref.sum()), "with a reference")
    for v in (50, 60, 70, 80, 90, 100, 110, 120, 150, 200):
        n = int((r.value == v).sum()); nb = int(((r.value == v - 1) | (r.value == v + 1)).sum()) / 2
        print("  heaping", v, ": n", n, "; mean of", v - 1, "and", v + 1, ":", nb, "; ratio", round(n / nb, 2) if nb else None)
    h.to_csv(OUT / "q2_value_100.csv", index=False)


def q3(r):
    r = r.copy()
    r["cat"] = np.select([r.flag.str.contains("src_unrealistic"), r.flag.str.contains("src_suspect"), r.flag == ""],
                         ["src_unrealistic", "src_suspect", "unflagged"], "other flag")
    fs = set(r.sid[r.cat.isin(["src_suspect", "src_unrealistic"])])
    r["in_flag_series"] = r.sid.isin(fs)
    ym = r.date_raw.dt.to_period("M")
    mz = r.groupby([r.sid, ym]).value.transform(lambda v: (v > 0).sum() == 0)
    r["month_all_zero"] = mz

    def stats(d):
        return pd.Series(dict(
            n=len(d), posts=d.sid.nunique(), zero_share=round(float((d.value == 0).mean()), 3), mean_mm=round(float(d.value.mean()), 2),
            cpc0_mean=round(float(d.cpc0.mean()), 2), pu_med0_mean=round(float(d.pu_med0.mean()), 2),
            in_all_zero_month=round(float(d.month_all_zero.mean()), 3),
            zero_when_cpc3_ge10=round(float((d.value[d.cpc3max >= 10] == 0).mean()), 3),
            zero_when_pu_med3_ge10=round(float((d.value[d.pu_med3 >= 10] == 0).mean()), 3),
            wet20_when_cpc3_lt1=round(float((d.value[d.cpc3max < 1] >= 20).mean()), 4),
            wet20_when_pu_max3_lt1=round(float((d.value[d.pu_max3 < 1] >= 20).mean()), 4),
            ge100=int((d.value >= 100).sum()), gt500=int((d.value > 500).sum())))
    t = r.groupby("cat").apply(stats)
    t2 = r[r.in_flag_series].groupby("cat").apply(stats)
    t2.index = [i + " (series with provider flags)" for i in t2.index]
    tt = pd.concat([t, t2])
    tt.to_csv(OUT / "q3_flags.csv")
    print("\n== Q3 provider flags vs references")
    print(tt.T.to_string())
    # per series r with CPC (best lag) and with the PU-neighbour median (same day), flagged vs unflagged days
    cpc = c.CPCField()
    st = c.pu_stations().set_index("station_key")
    rows = []
    for sid in sorted(fs):
        g = r[r.sid == sid]
        sk = g.station_key.astype(str).iloc[0]
        d = pd.DatetimeIndex(g.date_raw)
        cp = {L: cpc.at(st.at[sk, "lat"], st.at[sk, "lon"], d, lag=L) for L in (-1, 0, 1)}
        row = dict(sid=sid)
        for k, m in (("flagged", g.cat.isin(["src_suspect", "src_unrealistic"]).values), ("unflagged", (g.cat == "unflagged").values)):
            row["n_" + k] = int(m.sum())
            row["zero_" + k] = round(float((g.value.values[m] == 0).mean()), 3) if m.any() else np.nan
            rr = [c.pearson(g.value.values[m], cp[L][m], min_n=100)[0] for L in cp]
            row["r_cpc_" + k] = np.nanmax(rr) if np.isfinite(rr).any() else np.nan
            row["r_nb_" + k] = c.pearson(g.value.values[m], g.pu_med0.values[m], min_n=100)[0]
        rows.append(row)
    s = pd.DataFrame(rows)
    s.to_csv(OUT / "q3_flag_series.csv", index=False)
    both = s.dropna(subset=["r_cpc_flagged", "r_cpc_unflagged"])
    print("series with provider flags:", len(s), "; with >= 100 flagged and unflagged days vs CPC:", len(both))
    print("median r with CPC: flagged", round(both.r_cpc_flagged.median(), 3), "; unflagged", round(both.r_cpc_unflagged.median(), 3),
          "; series where flagged r < unflagged r:", int((both.r_cpc_flagged < both.r_cpc_unflagged).sum()))
    bn = s.dropna(subset=["r_nb_flagged", "r_nb_unflagged"])
    print("with neighbours:", len(bn), "; median r with PU-neighbour median: flagged", round(bn.r_nb_flagged.median(), 3),
          "; unflagged", round(bn.r_nb_unflagged.median(), 3), "; flagged lower:", int((bn.r_nb_flagged < bn.r_nb_unflagged).sum()))
    fz = r[r.cat.isin(["src_suspect", "src_unrealistic"])]
    print("flagged values in all-zero months:", int(fz.month_all_zero.sum()), "of", len(fz),
          "; flagged values that are zero while CPC 3-day max >= 10 mm:", int(((fz.value == 0) & (fz.cpc3max >= 10)).sum()))
    return r


def acc_outliers(r, p95, p999):
    r = r.copy()
    r["p95"] = r.sid.map(p95)
    r["p999"] = r.sid.map(p999)
    r["ref_max"] = ref_max(r)
    acc = (r.missing_before >= 2) & (r.value >= r.p95) & (r.value >= 20)
    # zero-run accumulation: >= 5 zeros directly before (no gap) while references were wet
    z = (r.value == 0).astype(int)
    grp = (r.sid != r.sid.shift()) | (r.missing_before != 0)
    run = z.groupby(grp.cumsum()).cumsum()
    zeros_before = run.shift().where(~grp, 0).fillna(0)
    acc_z = (zeros_before >= 5) & (r.value >= r.p95) & (r.value >= 50) & (r.ref_max < 0.25 * r.value)
    iso = (r.value >= 100) & r.has_ref & (r.cpc3max.fillna(0) < 10) & (r.pu_max3.fillna(0) < 10) & (r.site_max4.fillna(0) < 10)
    big = r.value > 3 * r.p999
    f = pd.DataFrame({"sid": r.sid, "date_raw": r.date_raw, "value": r.value, "flag": r.flag,
                      "accumulation_after_gap": acc, "after_zero_run_refs_small": acc_z, "isolated_extreme": iso,
                      "above_3x_p999": big, "gt500": r.value > 500, "eq100": r.value == 100,
                      "cpc3max": r.cpc3max, "pu_max3": r.pu_max3, "site_max4": r.site_max4, "missing_before": r.missing_before})
    k = ["accumulation_after_gap", "after_zero_run_refs_small", "isolated_extreme", "above_3x_p999", "gt500", "eq100"]
    f = f[f[k].any(axis=1)]
    f.to_csv(OUT / "q36_value_flags.csv", index=False)
    print("\n== accumulations and outliers (counts of values)")
    for kk in k:
        print(" ", kk, int(f[kk].sum()), "at", f[f[kk]].sid.nunique(), "series; provider-flagged", int((f[kk] & (f.flag != "")).sum()))
    a = r[acc]
    print("accumulation candidates: missing days before:", a.missing_before.describe().round(0).to_dict(),
          "; references >= 0.25 x value:", int((a.ref_max >= 0.25 * a.value).sum()), "of", len(a))
    print("isolated extremes value:", r[iso].value.describe().round(0).to_dict())


def main():
    r, p95, p999 = prep()
    q2_big(r)
    q2_100(r)
    q3(r)
    acc_outliers(r, p95, p999)


if __name__ == "__main__":
    main()
