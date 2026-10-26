import numpy as np

from gothic_extract.g3.mesh import read_xcmsh

LOW = "G3_World_Lowpoly_Landscape_01/G3_World_Landscape_Lowpoly_001.xcmsh"
CELL = "G3_Myrtana_Landscape_01/LOD/G3_Myrtana_Landscape_Cell_101.xcmsh"


def test_single_element_mesh(g3_fs):
    (el,) = read_xcmsh(g3_fs.find(LOW))
    assert el.material == "G3_World_Lowpoly_Myrtana_01_Diffuse__05.xshmat"
    assert el.positions.shape == (59, 3) and el.indices.shape == (156,)
    assert el.normals.shape == (59, 3) and el.uvs.shape == (59, 2)
    lo, hi = el.positions.min(axis=0), el.positions.max(axis=0)
    assert lo[0] >= -150125 and hi[0] <= -119999  # inside the mesh's BoundingBox (world coordinates, cm)


def test_multi_material_cell(g3_fs):
    els = read_xcmsh(g3_fs.find(CELL))
    assert len(els) == 7 and els[0].material == "G3_Nature_Ground_Grass_01_A.xshmat"
    for el in els:
        assert el.indices.max() < len(el.positions) and len(el.indices) % 3 == 0
        assert np.allclose(np.linalg.norm(el.normals, axis=1), 1.0, atol=0.02)


def test_inline_string_mesh(g3_fs):
    els = read_xcmsh(g3_fs.find("G3_World_Lowpoly_Landscape_01/G3_World_Landscape_Lowpoly_008.xcmsh"))
    assert els and els[0].material == "G3_World_Lowpoly_Nordmar_01_Diffuse_02.xshmat"


def test_every_landscape_cell_reads(g3_fs):
    for region in ("Myrtana", "Varant", "Nordmar"):
        for p in g3_fs.list(f"G3_{region}_Landscape_01/", ".xcmsh"):
            els = read_xcmsh(g3_fs.find(p))
            assert els, p
            assert all(el.indices.max() < len(el.positions) for el in els), p
