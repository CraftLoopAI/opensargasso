"""Context for the site: the newest USF sargassum outlook and Atlantic storms near the region.

Fetched once a day by the daily job. Both are context only: if a server does
not answer, the site leaves the item out and keeps working.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request

from . import erddap, risk

USF_PDF = "https://optics.marine.usf.edu/projects/SaWS/pdf/Sargassum_outlook_{year}_bulletin{month:02d}_USF.pdf"
NHC_STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"
NHC_PAGE = "https://www.nhc.noaa.gov/"
STORM_RADIUS_KM = 1500  # a storm moving at 20 km/h covers that in about three days


def exists(url: str, timeout: int = 30) -> bool:
    """True if the server has the file; False on 404. Other errors raise."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": erddap.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def latest_usf(today: dt.date, check=exists) -> dict | None:
    """{"url", "month"} of the newest monthly USF outlook, looking back two months; None if none is found.

    USF publishes the bulletin for a month at the end of that month.
    """
    for back in range(3):
        year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
        url = USF_PDF.format(year=year, month=month + 1)
        if check(url):
            return {"url": url, "month": f"{year}-{month + 1:02d}"}
    return None


def nearby_storms(center: tuple, radius_km: float = STORM_RADIUS_KM, fetch=None) -> list:
    """Active Atlantic storms within `radius_km` of `center` (lat, lon), nearest first, from NHC."""
    fetch = fetch or (lambda url: erddap.fetch_text(url, timeout=30, waits=(20,)))
    storms = []
    for s in json.loads(fetch(NHC_STORMS)).get("activeStorms", []):
        if not str(s.get("id", "")).lower().startswith("al"):  # Atlantic basin only
            continue
        lat, lon = float(s["latitudeNumeric"]), float(s["longitudeNumeric"])
        km = risk.distance_km(lon, lat, center[1], center[0])
        if km > radius_km:
            continue
        storms.append({"name": s.get("name", ""), "kind": s.get("classification", ""), "intensity_kt": _int(s.get("intensity")),
                       "lat": lat, "lon": lon, "distance_km": round(km), "updated": s.get("lastUpdate", ""),
                       "url": (s.get("forecastGraphics") or {}).get("url") or NHC_PAGE})
    return sorted(storms, key=lambda s: s["distance_km"])


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
