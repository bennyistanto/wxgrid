"""Build the decisions file the `pu_sihka` reader applies (rules R1-R3, user 2026-11-25; measurements F68).

kinds:
  year_body           publication whose own (body) year fits CPC better than the catalogue year (M2b verdict "body year")
  copy                publication >= 99% equal to another publication of the same post on >= 300 shared dates (M2)
  zero_year           post-gauge-year with 12 complete months, all zero (R1; unfilled templates, as F64)
  zero_month_missing  complete all-zero month where CPC at the post or the median of posts within 25 km had >= 100 mm (R2)
Dates are taken after the reader's own re-dating (`pu_sihka.dated_values`), so the tests see what the reader keeps.
The 100 mm threshold is provisional (not sourced), in the spirit of F59.

Input:  F:/temp/station/pu_sihka/raw/, measure/m2_year_mismatch.csv, measure/m2b_year_verdict.csv (tools/measure_pu_sihka.py m2 m2b)
Output: F:/temp/station/pu_sihka/_decisions.csv (kind, pubId, integration_id, gauge, period, evidence)
Usage:  python tools/build_pu_sihka_decisions.py
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers import pu_sihka as ps  # noqa: E402

ROOT = Path("F:/temp/station/pu_sihka")
RAW, MEAS = ROOT / "raw", ROOT / "measure"
CPC = "F:/temp/station/cpc/idn_cpc_1979_2025.nc"
THRESH, NB_KM = 100.0, 25.0

pubs = ps.load_publications(RAW)
m2 = pd.read_csv(MEAS / "m2_year_mismatch.csv")
m2b = pd.read_csv(MEAS / "m2b_year_verdict.csv")
rows = [dict(kind="year_body", pubId=r.pubId, evidence=f"CPC r body year {r.r_body:.2f} vs catalogue year {r.r_catalogue:.2f}")
        for r in m2b[m2b.verdict == "body year"].itertuples()]
rows += [dict(kind="copy", pubId=r.pubId, evidence=f"{r.equal_frac:.3f} equal to publication {r.sibling} ({r.sibling_year_gauge}) on {r.n_common} dates")
         for r in m2[m2.equal_frac >= 0.99].itertuples()]
year_body = frozenset(x["pubId"] for x in rows if x["kind"] == "year_body")
copies = frozenset(x["pubId"] for x in rows if x["kind"] == "copy")
idmap = pubs.set_index("pubId")[["integration_id", "gauge"]]
for x in rows:
    x.update(integration_id=idmap.at[x["pubId"], "integration_id"], gauge=idmap.at[x["pubId"], "gauge"], period="")

# daily values after re-dating, and one position per post (most common)
frames, pos = [], {}
for r, head, d in ps.dated_values(RAW, pubs, year_body, copies):
    la, lo, _ = ps.parse_coord(head.get("koordinat"))
    if not np.isnan(la):
        pos.setdefault(r.integration_id, []).append((round(la, 5), round(lo, 5)))
    if len(d):
        frames.append(d.assign(integration_id=r.integration_id, gauge=r.gauge)[["integration_id", "gauge", "date", "value"]])
obs = pd.concat(frames, ignore_index=True)
obs["value"] = pd.to_numeric(obs.value, errors="coerce")
pos = {k: Counter(v).most_common(1)[0][0] for k, v in pos.items()}

mo = obs.assign(ym=obs.date.dt.to_period("M")).groupby(["integration_id", "gauge", "ym"]).agg(
    n_days=("date", "nunique"), total=("value", "sum"), n_pos=("value", lambda v: int((v > 0).sum()))).reset_index()
mo["complete"] = mo.n_days >= mo.ym.dt.days_in_month
mo["all_zero"] = mo.complete & (mo.n_pos == 0)

# R1: zero years
mo["y"] = mo.ym.dt.year
yz = mo.groupby(["integration_id", "gauge", "y"]).agg(m=("complete", "sum"), z=("all_zero", "sum")).reset_index()
zy = yz[(yz.m == 12) & (yz.z == 12)]
rows += [dict(kind="zero_year", pubId="", integration_id=r.integration_id, gauge=r.gauge, period=str(r.y),
              evidence="12 complete months, all 0") for r in zy.itertuples()]
zy_set = {(r.integration_id, r.gauge, r.y) for r in zy.itertuples()}

# R2: all-zero months vs CPC and neighbours
cpc = xr.open_dataset(CPC).precip
lon360 = float(cpc.lon.max()) > 180
cm = cpc.resample(time="MS").sum()
cpc_m = {}
for k, (la, lo) in pos.items():
    s = cm.sel(lat=la, lon=lo % 360 if lon360 else lo, method="nearest").to_series()
    s.index = s.index.to_period("M")
    cpc_m[k] = s
ok = mo[mo.complete & ~mo.all_zero].groupby(["integration_id", "ym"]).total.max().to_dict()
keys = list(pos)
nb = {a: [b for b in keys if b != a and abs(pos[a][0] - pos[b][0]) < .3 and abs(pos[a][1] - pos[b][1]) < .3
          and ps.km(*pos[a], *pos[b]) <= NB_KM] for a in keys}
cand = mo[mo.all_zero & ~mo.apply(lambda r: (r.integration_id, r.gauge, r.y) in zy_set, axis=1)]
n_test = 0
for r in cand.itertuples():
    c = cpc_m.get(r.integration_id)
    cv = float(c.get(r.ym, np.nan)) if c is not None else np.nan
    nv = [ok[(q, r.ym)] for q in nb.get(r.integration_id, []) if (q, r.ym) in ok]
    nbm = float(np.median(nv)) if nv else np.nan
    n_test += 1
    if (not np.isnan(cv) and cv >= THRESH) or (not np.isnan(nbm) and nbm >= THRESH):
        rows.append(dict(kind="zero_month_missing", pubId="", integration_id=r.integration_id, gauge=r.gauge, period=str(r.ym),
                         evidence=f"all 0; CPC {cv:.0f} mm; median of {len(nv)} posts within {NB_KM:.0f} km {nbm:.0f} mm"))
out = pd.DataFrame(rows)[["kind", "pubId", "integration_id", "gauge", "period", "evidence"]]
out.to_csv(ROOT / "_decisions.csv", index=False)
print(f"all-zero complete months tested {n_test} (outside zero years)")
print(out.kind.value_counts().to_string())
