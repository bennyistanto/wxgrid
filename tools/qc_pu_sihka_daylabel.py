"""Q5 of the pu_sihka /qc: why so many PU days are day-label `unverified`.

Reads compiled/daylabel_segments.csv, daylabel_blocks.csv.gz and the PU observations (qc_pu_sihka_common).
The pipeline (src/wxgrid/consolidate/daylabel.py) tests only unflagged values (flag == ""), on raw dates,
in a 120-day window centred on each 30-day block; r is NaN when the window has < min_pairs (60) pairs or
either side has zero variance. A block with NaN r for every reference is "not covered" -> unverified.

For every PU value labelled unverified (and every unverified segment day) this script assigns the reason:
  before_refs       raw date before CPC starts (1979-01-01)
  beyond_refs       raw date after the last reference day (CPC 2025-12-31, IMERG 2025-09-30)
  outside_unflagged_span  before the first or after the last block of unflagged values (segment ends are
                    stretched over flagged values, daylabel.detect)
  too_few_series    whole series < min_pairs unflagged values ("none: too few values")
  window_sparse     < 60 unflagged station values in the 120-day window centred on the value's block
  reference_missing >= 60 station values but < 60 days where a reference (IMERG or CPC cell of the pipeline
                    cache compiled/_staging/daylabel_*.pkl, read only) also has a value: sea cell (both products
                    are land-masked) or a gap in the reference
  window_constant   >= 60 values but zero variance (all zero) in the window
  other             none of the above (should not happen)
Segment calendar days are also split into days with a value and days without one.

Output: F:/temp/station/qc_pu_sihka/q5_unverified_values.csv (per series), q5_reasons.csv, log q5.log
Usage: python tools/qc_pu_sihka_daylabel.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)
WIN, MINP = 120, 60
REF_END = pd.Timestamp("2025-12-31")


def main():
    seg = pd.read_csv(f"{c.COMP}/daylabel_segments.csv", parse_dates=["start", "end"])
    seg = seg[seg.series_id.str.startswith("pu_sihka:")].copy()
    seg["days"] = (seg.end - seg.start).dt.days + 1
    o = c.pu_obs()
    print("PU segment calendar days by status:", seg.groupby("status").days.sum().to_dict())
    print("PU values by label:", o.label.value_counts().to_dict())
    off = (o.date - o.date_raw).dt.days
    print("PU values by label and offset (days added to the raw date):")
    print(pd.crosstab(o.label.astype(str), off).to_string())
    # calendar days in unverified segments that carry a value
    u = seg[seg.status == "unverified"]
    have = 0
    for r in u.itertuples():
        x = o[(o.series_id == r.series_id)]
        have += int(((x.date_raw >= r.start) & (x.date_raw <= r.end)).sum())
    print(f"unverified segments: {len(u)} in {u.series_id.nunique()} series, {u.days.sum():,} calendar days, "
          f"of which {have:,} have a value ({u.days.sum() - have:,} are gaps between publications)")
    print("unverified segment length (days):", u.days.describe().round(0).to_dict())

    # reason per unverified value
    uv = o[o.label == "unverified"].copy()
    clean = o[o.flag.astype(str) == ""]
    st = c.pu_stations().set_index("station_key")
    import xarray as xr
    refs = {}
    for name, path, f in (("imerg", "F:/temp/hybrid-bias-correction/data/input/imergf/idn_imergf.nc4", "daylabel_imerg_final.pkl"),
                          ("cpc", c.CPC, "daylabel_cpc_uni.pkl")):
        ds = xr.open_dataset(path)
        refs[name] = (pd.read_pickle(f"{c.COMP}/_staging/{f}"), ds.lat.values, ds.lon.values)
    rows = []
    for sid, g in uv.groupby("series_id", observed=True):
        s = clean[clean.series_id == sid].drop_duplicates("date_raw").set_index("date_raw").value.sort_index()
        if len(s) < MINP:
            rows.append(g.assign(reason="too_few_series"))
            continue
        s0, s1 = s.index.min(), s.index.max()
        idx = pd.date_range(s0, s1, freq="D")
        x = s.reindex(idx)
        n = x.notna().astype(int).rolling(WIN, center=True, min_periods=1).sum()
        sd = x.rolling(WIN, center=True, min_periods=2).std()
        d = g.date_raw
        k = ((d - s0).dt.days // 30).to_numpy()
        centre = s0 + pd.to_timedelta(30 * k + 15, unit="D")
        nn = n.reindex(centre).to_numpy()
        # pairs with a reference in the window (station value and reference value both present), best reference
        la, lo = st.at[sid.rsplit(":", 2)[0], "lat"], st.at[sid.rsplit(":", 2)[0], "lon"]
        pr = np.zeros(len(idx))
        for name, (G, glat, glon) in refs.items():
            col = str((int(np.abs(glat - la).argmin()), int(np.abs(glon - lo).argmin())))
            if col in G.columns:
                y = G[col].reindex(idx)
                pr = np.fmax(pr, (x.notna() & y.notna()).astype(int).rolling(WIN, center=True, min_periods=1).sum().to_numpy())
        npair = pd.Series(pr, index=idx).reindex(centre).to_numpy()
        ss = sd.reindex(centre).fillna(0).to_numpy()
        dd = d.to_numpy()
        reason = np.select([dd < np.datetime64("1979-01-01"), dd > np.datetime64(REF_END),
                            dd < np.datetime64(s0), np.asarray(centre > s1),
                            np.isnan(nn) | (nn < MINP), np.nan_to_num(npair) < MINP, ss <= 1e-6],
                           ["before_refs", "beyond_refs", "outside_unflagged_span", "outside_unflagged_span",
                            "window_sparse", "reference_missing", "window_constant"], "other")
        rows.append(g.assign(reason=reason))
    uv = pd.concat(rows)
    uv["year"] = uv.date_raw.dt.year
    uv["flagged"] = uv.flag.astype(str) != ""
    uv["zero"] = uv.value == 0
    print("unverified values by reason (window = 120 days centred, unflagged values only):")
    print(uv.groupby("reason", observed=True).agg(n=("value", "size"), series=("series_id", "nunique"),
                                                   frac_zero=("zero", "mean"), frac_flagged=("flagged", "mean")).round(3).to_string())
    print("unverified values by year:", uv.year.value_counts().sort_index().to_dict())
    print("unverified values that carry a provider flag:", int(uv.flagged.sum()),
          uv[uv.flagged].flag.astype(str).value_counts().to_dict())
    # compare with values in verified blocks: share flagged
    print("share of values flagged, by label:", o.assign(f=o.flag.astype(str) != "").groupby("label", observed=True).f.mean().round(3).to_dict())
    # uncertain: margin distribution in PU blocks
    bl = pd.concat(b[b.series_id.str.startswith("pu_sihka:")] for b in pd.read_csv(f"{c.COMP}/daylabel_blocks.csv.gz", chunksize=1_000_000))
    bl["covered"] = bl.r.notna()
    b2 = bl.groupby(["series_id", "start"]).agg(covered=("covered", "any"), decided=("offset", lambda v: v.notna().any()),
                                                 rmax=("r", "max"), mmax=("margin", "max")).reset_index()
    print(f"PU blocks: {len(b2):,}; covered {int(b2.covered.sum()):,}; decided {int(b2.decided.sum()):,}; "
          f"covered but undecided {int((b2.covered & ~b2.decided).sum()):,}")
    und = b2[b2.covered & ~b2.decided]
    print("covered but undecided blocks: best r", und.rmax.describe().round(2).to_dict(), "; best margin", und.mmax.describe().round(3).to_dict())
    uv.groupby(["series_id", "reason"], observed=True).size().unstack(fill_value=0).to_csv(OUT / "q5_unverified_values.csv")
    uv.groupby(["reason", "year"], observed=True).size().rename("n").reset_index().to_csv(OUT / "q5_reasons.csv", index=False)


if __name__ == "__main__":
    main()
