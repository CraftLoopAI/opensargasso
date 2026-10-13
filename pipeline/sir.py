"""NOAA Sargassum Inundation Risk (SIR): the beach levels shown on the site.

SIR (NOAA AOML with USF) grades coastal segments every day from AFAI in a
50 to 100 km neighborhood: 0 low, 1 warning, 2 medium, 3 high. In a backtest
against SIR (docs/CALIBRATION.md), carrying the latest SIR level forward beat
our own drift forecast at every lead time, so the site uses it for beaches.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import urllib.error
import zipfile

from . import erddap, risk, sources

MAX_KM = 3.0          # a beach farther than this from any SIR segment gets no level
LOOK_BACK_DAYS = 7    # SIR is usually one to two days behind


def parse_kml(text: str, bbox: dict | None = None):
    """Coastal segments as [(level, [(lon, lat), ...])], optionally only those touching `bbox`."""
    segments = []
    for m in re.finditer(r'<SimpleData name="risk">(-?\d+)</SimpleData>.*?<coordinates>([^<]+)</coordinates>', text, re.S):
        level = int(m.group(1))
        if not 0 <= level <= 3:
            continue  # anything else is "not enough data"
        pts = [tuple(map(float, c.split(",")[:2])) for c in m.group(2).split()]
        if bbox is None or any(bbox["west"] <= x <= bbox["east"] and bbox["south"] <= y <= bbox["north"] for x, y in pts):
            segments.append((level, pts))
    return segments


def site_levels(sites, segments, max_km: float = MAX_KM) -> dict:
    """{site id: level of the nearest segment, or None when none is within `max_km`}."""
    out = {}
    for s in sites:
        best = min(((min(risk.distance_km(s["lon"], s["lat"], x, y) for x, y in pts), level) for level, pts in segments),
                   default=(None, None))
        out[s["id"]] = best[1] if best[0] is not None and best[0] <= max_km else None
    return out


def fetch_latest(today: dt.date, bbox: dict, fetch=None):
    """(report date, segments) for the newest SIR report within LOOK_BACK_DAYS, or raise."""
    fetch = fetch or (lambda url: erddap.fetch_bytes(url))
    last = None
    for back in range(LOOK_BACK_DAYS + 1):
        day = today - dt.timedelta(days=back)
        url = sources.SIR["kmz"].format(date=day.strftime("%Y%m%d"))
        try:
            data = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            last = e  # no report for that day yet: try the one before
            continue
        kmz = zipfile.ZipFile(io.BytesIO(data))
        kml = kmz.read(next(n for n in kmz.namelist() if n.endswith(".kml"))).decode("utf-8", "replace")
        return day, parse_kml(kml, bbox)
    raise RuntimeError(f"no SIR report in the last {LOOK_BACK_DAYS} days: {last}")
