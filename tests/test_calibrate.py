"""Calibration helpers: scoring, threshold search, weighted counts, time-varying currents."""
import math

from pipeline import calibrate, drift

BBOX = {"west": -64.0, "east": -62.0, "south": 17.0, "north": 19.0}


def test_kappa_rewards_agreement_and_punishes_reversal():
    assert calibrate.qwk([0, 1, 2, 3], [0, 1, 2, 3])[0] == 1.0
    assert calibrate.qwk([3, 2, 1, 0], [0, 1, 2, 3])[0] < 0
    assert calibrate.qwk([0, 1, 2], [2, 2, 2])[0] == 0.0               # constant reference: no better than chance
    assert math.isnan(calibrate.qwk([2, 2], [2, 2])[0])                # both constant: undefined
    assert calibrate.qwk([0, 1], [0, 0])[1][1][0] == 1                 # confusion: rows ours, columns reference


def test_level_boundaries():
    assert [calibrate.level(c, (21, 24, 33)) for c in (0, 20, 21, 24, 32, 33)] == [0, 0, 1, 2, 2, 3]


def test_fit_finds_thresholds_that_separate_the_levels():
    samples = [(c, 0) for c in range(0, 5)] + [(c, 1) for c in range(10, 15)] + [(c, 2) for c in range(20, 25)] + [(c, 3) for c in range(30, 35)]
    k, (low, moderate, high) = calibrate.fit_thresholds(samples)
    assert k == 1.0 and 4 < low <= 10 and 14 < moderate <= 20 and 24 < high <= 30
    assert calibrate.fit_thresholds([(3, 2), (5, 2)])[1] is None       # one reference level: nothing to fit


def test_counts_near_weighs_each_particle():
    site = {"id": "a", "lat": 18.0, "lon": -63.0}
    points = [(-63.0, 18.0)] * 3 + [(-62.0, 18.0)]                    # three near, one about 105 km away
    assert calibrate.counts_near(points, [site], 10, weight=2.5) == {"a": 8}


def test_simulate_can_use_currents_that_change_over_time():
    def current(lon, lat, hours):
        return (0.3, 0.0) if hours < 24 else (-0.3, 0.0)
    track = drift.simulate([(-63.0, 18.0)], current, lambda lon, lat: False, BBOX, days=2, windage=0,
                           diffusion_deg=0, velocity_hours=True)[0]
    assert track[1][0] > -63.0 + 0.2 and abs(track[2][0] + 63.0) < 1e-9
