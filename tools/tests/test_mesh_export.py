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
