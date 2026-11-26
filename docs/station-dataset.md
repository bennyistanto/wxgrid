# Compiled station dataset

Built by `python -m wxgrid consolidate <config>` (run from `src/`). The config names every
source, its reader, units, missing codes and day convention; nothing dataset-specific is
in the code. Current config: `configs/idn_bmkg_sacad.yaml`, output `F:/temp/station/compiled/`.

## Files

| File | One row per | Key columns |
|---|---|---|
| `stations.csv.gz` | source station | `station_key` (`<source>:<id>`), name, lat, lon, elev_m, country, wmo_id, `site_id` |
| `series.csv.gz` | source series (station x variable x source) | `series_id`, station_key, source, variable, units, day_convention, n_values, n_missing_code, n_unparsed, first, last |
| `observations_<VAR>.csv.gz` | value | series_id, date (corrected), value (standard units), flag, date_raw, label |
| `daylabel_segments.csv` | series period with one day offset | series_id, start, end, offset (days added to date_raw), status, method |
| `crosswalk_stations.csv` | candidate station pair (within `max_km`) | dist_km, name_sim, relation, evidence, needs_review, review_reason, best series-pair stats |
| `crosswalk_series.csv` | series pair of a candidate station pair | n_overlap, r at lags -1/0/+1, best_lag, equal_frac_best, ratio_best |
| `sites.csv` | site (stations joined by the crosswalk) | site_id, representative station, members, sources |
| `merged_<VAR>.csv.gz` | site x day | value, flag, series_id that supplied it |
| `merged_<VAR>.nc` | site x day, from `merge.netcdf_start` | CF-1.8 timeSeries; `<VAR>`, `<VAR>_flag`, `source_series` index into `series_id` |
| `merge_fillers.csv` | lower-priority series at a site | status pass / fail / untested, with the comparison stats |
| `summary.json`, `config_used.yaml`, `run.log` | run | counts and the exact config used |

## Rules

- **Nothing is deleted.** Missing codes are dropped and counted in `series`; implausible
  values are kept and flagged (`below_min`, `above_max`, `src_suspect`, `calm`).
- **TU and TTU ("Tidak Terukur") are unmeasurable like 8888**: rain below 0.5 mm, observed but not
  a rain day (F62, F63). Read so in `chind` (TU, TTU), `fklim_sumatera` (TTU in Rainfall), the
  agro readers and `bmg_posts`. In CH_IND "-" is no data.
- **BMKG codes follow the workbook legend.** 9999 ("Tidak Ada Data") is missing; 8888
  ("data tidak terukur", not measurable) is kept as an observed day with no value and flag
  `unmeasurable` (config `unmeasurable_value` can set a number).
- **Duplicates in a source** (two values for one series and date) are both kept and flagged
  `src_duplicate`; `collision` is reserved for clashes created by a day-label shift.
- **SACA&D SYNOP sources are stations of their own** (`sacad_synop:<SOUID>`) at their own
  coordinates; the crosswalk decides their site. SACA&D 2013 extras keep only sources whose
  coordinates match the station.
- **GHCN series** are split by element, source flag and measurement flag
  (`ghcnd:<id>:<SFLAG><MFLAG>:<VAR>`), e.g. GSOD rain from four 6-h reports (`SD`) vs unknown
  completeness (`S`).
- **QC exclusions** (config `qc.exclusions`, built by `tools/build_qc_exclusions.py` from the
  /qc tables): matching values are flagged `qc_excluded` and left out of merged views, so a
  lower-priority source can fill the day. A row with a `flag` column value other than
  `qc_excluded` adds that flag instead and the value stays in merged views (review flags such as
  `suspect_accumulation` or `day_label_unverified`; gridding decides). Compendium -333 is `unmeasurable` like BMKG 8888;
  compendium 200.0 mm is flagged `code_suspect`.
- **Sources left out of a merged view** per variable: `merge.exclude_sources` (currently GHCN
  and SACA&D SYNOP for RR); their values stay in the observations tables.
- **Merged views keep flagged values** (e.g. `above_max`, `src_suspect`, `code_suspect`,
  `unmeasurable`) except `qc_excluded`, `src_duplicate` and `collision`. Gridding must decide
  which flags to drop.
- **Relations are proposals.** `same_site` comes from distance or name; `duplicate_data`
  from near-identical values. Pairs whose data contradict a merge (best lag not 0, or r at
  lag 0 below `r_min`) get `needs_review` and are not joined.
- **A site never holds two stations of one provider**, so co-located BMKG stations stay
  separate (`colocated_same_source`).
- **PU rain posts never join a BMKG station** (user 2026-11-25): PU owns its network and sites,
  usually at PU field offices, so a PU post and a BMKG station are two gauges however close.
  Config `crosswalk.provider_groups` (`PU: [pu_sihka, jatim]`): a source in a group joins only
  sources of the same group; other pairs get relation `different_provider` and are not reviewed.
  The ASEAN compendium is neutral (`crosswalk.neutral_sources`): it carries both BMKG stations and
  rain posts, so it may join either, but a site never holds a PU post and a BMKG station together.
- **Merged view = priority order, gap filling only.** A filler must pass the overlap test
  against the primary; fillers with too little overlap are used and reported as untested.

- **Rain-post forms (reader `post_forms`; sources `bmg_posts`, `sumbar_daily`, `larantuka`,
  `sumsel_posts`).** These forms code cells differently from the BMKG workbooks, as measured
  in F57 and F59:
  - "-" is a dry day (0.0 mm).
  - 0 is an observed rain day too small to measure: no value, flag `unmeasurable`.
  - X and R mean no data.
  - A month written entirely as "-" keeps 0.0 with flag `dash_month` (`bmg_posts`), or is
    dropped as unreported (`sumsel_posts`, config `codes.dash_month: missing`).
  - The **East Java PU forms (`jatim`) use the opposite convention**: "-" means no data and
    0 means dry. Never share a cell coding between the two families.
  - West Sumatra: 999 is missing, and 888 is treated as `unmeasurable` (no legend) [to verify].
  - Station coordinates come only from `_post_catalogue.csv` (`tools/build_post_catalogue.py`,
    which records the source of every coordinate). Posts without a coordinate are counted and
    skipped.

- **PU SIHKA rain posts (reader `pu_sihka`, source `pu_sihka`; F67, F68).** Raw JSON from the public
  SIHKA service behind pdsda.sda.pu.go.id (`tools/fetch_pu_sihka.py`), read with the rules the user adopted
  on 2026-11-25 (R1-R6), listed per publication or month in `_decisions.csv` (`tools/build_pu_sihka_decisions.py`):
  - A station-year that is zero in all 12 months is dropped (unfilled template, as F64).
  - An all-zero month is dropped as missing when CPC at the post or the median of posts within 25 km had
    >= 100 mm (provisional threshold); other zeros are dry days.
  - Every publication is dated by its catalogue year, except 5 whose own year fits CPC better; 19 copies
    of another publication are skipped. A stray key at Unix 0 is dropped.
  - One position per post, the most common across its publications (the spread is in the series note).
    Where that position is more than 1 km from the same-named post in the PU register (read 2026-11-26),
    the register position is used (169 posts), except one name shared by two different posts and 8 posts
    whose rainfall agrees better with nearby gauges at the original position; those 8 keep it and are
    flagged `coord_approx` (F77).
  - The provider's day flags are kept: "data meragukan" -> `src_suspect`, "data tidak realistis" ->
    `src_unrealistic`.
  - Dates are left as read; most posts match CPC one day earlier than the BMKG convention, which the
    day-label step corrects per series.

- **KNMI Dutch-era daily sheets (reader `knmi_sheets`, source `knmi`; F28, F71, F74).** 14 stations, 1879-1916.
  "-" is a dry day; "n.w." and "Geen waarnemingen ontvangen" are missing. A blank is missing in `CH Jawa.xls`
  (which writes "-" for dry days); in the other three workbooks a blank is a dry day when the station-month has
  any number, and the whole month is missing when it is entirely blank (Jakarta: SACA&D shows 0 mm on 84% of those
  blank days). Positions come from a reviewed name table (`tools/build_knmi_stations.py`), from the Dutch station
  list or the user's Panjang data sheet. KNMI Jakarta is skipped: SACA&D 180 Kemayoran holds the same record at 0.1 mm.
  Before 1979 there is no reference, so every KNMI date is `unverified`.
  Each KNMI gauge is its own site (`crosswalk.isolated_sources: [knmi]`, user 2026-11-26): it never joins a modern
  station, the compendium included, because no KNMI record overlaps a modern one and a Dutch-era town gauge is not
  known to stand where today's station does (F79). Medan II carries `coord_approx` (F78).

## Day labels (rainfall)

Dates of RR values are shifted to the target convention (config `daylabel.target`) per
series and period: `date = date_raw + offset`. `label` says how sure that is:
`verified` (reference evidence), `interpolated` (both neighbouring periods agree),
`uncertain` (reference present but inconclusive; not shifted), `unverified` (no reference;
not shifted), `collision` (two values on one date after shifting; excluded from merged
views). Other variables keep `date = date_raw` and an empty label. The merged NetCDF
carries `RR_label` with the same codes.

## Variables

ECA&D-style codes (`src/wxgrid/schema.py`): RR precipitation (mm), TN/TX/TG temperature
(degC), HU relative humidity (%), SS sunshine (h), FX/FG wind speed max/mean (m s-1),
DX/DD wind direction at max / prevailing (degree; BMKG compass text converted).

Also carried where a source records them: EV evaporation (mm), RA global radiation
(cal cm-2, source units), PP station pressure (hPa), HU07/HU13/HU18 humidity at 07/13/18
local. Bounds per element in `schema.VALUE_BOUNDS`.

## Adding a source

Write `src/wxgrid/readers/<name>.py` with `read(src, bbox) -> (stations, series, obs)`,
register it in `readers/__init__.py`, add a `sources:` entry to a config. Use the source's
own missing codes, scale, and day convention in the config.
