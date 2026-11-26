"""After adopting the agro:MOJOSARI day-label overrides and QC flags (F66): offsets, labels, flags, merged rows, summary diff vs `_before_mojosari/`.
Usage: python tools/check_mojosari_adoption.py"""
import json
import pandas as pd
C = "F:/temp/station/compiled/"
SID = "agro:MOJOSARI:RR"
o = pd.concat(c[c.series_id == SID] for c in pd.read_csv(C + "observations_RR.csv.gz", chunksize=2_000_000, dtype={"flag": str}))
o["off"] = (pd.to_datetime(o.date) - pd.to_datetime(o.date_raw)).dt.days
print("n", len(o), "offsets", o.off.value_counts().to_dict(), "labels", o.label.value_counts().to_dict())
print("flags", o.flag.fillna("").str.split(";").explode().value_counts().to_dict())
print(o[o.date_raw == "1994-11-17"][["date", "value", "flag"]].to_string())
seg = pd.read_csv(C + "daylabel_segments.csv"); print(seg[seg.series_id == SID].to_string(index=False))
m = pd.concat(c for c in pd.read_csv(C + "merged_RR.csv.gz", chunksize=2_000_000))
st = pd.read_csv(C + "stations.csv.gz"); site = st[st.station_key == "agro:MOJOSARI"].site_id.iloc[0]
print("site", site, "merged rows", (m.site_id == site).sum() if "site_id" in m else m.columns.tolist())
a, b = json.load(open(C + "summary.json")), json.load(open(C + "_before_mojosari/summary.json"))
def flat(d, p=""):
    for k, v in d.items():
        yield from (flat(v, p + k + ".") if isinstance(v, dict) else [(p + k, v)])
fa, fb = dict(flat(a)), dict(flat(b))
print({k: (fb.get(k), fa[k]) for k in fa if fa[k] != fb.get(k) and "time" not in k})
print("sites", len(pd.read_csv(C + "_before_mojosari/sites.csv")), "->", len(pd.read_csv(C + "sites.csv")))
