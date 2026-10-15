import json

import pytest

from gothic_extract.__main__ import main as run_extract
from gothic_extract.geoportal import build_geoportal, load_model_index, resolve_model

INDEX = {
    "models": [
        {"visual": "ITPL_BLUEPLANT.3DS", "file": "itpl_blueplant.glb", "kind": "item", "instances": 3},
        {"visual": "NW_HARBOUR_BARREL_01.3DS", "file": "nw_harbour_barrel_01.glb", "kind": "vob", "instances": 150},
        {"visual": "NW_NATURE_STONE_01.3DS", "file": "nw_nature_stone_01.glb", "kind": "vob", "instances": 9},
    ],
    "missing": ["ITMW_BROKEN.3DS"],
}
CATALOG = {
    "ITPL_BLUEPLANT": {"visual": "ItPl_Blueplant.3ds"},
    "ITMI_BARREL": {"visual": "nw_harbour_barrel_01.3DS"},
    "ITMW_BROKEN": {"visual": "ItMw_Broken.3ds"},
    "ITWR_NO_MODEL": {"visual": "ItWr_Scroll.3ds"},
    "ITXX_NO_VISUAL": {"visual": ""},
}


@pytest.fixture
def models():
    return load_model_index(INDEX)


def test_item_with_model(models):
    assert resolve_model("ITPL_BLUEPLANT", CATALOG, models) == ("itpl_blueplant.glb", None)


def test_visual_in_other_case_and_vob_entry_is_used(models):
    # catalog visual is lower/mixed case, the index entry is a VOB of the same visual
    assert resolve_model("ITMI_BARREL", CATALOG, models) == ("nw_harbour_barrel_01.glb", None)


def test_item_without_model_is_null_with_reason(models):
    assert resolve_model("ITWR_NO_MODEL", CATALOG, models) == (None, "no_index_entry")
    assert resolve_model("ITMW_BROKEN", CATALOG, models) == (None, "missing")
    assert resolve_model("ITXX_NO_VISUAL", CATALOG, models) == (None, "no_visual")
    assert resolve_model("ITXX_NOT_IN_CATALOG", CATALOG, models) == (None, "no_visual")


def test_index_entry_without_matching_item_is_harmless(models):
    # NW_NATURE_STONE_01 has no item; it is in the map but never returned for an item
    files = {resolve_model(code, CATALOG, models)[0] for code in CATALOG}
    assert "nw_nature_stone_01.glb" not in files
    assert models["NW_NATURE_STONE_01.3DS"] == "nw_nature_stone_01.glb"


@pytest.fixture(scope="module")
def dist(tmp_path_factory, g2_cfg):
    src = tmp_path_factory.mktemp("full")
    run_extract(["--game", "g2nk", "--world", "NEWWORLD", "--out", str(src), "--skip-mesh"])
    dst = tmp_path_factory.mktemp("dist")
    build_geoportal(src, dst)
    return dst


def test_package_items_carry_model(dist):
    index = json.loads((dist / "search_index.json").read_text("utf-8"))
    items = [e for e in index["entries"] if e["type"] == "item"]
    assert all("model" in e for e in items)
    herb = next(e for e in items if e["code"] == "ITPL_PERM_HERB")
    assert herb["model"] == "itpl_perm_herb.glb"
    assert (dist / "models" / herb["model"]).exists()
    assert any(e["model"] is None for e in items)


def test_package_layers_carry_model(dist):
    items = json.loads((dist / "items.geojson").read_text("utf-8"))["features"]
    assert all("model" in f["properties"] for f in items)
    assert all((dist / "models" / f["properties"]["model"]).exists() for f in items if f["properties"]["model"])
    containers = json.loads((dist / "containers.geojson").read_text("utf-8"))["features"]
    assert all("model" in f["properties"] for f in containers)


def test_package_version_bumped(dist):
    meta = json.loads((dist / "metadata.json").read_text("utf-8"))
    assert meta["package"]["version"] == 2
    assert meta["package"]["counts"]["search_items_with_model"] > 0
