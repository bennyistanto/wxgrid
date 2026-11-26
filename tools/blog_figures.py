"""Figures for the gauge-compilation blog post. Reads the compiled build and writes PNGs
into the site's image folder. Every figure is a measured summary (counts, shares,
correlation statistics, station locations, a derived climatology); no raw daily station
series are plotted. Run: python tools/blog_figures.py

Palette: Okabe-Ito (a published colour-blind-safe categorical set) for identity; single-hue
blue ramps for ordered/sequential jobs. One axis per chart; legends present; recessive grid.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

C = Path("F:/temp/station/compiled")
OUT = Path("C:/Users/benny/OneDrive/Documents/Github/site/docs/assets/image-blog")
PRE = "20261007-ten-archives"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": "#888", "axes.linewidth": 0.8,
                     "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.7,
                     "figure.dpi": 150, "savefig.dpi": 150, "savefig.bbox": "tight",
                     "axes.spines.top": False, "axes.spines.right": False})
OKABE = {"BMKG workbooks + national": "#0072B2", "SACA&D": "#E69F00",
         "ASEAN compendium": "#009E73", "GHCN-Daily": "#CC79A7", "Field rain posts": "#D55E00"}
FAMILY = {"bmkg_xlsx": "BMKG workbooks + national", "chind": "BMKG workbooks + national",
          "fklim": "BMKG workbooks + national", "fklim_sumatera": "BMKG workbooks + national",
          "sacad": "SACA&D", "sacad_nonblend": "SACA&D", "sacad_synop": "SACA&D",
          "sacad2013_extra": "SACA&D", "asean_comp": "ASEAN compendium", "ghcnd": "GHCN-Daily",
          "jatim": "Field rain posts", "agro": "Field rain posts"}

st = pd.read_csv(C / "stations.csv.gz")
st = st[st["site_id"].notna()]
site_country = st.groupby("site_id")["country"].agg(lambda x: x.mode().iat[0])
m = pd.read_csv(C / "merged_RR.csv.gz", usecols=["site_id", "date", "value", "series_id", "label", "flag"],
                dtype={"label": str, "flag": str})
m["year"] = m["date"].str[:4].astype(int)
m["src"] = m["series_id"].str.split(":").str[0]
m["family"] = m["src"].map(FAMILY)
m["country"] = m["site_id"].map(site_country)
idn = m[m["country"] == "ID"].copy()
audit = {}

# 1. Station map, coloured by source family
fig = plt.figure(figsize=(9, 5.2))
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([94, 142, -11.5, 7], ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#f3f1ec")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="#9a9a9a")
    tf = ccrs.PlateCarree()
except Exception:
    ax = plt.axes(); ax.set_xlim(94, 142); ax.set_ylim(-11.5, 7); tf = None
sm = st.copy(); sm["family"] = sm["source"].map(FAMILY)
rep = sm.sort_values("source").drop_duplicates("site_id")
for fam, col in OKABE.items():
    d = rep[rep["family"] == fam]
    if len(d) == 0:   # GHCN is never a site's highest-priority source
        continue
    kw = dict(transform=tf) if tf is not None else {}
    ax.scatter(d["lon"], d["lat"], s=7, color=col, label=f"{fam} ({len(d)})", alpha=0.8, linewidths=0, **kw)
ax.legend(loc="upper right", fontsize=8, frameon=True, framealpha=0.92, title="highest-priority source per site")
ax.set_title("Rain gauge sites in the compilation, by source", loc="left", fontweight="bold")
fig.savefig(OUT / f"{PRE}-01-map-sources.png"); plt.close(fig)
audit["map_sites_by_family"] = rep["family"].value_counts().to_dict()

# 2. Coverage over time: distinct Indonesian sites with RR per year, stacked by dominant family
sy = idn.groupby(["site_id", "year", "family"]).size().reset_index(name="n")
dom = sy.sort_values("n").drop_duplicates(["site_id", "year"], keep="last")
piv = dom.groupby(["year", "family"]).size().unstack(fill_value=0).reindex(columns=list(OKABE))
piv = piv.reindex(range(1950, 2022), fill_value=0)
fams = [f for f in OKABE if piv[f].sum() > 0]   # GHCN contributes nothing to merged RR
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.stackplot(piv.index, [piv[f].values for f in fams], labels=fams,
             colors=[OKABE[f] for f in fams], edgecolor="white", linewidth=0.2)
ax.set_xlim(1950, 2021); ax.set_ylabel("Indonesian sites with rainfall that year")
ax.legend(loc="upper left", fontsize=8, frameon=False)
ax.set_title("Coverage over time, by source family", loc="left", fontweight="bold")
fig.savefig(OUT / f"{PRE}-02-coverage.png"); plt.close(fig)
audit["coverage_total_by_year"] = {y: int(piv.loc[y].sum()) for y in [1950, 1980, 1990, 2000, 2010, 2021]}

# 3. Day-label confidence over time (ordered share, single-hue ramp)
RAMP = {"verified": "#08519c", "interpolated": "#4a97c9", "uncertain": "#9ecae1", "unverified": "#d9d9d9"}
lab = idn.assign(label=idn["label"].replace("", "unverified").fillna("unverified"))
lab = lab.groupby(["year", "label"]).size().unstack(fill_value=0).reindex(columns=list(RAMP), fill_value=0)
lab = lab[lab.sum(axis=1) > 0]
share = lab.div(lab.sum(axis=1), axis=0)
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.stackplot(share.index, [share[k].values for k in RAMP], labels=list(RAMP), colors=[RAMP[k] for k in RAMP])
ax.set_xlim(1950, 2021); ax.set_ylim(0, 1); ax.set_ylabel("share of daily values")
ax.legend(loc="lower center", ncol=4, fontsize=8, frameon=False)
ax.set_title("How sure the date is, Indonesian rainfall by year", loc="left", fontweight="bold")
fig.savefig(OUT / f"{PRE}-03-daylabel-confidence.png"); plt.close(fig)
audit["confidence_shares"] = {y: {k: round(float(share.loc[y, k]), 2) for k in RAMP}
                              for y in [1980, 1990, 2000, 2010, 2020] if y in share.index}

# 4. Day-label before/after: BMKG workbook series-years by best offset vs IMERG
def best_offset(path):
    r = pd.read_csv(path)
    r = r[r["source"] == "bmkg_xlsx"]
    b = r.loc[r.groupby(["series_id", "year"])["r"].idxmax()]
    return b["lag"].value_counts()
bef = best_offset(C / "daylabel_imerg_by_year_before.csv")
aft = best_offset(C / "daylabel_imerg_by_year.csv")
lags = [-2, -1, 0, 1]
bv = [int(bef.get(l, 0)) for l in lags]; av = [int(aft.get(l, 0)) for l in lags]
x = np.arange(len(lags)); w = 0.38
fig, ax = plt.subplots(figsize=(7.5, 4.4))
ax.bar(x - w / 2, bv, w, color="#D55E00", label="before correction")
ax.bar(x + w / 2, av, w, color="#0072B2", label="after correction")
ax.set_xticks(x); ax.set_xticklabels([f"{l:+d} day" for l in lags])
ax.set_xlabel("best-matching day offset against IMERG"); ax.set_ylabel("BMKG station-years")
ax.legend(frameon=False); ax.grid(axis="x", visible=False)
ax.set_title("The date correction, measured against satellite rainfall", loc="left", fontweight="bold")
ax.annotate("expected offset", xy=(1, max(av) * 0.98), xytext=(1.6, max(av) * 0.98), fontsize=8, color="#555",
            va="top", ha="left")
fig.savefig(OUT / f"{PRE}-04-daylabel-beforeafter.png"); plt.close(fig)
audit["offset_before"] = dict(zip(lags, bv)); audit["offset_after"] = dict(zip(lags, av))

# 5. Derived climatology: mean annual rainfall per site (sites with >= 10 full-ish years)
good = idn[idn["flag"].fillna("") == ""].dropna(subset=["value"])
yr_tot = good.groupby(["site_id", "year"])["value"].agg(["sum", "count"])
yr_tot = yr_tot[yr_tot["count"] >= 300]
clim = yr_tot.groupby("site_id")["sum"].agg(["mean", "size"])
clim = clim[clim["size"] >= 10]
loc = rep.set_index("site_id")[["lat", "lon"]]
clim = clim.join(loc).dropna()
fig = plt.figure(figsize=(9, 5.2))
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    ax = plt.axes(projection=ccrs.PlateCarree()); ax.set_extent([94, 142, -11.5, 7], ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#f3f1ec"); ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="#9a9a9a")
    tf = ccrs.PlateCarree()
except Exception:
    ax = plt.axes(); ax.set_xlim(94, 142); ax.set_ylim(-11.5, 7); tf = None
kw = dict(transform=tf) if tf is not None else {}
sc = ax.scatter(clim["lon"], clim["lat"], c=clim["mean"], s=16, cmap="YlGnBu", vmin=1000, vmax=4000,
                edgecolor="#555", linewidth=0.2, **kw)
cb = fig.colorbar(sc, ax=ax, shrink=0.7, pad=0.02); cb.set_label("mean annual rainfall (mm)")
ax.set_title(f"Mean annual rainfall at {len(clim)} long-record sites (derived)", loc="left", fontweight="bold")
fig.savefig(OUT / f"{PRE}-05-climatology.png"); plt.close(fig)
audit["climatology_sites"] = int(len(clim))
audit["climatology_mm_range"] = [round(float(clim["mean"].quantile(.05))), round(float(clim["mean"].quantile(.95)))]

Path("C:/Users/benny/OneDrive/Documents/Github/wxgrid/temp/blog_figures_audit.json").write_text(
    json.dumps(audit, indent=2), encoding="utf-8")
print(json.dumps(audit, indent=2))
print("wrote 5 figures to", OUT)
