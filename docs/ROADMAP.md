# Roadmap

## Phase 1: Saint-Martin / Sint Maarten

Goal: a forecast local people can trust.

- [x] Run the live pipeline once and fix whatever the real responses break
- [ ] Confirm the land mask dataset, or replace it with an OpenStreetMap coastline
- [ ] Check beach coordinates against OpenStreetMap
- [ ] Real wind: replace the constant trade wind with a forecast source
- [ ] Decide on currents: keep geostrophic or move to HYCOM, based on data lag
- [ ] Calibrate risk thresholds against sightings and NOAA's Sargassum Inundation Risk
- [ ] Find local partners for sightings and validation (nature foundations, the Réserve Naturelle, hotels, dive shops)
- [ ] Sighting form that does not need a GitHub account

## Phase 2: neighboring islands

Anguilla, Saint-Barthélemy, Saba, Sint Eustatius, Saint Kitts and Nevis. The Saint Martin bounding box already covers them, so the work is adding beaches and a region picker on the site.

- [ ] One region file per island, or one file with island groups
- [ ] Region picker and per-island pages
- [ ] Alerts by email or messaging when a beach is forecast Moderate or higher
- [ ] Weekly summary per island

## Phase 3: wider Caribbean

- [ ] Tile the pipeline over several boxes so no single request gets too large
- [ ] Spanish and Papiamento
- [ ] Higher resolution detection near shore from Sentinel-2 and Sentinel-3
- [ ] Forecast uncertainty: run several windage values and show a range
- [ ] Public API documentation and long-term history with seasonal charts
