"""pu_sihka /qc: scale check (values in tenths of mm read as mm would multiply a year by 10).

Per series-year with >= 300 values: total, CPC total on the same days (raw dates, lag 0), median of PU
neighbours within 25 km (each neighbour summed over the shared days, >= 90% of them), and the wet-day
99th percentile. A ratio near 10 to both references, or a wet-day p99 above 300 mm, marks a scale suspect.

Output: F:/temp/station/qc_pu_sihka/q2b_scale.csv; log q2b.log
Usage: python tools/qc_pu_sihka_scale.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)


def main():
    r = c.refs()
    r = r[r.value.notna()].copy()
    r["sid"] = r.series_id.astype(str)
    r["y"] = r.date_raw.dt.year
    g = r.groupby(["sid", "y"])
    t = g.agg(n=("value", "size"), total=("value", "sum"), cpc=("cpc0", "sum"), cpc_n=("cpc0", "count"),
              nb=("pu_med0", "sum"), nb_n=("pu_med0", "count"),
              p99=("value", lambda v: v[v > 0].quantile(0.99) if (v > 0).any() else np.nan),
              n_gt500=("value", lambda v: int((v > 500).sum()))).reset_index()
    t = t[t.n >= 300]
    t["ratio_cpc"] = np.where(t.cpc_n >= 0.9 * t.n, t.total / t.cpc, np.nan)
    t["ratio_nb"] = np.where(t.nb_n >= 0.9 * t.n, t.total / t.nb, np.nan)
    t["scale_suspect"] = ((t.ratio_cpc > 4) & ((t.ratio_nb > 4) | t.ratio_nb.isna())) | (t.p99 > 300)
    st = c.pu_stations().set_index("station_key")
    t["name"] = t.sid.str.rsplit(":", n=2).str[0].map(st["name"])
    t.round(2).to_csv(OUT / "q2b_scale.csv", index=False)
    print("series-years with >= 300 values:", len(t))
    print("ratio to CPC:", t.ratio_cpc.describe(percentiles=[.01, .05, .5, .95, .99]).round(2).to_dict())
    print("ratio to PU neighbours:", t.ratio_nb.describe(percentiles=[.01, .05, .5, .95, .99]).round(2).to_dict())
    print("scale suspects:", int(t.scale_suspect.sum()))
    pd.set_option("display.width", 250)
    print(t[t.scale_suspect | (t.ratio_cpc > 3) | (t.ratio_nb > 3)].sort_values("ratio_cpc", ascending=False)
          [["sid", "name", "y", "n", "total", "cpc", "nb", "ratio_cpc", "ratio_nb", "p99", "n_gt500", "scale_suspect"]].round(2).to_string(index=False))
    print("lowest ratios (possible partial zero-filling):")
    print(t[(t.ratio_cpc < 0.25)].sort_values("ratio_cpc")[["sid", "name", "y", "n", "total", "cpc", "nb", "ratio_cpc", "ratio_nb"]].round(2).head(25).to_string(index=False))
    print("series-years with total / CPC < 0.25:", int((t.ratio_cpc < 0.25).sum()), "; and also / neighbours < 0.25:", int(((t.ratio_cpc < 0.25) & (t.ratio_nb < 0.25)).sum()))


if __name__ == "__main__":
    main()
