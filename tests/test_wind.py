"""Wind forecast: GFS time series from ERDDAP, nearest-step lookup, fallback, use in the drift."""
import datetime as dt
import pathlib

from pipeline import drift, erddap, run, sample, sources

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "wind.csv"
START = dt.datetime(2026, 10, 12, 12, tzinfo=dt.timezone.utc)
BBOX = {"west": -64.0, "east": -62.0, "south": 17.0, "north": 19.0}


def series():
    return erddap.parse_series(FIXTURE.read_text(), sources.WIND["variables"])


def test_series_url_asks_for_a_time_range():
    url = erddap.griddap_url("https://x.org/erddap", "ds", ["ugrd10m"], BBOX, time=("2026-10-12T12:00:00Z", 1, "last"))
    assert "ugrd10m%5B(2026-10-12T12:00:00Z):1:(last)%5D%5B(17.0):1:(19.0)%5D" in url


def test_parse_series_splits_time_steps():
    s = series()
    assert [g.time for g in s] == ["2026-10-12T12:00:00Z", "2026-10-12T15:00:00Z"]
    assert s[0].lats == [17.5, 18.0, 18.5]                    # stored north to south, sorted here
    assert s[0].value("ugrd10m", -63.0, 18.0) == -6.339717
    assert s[1].value("vgrd10m", -63.0, 18.0) == 0.29091796


def test_make_wind_uses_the_nearest_step_and_falls_back():
    wind = drift.make_wind(series(), START, fallback=(-1.0, -2.0))
    assert wind(-63.0, 18.0, 1) == (-6.339717, -0.93475586)     # nearer 12:00
    assert wind(-63.0, 18.0, 2) == (-6.3423977, 0.29091796)     # nearer 15:00
    assert wind(-63.0, 18.0, 90) == wind(-63.0, 18.0, 3)        # past the forecast: newest step
    assert wind(-63.0, 18.0, -6) == wind(-63.0, 18.0, 0)        # before it: oldest step
    assert wind(-60.0, 18.0, 0) == (-1.0, -2.0)                 # outside the grid
    assert drift.make_wind(None, START, (-1.0, -2.0))(-63.0, 18.0, 0) == (-1.0, -2.0)


def test_drift_follows_wind_that_turns():
    def wind(lon, lat, hours):
        return (10.0, 0.0) if hours < 24 else (-10.0, 0.0)
    track = drift.simulate([(-63.0, 18.0)], lambda lon, lat: (0.0, 0.0), lambda lon, lat: False, BBOX,
                           days=2, windage=0.02, wind=wind, diffusion_deg=0)[0]
    assert track[1][0] > -63.0 + 0.1                            # pushed east on day 1
    assert abs(track[2][0] + 63.0) < 1e-9                       # and back on day 2


def test_output_records_the_wind_source():
    region = run.load_region("sxm")
    bbox, now = region["bbox"], dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)
    inputs = (sample.afai_grid(bbox), sample.currents_grid(bbox), sample.land_grid(bbox), [])
    live = run.build(region, *inputs, False, now, wind=series())["sources"]["wind"]
    assert live["fallback"] is False and live["until"] == "2026-10-12T15:00:00Z" and live["url"].endswith("ncep_global_lon180.html")
    assert run.build(region, *inputs, False, now)["sources"]["wind"]["fallback"] is True


def test_lon360_source_is_asked_in_0_360_and_answers_in_pm180():
    asked = []
    csv = ("time,latitude,longitude,ugrd10m,vgrd10m\nUTC,degrees_north,degrees_east,m s-1,m s-1\n"
           "2026-10-12T12:00:00Z,18.0,296.5,-6.7,-0.2\n2026-10-12T12:00:00Z,18.0,297.0,-6.0,-0.8\n")

    def fake(url):
        asked.append(url)
        return csv

    source = {**sources.WIND_BACKUP}
    s = erddap.fetch_series(source, BBOX, start="2026-10-12T12:00:00Z", fetch=fake)
    assert "%5B(296.0):1:(298.0)%5D" in asked[0]                    # -64..-62 asked as 296..298
    assert s[0].lons == [-63.5, -63.0] and s[0].value("ugrd10m", -63.0, 18.0) == -6.0


def test_fetch_wind_falls_back_to_the_backup_server(monkeypatch):
    def fake(source, bbox, start, end="last"):
        if source is sources.WIND:
            raise RuntimeError("Currently unknown datasetID")
        return series()

    monkeypatch.setattr(erddap, "fetch_series", fake)
    used, got, problems = run.fetch_wind(BBOX, "2026-10-12T12:00:00Z")
    assert used is sources.WIND_BACKUP and len(got) == 2
    assert problems == ["ncep_global_lon180: Currently unknown datasetID"]


def test_fetch_wind_raises_when_no_server_answers(monkeypatch):
    def down(source, bbox, start, end="last"):
        raise RuntimeError("down")

    monkeypatch.setattr(erddap, "fetch_series", down)
    try:
        run.fetch_wind(BBOX, "2026-10-12T12:00:00Z")
    except RuntimeError as e:
        assert "ncep_global_lon180: down" in str(e) and "NCEP_Global_Best: down" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_output_names_the_backup_when_it_was_used():
    region = run.load_region("sxm")
    bbox, now = region["bbox"], dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)
    inputs = (sample.afai_grid(bbox), sample.currents_grid(bbox), sample.land_grid(bbox), [])
    w = run.build(region, *inputs, False, now, wind=series(), wind_from=sources.WIND_BACKUP)["sources"]["wind"]
    assert w["url"].endswith("/NCEP_Global_Best.html") and "backup" in w["name"] and w["fallback"] is False
