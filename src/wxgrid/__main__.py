"""Command line.

    python -m wxgrid consolidate configs/idn_bmkg_sacad.yaml [--reread]
    python -m wxgrid export configs/idn_bmkg_sacad.yaml rainfall

Run from `src/` or with `src/` on PYTHONPATH. Each source is read once and cached in
`<output_dir>/_staging/`; `--reread` ignores the cache.
"""

import argparse
import json
import shutil
import time

import pandas as pd

from . import __version__, config, writers
from .consolidate import crosswalk, daylabel, flags, merge
from .readers import READERS


def _read_sources(cfg, reread):
    stage = cfg["output_dir"] / "_staging"
    stage.mkdir(parents=True, exist_ok=True)
    parts = []
    for src in cfg["sources"]:
        cache = stage / f"{src['name']}.pkl"
        if cache.exists() and not reread:
            print(f"[cache] {src['name']}")
            parts.append(pd.read_pickle(cache))
            continue
        t = time.time()
        print(f"[read] {src['name']} ({src['reader']})")
        out = READERS[src["reader"]](src, cfg["domain"].get("bbox"))
        pd.to_pickle(out, cache)
        print(f"[read] {src['name']} done in {time.time() - t:.0f} s")
        parts.append(out)
    stations = pd.concat([p[0] for p in parts], ignore_index=True)
    # one row per station_key: several series sources can share a station namespace
    stations = stations.drop_duplicates("station_key", keep="first").reset_index(drop=True)
    series = pd.concat([p[1] for p in parts], ignore_index=True)
    obs = pd.concat([p[2] for p in parts], ignore_index=True)
    dup = series["series_id"].duplicated(keep=False)
    if dup.any():  # a reader (or a stale cache) emitted a non-unique series_id
        bad = sorted(series.loc[dup, "series_id"].unique())
        raise ValueError(f"{len(bad)} duplicate series_id across sources, e.g. {bad[:5]}. "
                         f"Fix the reader and delete that source's _staging/*.pkl, then re-run.")
    return stations, series, obs


def _exclusions(cfg, obs):
    """QC exclusion tables (config qc.exclusions): flag, never delete."""
    paths = (cfg.get("qc") or {}).get("exclusions", [])
    if not paths:
        return obs
    table = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    print(f"[qc] exclusions: {len(table)} periods from {len(paths)} file(s)")
    return flags.apply_exclusions(obs, table)


def _daylabel(cfg, stations, series, obs, site_of):
    """Detect and apply day-label offsets for the configured variables."""
    dl = cfg["daylabel"]
    print("[daylabel] reference grid")
    grids = [daylabel.gridded_reference(series, stations, g, cfg["output_dir"] / "_staging" / f"daylabel_{g['name']}.pkl")
             for g in dl.get("gridded_references", [])]
    print("[daylabel] detect")
    seg, blocks = daylabel.detect(obs, series, stations, site_of, cfg, grids)
    if len(blocks):
        writers.write_csv(blocks, cfg["output_dir"] / "daylabel_blocks.csv.gz")
    var_of = series.set_index("series_id")["variable"]
    target = obs["series_id"].map(var_of).isin(dl.get("variables", ["RR"]))
    shifted = daylabel.apply(obs[target], seg)
    rest = obs[~target].assign(date_raw=obs.loc[~target, "date"], label="")
    writers.write_csv(seg, cfg["output_dir"] / "daylabel_segments.csv")
    return pd.concat([shifted, rest], ignore_index=True), seg


def consolidate(cfg, reread=False):
    out = cfg["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    stations, series, obs = _read_sources(cfg, reread)
    obs["flag"] = obs["flag"].fillna("")
    obs = flags.apply_bounds(obs, series, cfg["flag_bounds"])
    obs = flags.flag_duplicates(obs)
    n_flag = obs[obs["flag"].ne("")].merge(series[["series_id", "variable"]]).groupby(["variable"])["flag"].value_counts()

    print("[crosswalk]")
    pairs, series_pairs, root = crosswalk.build(stations, series, obs, cfg)
    sites, site_of = merge.sites_table(stations, series, root, cfg["merge"]["priority"])

    seg = None
    if cfg.get("daylabel"):
        obs, seg = _daylabel(cfg, stations, series, obs, site_of)
        obs = _exclusions(cfg, obs)
        print("[crosswalk] on corrected dates")
        pairs, series_pairs, root = crosswalk.build(stations, series, obs, cfg)
        sites, site_of = merge.sites_table(stations, series, root, cfg["merge"]["priority"])
    stations["site_id"] = stations["station_key"].map(site_of)

    print("[write] tables")
    writers.write_csv(stations, out / "stations.csv.gz")
    writers.write_csv(series, out / "series.csv.gz")
    writers.write_csv(sites, out / "sites.csv")
    writers.write_csv(pairs, out / "crosswalk_stations.csv")
    writers.write_csv(series_pairs, out / "crosswalk_series.csv")
    var_of = series.set_index("series_id")["variable"]
    summary = dict(wxgrid_version=__version__, config=cfg["_path"], n_stations=len(stations),
                   n_sites=len(sites), n_series=len(series), n_obs=int(len(obs)),
                   relations=pairs["relation"].value_counts().to_dict() if len(pairs) else {},
                   needs_review=int(pairs["needs_review"].sum()) if len(pairs) else 0,
                   flags={f"{v}:{f}": int(n) for (v, f), n in n_flag.items()}, variables={})
    if seg is not None:
        days = (seg["end"] - seg["start"]).dt.days + 1
        summary["daylabel"] = {f"{s}:{o:+d}": int(n) for (s, o), n in days.groupby([seg["status"], seg["offset"]]).sum().items()}
        summary["daylabel_labels"] = obs["label"].value_counts().to_dict()
    def _conv(s):  # a source may give one convention, or one per source flag
        c = s.get("day_convention", "")
        return "; ".join(f"{k}: {v}" for k, v in c.items()) if isinstance(c, dict) else c
    day_conv = " | ".join(f"{s['name']}: {_conv(s)}" for s in cfg["sources"])
    fill_reports = []
    for var in sorted(series["variable"].unique()):
        o = obs[obs["series_id"].map(var_of) == var]
        writers.write_csv(o, out / f"observations_{var}.csv.gz")
        mv, rep = merge.merged(obs=o, series=series, site_of=site_of, cfg=cfg, variable=var)
        writers.write_csv(mv, out / f"merged_{var}.csv.gz")
        conv = day_conv
        dl = cfg.get("daylabel") or {}
        if var in dl.get("variables", []):
            conv = (f"{dl.get('target', '')}; dates of series in {dl.get('countries', 'all countries')} shifted "
                    f"to it (see {var}_label); other series unshifted, as delivered: {day_conv}")
        writers.write_merged_netcdf(mv, sites, var, out / f"merged_{var}.nc", cfg["merge"]["netcdf_start"], cfg, conv)
        if len(rep):
            fill_reports.append(rep.assign(variable=var))
        summary["variables"][var] = dict(n_series=int((series["variable"] == var).sum()), n_obs=int(len(o)),
                                         n_sites_merged=int(mv["site_id"].nunique()) if len(mv) else 0,
                                         n_merged_values=int(len(mv)))
        print(f"[write] {var}: {len(o):,} obs, {len(mv):,} merged values")
    if fill_reports:
        writers.write_csv(pd.concat(fill_reports, ignore_index=True), out / "merge_fillers.csv")
        fr = pd.concat(fill_reports)
        summary["fillers"] = {f"{v}:{s}": int(n) for (v, s), n in fr.groupby(["variable", "status"]).size().items()}
    shutil.copy(cfg["_path"], out / "config_used.yaml")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser(prog="wxgrid")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("consolidate", help="compile station data from all configured sources")
    c.add_argument("config")
    c.add_argument("--reread", action="store_true", help="ignore the per-source cache")
    e = sub.add_parser("export", help="write deliverable CSVs for one export job in the config")
    e.add_argument("config")
    e.add_argument("job", help="name of a job under `export:` in the config, e.g. rainfall")
    args = ap.parse_args()
    if args.cmd == "consolidate":
        consolidate(config.load(args.config), reread=args.reread)
    elif args.cmd == "export":
        from . import export
        export.export(config.load(args.config), args.job)


if __name__ == "__main__":
    main()
