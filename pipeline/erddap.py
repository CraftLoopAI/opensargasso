"""Minimal ERDDAP griddap client. Standard library only.

ERDDAP serves gridded data as plain text, CSV or OPeNDAP's ASCII form (.asc),
so no netCDF stack is needed. The .asc answer is about a fifth the size of the
CSV, with the same values.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import random
import re
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "opensargasso/0.1 (+https://github.com/CraftLoopAI/opensargasso)"
NAN = float("nan")
RETRY_WAITS = (20, 60, 120)  # seconds before each retry of a timeout, 429 or 5xx (plus jitter)


class HostBlocked(RuntimeError):
    """The server refused this client (HTTP 403), usually an IP block: skip the host for this run."""


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


def griddap_url(base, dataset, variables, bbox, time="last", stride=1, descending_lat=False, fmt="csv"):
    """Build a griddap request for a bounding box, as CSV or, with fmt="asc", OPeNDAP text.

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
    return f"{base.rstrip('/')}/griddap/{dataset}.{fmt}?" + urllib.parse.quote(query, safe="(),:.-_")


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


def parse_asc(text: str, variables) -> Grid:
    """Parse ERDDAP's OPeNDAP text answer (.asc) for one time step, like parse_csv."""
    a = parse_ascii(text)
    lats, lons = a[f"{variables[0]}.latitude"], a[f"{variables[0]}.longitude"]
    data = {}
    for v in variables:
        rows = a[f"{v}.{v}"]  # one row of longitudes per latitude
        if len(rows) != len(lats):
            raise ValueError(f"{v}: expected one time step of {len(lats)} rows, got {len(rows)}")
        data[v] = rows
    if len(lats) > 1 and lats[0] > lats[-1]:  # stored ascending, like parse_csv
        lats, data = lats[::-1], {v: rows[::-1] for v, rows in data.items()}
    seconds = a.get(f"{variables[0]}.time")
    when = dt.datetime.fromtimestamp(seconds[0], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if seconds else None
    return Grid(lats=lats, lons=lons, data=data, time=when)


def parse_ascii(text: str) -> dict:
    """{name: values} from an OPeNDAP ASCII response (THREDDS .ascii, ERDDAP .asc).

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


def _num(s: str) -> float:
    try:
        x = float(s)
    except ValueError:
        return NAN
    return x if math.isfinite(x) else NAN


def fetch_text(url: str, timeout: int = 90, waits=RETRY_WAITS, deadline: float | None = None, sleep=_time.sleep) -> str:
    """GET a URL as text; see fetch_bytes."""
    return fetch_bytes(url, timeout, waits, deadline, sleep).decode("utf-8", errors="replace")


def fetch_bytes(url: str, timeout: int = 90, waits=RETRY_WAITS, deadline: float | None = None, sleep=_time.sleep) -> bytes:
    """GET a URL.

    Timeouts, connection errors, HTTP 429 and 5xx are retried after each of
    `waits` seconds (longer if the server sends Retry-After), but not past
    `deadline` (a time.monotonic() value), and so is ERDDAP's 404 "Currently
    unknown datasetID", which it answers while it reloads a dataset. HTTP 403
    raises HostBlocked and other 4xx errors raise at once. Errors keep the start of the server's answer,
    which usually says why it refused.
    """
    last = None
    for attempt in range(len(waits) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            why = _answer(e)
            if e.code == 403:
                raise HostBlocked(f"HTTP 403 from {urllib.parse.urlsplit(url).netloc}: {why}") from None
            reloading = e.code == 404 and "Currently unknown datasetID" in why
            if e.code != 429 and e.code < 500 and not reloading:
                raise urllib.error.HTTPError(e.url, e.code, f"{e.reason} {why}".strip(), e.headers, None) from None
            last, wait_at_least = f"HTTP {e.code} {why}".strip(), _retry_after(e)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last, wait_at_least = e, 0
        if attempt == len(waits):
            break
        wait = max(waits[attempt], wait_at_least) * random.uniform(1.0, 1.25)
        if deadline is not None and _time.monotonic() + wait > deadline:
            break
        sleep(wait)
    raise RuntimeError(f"could not fetch {url}: {last}")


def _answer(e: urllib.error.HTTPError, limit: int = 300) -> str:
    """The first characters of an error response, on one line."""
    try:
        return " ".join(e.read(4096).decode("utf-8", "replace").split())[:limit]
    except Exception:  # noqa: BLE001 - the status code alone still says something
        return ""


def _retry_after(e: urllib.error.HTTPError) -> float:
    try:
        return min(float(e.headers.get("Retry-After", 0)), 300.0)
    except (TypeError, ValueError):
        return 0.0


def fetch_grid(source: dict, bbox: dict, stride: int = 1, time="last", fetch=fetch_text, fmt="csv") -> Grid:
    """Fetch one source for a bounding box, as CSV or, with fmt="asc", the smaller OPeNDAP text.

    Latitude can be stored ascending or descending depending on the dataset,
    and ERDDAP rejects a request in the wrong order: a source that records
    `lat_descending` is asked in that order only, otherwise both are tried.
    """
    return _request(source, bbox, time if source.get("has_time", True) else None, stride, fetch,
                    parse_asc if fmt == "asc" else parse_csv, fmt)


def fetch_series(source: dict, bbox: dict, start: str, end: str = "last", time_step: int = 1,
                 stride: int = 1, fetch=fetch_text) -> list:
    """Fetch every `time_step`-th time step from `start` to `end` ("last" is the newest). Oldest first."""
    return _request(source, bbox, (start, time_step, end), stride, fetch, parse_series)


def _request(source, bbox, time, stride, fetch, parse, fmt="csv"):
    if source.get("lon360"):  # dataset stores longitude 0 to 360: ask in its terms, answer in +/-180
        bbox = {**bbox, "west": bbox["west"] % 360, "east": bbox["east"] % 360}
        if bbox["west"] > bbox["east"]:
            raise ValueError(f"{source['dataset']}: a box crossing 0 degrees longitude is not supported")
    error = None
    for descending in [source["lat_descending"]] if "lat_descending" in source else (False, True):
        url = griddap_url(source["base"], source["dataset"], source["variables"], bbox,
                          time=time, stride=stride, descending_lat=descending, fmt=fmt)
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
