"""Daily job: fetch, detect, forecast drift, grade sites, write JSON for the site.

    python -m pipeline.run --region sxm            # live data
    python -m pipeline.run --region sxm --sample   # synthetic data, no network
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import sys

from . import __version__, detect, drift, erddap, landmask, risk, sample, sources

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_region(region_id: str) -> dict:
    path = ROOT / "regions" / f"{region_id}.json"
    if not path.exists():
        raise SystemExit(f"unknown region '{region_id}': {path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def age_days(stamp: str | None, now: dt.datetime):
    if not stamp or stamp == "sample":
        return None
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - when).days


def fetch_inputs(region: dict, cache_dir: pathlib.Path, log):
    """Live inputs. AFAI is required; currents and land degrade gracefully."""
    bbox, notes = region["bbox"], []
    afai = erddap.fetch_grid(sources.AFAI, bbox, stride=region["afai"]["stride"])
    try:
        currents = erddap.fetch_grid(sources.CURRENTS, bbox)
    except Exception as e:  # noqa: BLE001 - any failure here has the same fallback
        currents = None
        notes.append(f"currents unavailable ({e}); used the region's fallback current")
        log(notes[-1])
    land_cache = cache_dir / f"land-{region['id']}.json"
    land = None
    try:
        if region.get("land_mask"):  # coastline mask stored in the repo: no download
            land = landmask.load(ROOT / "regions" / region["land_mask"])
        elif land_cache.exists():
            land = erddap.Grid(**json.loads(land_cache.read_text()))
        else:
            land = erddap.fetch_grid(sources.LAND, bbox)
            cache_dir.mkdir(parents=True, exist_ok=True)
            land_cache.write_text(json.dumps({"lats": land.lats, "lons": land.lons, "data": land.data}))
    except Exception as e:  # noqa: BLE001
        notes.append(f"land mask unavailable ({e}); particles cannot beach")
        log(notes[-1])
    return afai, currents, land, notes


def land_source(land) -> dict:
    if isinstance(land, landmask.LandMask):
        return {"name": land.name, "url": land.url}
    return {"name": sources.LAND["name"], "url": erddap.dataset_page(sources.LAND)}


def build(region: dict, afai, currents, land, notes, is_sample: bool, now: dt.datetime) -> dict:
    a, d = region["afai"], region["drift"]
    is_land = drift.make_land_test(land)
    cell = abs(afai.dlon)
    detections, stats = detect.detect(afai, a["threshold"], a["background_block_deg"],
                                      is_land=is_land, pixel_deg=cell / a["stride"])
    rng = random.Random(now.toordinal())
    seeds = drift.seed_particles(detections, d["max_particles"], rng, cell)
    tracks = drift.simulate(
        seeds, drift.make_velocity(currents, d["fallback_current_ms"]), is_land,
        region["bbox"], days=d["days"], step_hours=d["step_hours"], windage=d["windage"],
        wind=d["wind_ms"], diffusion_deg=d["diffusion_deg"], rng=rng)
    sites = risk.site_risk(tracks, region["sites"], region["risk"], d["days"])
    forecast = [[[round(tr[day][0], 3), round(tr[day][1], 3), tr[day][2]] for tr in tracks if tr[day][2] != drift.LEFT]
                for day in range(d["days"] + 1)]
    return {
        "version": __version__,
        "region": {k: region[k] for k in ("id", "name", "languages", "bbox", "view")},
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample": is_sample,
        "sources": {
            "afai": {"name": sources.AFAI["name"], "url": erddap.dataset_page(sources.AFAI),
                     "time": afai.time, "age_days": age_days(afai.time, now)},
            "currents": {"name": sources.CURRENTS["name"], "url": erddap.dataset_page(sources.CURRENTS),
                         "time": currents.time if currents else None,
                         "age_days": age_days(currents.time, now) if currents else None,
                         "fallback": currents is None},
            "wind": {"name": "constant trade wind from the region file", "ms": d["wind_ms"]},
            "land": {**land_source(land), "available": land is not None},
        },
        "notes": notes,
        "settings": {"threshold": a["threshold"], "background_block_deg": a["background_block_deg"],
                     "windage": d["windage"], "diffusion_deg": d["diffusion_deg"], "step_hours": d["step_hours"],
                     "days": d["days"], "max_particles": d["max_particles"], "radius_km": region["risk"]["radius_km"],
                     "risk": region["risk"], "cell_deg": round(cell, 4)},
        "stats": stats,
        "detections": [[round(lon, 3), round(lat, 3), round(x, 5)] for lon, lat, x in detections],
        "forecast": forecast,
        "sites": sites,
    }


def write_outputs(result: dict, out: pathlib.Path, now: dt.datetime) -> None:
    (out / "history").mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    day = now.strftime("%Y-%m-%d")
    summary = {"date": day, "sample": result["sample"], "afai_time": result["sources"]["afai"]["time"],
               "detected": result["stats"]["detected"], "sites": {s["id"]: s["risk"] for s in result["sites"]}}
    (out / "history" / f"{day}.json").write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    dates = sorted(p.stem for p in (out / "history").glob("20*.json"))
    (out / "history" / "index.json").write_text(json.dumps(dates), encoding="utf-8")
    reports = out / "reports.geojson"
    if not reports.exists():
        reports.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", default="sxm")
    p.add_argument("--out", default=str(ROOT / "site" / "data"))
    p.add_argument("--sample", action="store_true", help="use synthetic inputs, no network")
    args = p.parse_args(argv)
    log = lambda m: print(f"[opensargasso] {m}", file=sys.stderr)  # noqa: E731
    region = load_region(args.region)
    now = dt.datetime.now(dt.timezone.utc)
    if args.sample:
        bbox = region["bbox"]
        afai, currents, land, notes = sample.afai_grid(bbox), sample.currents_grid(bbox), sample.land_grid(bbox), \
            ["synthetic sample data, not an observation"]
    else:
        try:
            afai, currents, land, notes = fetch_inputs(region, ROOT / ".cache", log)
        except Exception as e:  # noqa: BLE001
            log(f"AFAI fetch failed, keeping the previous output: {e}")
            return 1
    result = build(region, afai, currents, land, notes, args.sample, now)
    write_outputs(result, pathlib.Path(args.out), now)
    log(f"{result['stats']['detected']} pixels flagged, {len(result['forecast'][0])} particles, "
        f"AFAI time {result['sources']['afai']['time']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
