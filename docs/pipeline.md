# Pipeline

How the compiled station dataset is built. The rules behind each step, and the files and columns it writes,
are in [station-dataset.md](station-dataset.md).

## Steps

`python -m wxgrid consolidate <config>` reads every source named in the config and writes the compiled
dataset. Nothing dataset-specific is in the code: each source's reader, units, missing codes and day
convention come from the config.

1. **Read** each source with its own reader (`src/wxgrid/readers/`), decoding that source's codes by its
   own rules. For example, BMKG 8888 and "TU" (*Tidak Terukur*) mean rain fell but was too little to
   measure, while 9999 means no observation.
2. **Flag**, never delete: values outside plausibility bounds, duplicates within a source, and the
   source's own quality marks are kept with a flag.
3. **Crosswalk**: stations from different archives that are the same gauge are linked into one site,
   by distance, name and agreement of their data. Pairs whose data contradict a join are left for review.
   Some sources never join others: PU rain posts stay apart from BMKG stations, and the Dutch-era KNMI
   gauges stay their own sites.
4. **Day label**: rainfall dates are shifted per series and period to one convention (24 hours ending
   07:00 local, labelled with the end date), using IMERG and CPC as references. Every value records how
   sure its date is. Before 1979 there is no reference, so earlier dates are kept as delivered and
   labelled `unverified`.
5. **QC exclusions**: periods that checks found to be copied, zero-filled or code-like are flagged
   `qc_excluded` and left out of merged views.
6. **Merge**: one value per site and day, from the highest-priority source, with lower-priority sources
   filling only days it lacks, after an overlap test.

`python -m wxgrid export <config> rainfall` writes the release tables (long, wide, wide-source, site
table and a README) from the merged view, and copies them to `data/` in this repository (job option
`mirror_dir`).

## Running

From `src/`:

```
python -m wxgrid consolidate ../configs/idn_bmkg_sacad.yaml
python -m wxgrid export ../configs/idn_bmkg_sacad.yaml rainfall
```

A full consolidation takes roughly 15 to 20 minutes. Each source is cached under `<output_dir>/_staging/`
(keyed by source name): after changing a reader or a source's config, delete that source's `.pkl`, or
run with `--reread`.

Tests, from the repository root:

```
python -m pytest tests
```

## Requirements

Python 3.12 with pandas, numpy, xarray, netCDF4, xlrd, openpyxl, PyYAML and rapidfuzz; pytest for the tests.
Some tools also use requests, scipy, matplotlib, geopandas and shapely.

## Repository layout

| Path | What |
|---|---|
| `src/wxgrid/` | The package: `readers/` (one per source format), `consolidate/` (flags, crosswalk, day label, merge), `writers.py`, `export.py`, `schema.py` |
| `data/` | Draft rainfall release, copied by `wxgrid export` |
| `configs/` | One config per dataset: sources, codes, thresholds, merge priority, export jobs |
| `tests/` | Unit tests |
| `tools/` | Scripts that measured something, fetched a source, or built a decision table; each finding names the script that produced it |
| `docs/` | This page, [sources.md](sources.md), [station-dataset.md](station-dataset.md), [findings.md](findings.md) and [references.md](references.md) |
