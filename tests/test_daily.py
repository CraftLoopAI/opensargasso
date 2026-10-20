"""The daily satellite images: read as OPeNDAP text, then used to date each detection of the 7-day composite."""
import datetime as dt
import math

import pytest

from pipeline import detect, erddap, run, sample, sources

NAN = float("nan")

# ERDDAP's .asc answer for a 2 x 3 box, cut from a real one; latitude asked north to south.
ASC = """Dataset {
  GRID {
    ARRAY:
      Float32 AFAI[time = 1][latitude = 2][longitude = 3];
    MAPS:
      Float64 time[time = 1];
      Float32 latitude[latitude = 2];
      Float32 longitude[longitude = 3];
  } AFAI;
} noaa_aoml_atlantic_oceanwatch_AFAI_1D;
---------------------------------------------
AFAI.AFAI[1][2][3]
[0][0], -0.001464, NaN, -0.001438
[0][1], -0.001515, -0.001438, 0.002107

AFAI.time[1]
1.7924112E9

AFAI.latitude[2]
17.012238, 16.997236

AFAI.longitude[3]
-63.005, -62.99, -62.975
"""


def test_asc_answer_reads_like_the_csv_one():
    g = erddap.parse_asc(ASC, ["AFAI"])
    assert g.time == "2026-10-19T12:00:00Z"
    assert g.lats == [16.997236, 17.012238]                     # stored ascending, rows turned with them
    assert g.data["AFAI"][0] == [-0.001515, -0.001438, 0.002107]
    assert math.isnan(g.data["AFAI"][1][1])
    url = erddap.griddap_url("https://x.org/erddap", "ds", ["AFAI"], {"west": -63, "east": -62, "south": 17, "north": 18}, fmt="asc")
    assert url.startswith("https://x.org/erddap/griddap/ds.asc?AFAI")


def test_asc_answer_with_more_than_one_time_step_is_refused():
    two = ASC.replace("AFAI.AFAI[1][2][3]", "AFAI.AFAI[2][2][3]").replace("\n\nAFAI.time", "\n[1][0], 1, 2, 3\n[1][1], 1, 2, 3\n\nAFAI.time")
    with pytest.raises(ValueError, match="one time step"):
        erddap.parse_asc(two, ["AFAI"])


def grid(values, time=None):
    return erddap.Grid([18.0, 18.015], [-63.0, -62.985], {"AFAI": values}, time=time)


def test_each_detection_is_dated_by_the_day_its_value_came_from():
    daily = [grid([[0.001, NAN], [NAN, 0.003]]),     # the composite's day
             grid([[0.002, 0.004], [NAN, 0.003]]),   # one day before
             grid([[0.002, NAN], [NAN, NAN]])]       # two days before
    week = grid([[0.002, 0.004], [0.005, 0.003]])    # the highest of each pixel; 0.005 is in no daily image
    found = [(-63.0, 18.0, 1.0), (-62.985, 18.0, 1.0), (-63.0, 18.015, 1.0), (-62.985, 18.015, 1.0)]
    assert detect.seen_days(found, week, daily) == [1, 1, None, 0]   # 0.002 on days 1 and 2: the newer wins


def test_daily_images_must_be_the_days_asked_for(monkeypatch):
    composite = grid([[0.0, 0.0], [0.0, 0.0]], time="2026-10-19T12:00:00Z")
    asked = []

    def answer(source, bbox, stride, time, fetch, fmt):
        asked.append((source["dataset"], time, fmt))
        return grid([[0.0, 0.0], [0.0, 0.0]], time=time)
    monkeypatch.setattr(run.erddap, "fetch_grid", answer)
    days = run.fetch_daily({}, composite, 1)
    assert [g.time[:10] for g in days] == ["2026-10-19", "2026-10-18", "2026-10-17", "2026-10-16",
                                           "2026-10-15", "2026-10-14", "2026-10-13"]
    assert {(a[0], a[2]) for a in asked} == {(sources.AFAI_DAILY["dataset"], "asc")}

    def missing_day(source, bbox, stride, time, fetch, fmt):  # ERDDAP gives the nearest day it has
        return grid([[0.0, 0.0], [0.0, 0.0]], time="2026-10-18T12:00:00Z" if time.startswith("2026-10-17") else time)
    monkeypatch.setattr(run.erddap, "fetch_grid", missing_day)
    with pytest.raises(ValueError, match="no daily image for 2026-10-17"):
        run.fetch_daily({}, composite, 1)


def test_published_detections_carry_the_day_they_were_seen():
    region = run.load_region("sxm")
    afai, currents, land = sample.afai_grid(region["bbox"]), sample.currents_grid(region["bbox"]), sample.land_grid(region["bbox"])
    now = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc)
    unknown = run.build(region, afai, currents, land, [], True, now)["detections"]
    assert {len(d) for d in unknown} == {4} and {d[3] for d in unknown} == {None}   # no daily images: no dates
    seen = run.build(region, afai, currents, land, [], True, now, daily=[afai])["detections"]
    assert {d[3] for d in seen} == {0}                          # every value is in the newest image
