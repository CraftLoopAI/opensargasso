"""Turn an approved GitHub issue (sargassum report form) into a GeoJSON feature.

    python -m pipeline.reports --event "$GITHUB_EVENT_PATH" --region sxm
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from .run import ROOT, load_region

AMOUNTS = {"none": 0, "light": 1, "moderate": 2, "heavy": 3}


def parse_issue_body(body: str) -> dict:
    """Issue forms render as '### Label' followed by the answer."""
    fields = {}
    for m in re.finditer(r"^###\s+(.+?)\s*\n+(.*?)(?=^###\s|\Z)", body or "", flags=re.S | re.M):
        value = m.group(2).strip()
        fields[m.group(1).strip().lower()] = "" if value == "_No response_" else value
    return fields


def to_feature(fields: dict, region: dict, issue_number: int, created: str) -> dict:
    """Validate a parsed report. Raises ValueError with a readable reason."""
    amount = fields.get("amount", "").split(",")[0].split("(")[0].strip().lower()
    if amount not in AMOUNTS:
        raise ValueError(f"unknown amount '{fields.get('amount', '')}'")
    lat_s, lon_s = fields.get("latitude", ""), fields.get("longitude", "")
    beach = fields.get("beach", "")
    site = next((s for s in region["sites"] if s["name"] == beach), None)
    if lat_s and lon_s:
        try:
            lat, lon = float(lat_s.replace(",", ".")), float(lon_s.replace(",", "."))
        except ValueError:
            raise ValueError("latitude and longitude must be numbers") from None
    elif site:
        lat, lon = site["lat"], site["lon"]
    else:
        raise ValueError("pick a beach from the list or give latitude and longitude")
    b = region["bbox"]
    if not (b["south"] <= lat <= b["north"] and b["west"] <= lon <= b["east"]):
        raise ValueError("location is outside the monitored region")
    note = re.sub(r"\s+", " ", fields.get("note", ""))[:140]
    observed = fields.get("observed on", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", observed):
        observed = created[:10]
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
            "properties": {"id": issue_number, "level": AMOUNTS[amount], "beach": site["name"] if site else "",
                           "note": note, "observed": observed}}


def append_report(path: pathlib.Path, feature: dict) -> bool:
    """Add a feature unless that issue is already recorded. Returns True if added."""
    fc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"type": "FeatureCollection", "features": []}
    if any(f["properties"].get("id") == feature["properties"]["id"] for f in fc["features"]):
        return False
    fc["features"].append(feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--event", required=True, help="path to the GitHub event JSON")
    p.add_argument("--region", default="sxm")
    p.add_argument("--out", default=str(ROOT / "site" / "data" / "reports.geojson"))
    args = p.parse_args(argv)
    issue = json.loads(pathlib.Path(args.event).read_text(encoding="utf-8"))["issue"]
    try:
        feature = to_feature(parse_issue_body(issue.get("body", "")), load_region(args.region),
                             issue["number"], issue.get("created_at", ""))
    except ValueError as e:
        print(f"report rejected: {e}")
        return 1
    print("report added" if append_report(pathlib.Path(args.out), feature) else "report already recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
