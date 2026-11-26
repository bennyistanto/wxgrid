"""pu_sihka /qc, checks 1 and 8: metadata (positions, land, province, duplicates, elevation) and coverage.

Positions are the compiled ones (stations.csv.gz, rule R4: the most common header position).
  land        Natural Earth 10 m land polygon (cartopy cache), distance to the NE 10 m coastline
  refs        is the CPC-UNI (0.5 deg) and IMERG Final (0.1 deg) cell at the post all-NaN? Both are
              land-masked here, and the day-label step cannot test a post in a NaN cell (Q5)
  province    NE 10 m admin-1 polygon containing the post vs the province written in the headers
              (most common across publications; aliases mapped; NE has no Kalimantan Utara or Papua Selatan)
  duplicates  other station keys (any source) at <= 0.1 km
  elevation   no DEM is on disk (F:/temp searched 2026-11-25), so the DEM test is not run [to verify];
              header elevation given or missing only
Coverage: per series values, span, missing % inside the span, by year; PU series reporting per day.

Output: F:/temp/station/qc_pu_sihka/q0_metadata.csv, q8_coverage_series.csv, q8_coverage_year.csv,
        q8_daily_count.csv; log q0.log
Usage: python tools/qc_pu_sihka_metadata.py
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qc_pu_sihka_common as c  # noqa: E402

OUT = Path(c.OUT)
NE = Path.home() / ".local/share/cartopy/shapefiles/natural_earth"
IMERG = "F:/temp/hybrid-bias-correction/data/input/imergf/idn_imergf.nc4"
ALIAS = {"NAD": "ACEH", "NTT": "NUSA TENGGARA TIMUR", "DAERAH ISTIMEWA YOGYAKARTA": "YOGYAKARTA",
         "KEPULAUAN BANGKA BELITUNG": "BANGKA-BELITUNG", "KALIMANTAN UTARA": "KALIMANTAN TIMUR",
         "KALIMANTAN UTARA-TIMUR": "KALIMANTAN TIMUR", "PAPUA SELATAN": "PAPUA", "MADURA": "JAWA TIMUR",
         "TUBAN": "JAWA TIMUR", "KALI KONTO": "JAWA TIMUR", "JAWATIMUR": "JAWA TIMUR", "JAWA_TIMUR": "JAWA TIMUR"}


def norm_prov(s):
    s = str(s or "").upper().replace("_", " ").strip()
    if s in ("NAN", "NONE"):
        s = ""
    s = " ".join(s.split())
    return ALIAS.get(s, s)


def main():
    st = c.pu_stations()
    pubs = pd.read_csv(f"{c.PU}/measure/pubs.csv")
    posts = pd.read_csv(f"{c.PU}/measure/posts.csv")
    st["integration_id"] = st.source_station_id
    pubs["p"] = pubs.provinsi.map(norm_prov)
    hp = pubs[pubs.p != ""].groupby("integration_id").p.agg(lambda v: v.mode().iloc[0])
    st["prov_header"] = st.integration_id.map(hp).fillna("")
    st = st.merge(posts[["integration_id", "spread_km", "n_coord_pubs", "coord_how", "unit"]], on="integration_id", how="left")
    gdf = gpd.GeoDataFrame(st.copy(), geometry=[Point(x, y) for x, y in zip(st.lon, st.lat)], crs=4326)
    land = gpd.read_file(NE / "physical" / "ne_10m_land.shp").cx[90:145, -15:12]
    coast = gpd.read_file(NE / "physical" / "ne_10m_coastline.shp").cx[90:145, -15:12]
    adm = gpd.read_file(NE / "cultural" / "ne_10m_admin_1_states_provinces.shp")
    adm = adm[adm.admin == "Indonesia"][["name", "geometry"]].reset_index(drop=True)
    lu = land.union_all()
    st["on_land"] = [lu.contains(g) for g in gdf.geometry]
    g3 = gdf.to_crs(3395)
    cu = coast.to_crs(3395).union_all()
    st["coast_km"] = [round(g.distance(cu) / 1000, 2) for g in g3.geometry]
    j = gpd.sjoin(gdf[["station_key", "geometry"]], adm, how="left", predicate="within")
    st["prov_ne"] = st.station_key.map(j.drop_duplicates("station_key").set_index("station_key")["name"]).fillna("").str.upper()
    a3 = adm.to_crs(3395)
    for i in st.index[st.prov_ne.eq("")]:
        d = a3.distance(g3.geometry[i])
        st.at[i, "prov_ne"] = adm["name"].iloc[int(np.argmin(d.values))].upper() + " (nearest, %.1f km)" % (d.min() / 1000)
    pn = st.prov_ne.str.split(" [(]nearest", regex=True).str[0]
    st["prov_match"] = np.where(st.prov_header.eq(""), "no header", np.where(pn.eq(st.prov_header), "yes", "NO"))
    cpc = xr.open_dataset(c.CPC).precip
    im = xr.open_dataset(IMERG).precipitation
    cpc_nan = cpc.isnull().all("time").values
    im_nan = im.sel(time=slice("2016", "2025")).isnull().all("time").values
    st["cpc_cell_nan"] = [bool(cpc_nan[int(np.abs(cpc.lat.values - a).argmin()), int(np.abs(cpc.lon.values - b).argmin())]) for a, b in zip(st.lat, st.lon)]
    st["imerg_cell_nan"] = [bool(im_nan[int(np.abs(im.lat.values - a).argmin()), int(np.abs(im.lon.values - b).argmin())]) for a, b in zip(st.lat, st.lon)]
    al = c.stations().dropna(subset=["lat", "lon"])
    dup = []
    for r in st.itertuples():
        near = al[(al.lat - r.lat).abs().lt(0.01) & (al.lon - r.lon).abs().lt(0.01) & al.station_key.ne(r.station_key)]
        d = c.haversine_km(r.lat, r.lon, near.lat.values, near.lon.values)
        dup.append(";".join("%s (%.2f km)" % (k, x) for k, x in zip(near.station_key, d) if x <= 0.1))
    st["same_position_as"] = dup
    print("PU stations", len(st), "; unique keys", st.station_key.is_unique, "; distinct names", st["name"].nunique())
    print("on NE10m land:", int(st.on_land.sum()), "; off land:", int((~st.on_land).sum()))
    off = st[~st.on_land].sort_values("coast_km", ascending=False)
    print("off-land posts by distance to the coastline (km):", pd.cut(off.coast_km, [0, 0.5, 1, 2, 5, 10, 1000]).value_counts().sort_index().to_dict())
    cols = ["station_key", "name", "unit", "lat", "lon", "coast_km", "prov_header", "prov_ne", "cpc_cell_nan", "imerg_cell_nan"]
    print(off[off.coast_km > 1][cols].to_string(index=False))
    print("CPC cell all-NaN:", int(st.cpc_cell_nan.sum()), "; IMERG cell all-NaN 2016-2025:", int(st.imerg_cell_nan.sum()),
          "; both:", int((st.cpc_cell_nan & st.imerg_cell_nan).sum()))
    print("province header vs NE polygon:", st.prov_match.value_counts().to_dict())
    cols = ["station_key", "name", "unit", "lat", "lon", "prov_header", "prov_ne", "on_land", "spread_km"]
    print(st[st.prov_match == "NO"][cols].to_string(index=False))
    print("posts sharing a position (<= 0.1 km) with another station key:", int(st.same_position_as.ne("").sum()))
    print(st[st.same_position_as.ne("")][["station_key", "name", "same_position_as"]].to_string(index=False))
    print("header elevation given:", int(st.elev_m.notna().sum()), "of", len(st), "; no DEM on disk, DEM test not run [to verify]")
    st.to_csv(OUT / "q0_metadata.csv", index=False)

    o = c.pu_obs()
    se = c.series()
    se = se[se.source == "pu_sihka"].set_index("series_id")
    g = o.groupby("series_id", observed=True)
    cov = pd.DataFrame({"n_values": g.size(), "first": g.date_raw.min(), "last": g.date_raw.max(),
                        "n_years": g.date_raw.agg(lambda d: d.dt.year.nunique())})
    cov["span_days"] = (cov["last"] - cov["first"]).dt.days + 1
    cov["missing_pct_in_span"] = (100 * (1 - cov.n_values / cov.span_days)).round(1)
    cov["n_dropped_R1R2"] = se.n_missing_code.reindex(cov.index)
    cov.to_csv(OUT / "q8_coverage_series.csv")
    print("series", len(cov), "; values", int(cov.n_values.sum()), "; missing % in span: median", cov.missing_pct_in_span.median(),
          "; series with >= 50% missing in span", int((cov.missing_pct_in_span >= 50).sum()))
    print("years of data per series:", cov.n_years.describe().round(1).to_dict())
    y = o.assign(y=o.date_raw.dt.year).groupby("y").agg(values=("value", "size"), series=("series_id", "nunique"))
    ndays = np.array([366 if pd.Timestamp(int(k), 1, 1).is_leap_year else 365 for k in y.index])
    y["mean_series_per_day"] = (y["values"] / ndays).round(0)
    y.to_csv(OUT / "q8_coverage_year.csv")
    print(y.to_string())
    d = o[o.gauge == "MANUAL"].groupby("date_raw").series_id.nunique().rename("n_series_manual")
    d.to_csv(OUT / "q8_daily_count.csv")
    print("PU MANUAL series reporting per day, by year (median):", d.groupby(d.index.year).median().to_dict())


if __name__ == "__main__":
    main()
