import json

import pytest

from gothic_extract.__main__ import main as run_cli
from gothic_extract.catalog import ItemDef
from gothic_extract.export_geojson import write_outputs
from gothic_extract.mesh_export import MeshStats
from gothic_extract.records import ItemRec, WorldData


@pytest.fixture(scope="module")
def full_run(tmp_path_factory, g2_cfg):
    out = tmp_path_factory.mktemp("out")
    run_cli(["--game", "g2nk", "--world", "NEWWORLD", "--out", str(out), "--skip-mesh"])
    return out


@pytest.fixture
def small_inputs(g2_cfg):
    wd = WorldData(items=[ItemRec("ITXX_NIE_MA", 1, (0.0, 0.0, 0.0), "zen", None, None)])
    catalog = {"ITMI_GOLD": ItemDef("ITMI_GOLD", "Złoto", "Różne", 1, 0, 1, "", "")}
    return dict(cfg=g2_cfg, world_name="TEST", wd=wd, catalog=catalog, npcs=[], script_items=[], mesh=MeshStats())


def test_end_to_end(full_run):
    items = json.loads((full_run / "items.geojson").read_text("utf-8"))
    names = {f["properties"]["name"] for f in items["features"]}
    assert "Szczaw królewski" in names


def test_utf8_raw_bytes(full_run):
    raw = (full_run / "items.geojson").read_bytes()
    assert "królewski".encode("utf-8") in raw and rb"\u00f3" not in raw


def test_unknown_code_does_not_crash(tmp_path, small_inputs):
    write_outputs(tmp_path, **small_inputs)
    items = json.loads((tmp_path / "items.geojson").read_text("utf-8"))
    feat = next(f for f in items["features"] if f["properties"]["code"] == "ITXX_NIE_MA")
    assert feat["properties"]["name"] is None
    assert "ITXX_NIE_MA" in (tmp_path / "report.txt").read_text("utf-8")


def test_every_feature_has_game_pos(full_run):
    for fn in ["items", "containers", "npcs", "npc_routines", "vobs", "freepoints"]:
        fc = json.loads((full_run / f"{fn}.geojson").read_text("utf-8"))
        assert fc["features"], fn
        assert all("game_pos" in f["properties"] and "height_m" in f["properties"] for f in fc["features"]), fn


def test_all_output_files_present(full_run):
    for fn in ["items.geojson", "containers.geojson", "npcs.geojson", "npc_routines.geojson", "vobs.geojson",
               "waypoints.geojson", "freepoints.geojson", "catalog_items.json", "metadata.json", "report.txt"]:
        assert (full_run / fn).exists(), fn
