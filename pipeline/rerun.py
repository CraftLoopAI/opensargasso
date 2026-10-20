"""Should the second daily run go ahead? When today's first run had no fresh wind
forecast, or NOAA has posted a newer SIR report since.

    python -m pipeline.rerun --history site/data/history   # prints go=true or go=false

NOAA posts each day's SIR report the next afternoon (13:09 to 16:08 UTC in
October 2026), so a morning run usually has the one from two days before. A
new run also usually gets a different GitHub runner and IP address, which is
often enough to get past a server that blocked the first one. The answer is
printed as `go=...` for $GITHUB_OUTPUT; the reason goes to stderr.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import bulletins, sir, sources


def needed(history: pathlib.Path, today: dt.date, check=bulletins.exists) -> tuple[bool, str]:
    """(go, reason) from today's history file, written by the first run."""
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
    have = summary.get("sir_date")
    try:
        newer = newer_sir(have, today, check)
    except Exception as e:  # noqa: BLE001 - with NOAA's server down, a second run would get no more
        return False, f"today's run had a fresh wind forecast, and NOAA's SIR server did not answer ({e})"
    if newer:
        return True, f"NOAA has posted the SIR report of {newer} since today's run, which had {have or 'none'}"
    return False, "today's run already had a fresh wind forecast and the newest SIR report"


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
    print(f"[opensargasso] second run: {'yes' if go else 'no'}, {reason}", file=sys.stderr)
    print(f"go={'true' if go else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
