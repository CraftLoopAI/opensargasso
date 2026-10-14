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
│   ├── config.js                GitHub repo for the report button, basemap tile server
│   ├── fonts/                   Atkinson Hyperlegible Next (SIL OFL 1.1), self-hosted
│   ├── vendor/leaflet/          Leaflet 1.9.4 (BSD 2-Clause), served with the site
│   └── data/
│       ├── latest.json          today's detections, forecast and beach risk (generated, not in git)
│       ├── reports.geojson      approved sightings
│       └── history/             one small file per day plus index.json
├── worker/                      sighting relay on Cloudflare: website form -> GitHub issue (README.md)
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
2. **Detect.** AFAI is read at full resolution (0.015 degrees, about 1.6 km). The box is split into blocks of about 0.75 degrees. Each block's median AFAI is the background. A pixel is flagged when it exceeds the background by the threshold (0.0005 by default), unless its footprint touches land, because the AFAI product leaves small islands and part-land pixels unmasked and land vegetation reads as algae, or it lies within about 3 km (two pixels) of land the product masked, where coastal glare raises AFAI.
3. **Seed.** Each flagged pixel becomes one to three particles, capped at 10,000. When the cap applies, each particle stands for several seeds and the counts are weighted (`particle_weight`).
4. **Drift.** Every 3 hours a particle moves with the surface current plus 2 % of the GFS wind at that hour (the nearest 3-hourly step), plus a small random step. It stops when it reaches land or leaves the box.
5. **Grade.** Each beach takes the latest NOAA SIR level of its nearest coastal segment, for every day of the outlook (a backtest showed this beats the drift forecast; see `CALIBRATION.md`). The drift model also grades each beach from the particles within 50 km, weighted for the particle cap (44 or more is Warning, 107 Medium, 159 High); those levels are kept and fill in where SIR has none.
6. **Publish.** `latest.json` is rewritten and a history file is added (date, AFAI time, SIR date, detections, each beach's levels and where they came from). The history file is committed and the site is deployed to GitHub Pages with `latest.json` in it. `latest.json` itself stays out of git, so the repository does not grow by half a megabyte a day. The site works out data ages itself, so they keep counting and it warns if the daily update stops.

## Output format (`site/data/latest.json`)

| Field | Content |
|---|---|
| `generated`, `sample` | Build time (UTC) and whether the inputs were synthetic |
| `sources` | Data time, age in days and dataset page link for each input, and whether a fallback was used |
| `settings`, `stats` | Run parameters (threshold, background block, windage, diffusion, step, days, particle cap, risk radius and levels, cell size); pixel counts, including `land` (candidates skipped because they touch land), and `particle_weight` (seeds per particle, used to weight the counts) |
| `detections` | `[lon, lat, excess]` per flagged pixel |
| `forecast` | For each day 0 to 7: `[lon, lat, state]` for up to 2,500 of the particles, an even subset (0 afloat, 1 beached) |
| `sites` | Per beach and day: `risk` shown (0 Low, 1 Warning, 2 Medium, 3 High), the model's `model` levels and `count`, and `source` (`sir` or `model`) |

## Citizen sightings

Two ways in, one review:

- **The form on the site**, no account needed. It posts to a small Cloudflare Worker (`worker/`), which checks a Turnstile captcha, validates the fields and opens a GitHub issue in exactly the format the issue form produces, labeled `sargassum-report`. Notes are made one line, without heading marks or @mentions, so a note cannot add fields or notify people. The form appears once `site/config.js` names the relay; until then the site links to the issue form.
- **The GitHub issue form**, for people with an account.

A maintainer checks the issue and adds the label `report-approved`. The workflow validates the report, appends it to `reports.geojson` and closes the issue; a rejected report gets a comment with the reason. An empty date becomes the day of filing on the island (UTC offset in the region file), and dates after filing are rejected. Moderation is built in. The Worker runs on Cloudflare's free plan; approved reports, including notes, are public.

## Known limits

- Geostrophic currents are coarse (0.2 degrees) and miss nearshore flow, tides and wind-driven surface currents, and one day of currents is used for the whole week.
- The 7-day AFAI composite hides day-to-day movement, and clouds leave gaps.
- The land mask has cells of about 220 m, so the smallest islets and channels can be missed.
- GFS wind is on a 0.5 degree grid (about 55 km), so wind effects around the island itself are missed.
- Beach levels repeat the latest SIR report for the whole week, so sargassum on its way in does not show until NOAA's next report.
- The model's levels are particle counts, not tonnage, fitted against SIR over one season.
