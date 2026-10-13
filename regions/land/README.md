# Land masks

One file per region, named in the region file as `land_mask`. The daily job reads it instead of downloading a land mask.

```
land/
└── sxm.json    Saint-Martin box (15 to 20.5 N, 66 to 58.5 W), 0.002 degree cells (about 220 m)
```

Each file holds the grid origin, cell size and size, and a bitmap (land = 1, rows from south to north) compressed with zlib and base64-encoded. `pipeline/landmask.py` reads and writes it.

## Rebuild

Coastlines change slowly, so rebuild only when OpenStreetMap has improved for the region:

```bash
python -m pipeline.landmask --region sxm
```

It downloads `natural=coastline` ways from the Overpass API in 1 degree tiles, joins them into closed islands and fills them into the grid. The download box is 1.5 degrees wider than the region so that islands crossing the edge, such as Puerto Rico, are complete. Requests use small declared limits, a crowded tile is split into quarters, and finished tiles are saved under `.cache/coast/` so an interrupted build resumes. If the default Overpass server is busy, pass another public instance with `--overpass`; the first build used `https://maps.mail.ru/osm/tools/overpass/api/interpreter` for part of the tiles.

## License

Derived from OpenStreetMap data, © OpenStreetMap contributors, available under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/). These files are therefore under the ODbL, not the code's MIT license. Forecasts made with them are produced works and only need the attribution.
