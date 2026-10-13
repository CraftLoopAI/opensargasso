"""Particle drift forecast: surface currents plus windage plus random spread."""
from __future__ import annotations

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


def seed_particles(detections, max_particles: int, rng: random.Random, cell_deg: float):
    """One to three particles per detected pixel, more for stronger signals."""
    seeds = []
    for lon, lat, excess in detections:
        for _ in range(1 + min(2, int(excess / 0.001))):
            seeds.append((lon + (rng.random() - 0.5) * cell_deg, lat + (rng.random() - 0.5) * cell_deg))
    if len(seeds) > max_particles:
        seeds = rng.sample(seeds, max_particles)
    return seeds


def simulate(seeds, velocity, is_land, bbox, days=7, step_hours=3, windage=0.02,
             wind=(0.0, 0.0), diffusion_deg=0.02, rng: random.Random | None = None):
    """Advect particles. Returns one track per seed: [(lon, lat, state)] for day 0..days.

    A particle stops when it reaches land (BEACHED) or leaves the box (LEFT).
    """
    rng = rng or random.Random(0)
    dt = step_hours * 3600.0
    steps = max(1, round(24 / step_hours))
    tracks = []
    for lon, lat in seeds:
        state = BEACHED if is_land(lon, lat) else AFLOAT
        track = [(lon, lat, state)]
        for _ in range(days):
            for _ in range(steps):
                if state != AFLOAT:
                    break
                u, v = velocity(lon, lat)
                u += windage * wind[0]
                v += windage * wind[1]
                nlon = lon + u * dt / (111320.0 * math.cos(math.radians(lat))) + rng.uniform(-1, 1) * diffusion_deg
                nlat = lat + v * dt / 110540.0 + rng.uniform(-1, 1) * diffusion_deg
                if not (bbox["west"] <= nlon <= bbox["east"] and bbox["south"] <= nlat <= bbox["north"]):
                    state = LEFT
                elif is_land(nlon, nlat):
                    state = BEACHED
                else:
                    lon, lat = nlon, nlat
            track.append((lon, lat, state))
        tracks.append(track)
    return tracks
