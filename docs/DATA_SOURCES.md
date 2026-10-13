# Data sources

Checked in October 2026. "Verified" means the dataset ID and variable names were confirmed against the server. The first live run, on 12 October 2026, downloaded all three.

| Input | Dataset | Server | Grid | Verified |
|---|---|---|---|---|
| Sargassum index | `noaa_aoml_atlantic_oceanwatch_AFAI_7D`, variable `AFAI` (1-day and 3-day versions end in `_1D`, `_3D`) | https://cwcgom.aoml.noaa.gov/erddap | 0.015 degrees, 0 to 38 N, 98 to 38 W, from June 2016 | Yes |
| Surface currents | `miamicurrents`, variables `u_current`, `v_current` (m/s) | https://cwcgom.aoml.noaa.gov/erddap | 0.2 degrees, daily, longitude -180 to 180 | Yes |
| Land mask | OpenStreetMap `natural=coastline`, filled into a grid and stored in `regions/land/` | https://overpass-api.de (only when rebuilt) | 0.002 degrees, about 220 m | Yes |
| Land mask fallback | `etopo180`, variable `altitude`, for regions without a stored mask | https://coastwatch.pfeg.noaa.gov/erddap | 1 arc-minute | Yes |
| Wind | `ncep_global_lon180` (NCEP GFS), variables `ugrd10m`, `vgrd10m` (m/s); the region's constant trade wind is the fallback | https://upwell.pfeg.noaa.gov/erddap | 0.5 degrees, every 3 hours: analyses, then the newest forecast about 7.5 days ahead | Yes |
| Beach levels | NOAA AOML Sargassum Inundation Risk (SIR v1.5), with USF; KMZ of coastal segments graded low, warning, medium, high | https://cwcgom.aoml.noaa.gov/SIR/ | daily, one to two days behind, from a 50 to 100 km AFAI neighborhood | Yes |
| Basemap | OpenStreetMap tiles | https://tile.openstreetmap.org | | Standard |

## Things to know

- **Data lag.** Earlier on 12 October 2026 the dataset pages reported AFAI through 29 September and currents through 21 August. The first live run the same day received AFAI for 11 October and currents for 10 October, so the pages were stale or the lag was temporary. Watch `sources.*.age_days` in `latest.json`. The site shows the age of each input and warns when the satellite composite is more than 10 days old. In live runs on 12 and 13 October the currents were 1 to 2 days old, so the lag that worried us was not real. If currents fall weeks behind, revisit the decision below.
- **Download size.** For the `sxm` box, AFAI at stride 2 is 2.8 MB (about 2 seconds), currents 50 KB (1 second), and the `etopo180` fallback land mask 6 MB (about 80 seconds). The stored coastline mask needs no download. The GFS wind for the drift window is about 0.8 MB (about 7 seconds). All servers accept latitude in either order.
- **Licenses.** Both NOAA AOML datasets and the GFS dataset on NOAA CoastWatch state that the data "may be used and redistributed for free" and carry a no-warranty disclaimer. The AFAI fields are produced by the University of South Florida Optical Oceanography Lab; credit USF and NOAA AOML. OpenStreetMap data is ODbL and needs the attribution shown on the map; the stored land masks are derived from it and are ODbL too (see `regions/land/README.md`). The public tile server is fine for light use; a busy site should use its own tile provider.
- **Method references.** AFAI: Wang and Hu (2016), Remote Sensing of Environment. Coastal risk from nearby detections: Trinanes et al. (2023), Journal of Operational Oceanography, the method behind NOAA's Sargassum Inundation Risk product at https://cwcgom.aoml.noaa.gov/SIR/.

## Currents decision (13 October 2026)

Kept `miamicurrents`: it is 1 to 2 days old, observation-based (satellite altimetry) and needs no new service. Two alternatives were checked:

- **HYCOM and NOAA RTOFS** are only published as GRIB2 or netCDF files now (the NOMADS OPeNDAP text service is retired, and the ERDDAP HYCOM sets end in 2018), so they would need a parsing dependency.
- **MeteoFrance SMOC total surface currents (with tides) through the Open-Meteo Marine API** work as free JSON without a key: 0.08 degrees (about 8 km), hourly, 10 days ahead, updated daily. Open-Meteo notes that accuracy near coasts is limited. The terms are non-commercial use under 10,000 calls a day and CC BY 4.0 attribution, plus the data providers' terms listed on Open-Meteo's licence page.

Measured on 13 October on a 0.5 degree lattice over the `sxm` box, with identical inputs otherwise:

| | `miamicurrents` (geostrophic) | SMOC via Open-Meteo |
|---|---|---|
| Mean speed | 0.14 m/s | 0.22 m/s |
| Mean flow (u, v) | -0.03, -0.01 m/s | -0.11, +0.11 m/s (west-northwest) |
| Direction difference | median 47 degrees; 52 of 189 points more than 90 degrees apart | |
| Beaches peaking High, Moderate, Low, Clear | 0, 17, 0, 0 | 4, 9, 3, 1 (2 % windage); 4, 9, 4, 0 (1 %) |

Which matches real landings is a calibration question: compare both against sightings and NOAA's Sargassum Inundation Risk in the calibration task. SMOC is a model total current that already responds to the wind, so the windage would likely have to be lowered (1 % was tested) to avoid counting the wind twice.

## Candidates not yet wired in

| Need | Candidate | Note |
|---|---|---|
| Forecast currents | MeteoFrance SMOC total surface currents via Open-Meteo Marine | Works without a key; to be tested during calibration (see the currents decision) |
| Forecast currents | HYCOM, NOAA RTOFS | Only as GRIB2 or netCDF files, so a parsing dependency would be needed |
| Nearshore detail | Sentinel-2 MSI, Sentinel-3 OLCI via Copernicus Data Space | Free account needed; `detect.afai_from_bands` is ready for it |
| More sightings | NOAA and Epicollect5 citizen science sargassum reports | Check terms before importing |
