"""Standard variables and table layouts shared by every reader.

Variable codes follow the ECA&D / SACA&D element style (RR, TN, TX, TG, ...), so
other sources map onto them through the per-source `variables` table in the config.
"""

VARIABLES = {
    "RR": dict(long_name="daily precipitation amount", units="mm",
               standard_name="lwe_thickness_of_precipitation_amount", cell_methods="time: sum"),
    "TN": dict(long_name="daily minimum air temperature", units="degC", standard_name="air_temperature"),
    "TX": dict(long_name="daily maximum air temperature", units="degC", standard_name="air_temperature"),
    "TG": dict(long_name="daily mean air temperature", units="degC", standard_name="air_temperature"),
    "HU": dict(long_name="daily mean relative humidity", units="%", standard_name="relative_humidity"),
    "SS": dict(long_name="daily sunshine duration", units="h", standard_name="duration_of_sunshine"),
    "FX": dict(long_name="daily maximum wind speed", units="m s-1", standard_name="wind_speed_of_gust"),
    "DX": dict(long_name="wind direction at maximum wind speed", units="degree", standard_name="wind_from_direction"),
    "FG": dict(long_name="daily mean wind speed", units="m s-1", standard_name="wind_speed"),
    "DD": dict(long_name="prevailing wind direction", units="degree", standard_name="wind_from_direction"),
    # Additional elements carried by the agro-climate and F-KLIM sheets. Units are kept as
    # recorded by the source (radiation in cal cm-2, not converted); no CF standard_name is
    # asserted where the daily total does not map cleanly onto one.
    "EV": dict(long_name="daily evaporation", units="mm", standard_name="lwe_thickness_of_water_evaporation_amount"),
    "RA": dict(long_name="daily global solar radiation", units="cal cm-2", standard_name=None),
    "PP": dict(long_name="daily mean station air pressure", units="hPa", standard_name="surface_air_pressure"),
    "HU07": dict(long_name="relative humidity at 07:00 local", units="%", standard_name="relative_humidity"),
    "HU13": dict(long_name="relative humidity at 13:00 local", units="%", standard_name="relative_humidity"),
    "HU18": dict(long_name="relative humidity at 18:00 local", units="%", standard_name="relative_humidity"),
    "HUX": dict(long_name="daily maximum relative humidity", units="%", standard_name="relative_humidity"),
    "HUN": dict(long_name="daily minimum relative humidity", units="%", standard_name="relative_humidity"),
    # Sunshine recorded as a percentage of possible sunshine (agro sheets where values exceed
    # 24): kept as recorded, not converted to hours (the reference duration is not stated).
    "SSP": dict(long_name="daily sunshine, percent of possible", units="%", standard_name=None),
}

# Provisional plausibility bounds per element, used by the readers that filter on read.
VALUE_BOUNDS = {
    "RR": (0, 2000), "TN": (-5, 45), "TX": (0, 50), "TG": (-5, 45), "HU": (0, 100),
    "SS": (0, 24), "FX": (0, 80), "FG": (0, 60), "DX": (0, 360), "DD": (0, 360),
    "EV": (0, 50), "RA": (0, 1200), "PP": (700, 1100),
    "HU07": (0, 100), "HU13": (0, 100), "HU18": (0, 100), "HUX": (0, 100), "HUN": (0, 100),
    "SSP": (0, 100),
}

# Every reader returns three DataFrames with these columns.
STATION_COLS = ["station_key", "source", "network", "source_station_id", "name",
                "lat", "lon", "elev_m", "country", "wmo_id"]
SERIES_COLS = ["series_id", "station_key", "source", "variable", "units", "day_convention",
               "n_values", "n_missing_code", "n_unparsed", "first", "last", "note"]
OBS_COLS = ["series_id", "date", "value", "flag"]

# 16-point compass to degrees, for sources that report direction as text.
COMPASS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
    "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}
