"""Context for the site: the newest USF outlook, and only Atlantic storms near the region."""
import datetime as dt
import json

from pipeline import bulletins, run, sample


def test_newest_usf_outlook_looks_back_across_new_year():
    have = {"https://optics.marine.usf.edu/projects/SaWS/pdf/Sargassum_outlook_2025_bulletin12_USF.pdf"}
    got = bulletins.latest_usf(dt.date(2026, 1, 20), check=lambda url: url in have)
    assert got == {"url": next(iter(have)), "month": "2025-12"}
    assert bulletins.latest_usf(dt.date(2026, 10, 15), check=lambda url: False) is None


def test_only_atlantic_storms_within_the_radius_nearest_first():
    feed = {"activeStorms": [
        {"id": "ep212026", "name": "Trudy", "classification": "TS", "intensity": "60", "latitudeNumeric": 12.4, "longitudeNumeric": -100.8},
        {"id": "al142026", "name": "Far", "classification": "HU", "intensity": "90", "latitudeNumeric": 35.0, "longitudeNumeric": -40.0},
        {"id": "al152026", "name": "Near", "classification": "TS", "intensity": "50", "latitudeNumeric": 16.0, "longitudeNumeric": -55.0,
         "lastUpdate": "2026-10-15T03:00:00.000Z", "forecastGraphics": {"url": "https://www.nhc.noaa.gov/graphics_at5.shtml"}},
        {"id": "al162026", "name": "Nearer", "classification": "TD", "intensity": "x", "latitudeNumeric": 17.0, "longitudeNumeric": -60.0},
    ]}
    storms = bulletins.nearby_storms((18.065, -63.07), 1500, fetch=lambda url: json.dumps(feed))
    assert [s["name"] for s in storms] == ["Nearer", "Near"]
    near = storms[1]
    assert near["kind"] == "TS" and near["intensity_kt"] == 50 and 850 < near["distance_km"] < 900
    assert near["url"].endswith("graphics_at5.shtml") and storms[0]["url"] == bulletins.NHC_PAGE and storms[0]["intensity_kt"] is None


def test_output_carries_links_and_context():
    region = run.load_region("sxm")
    bbox, now = region["bbox"], dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc)
    inputs = (sample.afai_grid(bbox), sample.currents_grid(bbox), sample.land_grid(bbox), [])
    context = {"usf": {"url": "https://x.org/b.pdf", "month": "2026-09"}, "storms": {"checked": "t", "radius_km": 1500, "active": []}}
    out = run.build(region, *inputs, False, now, context=context)
    assert out["context"] == context
    links = out["region"]["links"]
    assert [b["id"] for b in links["bulletins"]] == ["meteofrance", "sir", "usf", "cermes"]
    assert {w.get("side") for w in links["warnings"]} == {"FR", "NL", None} and links["emergency"][1]["numbers"][0]["n"] == "912"
    assert run.build(region, *inputs, True, now)["context"] == {"usf": None, "storms": None}


def test_context_failures_become_notes(monkeypatch):
    def down(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(bulletins, "latest_usf", down)
    monkeypatch.setattr(bulletins, "nearby_storms", down)
    context, notes = run.fetch_context(run.load_region("sxm"), dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc), lambda m: None)
    assert context == {"usf": None, "storms": None} and len(notes) == 2 and "no storm banner" in notes[1]
