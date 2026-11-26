"""Summarise the raw PU SIHKA rain-post publications (F67): posts, coordinate formats, elevation, date keys,
values, provider day notes and status. Reads F:/temp/station/pu_sihka/raw/ only.
Usage: python tools/summarise_pu_sihka.py
"""
import collections
import datetime as dt
import glob
import json

RAW = "F:/temp/station/pu_sihka/raw"
cat = json.load(open(glob.glob(f"{RAW}/catalogue_*.json")[0], encoding="utf-8"))
year_of = {d["pubId"]: d["year"] for p in cat for d in p["data"]}
post_of = {d["pubId"]: p["id"] for p in cat for d in p["data"]}
coord, nd, vtype, notes, stat, elev = (collections.Counter() for _ in range(6))
epoch = yr_mismatch = neg = big = nvals = 0
posts, posts_coord = set(), set()
for f in glob.glob(f"{RAW}/pub/*.json"):
    pub = f.replace("\\", "/").split("/")[-1][:-5]
    j = json.load(open(f, encoding="utf-8"))
    h, b = j.get("head") or {}, j.get("body") or {}
    if not isinstance(b, dict):
        coord["list-body"] += 1
        continue
    posts.add(post_of[pub])
    c = str(h.get("koordinat", ""))
    k = "POINT" if c.startswith("POINT") else ("DMS" if ("LS" in c or "LU" in c) else ("none" if c.strip() in ("", "-", "None") else "other"))
    coord[k] += 1
    if k != "none":
        posts_coord.add(post_of[pub])
    elev["given" if h.get("elevesi") not in (None, "", "-") else "none"] += 1
    ks = [int(x) for x in b]
    if ks and min(ks) < 86400 * 365:
        epoch += 1
    yrs = collections.Counter(dt.datetime.fromtimestamp(x, dt.timezone.utc).year for x in ks if x >= 86400 * 365)
    if yrs and str(yrs.most_common(1)[0][0]) != str(year_of.get(pub)):
        yr_mismatch += 1
    nd[len(b)] += 1
    for v in b.values():
        x = v.get("value")
        vtype[type(x).__name__] += 1
        notes[str(v.get("note"))[:20]] += 1
        stat[str(v.get("status"))] += 1
        if isinstance(x, (int, float)):
            nvals += 1
            neg += x < 0
            big += x > 500
print("posts", len(posts), "with a coordinate", len(posts_coord), "| coord formats per file", dict(coord), "| elevation", dict(elev))
print("files with epoch-start keys", epoch, "| main year differs from catalogue", yr_mismatch, "| days per file", dict(nd.most_common(6)))
print("value types", dict(vtype), "| numeric values", nvals, "negative", neg, ">500", big)
print("notes", dict(notes.most_common(10)))
print("day status", dict(stat.most_common(10)))
