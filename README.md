# OpenSargasso

Free, open sargassum monitoring for the Caribbean, starting with **Saint-Martin / Sint Maarten**.

It reads open satellite data once a day, flags floating sargassum, forecasts where it drifts over the next 7 days, and shows each beach's level from NOAA's Sargassum Inundation Risk: Low, Warning, Medium or High. The result is a static website in English, French and Dutch: **https://craftloopai.github.io/opensargasso/**. There is no server and no paid service.

> **Status: experimental.** Live since 14 October 2026, updated every day from NOAA data. The pipeline also runs on synthetic sample data and has unit tests. Beach levels come from NOAA's Sargassum Inundation Risk, which beat our own drift forecast in a backtest ([docs/CALIBRATION.md](docs/CALIBRATION.md)). See [Status](#status).

## Quick start

The pipeline needs only Python 3.11+. The tests need pytest (`pip install pytest`).

```bash
python -m pytest                               # run the tests
python -m pipeline.run --region sxm --sample   # build site/data/latest.json from sample inputs (it is not stored in git)
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
6. Optional: deploy the sighting relay in `worker/` (free Cloudflare account) so visitors can report without a GitHub account. See [worker/README.md](worker/README.md).

## How it works

```
NOAA / USF open data ──> pipeline (Python) ──> site/data/*.json ──> static site (Leaflet)
                              ^
        approved GitHub issue ┘  (citizen sightings, from the issue form or the site's form via worker/)
```

| Step | Module | What it does |
|---|---|---|
| Fetch | `pipeline/erddap.py`, `sources.py`, `landmask.py` | Downloads the AFAI satellite index, surface currents and the GFS wind forecast as CSV, and reads the stored coastline land mask |
| Detect | `pipeline/detect.py` | Flags pixels whose AFAI stands out above the local background |
| Drift | `pipeline/drift.py` | Moves particles with currents and wind for 7 days; they stop at land |
| Beach levels | `pipeline/sir.py`, `risk.py` | Takes NOAA SIR for the coast nearest each beach; the drift model's particle counts within 50 km are the fallback |
| Publish | `pipeline/run.py` | Writes `latest.json`, deployed with the site, and a small daily history file, committed to the repository |
| Sightings | `pipeline/reports.py`, `worker/` | The site's form posts to a small Cloudflare Worker that opens a GitHub issue; an approved issue becomes a point in `reports.geojson` |

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), [docs/ROADMAP.md](docs/ROADMAP.md).

## Status

| Part | State |
|---|---|
| Pipeline logic (detect, drift, risk, reports) | Unit tested, runs on sample data |
| Dataset IDs (AFAI, currents, land mask) | Checked against the NOAA servers in October 2026 |
| Live download | Works. First run 12 October 2026: AFAI 1 day old, currents 2 days old. Response formats pinned by `tests/fixtures/` |
| Daily update | Runs on GitHub Actions every day at 11:23 UTC since 14 October 2026 and deploys the site to GitHub Pages. Each run commits only the day's small history file; `latest.json` goes to the site, not into git |
| Land mask | OpenStreetMap coastline in 220 m cells, stored in `regions/land/` (13 October 2026). Simpson Bay Lagoon, Oyster Pond and Pinel are resolved, and the daily run needs no land download (3 seconds instead of 80) |
| Detection | AFAI at full resolution (0.015 degrees, about 1.6 km) since 13 October 2026. Pixels that touch land are skipped (Tintamarre was flagged as sargassum), and so are pixels within about 3 km of land the AFAI product masked, where coastal glare looks like algae. Real mats that close to the coast are missed |
| Currents | NOAA AOML geostrophic currents, 1 to 2 days old in October 2026. Kept after a comparison with SMOC total currents via Open-Meteo (13 October 2026); see `docs/DATA_SOURCES.md` |
| Wind | NOAA GFS 10 m wind forecast (0.5 degrees, every 3 hours) from the satellite date to the end of the newest forecast, since 13 October 2026. Served by PacIOOS (University of Hawaii), with NOAA PFEG's copy as a second try, since 15 October 2026: NOAA's servers refused GitHub's runners on two of three days. When both fail, the last good forecast is reused while it covers at least a day, and a second run at 15:23 UTC tries again on a new runner; the region's constant trade wind is the last resort. Independent sources (Open-Meteo, UCAR) are not added yet |
| Beach levels | NOAA SIR, latest report carried forward over the week, days 4 to 7 marked less certain (13 October 2026). The drift model's thresholds (50 km: 44, 107, 159, refitted for full resolution) were fitted against SIR and are the fallback. Not yet checked against sightings. See `docs/CALIBRATION.md` |
| Beach coordinates | Checked against OpenStreetMap on 13 October 2026. Each beach records the OSM feature its position comes from (`osm`); Cul-de-Sac, Marigot and Oyster Pond have no mapped beach and use the bay or place |
| Website | Three views (beaches, coastal managers, data and methods), viewed with live tiles in Chromium at desktop and phone width, light and dark, English and French, on 12 October 2026. Checked with scripted tests in Firefox 157 and WebKit 27.2 (the engine behind Safari) through Playwright on 13 October 2026: every view, day switching, CSV in English and French, dark theme, phone layout with touch. Not yet checked in Safari itself or on a real phone |
| Sighting form | Form on the site that needs no GitHub account, live since 14 October 2026, with a Cloudflare Worker relay and Turnstile spam check in `worker/`. A test report from the live site opened the expected GitHub issue (closed without publishing). The GitHub issue form remains for people with an account |
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

Code: MIT ([LICENSE](LICENSE)). Data written to `site/data/`: CC BY 4.0. Font: Atkinson Hyperlegible Next, SIL Open Font License 1.1 ([site/fonts/OFL.txt](site/fonts/OFL.txt)). Map library: Leaflet 1.9.4, BSD 2-Clause ([site/vendor/leaflet/LICENSE](site/vendor/leaflet/LICENSE)). Land masks in `regions/land/`: ODbL, © OpenStreetMap contributors. Source data stays under its providers' terms, see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

This is an experimental forecast. Do not use it as the only basis for health, safety or navigation decisions.
