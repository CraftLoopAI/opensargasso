"""Detection near land: glare beside masked land is skipped, cloud edges are not."""
import math

from pipeline import detect, erddap

NAN = float("nan")


def grid_with_gap():
    lats = [18 + 0.03 * k for k in range(12)]
    lons = [-63 + 0.03 * k for k in range(12)]
    field = [[-0.0003] * 12 for _ in lats]
    field[5][5] = NAN        # a gap in the satellite product
    field[5][6] = 0.002      # bright pixel right beside it
    field[9][9] = 0.002      # bright pixel in open water
    return erddap.Grid(lats, lons, {"AFAI": field})


def test_pixel_next_to_masked_land_is_skipped():
    g = grid_with_gap()
    gap = (g.lons[5], g.lats[5])
    on_gap = lambda lon, lat: math.isclose(lon, gap[0]) and math.isclose(lat, gap[1])  # noqa: E731
    found, stats = detect.detect(g, threshold=0.0005, is_land=on_gap, pixel_deg=0.015)
    assert [(round(x, 2), round(y, 2)) for x, y, _ in found] == [(round(g.lons[9], 2), round(g.lats[9], 2))]
    assert stats["land"] == 1


def test_pixel_next_to_a_cloud_gap_is_kept():
    found, stats = detect.detect(grid_with_gap(), threshold=0.0005, is_land=lambda lon, lat: False, pixel_deg=0.015)
    assert len(found) == 2 and stats["land"] == 0
