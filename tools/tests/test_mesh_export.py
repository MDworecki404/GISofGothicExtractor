import pygltflib
import pytest

from gothic_extract.mesh_export import export_world_glb


@pytest.fixture(scope="module")
def exported(tmp_path_factory, newworld, g2_vfs):
    world, _ = newworld
    out = tmp_path_factory.mktemp("glb") / "w.glb"
    return out, export_world_glb(world, g2_vfs, out)


def test_glb_written_and_valid(exported):
    path, stats = exported
    g = pygltflib.GLTF2().load(str(path))
    assert stats.triangles > 100_000
    assert len(g.meshes[0].primitives) == stats.materials
    assert stats.textures_ok / stats.materials > 0.9


def test_bbox_matches_waynet(exported, newworld):
    _, stats = exported
    _, wd = newworld
    xs = [w.pos[0] / 100 for w in wd.waypoints]
    assert stats.bbox_min[0] <= min(xs) and max(xs) <= stats.bbox_max[0]


def _read(g, blob, acc_idx, dtype, width):
    import numpy as np

    acc = g.accessors[acc_idx]
    view = g.bufferViews[acc.bufferView]
    arr = np.frombuffer(blob, dtype=dtype, count=acc.count * width, offset=view.byteOffset)
    return arr.reshape(acc.count, width) if width > 1 else arr


def test_triangles_face_along_normals(exported):
    import numpy as np

    path, _ = exported
    g = pygltflib.GLTF2().load(str(path))
    blob = g.binary_blob()
    agree = total = 0
    for prim in g.meshes[0].primitives[:200]:
        pos = _read(g, blob, prim.attributes.POSITION, np.float32, 3)
        nrm = _read(g, blob, prim.attributes.NORMAL, np.float32, 3)
        idx = _read(g, blob, prim.indices, np.uint32, 1).reshape(-1, 3)
        a, b, c = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
        face = np.cross(b - a, c - a)
        dots = (face * nrm[idx[:, 0]]).sum(axis=1)
        agree += int((dots > 0).sum())
        total += len(dots)
    assert agree / total > 0.95


def test_triangulate_skip_lod_flag():
    from types import SimpleNamespace as NS

    from gothic_extract.mesh_export import _triangulate

    def poly(lod):
        return NS(is_portal=False, is_lod=lod, material_index=0, position_indices=[0, 1, 2], feature_indices=[0, 1, 2])

    mesh = NS(materials=[NS(name="WALL")], polygons=[poly(False), poly(True)])
    assert len(_triangulate(mesh)[0]) == 1  # G2: LOD polygons are dropped
    assert len(_triangulate(mesh, skip_lod=False)[0]) == 2  # G1: the flag is unreliable, keep everything
