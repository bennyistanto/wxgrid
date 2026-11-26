"""PU (Ditjen SDA) rain posts from SIHKA, the backend of https://pdsda.sda.pu.go.id (F67, F68).

Input is the raw JSON saved by `tools/fetch_pu_sihka.py` under `path`:
  catalogue_<date>.json   posts with their publications {pubId, type (gauge), variable, year, status}
  pub/<pubId>.json        {head: post metadata, body: {unix_seconds: {value, note, status}}}
Only `variable == "Rainfall"` publications are read. One station per post (key = integration_id),
one series per gauge type (MANUAL, OTOMATIK, TELEMETRI): `pu_sihka:<integration_id>:<gauge>:RR`.

Rules (measured in F68, adopted by the user 2026-11-25 as R1-R6):
- Body keys are 00:00 UTC of the date. A stray key at Unix 0 (value 0, 1,240 files) is dropped.
- R3: every publication is dated by its catalogue year (month and day from the key; 29 Feb dropped when
  the catalogue year is not a leap year), except publications listed as `year_body` in the decisions
  file; publications listed as `copy` are skipped.
- R1 / R2: post-gauge-years that are zero in all 12 months, and all-zero months where CPC or nearby posts
  had >= 100 mm, are listed in the decisions file (`zero_year`, `zero_month_missing`; built by
  `tools/build_pu_sihka_decisions.py`) and dropped as missing (counted in `n_missing_code`).
- R4: one position per post, the most common across its publications; the spread is in the series note.
  Config `coordinates_override` (integration_id -> lat, lon, note) replaces it (/qc 2026-11-25, F76), and so does
  `coordinates_override_csv` (columns integration_id, lat, lon, approx, note; the PU register positions,
  `tools/build_pu_register_overrides.py`, F77). Config entries win over the CSV. `approx` 1 adds `coord_approx`
  to every value of the post.
  Coordinates: WKT `POINT(lon lat)`, degrees-minutes-seconds with LS/LU (no hemisphere: south, all East
  Java [to verify]), or decimal text. Elevation: the median parsed value, ignored above `max_elev_m`.
- R5: provider day flags are kept: note "meragukan" or status "meragukan" -> `src_suspect`;
  note "tidak realistis" or status "tidak_realistis" -> `src_unrealistic`.
- R6: dates are left as read; the day-label step corrects them per series (most posts match CPC one day
  earlier than the BMKG convention, F68 M4).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import in_bbox

EPOCH_CUTOFF = 86400 * 365   # keys below this are the stray Unix-0 entry


def parse_coord(c):
    """`koordinat` text -> (lat, lon, how); (nan, nan, reason) when not readable."""
    s = str(c or "").strip()
    if s in ("", "-", "0", "None"):
        return np.nan, np.nan, "none"
    m = re.match(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", s)
    if m:
        return float(m.group(2)), float(m.group(1)), "wkt"
    t = s.replace("⁰", "°").replace(",", ".")
    m = re.match(r"^\s*-?\s*(\d+\.\d+)\s*°?\s*([SNU]|LS|LU)?\s*-\s*(\d+\.\d+)\s*°?\s*(E|BT)?", t)
    if m:
        la = float(m.group(1))
        north = (m.group(2) or "") in ("N", "U", "LU")
        return (la if north else -la), float(m.group(3)), "decimal text"
    north = bool(re.search(r"\bLU\b|LU\s*-", t))
    south = bool(re.search(r"\bLS\b|LS\s*-", t))
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if len(nums) == 6:
        la = nums[0] + nums[1] / 60 + nums[2] / 3600
        lo = nums[3] + nums[4] / 60 + nums[5] / 3600
    elif len(nums) == 4:
        la, lo = nums[0] + nums[1] / 60, nums[2] + nums[3] / 60
    else:
        return np.nan, np.nan, f"unparsed ({len(nums)} numbers)"
    how = "dms" if (north or south) else "dms, no hemisphere (assumed S)"
    return (la if north else -la), lo, how


def parse_elev(e):
    m = re.search(r"(-?\d+(?:[.,]\d+)?)", str(e or ""))
    return float(m.group(1).replace(",", ".")) if m else np.nan


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p)
                                          * math.sin((d - b) * p / 2) ** 2))


def body_frame(body):
    """Body dict -> DataFrame(date, value, note, day_status), stray Unix-0 key removed."""
    if not isinstance(body, dict) or not body:
        return pd.DataFrame(columns=["date", "value", "note", "day_status"])
    ks = np.array([int(k) for k in body], dtype="int64")
    v = list(body.values())
    d = pd.DataFrame(dict(ts=ks, value=[x.get("value") for x in v], note=[x.get("note") for x in v],
                          day_status=[x.get("status") for x in v]))
    d = d[d.ts >= EPOCH_CUTOFF]
    d["date"] = pd.to_datetime(d.ts, unit="s").dt.normalize()
    return d.drop(columns="ts").reset_index(drop=True)


def redate(dates, year):
    """Put dates into `year` keeping month and day; returns (new dates, mask of kept rows).
    29 Feb is dropped when `year` is not a leap year."""
    dates = pd.DatetimeIndex(dates)
    keep = ~((dates.month == 2) & (dates.day == 29) & (not pd.Timestamp(year, 1, 1).is_leap_year))
    new = pd.to_datetime(dict(year=year, month=dates.month[keep], day=dates.day[keep]))
    return pd.DatetimeIndex(new), np.asarray(keep)


def load_publications(path):
    """Catalogue rows for Rainfall publications: pubId, post_id, integration_id, name, unit, gauge, year_cat, year_status."""
    cat = json.loads(sorted(Path(path).glob("catalogue_*.json"))[-1].read_text(encoding="utf-8"))
    return pd.DataFrame([dict(pubId=d["pubId"], post_id=p["id"], integration_id=p.get("integration_id") or p["id"],
                              name=p["name"], unit=p.get("unit", ""), gauge=d["type"], year_cat=int(d["year"]),
                              year_status=d.get("status", ""))
                         for p in cat for d in p.get("data", []) if d.get("variable") == "Rainfall"])


def dated_values(path, pubs, year_body=frozenset(), copies=frozenset()):
    """Yield (pub row, head, DataFrame with corrected dates) for every publication not skipped as a copy."""
    for r in pubs.itertuples():
        if r.pubId in copies:
            continue
        f = Path(path) / "pub" / f"{r.pubId}.json"
        if not f.exists():
            continue
        j = json.loads(f.read_text(encoding="utf-8"))
        d = body_frame(j.get("body"))
        if len(d) and r.pubId not in year_body and (d.date.dt.year != r.year_cat).any():
            new, keep = redate(d.date, r.year_cat)
            d = d[keep].assign(date=new.values)
        yield r, (j.get("head") or {}), d


def provider_flag(note, status):
    n, s = str(note or "").lower(), str(status or "").lower()
    if "tidak realistis" in n or s == "tidak_realistis":
        return "src_unrealistic"
    if "meragukan" in n or s == "meragukan":
        return "src_suspect"
    return ""


def read(src, bbox):
    path = Path(src["path"])
    pubs = load_publications(path)
    dec = pd.read_csv(src["decisions"], dtype=str, keep_default_na=False) if src.get("decisions") else pd.DataFrame(columns=["kind", "pubId", "integration_id", "gauge", "period"])
    year_body = frozenset(dec.loc[dec.kind == "year_body", "pubId"])
    copies = frozenset(dec.loc[dec.kind == "copy", "pubId"])
    drop_y = {(r.integration_id, r.gauge, str(r.period)) for r in dec[dec.kind == "zero_year"].itertuples()}
    drop_m = {(r.integration_id, r.gauge, str(r.period)) for r in dec[dec.kind == "zero_month_missing"].itertuples()}
    max_elev = float(src.get("max_elev_m", 4900))
    overrides = {}
    if src.get("coordinates_override_csv"):
        oc = pd.read_csv(src["coordinates_override_csv"], dtype={"integration_id": str}, keep_default_na=False)
        overrides = {r.integration_id: dict(lat=r.lat, lon=r.lon, note=r.note, approx=int(r.approx)) for r in oc.itertuples()}
    overrides.update({str(k): v for k, v in (src.get("coordinates_override") or {}).items()})

    pos, elev, names, meta = {}, {}, {}, {}
    frames, n_drop, n_dup_days = {}, Counter(), Counter()
    for r, head, d in dated_values(path, pubs, year_body, copies):
        key = r.integration_id
        la, lo, how = parse_coord(head.get("koordinat"))
        if not np.isnan(la):
            pos.setdefault(key, []).append((round(la, 5), round(lo, 5), how))
        e = parse_elev(head.get("elevesi"))
        if not np.isnan(e) and 0 <= e <= max_elev:
            elev.setdefault(key, []).append(e)
        names.setdefault(key, r.name)
        meta.setdefault(key, dict(unit=r.unit, post_id=r.post_id))
        if d.empty:
            continue
        d = d.assign(value=pd.to_numeric(d.value, errors="coerce"))
        ym = d.date.dt.to_period("M").astype(str)
        y = d.date.dt.year.astype(str)
        gone = np.array([(key, r.gauge, a) in drop_y or (key, r.gauge, b) in drop_m for a, b in zip(y, ym)], dtype=bool)
        n_drop[(key, r.gauge)] += int(gone.sum())
        d = d[~gone]
        d = d.assign(flag=[provider_flag(n, s) for n, s in zip(d.note, d.day_status)])
        frames.setdefault((key, r.gauge), []).append(d[["date", "value", "flag"]])

    stations, series, obs = [], [], []
    n_skip_pos = 0
    for key in names:
        p = pos.get(key)
        if not p:
            n_skip_pos += 1
            continue
        (la, lo, how), _ = Counter(p).most_common(1)[0]
        if key in overrides:
            ov = overrides[key]
            la, lo, how = float(ov["lat"]), float(ov["lon"]), f"override: {ov.get('note', '')}"
        approx = key in overrides and bool(int(overrides[key].get("approx", 0) or 0))
        if not in_bbox(la, lo, bbox):
            n_skip_pos += 1
            continue
        spread = max(km(la, lo, a, b) for a, b, _ in p)
        skey = f"{src['name']}:{key}"
        made = False
        for (k, gauge), fs in frames.items():
            if k != key:
                continue
            df = pd.concat(fs, ignore_index=True).sort_values("date")
            df = df[df.value.notna()]
            if df.empty:
                continue
            sid = f"{skey}:{gauge}:RR"
            n_dup_days[sid] = int(df.duplicated("date").sum())
            series.append(dict(series_id=sid, station_key=skey, source=src["name"], variable="RR",
                               units=src.get("units", "mm"), day_convention=src.get("day_convention", ""),
                               n_values=len(df), n_missing_code=n_drop[(key, gauge)], n_unparsed=0,
                               first=df.date.min(), last=df.date.max(),
                               note=f"{names[key]} ({meta[key]['unit']}); gauge {gauge}; position {how}, spread across "
                                    f"publications {spread:.1f} km; zero years/months dropped {n_drop[(key, gauge)]}"))
            fl = df.flag.values
            if approx:
                fl = np.array([f"{f};coord_approx" if f else "coord_approx" for f in fl], dtype=object)
            obs.append(pd.DataFrame({"series_id": sid, "date": df.date.values, "value": df.value.values.astype(float),
                                     "flag": fl}))
            made = True
        if made:
            stations.append(dict(station_key=skey, source=src["name"], network=src.get("network", ""),
                                 source_station_id=key, name=names[key], lat=la, lon=lo,
                                 elev_m=float(np.median(elev[key])) if key in elev else np.nan,
                                 country=src.get("country", "ID"), wmo_id=""))
    print(f"  read {path}: {len(stations)} stations, {len(series)} series; copies skipped {len(copies)}; "
          f"zero years/months dropped {sum(n_drop.values())} values; posts without a usable position {n_skip_pos}; "
          f"same-date values within a series {sum(n_dup_days.values())}")
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
