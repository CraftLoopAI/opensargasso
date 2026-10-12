"""Synthetic inputs so the pipeline and site run offline.

Nothing here is an observation. Islands are ellipses, sargassum lines are
random walks, currents are a steady westward flow with noise.
"""
from __future__ import annotations

import math
import random

from .erddap import Grid, NAN

ISLANDS = [  # lon, lat, half-width, half-height in degrees
    (-63.06, 18.07, 0.075, 0.055), (-63.06, 18.22, 0.13, 0.03), (-62.83, 17.90, 0.05, 0.025),
    (-63.24, 17.63, 0.02, 0.02), (-62.97, 17.49, 0.03, 0.035), (-62.75, 17.33, 0.12, 0.07),
    (-62.58, 17.15, 0.05, 0.05), (-61.80, 17.07, 0.12, 0.09), (-61.80, 17.63, 0.07, 0.10),
    (-62.19, 16.74, 0.04, 0.07), (-61.55, 16.25, 0.30, 0.20), (-61.35, 15.42, 0.11, 0.20),
    (-64.75, 17.73, 0.17, 0.04), (-64.75, 18.38, 0.30, 0.05), (-65.90, 18.20, 0.40, 0.22),
]


def _axis(lo, hi, step):
    n = int(round((hi - lo) / step)) + 1
    return [round(lo + k * step, 6) for k in range(n)]


def _on_land(lon, lat):
    return any(((lon - x) / rx) ** 2 + ((lat - y) / ry) ** 2 <= 1 for x, y, rx, ry in ISLANDS)


def land_grid(bbox, step=1 / 60) -> Grid:
    lats, lons = _axis(bbox["south"], bbox["north"], step), _axis(bbox["west"], bbox["east"], step)
    alt = [[50.0 if _on_land(lon, lat) else -2000.0 for lon in lons] for lat in lats]
    return Grid(lats, lons, {"altitude": alt})


def currents_grid(bbox, seed=3, step=0.2) -> Grid:
    rng = random.Random(seed)
    lats, lons = _axis(bbox["south"], bbox["north"], step), _axis(bbox["west"], bbox["east"], step)
    u = [[-0.25 + rng.gauss(0, 0.05) for _ in lons] for _ in lats]
    v = [[0.06 + rng.gauss(0, 0.04) for _ in lons] for _ in lats]
    return Grid(lats, lons, {"u_current": u, "v_current": v}, time="sample")


def afai_grid(bbox, seed=11, step=0.03) -> Grid:
    rng = random.Random(seed)
    lats, lons = _axis(bbox["south"], bbox["north"], step), _axis(bbox["west"], bbox["east"], step)
    ny, nx = len(lats), len(lons)
    extra = [[0.0] * nx for _ in range(ny)]
    for _ in range(9):  # sargassum lines east and south-east of the island
        lon, lat = rng.uniform(-62.9, -59.5), rng.uniform(16.2, 19.2)
        heading, strength = math.pi + rng.uniform(-0.5, 0.5), rng.uniform(0.0008, 0.0025)
        for _ in range(rng.randint(15, 45)):
            heading += rng.uniform(-0.25, 0.25)
            lon += math.cos(heading) * step
            lat += math.sin(heading) * step * 0.6
            i, j = round((lon - lons[0]) / step), round((lat - lats[0]) / step)
            if 0 <= i < nx and 0 <= j < ny:
                extra[j][i] += strength * rng.uniform(0.4, 1.0)
    clouds = [(rng.uniform(bbox["west"], bbox["east"]), rng.uniform(bbox["south"], bbox["north"]), rng.uniform(0.3, 0.8))
              for _ in range(6)]
    field = []
    for j, lat in enumerate(lats):
        row = []
        for i, lon in enumerate(lons):
            if _on_land(lon, lat) or any((lon - x) ** 2 + (lat - y) ** 2 < r * r for x, y, r in clouds):
                row.append(NAN)
            else:
                row.append(-0.0003 + rng.gauss(0, 0.00008) + extra[j][i])
        field.append(row)
    return Grid(lats, lons, {"AFAI": field}, time="sample")
