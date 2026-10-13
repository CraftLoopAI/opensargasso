"""Backtest the beach levels against NOAA's Sargassum Inundation Risk (SIR).

    python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11
    python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11 --smoc

Downloads, and caches under .cache/calibrate/<region>/, each day's SIR report
and, every --step days, that day's AFAI composite (run through the daily job's
detection), currents and the following week's GFS wind. Then prints:

  1. how much the particle cap thins the seeds,
  2. day 0 (detections only) against SIR on the same date: the best thresholds
     per radius, with a held-out check on alternate dates,
  3. forecast day k against SIR on day k, next to persistence (SIR carried
     forward), with the region's radius and thresholds.

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
    return {s["id"]: round(weight * sum(1 for lon, lat in points if risk.distance_km(lon, lat, s["lon"], s["lat"]) <= radius_km))
            for s in sites}


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


def inputs(day: dt.date, region: dict, land, cache: pathlib.Path, pause: float = 1.0):
    """Detections, currents and the next week's wind for a date, as the daily job would see them.
    The detections are redone when the region's AFAI settings change; currents and wind are kept."""
    f = cache / f"inputs_{day:%Y%m%d}.json"
    j = json.loads(f.read_text()) if f.exists() else {}
    bbox, a = region["bbox"], region["afai"]
    stamp = f"{day:%Y-%m-%d}T12:00:00Z"
    if j.get("afai") == a and "wind" in j:
        return j
    if j.get("afai") != a:
        afai = erddap.fetch_grid(sources.AFAI, bbox, stride=a["stride"], time=stamp)
        dets, stats = detect.detect(afai, a["threshold"], a["background_block_deg"],
                                    is_land=land.is_land, pixel_deg=abs(afai.dlon) / a["stride"])
        j.update(afai=a, afai_time=afai.time, cell=abs(afai.dlon), stats=stats, detections=dets)
    if "wind" not in j:
        try:
            cur = erddap.fetch_grid(sources.CURRENTS, bbox, time=f"{day:%Y-%m-%d}T00:00:00Z")
            cur = {"lats": cur.lats, "lons": cur.lons, "data": cur.data, "time": cur.time}
        except Exception:  # noqa: BLE001 - the daily job falls back too
            cur = None
        _, wind, _ = run.fetch_wind(bbox, stamp, end=f"{day + dt.timedelta(region['drift']['days']):%Y-%m-%d}T12:00:00Z")
        j.update(currents=cur, wind=[{"lats": g.lats, "lons": g.lons, "data": g.data, "time": g.time} for g in wind])
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


def drift_tracks(day, j, seeds, region, land, windage=None, smoc=None):
    """The daily job's drift from a past date; with `smoc`, those currents change every 3 hours."""
    d = region["drift"]
    start = dt.datetime(day.year, day.month, day.day, 12, tzinfo=dt.timezone.utc)
    geo = drift.make_velocity(grid(j["currents"]) if j["currents"] else None, d["fallback_current_ms"])
    wind = drift.make_wind([grid(g) for g in j["wind"]], start, d["wind_ms"])
    def velocity(lon, lat, hours):
        g = smoc.get(start + dt.timedelta(hours=hours)) if smoc else None
        u, v = (g.value("u_current", lon, lat), g.value("v_current", lon, lat)) if g else (math.nan, math.nan)
        return (u, v) if math.isfinite(u) and math.isfinite(v) else geo(lon, lat)  # outside SMOC: geostrophic

    return drift.simulate(seeds, velocity, land.is_land, region["bbox"], days=d["days"], step_hours=d["step_hours"],
                          windage=d["windage"] if windage is None else windage, wind=wind,
                          diffusion_deg=d["diffusion_deg"], rng=random.Random(day.toordinal() + 1), velocity_hours=True)


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
    runs = []
    for n in range(0, span + 1, args.step):
        day = args.start + dt.timedelta(n)
        try:
            j = inputs(day, region, land, cache)
        except Exception as e:  # noqa: BLE001 - nothing is cached, so a rerun tries this day again
            print(f"skipping {day}: {str(e)[:120]}")
            continue
        dets = [tuple(x) for x in j["detections"]]
        seeds = drift.seed_particles(dets, dr["max_particles"], random.Random(day.toordinal()), j["cell"])
        weight = sum(drift.seeds_for(x) for _, _, x in dets) / len(seeds) if seeds else 1.0
        runs.append((day, j, seeds, weight))
    if not runs:
        print("no input days could be fetched; nothing to score")
        return 1
    reports = [v for v in sir_by_day.values() if v]
    balance = [sum(1 for lv in reports for x in lv.values() if x == k) for k in range(4)]
    print(f"{len(runs)} input days, {len(reports)} of {len(sir_by_day)} SIR reports; SIR beach-days low/warning/medium/high: {balance}\n")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
