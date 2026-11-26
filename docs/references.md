# Reference registry

Every method choice, dataset property, or published result used in this project must
trace to a row here. Rows are added with `/add-ref` and re-checked with `/verify-refs`.

**Status codes**

- `VERIFIED` - DOI resolves on Crossref; author, year, and journal match.
- `CONTENT` - the "Supports" column was checked against the abstract (OpenAlex) or the
  full text. Without this flag, only the paper's existence is confirmed, not the claim.
- `WEB` - a dataset or agency web page, with access date. Re-check before publishing,
  since pages change.
- `UNVERIFIED` - not yet resolved. Do not cite in a deliverable.

Checked with `tools/refcheck.py` on 2026-10-05.

## Interpolation of daily station rainfall

| Key | DOI | Status | Supports (what the source actually says) |
|---|---|---|---|
| Hofstra 2008 | 10.1029/2008JD010100 | VERIFIED, CONTENT | Compared six methods for daily European data. Differences between methods are smaller than the range in skill of one method across the domain or seasons. **Station density is the main control on skill**, topographic complexity compounds it. **Relative skill of methods stays roughly constant through time despite a varying station network**, and for extremes. Global kriging selected. |
| Haylock 2008 | 10.1029/2008JD010201 | VERIFIED, CONTENT | E-OBS: three steps. Monthly totals by 3D thin-plate splines, daily anomalies by indicator + universal kriging, then combined. Daily standard errors provided. |
| Cornes 2018 | 10.1029/2017JD028200 | VERIFIED, CONTENT | E-OBS ensemble: 100 realisations per day at 0.25 deg. Uncertainty still underestimated in data-sparse regions. |
| Chen 2008 | 10.1029/2007JD009132 | VERIFIED, CONTENT | CPC global daily: Cressman, Shepard, and optimal interpolation (OI) compared. OI best in almost all regions, seasons, densities. Quality degrades as network gets sparser. |
| Xie 2007 | 10.1175/JHM583.1 | VERIFIED, CONTENT | CPC East Asia daily: daily climatology (6 harmonics) adjusted by PRISM, then ratio of daily to climatology interpolated by OI, then multiplied back. Quality increases with gauge density. Domain 5-60N, so mostly excludes Indonesia. |
| Ly 2011 | 10.5194/hess-15-2259-2011 | VERIFIED, CONTENT | Daily rainfall, 70 gauges, Belgium. Seven variogram models fitted per day; Gaussian most often best. **Elevation in KED and cokriging did not improve daily accuracy.** OK and IDW best. Negative kriging estimates more frequent for convective rain. |
| Verworn 2011 | 10.5194/hess-15-569-2011 | VERIFIED, CONTENT | Hourly rainfall by KED with topography, daily gauges, radar. Variogram type had low impact; an averaged variogram was sufficient. Radar was the most valuable drift for convective events. |
| Barancourt 1992 | 10.1029/91WR02896 | VERIFIED, CONTENT | Intermittent rainfall: separate kriging of a binary occurrence field and the amount inside rainy areas outperforms global kriging. |
| Newman 2015 | 10.1175/JHM-D-15-0026.1 | VERIFIED, CONTENT | Daily observation-based ensemble for CONUS. Ensemble gives more realistic wet-day fraction than deterministic products. |
| Frei 2019 | 10.1029/2018JD030004 | VERIFIED, CONTENT | Ensemble daily analysis by trans-Gaussian conditional simulation. Even in the dense Alpine network, ensemble spread for 500 km2 means is typically a factor 2-4 for intense convective events. |
| Haberlandt 2007 | 10.1016/j.jhydrol.2006.06.028 | VERIFIED | Geostatistical interpolation of hourly rainfall from gauges and radar. Abstract not retrievable; content not checked. |
| Goovaerts 2000 | 10.1016/S0022-1694(00)00144-X | VERIFIED | Geostatistical approaches for incorporating elevation into rainfall interpolation. Abstract elided by publisher; content not checked. |
| Hengl 2007 | 10.1016/j.cageo.2007.05.001 | VERIFIED | Regression-kriging theory and case studies. Content not checked. |
| Pebesma 2004 | 10.1016/j.cageo.2004.03.012 | VERIFIED | gstat package. Software reference. |

## Climatology-aided and terrain-aware gridding

| Key | DOI | Status | Supports |
|---|---|---|---|
| Willmott 1995 | 10.1002/joc.3370150207 | VERIFIED, CONTENT | Climatologically aided interpolation (CAI): interpolate deviations from a high-resolution climatology. Most of the accuracy came from the climatology. (Tested on temperature, not rainfall.) |
| Daly 1994 | 10.1175/1520-0450(1994)033<0140:ASTMFM>2.0.CO;2 | VERIFIED | PRISM original paper, climatological precipitation in mountains. Content not checked. |
| Daly 2008 | 10.1002/joc.1688 | VERIFIED, CONTENT | PRISM: climate-elevation regression per DEM cell; stations weighted by physiographic similarity (elevation, coastal proximity, facet, etc.). Monthly **climatology**, ~13,000 precipitation stations. |
| Hutchinson 1995 | 10.1080/02693799508902045 | VERIFIED | Thin-plate smoothing splines for mean rainfall (ANUSPLIN basis). Content not checked. |
| Hijmans 2005 | 10.1002/joc.1276 | VERIFIED | WorldClim 1. Content not checked. |
| Fick 2017 | 10.1002/joc.5086 | VERIFIED | WorldClim 2. Content not checked. |
| Karger 2017 | 10.1038/sdata.2017.122 | VERIFIED | CHELSA. Content not checked. |

## Satellite merging and machine learning

| Key | DOI | Status | Supports |
|---|---|---|---|
| Baez-Villanueva 2020 | 10.1016/j.rse.2019.111606 | VERIFIED, CONTENT | RF-MEP over Chile: random forest merging gauges, CHIRPS/PERSIANN/ERA-Interim, and topography. Outperformed its inputs and MSWEP; worked with 10% of gauges for training. |
| Hengl 2018 | 10.7717/peerj.5518 | VERIFIED, CONTENT | RFsp: random forest with buffer distances as covariates. As accurate as kriging variants in 5-fold CV; no stationarity assumption. |
| Beck 2019 | 10.1175/BAMS-D-17-0138.1 | VERIFIED | MSWEP V2. Content not checked. |
| Dinku 2018a | 10.1080/17565529.2017.1405784 | VERIFIED, CONTENT | ENACTS: NMHS-owned gridded historical datasets combining station data with other sources; 10 African countries. Template for an NMHS product. |
| Dinku 2018b | 10.1002/qj.3244 | VERIFIED | CHIRPS validation over eastern Africa. Content not checked. |

## Validation and uncertainty

| Key | DOI | Status | Supports |
|---|---|---|---|
| Roberts 2017 | 10.1111/ecog.02881 | VERIFIED, CONTENT | Random CV underestimates error for spatially structured data; block CV addresses it, but blocking can force extrapolation and overestimate interpolation error. |
| Meyer 2021 | 10.1111/2041-210X.13650 | VERIFIED, CONTENT | Area of applicability (AOA): CV error holds inside it, not outside. Dissimilarity index in predictor space. |
| Durre 2010 | 10.1175/2010JAMC2375.1 | VERIFIED, CONTENT | GHCN-Daily QA: 19 ordered tests (duplicates, climatological outliers, internal/temporal/spatial consistency); 0.24% flagged; 1-2% false positives. |
| Kidd 2017 | 10.1175/BAMS-D-14-00283.1 | VERIFIED, CONTENT | Gauge coverage is tiny; autocorrelation distances of precipitation vary greatly with regime and integration period. |

## Regional datasets and Indonesian rainfall regimes

| Key | DOI / URL | Status | Supports |
|---|---|---|---|
| Funk 2015 | 10.1038/sdata.2015.66 | VERIFIED, CONTENT | CHIRPS v2: 0.05 deg climatology with satellite information, CCD-based estimates 1981-present, blended with stations. |
| CHIRPS v3 page | https://www.chc.ucsb.edu/data/chirps3 | WEB 2026-10-05 | v3: 60N-60S, 1981 to near-present, 0.05 deg, **over land**. Fundamentally pentad and monthly; daily is derived by disaggregation ('rnl' via ERA5, 'sat' via IMERG Late V07). Daily date is a label, not a uniform observation window. |
| Abatzoglou 2018 | 10.1038/sdata.2017.191 | VERIFIED, CONTENT | TerraClimate: 1/24 deg monthly, terrestrial; CAI combining WorldClim normals with coarser time-varying data. Paper period 1958-2015. |
| TerraClimate page | https://www.climatologylab.org/terraclimate.html | WEB 2026-10-05 | Site now states **1950-present** (v1.1). |
| Becker 2013 | 10.5194/essd-5-71-2013 | VERIFIED, CONTENT | GPCC monthly products, >85,000 stations, 1901-present. |
| Yatagai 2012 | 10.1175/BAMS-D-11-00122.1 | VERIFIED, CONTENT | APHRODITE daily gauge-only for Asia, 5,000-12,000 stations, 0.5 and 0.25 deg. |
| Aldrian 2003 | 10.1002/joc.950 | VERIFIED, CONTENT | Three rainfall regions in Indonesia by double correlation (vs EOF/rotated EOF): A south (S Sumatra to Timor, S Kalimantan, Sulawesi, part of Papua), B northwest, C Maluku and N Sulawesi. ENSO strongest in C, suppressed in B. |
| Hamada 2002 | 10.2151/jmsj.80.285 | VERIFIED | Rainy season variation over Indonesia and ENSO. Abstract not retrieved; content not checked. |
| BMKG Data Online FAQ | https://dataonline.bmkg.go.id/faq | WEB 2026-10-06 | RR is "curah hujan sehari yang diamati pada jam 07.00 WS" (daily rainfall observed at 07:00 local time). The Data Iklim menu offers only **monthly** data, max 2 stations per request, last 2 years only, quota 24 months then a 30-day wait. The limit follows **Peraturan BMKG No. 4 Tahun 2022** on data access policy (access limited to the last two years). Other data via PTSP (https://ptsp.bmkg.go.id/). |
| van den Besselaar 2015 | 10.1175/BAMS-D-13-00249.1 | VERIFIED, CONTENT | ICA&D concept (incl. SACA&D for Southeast Asia): NMHSs share quality-controlled daily station data plus derived indices via a web system. Required acknowledgement for SACA&D data use. |
| SACA&D daily data page | https://sacad.bmkg.go.id/ID/dailydata/index.php | WEB 2026-10-06 | Daily station series for SE Asia, part free for non-commercial research. Blended series fill gaps from nearby stations and are updated with SYNOP; non-blended series are also offered. Page states daily data "updated until Dec 31, 2025"; SA-OBS grid until 2014. **Measured (findings F7):** the downloadable RR zips were created 10-12-2022 and Indonesian data end 2008 (non-blended) and 2020-03-30 (blended). RR unit 0.1 mm; Q_RR 0 valid, 1 suspect, 9 missing. |
| SACA&D RR source list | https://sacad.bmkg.go.id/ID/download/SACA_blend_source_rr.txt | WEB 2026-10-06 | File header: created 10-12-2022, missing value -9999, free use with acknowledgement of van den Besselaar 2015. Source IDs starting 9 are SYNOP, 1 are participant data. |
| Menne 2012 | 10.1175/JTECH-D-11-00103.1 | VERIFIED, CONTENT | GHCN-Daily: >80,000 stations in 180 countries, 20+ source components, routine QA, **not homogenized**, regularly reconstructed with version numbers. |
| GHCN-Daily readme | https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt | WEB 2026-10-06 | .dly format; PRCP/TMAX/TMIN in tenths. Source flag `S` = Global Summary of the Day, "derived from hourly synoptic reports exchanged on the GTS", may "differ significantly from 'true' daily data, particularly for precipitation"; `2` = its successor (SSOD v2); `I` = international collection; `G` = official GCOS or other government-supplied. Version used: 3.35-upd-2026100418. |
| GSOD readme | https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt | WEB 2026-10-06 | GSOD is derived from synoptic/hourly observations (DATSAV3/ISD), needs >= 4 observations per day. PRCP "will usually not end with the midnight observation". PRCP_ATTRIBUTES: A/B/C/D = 1/2/3/4 six-hour reports summed, E/F = 1/2 twelve-hour reports, G = one 24-hour report, H = reported 0 but precipitation seen hourly (incomplete), I = no precipitation data reported. Only D, F, G describe a complete day. |
| CPC Global Unified (PSL) | https://www.psl.noaa.gov/data/gridded/data.cpc.globalprecip.html | WEB 2026-10-06 | File attributes of the user's copies: "CPC GLOBAL PRCP V1.0", created 9/2016 by NOAA/ESRL PSD, 0.5 deg, `precip` in mm, `cell_methods: time: sum`. Methods: Chen 2008, Xie 2007 rows above. Day closing time not taken from documentation; its lag relative to BMKG measured instead (findings F38). |
| BMKG workbook legend | rows "Keterangan" at the bottom of every `F:/temp/station/bmkg_xlsx/*.xlsx` | FILE 2026-10-07 | "8888: data tidak terukur" (not measurable); "9999: Tidak Ada Data (tidak dilakukan pengukuran)" (no data, no measurement taken); variable units (RR mm, Tn/Tx/Tavg degC, RH %, ss jam, ff m/s, ddd degrees). |
| Teleti 2026 | 10.5194/egusphere-2026-3459 | VERIFIED, CONTENT (PDF read: Table 1 p. 9, Sect. A1.8 p. 31) | SEA-HISTIN, inventory of historical weather observations for Southeast Asia (EGUsphere preprint, discussion started 24 July 2026, CC BY 4.0). A1.8: the ASEAN Compendium of Climate Statistics, coordinated by the ASEAN Secretariat, data contributed mainly by national statistical offices and NMHSs; the 1976 edition holds **monthly and annual** statistics (rainfall, temperature, humidity, dew point, sunshine, cloudiness, pressure, winds) for **more than 900 stations in Indonesia, Malaysia, Philippines, Singapore and Thailand, 1951-1975**, stations with under 20 years. Table 1: "Climate summaries and Compendium", ASEAN Meteorological Service, personal collection Rory Walsh, 1951-1975, status Imaged (not transcribed). |
| Ward 1963 | 10.1080/01621459.1963.10500845 | VERIFIED (foundational) | Ward's hierarchical clustering. |

## Project-internal measurements

| Key | Source | Supports |
|---|---|---|
| HBC day-label | `../hybrid-bias-correction/paper/NUMBERS.md` (rows R4, R5, R10) | BMKG daily totals are a local day ending at the morning observation. Daily r vs IMERG-L: 0.20 at native UTC date, 0.57 after a h = -23 date-label shift. Measured in that repo, not yet re-measured here. |

## Rejected during checking

| Candidate | Reason |
|---|---|
| 10.1175/2009JHM1144.1 | Resolves to an unrelated paper (Mascaro 2010, QPF errors). |
| 10.1029/2009WR008524 | 404 on Crossref. |
| 10.1007/s00382-017-3830-5 | 404 on Crossref (intended: Supari et al., ENSO and Indonesian rainfall). Find the correct DOI before citing. |
| 10.1016/S0022-1694(99)00134-1 | Resolves to an unrelated paper (Martin-Vide 1999, Mediterranean runoff). |
