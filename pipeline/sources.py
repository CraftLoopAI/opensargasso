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

# The daily images behind the 7-day composite. The composite keeps each pixel's highest
# value of the week, so the day that value came from tells when that patch was seen.
AFAI_DAILY = {
    "name": "USF AFAI daily fields, served by NOAA AOML",
    "base": "https://cwcgom.aoml.noaa.gov/erddap",
    "dataset": "noaa_aoml_atlantic_oceanwatch_AFAI_1D",
    "variables": ["AFAI"],
    "has_time": True,
    "verified": True,  # 20 October 2026: every 7-day value equals the highest of its seven daily values
}

CURRENTS = {
    "name": "NOAA AOML near real time geostrophic currents",
    "base": "https://cwcgom.aoml.noaa.gov/erddap",
    "dataset": "miamicurrents",
    "variables": ["u_current", "v_current"],
    "has_time": True,
    "verified": True,
}

# GFS 10 m wind, tried in the order of WINDS below. NOAA PFEG's ERDDAP datasets are
# copies of the PacIOOS one, so the NOAA copy is a last resort. NOAA's servers refused
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

# Independent of PacIOOS: UCAR decodes GFS itself and serves it as OPeNDAP text (pipeline/opendap.py).
WIND_UCAR = {
    "name": "NOAA NCEP GFS 10 m wind forecast, 0.5 degree, via UCAR Unidata THREDDS",
    "kind": "opendap",
    "dataset": "GFS Global_0p5deg Best",
    "url": "https://thredds.ucar.edu/thredds/dodsC/grib/NCEP/GFS/Global_0p5deg/Best",
    "page": "https://thredds.ucar.edu/thredds/catalog/grib/NCEP/GFS/Global_0p5deg/catalog.html",
    "variables": ["ugrd10m", "vgrd10m"],
    "verified": True,  # 3-hourly to about 16 days ahead; checked 15 October 2026
}

# UCAR first: on 15 October 2026 it answered GitHub's runners every time, while PacIOOS
# timed out on two of four tries, each costing up to WIND_BUDGET_S. The PacIOOS copy last.
WINDS = [WIND_UCAR, WIND, WIND_MIRROR]

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
