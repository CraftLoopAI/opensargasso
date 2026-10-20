"""Should a scheduled run go ahead? Always for the day's first, and for a later
one when the first had no fresh wind forecast, or NOAA has since posted a newer
satellite image or SIR report.

    python -m pipeline.rerun --history site/data/history   # prints go=true or go=false

The satellite image of a day comes out overnight (it was on AOML's ERDDAP by
08:07 UTC the next morning, and not yet at 22:00 UTC the same day, in October
2026). NOAA posts each day's SIR report the next afternoon (13:09 to 16:08 UTC),
so a morning run usually has the one from two days before. A new run also
usually gets a different GitHub runner and IP address, which is often enough to
get past a server that blocked the first one. The answer is printed as `go=...`
for $GITHUB_OUTPUT; the reason goes to stderr.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import bulletins, erddap, sir, sources


def latest_image(fetch=erddap.fetch_text) -> str:
    """Time of the newest 7-day satellite composite on ERDDAP, as YYYY-MM-DDTHH:MM:SSZ like the history's afai_time."""
    text = fetch(f"{sources.AFAI['base']}/griddap/{sources.AFAI['dataset']}.csv?time%5Blast%5D", timeout=30, waits=(20,))
    time = text.split()[-1]  # the CSV is a header, a units line and the time
    dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")  # anything else raises
    return time


def needed(history: pathlib.Path, today: dt.date, check=bulletins.exists, newest_image=latest_image) -> tuple[bool, str]:
    """(go, reason) from today's history file, written by the day's first run."""
    path = history / f"{today.isoformat()}.json"
    if not path.exists():
        return True, "no run today yet"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, "today's history file is unreadable"
    wind = summary.get("wind")
    if wind != "forecast":
        return True, f"today's run used {'an earlier' if wind == 'cached' else 'no'} wind forecast"
    news, silent = [], []
    try:
        image = newest_image()
        if image > (summary.get("afai_time") or ""):
            news.append(f"the satellite image of {image[:10]}")
    except Exception as e:  # noqa: BLE001 - a server that does not answer has nothing newer for a second run
        silent.append(f"AOML's ERDDAP ({e})")
    try:
        report = newer_sir(summary.get("sir_date"), today, check)
        if report:
            news.append(f"the SIR report of {report}")
    except Exception as e:  # noqa: BLE001
        silent.append(f"NOAA's SIR server ({e})")
    if news:
        return True, f"NOAA has posted {' and '.join(news)} since today's run"
    if silent:
        return False, f"today's run had a fresh wind forecast, and {' and '.join(silent)} did not answer"
    return False, "today's run already had a fresh wind forecast, the newest satellite image and the newest SIR report"


def newer_sir(have: str | None, today: dt.date, check=bulletins.exists) -> dt.date | None:
    """The newest SIR report after `have` (YYYY-MM-DD, None for none), up to yesterday's, or None."""
    oldest = dt.date.fromisoformat(have) + dt.timedelta(days=1) if have else today - dt.timedelta(days=sir.LOOK_BACK_DAYS)
    day = today - dt.timedelta(days=1)  # a day's report comes out the next day
    while day >= oldest:
        if check(sources.SIR["kmz"].format(date=day.strftime("%Y%m%d"))):
            return day
        day -= dt.timedelta(days=1)
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--history", default="site/data/history")
    args = p.parse_args(argv)
    go, reason = needed(pathlib.Path(args.history), dt.datetime.now(dt.timezone.utc).date())
    print(f"[opensargasso] scheduled run: {'yes' if go else 'no'}, {reason}", file=sys.stderr)
    print(f"go={'true' if go else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
