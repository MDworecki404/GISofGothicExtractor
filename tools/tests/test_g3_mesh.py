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


def test_old_object_version_with_name_and_guid(g3_fs):
    # class version 1: the object's name and GUID come before the properties
    (el, *_) = read_xcmsh(g3_fs.find_name("G3_Object_Shelfstuff_Plates_03.xcmsh"))
    assert len(el.positions) > 0 and el.indices.max() < len(el.positions)


def test_lod_mesh_resolves_to_its_most_detailed_mesh(g3_fs):
    from gothic_extract.g3.mesh import load_mesh

    els = load_mesh(g3_fs, "G3_Object_Interact_Alchemy_Table_01.xlmsh")
    assert els and len(els[0].positions) > 0
    assert load_mesh(g3_fs, "nie_ma_takiej.xcmsh") is None


def test_inline_material_name_is_not_prefixed_with_the_bytes_before_it(g3_fs):
    # the scanner used to accept an earlier, shifted header whose length also ends at ".xshmat"
    els = read_xcmsh(g3_fs.find("G3_Items_Armor_01/G3_ARMOR_SHIELD_TOWER_01.xcmsh"))
    assert {el.material for el in els} == {"G3_Weapons_Shields_01_A.xshmat"}
