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
    assert sum(m["instances"] for m in index["models"]) + index["missing_instances"] + index["hidden_instances"] == len(placements)
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


def _builder(g3_fs, tmp_path):
    from gothic_extract.g3.models import _Builder

    return _Builder(g3_fs, tmp_path / "t.glb", {}, None, 64)


def test_alpha_mode_follows_the_shader_not_the_alpha_channel(g3_fs, tmp_path):
    b = _builder(g3_fs, tmp_path)
    wall = b.materials[b.material("G3_Architecture_WallHouse_01_A.xshmat")]  # alpha channel = detail map
    leaf = b.materials[b.material("G3_Nature_Plant_Leaf_04_A.xshmat")]
    assert wall.alphaMode == "OPAQUE" and not wall.doubleSided
    assert leaf.alphaMode == "MASK" and abs(leaf.alphaCutoff - 176 / 255) < 1e-6 and leaf.doubleSided


def test_water_is_a_translucent_flat_colour(g3_fs, tmp_path):
    b = _builder(g3_fs, tmp_path)
    river = b.materials[b.material("G3_Myrtana_Water_River_01_A.xshmat")]
    assert river.alphaMode == "BLEND" and river.pbrMetallicRoughness.baseColorTexture is None
    r, g, bl, a = river.pbrMetallicRoughness.baseColorFactor
    assert bl > r and 0.3 < a < 1.0  # bluish, see-through, not the green of a DXT5nm normal map


def test_water_helpers_are_not_exported(g3_fs, tmp_path):
    from gothic_extract.g3.mesh import MeshElement

    tri = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0]], np.float32)
    els = [MeshElement(m, tri, None, None, np.array([0, 1, 2], np.uint32))
           for m in ("G3_Myrtana_Water_Sea_01_A.xshmat", "G3_Myrtana_Rivermesh_Depth_01_A.xshmat",
                     "G3_Myrtana_Water_River_01_A.xshmat")]
    b = _builder(g3_fs, tmp_path)
    mesh, tris = b.add_mesh(els, "water")
    assert tris == 1 and len(b.meshes[mesh].primitives) == 1


def _at(x, z):
    w = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, x * 100, 0, -z * 100, 1.0]  # game cm; glTF z = -game z
    return w


def test_spatial_parts_are_balanced_x_then_z():
    from gothic_extract.g3.models import spatial_parts

    rng = np.random.default_rng(1)
    pts = rng.uniform(-1000, 1000, (400, 2))
    worlds = [_at(x, z) for x, z in pts]
    part = spatial_parts(worlds, 4)
    assert sorted(set(part)) == [0, 1, 2, 3] and all(part.count(i) == 100 for i in range(4))
    gx = np.array([instance_matrix(w)[12] for w in worlds])
    gz = np.array([instance_matrix(w)[14] for w in worlds])
    low_x = np.array([p in (0, 1) for p in part])
    assert gx[low_x].max() <= gx[~low_x].min()  # parts 1-2 west of parts 3-4
    for a, b in ((0, 1), (2, 3)):  # inside a half: part a south of part b
        assert gz[np.array(part) == a].max() <= gz[np.array(part) == b].min()
    assert spatial_parts(worlds, 1) == [0] * 400


def test_vobs_split_into_parts(g3_fs, tmp_path):
    placements = node_placements(g3_fs, [NODE])
    out = tmp_path / "models"
    report = export_models(g3_fs, placements, out, max_texture=32, vobs_parts=4)
    files = sorted((tmp_path / "vobs_czesci").glob("vobs_czesc_*.glb"))
    assert [f.name for f in files] == [f"vobs_czesc_{i}.glb" for i in range(1, 5)]
    counts = []
    for f in files:
        g = gl.GLTF2().load_binary(str(f))
        assert not g.extensionsUsed and g.meshes and g.images  # plain nodes, only the textures the part uses
        counts.append(len(g.nodes))
    assert sum(counts) == report.instances and max(counts) - min(counts) <= 1


def test_opaque_materials_get_textures_without_alpha(g3_fs, tmp_path):
    # the alpha channel of an opaque material is a detail map; keep it out of the PNG so no viewer or tiler can use it
    import io

    from PIL import Image

    b = _builder(g3_fs, tmp_path)
    for name, mode in (("G3_Architecture_WallHouse_01_A.xshmat", "OPAQUE"), ("G3_Nature_Plant_Leaf_04_A.xshmat", "MASK")):
        mat = b.materials[b.material(name)]
        assert mat.alphaMode == mode
        png = b.blob.bytes()  # embedded in order of creation
        view = b.blob.views[b.images[mat.pbrMetallicRoughness.baseColorTexture.index].bufferView]
        img = Image.open(io.BytesIO(png[view.byteOffset:view.byteOffset + view.byteLength]))
        assert img.mode == ("RGB" if mode == "OPAQUE" else "RGBA"), name
