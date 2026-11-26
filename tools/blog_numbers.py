"""Print the headline numbers the gauge-compilation blog post cites, from the current
compiled build, so every measured claim traces to this script's output.

Run: python tools/blog_numbers.py   (reads F:/temp/station/compiled)
"""
import json
from pathlib import Path

import pandas as pd

C = Path("F:/temp/station/compiled")
s = json.load(open(C / "summary.json"))
print("== build")
print("sources:", len(json.load(open(C / "config_used.yaml".replace(".yaml", ".yaml"))) if False else []) or "see config")
print("n_stations:", s["n_stations"], "| n_sites:", s["n_sites"], "| n_series:", s["n_series"], "| n_obs:", s["n_obs"])

st = pd.read_csv(C / "stations.csv.gz")
print("sources:", sorted(st["source"].unique()))

m = pd.read_csv(C / "merged_RR.csv.gz", usecols=["site_id", "date", "series_id", "label", "flag"],
                dtype={"label": str, "flag": str})
m["src"] = m["series_id"].str.split(":").str[0]
m["year"] = m["date"].str[:4].astype(int)
print("\n== merged RR by source")
print(m["src"].value_counts().to_dict())

# Indonesian sites only (via stations->site country)
site_country = st.dropna(subset=["site_id"]).groupby("site_id")["country"].agg(lambda x: x.mode().iat[0])
m["country"] = m["site_id"].map(site_country)
idn = m[m["country"] == "ID"]
print("\n== Indonesian merged RR: sites with any value per year")
cov = idn.groupby("year")["site_id"].nunique()
print({y: int(cov.get(y, 0)) for y in [1950, 1970, 1980, 1990, 2000, 2010, 2015, 2021, 2022]})
print("median Indonesian sites reporting per day, selected years:")
d = idn.groupby("date")["site_id"].size()
d.index = pd.to_datetime(d.index)
print({y: int(d[str(y)].median()) for y in [1980, 1990, 2000, 2010, 2021]})

print("\n== Indonesian RR day-label shares by year (verified/interpolated/uncertain/unverified)")
lab = idn.assign(label=idn["label"].fillna("")).groupby(["year", "label"]).size().unstack(fill_value=0)
lab = lab.div(lab.sum(axis=1), axis=0).round(2)
for y in [1980, 1990, 2000, 2010, 2020]:
    if y in lab.index:
        print(y, {k: float(lab.loc[y, k]) for k in ["verified", "interpolated", "uncertain", "unverified"] if k in lab})

print("\n== flags present in merged RR")
print(m["flag"].fillna("").str.split(";").explode().value_counts().head(10).to_dict())

ex = Path("F:/temp/station/compiled/export")
if (ex / "idn_rr_daily_1950_2021_sites.csv").exists():
    sites = pd.read_csv(ex / "idn_rr_daily_1950_2021_sites.csv")
    print("\n== export: Indonesian sites", len(sites),
          "| median years with values", int(sites["n_days_with_value"].gt(0).sum() and sites["n_days_with_value"].median() // 365))
