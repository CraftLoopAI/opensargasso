"""Daily job: fetch, detect, forecast drift, grade sites, write JSON for the site.

    python -m pipeline.run --region sxm            # live data
    python -m pipeline.run --region sxm --sample   # synthetic data, no network

Add --no-history for a local preview: it writes only latest.json, not the
day's history file, which the daily job commits.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import json
import math
import pathlib
import random
import sys
import time
import urllib.parse

from . import __version__, bulletins, detect, drift, erddap, landmask, opendap, risk, sample, sir, sources

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAP_PARTICLES = 2500  # particles published for the map; the counts use every simulated particle
WIND_BUDGET_S = 300   # per wind source, so a stuck server cannot use up the job's 30 minutes
CLOUD_RADIUS_KM = 150  # area around the island where cloud gaps matter for the next days
DAILY_BUDGET_S = 180   # for the seven daily satellite images that date the detections


def load_region(region_id: str) -> dict:
    path = ROOT / "regions" / f"{region_id}.json"
    if not path.exists():
        raise SystemExit(f"unknown region '{region_id}': {path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_time(stamp):
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def age_days(stamp: str | None, now: dt.datetime):
    when = parse_time(stamp)
    return None if when is None else (now - when).days


def fetch_wind(bbox: dict, start: str, end: str = "last"):
    """(source, series, problems) from the first wind source in sources.WINDS that answers.

    `problems` lists the sources that failed first; raises when none answers.
    Each source gets WIND_BUDGET_S seconds, retries included; a source that
    refuses this client (HTTP 403) is skipped at once.
    """
    problems = []
    for source in sources.WINDS:
        fetch = functools.partial(erddap.fetch_text, deadline=time.monotonic() + WIND_BUDGET_S)
        get = opendap.fetch_wind_series if source.get("kind") == "opendap" else erddap.fetch_series
        try:
            return source, get(source, bbox, start=start, end=end, fetch=fetch), problems
        except Exception as e:  # noqa: BLE001 - try the next server
            host = urllib.parse.urlsplit(source.get("base") or source["url"]).netloc
            problems.append(f"{source['dataset']} at {host}: {e}")
    raise RuntimeError("; ".join(problems))


def fetch_daily(bbox: dict, composite, stride: int) -> list:
    """The daily AFAI images behind the 7-day composite, newest first: [k] is from k days before it.

    Raises if one is missing: the map then shows every detection alike rather
    than date some of them wrongly.
    """
    end = parse_time(composite.time)
    fetch = functools.partial(erddap.fetch_text, deadline=time.monotonic() + DAILY_BUDGET_S)
    out = []
    for k in range(detect.COMPOSITE_DAYS):
        want = (end - dt.timedelta(days=k)).strftime("%Y-%m-%dT%H:%M:%SZ")
        grid = erddap.fetch_grid(sources.AFAI_DAILY, bbox, stride=stride, time=want, fetch=fetch, fmt="asc")
        if grid.time != want:  # ERDDAP answers with the nearest day it has
            raise ValueError(f"no daily image for {want[:10]}, nearest is {grid.time}")
        out.append(grid)
    return out


def source_page(source: dict) -> str:
    """A page about the dataset, for people."""
    return source.get("page") or erddap.dataset_page(source)


def save_wind(path: pathlib.Path, source: dict, series, now: dt.datetime) -> None:
    """Keep the last good forecast, for a day when every wind source fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "name": source["name"], "url": source_page(source), "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "series": [{"time": g.time, "lats": g.lats, "lons": g.lons, "data": g.data} for g in series]}), encoding="utf-8")


def load_wind(path: pathlib.Path, start: str):
    """(source, series) from the kept forecast if it still covers at least a day after `start`, else None.

    The drift uses the constant trade wind for hours past its end (drift.make_wind).
    """
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
        series = [erddap.Grid(g["lats"], g["lons"], g["data"], time=g["time"]) for g in kept["series"]]
        covered = parse_time(series[-1].time) - parse_time(start)
    except Exception:  # noqa: BLE001 - missing or unreadable: nothing to reuse
        return None
    if covered < dt.timedelta(days=1):
        return None
    return {"name": kept["name"], "url": kept["url"], "fetched": kept["fetched"]}, series


def fetch_inputs(region: dict, cache_dir: pathlib.Path, log, today: dt.date | None = None):
    """Live inputs. AFAI is required; the daily images, currents, wind, land and SIR degrade gracefully."""
    bbox, notes = region["bbox"], []
    afai = erddap.fetch_grid(sources.AFAI, bbox, stride=region["afai"]["stride"], fmt="asc")
    try:  # the day each detection was seen, so the map can tell recent sightings from older ones
        daily = fetch_daily(bbox, afai, region["afai"]["stride"])
    except Exception as e:  # noqa: BLE001
        daily = None
        notes.append(f"daily satellite images unavailable ({e}); the map shows every detection of the week alike")
        log(notes[-1])
    try:
        currents = erddap.fetch_grid(sources.CURRENTS, bbox)
    except Exception as e:  # noqa: BLE001 - any failure here has the same fallback
        currents = None
        notes.append(f"currents unavailable ({e}); used the region's fallback current")
        log(notes[-1])
    wind_kept = cache_dir / "wind" / f"{region['id']}.json"
    try:  # from day 0 (the satellite date) to the end of the newest forecast
        wind_from, wind, problems = fetch_wind(bbox, afai.time)
        for problem in problems:
            notes.append(f"wind source unavailable ({problem}); used {wind_from['name']}")
            log(notes[-1])
        save_wind(wind_kept, wind_from, wind, dt.datetime.now(dt.timezone.utc))
    except Exception as e:  # noqa: BLE001
        kept = load_wind(wind_kept, afai.time)
        wind_from, wind = kept if kept else (None, None)
        if kept:
            notes.append(f"wind forecast unavailable ({e}); reused the forecast fetched {wind_from['fetched']}, "
                         f"which runs to {wind[-1].time}, with the region's constant trade wind after that")
        else:
            notes.append(f"wind forecast unavailable ({e}); used the region's constant trade wind")
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
    try:
        day, segments = sir.fetch_latest(today or dt.datetime.now(dt.timezone.utc).date(), bbox)
        sir_levels = (day, sir.site_levels(region["sites"], segments))
    except Exception as e:  # noqa: BLE001
        sir_levels = None
        notes.append(f"NOAA SIR unavailable ({e}); beach levels come from the drift model")
        log(notes[-1])
    return afai, daily, currents, (wind_from, wind), land, sir_levels, notes


def land_source(land) -> dict:
    if isinstance(land, landmask.LandMask):
        return {"name": land.name, "url": land.url}
    return {"name": sources.LAND["name"], "url": erddap.dataset_page(sources.LAND)}


def fetch_context(region: dict, now: dt.datetime, log) -> tuple:
    """(context, notes): the newest USF outlook and nearby Atlantic storms. Failures only leave them out."""
    context, notes = {"usf": None, "storms": None}, []
    try:
        context["usf"] = bulletins.latest_usf(now.date())
    except Exception as e:  # noqa: BLE001
        notes.append(f"USF outlook check failed ({e})")
    radius = region.get("storm_radius_km", bulletins.STORM_RADIUS_KM)
    try:
        active = bulletins.nearby_storms(tuple(region["view"]["center"]), radius)
        context["storms"] = {"checked": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "radius_km": radius, "active": active}
    except Exception as e:  # noqa: BLE001
        notes.append(f"NHC storm data unavailable ({e}); no storm banner today")
    for note in notes:
        log(note)
    return context, notes


def cloud_share_near(grid, is_land, center: tuple, radius_km: float) -> dict:
    """Share of the sea within `radius_km` of `center` (lat, lon) that the satellite image left
    empty, mostly because of clouds. Sargassum there cannot be seen."""
    lat0, lon0 = center
    dlat = radius_km / 111.0
    dlon = dlat / max(0.1, math.cos(math.radians(lat0)))
    field, sea, gaps = grid.data["AFAI"], 0, 0
    for j, lat in enumerate(grid.lats):
        if abs(lat - lat0) > dlat:
            continue
        for i, lon in enumerate(grid.lons):
            if abs(lon - lon0) > dlon or risk.distance_km(lon, lat, lon0, lat0) > radius_km or is_land(lon, lat):
                continue
            sea += 1
            gaps += not math.isfinite(field[j][i])
    return {"radius_km": radius_km, "sea_cells": sea, "cloud_share": round(gaps / sea, 3) if sea else None}


def wind_source(wind, region: dict, wind_from: dict | None = None) -> dict:
    """Where the wind came from; `cached` holds the fetch time when an earlier run's forecast was reused."""
    if wind:
        wind_from = wind_from or sources.WIND
        out = {"name": wind_from["name"], "url": wind_from["url"] if wind_from.get("fetched") else source_page(wind_from),
               "time": wind[0].time, "until": wind[-1].time, "fallback": False}
        if wind_from.get("fetched"):
            out["cached"] = wind_from["fetched"]
        return out
    return {"name": "constant trade wind from the region file", "ms": region["drift"]["wind_ms"], "fallback": True}


def sir_source(sir_levels, now: dt.datetime) -> dict:
    base = {"name": sources.SIR["name"], "url": sources.SIR["page"]}
    if not sir_levels:
        return {**base, "fallback": True}
    day = sir_levels[0]
    return {**base, "date": day.isoformat(), "age_days": (now.date() - day).days, "fallback": False}


def beach_levels(model_sites, sir_levels, days: int):
    """Each beach shows the latest SIR level for every day (it beat our drift in the
    backtest); the drift model's own levels stay in `model` and fill in where SIR has none."""
    levels = sir_levels[1] if sir_levels else {}
    out = []
    for m in model_sites:
        level = levels.get(m["id"])
        out.append({**m, "model": m["risk"], "risk": [level] * (days + 1) if level is not None else m["risk"],
                    "source": "sir" if level is not None else "model"})
    return out


def build(region: dict, afai, currents, land, notes, is_sample: bool, now: dt.datetime, wind=None, sir_levels=None,
          wind_from=None, context=None, daily=None) -> dict:
    a, d = region["afai"], region["drift"]
    is_land = drift.make_land_test(land)
    cell = abs(afai.dlon)
    detections, stats = detect.detect(afai, a["threshold"], a["background_block_deg"],
                                      is_land=is_land, pixel_deg=cell / a["stride"])
    seen = detect.seen_days(detections, afai, daily) if daily else [None] * len(detections)
    rng = random.Random(now.toordinal())
    seeds = drift.seed_particles(detections, d["max_particles"], rng, cell)
    weight = sum(drift.seeds_for(x) for _, _, x in detections) / len(seeds) if seeds else 1.0
    stats = {**stats, "particle_weight": round(weight, 3),  # seeds per particle, to weight the counts
             "near": cloud_share_near(afai, is_land, tuple(region["view"]["center"]), region.get("cloud_radius_km", CLOUD_RADIUS_KM))}
    tracks = drift.simulate(
        seeds, drift.make_velocity(currents, d["fallback_current_ms"]), is_land,
        region["bbox"], days=d["days"], step_hours=d["step_hours"], windage=d["windage"],
        wind=drift.make_wind(wind, parse_time(afai.time) or now, d["wind_ms"]), diffusion_deg=d["diffusion_deg"], rng=rng)
    sites = beach_levels(risk.site_risk(tracks, region["sites"], region["risk"], d["days"], weight), sir_levels, d["days"])
    shown = tracks[::-(-len(tracks) // MAP_PARTICLES)] if tracks else []  # every k-th track, at most MAP_PARTICLES
    forecast = [[[round(tr[day][0], 3), round(tr[day][1], 3), tr[day][2]] for tr in shown if tr[day][2] != drift.LEFT]
                for day in range(d["days"] + 1)]
    return {
        "version": __version__,
        "region": {k: region[k] for k in ("id", "name", "languages", "bbox", "view", "links") if k in region},
        "context": context or {"usf": None, "storms": None},  # official outlook and nearby storms, for the site
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample": is_sample,
        "sources": {
            "afai": {"name": sources.AFAI["name"], "url": erddap.dataset_page(sources.AFAI),
                     "time": afai.time, "age_days": age_days(afai.time, now)},
            "currents": {"name": sources.CURRENTS["name"], "url": erddap.dataset_page(sources.CURRENTS),
                         "time": currents.time if currents else None,
                         "age_days": age_days(currents.time, now) if currents else None,
                         "fallback": currents is None},
            "wind": wind_source(wind, region, wind_from),
            "land": {**land_source(land), "available": land is not None},
            "sir": sir_source(sir_levels, now),
        },
        "notes": notes,
        "settings": {"threshold": a["threshold"], "background_block_deg": a["background_block_deg"],
                     "windage": d["windage"], "diffusion_deg": d["diffusion_deg"], "step_hours": d["step_hours"],
                     "days": d["days"], "max_particles": d["max_particles"], "radius_km": region["risk"]["radius_km"],
                     "risk": region["risk"], "cell_deg": round(cell, 4)},
        "stats": stats,
        "detections": [[round(lon, 3), round(lat, 3), round(x, 5), days] for (lon, lat, x), days in zip(detections, seen)],
        "forecast": forecast,
        "sites": sites,
    }


def write_outputs(result: dict, out: pathlib.Path, now: dt.datetime, history: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    reports = out / "reports.geojson"
    if not reports.exists():
        reports.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    if not history:  # local preview: leave the committed history alone
        return
    (out / "history").mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    w = result["sources"]["wind"]
    summary = {"date": day, "sample": result["sample"], "afai_time": result["sources"]["afai"]["time"],
               "wind": "constant" if w.get("fallback") else "cached" if w.get("cached") else "forecast",
               "sir_date": result["sources"].get("sir", {}).get("date"), "detected": result["stats"]["detected"],
               "sites": {s["id"]: s["risk"] for s in result["sites"]},
               "level_source": {s["id"]: s.get("source", "model") for s in result["sites"]}}
    (out / "history" / f"{day}.json").write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    dates = sorted(p.stem for p in (out / "history").glob("20*.json"))
    (out / "history" / "index.json").write_text(json.dumps(dates), encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", default="sxm")
    p.add_argument("--out", default=str(ROOT / "site" / "data"))
    p.add_argument("--sample", action="store_true", help="use synthetic inputs, no network")
    p.add_argument("--no-history", action="store_true", help="write only latest.json (local preview), not the day's history file")
    args = p.parse_args(argv)
    log = lambda m: print(f"[opensargasso] {m}", file=sys.stderr)  # noqa: E731
    region = load_region(args.region)
    now = dt.datetime.now(dt.timezone.utc)
    if args.sample:
        bbox = region["bbox"]
        afai, currents, land, notes = sample.afai_grid(bbox), sample.currents_grid(bbox), sample.land_grid(bbox), \
            ["synthetic sample data, not an observation"]
        wind = wind_from = sir_levels = context = daily = None
    else:
        try:
            afai, daily, currents, (wind_from, wind), land, sir_levels, notes = fetch_inputs(region, ROOT / ".cache", log, now.date())
        except Exception as e:  # noqa: BLE001
            log(f"AFAI fetch failed, keeping the previous output: {e}")
            return 1
        context, context_notes = fetch_context(region, now, log)
        notes += context_notes
    result = build(region, afai, currents, land, notes, args.sample, now, wind=wind, sir_levels=sir_levels,
                   wind_from=wind_from, context=context, daily=daily)
    write_outputs(result, pathlib.Path(args.out), now, history=not args.no_history)
    log(f"{result['stats']['detected']} pixels flagged, {len(result['forecast'][0])} particles on the map, "
        f"AFAI time {result['sources']['afai']['time']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
