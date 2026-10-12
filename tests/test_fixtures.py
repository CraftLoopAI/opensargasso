"""Parse real ERDDAP responses saved in tests/fixtures/ (see the README there)."""
import datetime as dt
import math
import pathlib

from pipeline import detect, drift, erddap, run, sources

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name, source):
    return erddap.parse_csv((FIXTURES / name).read_text(encoding="utf-8"), source["variables"])


def test_afai():
    g = load("afai.csv", sources.AFAI)
    assert g.time == "2026-10-11T12:00:00Z"
    assert (len(g.lats), len(g.lons)) == (5, 6)
    assert g.lats == sorted(g.lats) and g.lons == sorted(g.lons)
    assert math.isclose(g.dlat, 0.015, abs_tol=1e-4) and math.isclose(g.dlon, 0.015)
    assert g.value("AFAI", -63.005, 18.077) == 4.51e-4  # sent as "4.51E-4"
    assert g.value("AFAI", -62.975, 18.122) == 0.003157  # Tintamarre: land, but not masked
    assert math.isnan(g.value("AFAI", -63.035, 18.077))  # Saint Martin land is NaN
    later = dt.datetime(2026, 10, 13, 13, tzinfo=dt.timezone.utc)
    assert run.age_days(g.time, later) == 2


def test_currents():
    g = load("currents.csv", sources.CURRENTS)
    assert g.time == "2026-10-10T00:00:00Z"
    assert g.lats == [17.9, 18.1, 18.3]
    assert g.lons == [-63.3, -63.1, -62.9]
    velocity = drift.make_velocity(g, (0.0, 0.0))
    assert velocity(-63.1, 18.1) == (-0.0841, 0.0014)
    assert velocity(-62.9, 18.3) == (-0.2333, 0.0795)


def test_land():
    g = load("land.csv", sources.LAND)
    assert g.time is None  # etopo180 has no time axis
    assert (len(g.lats), len(g.lons)) == (5, 6)
    assert math.isclose(g.dlat, 1 / 60) and math.isclose(g.dlon, 1 / 60)
    is_land = drift.make_land_test(g)
    assert is_land(-63.033, 18.083)  # 101 m, above Orient Bay
    assert is_land(-62.983, 18.117)  # Tintamarre: altitude 0 counts as land
    assert not is_land(-63.0, 18.117)  # -2 m
    assert not is_land(-62.95, 18.083)  # -4 m


def test_tintamarre_is_not_flagged():
    # Tintamarre's AFAI pixel sits halfway between a 0 m and a -1 m land cell,
    # so a test at the pixel center alone misses it on this grid.
    afai, land = load("afai.csv", sources.AFAI), load("land.csv", sources.LAND)

    def flagged(found):
        return {(round(lon, 3), round(lat, 3)) for lon, lat, _ in found}

    plain, _ = detect.detect(afai, threshold=0.0005)
    masked, stats = detect.detect(afai, threshold=0.0005, is_land=drift.make_land_test(land), pixel_deg=0.015)
    assert (-62.975, 18.122) in flagged(plain)
    assert flagged(masked) == {(-62.96, 18.122), (-62.975, 18.137)}  # open water east and north of it
    assert stats["land"] == 4 and stats["detected"] == 2
