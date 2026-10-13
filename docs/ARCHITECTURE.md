# Architecture

## Principles

- **Free to run.** GitHub Actions does the daily job, GitHub Pages hosts the site. No server, no database, no API keys.
- **No dependencies.** The pipeline uses only the Python standard library. ERDDAP serves grids as CSV, which removes the need for netCDF tooling.
- **Regions are data.** One JSON file per region holds the bounding box, beaches and tuning values. Expanding means adding files, not code.
- **Fail visibly, degrade gently.** If the satellite fetch fails, the job fails and the site keeps yesterday's data with its date. If currents, wind or the land mask fail, the forecast still runs and says which fallback it used.

## Work tree

```
opensargasso/
├── regions/
│   ├── sxm.json                 region config: bbox, map view, beaches, tuning, land mask file
│   └── land/sxm.json            coastline land mask from OpenStreetMap (ODbL), see land/README.md
├── pipeline/
│   ├── erddap.py                ERDDAP CSV client and Grid type
│   ├── landmask.py              coastline land mask: build from Overpass, load, is_land
│   ├── sources.py               dataset IDs and their verification status
│   ├── detect.py                AFAI formula and detection above local background
│   ├── drift.py                 particle seeding and advection
│   ├── risk.py                  particle counts and the drift model's levels per beach
│   ├── sir.py                   NOAA Sargassum Inundation Risk: the beach levels shown
│   ├── reports.py               GitHub issue -> GeoJSON sighting
│   ├── sample.py                synthetic inputs for offline runs and tests
│   ├── calibrate.py             backtest against NOAA SIR (docs/CALIBRATION.md)
│   └── run.py                   command line entry point, writes site/data
├── site/
│   ├── index.html, style.css    page and theme (light and dark)
│   ├── app.js                   three views: beaches (map, outlook board), coastal managers (summary, table, CSV), data and methods
│   ├── i18n.js                  English, French, Dutch text
│   ├── config.js                GitHub repo for the report button
│   ├── fonts/                   Atkinson Hyperlegible Next (SIL OFL 1.1), self-hosted
│   └── data/
│       ├── latest.json          today's detections, forecast and beach risk
│       ├── reports.geojson      approved sightings
│       └── history/             one small file per day plus index.json
├── tests/test_pipeline.py       unit tests and an end-to-end sample run
├── .github/
│   ├── workflows/daily.yml      fetch, build, commit data, deploy Pages
│   ├── workflows/tests.yml      tests on every push and pull request
│   ├── workflows/report.yml     publish a sighting when it is approved
│   └── ISSUE_TEMPLATE/sargassum-report.yml
└── docs/                        this file, DATA_SOURCES.md, ROADMAP.md
```

## Daily flow

1. **Fetch.** `erddap.fetch_grid` requests a bounding box as CSV. It tries latitude ascending, then descending, because ERDDAP rejects the wrong order. The GFS wind is fetched as a 3-hourly series from the satellite date to the end of the newest forecast, from a second NOAA server when the first is reloading (`run.fetch_wind`). The land mask is read from `regions/land/`, so it needs no download; a region without one falls back to ETOPO1 from ERDDAP, cached in `.cache/`.
2. **Detect.** The box is split into blocks of about 0.75 degrees. Each block's median AFAI is the background. A pixel is flagged when it exceeds the background by the threshold (0.0005 by default), unless its footprint touches land, because the AFAI product leaves small islands and part-land pixels unmasked and land vegetation reads as algae, or it sits next to land the product masked, where coastal glare raises AFAI.
3. **Seed.** Each flagged pixel becomes one to three particles, capped at 2,500.
4. **Drift.** Every 3 hours a particle moves with the surface current plus 2 % of the GFS wind at that hour (the nearest 3-hourly step), plus a small random step. It stops when it reaches land or leaves the box.
5. **Grade.** Each beach takes the latest NOAA SIR level of its nearest coastal segment, for every day of the outlook (a backtest showed this beats the drift forecast; see `CALIBRATION.md`). The drift model also grades each beach from the particles within 50 km, weighted for the particle cap (21 or more is Warning, 24 Medium, 33 High); those levels are kept and fill in where SIR has none.
6. **Publish.** `latest.json` is rewritten, a history file is added, the data is committed and the site is deployed.

## Output format (`site/data/latest.json`)

| Field | Content |
|---|---|
| `generated`, `sample` | Build time (UTC) and whether the inputs were synthetic |
| `sources` | Data time, age in days and dataset page link for each input, and whether a fallback was used |
| `settings`, `stats` | Run parameters (threshold, background block, windage, diffusion, step, days, particle cap, risk radius and levels, cell size); pixel counts, including `land` (candidates skipped because they touch land) |
| `detections` | `[lon, lat, excess]` per flagged pixel |
| `forecast` | For each day 0 to 7: `[lon, lat, state]` per particle (0 afloat, 1 beached) |
| `sites` | Per beach and day: `risk` shown (0 Low, 1 Warning, 2 Medium, 3 High), the model's `model` levels and `count`, and `source` (`sir` or `model`) |

## Citizen sightings

A visitor opens the issue form, picks a beach and an amount. A maintainer checks it and adds the label `report-approved`. The workflow validates the report, appends it to `reports.geojson` and closes the issue. Moderation is built in, and the cost is zero. The trade-off is that reporters need a GitHub account; the roadmap lists a form without that requirement.

## Known limits

- Geostrophic currents are coarse (0.2 degrees) and miss nearshore flow, tides and wind-driven surface currents, and one day of currents is used for the whole week.
- The 7-day AFAI composite hides day-to-day movement, and clouds leave gaps.
- The land mask has cells of about 220 m, so the smallest islets and channels can be missed.
- GFS wind is on a 0.5 degree grid (about 55 km), so wind effects around the island itself are missed.
- Beach levels repeat the latest SIR report for the whole week, so sargassum on its way in does not show until NOAA's next report.
- The model's levels are particle counts, not tonnage, fitted against SIR over one season.
