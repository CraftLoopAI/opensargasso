"""Sargassum detection from the Alternative Floating Algae Index (AFAI)."""
from __future__ import annotations

import math
import statistics

from .erddap import Grid


def afai_from_bands(r667: float, r748: float, r869: float) -> float:
    """AFAI from Rayleigh-corrected reflectance (Wang and Hu, 2016).

    The red-edge band is compared with a straight baseline drawn between the
    red and near-infrared bands. Floating algae lift it above the baseline.
    Kept here for the planned Sentinel-3 processing; the daily job currently
    reads AFAI that USF has already computed.
    """
    baseline = r667 + (r869 - r667) * (748.0 - 667.0) / (869.0 - 667.0)
    return r748 - baseline


def touches_land(is_land, lon: float, lat: float, pixel_deg: float) -> bool:
    """True when a pixel of `pixel_deg` centered on (lon, lat) overlaps land.

    Samples the center, edges and corners, so a pixel halfway between two
    land-mask cells is not decided by rounding.
    """
    h = pixel_deg / 2
    return any(is_land(lon + dx, lat + dy) for dx in (-h, 0.0, h) for dy in (-h, 0.0, h))


def detect(grid: Grid, threshold: float, block_deg: float = 0.75, var: str = "AFAI",
           is_land=None, pixel_deg: float | None = None):
    """Flag pixels whose AFAI exceeds the local background by `threshold`.

    The background is the median of valid pixels in a block of about
    `block_deg` degrees, which removes large-scale glint and haze gradients.
    With `is_land(lon, lat)`, pixels that touch land are not flagged: the AFAI
    product leaves small islands such as Tintamarre and part-land pixels
    unmasked, and land vegetation reads as floating algae. `pixel_deg` is the
    sensor pixel size, which is smaller than the grid step when it is strided.
    Returns (detections, stats); detections are (lon, lat, excess) tuples.
    """
    field = grid.data[var]
    ny, nx = len(grid.lats), len(grid.lons)
    pixel_deg = pixel_deg or abs(grid.dlon)
    valid_all = [v for row in field for v in row if math.isfinite(v)]
    stats = {"pixels": nx * ny, "valid": len(valid_all), "nodata": nx * ny - len(valid_all), "land": 0, "detected": 0}
    if not valid_all:
        return [], stats
    global_median = statistics.median(valid_all)
    bj = max(1, round(block_deg / abs(grid.dlat)))
    bi = max(1, round(block_deg / abs(grid.dlon)))
    detections = []
    for j0 in range(0, ny, bj):
        for i0 in range(0, nx, bi):
            cells = [(j, i) for j in range(j0, min(j0 + bj, ny)) for i in range(i0, min(i0 + bi, nx))
                     if math.isfinite(field[j][i])]
            if not cells:
                continue
            background = statistics.median(field[j][i] for j, i in cells) if len(cells) >= 10 else global_median
            for j, i in cells:
                excess = field[j][i] - background
                if excess <= threshold:
                    continue
                if is_land and touches_land(is_land, grid.lons[i], grid.lats[j], pixel_deg):
                    stats["land"] += 1
                else:
                    detections.append((grid.lons[i], grid.lats[j], excess))
    stats["detected"] = len(detections)
    return detections, stats
