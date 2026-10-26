import numpy as np
import pygltflib as gl
import pytest

from gothic_extract.g3.mesh import read_xcmsh
from gothic_extract.g3.terrain import export_terrain_glb, landscape_meshes


def _accessor(g, blob, idx):
    acc = g.accessors[idx]
    view = g.bufferViews[acc.bufferView]
    dtype = {gl.FLOAT: np.float32, gl.UNSIGNED_INT: np.uint32}[acc.componentType]
    width = {gl.VEC3: 3, gl.VEC2: 2, gl.SCALAR: 1}[acc.type]
    arr = np.frombuffer(blob[view.byteOffset:view.byteOffset + view.byteLength], dtype=dtype)
    return arr.reshape(-1, width) if width > 1 else arr


@pytest.fixture(scope="module")
def small_terrain(g3_fs, tmp_path_factory):
    paths = g3_fs.list("G3_Myrtana_Landscape_01/", ".xcmsh")[:6]
    out = tmp_path_factory.mktemp("terrain") / "world.glb"
    stats = export_terrain_glb(g3_fs, paths, out, max_texture=64)
    return paths, out, stats


def test_landscape_meshes_cover_all_regions(g3_fs):
    paths = landscape_meshes(g3_fs)
    assert any("Myrtana" in p for p in paths) and any("Varant" in p for p in paths) and any("Nordmar" in p for p in paths)
    assert not any("Lowpoly" in p for p in paths)


def test_triangles_and_bbox(g3_fs, small_terrain):
    paths, out, stats = small_terrain
    els = [el for p in paths for el in read_xcmsh(g3_fs.find(p))]
    assert stats.triangles == sum(len(el.indices) // 3 for el in els)
    src = np.vstack([el.positions for el in els])
    # glTF = (x/100, y/100, -z/100)
    assert np.allclose(stats.bbox_min, [src[:, 0].min() / 100, src[:, 1].min() / 100, -src[:, 2].max() / 100], atol=0.01)
    assert stats.textures_ok > 0 and not stats.textures_missing


def test_front_faces_match_normals(small_terrain):
    _, out, _ = small_terrain
    g = gl.GLTF2().load_binary(str(out))
    blob = g.binary_blob()
    agree = total = 0
    for prim in g.meshes[0].primitives:
        pos = _accessor(g, blob, prim.attributes.POSITION)
        nrm = _accessor(g, blob, prim.attributes.NORMAL)
        tri = _accessor(g, blob, prim.indices).reshape(-1, 3)
        face = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
        agree += int(((face * nrm[tri].mean(axis=1)).sum(axis=1) > 0).sum())
        total += len(tri)
    assert agree > 0.95 * total  # counter-clockwise front faces, as glTF expects
