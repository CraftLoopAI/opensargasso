"""Beach list in regions/sxm.json: issue form in sync, positions on the coast, sources recorded."""
import pathlib
import re

from pipeline import landmask, run

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGION = run.load_region("sxm")


def form_beaches():
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "sargassum-report.yml").read_text(encoding="utf-8")
    block = text.split("id: beach", 1)[1].split("validations:", 1)[0]
    return [m.group(1).strip() for m in re.finditer(r"^\s+- (.+)$", block, re.M)]


def test_issue_form_lists_exactly_the_region_beaches():
    # A name that differs by one character makes a sighting fail validation.
    assert form_beaches() == [s["name"] for s in REGION["sites"]] + ["Other"]


def test_every_beach_is_on_the_coast():
    mask = landmask.load(ROOT / "regions" / REGION["land_mask"])
    for s in REGION["sites"]:
        around = {mask.is_land(s["lon"] + dx * mask.step, s["lat"] + dy * mask.step)
                  for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        assert around == {True, False}, f"{s['name']} is not within one cell (about 220 m) of the coastline"


def test_every_beach_names_its_openstreetmap_source():
    for s in REGION["sites"]:
        assert s["osm"] and all(re.fullmatch(r"[nwr]\d+", ref) for ref in s["osm"]), s["id"]
