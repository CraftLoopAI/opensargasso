"""GFS 10 m wind from a THREDDS server's OPeNDAP text service (UCAR Unidata). Standard library only.

The ERDDAP copies of GFS all come from PacIOOS and go down together; UCAR
decodes GFS itself, so it is an independent source. OPeNDAP's ASCII service
returns arrays as text. The dataset description (DDS) names the time and
height dimensions of the wind, and its attributes (DAS) give the time units,
whose reference date moves as the rolling collection advances, so both are
read on every run.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from . import erddap

U = "u-component_of_wind_height_above_ground"
V = "v-component_of_wind_height_above_ground"
STEP = 0.5  # degrees, the Global_0p5deg grid


def fetch_wind_series(source: dict, bbox: dict, start: str, end: str = "last", days: float = 8,
                      fetch=erddap.fetch_text) -> list:
    """3-hourly Grids of ugrd10m and vgrd10m over `bbox`, from the step at or before `start`
    to `end` (an ISO time) or, with "last", `days` later. Oldest first, both axes ascending,
    longitude -180 to 180, as erddap.parse_series returns them."""
    base = source["url"]
    found = re.search(rf"Float32 {re.escape(U)}\[(\w+) = \d+\]\[(\w+) = \d+\]\[lat = \d+\]\[lon = \d+\]", fetch(base + ".dds"))
    if not found:
        raise RuntimeError("the dataset description has no 10 m wind on a lat/lon grid")
    tdim, hdim = found.groups()
    since = time_reference(fetch(base + ".das"), tdim)
    axes = parse_ascii(fetch(f"{base}.ascii?{urllib.parse.quote(f'{tdim},{hdim},lat,lon')}"))
    times = [since + dt.timedelta(hours=h) for h in axes[tdim]]
    t_start = erddap_time(start)
    t_end = t_start + dt.timedelta(days=days) if end == "last" else erddap_time(end)
    if not times or times[0] > t_start or times[-1] < t_start:
        raise RuntimeError(f"the forecast runs {times[0]:%Y-%m-%dT%H:%MZ} to {times[-1]:%Y-%m-%dT%H:%MZ}, not from {start}")
    t0 = max(k for k, t in enumerate(times) if t <= t_start)
    t1 = max(k for k, t in enumerate(times) if t <= t_end)
    if 10.0 not in axes[hdim]:
        raise RuntimeError(f"no 10 m level among heights {axes[hdim]}")
    h = axes[hdim].index(10.0)
    west, east = bbox["west"] % 360, bbox["east"] % 360
    if west > east:
        raise ValueError("a box crossing 0 degrees longitude is not supported")
    rows = [i for i, lat in enumerate(axes["lat"]) if bbox["south"] - 1e-6 <= lat <= bbox["north"] + 1e-6]
    cols = [j for j, lon in enumerate(axes["lon"]) if west - 1e-6 <= lon <= east + 1e-6]
    if not rows or not cols:
        raise RuntimeError("the box is outside the grid")
    pick = f"[{t0}:1:{t1}][{h}:1:{h}][{rows[0]}:1:{rows[-1]}][{cols[0]}:1:{cols[-1]}]"
    data = parse_ascii(fetch(f"{base}.ascii?{urllib.parse.quote(f'{U}{pick},{V}{pick}')}"))
    lats, lons = [axes["lat"][i] for i in rows], [axes["lon"][j] for j in cols]
    order = sorted(range(len(lats)), key=lambda i: lats[i])                # ascending, as Grid expects
    series = []
    for k in range(t1 - t0 + 1):
        block = lambda name: [data[f"{name}.{name}"][k * len(lats) + i] for i in order]  # noqa: E731
        series.append(erddap.Grid(sorted(lats), [x - 360 if x > 180 else x for x in lons],
                                  {"ugrd10m": block(U), "vgrd10m": block(V)},
                                  time=times[t0 + k].strftime("%Y-%m-%dT%H:%M:%SZ")))
    return series


def time_reference(das: str, tdim: str) -> dt.datetime:
    """The datetime that the hours of `tdim` count from, from the attribute text."""
    block = re.search(rf"^\s*{re.escape(tdim)} {{(.*?)^\s*}}", das, flags=re.M | re.S)
    unit = re.search(r'String units "Hours? since (\S+?)Z?"', block.group(1)) if block else None
    if not unit:
        raise RuntimeError(f"no time units in hours for {tdim}")
    return dt.datetime.fromisoformat(unit.group(1)).replace(tzinfo=dt.timezone.utc)


def erddap_time(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def parse_ascii(text: str) -> dict:
    """{name: values} from an OPeNDAP ASCII response.

    1-D variables give a list of numbers; arrays give one list per row (the
    last dimension), in row order. Grid members are named "grid.member".
    """
    if text.lstrip().startswith("Error {"):
        raise RuntimeError(" ".join(text.split())[:300])
    body = re.split(r"\n-{10,}\n", text, maxsplit=1)[-1]                 # after the line of dashes
    out, name = {}, None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            name = None
            continue
        header = re.fullmatch(r"([\w.\-]+)((?:\[\d+\])+)", line)
        if header:
            name = header.group(1)
            out[name] = []
            continue
        if name is None:
            continue
        if line.startswith("["):                                          # "[t][h][i], v, v, ..." one row
            out[name].append([_num(v) for v in line.split(",")[1:]])
        else:                                                             # a 1-D variable's values
            out[name].extend(_num(v) for v in line.split(","))
    return out


def _num(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return erddap.NAN
