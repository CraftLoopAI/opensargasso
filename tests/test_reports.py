"""Sightings: the island's day, dates that cannot be right, and website form issues."""
import json
import shutil
import subprocess

import pytest

from pipeline import reports, run

REGION = run.load_region("sxm")
FIELDS = {"beach": "Orient Bay (Baie Orientale)", "amount": "Light (scattered clumps)", "observed on": ""}


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
