"""Reader for SACA&D / ECA&D style predefined zips (one element per zip).

Two kinds, set by `kind` in the config:

- `nonblend`: one file per source series (RR_SOUIDnnnnnn.txt). Every valid row is kept.
- `blend_own`: like `blend_synop` but keeps every own source of the station; with
  `skip_stations_in` it reads only stations absent from another release.
- `blend_synop`: every SYNOP source (participant name containing `synop_parname`) becomes
  its own station at its sources.txt coordinates, with the rows it supplied in a blended
  file. Participant series come from the non-blended zip instead.

Data: value * `scale` (RR is stored in 0.1 mm). Q code 0 = valid, 1 = suspect (kept,
flagged), 9 = missing (dropped). Missing value code -9999.
"""

from collections import defaultdict
import io
import re
import zipfile

import pandas as pd

from ..config import in_bbox

# ...,CN,LAT,LON,HGHT: the fixed core of every metadata line; names around it may
# contain commas or tabs, so the core is located by pattern, not by splitting.
CORE = re.compile(r",\s*([A-Z]{2})\s*,\s*([+-]\d{1,3}:\d{2}:\d{2})\s*,\s*([+-]\d{1,3}:\d{2}:\d{2})\s*,\s*(-?\d+)")


def _dms(s):
    sign = -1.0 if s.strip().startswith("-") else 1.0
    d, m, sec = (float(x) for x in s.strip().lstrip("+-").split(":"))
    return sign * (d + m / 60 + sec / 3600)


def _meta(z, member, n_ids):
    """Parse stations.txt / sources.txt. Returns rows with the leading ids, name, coords."""
    rows = []
    for line in z.read(member).decode("utf-8", "ignore").splitlines():
        m = CORE.search(line)
        lead = re.match(r"\s*" + r"\s*,\s*".join([r"(\d+)"] * n_ids) + r"\s*,", line)
        if not (m and lead):
            continue
        # Some names carry real tabs, others a literal backslash-t; strip both.
        name = re.sub(r"\s+", " ", line[lead.end():m.start()].replace("\\t", " ").replace("\t", " ")).strip()
        rest = [x.strip() for x in line[m.end():].split(",")]  # ELEI, START, STOP, PARID, PARNAME
        rows.append(dict(ids=[int(x) for x in lead.groups()], name=name, country=m.group(1),
                         lat=_dms(m.group(2)), lon=_dms(m.group(3)),
                         elev_m=float(m.group(4)) if float(m.group(4)) > -999 else float("nan"),
                         parname=",".join(rest[4:]).strip() if len(rest) > 4 else ""))
    return rows


def _data(z, member):
    lines = z.read(member).decode("utf-8", "ignore").splitlines()
    i = max(k for k, l in enumerate(lines) if l.strip().startswith("STAID"))
    df = pd.read_csv(io.StringIO("\n".join(lines[i:])), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
    return df


def read(src, bbox):
    z = zipfile.ZipFile(src["path"])
    var, scale = src["variable"], float(src.get("scale", 1.0))
    ns = src.get("station_namespace", "sacad")
    names = set(z.namelist())
    stations, series, obs = {}, [], []

    if src["kind"] == "nonblend":
        # sources.txt: SOUID, SOUNAME, CN, LAT, LON, ...  (one id before the name)
        meta = {r["ids"][0]: r for r in _meta(z, "sources.txt", 1)}
        members = sorted(n for n in names if n.startswith(f"{var}_SOUID"))
        jobs = [(m, None) for m in members]
    elif src["kind"] == "blend_own":
        # stations.txt: STAID, STANAME, CN, ...; sources.txt: STAID, SOUID, SOUNAME, CN, ...
        # sources.txt lists every source used in a station's blend, including neighbours
        # used for infill (e.g. TEGAL under 31 stations). A source is the station's own only
        # if its coordinates match the station's (`own_coord_tol_deg`); a source matching
        # several stations goes to the closest one.
        meta = {r["ids"][0]: r for r in _meta(z, "stations.txt", 1)}
        tol = float(src.get("own_coord_tol_deg", 0.02))
        best = {}
        for r in _meta(z, "sources.txt", 2):
            st = meta.get(r["ids"][0])
            if st is None:
                continue
            d = max(abs(r["lat"] - st["lat"]), abs(r["lon"] - st["lon"]))
            if d <= tol and (r["ids"][1] not in best or d < best[r["ids"][1]][0]):
                best[r["ids"][1]] = (d, r["ids"][0])
        own = defaultdict(set)
        for souid, (_, staid) in best.items():
            own[staid].add(souid)
        skip = set()
        if src.get("skip_stations_in"):
            skip = {r["ids"][0] for r in _meta(zipfile.ZipFile(src["skip_stations_in"]), "stations.txt", 1)}
        jobs = [(f"{var}_STAID{s:06d}.txt", souids, None) for s, souids in own.items()
                if s not in skip and f"{var}_STAID{s:06d}.txt" in names]
        jobs = [(m, k) for m, k, _ in jobs]
    elif src["kind"] == "blend_synop":
        # SYNOP sources (participant name containing `synop_parname`) become stations of
        # their own, at the coordinates sources.txt gives them. SACA&D attaches them to
        # stations up to ~17 km away (e.g. Kendari airport SYNOP under Maritim Kendari), so
        # the crosswalk, not the attachment, decides which site they belong to.
        synop = {}
        for r in _meta(z, "sources.txt", 2):
            if src.get("synop_parname", "Synop").lower() in r["parname"].lower():
                synop.setdefault(r["ids"][1], []).append(r)
        jobs = []
        for souid, rs in synop.items():
            member = next((f"{var}_STAID{r['ids'][0]:06d}.txt" for r in rs
                           if f"{var}_STAID{r['ids'][0]:06d}.txt" in names), None)
            if member:
                jobs.append((member, {souid}))
        meta = {souid: rs[0] for souid, rs in synop.items()}
    else:
        raise ValueError(f"unknown sacad kind: {src['kind']}")

    for member, keep_souids in jobs:
        df = _data(z, member)
        staid = int(df["STAID"].iloc[0])
        if src["kind"] == "blend_synop":
            souid = next(iter(keep_souids))
            m, sid_txt = meta[souid], str(souid)
        else:
            m = meta.get(int(df["SOUID"].iloc[0]) if src["kind"] == "nonblend" else staid)
            sid_txt = str(staid)
        if m is None or not in_bbox(m["lat"], m["lon"], bbox):
            continue
        key = f"{ns}:{sid_txt}"
        # SYNOP SOUIDs read 99 + WMO number (all 60 Indonesian ones match a BMKG station of
        # the same name, findings F41), so the WMO rule can place them.
        wmo = sid_txt[1:] if src.get("wmo_from_souid") and re.fullmatch(r"99\d{4}", sid_txt) else ""
        stations.setdefault(key, dict(station_key=key, source=ns, network=src.get("network", ""),
                                      source_station_id=sid_txt, name=m["name"], lat=m["lat"],
                                      lon=m["lon"], elev_m=m["elev_m"], country=m["country"], wmo_id=wmo))
        if keep_souids is not None:
            df = df[df["SOUID"].isin(keep_souids)]
        for souid, g in df.groupby("SOUID"):
            missing = (g[var] == -9999) | (g[f"Q_{var}"] == 9)
            v = g[~missing]
            sid = f"{src['name']}:{staid}:{souid}:{var}"
            series.append(dict(series_id=sid, station_key=key, source=src["name"], variable=var,
                               units=src.get("units", ""), day_convention=src.get("day_convention", ""),
                               n_values=len(v), n_missing_code=int(missing.sum()), n_unparsed=0,
                               first=v["date"].min(), last=v["date"].max(), note=f"SOUID {souid}"))
            if len(v):
                obs.append(pd.DataFrame({"series_id": sid, "date": v["date"].values,
                                         "value": v[var].astype(float).values * scale,
                                         "flag": v[f"Q_{var}"].map({1: "src_suspect"}).fillna("").values}))
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series")
    return (pd.DataFrame(list(stations.values())), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
