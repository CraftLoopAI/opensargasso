# OpenSargasso

Free, open sargassum monitoring for the Caribbean, starting with **Saint-Martin / Sint Maarten**.

It reads open satellite data once a day, flags floating sargassum, forecasts where it drifts over the next 7 days, and grades each beach as Clear, Low, Moderate or High. The result is a static website in English, French and Dutch. There is no server and no paid service.

> **Status: experimental.** The pipeline runs end to end on live NOAA data (first run 12 October 2026) and on synthetic sample data, and has unit tests. The risk levels are not calibrated. See [Status](#status).

## Quick start

The pipeline needs only Python 3.11+. The tests need pytest (`pip install pytest`).

```bash
python -m pytest                               # run the tests
python -m pipeline.run --region sxm --sample   # build the site data from sample inputs
python -m http.server 8000 --directory site    # open http://localhost:8000
python -m pipeline.run --region sxm            # live data (needs internet)
```

On macOS with Python from python.org, run `Install Certificates.command` in the Python folder under Applications once. Otherwise live downloads fail with `CERTIFICATE_VERIFY_FAILED`.

## Put it online (GitHub Pages)

1. Push this folder to a GitHub repository.
2. In **Settings > Pages**, set **Source** to **GitHub Actions**.
3. In `site/config.js`, set `repo` to your `owner/repo`.
4. In **Actions**, run **Daily update** once by hand. After that it runs every day at 11:23 UTC.
5. Create two issue labels: `sargassum-report` and `report-approved`.

## How it works

```
NOAA / USF open data ──> pipeline (Python) ──> site/data/*.json ──> static site (Leaflet)
                              ^
        approved GitHub issue ┘  (citizen sightings)
```

| Step | Module | What it does |
|---|---|---|
| Fetch | `pipeline/erddap.py`, `sources.py`, `landmask.py` | Downloads the AFAI satellite index, surface currents and the GFS wind forecast as CSV, and reads the stored coastline land mask |
| Detect | `pipeline/detect.py` | Flags pixels whose AFAI stands out above the local background |
| Drift | `pipeline/drift.py` | Moves particles with currents and wind for 7 days; they stop at land |
| Risk | `pipeline/risk.py` | Counts particles within 10 km of each beach, per day |
| Publish | `pipeline/run.py` | Writes `latest.json` and a small daily history file |
| Sightings | `pipeline/reports.py` | Turns an approved issue into a point in `reports.geojson` |

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), [docs/ROADMAP.md](docs/ROADMAP.md).

## Status

| Part | State |
|---|---|
| Pipeline logic (detect, drift, risk, reports) | Unit tested, runs on sample data |
| Dataset IDs (AFAI, currents, land mask) | Checked against the NOAA servers in October 2026 |
| Live download | Works. First run 12 October 2026: AFAI 1 day old, currents 2 days old. Response formats pinned by `tests/fixtures/` |
| Land mask | OpenStreetMap coastline in 220 m cells, stored in `regions/land/` (13 October 2026). Simpson Bay Lagoon, Oyster Pond and Pinel are resolved, and the daily run needs no land download (3 seconds instead of 80) |
| Detection near land | Pixels that touch land are skipped (Tintamarre was flagged as sargassum), and so are pixels next to land the AFAI product masked, where coastal glare looks like algae. Real mats in that first pixel are missed |
| Wind | NOAA GFS 10 m wind forecast (0.5 degrees, every 3 hours) from the satellite date to the end of the newest forecast, since 13 October 2026. The region's constant trade wind is the fallback |
| Risk thresholds | **Uncalibrated** first guesses |
| Beach coordinates | Checked against OpenStreetMap on 13 October 2026. Each beach records the OSM feature its position comes from (`osm`); Cul-de-Sac, Marigot and Oyster Pond have no mapped beach and use the bay or place |
| Website | Three views (beaches, coastal managers, data and methods), viewed with live tiles in Chromium at desktop and phone width, light and dark, English and French, on 12 October 2026. Not yet checked in Safari, Firefox or on a real phone |
| Translations | French and Dutch text written by the model, not yet reviewed by native speakers |

## Site views

| View | For | What it shows |
|---|---|---|
| Beaches | Public and visitors | Map with sargassum and drift, an 8-day outlook per beach, sightings |
| Coastal managers | Governments and cleanup planners | Summary per side of the island, early-warning table sorted by urgency, CSV export |
| Data and methods | Researchers | Files and fields, example code, method with this run's settings, sources, citation, known limits |

All three read the same `site/data/` files; switching views needs no extra download.

## Add a region

Copy `regions/sxm.json`, change the bounding box, map view and beach list (with the OpenStreetMap feature behind each beach in `osm`), build a land mask with `python -m pipeline.landmask --region <id>`, then run `python -m pipeline.run --region <id>`. The Saint Martin box already covers Anguilla, Saint-Barthélemy, Saba, Sint Eustatius and Saint Kitts and Nevis, so those only need beaches added.

## License

Code: MIT ([LICENSE](LICENSE)). Data written to `site/data/`: CC BY 4.0. Font: Atkinson Hyperlegible Next, SIL Open Font License 1.1 ([site/fonts/OFL.txt](site/fonts/OFL.txt)). Land masks in `regions/land/`: ODbL, © OpenStreetMap contributors. Source data stays under its providers' terms, see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

This is an experimental forecast. Do not use it as the only basis for health, safety or navigation decisions.
