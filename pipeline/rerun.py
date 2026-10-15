"""Should the second daily run go ahead? Only when today's first run had no fresh wind forecast.

    python -m pipeline.rerun --history site/data/history   # prints go=true or go=false

A new run usually gets a different GitHub runner and IP address, which is
often enough to get past a server that blocked the first one. The answer is
printed as `go=...` for $GITHUB_OUTPUT; the reason goes to stderr.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys


def needed(history: pathlib.Path, today: dt.date) -> tuple[bool, str]:
    """(go, reason) from today's history file, written by the first run."""
    path = history / f"{today.isoformat()}.json"
    if not path.exists():
        return True, "no run today yet"
    try:
        wind = json.loads(path.read_text(encoding="utf-8")).get("wind")
    except (OSError, ValueError):
        return True, "today's history file is unreadable"
    if wind == "forecast":
        return False, "today's run already had a fresh wind forecast"
    return True, f"today's run used {'an earlier' if wind == 'cached' else 'no'} wind forecast"


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
