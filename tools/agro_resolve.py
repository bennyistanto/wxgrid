"""Decide the station and year of every parsed agro sheet.

1. Copy groups: sheets whose daily rainfall is identical (>= 90% of >= 60 shared month-days,
   >= 20 of them wet) are linked regardless of year or station; each connected group is one
   record and gets one (station, year).
2. Candidates for a group: every member's file station and name-cell station, crossed with
   its parsed year, Tahun-cell year and file/sheet-name year.
3. If all members agree on one candidate and none carries a name or year conflict, that is
   the answer (status "default"). Otherwise each candidate is scored by the best correlation
   with neighbouring gauges (CPC from 1979 as a second score); the best wins when r >= 0.15
   and it leads the runner-up by >= 0.10 (status "decided"); else "unresolved" (excluded).

Run: python tools/agro_resolve.py  -> _agro_sheet_resolution.csv, _agro_copy_groups.csv
"""
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agro_refs import B, C, R, S, cell, cpc_series, name_to_station, rbest, rnb  # noqa: E402

S = S.copy()
S["key"] = list(zip(S["file"], S["sheet"]))
ser = {k: g.set_index("date")["value"].sort_index() for k, g in R.groupby(["file", "sheet"])}
md = {}
for k, s in ser.items():
    t = s.copy(); t.index = t.index.strftime("%m-%d")
    md[k] = t[~t.index.duplicated()]

# 1. copy graph across all years and stations
keys = [k for k in S["key"] if k in md]
parent = {k: k for k in keys}


def find(k):
    while parent[k] != k:
        parent[k] = parent[parent[k]]
        k = parent[k]
    return k


LINKS = B / "_agro_copy_groups.csv"
use_cache = LINKS.exists() and LINKS.stat().st_mtime > (B / "_agro_raw_records.csv.gz").stat().st_mtime
links = []
if use_cache:
    for _, l in pd.read_csv(LINKS).iterrows():
        a, b = tuple(l["a"].split("|")), tuple(l["b"].split("|"))
        if a in parent and b in parent:
            links.append((a, b, l["shared_days"], l["identical"]))
            parent[find(a)] = find(b)
for a, b in ([] if use_cache else itertools.combinations(keys, 2)):
    sa, sb = md[a], md[b]
    j = sa.index.intersection(sb.index)
    if len(j) < 60:
        continue
    x, y = sa[j].values, sb[j].values
    if ((x > 0) | (y > 0)).sum() < 20:
        continue
    eq = np.isclose(x, y).mean()
    if eq >= 0.9:
        links.append((a, b, len(j), round(eq, 3)))
        parent[find(a)] = find(b)
groups = {}
for k in keys:
    groups.setdefault(find(k), []).append(k)


def cand_of(row):
    sts = {row["station"]}
    ns = name_to_station(row["name_cell"])
    if ns:
        sts.add(ns)
    yrs = {int(row["year"])}
    for c in ("year_cell", "year_hint", "sheet_year", "file_year"):
        if pd.notna(row[c]):
            yrs.add(int(row[c]))
    return sts, yrs


def score(k, st, y):
    s = ser[k].copy()
    y0 = int(pd.Series(s.index.year).mode().iat[0])
    s.index = s.index + pd.DateOffset(years=y - y0)
    lat, lon = C.loc[st, "lat"], C.loc[st, "lon"]
    nb = rnb(s, lat, lon)[0]
    cp = rbest(s, cpc_series(*cell(lat, lon)))[0] if y >= 1979 else np.nan
    return nb, cp


rows = []
Si = S.set_index("key")
for gid, members in groups.items():
    info = [Si.loc[[k]].iloc[0] for k in members]
    sts, yrs = set(), set()
    conflict = False
    defaults = set()
    for r in info:
        a, b = cand_of(r)
        sts |= a; yrs |= b
        defaults.add((r["station"], int(r["year"])))
        if len(a) > 1 or len(b) > 1:
            conflict = True
    if not conflict and len(defaults) == 1:
        st, y = defaults.pop()
        status, ev = "default", ""
    else:
        k0 = max(members, key=lambda k: len(ser[k]))   # longest member carries the test
        scored = []
        for st, y in itertools.product(sorted(sts), sorted(yrs)):
            nb, cp = score(k0, st, y)
            primary = nb if not np.isnan(nb) else cp
            scored.append((primary, nb, cp, st, y))
        scored = [x for x in scored if not np.isnan(x[0])]
        scored.sort(key=lambda x: -x[0])
        # label votes: folder/prefix station x2, name-cell station x1; name year x2, Tahun cell x1
        sv, yv = {}, {}
        for r in info:
            sv[r["station"]] = sv.get(r["station"], 0) + 2
            ns = name_to_station(r["name_cell"])
            if ns:
                sv[ns] = sv.get(ns, 0) + 1
            named = False
            for col, w in (("sheet_year", 2), ("file_year", 2), ("year_cell", 1)):
                if pd.notna(r.get(col)):
                    yv[int(r[col])] = yv.get(int(r[col]), 0) + w
                    named = True
            if not named:
                yv[int(r["year"])] = yv.get(int(r["year"]), 0) + 1

        def label_winner(v):
            top = sorted(v.items(), key=lambda x: -x[1])
            return top[0][0] if top and (len(top) == 1 or top[0][1] > top[1][1]) else None
        lst, lyr = label_winner(sv), label_winner(yv)
        if scored and scored[0][0] >= 0.15 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.10):
            _, nb, cp, st, y = scored[0]
            status = "decided"
        else:
            st = y = None
            status = "unresolved"
            # R1: neighbours and CPC lean the same way, and a label supports it
            if len(scored) >= 2:
                a_, b_ = scored[0], scored[1]
                cpc_ok = np.isnan(a_[2]) or np.isnan(b_[2]) or a_[2] > b_[2]
                nb_ok = not np.isnan(a_[1]) and not np.isnan(b_[1]) and a_[1] > b_[1]
                if a_[0] >= 0.15 and nb_ok and cpc_ok and (a_[3] == lst or a_[4] == lyr):
                    st, y, status = a_[3], a_[4], "decided-lean+label"
            # R2: label majority where fingerprints cannot decide, unless contradicted by >= 0.10
            def beaten_elsewhere(st_, y_):
                """A label-based pick is withdrawn when another year fits >= 0.10 better."""
                mine = score(k0, st_, y_)[0]
                if np.isnan(mine):
                    return False, ""
                others = [(score(k0, st_, yy)[0], yy) for yy in range(1973, 1995) if yy != y_]
                others = [o for o in others if not np.isnan(o[0])]
                if others:
                    rb, yb = max(others)
                    if rb - mine >= 0.10:
                        return True, f"year scan: {yb} fits r {rb:.2f} vs chosen {y_} r {mine:.2f}"
                return False, ""
            if status == "decided-lean+label":
                bad, why = beaten_elsewhere(st, y)
                if bad:
                    st, y, status, ev = None, None, "unresolved", why
            if status == "unresolved" and lst and lyr:
                pick = [x for x in scored if x[3] == lst and x[4] == lyr]
                best_other = max((x[0] for x in scored if (x[3], x[4]) != (lst, lyr)), default=np.nan)
                contradicted = pick and not np.isnan(best_other) and best_other - pick[0][0] >= 0.10
                weak = scored and max(x[0] for x in scored) < 0.15   # nothing matches anywhere
                if not contradicted and not (weak and len(scored) >= 2):
                    st, y, status = lst, lyr, "decided-labels"
                    bad, why = beaten_elsewhere(st, y)
                    if bad:
                        st, y, status, ev = None, None, "unresolved", why
        ev = "; ".join(f"{s_}/{y_}: nb {nb_:.2f} cpc {cp_:.2f}" for _, nb_, cp_, s_, y_ in scored[:3])
    for k, r in zip(members, info):
        rows.append(dict(file=k[0], sheet=k[1], group=f"{gid[0]}[{gid[1]}]", group_size=len(members),
                         file_station=r["station"], name_cell=r["name_cell"], parsed_year=int(r["year"]),
                         year_cell=r["year_cell"], year_hint=r["year_hint"],
                         station=st, year=y, status=status, evidence=ev))
out = pd.DataFrame(rows)
out.to_csv(B / "_agro_sheet_resolution.csv", index=False)
pd.DataFrame([("|".join(a), "|".join(b), n, e) for a, b, n, e in links],
             columns=["a", "b", "shared_days", "identical"]).to_csv(LINKS, index=False)

print("sheets:", len(out), "| copy links:", len(links), "| groups:", len(groups),
      "| groups with >1 sheet:", sum(len(v) > 1 for v in groups.values()))
print("status:", out["status"].value_counts().to_dict())
moved = out[(out["status"].str.startswith("decided")) & ((out["station"] != out["file_station"]) | (out["year"] != out["parsed_year"]))]
print("\nsheets re-assigned (station or year differs from file/parsed):", len(moved))
pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 70); pd.set_option("display.max_rows", 200)
print(moved[["file", "sheet", "file_station", "parsed_year", "station", "year", "evidence"]].to_string(index=False))
print("\nunresolved:")
print(out[out["status"] == "unresolved"][["file", "sheet", "file_station", "parsed_year", "name_cell", "year_cell", "evidence"]].to_string(index=False))
