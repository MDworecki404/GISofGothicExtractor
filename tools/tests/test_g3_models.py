import json

import numpy as np
import pygltflib as gl
import pytest

from gothic_extract.g3.entities import read_node_file, to_world, walk
from gothic_extract.g3.models import (Placement, export_item_previews, export_models, instance_matrix, instance_trs,
                                      node_placements)

NODE = "G3_World_01/SysDyn_{9A103CC2-4190-4DB3-9618-0419E5445AAD}/G3_World_01_x55000y0z55000_CStat.node"
_F = np.diag([1.0, 1.0, -1.0])


def _rot(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), 0, -np.sin(a)], [0, 1, 0], [np.sin(a), 0, np.cos(a)]])


def test_instance_matches_world_transform():
    m = np.eye(4)
    m[:3, :3] = _rot(30) * 1.7  # rotated and scaled, row vectors
    m[3, :3] = [1000.0, 200.0, -3000.0]
    world = list(m.flatten())
    p = np.array([[10.0, 20.0, 30.0], [-5.0, 0.0, 7.0]])
    expected = (to_world(world, p) @ _F) / 100  # game world -> glTF
    local = (p @ _F) / 100  # mesh vertices in glTF
    n = np.array(instance_matrix(world)).reshape(4, 4, order="F")
    assert np.allclose(local @ n[:3, :3].T + n[:3, 3], expected)
    t, q, s = instance_trs(world)
    x, y, z, w = q
    rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    assert np.allclose(local @ (rot * np.array(s)).T + np.array(t), expected)


@pytest.fixture(scope="module")
def small_models(g3_fs, tmp_path_factory):
    placements = node_placements(g3_fs, [NODE])
    out = tmp_path_factory.mktemp("models") / "models"
    report = export_models(g3_fs, placements, out, max_texture=32)
    return placements, out, report


def test_node_placements(g3_fs):
    placements = node_placements(g3_fs, [NODE])
    meshes = sum(1 for e in walk(read_node_file(g3_fs.find(NODE))) if "eCVisualMeshStatic_PS" in e.props)
    assert len(placements) == meshes and all(p.kind == "vob" for p in placements)
    assert all(isinstance(p, Placement) and len(p.world) == 16 for p in placements)


def test_models_and_vobs_files(small_models):
    placements, out, report = small_models
    index = json.loads((out / "index.json").read_text("utf-8"))
    assert sum(m["instances"] for m in index["models"]) + index["missing_instances"] == len(placements)
    assert isinstance(index["missing"], list)
    assert report.models == len(index["models"]) and report.instances == sum(m["instances"] for m in index["models"])
    g = gl.GLTF2().load_binary(str(out / index["models"][0]["file"]))
    assert "EXT_mesh_gpu_instancing" in g.extensionsUsed and g.images and g.images[0].uri.startswith("textures/")
    vobs = gl.GLTF2().load_binary(str(out.parent / "vobs.glb"))
    assert len(vobs.nodes) == report.instances and not vobs.extensionsUsed
    assert list((out / "textures").glob("*.png"))


def test_item_previews(g3_fs, g3_catalog, tmp_path):
    out = tmp_path / "models" / "previews"
    report = export_item_previews(g3_fs, {"It_Plant_Perm_01": g3_catalog["It_Plant_Perm_01"]}, out)
    (entry,) = report.entries
    assert entry["visual"] == "G3_Item_Perm_01.xcmsh" and entry["codes"] == ["It_Plant_Perm_01"]
    g = gl.GLTF2().load_binary(str(out / entry["file"]))
    acc = g.accessors[g.meshes[0].primitives[0].attributes.POSITION]
    assert abs(min(acc.min[1] for _ in [0])) < 1e-4  # stands on y = 0
    assert abs(acc.min[0] + acc.max[0]) < 0.05 and abs(acc.min[2] + acc.max[2]) < 0.05  # centred
    assert g.images[0].uri.startswith("../textures/")


def test_preview_model_for_g3_visual():
    from gothic_extract.geoportal import resolve_model

    catalog = {"It_Plant_Perm_01": {"visual": "G3_Item_Perm_01.xcmsh"}}
    previews = {"G3_ITEM_PERM_01.XCMSH": "previews/g3_item_perm_01.glb",
                "IT_WEAPON_RANGED_BOW_01.FXA": "previews/it_weapon_ranged_bow_01.glb"}
    assert resolve_model("It_Plant_Perm_01", catalog, previews) == ("previews/g3_item_perm_01.glb", None)
    bow = {"It_Bow_01": {"visual": "It_Weapon_Ranged_Bow_01.FXA"}}
    assert resolve_model("It_Bow_01", bow, previews) == ("previews/it_weapon_ranged_bow_01.glb", None)


def test_world_placements(g3_fs, g3_cfg, g3_world, g3_templates):
    from gothic_extract.g3.models import world_placements

    placements, unreadable = world_placements(g3_fs, g3_cfg, "G3_World_01", g3_templates)
    wd, _ = g3_world
    items = [p for p in placements if p.kind == "item"]
    assert len(items) == len(wd.items)  # every item lying in the world gets its model (bows: animated actors)
    assert any(p.mesh == "G3_Item_Perm_01.xcmsh" for p in items)
    assert sum(1 for p in placements if p.mesh.lower().startswith("g3_chest_body_chest")) > 900  # chests
    assert unreadable < 50


def test_container_previews(g3_fs, tmp_path):
    out = tmp_path / "models" / "previews"
    report = export_item_previews(g3_fs, {}, out, extra_visuals=["G3_Chest_Body_Chest.FXA"])
    (entry,) = report.entries
    assert entry["visual"] == "G3_Chest_Body_Chest.FXA" and entry["codes"] == []


def test_sector_names_include_level_meshes(g3_fs, g3_cfg):
    from gothic_extract.g3.models import node_files
    from gothic_extract.g3.world import sector_names

    names = sector_names(g3_fs, "G3_World_01", g3_cfg.sector_exclude, True)
    assert "G3_Myrtana_01_Levelmesh_01" in names  # sectors with buildings have no entity file
    files = node_files(g3_fs, "G3_World_01", names)
    assert any("Levelmesh" in p for p in files) and not any("Lowpoly" in p for p in files)
