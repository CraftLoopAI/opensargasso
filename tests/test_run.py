"""The JSON the site reads: settings and source links for the Data and methods view."""
import json

from pipeline import erddap, run


def test_dataset_page():
    assert erddap.dataset_page({"base": "https://x.org/erddap/", "dataset": "ds"}) == "https://x.org/erddap/griddap/ds.html"


def test_output_has_method_settings_and_source_links(tmp_path):
    assert run.main(["--region", "sxm", "--sample", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "latest.json").read_text())
    settings = data["settings"]
    for key in ("threshold", "background_block_deg", "windage", "diffusion_deg", "step_hours", "days",
                "max_particles", "radius_km", "cell_deg"):
        assert key in settings
    assert settings["risk"] == run.load_region("sxm")["risk"]
    assert data["sources"]["afai"]["url"].endswith("/griddap/noaa_aoml_atlantic_oceanwatch_AFAI_7D.html")
    assert data["sources"]["currents"]["url"].endswith("/griddap/miamicurrents.html")
    assert data["sources"]["land"]["url"].endswith("/griddap/etopo180.html")


def test_map_gets_a_subset_of_the_particles(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "MAP_PARTICLES", 100)
    assert run.main(["--region", "sxm", "--sample", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "latest.json").read_text())
    assert 50 < len(data["forecast"][0]) <= 100 < data["settings"]["max_particles"]


def test_output_has_particle_weight_and_history_records_its_source(tmp_path):
    assert run.main(["--region", "sxm", "--sample", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "latest.json").read_text())
    assert data["stats"]["particle_weight"] >= 1.0
    day = json.loads((tmp_path / "history" / "index.json").read_text())[-1]
    history = json.loads((tmp_path / "history" / f"{day}.json").read_text())
    assert history["sir_date"] is None                           # sample runs have no SIR
    assert set(history["level_source"].values()) == {"model"}
    assert set(history["level_source"]) == set(history["sites"])


def test_preview_run_leaves_the_history_alone(tmp_path):
    assert run.main(["--region", "sxm", "--sample", "--no-history", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "latest.json").exists() and (tmp_path / "reports.geojson").exists()
    assert not (tmp_path / "history").exists()
