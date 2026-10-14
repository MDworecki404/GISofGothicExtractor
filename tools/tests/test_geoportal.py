import json
from collections import Counter

import pytest

from gothic_extract.__main__ import main as run_extract
from gothic_extract.geoportal import build_geoportal


@pytest.fixture(scope="module")
def dist(tmp_path_factory, g2_cfg):
    src = tmp_path_factory.mktemp("full")
    run_extract(["--game", "g2nk", "--world", "NEWWORLD", "--out", str(src), "--skip-mesh", "--skip-models"])
    dst = tmp_path_factory.mktemp("dist")
    build_geoportal(src, dst)
    return dst


@pytest.fixture(scope="module")
def index(dist):
    return json.loads((dist / "search_index.json").read_text("utf-8"))


def _entry(index, type_, name):
    return next(e for e in index["entries"] if e["type"] == type_ and e["name"] == name)


def test_files_present(dist):
    for fn in ["search_index.json", "items.geojson", "containers.geojson", "characters.geojson",
               "character_places.geojson", "metadata.json", "README.md"]:
        assert (dist / fn).exists(), fn


def test_royal_sorrel_places(index):
    e = _entry(index, "item", "Szczaw królewski")
    assert e["code"] == "ITPL_PERM_HERB"
    assert len(e["places"]) == 11
    assert {p["kind"] for p in e["places"]} == {"ground", "script"}


def test_gold_comes_from_chests_and_npcs(index):
    kinds = Counter(p["kind"] for p in _entry(index, "item", "Złoto")["places"])
    assert kinds["container"] > 50 and kinds["npc"] > 0 and kinds["ground"] > 0


def test_harad_is_a_character_with_routine(index):
    e = _entry(index, "character", "Harad")
    kinds = Counter(p["kind"] for p in e["places"])
    assert kinds["spawn"] >= 1 and kinds["routine"] >= 1
    assert any(p["kind"] == "routine" and "–" in p["label"] for p in e["places"])


def test_only_unique_characters(index):
    names = [e["name"] for e in index["entries"] if e["type"] == "character"]
    assert len(names) == len(set(names))
    assert not {"Bandyta", "Strażnik miejski"} & set(names)
    # "Wilk" is both the wolf monster (many inserts) and Wolf the mercenary (SLD_811_WOLF): only he counts
    codes = {e["code"] for e in index["entries"] if e["type"] == "character"}
    assert "SLD_811_WOLF" in codes and "WOLF" not in codes
    # generic monster species that just happen to appear once in Khorinis
    assert not {"Chrząszcz", "Cieniostwór", "Dzik"} & set(names)
    assert "Pan cienia Inubis" in names
    # humans with a second incarnation in another world (e.g. the ship to Irdorath) stay
    assert {"Bennet", "Cipher", "Lee"} <= set(names)
    assert len(names) > 100


def test_every_place_has_coordinates(index):
    for e in index["entries"]:
        assert e["places"], e["id"]
        for p in e["places"]:
            assert all(isinstance(p[k], (int, float)) for k in ("lon", "lat", "h")), e["id"]


def test_character_layers_only_unique(dist, index):
    chars = json.loads((dist / "characters.geojson").read_text("utf-8"))["features"]
    places = json.loads((dist / "character_places.geojson").read_text("utf-8"))["features"]
    codes = {e["code"] for e in index["entries"] if e["type"] == "character"}
    assert {f["properties"]["code"] for f in chars} == codes
    assert {f["properties"]["npc_code"] for f in places} <= codes
    assert all("times" in f["properties"] for f in places)


def test_routine_labels_are_short(index):
    e = _entry(index, "character", "Harad")
    assert all(len(p["label"]) <= 60 for p in e["places"])


def test_merge_times():
    from gothic_extract.geoportal import summarize_times

    assert summarize_times(["08:00–12:00", "12:00–20:00"]) == "08:00–20:00"
    assert summarize_times(["22:00–07:00"]) == "22:00–07:00"
    assert summarize_times(["07:00–07:10", "07:20–07:30", "08:00–08:10", "09:00–09:10", "18:50–19:00"])         == "07:00–19:00 (z przerwami)"
