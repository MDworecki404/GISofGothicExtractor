import struct

import pytest

from gothic_extract.g3.genome import FormatError, Reader, iter_property_objects, parse_genomfle, read_property_object

PLANT = "Items/Items/Items_Story/Plants_Story_It_Plant_Perm_01.tple"


def test_string_table(g3_fs):
    gf = parse_genomfle(g3_fs.find(PLANT))
    assert "It_Plant_Perm_01" in gf.strings and "gCItem_PS" in gf.strings


def test_context_object(g3_fs):
    path = next(p for p in g3_fs.list("G3_World_01/", ".lrentdat") if p.endswith("Silden_NPC_01.lrentdat"))
    data = g3_fs.find(path)
    gf = parse_genomfle(data)
    r = Reader(data, 14)
    assert r.take(8) == b"GENOMEDL"
    r.u16()
    obj = read_property_object(r, gf.strings)
    assert obj.cls == "eCEntityDynamicContext" and set(obj.props) == {"ID", "ContextBox"}
    # the context object spans the whole entity tree and ends exactly at the string table
    assert r.pos == obj.data_end == struct.unpack("<I", data[10:14])[0]


def test_bad_magic():
    with pytest.raises(FormatError):
        parse_genomfle(b"NOTGENOM" + b"\0" * 20)


def test_item_template_props(g3_fs):
    objs = list(iter_property_objects(parse_genomfle(g3_fs.find(PLANT))))
    items = [o for o in objs if o.cls == "gCItem_PS"]
    assert items
    for o in items:
        assert isinstance(o.props["GoldValue"].value, int) and o.props["GoldValue"].value >= 0
        assert isinstance(o.props["Category"].value, int)
    mesh = next(o for o in objs if o.cls == "eCVisualMeshDynamic_PS")
    assert mesh.props["ResourceFilePath"].value == "G3_Item_Perm_01.xcmsh"


def test_template_with_inline_strings(g3_fs):
    # some .tple files have no GENOMFLE header: the string list sits after the GENOMETP tag
    gf = parse_genomfle(g3_fs.find("Enclaves/Enclaves/Nordmar_Enclaves_Fireclan.tple"))
    assert "Fireclan" in gf.strings and "gCEnclave_PS" in gf.strings
    assert any(o.cls == "gCEnclave_PS" for o in iter_property_objects(gf))


def test_template_body_offset(g3_fs):
    # GENOMFLE header (14) + b"GENOMETP" (8) + u16 62, u16 1, u8 1, u32 146 + 146 u16 string indexes
    assert parse_genomfle(g3_fs.find(PLANT)).body == 14 + 8 + 9 + 2 * 146


def test_navigation_point_lists(g3_fs):
    path = next(p for p in g3_fs.list("G3_World_01/", ".lrentdat") if p.endswith("Silden_NPC_01.lrentdat"))
    navs = [o for o in iter_property_objects(parse_genomfle(g3_fs.find(path))) if o.cls == "gCNavigation_PS"]
    assert navs
    pts = [g for o in navs for g in o.props["WorkingPoints"].value]
    assert pts and all(g.startswith("{") and len(g) == 38 for g in pts)
    assert all(isinstance(o.props["RoutineNames"].value, list) for o in navs)
    assert isinstance(navs[0].props["WorkingPoint"].value, (str, type(None)))


def test_entity_proxy_with_guid():
    from gothic_extract.g3.genome import decode_value

    raw = bytes.fromhex("010001" "2ebd7eb46bc9444a966dae3e53449712" "00000000")
    assert decode_value("eCEntityProxy", raw, []) == "{b47ebd2e-c96b-4a44-966d-ae3e53449712}"
    assert decode_value("eCTemplateEntityProxy", bytes.fromhex("010000"), []) is None
