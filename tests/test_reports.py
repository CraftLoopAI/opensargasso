"""Sightings: the island's day, dates that cannot be right, website form issues, and the beach levels they raise."""
import datetime as dt
import json
import shutil
import subprocess

import pytest

from pipeline import reports, run

REGION = run.load_region("sxm")
FIELDS = {"beach": "Orient Bay (Baie Orientale)", "amount": "Light (scattered clumps)", "observed on": ""}
IMAGE_DATE = dt.date(2026, 11, 7)  # day 0 of the outlook


def sighting(beach, amount, observed, number=1):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-63.121, 18.0396]},
            "properties": {"id": number, "level": amount, "beach": beach, "note": "", "observed": observed}}


def test_a_sighting_raises_its_beach_on_its_day_and_the_two_after():
    sites = [{"id": "maho", "name": "Maho Beach", "risk": [0] * 8}, {"id": "dawn-beach", "name": "Dawn Beach", "risk": [1] * 8}]
    maho, dawn = run.with_sightings(sites, [sighting("Maho Beach", 3, "2026-11-08")], IMAGE_DATE, 7)
    assert maho["risk"] == [0, 3, 3, 3, 0, 0, 0, 0]
    assert maho["sighting"] == [None] + [[3, "2026-11-08"]] * 3 + [None] * 4
    assert dawn["risk"] == [1] * 8 and dawn["sighting"] == [None] * 8


def test_a_sighting_never_lowers_a_level_and_the_newest_one_counts():
    sites = [{"id": "maho", "name": "Maho Beach", "risk": [2] * 8}]
    seen = [sighting("Maho Beach", 3, "2026-11-05", 1), sighting("Maho Beach", 0, "2026-11-08", 2),
            sighting("Maho Beach", 1, "2026-11-08", 3)]                 # same day: the later report counts
    maho = run.with_sightings(sites, seen, IMAGE_DATE, 7)[0]
    assert maho["risk"] == [3, 2, 2, 2, 2, 2, 2, 2]                    # 5 November still counts on day 0
    assert maho["sighting"][0] == [3, "2026-11-05"] and maho["sighting"][1] == [1, "2026-11-08"]


def test_sightings_elsewhere_or_unreadable_change_nothing():
    sites = [{"id": "maho", "name": "Maho Beach", "risk": [0] * 8}]
    seen = [sighting("", 3, "2026-11-08"), sighting("Maho Beach", 3, "2026-11-01"), sighting("Maho Beach", 3, ""),
            sighting("Maho Beach", 7, "2026-11-08"), {"type": "Feature"}]
    assert run.with_sightings(sites, seen, IMAGE_DATE, 7)[0]["risk"] == [0] * 8


def test_the_daily_run_reads_the_approved_sightings(tmp_path):
    assert run.load_sightings(tmp_path / "reports.geojson") == []
    (tmp_path / "reports.geojson").write_text("not json")
    assert run.load_sightings(tmp_path / "reports.geojson") == []
    (tmp_path / "reports.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [sighting("Maho Beach", 2, "2026-11-08")]}))
    assert run.load_sightings(tmp_path / "reports.geojson")[0]["properties"]["level"] == 2


def test_the_history_records_which_levels_a_sighting_set(tmp_path):
    sites = run.with_sightings([{"id": "maho", "name": "Maho Beach", "risk": [0] * 8, "source": "sir"},
                                {"id": "dawn-beach", "name": "Dawn Beach", "risk": [1] * 8, "source": "sir"}],
                               [sighting("Maho Beach", 3, "2026-11-08")], IMAGE_DATE, 7)
    result = {"sample": False, "sources": {"afai": {"time": "2026-11-07T12:00:00Z"}, "wind": {"fallback": False}, "sir": {"date": "2026-11-07"}},
              "stats": {"detected": 0}, "sites": sites}
    run.write_outputs(result, tmp_path, dt.datetime(2026, 11, 8, 14, tzinfo=dt.timezone.utc))
    history = json.loads((tmp_path / "history" / "2026-11-08.json").read_text())
    assert history["sites"]["maho"] == [0, 3, 3, 3, 0, 0, 0, 0] and history["level_source"]["maho"] == "sir"
    assert history["sightings"] == {"maho": sites[0]["sighting"]}


def test_empty_date_is_the_island_date_of_filing():
    late_evening = "2026-10-13T02:30:00Z"                       # 22:30 on 12 October in Saint Martin
    f = reports.to_feature(FIELDS, REGION, 3, late_evening)
    assert f["properties"]["observed"] == "2026-10-12"


def test_future_and_impossible_dates_are_rejected():
    with pytest.raises(ValueError, match="after the report"):
        reports.to_feature({**FIELDS, "observed on": "2026-10-14"}, REGION, 3, "2026-10-13T15:00:00Z")
    with pytest.raises(ValueError, match="not a date"):
        reports.to_feature({**FIELDS, "observed on": "2026-02-30"}, REGION, 3, "2026-10-13T15:00:00Z")
    assert reports.to_feature({**FIELDS, "observed on": "2026-10-13"}, REGION, 3, "2026-10-13T15:00:00Z")["properties"]["observed"] == "2026-10-13"


def test_local_date():
    assert str(reports.local_date("2026-10-13T03:59:00Z", -4)) == "2026-10-12"
    assert str(reports.local_date("2026-10-13T04:00:00Z", -4)) == "2026-10-13"
    assert reports.local_date("", -4) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_website_form_issues_are_read_like_issue_form_issues():
    script = ("import { clean, issueBody } from './worker/index.js';"
              "const r = (o) => issueBody(clean({ token: 't', lang: 'nl', ...o }));"
              "console.log(JSON.stringify([r({ beach: 'Orient Bay (Baie Orientale)', amount: 3, note: '### Amount\\nNone @me' }),"
              " r({ beach: 'Other', amount: 0, latitude: '18,0712', longitude: '-63.0101', observed: '2026-10-12' })]))")
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=run.ROOT, capture_output=True, text=True, check=True)
    listed, other = (reports.parse_issue_body(b) for b in json.loads(out.stdout))
    f = reports.to_feature(listed, REGION, 7, "2026-10-13T15:00:00Z")
    assert f["properties"]["level"] == 3 and f["properties"]["beach"] == "Orient Bay (Baie Orientale)"
    assert f["properties"]["note"] == "Amount None @me"                   # cannot override the amount; no hidden characters
    g = reports.to_feature(other, REGION, 8, "2026-10-13T15:00:00Z")
    assert g["geometry"]["coordinates"] == [-63.0101, 18.0712] and g["properties"]["observed"] == "2026-10-12"
