import numpy as np

from gothic_extract.g3.actor import read_xact
from gothic_extract.g3.entities import to_world
from gothic_extract.g3.mesh import load_mesh


def test_chest_actor(g3_fs):
    els = read_xact(g3_fs.find_name("G3_Chest_Body_Chest.xact"))
    assert sorted(e.material for e in els) == ["G3_Objects_Barrelmetal_01_Diffuse_01.ximg",
                                               "G3_Objects_Wood_01_Diffuse_02.ximg"]
    assert sorted(len(e.positions) for e in els) == [792, 2247]
    assert sorted(len(e.indices) // 3 for e in els) == [444, 1142]
    for el in els:  # same convention as .xcmsh: clockwise front faces (face normal opposite to the vertex normal)
        p, t = el.positions, el.indices.reshape(-1, 3)
        face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
        assert ((face * el.normals[t].mean(axis=1)).sum(axis=1) < 0).mean() > 0.95


def test_every_actor_reads(g3_fs):
    for path in g3_fs.list(suffix=".xact"):
        els = read_xact(g3_fs.find(path))
        assert all(len(e.indices) % 3 == 0 and (not len(e.indices) or e.indices.max() < len(e.positions))
                   for e in els), path


def test_load_mesh_takes_fxa_names(g3_fs):
    assert load_mesh(g3_fs, "G3_Chest_Body_Chest.FXA")


def test_chests_sit_in_their_boxes(g3_fs, g3_cfg):
    from gothic_extract.g3.world import _load, sector_files, WorldStats

    loaded = _load(g3_fs, sector_files(g3_fs, "G3_World_01", g3_cfg.sector_exclude)[:30], WorldStats())
    checked = 0
    for x in loaded:
        vis = x.entity.props.get("eCVisualAnimation_PS")
        if vis is None or "gCInventory_PS" not in x.entity.props or x.entity.box is None:
            continue
        els = load_mesh(g3_fs, vis.props["ResourceFilePath"].value)
        if not els:  # 5 actors have no mesh at all
            continue
        pts = to_world(x.entity.world, np.vstack([e.positions for e in els]))
        lo, hi = np.array(x.entity.box[0]), np.array(x.entity.box[1])
        assert (pts.min(axis=0) >= lo - 5).all() and (pts.max(axis=0) <= hi + 5).all(), x.entity.name
        checked += 1
    assert checked > 20
