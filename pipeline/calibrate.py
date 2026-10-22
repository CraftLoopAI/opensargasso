"""Backtest the beach levels against NOAA's Sargassum Inundation Risk (SIR).

    python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11
    python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11 --smoc

Downloads, and caches under .cache/calibrate/<region>/, each day's SIR report
and, every --step days, that day's AFAI composite (run through the daily job's
detection), the day each detection was seen (from the seven daily images
behind the composite), currents, and GFS wind from six days before to a week
after. Then prints:

  1. how much the particle cap thins the seeds,
  2. day 0 (detections only) against SIR on the same date: the best thresholds
     per radius, with a held-out check on alternate dates,
  3. forecast day k against SIR on day k, next to persistence (SIR carried
     forward), with the region's radius and thresholds, and with each patch
     drifting from the day it was seen,
  4. whether drifting the patches seen earlier in the week up to the
     composite's date brings them closer to the sargassum that day's own
     image shows.

--smoc adds the drift with MeteoFrance SMOC currents from the Open-Meteo Marine
API (free for non-commercial use). Standard library only. The method and the
October 2026 results are in docs/CALIBRATION.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import pathlib
import random
import time
import urllib.parse
import zipfile

from . import detect, drift, erddap, landmask, risk, run, sir, sources

LEADS = (1, 3, 5, 7)
NEAR_KM = 5  # section 4: about three satellite pixels
SMOC_URL = "https://marine-api.open-meteo.com/v1/marine"


# ---------- scoring ----------

def level(count: float, thresholds) -> int:
    low, moderate, high = thresholds
    return 3 if count >= high else 2 if count >= moderate else 1 if count >= low else 0


def qwk(ours, ref, n: int = 4):
    """Quadratic weighted kappa and the confusion matrix (rows ours, columns reference)."""
    m = [[0] * n for _ in range(n)]
    for a, b in zip(ours, ref):
        m[a][b] += 1
    total = len(ours)
    rows, cols = [sum(r) for r in m], [sum(m[i][j] for i in range(n)) for j in range(n)]
    w = lambda i, j: (i - j) ** 2 / (n - 1) ** 2  # noqa: E731
    observed = sum(w(i, j) * m[i][j] for i in range(n) for j in range(n))
    expected = sum(w(i, j) * rows[i] * cols[j] / total for i in range(n) for j in range(n)) if total else 0
    return (1 - observed / expected if expected else float("nan")), m


def fit_thresholds(samples):
    """Best (low, moderate, high) for [(count, reference level)] by kappa, searching every
    combination of observed counts. Returns (kappa, thresholds); (nan, None) when the
    reference has fewer than two levels, since any fit would then be meaningless."""
    if len({s for _, s in samples}) < 2:
        return float("nan"), None
    top = int(max((c for c, _ in samples), default=0)) + 2
    below = [[0] * 4 for _ in range(top + 2)]             # below[c][s]: samples with count < c
    hist = [[0] * 4 for _ in range(top + 1)]
    for c, s in samples:
        hist[min(int(c), top)][s] += 1
    for c in range(top + 1):
        for s in range(4):
            below[c + 1][s] = below[c][s] + hist[c][s]
    total, cols = len(samples), [below[top + 1][s] for s in range(4)]
    w = lambda i, j: (i - j) ** 2 / 9  # noqa: E731
    cand = sorted({int(c) for c, _ in samples if c >= 1} | {1}) + [top]
    best = (float("-inf"), None)
    for a in range(len(cand)):
        for b in range(a + 1, len(cand)):
            for c in range(b + 1, len(cand)):
                edges = (0, cand[a], cand[b], cand[c], top + 1)
                m = [[below[edges[k + 1]][s] - below[edges[k]][s] for s in range(4)] for k in range(4)]
                rows = [sum(r) for r in m]
                expected = sum(w(i, j) * rows[i] * cols[j] / total for i in range(4) for j in range(4))
                if not expected:
                    continue
                k = 1 - sum(w(i, j) * m[i][j] for i in range(4) for j in range(4)) / expected
                if k > best[0]:
                    best = (k, (cand[a], cand[b], cand[c]))
    return best


def fmt(kappa: float) -> str:
    return f"{kappa:+.2f}" if math.isfinite(kappa) else "  n/a"


def counts_near(points, sites, radius_km: float, weight: float = 1.0) -> dict:
    """{site id: weighted number of points within `radius_km`}, as risk.site_risk counts them."""
    return {s["id"]: round(weight * sum(1 for lon, lat, *_ in points if risk.distance_km(lon, lat, s["lon"], s["lat"]) <= radius_km))
            for s in sites}


def share_near(points, targets, km: float) -> float:
    """Share of `points` within `km` (at most 10) of any of `targets`, all (lon, lat)."""
    buckets = {}
    for lon, lat in targets:
        buckets.setdefault((math.floor(lon * 10), math.floor(lat * 10)), []).append((lon, lat))
    hits = 0
    for lon, lat in points:
        i, j = math.floor(lon * 10), math.floor(lat * 10)
        hits += any(risk.distance_km(lon, lat, x, y) <= km
                    for di in (-1, 0, 1) for dj in (-1, 0, 1) for x, y in buckets.get((i + di, j + dj), ()))
    return hits / len(points) if points else float("nan")


# ---------- data, cached one file per day ----------

def sir_levels(day: dt.date, region: dict, cache: pathlib.Path, pause: float = 1.0):
    f = cache / f"sir_{day:%Y%m%d}.json"
    if not f.exists():
        try:
            data = erddap.fetch_bytes(sources.SIR["kmz"].format(date=f"{day:%Y%m%d}"))
        except Exception as e:  # noqa: BLE001 - a missing day is normal
            f.write_text(json.dumps({"missing": str(e)[:80]}))
            return None
        kmz = zipfile.ZipFile(io.BytesIO(data))
        kml = kmz.read(next(n for n in kmz.namelist() if n.endswith(".kml"))).decode("utf-8", "replace")
        segments = sir.parse_kml(kml, region["bbox"])
        f.write_text(json.dumps({"levels": sir.site_levels(region["sites"], segments), "segments": len(segments)}))
        time.sleep(pause)
    return json.loads(f.read_text()).get("levels")


def daily_image(day: dt.date, region: dict, kept: dict, pause: float = 1.0):
    """The daily AFAI image of a date, or None if NOAA has none; `kept` holds the ones already fetched."""
    if day not in kept:
        stamp = f"{day:%Y-%m-%d}T12:00:00Z"
        g = erddap.fetch_grid(sources.AFAI_DAILY, region["bbox"], stride=region["afai"]["stride"], time=stamp, fmt="asc")
        kept[day] = g if g.time == stamp else None  # ERDDAP answers with the nearest day it has
        time.sleep(pause)
    return kept[day]


def seen_by_max(detections, daily) -> list:
    """detect.seen_days without the composite: the composite keeps each pixel's highest daily
    value (checked 20 October 2026), so a detection was seen on the newest day with that value."""
    out = []
    for lon, lat, *_ in detections:
        values = [g.value("AFAI", lon, lat) for g in daily]
        top = max((v for v in values if math.isfinite(v)), default=None)
        out.append(None if top is None else values.index(top))
    return out


def inputs(day: dt.date, region: dict, land, cache: pathlib.Path, pause: float = 1.0, images: dict | None = None):
    """Detections and the day each was seen, the detections in the date's own daily image,
    currents, and the wind from six days before to a week after, as the daily job would see them.
    The detections are redone when the region's AFAI settings change; currents and wind are kept."""
    f = cache / f"inputs_{day:%Y%m%d}.json"
    j = json.loads(f.read_text()) if f.exists() else {}
    bbox, a = region["bbox"], region["afai"]
    stamp = f"{day:%Y-%m-%d}T12:00:00Z"
    if j.get("afai") == a and all(k in j for k in ("wind", "wind_before", "seen")):
        return j
    if j.get("afai") != a:
        afai = erddap.fetch_grid(sources.AFAI, bbox, stride=a["stride"], time=stamp)
        dets, stats = detect.detect(afai, a["threshold"], a["background_block_deg"],
                                    is_land=land.is_land, pixel_deg=abs(afai.dlon) / a["stride"])
        j.update(afai=a, afai_time=afai.time, cell=abs(afai.dlon), stats=stats, detections=dets)
        j.pop("seen", None)
    if "seen" not in j:
        daily = [daily_image(day - dt.timedelta(k), region, images if images is not None else {}, pause)
                 for k in range(detect.COMPOSITE_DAYS)]
        j["seen"] = seen_by_max(j["detections"], daily) if all(daily) else None
        fresh = detect.detect(daily[0], a["threshold"], a["background_block_deg"], is_land=land.is_land,
                              pixel_deg=abs(daily[0].dlon) / a["stride"])[0] if daily[0] else None
        j["fresh"] = [[round(lon, 3), round(lat, 3)] for lon, lat, _ in fresh] if fresh is not None else None
    if "wind" not in j:
        try:
            cur = erddap.fetch_grid(sources.CURRENTS, bbox, time=f"{day:%Y-%m-%d}T00:00:00Z")
            cur = {"lats": cur.lats, "lons": cur.lons, "data": cur.data, "time": cur.time}
        except Exception:  # noqa: BLE001 - the daily job falls back too
            cur = None
        _, wind, _ = run.fetch_wind(bbox, stamp, end=f"{day + dt.timedelta(region['drift']['days']):%Y-%m-%d}T12:00:00Z")
        j.update(currents=cur, wind=[{"lats": g.lats, "lons": g.lons, "data": g.data, "time": g.time} for g in wind])
    if "wind_before" not in j:  # for the patches seen up to six days before the date
        _, wind, _ = run.fetch_wind(bbox, f"{day - dt.timedelta(detect.COMPOSITE_DAYS - 1):%Y-%m-%d}T12:00:00Z", end=stamp)
        j["wind_before"] = [{"lats": g.lats, "lons": g.lons, "data": g.data, "time": g.time} for g in wind if g.time < stamp]
    f.write_text(json.dumps(j))
    time.sleep(pause)
    return json.loads(f.read_text())


def smoc_series(region: dict, start: dt.date, end: dt.date, cache: pathlib.Path):
    """3-hourly SMOC surface currents on a 0.5 degree lattice, as Grids keyed by time."""
    f = cache / "smoc.json"
    if not f.exists():
        bbox = region["bbox"]
        lats = [bbox["south"] + 0.5 * k for k in range(int((bbox["north"] - bbox["south"]) / 0.5) + 1)]
        lons = [bbox["west"] + 0.5 * k for k in range(int((bbox["east"] - bbox["west"]) / 0.5) + 1)]
        pts = [(la, lo) for la in lats for lo in lons]
        out = {"lats": lats, "lons": lons, "hours": [], "u": [], "v": []}
        month = start.replace(day=1)
        while month <= end:  # one request per month keeps each response small
            nxt = (month + dt.timedelta(days=32)).replace(day=1)
            a, b = max(month, start), min(nxt - dt.timedelta(days=1), end)
            query = urllib.parse.urlencode({"latitude": ",".join(str(p[0]) for p in pts), "longitude": ",".join(str(p[1]) for p in pts),
                                            "hourly": "ocean_current_velocity,ocean_current_direction", "start_date": a.isoformat(),
                                            "end_date": b.isoformat(), "timezone": "UTC", "cell_selection": "sea"})
            res = json.loads(erddap.fetch_text(f"{SMOC_URL}?{query}"))
            hours = res[0]["hourly"]["time"]
            for h in range(0, len(hours), 3):
                u = [[None] * len(lons) for _ in lats]
                v = [[None] * len(lons) for _ in lats]
                for (la, lo), p in zip(pts, res):
                    speed, toward = p["hourly"]["ocean_current_velocity"][h], p["hourly"]["ocean_current_direction"][h]
                    if speed is None or toward is None:
                        continue
                    j, i = lats.index(la), lons.index(lo)
                    u[j][i] = speed / 3.6 * math.sin(math.radians(toward))  # km/h, direction the current flows to
                    v[j][i] = speed / 3.6 * math.cos(math.radians(toward))
                out["hours"].append(hours[h] + ":00Z"); out["u"].append(u); out["v"].append(v)
            month = nxt
            time.sleep(2)
        f.write_text(json.dumps(out))
    d = json.loads(f.read_text())
    nan = lambda rows: [[math.nan if x is None else x for x in r] for r in rows]  # noqa: E731
    return {run.parse_time(h): erddap.Grid(d["lats"], d["lons"], {"u_current": nan(u), "v_current": nan(v)})
            for h, u, v in zip(d["hours"], d["u"], d["v"])}


# ---------- backtest ----------

def grid(g):
    return erddap.Grid(g["lats"], g["lons"], g["data"], time=g.get("time"))


def drift_tracks(day, j, seeds, region, land, windage=None, smoc=None, days=None, diffusion=None, currents=True, speed=1):
    """The daily job's drift from a past date; with `smoc`, those currents change every 3 hours.
    `speed` scales currents and wind alike (-1 drifts backward)."""
    d = region["drift"]
    start = dt.datetime(day.year, day.month, day.day, 12, tzinfo=dt.timezone.utc)
    geo = drift.make_velocity(grid(j["currents"]) if j["currents"] else None, d["fallback_current_ms"]) if currents \
        else drift.make_velocity(None, (0.0, 0.0))
    wind_at = drift.make_wind([grid(g) for g in j.get("wind_before", []) + j["wind"]], start, d["wind_ms"])
    def velocity(lon, lat, hours):
        g = smoc.get(start + dt.timedelta(hours=hours)) if smoc else None
        u, v = (g.value("u_current", lon, lat), g.value("v_current", lon, lat)) if g else (math.nan, math.nan)
        u, v = (u, v) if math.isfinite(u) and math.isfinite(v) else geo(lon, lat)  # outside SMOC: geostrophic
        return speed * u, speed * v

    def wind(lon, lat, hours):
        u, v = wind_at(lon, lat, hours)
        return speed * u, speed * v

    return drift.simulate(seeds, velocity, land.is_land, region["bbox"], days=d["days"] if days is None else days,
                          step_hours=d["step_hours"], windage=d["windage"] if windage is None else windage, wind=wind,
                          diffusion_deg=d["diffusion_deg"] if diffusion is None else diffusion,
                          rng=random.Random(day.toordinal() + 1), velocity_hours=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", default="sxm")
    p.add_argument("--start", required=True, type=dt.date.fromisoformat)
    p.add_argument("--end", required=True, type=dt.date.fromisoformat)
    p.add_argument("--step", type=int, default=2, help="use our inputs every N days (SIR is read every day)")
    p.add_argument("--radii", default="10,20,30,50", help="radii in km to fit on day 0")
    p.add_argument("--smoc", action="store_true", help="also score the drift with SMOC currents (Open-Meteo)")
    p.add_argument("--cache", type=pathlib.Path, default=None)
    args = p.parse_args(argv)
    region = run.load_region(args.region)
    cache = args.cache or run.ROOT / ".cache" / "calibrate" / args.region
    cache.mkdir(parents=True, exist_ok=True)
    land = landmask.load(run.ROOT / "regions" / region["land_mask"])
    sites, dr = region["sites"], region["drift"]
    span = (args.end - args.start).days
    sir_by_day = {args.start + dt.timedelta(n): sir_levels(args.start + dt.timedelta(n), region, cache) for n in range(span + 1)}
    runs, dated, images = [], {}, {}
    for n in range(0, span + 1, args.step):
        day = args.start + dt.timedelta(n)
        for old in [d for d in images if d <= day - dt.timedelta(detect.COMPOSITE_DAYS)]:
            del images[old]  # days are taken in order: older images are not needed again
        try:
            j = inputs(day, region, land, cache, images=images)
        except Exception as e:  # noqa: BLE001 - nothing is cached, so a rerun tries this day again
            print(f"skipping {day}: {str(e)[:120]}")
            continue
        dets = [tuple(x) for x in j["detections"]]
        seeds = drift.seed_particles(dets, dr["max_particles"], random.Random(day.toordinal()), j["cell"])
        weight = sum(drift.seeds_for(x) for _, _, x in dets) / len(seeds) if seeds else 1.0
        runs.append((day, j, seeds, weight))
        if j["seen"] is not None:  # the same seeds, each with the day its detection was seen
            dated[day] = drift.seed_particles([(*x, k) for x, k in zip(dets, j["seen"])], dr["max_particles"],
                                              random.Random(day.toordinal()), j["cell"])
    if not runs:
        print("no input days could be fetched; nothing to score")
        return 1
    reports = [v for v in sir_by_day.values() if v]
    balance = [sum(1 for lv in reports for x in lv.values() if x == k) for k in range(4)]
    print(f"{len(runs)} input days ({len(dated)} with every daily image, so each detection dated), "
          f"{len(reports)} of {len(sir_by_day)} SIR reports; SIR beach-days low/warning/medium/high: {balance}\n")

    print("1. Seeds thinned by the particle cap")
    for day, j, seeds, weight in runs[::max(1, len(runs) // 8)]:
        print(f"   {day}: {len(j['detections'])} detections, weight {weight:.1f}")

    print("\n2. Day 0 against SIR on the same date (counts weighted as the daily job does)")
    fitted = {}
    for radius in [float(r) for r in args.radii.split(",")]:
        halves, samples = [[], []], []
        for n, (day, j, seeds, weight) in enumerate(runs):
            ref = sir_by_day.get(day)
            if not ref:
                continue
            counts = counts_near(seeds, sites, radius, weight)
            for s in sites:
                if ref.get(s["id"]) is not None:
                    samples.append((counts[s["id"]], ref[s["id"]])); halves[n % 2].append(samples[-1])
        k, t = fit_thresholds(samples)
        if t is None:
            print(f"   radius {radius:g} km: too little variety in SIR to fit")
            continue
        held = []
        for a, b in ((0, 1), (1, 0)):
            _, ta = fit_thresholds(halves[a])
            held.append(f"{qwk([level(c, ta) for c, _ in halves[b]], [s for _, s in halves[b]])[0]:.2f}" if ta else "n/a")
        line = f"   radius {radius:g} km: thresholds {t}, kappa {k:.2f} fitted, {' and '.join(held)} held out"
        if radius == region["risk"]["radius_km"]:
            cur = (region["risk"]["low"], region["risk"]["moderate"], region["risk"]["high"])
            line += f"; region's {cur}: {qwk([level(c, cur) for c, _ in samples], [s for _, s in samples])[0]:.2f}"
        print(line)
        fitted[radius] = t

    radius, thresholds = region["risk"]["radius_km"], (region["risk"]["low"], region["risk"]["moderate"], region["risk"]["high"])
    print(f"\n3. Forecast day k against SIR on day k (kappa), radius {radius:g} km, thresholds {thresholds}")
    configs = [("drift, region's currents and windage", {})]
    if args.smoc:
        smoc = smoc_series(region, args.start, args.end + dt.timedelta(days=dr["days"]), cache)
        configs += [("drift, SMOC currents, 2 % windage", {"smoc": smoc, "windage": 0.02}),
                    ("drift, SMOC currents, 1 % windage", {"smoc": smoc, "windage": 0.01})]
    pers = {k: ([], []) for k in LEADS}
    for day, *_ in runs:
        now_l = sir_by_day.get(day)
        for k in LEADS:
            later = sir_by_day.get(day + dt.timedelta(k))
            if now_l and later:
                for s in sites:
                    if now_l.get(s["id"]) is not None and later.get(s["id"]) is not None:
                        pers[k][0].append(now_l[s["id"]]); pers[k][1].append(later[s["id"]])
    print(f"   {'persistence (SIR carried forward)':38s}" + "".join(f"  day {k}: {fmt(qwk(*pers[k])[0])}" for k in LEADS))
    for name, opts in configs:
        scores = {k: ([], []) for k in LEADS}
        for day, j, seeds, weight in runs:
            tracks = drift_tracks(day, j, seeds, region, land, **opts)
            for k in LEADS:
                later = sir_by_day.get(day + dt.timedelta(k))
                if not later:
                    continue
                counts = counts_near([(tr[k][0], tr[k][1]) for tr in tracks if tr[k][2] != drift.LEFT], sites, radius, weight)
                for s in sites:
                    if later.get(s["id"]) is not None:
                        scores[k][0].append(level(counts[s["id"]], thresholds)); scores[k][1].append(later[s["id"]])
        print(f"   {name:38s}" + "".join(f"  day {k}: {fmt(qwk(*scores[k])[0])}" for k in LEADS))

    # Each patch drifting from the day it was seen: day 0 is then where it has likely got to, not where it was seen.
    counts, samples = {}, []
    for day, j, seeds, weight in runs:
        if day not in dated:
            continue
        tracks = drift_tracks(day, j, dated[day], region, land)
        counts[day] = {k: counts_near([(tr[k][0], tr[k][1]) for tr in tracks if tr[k][2] != drift.LEFT], sites, radius, weight)
                       for k in (0, *LEADS)}
        ref = sir_by_day.get(day)
        samples += [(counts[day][0][s["id"]], ref[s["id"]]) for s in sites if ref and ref.get(s["id"]) is not None]
    _, refit = fit_thresholds(samples)
    for label, t in (("drift from the day seen", thresholds), (f"same, thresholds {refit}", refit)):
        if t is None:
            continue
        scores = {k: ([], []) for k in LEADS}
        for day, c in counts.items():
            for k in LEADS:
                later = sir_by_day.get(day + dt.timedelta(k))
                for s in sites:
                    if later and later.get(s["id"]) is not None:
                        scores[k][0].append(level(c[k][s["id"]], t)); scores[k][1].append(later[s["id"]])
        day0 = qwk([level(c, t) for c, _ in samples], [r for _, r in samples])[0]
        print(f"   {label:38s}" + "".join(f"  day {k}: {fmt(qwk(*scores[k])[0])}" for k in LEADS) + f"  (day 0: {fmt(day0)})")

    # Do the drifted positions match where the composite's date's own image sees sargassum better than where it was seen?
    ways = [("where seen, not moved", None), ("drifted as the model does", {}), ("same without random spread", {"diffusion": 0}),
            ("currents only, no random spread", {"diffusion": 0, "windage": 0}),
            ("wind only, no random spread", {"diffusion": 0, "currents": False}),
            ("backward, no random spread (a check)", {"diffusion": 0, "speed": -1})]
    ages = range(1, detect.COMPOSITE_DAYS)
    near = {name: {k: [0, 0.0] for k in ages} for name, _ in ways}  # particles, particles near sargassum
    for day, j, *_ in runs:
        if day not in dated or not j["fresh"]:
            continue
        moved = {name: drift_tracks(day, j, dated[day], region, land, days=0, **opts) for name, opts in ways if opts is not None}
        for k in ages:  # only patches every way leaves afloat, so each position can be seen
            keep = [n for n, seed in enumerate(dated[day]) if seed[2] == k and all(t[n][0][2] == drift.AFLOAT for t in moved.values())]
            if not keep:
                continue
            for name, _ in ways:
                points = [moved[name][n][0][:2] if name in moved else dated[day][n][:2] for n in keep]
                near[name][k][0] += len(points)
                near[name][k][1] += share_near(points, j["fresh"], NEAR_KM) * len(points)
    print(f"\n4. Patches seen 1 to 6 days before the composite's date and afloat on it: share within {NEAR_KM:g} km of "
          f"sargassum in that date's own image ({sum(near[ways[0][0]][k][0] for k in ages)} particles)")
    print(f"   {'':38s}" + "".join(f"  {k} day{'s' if k > 1 else ' '}" for k in ages) + "    all")
    for name, by_age in near.items():
        n, hit = sum(v[0] for v in by_age.values()), sum(v[1] for v in by_age.values())
        print(f"   {name:38s}" + "".join(f"  {v[1] / v[0]:5.0%} " if v[0] else "    n/a " for v in by_age.values())
              + (f"  {hit / n:5.0%}" if n else "    n/a"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
