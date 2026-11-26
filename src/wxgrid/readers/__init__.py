"""Reader registry. A reader takes one `sources:` entry of the config plus the domain
bbox and returns (stations, series, obs) DataFrames with the columns in `schema`.

To support a new data source, add a module with a `read(src, bbox)` function and
register it here. Nothing downstream needs to change.
"""

from . import agro_collection, agro_grid, bmkg_xlsx, ghcnd_dly, jatim_grid, knmi_sheets, long_csv, long_table_xls, post_forms, pu_sihka, sacad_zip, station_month_grid

READERS = {
    "agro_collection": agro_collection.read,
    "bmkg_xlsx": bmkg_xlsx.read,
    "sacad_zip": sacad_zip.read,
    "ghcnd_dly": ghcnd_dly.read,
    "long_csv": long_csv.read,
    "station_month_grid": station_month_grid.read,
    "jatim_grid": jatim_grid.read,
    "knmi_sheets": knmi_sheets.read,
    "agro_grid": agro_grid.read,
    "long_table_xls": long_table_xls.read,
    "post_forms": post_forms.read,
    "pu_sihka": pu_sihka.read,
}
