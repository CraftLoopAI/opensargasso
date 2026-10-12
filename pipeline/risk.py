"""Coastal risk per site: how much forecast sargassum sits within reach."""
from __future__ import annotations

import math

from .drift import LEFT

LEVELS = ["clear", "low", "moderate", "high"]


def distance_km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def level_for(count: int, cfg: dict) -> int:
    if count >= cfg["high"]:
        return 3
    if count >= cfg["moderate"]:
        return 2
    if count >= cfg["low"]:
        return 1
    return 0


def site_risk(tracks, sites, cfg: dict, days: int):
    """For each site and day, count particles within `radius_km` and grade it.

    The thresholds are first guesses and have not been calibrated against
    observed landings. See docs/ROADMAP.md.
    """
    out = []
    for s in sites:
        counts = []
        for d in range(days + 1):
            n = 0
            for tr in tracks:
                lon, lat, state = tr[d]
                if state != LEFT and distance_km(lon, lat, s["lon"], s["lat"]) <= cfg["radius_km"]:
                    n += 1
            counts.append(n)
        out.append({**{k: s[k] for k in ("id", "name", "side", "lat", "lon") if k in s},
                    "count": counts, "risk": [level_for(n, cfg) for n in counts]})
    return out
