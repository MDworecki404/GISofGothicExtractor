import json
import struct

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
        "quests.json": {"version": 2, "quests": [{
            "id": "quest:CH1_X", "worlds": ["WORLD"], "places": [], "order": "script", "stages_with_place": 0,
            "stages": [{"seq": 1, "requires": [], "requires_source": "script_order", "level": 0, "alternative_group": None,
                        "place": None}],
            "characters": [{"code": "BOB", "in_index": True, "id": "character:BOB"}],
            "items": [{"code": "ITMI_NOPE", "in_index": False, "id": None}]}]},
        "metadata.json": {"game": "g1", "world": "WORLD", "anchor": {}, "axes": {}, "gltf_axes": "",
                          "movement_speeds_m_s": {}, "movement_speeds_animations": {}, "guild_names": {"GRD": "Strażnik"},
                          "package": {"version": 6, "files": ["metadata.json", "locations.json"], "counts": {
                              "search_items": 1, "search_items_with_model": 0, "search_characters": 1, "items": 1,
                              "containers": 0, "npcs": 1, "character_places": 0, "quests": 1, "locations": 0}}},
        "locations.json": {"version": 1, "game": "g1", "world": "WORLD", "locations": []},
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


def test_description_must_differ_from_name(pkg):
    _edit(pkg, "items.geojson", lambda fc: fc["features"][0]["properties"].update(name="Jabłko", description="Jabłko"))
    assert any("niepoprawnym description" in e for e in validate_package(pkg, "g1").errors)


def test_valid_description_passes(pkg):
    _edit(pkg, "items.geojson", lambda fc: fc["features"][0]["properties"].update(name="Jabłko", description="Zielone"))
    assert validate_package(pkg, "g1").errors == []


def test_warns_about_shared_names_without_description(pkg):
    def add(fc):
        fc["features"][0]["properties"]["name"] = "Mikstura"
        fc["features"].append(_feature("item-1", code="ITPO_MANA_01", name="Mikstura"))
    _edit(pkg, "items.geojson", add)
    assert any("1 nazw przy kilku kodach" in w for w in validate_package(pkg, "g1").warnings)


# --- waypoints.json -----------------------------------------------------------------------------------------------

def _waypoints(pkg, nodes=None, edges=None, **top):
    nodes = nodes if nodes is not None else [["A", 0.0, 0.0, 1.0, 0], ["B", 0.0001, 0.0, 1.0, 0],
                                             ["C", 0.0002, 0.0, 1.0, 1], ["D", 0.0003, 0.0, 1.0, 0]]
    edges = edges if edges is not None else [[0, 1], [1, 2]]
    data = {"version": 1, "game": "g1", "world": "WORLD", "nodes": nodes, "edges": edges, **top}
    (pkg / "waypoints.json").write_text(json.dumps(data), encoding="utf-8")
    _edit(pkg, "metadata.json", lambda m: m["package"]["counts"].update(waypoints=len(nodes),
                                                                         waypoint_edges=len(edges)))


def _write_glb(path, lo, hi):
    doc = json.dumps({"asset": {"version": "2.0"}, "accessors": [{"min": lo, "max": hi}],
                      "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}).encode()
    doc += b" " * (-len(doc) % 4)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(doc)) + struct.pack("<II", len(doc), 0x4E4F534A) + doc)


def test_valid_waypoints_report_components(pkg):
    _waypoints(pkg)
    r = validate_package(pkg, "g1")
    assert r.errors == []
    assert r.counts["waypoint_components"] == 2 and r.counts["waypoints_in_largest_component"] == 3


@pytest.mark.parametrize("edges, text", [
    ([[0, 9]], "spoza nodes"), ([[1, 1]], "pętli"), ([[0, 1], [1, 0]], "powtórzonych krawędzi"),
    ([[2, 1]], "większym indeksem")])
def test_bad_waypoint_edges(pkg, edges, text):
    _waypoints(pkg, edges=edges)
    assert any(text in e for e in validate_package(pkg, "g1").errors)


def test_waypoint_names_unique_and_no_tot(pkg):
    _waypoints(pkg, nodes=[["A", 0, 0, 0, 0], ["A", 0, 0, 0, 0], ["TOT", 0, 0, 0, 0]], edges=[])
    errors = validate_package(pkg, "g1").errors
    assert any("powtórzonych nazw" in e for e in errors) and any("TOT" in e for e in errors)


def test_waypoints_version_checked(pkg):
    _waypoints(pkg, version=2)
    assert any("version" in e for e in validate_package(pkg, "g1").errors)


def test_waypoints_geojson_not_allowed_in_package(pkg):
    (pkg / "waypoints.geojson").write_text("{}", encoding="utf-8")
    assert any("waypoints.geojson" in e for e in validate_package(pkg, "g1").errors)


def test_waypoints_outline(pkg):
    _edit(pkg, "metadata.json", lambda m: m.update(anchor={"lon": 0.0, "lat": 0.0, "h": 0.0}))
    _waypoints(pkg, nodes=[["IN", 0.0, 0.0, 0, 0], ["OUT", 0.01, 0.0, 0, 0]], edges=[[0, 1]])  # 0.01° ≈ 1113 m
    _write_glb(pkg / "world.glb", [-10, 0, -10], [100, 10, 10])
    errors = validate_package(pkg, "g1").errors
    assert any("poza obrysem" in e and "OUT" in e for e in errors) and not any("IN'" in e for e in errors)


def test_quest_order_errors_are_reported(pkg):
    path = pkg / "quests.json"
    data = json.loads(path.read_text("utf-8"))
    st = data["quests"][0]["stages"][0]
    st.update(requires=[1])                       # requires itself
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert any("requires" in e for e in validate_package(pkg, "g1").errors)
    st.update(requires=[], requires_source="script_order", level=3)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert any("level" in e for e in validate_package(pkg, "g1").errors)
    st.update(level=0)
    data["quests"][0]["order"] = "dependency"      # 0 of 1 stages has a known source
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert any("order" in e for e in validate_package(pkg, "g1").errors)
