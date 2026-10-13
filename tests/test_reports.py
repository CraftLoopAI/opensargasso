"""Sighting dates: the island's day, and dates that cannot be right."""
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
