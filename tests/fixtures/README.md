# Fixtures

Small real ERDDAP responses, saved on 12 October 2026 so the live formats are pinned by the tests (`test_fixtures.py`, `test_wind.py`, `test_sir.py`). Each was requested with `erddap.griddap_url` at stride 1.

```
fixtures/
├── afai.csv        AFAI 7D, 2026-10-11, east coast of Saint Martin and Tintamarre (land cells are NaN)
├── currents.csv    miamicurrents, 2026-10-10, 3 x 3 cells around the island
├── land.csv        etopo180, same area as afai.csv (no time column)
├── wind.csv        ncep_global_lon180 (GFS), 2026-10-12 12:00 and 15:00 UTC, 3 x 3 cells
└── sir.kml         NOAA SIR of 2026-10-11: the 10 segments around Saint Martin and 2 far away, unchanged KML
```

To refresh one, request the same box again:

```
https://cwcgom.aoml.noaa.gov/erddap/griddap/noaa_aoml_atlantic_oceanwatch_AFAI_7D.csv?AFAI%5B(2026-10-11T12:00:00Z)%5D%5B(18.08):1:(18.13)%5D%5B(-63.03):1:(-62.96)%5D
https://cwcgom.aoml.noaa.gov/erddap/griddap/miamicurrents.csv?u_current%5B(2026-10-10T00:00:00Z)%5D%5B(17.9):1:(18.3)%5D%5B(-63.3):1:(-62.9)%5D,v_current%5B(2026-10-10T00:00:00Z)%5D%5B(17.9):1:(18.3)%5D%5B(-63.3):1:(-62.9)%5D
https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv?altitude%5B(18.07):1:(18.14)%5D%5B(-63.04):1:(-62.95)%5D
https://upwell.pfeg.noaa.gov/erddap/griddap/ncep_global_lon180.csv?ugrd10m%5B(2026-10-12T12:00:00Z):1:(2026-10-12T15:00:00Z)%5D%5B(17.5):1:(18.5)%5D%5B(-63.5):1:(-62.5)%5D,vgrd10m%5B(2026-10-12T12:00:00Z):1:(2026-10-12T15:00:00Z)%5D%5B(17.5):1:(18.5)%5D%5B(-63.5):1:(-62.5)%5D
```
