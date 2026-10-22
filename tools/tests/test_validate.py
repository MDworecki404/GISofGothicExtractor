import json

import pytest

from gothic_extract.validate import validate_package


def _feature(fid, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0, 0]}, "properties": {"id": fid, **props}}


def _fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


@pytest.fixture
def pkg(tmp_path):
    """Smallest consistent v4 package: one item on the ground, one character, one quest."""
    spot = {"kind": "ground", "lon": 0, "lat": 0, "h": 0, "label": "na ziemi", "ref": "item-0", "amount": 1}
    files = {
        "items.geojson": _fc(_feature("item-0", code="ITFO_APPLE")),
        "containers.geojson": _fc(),
        "characters.geojson": _fc(_feature("npc-0")),
        "npcs.geojson": _fc(_feature("npc-0", guild_name="GRD")),
        "character_places.geojson": _fc(),
        "search_index.json": {"version": 1, "entries": [
            {"id": "item:ITFO_APPLE", "type": "item", "model": None, "places": [spot]},
            {"id": "character:BOB", "type": "character", "places": [{**spot, "kind": "spawn", "ref": "npc-0"}]},
            {"id": "quest:CH1_X", "type": "quest", "places": []}]},
        "quests.json": {"version": 1, "quests": [{
            "id": "quest:CH1_X", "worlds": ["WORLD"], "places": [],
            "characters": [{"code": "BOB", "in_index": True, "id": "character:BOB"}],
            "items": [{"code": "ITMI_NOPE", "in_index": False, "id": None}]}]},
        "metadata.json": {"game": "g1", "world": "WORLD", "anchor": {}, "axes": {}, "gltf_axes": "",
                          "movement_speeds_m_s": {}, "movement_speeds_animations": {}, "guild_names": {"GRD": "Strażnik"},
                          "package": {"version": 4, "files": ["metadata.json"], "counts": {
                              "search_items": 1, "search_items_with_model": 0, "search_characters": 1, "items": 1,
                              "containers": 0, "npcs": 1, "character_places": 0, "quests": 1}}},
    }
    for name, obj in files.items():
        (tmp_path / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _edit(pkg, name, fn):
    path = pkg / name
    obj = json.loads(path.read_text("utf-8"))
    fn(obj)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_consistent_package_passes(pkg):
    assert validate_package(pkg, "g1").errors == []


def test_count_mismatch(pkg):
    _edit(pkg, "metadata.json", lambda m: m["package"]["counts"].update(items=5))
    assert any("counts.items" in e for e in validate_package(pkg, "g1").errors)


def test_duplicate_index_id(pkg):
    _edit(pkg, "search_index.json", lambda i: i["entries"].append(dict(i["entries"][0])))
    assert any("powtórzonych id" in e for e in validate_package(pkg, "g1").errors)


def test_dangling_ref(pkg):
    _edit(pkg, "search_index.json", lambda i: i["entries"][0]["places"][0].update(ref="item-99"))
    assert any("ze ref spoza items" in e for e in validate_package(pkg, "g1").errors)


def test_quest_without_quests_json_entry(pkg):
    _edit(pkg, "quests.json", lambda q: q["quests"].clear())
    assert any("bez wpisu w quests.json" in e for e in validate_package(pkg, "g1").errors)


def test_in_index_pointing_nowhere(pkg):
    _edit(pkg, "quests.json", lambda q: q["quests"][0]["characters"][0].update(id="character:GHOST"))
    assert any("nie pasuje do indeksu" in e for e in validate_package(pkg, "g1").errors)


def test_missing_listed_file_and_bad_json(pkg):
    _edit(pkg, "metadata.json", lambda m: m["package"]["files"].append("world.glb"))
    (pkg / "extra.json").write_text("{", encoding="utf-8")
    errors = validate_package(pkg, "g1").errors
    assert any("brak world.glb" in e for e in errors) and any("extra.json" in e for e in errors)


def test_guild_missing_from_guild_names(pkg):
    _edit(pkg, "metadata.json", lambda m: m["guild_names"].clear())
    assert any("guild_names bez gildii" in e for e in validate_package(pkg, "g1").errors)
