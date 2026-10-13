# Contributing

Thanks for helping. Three easy ways in:

- **Report sargassum** with the issue form. That is real validation data.
- **Fix a beach.** Each beach in `regions/*.json` names the OpenStreetMap feature its position comes from (`osm`). If OSM is wrong or a beach is missing, fix it in OpenStreetMap first, then update the region file in a pull request. Keep the issue form's beach list identical; a test checks it.
- **Translate.** Add a language block to `site/i18n.js` with the same keys.

For code: keep the pipeline free of third-party dependencies, add a test for every change, and run `python -m pytest` before opening a pull request. State plainly in the pull request what you ran and what you did not.
