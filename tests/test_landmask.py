"""Coastline land mask: joining ways, filling rings, storage, and the committed mask."""
import pathlib

from pipeline import detect, drift, erddap, landmask, sources

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_join_rings_with_split_and_reversed_ways():
    ways = [([1, 2], [(0, 0), (1, 0)]),
            ([3, 2], [(1, 1), (1, 0)]),           # stored the wrong way round
            ([3, 4, 1], [(1, 1), (0, 1), (0, 0)]),
            ([7, 8], [(5, 5), (6, 5)])]           # never closes
    rings, chains = landmask.join_rings(ways)
    assert len(rings) == 1 and len(chains) == 1
    assert sorted(set(rings[0])) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_rasterize_fills_islands_and_keeps_lagoons_open():
    lagoon = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]
    bits = landmask.rasterize([SQUARE, lagoon], west=-0.5, south=-0.5, step=0.1, cols=20, rows=20)
    mask = landmask.LandMask(-0.5, -0.5, 0.1, 20, 20, bits)
    assert mask.is_land(0.15, 0.85)
    assert not mask.is_land(0.5, 0.5)     # water inside the island
    assert not mask.is_land(1.2, 0.5)
    assert not mask.is_land(50.0, 0.5)    # outside the grid


def test_rasterize_clips_rings_that_leave_the_grid():
    bits = landmask.rasterize([[(-5.0, -5.0), (0.25, -5.0), (0.25, 5.0), (-5.0, 5.0)]], 0.0, 0.0, 0.1, 10, 10)
    mask = landmask.LandMask(0.0, 0.0, 0.1, 10, 10, bits)
    assert mask.is_land(0.05, 0.5) and mask.is_land(0.15, 0.5)
    assert not mask.is_land(0.35, 0.5)


def test_json_round_trip_and_land_test():
    bits = landmask.rasterize([SQUARE], -1.0, -1.0, 0.25, 12, 12)
    mask = landmask.LandMask.from_json(landmask.LandMask(-1.0, -1.0, 0.25, 12, 12, bits, "n", "u").to_json(built="x"))
    assert mask.bits == bytes(bits) and (mask.name, mask.url) == ("n", "u")
    is_land = drift.make_land_test(mask)
    assert is_land(0.5, 0.5) and not is_land(-0.5, 0.5)


def test_fetch_splits_crowded_tiles_and_merges_ways(monkeypatch, tmp_path):
    asked = []

    def fake(query, server=None):
        asked.append(query)
        if "(0,0,1.0,1.0)" in query:
            raise landmask.TileTooBig("Query run out of memory")
        way = {"type": "way", "id": 7, "nodes": [1, 2], "geometry": [{"lat": 0.1, "lon": 0.1}, {"lat": 0.2, "lon": 0.2}]}
        return {"elements": [way]}           # the same way shows up in every quarter

    monkeypatch.setattr(landmask, "_overpass", fake)
    ways = landmask.fetch_coastline({"west": 0.2, "east": 0.8, "south": 0.2, "north": 0.8}, tmp_path, log=lambda m: None, pause=0)
    assert len(asked) == 5 and list(ways) == [7]
    assert len(list(tmp_path.glob("*.json"))) == 4   # quarters cached for a resumed build


def test_committed_sxm_mask_matches_known_places():
    mask = landmask.load(ROOT / "regions" / "land" / "sxm.json")
    assert mask.is_land(-63.055, 18.075)        # interior of Saint Martin
    assert not mask.is_land(-63.11, 18.05)      # Simpson Bay Lagoon, land on the 1.8 km ETOPO grid
    assert not mask.is_land(-63.017, 18.055)    # Oyster Pond
    assert mask.is_land(-62.98, 18.117)         # Tintamarre
    assert mask.is_land(-63.05, 18.22)          # Anguilla
    assert mask.is_land(-65.8, 18.3)            # Puerto Rico, which crosses the region's west edge
    assert not mask.is_land(-63.3, 18.0)        # open sea


def test_committed_mask_skips_the_tintamarre_pixel():
    mask = landmask.load(ROOT / "regions" / "land" / "sxm.json")
    afai = erddap.parse_csv((ROOT / "tests" / "fixtures" / "afai.csv").read_text(), sources.AFAI["variables"])
    found, stats = detect.detect(afai, threshold=0.0005, is_land=mask.is_land, pixel_deg=0.015)
    flagged = {(round(lon, 3), round(lat, 3)) for lon, lat, _ in found}
    assert (-62.975, 18.122) not in flagged and (-62.96, 18.122) in flagged
    assert stats["land"] >= 1
