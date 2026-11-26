"""Reader for the "one row per station-month, one column per day" layout, as in the
national BMKG daily rainfall set `CH_IND.zip` (sheets `1990.xls`..`2001.xls`): columns
`NO STA`, `STA`, `TAHUN`, `BULAN`, `R1..R31`. Station coordinates come from a catalogue
sheet in the same archive (`STA-BMG.XLS`), keyed by WMO number, where the station id maps
to WMO as `wmo = id_offset + NO STA` (id_offset 96000 here).

Config example:

    - name: chind
      reader: station_month_grid
      path: F:/temp/station/additional-sources/DATA IKLIM/CH_IND.zip
      year_pattern: '^(19|20)\\d\\d\\.xls$'
      id_col: NO STA
      name_col: STA
      year_col: TAHUN
      month_col: BULAN
      day_prefix: R
      id_to_wmo_offset: 96000
      missing_codes: [9999]
      variable: RR
      units: mm
      catalogue: {member: STA-BMG.XLS, sheet: STA-BMG, header_row: 2,
                  wmo_col: 0, lat_col: 1, lon_col: 2, elev_col: 3, name_col: 4}

Text codes listed in `unmeasurable_text` (e.g. TU) become unmeasurable rows like the numeric
`unmeasurable_codes`; any other non-numeric text is counted per series (`n_unparsed`).

Variants handled (F72, CH_IND 1990-1993 and 1997): `id_col` may be a list of candidate headers (the
first one present is used); headers are matched ignoring spaces and dots (`No. Sta`); the header is
searched in every sheet, not only the first (1997 has an empty first sheet); ids, years and months
may be numbers or numeric text; an id >= `id_to_wmo_offset` is already a WMO number (1990-1993 write
96001, 1994-2001 write 1); a two-digit year means 19xx.

Everything about the layout is in the config, so a differently named but same-shaped set
(e.g. the `rini` files with `D1..D31`) is a second config entry, not new code.
"""

import re
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

from ..config import in_bbox


def _books(src):
    """Yield (name, raw-bytes-or-path) for every year file, from a .zip or a folder."""
    p = Path(src["path"])
    pat = re.compile(src["year_pattern"], re.I)
    if p.suffix.lower() == ".zip":
        z = zipfile.ZipFile(p)
        for n in z.namelist():
            if pat.search(Path(n).name):
                yield n, z.read(n)
    else:
        for f in sorted(p.iterdir()):
            if pat.search(f.name):
                yield f.name, f.read_bytes()


def _catalogue(src):
    """WMO -> dict(lat, lon, elev, name). A `catalogue_csv` (wmo, lat, lon, elev, name) is
    preferred; a `catalogue` sheet in the archive is a fallback/supplement."""
    out = {}
    c = src.get("catalogue")
    if c:
        p = Path(src["path"])
        data = zipfile.ZipFile(p).read(c["member"]) if p.suffix.lower() == ".zip" else (p / c["member"]).read_bytes()
        sh = xlrd.open_workbook(file_contents=data).sheet_by_name(c["sheet"])
        for r in range(c["header_row"] + 1, sh.nrows):
            w = sh.cell_value(r, c["wmo_col"])
            try:
                wmo = int(float(w))
            except (TypeError, ValueError):
                continue
            lat, lon = sh.cell_value(r, c["lat_col"]), sh.cell_value(r, c["lon_col"])
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or (lat == 0 and lon == 0):
                continue
            elev = sh.cell_value(r, c["elev_col"])
            out[wmo] = dict(lat=float(lat), lon=float(lon), name=str(sh.cell_value(r, c["name_col"])).strip(),
                            elev=float(elev) if isinstance(elev, (int, float)) else np.nan)
    if src.get("catalogue_csv"):  # authoritative coords (e.g. from the compiled set) win
        cc = pd.read_csv(src["catalogue_csv"])
        for r in cc.itertuples():
            out[int(r.wmo)] = dict(lat=float(r.lat), lon=float(r.lon),
                                   elev=float(r.elev) if pd.notna(r.elev) else np.nan, name=str(r.name))
    return out


def _num(v):
    """Number or numeric text -> float; anything else -> None."""
    if isinstance(v, (int, float)) and v != "":
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def read(src, bbox):
    var = src["variable"]
    missing = set(float(x) for x in src.get("missing_codes", []))
    offset = int(src["id_to_wmo_offset"])
    cat = _catalogue(src)
    ns = src.get("station_namespace", src["name"])
    long = []  # (wmo, date, value)
    skipped = set()
    unmeas = set(float(x) for x in src.get("unmeasurable_codes", []))
    unmeas_text = {str(x).upper() for x in src.get("unmeasurable_text", [])}
    text_skipped = Counter()
    ceiling = float(src.get("value_ceiling", 2000))   # above this = data error, dropped
    norm = lambda s: str(s).strip().upper().replace(" ", "").replace(".", "")
    id_cols = [norm(x) for x in (src["id_col"] if isinstance(src["id_col"], list) else [src["id_col"]])]
    yc, mc = norm(src["year_col"]), norm(src["month_col"])
    unmeas_rows = []
    for name, data in _books(src):
        found = None
        for sh in xlrd.open_workbook(file_contents=data).sheets():   # first sheet holding the header
            for r in range(min(6, sh.nrows)):
                hdr = [norm(sh.cell_value(r, c)) for c in range(sh.ncols)]
                idc = next((h for h in id_cols if h in hdr), None)
                if idc and yc in hdr and mc in hdr:
                    found = (sh, r, hdr, idc)
                    break
            if found:
                break
        if found is None:
            skipped.add(name)
            continue
        sh, hrow, hdr, idc = found
        i_id, i_y, i_m = hdr.index(idc), hdr.index(yc), hdr.index(mc)
        dp = norm(src["day_prefix"])
        day_cols = [(c, int(h[len(dp):])) for c, h in enumerate(hdr) if re.fullmatch(dp + r"\d+", h)]
        for r in range(hrow + 1, sh.nrows):
            sid, yr, mo = (_num(sh.cell_value(r, i)) for i in (i_id, i_y, i_m))
            if sid is None or yr is None or mo is None:
                continue
            wmo = int(sid) if sid >= offset else offset + int(sid)   # 1990-1993 already write the WMO number
            if wmo not in cat:
                skipped.add(f"wmo:{wmo}")
                continue
            yr, mo = int(yr), int(mo)
            if yr < 100:   # two-digit year (1997 file)
                yr += 1900
            for c, day in day_cols:
                v = sh.cell_value(r, c)
                if isinstance(v, str):
                    t = v.strip()
                    if t.upper().rstrip(".") in unmeas_text:   # e.g. TU in CH_IND = trace (F60/F61)
                        unmeas_rows.append((wmo, yr, mo, day))
                        continue
                    try:
                        v = float(t.replace(",", "."))
                    except ValueError:
                        if t:   # non-empty text that is not a value: counted, not silently lost
                            text_skipped[(wmo, t.upper()[:12])] += 1
                        continue
                if not isinstance(v, (int, float)) or v in missing:
                    continue
                if v in unmeas:                       # exact sentinel: before the ceiling
                    unmeas_rows.append((wmo, yr, mo, day))
                elif 0 <= v <= ceiling:               # above the ceiling = data error, dropped
                    long.append((wmo, yr, mo, day, float(v)))
    if not long:
        raise ValueError(f"{src['name']}: no values read (skipped: {sorted(skipped)[:10]})")
    df = pd.DataFrame(long, columns=["wmo", "year", "month", "day", "value"])
    df["flag"] = ""
    if unmeas_rows:
        u = pd.DataFrame(unmeas_rows, columns=["wmo", "year", "month", "day"]).assign(value=np.nan, flag="unmeasurable")
        df = pd.concat([df, u], ignore_index=True)
    df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=df.day), errors="coerce")
    df = df[df["date"].notna()]

    stations, series, obs = [], [], []
    for wmo, g in df.groupby("wmo"):
        m = cat[wmo]
        if not in_bbox(m["lat"], m["lon"], bbox):
            continue
        key = f"{ns}:{wmo}"
        sid = f"{src['name']}:{wmo}:{var}"
        stations.append(dict(station_key=key, source=ns, network=src.get("network", ""),
                             source_station_id=str(wmo), name=m["name"], lat=m["lat"], lon=m["lon"],
                             elev_m=m["elev"], country=src.get("country", "ID"), wmo_id=str(wmo)))
        # a measured value wins over an unmeasurable flag on the same date
        g = g.sort_values("value").drop_duplicates("date", keep="first").sort_values("date")
        series.append(dict(series_id=sid, station_key=key, source=src["name"], variable=var,
                           units=src.get("units", ""), day_convention=src.get("day_convention", ""),
                           n_values=int(g["value"].notna().sum()), n_missing_code=0,
                           n_unparsed=sum(n for (w, _), n in text_skipped.items() if w == wmo),
                           first=g["date"].min(), last=g["date"].max(),
                           note=f"WMO {wmo}; unmeasurable {int((g['flag'] == 'unmeasurable').sum())}"))
        obs.append(pd.DataFrame({"series_id": sid, "date": g["date"].values,
                                 "value": g["value"].values, "flag": g["flag"].values}))
    if text_skipped:
        tok = Counter()
        for (_, t), n in text_skipped.items():
            tok[t] += n
        print(f"  text cells skipped (not values): {dict(tok.most_common(8))}")
    print(f"  read {src['path']}: {len(stations)} stations, {len(series)} series"
          + (f" ({len([s for s in skipped if s.startswith('wmo:')])} WMO not in catalogue)" if skipped else ""))
    return (pd.DataFrame(stations), pd.DataFrame(series),
            pd.concat(obs, ignore_index=True) if obs else pd.DataFrame(columns=["series_id", "date", "value", "flag"]))
