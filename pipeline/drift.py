"""Particle drift forecast: surface currents plus windage plus random spread."""
from __future__ import annotations

import bisect
import datetime as dt
import math
import random

from .erddap import Grid

AFLOAT, BEACHED, LEFT = 0, 1, 2


def make_velocity(currents: Grid | None, fallback):
    """Return f(lon, lat) -> (u, v) in m/s.

    Geostrophic currents have gaps near coasts and are undefined on land, so a
    missing value falls back to the region's typical current.
    """
    def velocity(lon, lat):
        if currents is not None:
            u = currents.value("u_current", lon, lat)
            v = currents.value("v_current", lon, lat)
            if math.isfinite(u) and math.isfinite(v):
                return u, v
        return fallback[0], fallback[1]
    return velocity


def make_wind(series, start: dt.datetime, fallback):
    """Return f(lon, lat, hours) -> (u, v) in m/s, `hours` after `start`.

    `series` is a list of Grids with ugrd10m and vgrd10m, oldest first; the
    time step nearest to the requested hour is used. Without a series, or where
    a value is missing, the region's constant trade wind is used.
    """
    if not series:
        return lambda lon, lat, hours: (fallback[0], fallback[1])
    offsets = [(dt.datetime.fromisoformat(g.time.replace("Z", "+00:00")) - start).total_seconds() / 3600 for g in series]

    def wind(lon, lat, hours):
        k = bisect.bisect_left(offsets, hours)
        if k == len(offsets) or (k > 0 and hours - offsets[k - 1] <= offsets[k] - hours):
            k -= 1
        u, v = series[k].value("ugrd10m", lon, lat), series[k].value("vgrd10m", lon, lat)
        return (u, v) if math.isfinite(u) and math.isfinite(v) else (fallback[0], fallback[1])
    return wind


def make_land_test(land):
    """Return f(lon, lat) -> bool.

    `land` is a coastline mask (anything with `is_land`), an elevation Grid
    where altitude >= 0 is land, or None, in which case nothing is land.
    """
    if hasattr(land, "is_land"):
        return land.is_land

    def is_land(lon, lat):
        if land is None:
            return False
        h = land.value("altitude", lon, lat)
        return math.isfinite(h) and h >= 0
    return is_land


def seeds_for(excess: float) -> int:
    """One to three particles per detected pixel, more for stronger signals."""
    return 1 + min(2, int(excess / 0.001))


def seed_particles(detections, max_particles: int, rng: random.Random, cell_deg: float):
    """Particles for the detected pixels, sampled down to `max_particles`.

    When sampled, each particle stands for several seeds: weigh counts by
    sum(seeds_for(...)) / len(result), or more sargassum elsewhere in the box
    would mean fewer particles near any one beach.
    """
    seeds = []
    for lon, lat, excess in detections:
        for _ in range(seeds_for(excess)):
            seeds.append((lon + (rng.random() - 0.5) * cell_deg, lat + (rng.random() - 0.5) * cell_deg))
    if len(seeds) > max_particles:
        seeds = rng.sample(seeds, max_particles)
    return seeds


def simulate(seeds, velocity, is_land, bbox, days=7, step_hours=3, windage=0.02,
             wind=(0.0, 0.0), diffusion_deg=0.02, rng: random.Random | None = None, velocity_hours=False):
    """Advect particles. Returns one track per seed: [(lon, lat, state)] for day 0..days.

    `velocity` is f(lon, lat), or f(lon, lat, hours since day 0) with
    `velocity_hours`; `wind` is a constant (u, v) or f(lon, lat, hours).
    A particle stops when it reaches land (BEACHED) or leaves the box (LEFT).
    """
    rng = rng or random.Random(0)
    current_at = velocity if velocity_hours else (lambda lon, lat, hours: velocity(lon, lat))
    wind_at = wind if callable(wind) else (lambda lon, lat, hours: wind)
    step_s = step_hours * 3600.0
    steps = max(1, round(24 / step_hours))
    tracks = []
    for lon, lat in seeds:
        state = BEACHED if is_land(lon, lat) else AFLOAT
        track = [(lon, lat, state)]
        for day in range(days):
            for step in range(steps):
                if state != AFLOAT:
                    break
                hours = (day * steps + step) * step_hours
                u, v = current_at(lon, lat, hours)
                wu, wv = wind_at(lon, lat, hours)
                u += windage * wu
                v += windage * wv
                nlon = lon + u * step_s / (111320.0 * math.cos(math.radians(lat))) + rng.uniform(-1, 1) * diffusion_deg
                nlat = lat + v * step_s / 110540.0 + rng.uniform(-1, 1) * diffusion_deg
                if not (bbox["west"] <= nlon <= bbox["east"] and bbox["south"] <= nlat <= bbox["north"]):
                    state = LEFT
                elif is_land(nlon, nlat):
                    state = BEACHED
                else:
                    lon, lat = nlon, nlat
            track.append((lon, lat, state))
        tracks.append(track)
    return tracks
