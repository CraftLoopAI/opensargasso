# Fixtures

Small real ERDDAP responses, saved on 12 October 2026 so the live CSV format is pinned by `tests/test_fixtures.py`. Each was requested with `erddap.griddap_url` at stride 1.

```
fixtures/
├── afai.csv        AFAI 7D, 2026-10-11, east coast of Saint Martin and Tintamarre (land cells are NaN)
├── currents.csv    miamicurrents, 2026-10-10, 3 x 3 cells around the island
└── land.csv        etopo180, same area as afai.csv (no time column)
```

To refresh one, request the same box again:

```
https://cwcgom.aoml.noaa.gov/erddap/griddap/noaa_aoml_atlantic_oceanwatch_AFAI_7D.csv?AFAI%5B(2026-10-11T12:00:00Z)%5D%5B(18.08):1:(18.13)%5D%5B(-63.03):1:(-62.96)%5D
https://cwcgom.aoml.noaa.gov/erddap/griddap/miamicurrents.csv?u_current%5B(2026-10-10T00:00:00Z)%5D%5B(17.9):1:(18.3)%5D%5B(-63.3):1:(-62.9)%5D,v_current%5B(2026-10-10T00:00:00Z)%5D%5B(17.9):1:(18.3)%5D%5B(-63.3):1:(-62.9)%5D
https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv?altitude%5B(18.07):1:(18.14)%5D%5B(-63.04):1:(-62.95)%5D
```
