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
    # key characters with guild NONE, and one person with two instance codes in this world
    assert {"Diego", "Lester", "Lares", "Gorn", "Myxir"} <= set(names)
    # quest monsters inserted exactly once in the whole game are unique (black troll, Serpentes' golem)
    assert {"Czarny troll", "Magiczny golem"} <= set(names)
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
    all_codes = {c for e in index["entries"] if e["type"] == "character" for c in e["codes"]}
    assert {f["properties"]["npc_code"] for f in places} <= all_codes
    assert all("times" in f["properties"] for f in places)


def test_routine_labels_are_short(index):
    e = _entry(index, "character", "Harad")
    assert all(len(p["label"]) <= 60 for p in e["places"])


def test_merge_times():
    from gothic_extract.geoportal import summarize_times

    assert summarize_times(["08:00–12:00", "12:00–20:00"]) == "08:00–20:00"
    assert summarize_times(["22:00–07:00"]) == "22:00–07:00"
    assert summarize_times(["07:00–07:10", "07:20–07:30", "08:00–08:10", "09:00–09:10", "18:50–19:00"])         == "07:00–19:00 (z przerwami)"


def test_midnight_spans():
    from gothic_extract.geoportal import summarize_times

    assert summarize_times(["08:00–23:00", "23:00–08:00"]) == "cały dzień"
    assert summarize_times(["07:00–12:00", "22:00–07:00"]) == "22:00–12:00"


def test_no_dead_npc_pseudo_routine(index):
    for e in index["entries"]:
        assert not any(p.get("routine") == "TOT" for p in e["places"]), e["name"]


def test_every_ref_resolves(dist, index):
    layer_for = {"ground": "items", "script": "items", "container": "containers", "npc": "npcs",
                 "spawn": "npcs", "routine": "character_places"}
    ids = {name: {f["properties"]["id"] for f in json.loads((dist / f"{name}.geojson").read_text("utf-8"))["features"]}
           for name in set(layer_for.values())}
    for e in index["entries"]:
        for p in e["places"]:
            assert p["ref"] in ids[layer_for[p["kind"]]], (e["id"], p)


def test_guild_names_listed_for_guilds_in_the_world(tmp_path, g2_cfg, g2_vm):
    from gothic_extract.guilds import guild_names_pl

    src = tmp_path / "full"
    run_extract(["--game", "g2nk", "--world", "NEWWORLD", "--out", str(src), "--skip-mesh", "--skip-models"])
    dst = tmp_path / "dist"
    build_geoportal(src, dst, guild_names_pl(g2_vm))
    names = json.loads((dst / "metadata.json").read_text("utf-8"))["guild_names"]
    used = {f["properties"]["guild_name"] for f in json.loads((dst / "npcs.geojson").read_text("utf-8"))["features"]}
    assert set(names) == used
    assert names["MIL"] == "Strażnik"
