"""UCAR's OPeNDAP text service: dimension names from the description, moving time reference, box and order."""
import urllib.parse

import pytest

from pipeline import opendap, sources

DDS = """Dataset {
    Grid {
     ARRAY:
        Float32 u-component_of_wind_height_above_ground[time = 4][height_above_ground2 = 7][lat = 4][lon = 4];
     MAPS:
        Float64 time[time = 4];
    } u-component_of_wind_height_above_ground;
} grib/NCEP/GFS/Global_0p5deg/Best;"""
DAS = """Attributes {
    time {
        String units "Hour since 2026-09-15T00:00:00Z";
        String _CoordinateAxisType "Time";
    }
    time1 {
        String units "Hour since 2026-01-01T00:00:00Z";
    }
}"""
AXES = """Dataset {
    Float64 time[time = 4];
} grib/NCEP/GFS/Global_0p5deg/Best;
---------------------------------------------
time[4]
696.0, 699.0, 702.0, 705.0

height_above_ground2[7]
10.0, 20.0, 30.0, 40.0, 50.0, 80.0, 100.0

lat[4]
21.0, 20.5, 20.0, 19.5

lon[4]
293.5, 294.0, 294.5, 295.0
"""
U, V = opendap.U, opendap.V
DATA = f"""Dataset {{
}} grib/NCEP/GFS/Global_0p5deg/Best;
---------------------------------------------
{U}.{U}[2][1][2][2]
[0][0][0], -6.2, -5.8
[0][0][1], -4.8, -5.1
[1][0][0], -6.0, -5.6
[1][0][1], -4.6, NaN

{U}.time[2]
699.0, 702.0

{V}.{V}[2][1][2][2]
[0][0][0], 0.7, 1.3
[0][0][1], 0.6, 1.4
[1][0][0], 0.5, 1.2
[1][0][1], 0.4, 1.1
"""
BBOX = {"west": -66.0, "east": -65.4, "south": 19.9, "north": 20.6}


def fake_server(asked):
    def fetch(url):
        asked.append(urllib.parse.unquote(url))
        if url.endswith(".dds"):
            return DDS
        if url.endswith(".das"):
            return DAS
        return AXES if "height_above_ground2,lat,lon" in asked[-1] else DATA
    return fetch


def test_reads_the_box_from_the_named_dimensions_with_the_moving_reference():
    asked = []
    s = opendap.fetch_wind_series(sources.WIND_UCAR, BBOX, "2026-10-14T03:00:00Z", end="2026-10-14T06:00:00Z", fetch=fake_server(asked))
    assert f"{U}[1:1:2][0:1:0][1:1:2][1:1:2],{V}[1:1:2][0:1:0][1:1:2][1:1:2]" in asked[-1]   # 10 m, 2 times, 2 x 2 cells
    assert [g.time for g in s] == ["2026-10-14T03:00:00Z", "2026-10-14T06:00:00Z"]           # 699 h after 15 September
    assert s[0].lats == [20.0, 20.5] and s[0].lons == [-66.0, -65.5]                         # ascending, -180..180
    assert s[0].value("ugrd10m", -66.0, 20.5) == -6.2 and s[0].value("ugrd10m", -66.0, 20.0) == -4.8
    assert s[1].value("vgrd10m", -65.5, 20.0) == 1.1
    assert s[1].value("ugrd10m", -65.5, 20.0) != s[1].value("ugrd10m", -65.5, 20.0)          # NaN stays missing


def test_refuses_a_start_outside_the_forecast_and_server_errors():
    with pytest.raises(RuntimeError, match="not from 2026-09-01"):
        opendap.fetch_wind_series(sources.WIND_UCAR, BBOX, "2026-09-01T00:00:00Z", fetch=fake_server([]))
    with pytest.raises(RuntimeError, match="Implementation limitation"):
        opendap.parse_ascii('Error {\n    code = 0;\n    message = "Implementation limitation: multiple references";\n};')
    assert opendap.time_reference(DAS, "time1").isoformat() == "2026-01-01T00:00:00+00:00"
