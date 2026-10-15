import json

import pytest

from gothic_extract.__main__ import main as run_extract
from gothic_extract.geoportal import build_geoportal, load_preview_index, resolve_model

INDEX = {
    "previews": [
        {"visual": "ITPL_BLUEPLANT.3DS", "file": "itpl_blueplant.glb"},
        {"visual": "ITKE_KEY_03.3DS", "file": "itke_key_03.glb"},
        {"visual": "ITMI_ORPHAN.3DS", "file": "itmi_orphan.glb"},
    ],
}
CATALOG = {
    "ITPL_BLUEPLANT": {"visual": "ItPl_Blueplant.3ds"},
    "ITKE_DEXTER": {"visual": "ItKe_Key_03.3ds"},
    "ITKE_FINGERS": {"visual": "itke_key_03.3DS"},
    "ITRW_BOW_L_01": {"visual": "ItRw_Bow_L_01.mms"},
    "ITWR_NO_PREVIEW": {"visual": "ItWr_Scroll.3ds"},
    "ITXX_NO_VISUAL": {"visual": ""},
}


@pytest.fixture
def previews():
    return load_preview_index(INDEX)


def test_item_with_preview(previews):
    assert resolve_model("ITPL_BLUEPLANT", CATALOG, previews) == ("previews/itpl_blueplant.glb", None)


def test_visual_in_other_case_and_shared_file(previews):
    assert resolve_model("ITKE_DEXTER", CATALOG, previews) == ("previews/itke_key_03.glb", None)
    assert resolve_model("ITKE_FINGERS", CATALOG, previews) == ("previews/itke_key_03.glb", None)


def test_item_without_preview_is_null_with_reason(previews):
    assert resolve_model("ITRW_BOW_L_01", CATALOG, previews) == (None, "unsupported_visual")
    assert resolve_model("ITWR_NO_PREVIEW", CATALOG, previews) == (None, "no_preview")
    assert resolve_model("ITXX_NO_VISUAL", CATALOG, previews) == (None, "no_visual")
    assert resolve_model("ITXX_NOT_IN_CATALOG", CATALOG, previews) == (None, "no_visual")


def test_index_entry_without_matching_item_is_harmless(previews):
    files = {resolve_model(code, CATALOG, previews)[0] for code in CATALOG}
    assert "previews/itmi_orphan.glb" not in files


@pytest.fixture(scope="module")
def dist(tmp_path_factory, g2_cfg):
    src = tmp_path_factory.mktemp("full")
    run_extract(["--game", "g2nk", "--world", "NEWWORLD", "--out", str(src), "--skip-mesh"])
    dst = tmp_path_factory.mktemp("dist")
    build_geoportal(src, dst)
    return dst


def test_package_items_point_to_previews(dist):
    index = json.loads((dist / "search_index.json").read_text("utf-8"))
    items = [e for e in index["entries"] if e["type"] == "item"]
    assert all("model" in e for e in items)
    herb = next(e for e in items if e["code"] == "ITPL_PERM_HERB")
    assert herb["model"] == "previews/itpl_perm_herb.glb"
    # items only found in chests/inventories now get a preview too
    key = next(e for e in items if e["code"] == "ITKE_DEXTER")
    assert key["model"] == "previews/itke_key_03.glb"
    assert all((dist / "models" / e["model"]).exists() for e in items if e["model"])
    assert all(e["model"] is None for e in items if e["code"].startswith("ITRW_BOW"))


def test_package_layers_carry_model(dist):
    items = json.loads((dist / "items.geojson").read_text("utf-8"))["features"]
    assert all("model" in f["properties"] for f in items)
    assert all(f["properties"]["model"].startswith("previews/") for f in items if f["properties"]["model"])
    containers = json.loads((dist / "containers.geojson").read_text("utf-8"))["features"]
    assert all(f["properties"]["model"] is None for f in containers)


def test_package_version_bumped(dist):
    meta = json.loads((dist / "metadata.json").read_text("utf-8"))
    assert meta["package"]["version"] == 3
    assert meta["package"]["counts"]["search_items_with_model"] > 257
