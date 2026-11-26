"""Export a merged variable as deliverable CSVs: long table, wide matrix, source-code
matrix, site table and a README. Reads only the compiled outputs, so it can be re-run
without rebuilding.

    python -m wxgrid export configs/idn_bmkg_sacad.yaml rainfall

With `mirror_dir` set on the job, the written files are also copied there (relative paths are taken from
the repository root), so the draft release is tracked in `data/`.
"""

import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import VARIABLES

LABEL_CODE = {"verified": "V", "interpolated": "I", "uncertain": "U", "unverified": "N", "": "-", "collision": "C"}


def _sources(cfg):
    """source name -> dict(code, title, citation, day_convention) from the config."""
    out = {}
    for s in cfg["sources"]:
        conv = s.get("day_convention", "")
        if isinstance(conv, dict):
            conv = "; ".join(f"{k}: {v}" for k, v in conv.items())
        out[s["name"]] = dict(code=s.get("export_code", s["name"][:1].upper()), title=s.get("network", s["name"]),
                              citation=s.get("citation", ""), day_convention=conv)
    return out


def export(cfg, job_name):
    job = cfg["export"][job_name]
    var = job["variable"]
    comp = Path(cfg["output_dir"])
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    prefix = job["prefix"]
    src = _sources(cfg)

    sites = pd.read_csv(comp / "sites.csv", dtype={"wmo_id": str})
    stations = pd.read_csv(comp / "stations.csv.gz", dtype={"wmo_id": str, "source_station_id": str})
    series = pd.read_csv(comp / "series.csv.gz", usecols=["series_id", "station_key", "source"])
    m = pd.read_csv(comp / f"merged_{var}.csv.gz", dtype={"flag": str, "label": str})
    m["date"] = pd.to_datetime(m["date"])
    t0, t1 = pd.Timestamp(job["start"]), pd.Timestamp(job["end"])
    keep_sites = sites[sites["country"].isin(job.get("countries", sites["country"].unique()))]["site_id"]
    m = m[m["site_id"].isin(keep_sites) & m["date"].between(t0, t1)].copy()
    m["flag"], m["label"] = m["flag"].fillna(""), m.get("label", pd.Series("", index=m.index)).fillna("")

    # provenance per value: source dataset and the original station
    ser = series.merge(stations[["station_key", "name", "source_station_id"]], on="station_key", how="left")
    ser = ser.set_index("series_id")
    m["source"] = m["series_id"].map(ser["source"])
    m["source_dataset"] = m["source"].map(lambda s: src.get(s, {}).get("title", s))
    m["source_station"] = m["series_id"].map(ser["name"]) + " [" + m["series_id"].map(ser["station_key"]) + "]"

    # 1. long table
    long = m[["site_id", "date", "value", "flag", "label", "date_raw", "source_dataset", "source_station", "series_id"]]
    long = long.rename(columns={"value": f"{var.lower()}_{VARIABLES[var]['units']}", "label": "day_label"})
    long = long.sort_values(["site_id", "date"])
    long.assign(date=long["date"].dt.strftime("%Y-%m-%d")).to_csv(out / f"{prefix}_long.csv.gz", index=False, compression="gzip")

    # 2. site table
    used = sites[sites["site_id"].isin(m["site_id"].unique())].copy()
    g = m.groupby("site_id")
    first, last = g["date"].min(), g["date"].max()
    n_val = g["value"].count()
    span = (last - first).dt.days + 1
    used = used.set_index("site_id")
    used["first_date"], used["last_date"] = first.dt.date, last.dt.date
    used["n_days_with_value"] = n_val
    used["n_unmeasurable"] = g["flag"].apply(lambda f: int(f.str.contains("unmeasurable").sum()))
    used["pct_complete_first_to_last"] = (100 * g.size() / span).round(1)
    used["n_flagged"] = g["flag"].apply(lambda f: int(f.ne("").sum()))
    src_share = (m.groupby(["site_id", "source"]).size() / g.size()).unstack(fill_value=0)
    used["source_shares"] = src_share.apply(
        lambda r: "; ".join(f"{k} {v:.0%}" for k, v in r.sort_values(ascending=False).items() if v > 0), axis=1)
    lab = (m.groupby(["site_id", "label"]).size() / g.size()).unstack(fill_value=0)
    for k in ["verified", "interpolated", "uncertain", "unverified"]:
        used[f"day_label_{k}"] = (lab[k] if k in lab else 0).round(3)
    members = stations.groupby("site_id").apply(
        lambda d: "; ".join(f"{n} [{k}]" for k, n in zip(d["station_key"], d["name"])), include_groups=False)
    used["member_stations"] = members
    used = used.reset_index()
    cols = ["site_id", "name", "lat", "lon", "elev_m", "country", "wmo_id", "representative_station", "member_stations",
            "sources", "first_date", "last_date", "n_days_with_value", "n_unmeasurable", "pct_complete_first_to_last",
            "n_flagged", "source_shares", "day_label_verified", "day_label_interpolated", "day_label_uncertain",
            "day_label_unverified"]
    used[cols].to_csv(out / f"{prefix}_sites.csv", index=False)

    # 3-4. wide value matrix and wide source-code matrix
    days = pd.date_range(t0, t1, freq="D")
    order = sorted(used["site_id"])
    wide = m.pivot(index="date", columns="site_id", values="value").reindex(index=days, columns=order)
    wide.index.name = "date"
    wide.to_csv(out / f"{prefix}_wide.csv.gz", date_format="%Y-%m-%d", compression="gzip")
    code = (m["source"].map(lambda s: src.get(s, {}).get("code", "?")) + m["label"].map(LABEL_CODE).fillna("-")
            + np.where(m["flag"].ne(""), "!", ""))
    wcode = m.assign(code=code).pivot(index="date", columns="site_id", values="code").reindex(index=days, columns=order)
    wcode.index.name = "date"
    wcode.to_csv(out / f"{prefix}_wide_source.csv.gz", date_format="%Y-%m-%d", compression="gzip")

    # 5. README
    _readme(out / f"{prefix}_README.md", cfg, job, var, src, m, used, prefix)
    print(f"[export] {job_name}: {len(long):,} site-days, {len(used)} sites, {days[0].date()}..{days[-1].date()} -> {out}")
    if job.get("mirror_dir"):
        _mirror(out, prefix, job["mirror_dir"])


def _mirror(out, prefix, mirror_dir):
    """Copy this release's files to `mirror_dir`, replacing older copies with the same prefix."""
    dst = Path(mirror_dir)
    if not dst.is_absolute():
        dst = Path(__file__).resolve().parents[2] / dst
    dst.mkdir(parents=True, exist_ok=True)
    names = [f"{prefix}_{s}" for s in ("long.csv.gz", "wide.csv.gz", "wide_source.csv.gz", "sites.csv", "README.md")]
    for n in names:
        shutil.copy2(out / n, dst / n)
    print(f"[export] copied {len(names)} files -> {dst}")


def _readme(path, cfg, job, var, src, m, used, prefix):
    meta = VARIABLES[var]
    dl = cfg.get("daylabel") or {}
    present = sorted(m["source"].unique())
    lines = [
        f"# {prefix}", "",
        f"{meta['long_name'][0].upper()}{meta['long_name'][1:]} ({meta['units']}) at {len(used)} sites, {job['start']} to {job['end']}, "
        f"countries {', '.join(job.get('countries', []))}. Built {date.today()} by wxgrid from "
        f"`{cfg['_path']}` (compiled data in `{cfg['output_dir']}`).", "",
        "Values are station observations combined per site; nothing is interpolated. A site is one or more",
        "source stations judged to be the same place (crosswalk). The highest-priority source supplies each day;",
        "lower-priority sources only fill days the higher ones do not have, and only if they passed an overlap",
        f"test against the primary. Priority: {', '.join(cfg['merge']['priority'])}.", "",
        "## Files", "",
        f"- `{prefix}_long.csv.gz`: one row per site-day with a value or an observed-but-unmeasurable day.",
        f"- `{prefix}_wide.csv.gz`: one row per date, one column per site_id; empty = no observation.",
        f"- `{prefix}_wide_source.csv.gz`: same shape; code of the source behind each value (below).",
        f"- `{prefix}_sites.csv`: one row per site: location, member stations, record, completeness, source and day-label shares.", "",
        "## Long table columns", "",
        f"- `site_id`, `date` (target day convention, see below), `{var.lower()}_{meta['units']}` (empty for unmeasurable days)",
        "- `flag`: empty = no remark; otherwise `;`-separated codes (below)",
        "- `day_label`: verified / interpolated / uncertain / unverified (how sure the date is)",
        "- `date_raw`: the date as written in the source, before day-label correction",
        "- `source_dataset`, `source_station` (name [station_key]), `series_id` (exact source series)", "",
        "## Day convention", "",
        f"Target: {dl.get('target', 'as delivered')}. Dates of rainfall series in {', '.join(dl.get('countries', []))} were shifted",
        "to it per series and period, using IMERG Final (2001+) and CPC-UNI (1979+) as references; `day_label` says how",
        "sure each date is. Before 1979 no reference exists and dates are as delivered (`unverified`).", "",
        "## Flags", "",
        "- `unmeasurable`: observed day, rain too small to measure (BMKG 8888 'data tidak terukur'; compendium -333;",
        "  a 0 in the BMG/Data and Sumsel post forms, whose rain-day counts include it); no value",
        "- `dash_month`: 0 mm from a month written entirely as '-' (dry day in these forms); most such months are dry,",
        "  some are unreported wet-season months: check against neighbours or a gridded reference before use",
        "- `above_max` / `below_min`: outside the plausibility bounds in the config (kept, review before use)",
        "- `src_suspect` (SACA&D quality code 1; 'data meragukan' in PU SIHKA posts), `src_unrealistic` ('data tidak realistis'",
        "  in PU SIHKA posts), `code_suspect` (compendium 200.0 mm, code-like), `src_qflag_X` (GHCN)",
        "- `coord_approx`: station position known only approximately; `source_conflict`: two copies of one record disagree,",
        "  the preferred copy is used",
        "- `suspect_accumulation`, `zero_month_suspect`, `zero_run_wet_season`, `day_label_uncertain`, `day_label_unverified`:",
        "  raised by station checks (/qc) and kept for review",
        "- `unharmonised_source`: from a source that failed the overlap test, used only after the primary ended", "",
        "Values flagged by QC as zero-filled blocks, copied data, duplicated months or isolated codes were removed",
        "from this product (they remain in the compiled observations, flagged `qc_excluded`).", "",
        "## Source codes (wide_source)", "",
        "Code = source letter + day-label letter (V verified, I interpolated, U uncertain, N unverified, - not assessed),",
        "followed by `!` if the value carries any flag. A code with an empty value in the wide matrix is an",
        "observed day with unmeasurable rain (`unmeasurable`).", "",
        "| Letter | Source | Day convention as delivered | Citation |", "|---|---|---|---|",
    ]
    for s in present:
        d = src.get(s, {})
        lines.append(f"| {d.get('code', '?')} | {d.get('title', s)} | {d.get('day_convention', '')} | {d.get('citation', '')} |")
    lines += ["", "## Use", "",
              "Check `flag` before use: gridding should at least drop `above_max`, `below_min`, `src_suspect` and",
              "`code_suspect`, and decide how to treat `unmeasurable` (trace). BMKG-derived data are subject to BMKG's",
              "data access policy (Peraturan BMKG No. 4/2022); check redistribution terms before sharing."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
