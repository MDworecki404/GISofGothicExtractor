import json
import types

from gothic_extract.g3.locations import arena_name, enclave_key, place_names
from gothic_extract.locations import (Box, WaypointIndex, arrival_index, cluster, extent, target_key, write_locations,
                                      zone_base)
from gothic_extract.validate import validate_package

CFG = types.SimpleNamespace(anchor_lon=0.0, anchor_lat=0.0, anchor_h=0.0, key="g1")


def box(x0, z0, x1, z1, y=0.0):
    return Box((x0, -100.0, z0), (x1, 100.0, z1), y)


def test_zone_base_strips_suffix_and_digits():
    assert zone_base("OLDCAMP_OC") == "OLDCAMP"
    assert zone_base("ARCHOLOS2_CIT") == "ARCHOLOS"
    assert zone_base("newcamp_snow_nco") == "NEWCAMP"


def test_cluster_joins_touching_boxes_and_splits_distant_ones():
    groups = cluster([box(0, 0, 1000, 1000), box(900, 900, 2000, 2000), box(50000, 0, 51000, 1000)])
    assert sorted(len(g) for g in groups) == [1, 2]


def test_extent_single_box_has_closed_polygon_and_union_has_none():
    center, radius, polygon = extent([box(0, 0, 3000, 4000)], CFG)
    assert radius == 25.0 and len(polygon) == 5 and polygon[0] == polygon[-1]
    _, _, polygon2 = extent([box(0, 0, 3000, 4000), box(1000, 1000, 5000, 5000)], CFG)
    assert polygon2 is None
    _, radius3, polygon3 = extent([box(10, 10, 10, 10)], CFG)
    assert radius3 is None and polygon3 is None


def test_target_key_handles_paths_and_case():
    assert target_key(r"Oldworld\OldWorld.ZEN") == "OLDWORLD"
    assert target_key("ADDON/ADDONWORLD.ZEN") == "ADDONWORLD"
    assert target_key("ORCCITY.ZEN") == "ORCCITY"


def test_arrival_index_prefers_start_points(tmp_path):
    def feat(name, vob_type, lon):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, 0, 0]},
                "properties": {"name": name, "vob_type": vob_type}}
    (tmp_path / "vobs.geojson").write_text(json.dumps({"features": [
        feat("Start", "zCVobSpot", 1), feat("START", "zCVobStartpoint", 2), feat("", "zCVob", 3)]}), encoding="utf-8")
    (tmp_path / "waypoints.geojson").write_text(json.dumps({"features": [feat("WP1", "", 4)]}), encoding="utf-8")
    index = arrival_index(tmp_path)
    assert index["START"][0] == 2 and index["WP1"][0] == 4 and "" not in index


def test_nearest_waypoint_limited_by_distance(tmp_path):
    (tmp_path / "waypoints.json").write_text(json.dumps({"nodes": [["A", 0.0, 0.0, 0.0, 0], ["B", 0.01, 0.0, 0.0, 0]]}))
    wp = WaypointIndex(tmp_path, CFG)
    assert wp.nearest([0.00001, 0.0, 0.0], CFG) == "A"
    assert wp.nearest([0.005, 0.005, 0.0], CFG) is None  # farther than WAYPOINT_MAX_M
    assert WaypointIndex(tmp_path / "none", CFG).nearest([0, 0, 0], CFG) is None


def test_g3_names_come_from_game_texts():
    names = place_names({"MAP_World_Nordmar_FireClan_01": "Klan Ognia", "GO_Enclave_Vangard": "Vengard",
                         "MAP_World_Myrtana_Vangard_01": "Vangard", "MAP_SaturasTempleKeys_Temple_01": "Wojownik"})
    assert names == {"fireclan": "Klan Ognia", "vangard": "Vengard"}
    assert enclave_key("Enclave_Lago") == "lago" and enclave_key("FireClan") == "fireclan"
    assert arena_name("Faring_Arena_City", {"faring": "Faring"}) == "Arena: Faring (miasto)"
    assert arena_name("Arena_Silden", {"silden": "Silden"}) == "Arena: Silden"


def _package(tmp_path, locations):
    pkg = tmp_path / "g1" / "kolonia"
    pkg.mkdir(parents=True)
    (pkg / "metadata.json").write_text(json.dumps({"game": "g1", "world": "WORLD", "package": {
        "version": 4, "counts": {}, "files": ["metadata.json"]}}))
    return pkg, write_locations(pkg, "g1", locations)


def _loc(id, kind, **extra):
    return {"id": id, "kind": kind, "name": "X", "name_source": "derived", "code": "X", "center": [0.0, 0.0, 0.0],
            "radius_m": None, "polygon": None, "waypoint": None, **extra}


def test_write_locations_sorts_and_registers_in_metadata(tmp_path):
    pkg, r = _package(tmp_path, [_loc("location:B", "town"), _loc("location:A", "camp"), _loc("location:C", "camp")])
    assert [l["id"] for l in r["locations"]] == ["location:A", "location:C", "location:B"]
    meta = json.loads((pkg / "metadata.json").read_text("utf-8"))
    assert meta["package"]["version"] == 5 and meta["package"]["counts"]["locations"] == 3
    assert "locations.json" in meta["package"]["files"]
    assert (pkg / "locations.json").read_bytes()[:3] != b"\xef\xbb\xbf"


def test_validator_checks_locations(tmp_path):
    from gothic_extract.validate import PackageReport, _check_locations
    pkg, _ = _package(tmp_path, [
        _loc("location:A", "camp", waypoint="NOPE"),
        _loc("location:B", "passage", passage={"to_world": "g1/nowhere", "to_level": "X.ZEN", "arrival": None}),
        _loc("location:C", "camp", passage={"to_world": None, "to_level": "X", "arrival": None}),
        _loc("location:D", "town", center=[0.0, float("nan"), 0.0])])
    meta = json.loads((pkg / "metadata.json").read_text("utf-8"))
    r = PackageReport("t")
    _check_locations(pkg, meta, r)
    text = "\n".join(r.errors)
    assert "waypoint 'NOPE'" in text and "to_world 'g1/nowhere'" in text
    assert "passage tylko przy kind=passage" in text and "center" in text


def test_validator_accepts_valid_locations_and_requires_file(tmp_path):
    from gothic_extract.validate import PackageReport, _check_locations
    pkg, _ = _package(tmp_path, [_loc("location:A", "camp", radius_m=12.5)])
    meta = json.loads((pkg / "metadata.json").read_text("utf-8"))
    r = PackageReport("t")
    _check_locations(pkg, meta, r)
    assert r.errors == []
    (pkg / "locations.json").unlink()
    r = PackageReport("t")
    _check_locations(pkg, meta, r)
    assert any("brak locations.json" in e for e in r.errors)
