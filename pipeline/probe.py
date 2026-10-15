"""Which data sources answer from here? One small request to each, no retries.

    python -m pipeline.probe

Run from GitHub Actions (.github/workflows/probe.yml) to see which servers
accept GitHub's runners; servers can block the shared cloud addresses they use
while answering home connections. Prints status, time and the start of each
answer, and always exits 0.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from . import erddap, sources

BOX = {"west": -63.5, "east": -62.5, "south": 17.5, "north": 18.5}  # small box around Saint Martin


def candidates() -> list:
    """(label, url): wind sources first, then the other inputs and storm data."""
    wind = lambda s: erddap.griddap_url(s["base"], s["dataset"], s["variables"], BOX, time="last",  # noqa: E731
                                        descending_lat=s.get("lat_descending", False))
    return [
        ("wind: PacIOOS ERDDAP (primary)", wind(sources.WIND)),
        ("wind: PacIOOS THREDDS", "https://pae-paha.pacioos.hawaii.edu/thredds/dodsC/ncep_global/NCEP_Global_Atmospheric_Model_best.ncd.dds"),
        ("wind: NOAA PFEG upwell ERDDAP (copy)", wind(sources.WIND_MIRROR)),
        ("wind: NOAA PFEG coastwatch ERDDAP", "https://coastwatch.pfeg.noaa.gov/erddap/info/index.html"),
        ("wind: UCAR THREDDS GFS 0.5 degree", "https://thredds.ucar.edu/thredds/dodsC/grib/NCEP/GFS/Global_0p5deg/Best.dds"),
        ("wind: Open-Meteo GFS", "https://api.open-meteo.com/v1/gfs?latitude=18.05&longitude=-63.05"
                                 "&hourly=wind_speed_10m,wind_direction_10m&forecast_days=1"),
        ("wind: NOAA NOMADS", "https://nomads.ncep.noaa.gov/"),
        ("storms: NHC CurrentStorms.json", "https://www.nhc.noaa.gov/CurrentStorms.json"),
        ("control: NOAA AOML ERDDAP (AFAI, currents)", "https://cwcgom.aoml.noaa.gov/erddap/info/index.html"),
    ]


def check(url: str, timeout: int = 30, opener=urllib.request.urlopen) -> tuple:
    """(status, seconds, first characters of the answer) for one GET."""
    start = time.monotonic()
    try:
        with opener(urllib.request.Request(url, headers={"User-Agent": erddap.USER_AGENT}), timeout=timeout) as resp:
            status, body = resp.status, resp.read(400)
    except urllib.error.HTTPError as e:
        status, body = e.code, (e.read(400) if e.fp else b"")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        status, body = "no answer", str(getattr(e, "reason", e)).encode()
    return status, round(time.monotonic() - start, 2), " ".join(body.decode("utf-8", "replace").split())[:120]


def main() -> int:
    for label, url in candidates():
        status, seconds, start = check(url)
        print(f"{label:46s} {str(status):10s} {seconds:6.2f}s  {start}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
