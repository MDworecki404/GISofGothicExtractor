import json
import math

import numpy as np
import pygltflib
import pytest
import zenkit

from gothic_extract.vob_models import export_vob_models, game_instance, mrm_to_glb

INST = "EXT_mesh_gpu_instancing"


def _rot_y(deg):
    """Row-major 3x3 rotation about game +Y."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [c, 0, s, 0, 1, 0, -s, 0, c]


def _quat_apply(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    v = np.array(v, dtype=float)
    return v + 2 * np.cross(u, np.cross(u, v) + w * v)


def test_game_instance_matches_world_transform():
    rot, pos = _rot_y(90), (1000.0, 200.0, -500.0)
    t, q = game_instance(pos, rot)
    local = np.array([100.0, 20.0, 30.0])  # a vertex in model space, game cm
    world_game = np.array(rot).reshape(3, 3) @ local + np.array(pos)
    expected = world_game * np.array([1, 1, -1]) / 100  # world.glb convention
    got = _quat_apply(q, local * np.array([1, 1, -1]) / 100) + np.array(t)
    assert got == pytest.approx(expected, abs=1e-6)
    assert np.linalg.norm(q) == pytest.approx(1.0)


def _read(g, blob, acc_idx, dtype, width):
    acc = g.accessors[acc_idx]
    view = g.bufferViews[acc.bufferView]
    arr = np.frombuffer(blob, dtype=dtype, count=acc.count * width, offset=view.byteOffset)
    return arr.reshape(acc.count, width)


def test_mrm_glb_is_instanced_and_faces_outward(tmp_path, g2_vfs):
    mrm = zenkit.MultiResolutionMesh.load(g2_vfs.find("ITPL_PERM_HERB.MRM").open())
    out = tmp_path / "herb.glb"
    mrm_to_glb(mrm, g2_vfs, [((0, 0, 0), _rot_y(0)), ((500, 0, 0), _rot_y(45))], out)
    g = pygltflib.GLTF2().load(str(out))
    blob = g.binary_blob()
    assert INST in g.extensionsUsed
    attrs = g.nodes[0].extensions[INST]["attributes"]
    assert g.accessors[attrs["TRANSLATION"]].count == 2
    agree = total = 0
    for prim in g.meshes[0].primitives:
        pos = _read(g, blob, prim.attributes.POSITION, np.float32, 3)
        nrm = _read(g, blob, prim.attributes.NORMAL, np.float32, 3)
        idx = _read(g, blob, prim.indices, np.uint32, 1).reshape(-1, 3)
        a, b, c = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
        dots = (np.cross(b - a, c - a) * nrm[idx[:, 0]]).sum(axis=1)
        agree += int((dots > 0).sum())
        total += len(dots)
    assert agree / total > 0.9


@pytest.fixture(scope="module")
def exported_models(tmp_path_factory, g2_vfs, newworld, catalog, script_items):
    _, wd = newworld
    out = tmp_path_factory.mktemp("models")
    export_vob_models(g2_vfs, wd, catalog, script_items, out)
    return out


def test_models_index(exported_models):
    index = json.loads((exported_models / "index.json").read_text("utf-8"))
    assert len(index["models"]) > 300
    assert sum(m["instances"] for m in index["models"]) > 10_000
    assert all((exported_models / m["file"]).exists() for m in index["models"])
    assert not any(m["visual"].startswith("NEWWORLD_PART_") for m in index["models"])
    assert {m["kind"] for m in index["models"]} == {"vob", "item"}


def test_royal_sorrel_model_has_all_ground_instances(exported_models, newworld):
    _, wd = newworld
    index = json.loads((exported_models / "index.json").read_text("utf-8"))
    herb = next(m for m in index["models"] if m["visual"] == "ITPL_PERM_HERB.3DS")
    on_ground = sum(1 for i in wd.items if i.code == "ITPL_PERM_HERB")
    assert herb["instances"] >= on_ground


def test_textures_are_shared_files_not_embedded(exported_models):
    index = json.loads((exported_models / "index.json").read_text("utf-8"))
    g = pygltflib.GLTF2().load(str(exported_models / index["models"][0]["file"]))
    assert g.images and all(img.uri and img.uri.startswith("textures/") and img.bufferView is None for img in g.images)
    assert all((exported_models / img.uri).exists() for img in g.images)
    total = sum(p.stat().st_size for p in exported_models.rglob("*") if p.is_file())
    assert total < 120 * 2**20


def test_editor_only_helpers_are_skipped(exported_models):
    index = json.loads((exported_models / "index.json").read_text("utf-8"))
    assert not any(m["visual"].startswith("INVISIBLE_") for m in index["models"])


def test_unhandled_visual_types_are_reported(exported_models):
    index = json.loads((exported_models / "index.json").read_text("utf-8"))
    assert index["unhandled"]["ASC"] > 0 and index["unhandled"]["MDS"] > 0


def test_instance_translation_has_bounds(exported_models):
    index = json.loads((exported_models / "index.json").read_text("utf-8"))
    g = pygltflib.GLTF2().load(str(exported_models / index["models"][0]["file"]))
    acc = g.accessors[g.nodes[0].extensions[INST]["attributes"]["TRANSLATION"]]
    assert acc.min and acc.max and len(acc.min) == 3


def test_game_instance_with_tilt():
    c, s = math.cos(0.4), math.sin(0.4)
    rot_x = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    rot = (np.array(_rot_y(30)).reshape(3, 3) @ rot_x).ravel().tolist()
    pos = (10.0, -20.0, 30.0)
    t, q = game_instance(pos, rot)
    local = np.array([50.0, -70.0, 90.0])
    expected = (np.array(rot).reshape(3, 3) @ local + np.array(pos)) * np.array([1, 1, -1]) / 100
    got = _quat_apply(q, local * np.array([1, 1, -1]) / 100) + np.array(t)
    assert got == pytest.approx(expected, abs=1e-6)
