"""NOAA SIR beach levels, the particle-cap weighting, and how the output combines them."""
import datetime as dt
import io
import pathlib
import urllib.error
import zipfile

from pipeline import drift, risk, run, sample, sir

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sir.kml"
REGION = run.load_region("sxm")
SXM = {"west": -63.2, "east": -62.95, "south": 17.98, "north": 18.15}


def test_parse_kml_keeps_levels_and_filters_by_area():
    text = FIXTURE.read_text()
    assert len(sir.parse_kml(text)) == 12
    near = sir.parse_kml(text, SXM)
    assert len(near) == 10 and {level for level, _ in near} == {2}   # 11 October: medium all round Saint Martin
    junk = '<SimpleData name="risk">9</SimpleData><coordinates>-63.0,18.0 -63.01,18.01</coordinates>'
    assert sir.parse_kml(junk) == []                                  # not a level: not enough data


def test_site_levels_use_the_nearest_segment_within_reach():
    segments = sir.parse_kml(FIXTURE.read_text(), SXM)
    levels = sir.site_levels(REGION["sites"] + [{"id": "far", "lat": 25.0, "lon": -60.0}], segments)
    assert all(levels[s["id"]] == 2 for s in REGION["sites"])
    assert levels["far"] is None


def test_fetch_latest_steps_back_over_missing_days():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("KML/Risk.kml", FIXTURE.read_text())
    asked = []

    def fake(url):
        asked.append(url)
        if "20261013" in url:
            raise urllib.error.HTTPError(url, 404, "not yet", None, None)
        return buf.getvalue()

    day, segments = sir.fetch_latest(dt.date(2026, 10, 13), SXM, fetch=fake)
    assert day == dt.date(2026, 10, 12) and len(segments) == 10 and len(asked) == 2


def test_beach_levels_carry_sir_forward_and_fall_back_to_the_model():
    model = [{"id": "a", "risk": [0, 1, 2]}, {"id": "b", "risk": [3, 3, 3]}]
    out = run.beach_levels(model, (dt.date(2026, 10, 11), {"a": 1, "b": None}), days=2)
    assert out[0]["risk"] == [1, 1, 1] and out[0]["model"] == [0, 1, 2] and out[0]["source"] == "sir"
    assert out[1]["risk"] == [3, 3, 3] and out[1]["source"] == "model"
    assert run.beach_levels(model, None, days=2)[0]["source"] == "model"


def test_counts_are_weighted_by_the_seeds_each_particle_stands_for():
    site = {"id": "a", "name": "A", "lat": 18.0, "lon": -63.0}
    tracks = [[(-63.0, 18.0, drift.AFLOAT)]] * 3
    cfg = {"radius_km": 10, "low": 1, "moderate": 5, "high": 8}
    assert risk.site_risk(tracks, [site], cfg, days=0)[0]["count"] == [3]
    weighted = risk.site_risk(tracks, [site], cfg, days=0, weight=2.5)[0]
    assert weighted["count"] == [8] and weighted["risk"] == [3]       # 3 particles x 2.5 seeds each
    assert drift.seeds_for(0.0005) == 1 and drift.seeds_for(0.0025) == 3 and drift.seeds_for(0.01) == 3


def test_output_records_the_sir_source():
    bbox, now = REGION["bbox"], dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)
    inputs = (sample.afai_grid(bbox), sample.currents_grid(bbox), sample.land_grid(bbox), [])
    levels = {s["id"]: 2 for s in REGION["sites"]}
    out = run.build(REGION, *inputs, False, now, sir_levels=(dt.date(2026, 10, 11), levels))
    assert out["sources"]["sir"]["date"] == "2026-10-11" and out["sources"]["sir"]["age_days"] == 2
    assert all(s["risk"] == [2] * 8 and s["source"] == "sir" for s in out["sites"])
    assert run.build(REGION, *inputs, False, now)["sources"]["sir"]["fallback"] is True
