"""Minimal ERDDAP griddap client. Standard library only.

ERDDAP serves gridded data as plain CSV, so no netCDF stack is needed.
"""
from __future__ import annotations

import csv
import io
import math
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "opensargasso/0.1 (open sargassum monitoring)"
NAN = float("nan")


@dataclass
class Grid:
    """A regular lat/lon grid. Both axes are stored ascending."""

    lats: list
    lons: list
    data: dict
    time: str | None = None

    @property
    def dlat(self) -> float:
        return (self.lats[-1] - self.lats[0]) / (len(self.lats) - 1) if len(self.lats) > 1 else 1.0

    @property
    def dlon(self) -> float:
        return (self.lons[-1] - self.lons[0]) / (len(self.lons) - 1) if len(self.lons) > 1 else 1.0

    def index(self, lon: float, lat: float):
        """Nearest cell (i, j), or None when the point is outside the grid."""
        i = round((lon - self.lons[0]) / self.dlon)
        j = round((lat - self.lats[0]) / self.dlat)
        if 0 <= i < len(self.lons) and 0 <= j < len(self.lats):
            return i, j
        return None

    def value(self, var: str, lon: float, lat: float) -> float:
        ij = self.index(lon, lat)
        return NAN if ij is None else self.data[var][ij[1]][ij[0]]


def griddap_url(base, dataset, variables, bbox, time="last", stride=1, descending_lat=False):
    """Build a griddap CSV request for a bounding box.

    `time` is "last", an ISO timestamp, a (start, step, end) range where end
    may be "last", or None for datasets without a time axis.
    """
    south, north = bbox["south"], bbox["north"]
    lat = f"[({north}):{stride}:({south})]" if descending_lat else f"[({south}):{stride}:({north})]"
    lon = f"[({bbox['west']}):{stride}:({bbox['east']})]"
    if isinstance(time, tuple):
        t = f"[({time[0]}):{time[1]}:({time[2]})]"
    else:
        t = f"[({time})]" if time else ""
    query = ",".join(f"{v}{t}{lat}{lon}" for v in variables)
    return f"{base.rstrip('/')}/griddap/{dataset}.csv?" + urllib.parse.quote(query, safe="(),:.-_")


def dataset_page(source: dict) -> str:
    """The dataset's human-readable ERDDAP page, for links on the site."""
    return f"{source['base'].rstrip('/')}/griddap/{source['dataset']}.html"


def parse_csv(text: str, variables) -> Grid:
    """Parse ERDDAP griddap CSV (a names row, a units row, then data rows) for one time step."""
    return _to_grid(_read_rows(text, variables), variables)


def parse_series(text: str, variables) -> list:
    """Parse a griddap CSV that spans several time steps into one Grid per step, oldest first."""
    by_time = {}
    for row in _read_rows(text, variables):
        by_time.setdefault(row[0], []).append(row)
    return [_to_grid(by_time[t], variables) for t in sorted(by_time)]


def _read_rows(text: str, variables):
    """Rows of (time or None, lat, lon, [values])."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    next(reader)  # units row
    col = {name: k for k, name in enumerate(header)}
    for needed in ("latitude", "longitude", *variables):
        if needed not in col:
            raise ValueError(f"column '{needed}' missing from ERDDAP response: {header}")
    rows = [(row[col["time"]] if "time" in col else None, float(row[col["latitude"]]), float(row[col["longitude"]]),
             [_num(row[col[v]]) for v in variables]) for row in reader if row]
    if not rows:
        raise ValueError("ERDDAP response has no data rows")
    return rows


def _to_grid(rows, variables) -> Grid:
    when = rows[0][0]
    rows = [r[1:] for r in rows]
    lats = sorted({r[0] for r in rows})
    lons = sorted({r[1] for r in rows})
    jmap = {v: k for k, v in enumerate(lats)}
    imap = {v: k for k, v in enumerate(lons)}
    data = {v: [[NAN] * len(lons) for _ in lats] for v in variables}
    for lat, lon, vals in rows:
        j, i = jmap[lat], imap[lon]
        for v, x in zip(variables, vals):
            data[v][j][i] = x
    return Grid(lats=lats, lons=lons, data=data, time=when)


def _num(s: str) -> float:
    try:
        x = float(s)
    except ValueError:
        return NAN
    return x if math.isfinite(x) else NAN


def fetch_text(url: str, timeout: int = 180, retries: int = 3, backoff: float = 5.0) -> str:
    """GET a URL as text. Retries network and 5xx errors; 4xx errors raise at once."""
    return fetch_bytes(url, timeout, retries, backoff).decode("utf-8", errors="replace")


def fetch_bytes(url: str, timeout: int = 180, retries: int = 3, backoff: float = 5.0) -> bytes:
    """GET a URL. Retries network and 5xx errors; 4xx errors raise at once."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries - 1:
            _time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def fetch_grid(source: dict, bbox: dict, stride: int = 1, time="last", fetch=fetch_text) -> Grid:
    """Fetch one source for a bounding box.

    Latitude can be stored ascending or descending depending on the dataset,
    and ERDDAP rejects a request in the wrong order, so both are tried.
    """
    return _request(source, bbox, time if source.get("has_time", True) else None, stride, fetch, parse_csv)


def fetch_series(source: dict, bbox: dict, start: str, end: str = "last", time_step: int = 1,
                 stride: int = 1, fetch=fetch_text) -> list:
    """Fetch every `time_step`-th time step from `start` to `end` ("last" is the newest). Oldest first."""
    return _request(source, bbox, (start, time_step, end), stride, fetch, parse_series)


def _request(source, bbox, time, stride, fetch, parse):
    if source.get("lon360"):  # dataset stores longitude 0 to 360: ask in its terms, answer in +/-180
        bbox = {**bbox, "west": bbox["west"] % 360, "east": bbox["east"] % 360}
        if bbox["west"] > bbox["east"]:
            raise ValueError(f"{source['dataset']}: a box crossing 0 degrees longitude is not supported")
    error = None
    for descending in (False, True):
        url = griddap_url(source["base"], source["dataset"], source["variables"], bbox,
                          time=time, stride=stride, descending_lat=descending)
        try:
            result = parse(fetch(url), source["variables"])
        except urllib.error.HTTPError as e:
            error = e
            continue
        for g in result if isinstance(result, list) else [result]:
            if source.get("lon360"):
                g.lons = [x - 360 if x > 180 else x for x in g.lons]
        return result
    raise RuntimeError(f"ERDDAP rejected the request for {source['dataset']}: {error}")
