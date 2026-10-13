import json
import math
import pathlib
import random
import tempfile
import unittest
import urllib.error

from pipeline import detect, drift, erddap, reports, risk, run, sample

BBOX = {"west": -64.0, "east": -62.0, "south": 17.0, "north": 19.0}
CSV = """time,latitude,longitude,AFAI
UTC,degrees_north,degrees_east,
2026-09-29T12:00:00Z,18.03,-63.0,0.001
2026-09-29T12:00:00Z,18.03,-62.97,NaN
2026-09-29T12:00:00Z,18.0,-63.0,-0.0002
2026-09-29T12:00:00Z,18.0,-62.97,0.0003
"""


class ErddapTest(unittest.TestCase):
    def test_url(self):
        url = erddap.griddap_url("https://x.org/erddap/", "ds", ["AFAI"], BBOX, stride=2)
        self.assertEqual(url, "https://x.org/erddap/griddap/ds.csv?"
                              "AFAI%5B(last)%5D%5B(17.0):2:(19.0)%5D%5B(-64.0):2:(-62.0)%5D")

    def test_url_descending_and_no_time(self):
        url = erddap.griddap_url("https://x.org/erddap", "ds", ["altitude"], BBOX, time=None, descending_lat=True)
        self.assertIn("altitude%5B(19.0):1:(17.0)%5D", url)
        self.assertNotIn("last", url)

    def test_parse_sorts_axes_and_keeps_nan(self):
        g = erddap.parse_csv(CSV, ["AFAI"])
        self.assertEqual(g.lats, [18.0, 18.03])
        self.assertEqual(g.lons, [-63.0, -62.97])
        self.assertEqual(g.time, "2026-09-29T12:00:00Z")
        self.assertEqual(g.data["AFAI"][1][0], 0.001)
        self.assertTrue(math.isnan(g.data["AFAI"][1][1]))
        self.assertEqual(g.value("AFAI", -62.971, 18.001), 0.0003)
        self.assertTrue(math.isnan(g.value("AFAI", -60.0, 18.0)))

    def test_fetch_grid_retries_with_descending_latitude(self):
        calls = []

        def fake(url):
            calls.append(url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 404, "bad order", None, None)
            return CSV

        g = erddap.fetch_grid({"base": "https://x.org/erddap", "dataset": "ds", "variables": ["AFAI"]}, BBOX, fetch=fake)
        self.assertEqual(len(calls), 2)
        self.assertIn("(19.0):1:(17.0)", calls[1])
        self.assertEqual(len(g.lats), 2)


class DetectTest(unittest.TestCase):
    def test_afai_formula(self):
        self.assertAlmostEqual(detect.afai_from_bands(0.02, 0.02, 0.02), 0.0)
        self.assertAlmostEqual(detect.afai_from_bands(0.02, 0.019, 0.01), 0.019 - (0.02 - 0.01 * 81 / 202))

    def test_detects_only_above_background(self):
        lats = [18 + 0.03 * k for k in range(20)]
        lons = [-63 + 0.03 * k for k in range(20)]
        field = [[-0.0003] * 20 for _ in range(20)]
        field[5][7] = 0.002
        field[0][0] = float("nan")
        dets, stats = detect.detect(erddap.Grid(lats, lons, {"AFAI": field}), threshold=0.0005)
        self.assertEqual(len(dets), 1)
        self.assertAlmostEqual(dets[0][0], lons[7])
        self.assertAlmostEqual(dets[0][1], lats[5])
        self.assertEqual(stats["nodata"], 1)


class DriftTest(unittest.TestCase):
    def test_moves_west_with_current(self):
        tracks = drift.simulate([(-62.5, 18.0)], lambda lon, lat: (-0.3, 0.0), lambda lon, lat: False, BBOX,
                                days=2, windage=0, diffusion_deg=0)
        km = (tracks[0][0][0] - tracks[0][2][0]) * 111.32 * math.cos(math.radians(18))
        self.assertAlmostEqual(km, 0.3 * 2 * 86400 / 1000, delta=0.5)
        self.assertEqual(tracks[0][2][2], drift.AFLOAT)

    def test_beaches_and_leaves(self):
        land = lambda lon, lat: lon < -62.6  # noqa: E731
        tr = drift.simulate([(-62.5, 18.0)], lambda lon, lat: (-0.3, 0.0), land, BBOX, days=3, windage=0, diffusion_deg=0)[0]
        self.assertEqual(tr[-1][2], drift.BEACHED)
        self.assertGreaterEqual(tr[-1][0], -62.6)
        out = drift.simulate([(-63.9, 18.0)], lambda lon, lat: (-0.5, 0.0), lambda lon, lat: False, BBOX,
                             days=3, windage=0, diffusion_deg=0)[0]
        self.assertEqual(out[-1][2], drift.LEFT)

    def test_fallback_velocity_when_current_missing(self):
        g = erddap.Grid([18.0, 18.2], [-63.0, -62.8], {"u_current": [[float("nan"), 0.1]] * 2, "v_current": [[0.0, 0.2]] * 2})
        vel = drift.make_velocity(g, (-0.25, 0.05))
        self.assertEqual(vel(-63.0, 18.0), (-0.25, 0.05))
        self.assertEqual(vel(-62.8, 18.0), (0.1, 0.2))


class RiskTest(unittest.TestCase):
    def test_levels_and_radius(self):
        cfg = {"radius_km": 10, "low": 1, "moderate": 3, "high": 8}
        site = {"id": "a", "name": "A", "lat": 18.0, "lon": -63.0}
        near, far = (-63.02, 18.0, 0), (-63.5, 18.0, 0)
        tracks = [[far, near]] * 3 + [[far, (-63.02, 18.0, drift.LEFT)]]
        out = risk.site_risk(tracks, [site], cfg, days=1)[0]
        self.assertEqual(out["count"], [0, 3])
        self.assertEqual(out["risk"], [0, 2])
        self.assertAlmostEqual(risk.distance_km(-63, 18, -63, 19), 111.19, delta=0.1)


class ReportsTest(unittest.TestCase):
    region = run.load_region("sxm")
    body = "### Beach\n\nOrient Bay (Baie Orientale)\n\n### Latitude\n\n_No response_\n\n### Longitude\n\n_No response_\n\n" \
           "### Amount\n\nHeavy (thick mats)\n\n### Observed on\n\n2026-10-10\n\n### Note\n\nSmell is   strong\n<b>x</b>\n"

    def test_parse_and_build(self):
        f = reports.to_feature(reports.parse_issue_body(self.body), self.region, 7, "2026-10-11T08:00:00Z")
        self.assertEqual(f["geometry"]["coordinates"], [-63.0171, 18.0868])
        self.assertEqual(f["properties"]["level"], 3)
        self.assertEqual(f["properties"]["observed"], "2026-10-10")
        self.assertEqual(f["properties"]["note"], "Smell is strong <b>x</b>")

    def test_rejects_bad_input(self):
        fields = reports.parse_issue_body(self.body)
        with self.assertRaises(ValueError):
            reports.to_feature({**fields, "latitude": "48.8", "longitude": "2.3"}, self.region, 1, "")
        with self.assertRaises(ValueError):
            reports.to_feature({**fields, "amount": "lots"}, self.region, 1, "")
        with self.assertRaises(ValueError):
            reports.to_feature({**fields, "beach": "Other"}, self.region, 1, "")

    def test_append_is_idempotent(self):
        f = reports.to_feature(reports.parse_issue_body(self.body), self.region, 7, "2026-10-11T08:00:00Z")
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "reports.geojson"
            self.assertTrue(reports.append_report(path, f))
            self.assertFalse(reports.append_report(path, f))
            self.assertEqual(len(json.loads(path.read_text())["features"]), 1)


class EndToEndTest(unittest.TestCase):
    def test_sample_run_writes_valid_output(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run.main(["--region", "sxm", "--sample", "--out", d]), 0)
            data = json.loads((pathlib.Path(d) / "latest.json").read_text())
            self.assertTrue(data["sample"])
            self.assertEqual(len(data["forecast"]), 8)
            self.assertEqual(len(data["sites"]), 17)
            self.assertGreater(data["stats"]["detected"], 0)
            for s in data["sites"]:
                self.assertEqual(len(s["risk"]), 8)
                self.assertTrue(all(0 <= r <= 3 for r in s["risk"]))
            self.assertTrue((pathlib.Path(d) / "history" / "index.json").exists())
            self.assertTrue((pathlib.Path(d) / "reports.geojson").exists())


if __name__ == "__main__":
    unittest.main()
