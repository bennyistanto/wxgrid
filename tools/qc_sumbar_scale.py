"""QC follow-up: why do most sumbar_daily posts correlate so weakly with CPC-UNI day by day?

For every RR series in West Sumatra (lat -3.6..1.0, lon 98.5..102.0) with >= 300 values in
1991-2000: r with CPC-UNI at its cell on raw dates, best of lags -3..+3 (lag 0 = CPC D-1),
and r of pentad (5-day) and monthly totals (month >= 25 values, pentad 5 values). If the
monthly r is normal but the daily r is low, the totals are right and the days are not (day
alignment or transcription); if both are low, the position or the data are wrong.
Writes F:/temp/station/qc_phase2/sumbar_scale.csv. Run: python tools/qc_sumbar_scale.py
"""
import numpy as np
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
o = q.obs_rr(); st = q.stations(); se = q.series()
r = se[se.variable == "RR"].merge(st[["station_key", "lat", "lon"]], on="station_key")
r = r[r.lat.between(-3.6, 1.0) & r.lon.between(98.5, 102.0) & (r["first"] <= "2000-12-31") & (r["last"] >= "1991-01-01")]
cpc = q.CPCField()
sub = o[o.series_id.isin(r.series_id) & (o.date_raw >= "1991-01-01") & (o.date_raw <= "2000-12-31")
        & ~o.flag.astype(str).str.contains("src_duplicate|qc_excluded")]
rows = []
for sid, g in sub.groupby("series_id", observed=True):
    x = g.set_index("date_raw").value; x = x[~x.index.duplicated()].dropna()
    if len(x) < 300:
        continue
    rr = r.set_index("series_id").loc[sid]
    c = cpc.series(rr.lat, rr.lon)
    lag = {k: q.pearson(x.values, c.reindex(x.index + pd.Timedelta(days=k - 1)).values)[0] for k in range(-3, 4)}
    kb = max(lag, key=lambda k: lag[k] if np.isfinite(lag[k]) else -9)
    cs = c.copy(); cs.index = cs.index + pd.Timedelta(days=1 - kb)  # aligned at the best lag
    xd = x.asfreq("D")
    def agg(f, need):
        gx = xd.resample(f); s = gx.sum(min_count=1).where(gx.count() >= need)
        return q.pearson(s.values, cs.resample(f).sum().reindex(s.index).values)[0]
    rows.append(dict(series_id=sid, source=sid.split(":")[0], n=len(x), r_day_lag0=lag[0], best_lag=kb, r_day_best=lag[kb],
                     r_pentad=agg("5D", 5), r_month=agg("MS", 25), mean_mm=x.mean(), wet_freq=(x >= 1).mean()))
R = pd.DataFrame(rows).sort_values(["source", "r_day_best"])
R.to_csv(f"{q.OUT}/sumbar_scale.csv", index=False)
print(R.groupby("source")[["r_day_lag0", "r_day_best", "r_pentad", "r_month", "wet_freq"]].median().round(2).to_string())
print(R.round(2).to_string(index=False))
