# Sources

Every archive the compiled dataset reads, as configured in
[configs/idn_bmkg_sacad.yaml](../configs/idn_bmkg_sacad.yaml). Where a value comes from more than one
archive, the merge priority in that config decides which one is used.

| Source | Reader | Archive |
|---|---|---|
| `bmkg_xlsx` | `bmkg_xlsx` | BMKG station workbooks, downloaded from [BMKG Data Online](https://dataonline.bmkg.go.id/) |
| `chind` | `station_month_grid` | BMKG national daily rain sheets (CH_IND) |
| `fklim_sumatera` | `long_table_xls` | BMKG F-KLIM Sumatera, daily, several elements |
| `agro` | `agro_collection` | BMKG agro-climate stations |
| `bmg_posts` | `post_forms` | BMKG rain posts, regional office forms |
| `sacad_nonblend`, `sacad_blend_synop`, `sacad2013_extra` | `sacad_zip` | SACA&D, Southeast Asian Climate Assessment and Dataset |
| `ghcnd` | `ghcnd_dly` | GHCN-Daily (NOAA NCEI) |
| `asean_comp` | `long_csv` | ASEAN Compendium of Climate Statistics, daily Indonesia database |
| `knmi` | `knmi_sheets` | Dutch-era daily rainfall sheets, 1879-1916 |
| `jatim` | `jatim_grid` | Dinas PU East Java rain posts |
| `pu_sihka` | `pu_sihka` | Ministry of Public Works (Ditjen SDA) rain posts, SIHKA, from the [water resources data portal](https://pdsda.sda.pu.go.id/) |
| `sumbar_daily` | `post_forms` | West Sumatra rain posts |
| `sumsel_posts` | `post_forms` | South Sumatra district rain posts |
| `larantuka` | `post_forms` | NTT climate station |

Raw and compiled data live outside the repository (paths in the config). Only the draft rainfall release
is copied in, to `data/`. Each source keeps its own terms of use, and they apply to that copy too. The terms of several
sources are still being checked and are marked `[to verify]` in the config.
