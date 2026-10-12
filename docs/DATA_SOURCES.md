# Data sources

Checked in October 2026. "Verified" means the dataset ID and variable names were confirmed against the server. The first live run, on 12 October 2026, downloaded all three.

| Input | Dataset | Server | Grid | Verified |
|---|---|---|---|---|
| Sargassum index | `noaa_aoml_atlantic_oceanwatch_AFAI_7D`, variable `AFAI` (1-day and 3-day versions end in `_1D`, `_3D`) | https://cwcgom.aoml.noaa.gov/erddap | 0.015 degrees, 0 to 38 N, 98 to 38 W, from June 2016 | Yes |
| Surface currents | `miamicurrents`, variables `u_current`, `v_current` (m/s) | https://cwcgom.aoml.noaa.gov/erddap | 0.2 degrees, daily, longitude -180 to 180 | Yes |
| Land mask | `etopo180`, variable `altitude` | https://coastwatch.pfeg.noaa.gov/erddap | 1 arc-minute | Yes |
| Wind | none yet; a constant vector in the region file | | | Placeholder |
| Basemap | OpenStreetMap tiles | https://tile.openstreetmap.org | | Standard |

## Things to know

- **Data lag.** Earlier on 12 October 2026 the dataset pages reported AFAI through 29 September and currents through 21 August. The first live run the same day received AFAI for 11 October and currents for 10 October, so the pages were stale or the lag was temporary. Watch `sources.*.age_days` in `latest.json`. The site shows the age of each input and warns when the satellite composite is more than 10 days old. If currents stay that far behind, switch to another source (see the roadmap).
- **Download size.** For the `sxm` box, AFAI at stride 2 is 2.8 MB (about 2 seconds), currents 50 KB (1 second), and the `etopo180` land mask 6 MB (about 80 seconds). Both servers accept latitude in either order.
- **Licenses.** Both NOAA AOML datasets state that the data "may be used and redistributed for free" and carry a no-warranty disclaimer. The AFAI fields are produced by the University of South Florida Optical Oceanography Lab; credit USF and NOAA AOML. OpenStreetMap data is ODbL and needs the attribution shown on the map. The public tile server is fine for light use; a busy site should use its own tile provider.
- **Method references.** AFAI: Wang and Hu (2016), Remote Sensing of Environment. Coastal risk from nearby detections: Trinanes et al. (2023), Journal of Operational Oceanography, the method behind NOAA's Sargassum Inundation Risk product at https://cwcgom.aoml.noaa.gov/SIR/.

## Candidates not yet wired in

| Need | Candidate | Note |
|---|---|---|
| Forecast winds | NOAA GFS 10 m wind | Needs an ERDDAP or similar CSV endpoint to be confirmed |
| Forecast currents | HYCOM global surface currents | Includes wind-driven flow that geostrophic currents miss |
| Nearshore detail | Sentinel-2 MSI, Sentinel-3 OLCI via Copernicus Data Space | Free account needed; `detect.afai_from_bands` is ready for it |
| More sightings | NOAA and Epicollect5 citizen science sargassum reports | Check terms before importing |
