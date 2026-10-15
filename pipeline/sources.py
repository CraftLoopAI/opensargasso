"""Open data sources. See docs/DATA_SOURCES.md for status and licenses.

`verified` records whether the dataset ID and variable names were checked
against the live server when this file was written (October 2026).
"""

AFAI = {
    "name": "USF AFAI 7-day cumulative fields, served by NOAA AOML",
    "base": "https://cwcgom.aoml.noaa.gov/erddap",
    "dataset": "noaa_aoml_atlantic_oceanwatch_AFAI_7D",
    "variables": ["AFAI"],
    "has_time": True,
    "verified": True,
}

CURRENTS = {
    "name": "NOAA AOML near real time geostrophic currents",
    "base": "https://cwcgom.aoml.noaa.gov/erddap",
    "dataset": "miamicurrents",
    "variables": ["u_current", "v_current"],
    "has_time": True,
    "verified": True,
}

# GFS 10 m wind. NOAA PFEG's ERDDAP datasets are copies of the PacIOOS one, so
# PacIOOS comes first and the NOAA copy is a last resort. NOAA's servers refused
# GitHub's runners (HTTP 403, timeouts) in October 2026 while answering elsewhere.
WIND = {
    "name": "NOAA NCEP GFS 10 m wind forecast, 0.5 degree, via PacIOOS (University of Hawaii)",
    "base": "https://pae-paha.pacioos.hawaii.edu/erddap",
    "dataset": "ncep_global_lon180",
    "variables": ["ugrd10m", "vgrd10m"],
    "has_time": True,
    "lat_descending": True,
    "verified": True,  # 3-hourly analyses, then the newest forecast about 7.5 days ahead; checked 14 October 2026
}

WIND_MIRROR = {
    "name": "NOAA NCEP GFS 10 m wind forecast, 0.5 degree, via NOAA PFEG (copy of PacIOOS)",
    "base": "https://upwell.pfeg.noaa.gov/erddap",
    "dataset": "ncep_global_lon180",
    "variables": ["ugrd10m", "vgrd10m"],
    "has_time": True,
    "lat_descending": True,
    "verified": True,
}

WINDS = [WIND, WIND_MIRROR]  # tried in order

SIR = {
    "name": "NOAA AOML Sargassum Inundation Risk (SIR v1.5), with USF",
    "page": "https://cwcgom.aoml.noaa.gov/SIR/",
    "kmz": "https://cwcgom.aoml.noaa.gov/SIR/KMZ/sargassum_risk_{date}.kmz",
    "verified": True,  # daily, one to two days behind; levels 0 low, 1 warning, 2 medium, 3 high
}

COAST = {
    "name": "OpenStreetMap coastline, 0.002 degree grid",
    "url": "https://www.openstreetmap.org/copyright",
    "overpass": "https://overpass-api.de/api/interpreter",
    "verified": True,
}

# Fallback for regions without a stored coastline mask.
LAND = {
    "name": "ETOPO1 global relief (land where altitude >= 0)",
    "base": "https://coastwatch.pfeg.noaa.gov/erddap",
    "dataset": "etopo180",
    "variables": ["altitude"],
    "has_time": False,
    "verified": True,
}
