"""Land mask from OpenStreetMap coastlines. Standard library only.

The daily job only loads the stored mask (regions/land/<id>.json). Build or
refresh it, rarely, with:

    python -m pipeline.landmask --region sxm

That downloads coastline ways from the Overpass API in 1-degree tiles, joins
them into closed islands and fills them into a grid of about 220 m.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import pathlib
import shutil
import time
import urllib.error
import urllib.parse
import zlib

from . import erddap, sources

STEP_DEG = 0.002     # grid cell, about 220 m; ETOPO1 is 1.8 km
MARGIN_DEG = 1.5     # islands cut by the region edge must still be complete in the download


class LandMask:
    """A land/sea bitmap. Cell (i, j) covers [west + i*step, west + (i+1)*step) and the same in latitude."""

    def __init__(self, west, south, step, cols, rows, bits, name="", url=""):
        self.west, self.south, self.step, self.cols, self.rows = west, south, step, cols, rows
        self.bits, self.name, self.url = bits, name, url

    def is_land(self, lon: float, lat: float) -> bool:
        i = math.floor((lon - self.west) / self.step)
        j = math.floor((lat - self.south) / self.step)
        if 0 <= i < self.cols and 0 <= j < self.rows:
            k = j * self.cols + i
            return bool(self.bits[k >> 3] >> (k & 7) & 1)
        return False

    def to_json(self, **meta) -> dict:
        return {**meta, "name": self.name, "url": self.url, "west": self.west, "south": self.south,
                "step": self.step, "cols": self.cols, "rows": self.rows,
                "bits": base64.b64encode(zlib.compress(bytes(self.bits), 9)).decode("ascii")}

    @classmethod
    def from_json(cls, d: dict) -> "LandMask":
        return cls(d["west"], d["south"], d["step"], d["cols"], d["rows"],
                   zlib.decompress(base64.b64decode(d["bits"])), d.get("name", ""), d.get("url", ""))


def load(path: pathlib.Path) -> LandMask:
    return LandMask.from_json(json.loads(path.read_text(encoding="utf-8")))


def join_rings(ways):
    """Join coastline ways into closed rings by their end nodes.

    `ways` is a list of (node_ids, points). Direction is ignored, so a reversed
    way still joins; the fill below does not depend on orientation.
    Returns (rings, open_chains), both lists of [(lon, lat), ...].
    """
    ends = {}
    for k, (ids, _) in enumerate(ways):
        ends.setdefault(ids[0], []).append(k)
        ends.setdefault(ids[-1], []).append(k)
    used, rings, chains = set(), [], []
    for start in range(len(ways)):
        if start in used:
            continue
        used.add(start)
        first, last = ways[start][0][0], ways[start][0][-1]
        pts = list(ways[start][1])
        while last != first:
            nxt = next((k for k in ends.get(last, []) if k not in used), None)
            if nxt is None:
                break
            used.add(nxt)
            ids, way_pts = ways[nxt]
            if ids[0] == last:
                pts.extend(way_pts[1:]); last = ids[-1]
            else:
                pts.extend(list(reversed(way_pts))[1:]); last = ids[0]
        (rings if last == first else chains).append(pts)
    return rings, chains


def rasterize(rings, west, south, step, cols, rows) -> bytearray:
    """Fill rings into a bitmap with the even-odd rule, sampling cell centers."""
    crossings = [[] for _ in range(rows)]
    east, north = west + cols * step, south + rows * step
    for ring in rings:
        lons, lats = [p[0] for p in ring], [p[1] for p in ring]
        if max(lons) < west or min(lons) > east or max(lats) < south or min(lats) > north:
            continue
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            if y0 == y1:
                continue
            lo, hi = min(y0, y1), max(y0, y1)
            j0 = max(0, math.ceil((lo - south) / step - 0.5))
            j1 = min(rows, math.ceil((hi - south) / step - 0.5))  # rows whose center lies in [lo, hi)
            for j in range(j0, j1):
                yc = south + (j + 0.5) * step
                crossings[j].append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
    bits = bytearray((cols * rows + 7) // 8)
    for j, xs in enumerate(crossings):
        xs.sort()
        for xa, xb in zip(xs[::2], xs[1::2]):
            i0 = max(0, math.ceil((xa - west) / step - 0.5))
            i1 = min(cols, math.ceil((xb - west) / step - 0.5))
            for i in range(i0, i1):
                k = j * cols + i
                bits[k >> 3] |= 1 << (k & 7)
    return bits


# Small declared limits: a busy Overpass server admits these at once and answers
# 504 to queries that ask for long timeouts or the default memory.
QUERY = '[out:json][timeout:30][maxsize:33554432];way["natural"="coastline"]({s},{w},{n},{e});out body geom;'
MIN_TILE_DEG = 0.125


class TileTooBig(Exception):
    """The tile has more coastline than the small limits allow."""


def fetch_coastline(box, cache_dir: pathlib.Path | None = None, log=print, pause=2.0, server=None):
    """Coastline ways overlapping `box`, fetched tile by tile. Returns {way_id: (node_ids, points)}.

    A tile that is too big for the query limits is split into quarters. With
    `cache_dir`, each finished tile is saved, so an interrupted build resumes.
    """
    ways = {}
    todo = [(lat, lon, 1.0) for lat in range(math.floor(box["south"]), math.ceil(box["north"]))
            for lon in range(math.floor(box["west"]), math.ceil(box["east"]))]
    while todo:
        lat, lon, size = todo.pop(0)
        cached = cache_dir / f"{lat:g}_{lon:g}_{size:g}.json" if cache_dir else None
        if cached and cached.exists():
            data = json.loads(cached.read_text())
        else:
            try:
                data = _overpass(QUERY.format(s=lat, w=lon, n=lat + size, e=lon + size), server)
            except TileTooBig:
                if size / 2 < MIN_TILE_DEG:
                    raise
                h = size / 2
                todo[:0] = [(lat, lon, h), (lat, lon + h, h), (lat + h, lon, h), (lat + h, lon + h, h)]
                log(f"tile {lat:g},{lon:g} ({size:g} deg) too big, splitting")
                continue
            if cached:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(data))
            time.sleep(pause)
        for el in data.get("elements", []):
            if el.get("type") == "way" and el.get("geometry"):
                ways[el["id"]] = (el["nodes"], [(g["lon"], g["lat"]) for g in el["geometry"]])
        log(f"tile {lat:g},{lon:g} ({size:g} deg): {len(ways)} ways so far")
    return ways


def _overpass(query: str, server: str | None = None, attempts: int = 6) -> dict:
    url = (server or sources.COAST["overpass"]) + "?" + urllib.parse.urlencode({"data": query})
    for attempt in range(attempts):
        try:
            data = json.loads(erddap.fetch_text(url, timeout=90, retries=1))
        except (urllib.error.HTTPError, RuntimeError) as e:
            # fetch_text raises RuntimeError for 5xx and network errors, HTTPError for 4xx.
            busy = isinstance(e, RuntimeError) or e.code == 429
            if not busy or attempt == attempts - 1:
                raise
            time.sleep(20 * (attempt + 1))  # busy or rate limited: wait for a free slot
            continue
        remark = data.get("remark", "")
        if "out of memory" in remark or "timed out" in remark:
            raise TileTooBig(remark)
        if "runtime error" in remark:
            raise RuntimeError(f"Overpass: {remark}")
        return data
    raise RuntimeError("Overpass: no answer")


def build(region: dict, step=STEP_DEG, margin=MARGIN_DEG, cache_dir=None, server=None, log=print) -> LandMask:
    bbox = region["bbox"]
    box = {"west": bbox["west"] - margin, "east": bbox["east"] + margin,
           "south": bbox["south"] - margin, "north": bbox["north"] + margin}
    rings, chains = join_rings(list(fetch_coastline(box, cache_dir, log, server=server).values()))
    for pts in chains:  # an unclosed coastline that reaches into the region would leave a hole in the mask
        lons, lats = [p[0] for p in pts], [p[1] for p in pts]
        if not (max(lons) < bbox["west"] or min(lons) > bbox["east"] or max(lats) < bbox["south"] or min(lats) > bbox["north"]):
            raise SystemExit(f"an island crossing the region is not closed in the download; retry with --margin above {margin}")
    cols = round((bbox["east"] - bbox["west"]) / step)
    rows = round((bbox["north"] - bbox["south"]) / step)
    log(f"{len(rings)} closed rings, {len(chains)} open outside the region; filling {cols} x {rows} cells")
    return LandMask(bbox["west"], bbox["south"], step, cols, rows, rasterize(rings, bbox["west"], bbox["south"], step, cols, rows),
                    name=sources.COAST["name"], url=sources.COAST["url"])


def main(argv=None) -> int:
    from .run import ROOT, load_region
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", default="sxm")
    p.add_argument("--step", type=float, default=STEP_DEG)
    p.add_argument("--margin", type=float, default=MARGIN_DEG)
    p.add_argument("--overpass", default=sources.COAST["overpass"], help="Overpass API endpoint, if the default is busy")
    args = p.parse_args(argv)
    region = load_region(args.region)
    out = ROOT / "regions" / region.get("land_mask", f"land/{args.region}.json")
    cache_dir = ROOT / ".cache" / "coast"
    mask = build(region, args.step, args.margin, cache_dir=cache_dir, server=args.overpass)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"source": "OpenStreetMap natural=coastline via the Overpass API",
            "license": "ODbL 1.0, (c) OpenStreetMap contributors", "built": dt.date.today().isoformat()}
    out.write_text(json.dumps(mask.to_json(**meta)), encoding="utf-8")
    shutil.rmtree(cache_dir, ignore_errors=True)  # tiles only serve to resume this build, never a later one
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
