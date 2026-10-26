import pytest

from gothic_extract.g3.entities import read_entity_file, read_template, translation, walk


@pytest.fixture(scope="module")
def silden_path(g3_fs):
    return next(p for p in g3_fs.list("G3_World_01/", ".lrentdat") if p.endswith("Silden_NPC_01.lrentdat"))


def test_silden_reads_to_the_end(g3_fs, silden_path):
    ents, box = read_entity_file(g3_fs.find(silden_path))  # FormatError when the object is not read to its end
    orc = next(e for e in walk(ents) if e.name == "Orc_Elite_02")
    assert "gCNPC_PS" in orc.props and "gCInventory_PS" in orc.props
    assert orc.creator is not None and orc.creator.startswith("{")
    assert {c.name for c in orc.children} == {"Orc_Head_S02", "Orc_Body_Elite_S00"}


def test_positions_inside_context_box(g3_fs, silden_path):
    ents, (lo, hi) = read_entity_file(g3_fs.find(silden_path))
    for e in walk(ents):
        if e.props:  # the root carries no property sets
            assert all(lo[i] - 1 <= e.pos[i] <= hi[i] + 1 for i in range(3)), e.name


def test_child_uses_world_matrix(g3_fs, silden_path):
    ents, _ = read_entity_file(g3_fs.find(silden_path))
    nested = [c for e in walk(ents) for c in e.children if e.props]
    assert nested, "no entity nested under an entity with property sets"
    # an NPC's head/body sit under the NPC; their position is the world translation
    assert all(c.pos == translation(c.world) for c in nested)
    assert any(c.pos != translation(c.local) for c in nested)


def test_template(g3_fs):
    t = read_template(g3_fs.find("Items/Items/Items_Story/Plants_Story_It_Plant_Perm_01.tple"))
    assert t.name == "It_Plant_Perm_01" and "gCItem_PS" in t.props
    assert t.guid == "{ff68c3ea-4b6b-49a1-9866-adf806250707}"


def test_template_with_inline_strings(g3_fs):
    t = read_template(g3_fs.find("Enclaves/Enclaves/Nordmar_Enclaves_Fireclan.tple"))
    assert t.name == "Fireclan" and "gCEnclave_PS" in t.props


@pytest.mark.slow
def test_story_npcs_in_sysdyn(g3_fs):
    # named story characters (Inog of Silden) live in the dynamic sector SysDyn_{…}, not in the town sectors
    path = next(p for p in g3_fs.list("G3_World_01/SysDyn_", ".lrentdat"))
    ents, _ = read_entity_file(g3_fs.find(path))
    inog = next(e for e in walk(ents) if e.name == "Inog")
    assert "gCNPC_PS" in inog.props and "gCInventory_PS" in inog.props


@pytest.mark.slow
def test_every_sector_file_parses(g3_fs):
    """Every <sector>/<sector>.lrentdat outside developer test sectors parses to its last byte.

    Not covered: empty {GUID}.lrentdat stubs (10/124 bytes) and two sectors in the older inline-string variant
    (GENOMEDL version 0x38, no GENOMFLE header): Faring_VFX and MoraSul_Temple_Lights_01 (lights, effects).
    """
    legacy = []
    for p in g3_fs.list("G3_World_01/", ".lrentdat"):
        folder, name = p.split("/")[-2:]
        if name != folder + ".lrentdat" or "test" in p.lower():
            continue
        data = g3_fs.find(p)
        if not data.startswith(b"GENOMFLE"):
            legacy.append(folder)
            continue
        read_entity_file(data)
    assert sorted(legacy) == ["G3_Myrtana_01_Faring_VFX", "G3_Varant_01_MoraSul_Temple_Lights_01"]


NODE = "G3_World_01/SysDyn_{9A103CC2-4190-4DB3-9618-0419E5445AAD}/G3_World_01_x55000y0z55000_CStat.node"


def test_node_file_reads_to_the_end(g3_fs):
    from gothic_extract.g3.entities import read_node_file

    ents = list(walk(read_node_file(g3_fs.find(NODE))))
    assert len(ents) == 1524
    meshes = [e for e in ents if "eCVisualMeshStatic_PS" in e.props]
    assert any(e.props["eCVisualMeshStatic_PS"].props["ResourceFilePath"].value == "G3_Object_Pelt_01.xcmsh"
               for e in meshes)


def test_world_matrix_places_mesh_inside_entity_box(g3_fs):
    import numpy as np

    from gothic_extract.g3.entities import read_node_file, to_world
    from gothic_extract.g3.mesh import load_mesh

    checked = 0
    for e in walk(read_node_file(g3_fs.find(NODE))):
        vis = e.props.get("eCVisualMeshStatic_PS")
        els = load_mesh(g3_fs, vis.props["ResourceFilePath"].value) if vis else None
        if not els or e.box is None:
            continue
        pts = to_world(e.world, np.vstack([el.positions for el in els]))
        lo, hi = np.array(e.box[0]), np.array(e.box[1])
        assert (pts.min(axis=0) >= lo - 5).all() and (pts.max(axis=0) <= hi + 5).all(), e.name
        checked += 1
        if checked == 300:
            break
    assert checked == 300
