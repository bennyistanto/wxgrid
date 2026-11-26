"""Figures for the CSR "Indonesia Station Rainfall" pages, from the rainfall export (F71).

Input:  F:/temp/station/compiled/export/idn_rr_daily_1866_2025_{sites.csv,long.csv.gz}
        E:/temp/idn-bnd/idn_bnd_adm0.shp (Indonesia), wld_bnd_adm0.shp (neighbours)
Output (site repo, docs/assets/image-csr/):
  idn-station-rainfall-00.png  station map, 3:2, no legend (CSR card thumbnail)
  idn-station-rainfall-01.png  station map, wide, with legend (product page)
  idn-station-rainfall-02.png  coverage: one row per site, one column per year, shaded by share of days with a value
  idn-station-rainfall-03.png  sites with a value in each year, per provider group
Also writes docs/img/station-map.png in this repository (the wide map, for the README).
Provider group of a site (from its member sources): PU rain posts if any member is pu_sihka or jatim; else BMKG, Dutch-era and
derived archives if any member is bmkg_xlsx, chind, fklim, agro, bmg_posts, sumbar_daily, larantuka, sacad,
sacad_synop, ghcnd or knmi (KNMI = the Dutch-era service); else compendium and other posts (asean_comp only, sumsel_posts).
Colours: reference palette slots 1-3 (validated all-pairs, light mode); sequential blue ramp for coverage.
Usage: python tools/csr_figures.py
"""
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
E = Path("F:/temp/station/compiled/export")
PREFIX = "idn_rr_daily_1866_2025"
OUT = Path("C:/Users/benny/OneDrive/Documents/Github/site/docs/assets/image-csr")
REPO_IMG = Path(__file__).resolve().parents[1] / "docs" / "img"
BND = Path("E:/temp/idn-bnd")
EXTENT = (94.0, 142.0, -11.8, 7.0)

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
GROUPS = [("BMKG, Dutch-era and derived archives", "#2a78d6"), ("PU rain posts", "#eb6834"), ("Compendium and other posts", "#1baf7a")]
PU = {"pu_sihka", "jatim"}
BMKG = {"bmkg_xlsx", "chind", "fklim", "agro", "bmg_posts", "sumbar_daily", "larantuka", "sacad", "sacad_synop", "ghcnd", "knmi"}
SEQ = LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def group_of(sources):
    s = set(str(sources).split(";"))
    return GROUPS[1][0] if s & PU else GROUPS[0][0] if s & BMKG else GROUPS[2][0]


sites = pd.read_csv(E / f"{PREFIX}_sites.csv")
sites["group"] = sites.sources.map(group_of)
counts = sites.group.value_counts()
print("sites", len(sites), counts.to_dict())

# ---------------------------------------------------------------- 00 map
world = gpd.read_file(BND / "wld_bnd_adm0.shp", bbox=(EXTENT[0] - 2, EXTENT[2] - 2, EXTENT[1] + 2, EXTENT[3] + 2))
world = world[world.iso_3 != "IDN"]
idn = gpd.read_file(BND / "idn_bnd_adm0.shp")
idn["geometry"] = idn.geometry.simplify(0.01)
world["geometry"] = world.geometry.simplify(0.01)
SEA = "#eef4fa"


def draw_map(path, size, legend, extent):
    fig, ax = plt.subplots(figsize=size, dpi=200)
    fig.patch.set_facecolor(SEA if not legend else SURFACE)
    ax.set_facecolor(SEA)
    world.plot(ax=ax, color="#f3f2ef", edgecolor="#c9c7c0", linewidth=0.4)
    idn.plot(ax=ax, color="#e6e4de", edgecolor="#9a988f", linewidth=0.5)
    for name, col in GROUPS:
        g = sites[sites.group == name]
        ax.scatter(g.lon, g.lat, s=9 if legend else 12, color=col, edgecolors=SURFACE, linewidths=0.35, zorder=3,
                   label=f"{name} ({len(g):,})")
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3]); ax.set_aspect("equal", adjustable="datalim" if not legend else "box")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    if legend:
        leg = ax.legend(loc="lower left", frameon=True, facecolor=SURFACE, edgecolor=GRID, fontsize=10, markerscale=2.2,
                        title=f"{len(sites):,} rain-gauge sites, 1866-2025", title_fontsize=10.5)
        leg.get_title().set_color(INK)
        for tx in leg.get_texts():
            tx.set_color(INK)
        fig.tight_layout(pad=0.3)
    else:
        fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(OUT / path, facecolor=fig.get_facecolor())
    if legend:
        REPO_IMG.mkdir(parents=True, exist_ok=True)
        fig.savefig(REPO_IMG / "station-map.png", facecolor=fig.get_facecolor())
    plt.close(fig)


draw_map("idn-station-rainfall-00.png", (11.72, 7.8), False, (97.0, 139.0, -11.0, 6.5))   # card thumbnail, 3:2
draw_map("idn-station-rainfall-01.png", (13.0, 5.4), True, EXTENT)                       # page map, wide

# ---------------------------------------------------------------- coverage matrix
cnt = {}
for c in pd.read_csv(E / f"{PREFIX}_long.csv.gz", usecols=["site_id", "date"], chunksize=2_000_000):
    y = c.date.str[:4].astype(int)
    for (sid, yy), n in c.groupby([c.site_id, y]).size().items():
        cnt[(sid, yy)] = cnt.get((sid, yy), 0) + n
cov = pd.Series(cnt).rename_axis(["site_id", "year"]).unstack(fill_value=0)
years = np.arange(1866, 2026)
cov = cov.reindex(columns=years, fill_value=0)
days = np.array([366 if pd.Timestamp(y, 1, 1).is_leap_year else 365 for y in years])
frac = cov / days
first = frac.gt(0).idxmax(axis=1)
last = frac.gt(0).iloc[:, ::-1].idxmax(axis=1)
order = pd.DataFrame(dict(first=first, last=last)).sort_values(["first", "last"]).index
frac = frac.loc[order]
fig, ax = plt.subplots(figsize=(11.72, 7.8), dpi=200)
m = np.ma.masked_equal(frac.to_numpy(), 0)
im = ax.imshow(m, aspect="auto", cmap=SEQ, vmin=0, vmax=1, interpolation="nearest",
               extent=(years[0] - 0.5, years[-1] + 0.5, len(frac), 0))
ax.set_xlabel("Year"); ax.set_ylabel(f"Site ({len(frac):,}), ordered by first year with data")
ax.set_xticks(range(1870, 2030, 10))
ax.grid(axis="x", color=GRID, linewidth=0.6); ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.015)
cb.set_label("Share of days in the year with a value", color=INK2); cb.outline.set_visible(False)
ax.set_title("Daily rainfall coverage per site", loc="left", color=INK, fontsize=13)
fig.tight_layout()
fig.savefig(OUT / "idn-station-rainfall-02.png", facecolor=SURFACE)
plt.close(fig)

# ---------------------------------------------------------------- sites per year, per group
active = frac.gt(0)
grp = sites.set_index("site_id").group.reindex(active.index)
per = active.groupby(grp).sum().T
fig, ax = plt.subplots(figsize=(11.72, 5.4), dpi=200)
for name, col in GROUPS:
    if name in per:
        ax.plot(per.index, per[name], color=col, linewidth=2)
        yl = per[name]
        x_lab = int(yl.idxmax())
        above = name == GROUPS[0][0]   # BMKG label centred above its peak; the others to the left of theirs
        ax.annotate(name, (x_lab, yl.max()), xytext=(0, 8) if above else (-8, 2), textcoords="offset points", color=INK,
                    fontsize=10, ha="center" if above else "right", va="bottom" if above else "center")
ax.set_xlim(1866, 2025); ax.set_ylim(0, None)
ax.set_ylabel("Sites with a value in the year"); ax.set_xlabel("Year")
ax.grid(axis="y", color=GRID, linewidth=0.6)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.legend([plt.Line2D([], [], color=c, linewidth=2) for _, c in GROUPS], [n for n, _ in GROUPS], loc="upper left",
          frameon=False, fontsize=10)
ax.set_title("Sites reporting each year", loc="left", color=INK, fontsize=13)
fig.tight_layout()
fig.savefig(OUT / "idn-station-rainfall-03.png", facecolor=SURFACE)
plt.close(fig)
tot = active.sum()
print("sites with data per year (selected):", {y: int(tot[y]) for y in (1870, 1900, 1930, 1950, 1975, 1985, 1995, 2005, 2015, 2021, 2023, 2025)})
print("sites per group and year at peak:", {k: (int(per[k].idxmax()), int(per[k].max())) for k in per})
