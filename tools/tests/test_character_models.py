import json

import pygltflib as gl

from gothic_extract.character_models import (Visual, _safe, _variant, build_parts,
                                              read_visuals)
from gothic_extract.geoportal import SCRIPT_DUMMIES, unique_characters


def _npc(code, name):
    return {"properties": {"code": code, "name": name, "is_human": True, "name_unique_in_game": True,
                           "inserts_in_game": 1}}


def test_script_dummies_are_not_characters():
    npcs = [_npc("ITEM_HOLDER_INST", "ItemHolder"), _npc("VLK_1_X", "Ktoś")]
    assert set(unique_characters(npcs)) == {"Ktoś"}
    assert {"ITEM_HOLDER_INST", "ITEM_HELPER_INST", "MEM_HELPER_INST"} == SCRIPT_DUMMIES


def test_texture_variants():
    v = Visual("HUMANS.MDS", "hum_body_Naked0", 3, 2, "Hum_Head_Bald", 134, 5, None)
    assert _variant("HUM_BODY_NAKED_V0_C0.TGA", "body", v) == "HUM_BODY_NAKED_V3_C2.TGA"
    assert _variant("HUM_BODY_NAKED_V0_C0.TGA", "armor", v) == "HUM_BODY_NAKED_V3_C2.TGA"
    assert _variant("BUERGER1.TGA", "armor", v) == "BUERGER1.TGA"  # armor texture stays
    assert _variant("HUM_HEAD_V0_C0.TGA", "head", v) == "HUM_HEAD_V134_C2.TGA"
    assert _variant("HUM_TEETH_V0.TGA", "head", v) == "HUM_TEETH_V5.TGA"
    assert _variant("HUM_MOUTH_V0.TGA", "head", v) == "HUM_MOUTH_V0.TGA"
    assert _safe("Hum_Head_Bald") == "hum_head_bald"


def test_human_parts_line_up(g2_vm, g2_vfs, tmp_path):
    codes = ["VLK_412_HARAD", "MAGICGOLEM"]
    visuals = read_visuals(g2_vm, codes)
    assert visuals["VLK_412_HARAD"].human and not visuals["MAGICGOLEM"].human
    models, reasons, entries = build_parts(g2_vfs, g2_vm, visuals, tmp_path / "models" / "characters")
    assert not reasons
    harad = models["VLK_412_HARAD"]
    assert harad["body"] is None and harad["armor"] and harad["head"] and harad["weapon"] is None
    by_file = {e["file"]: e for e in entries}
    armor, head = by_file[harad["armor"].split("/")[1]], by_file[harad["head"].split("/")[1]]
    assert armor["kind"] == "armor" and head["kind"] == "head"
    assert 1.6 < armor["bounds_m"]["y"] < 2.0  # a standing human in metres
    glb = gl.GLTF2().load_binary(str(tmp_path / "models" / "characters" / harad["head"].split("/")[1]))
    pos = glb.accessors[glb.meshes[0].primitives[0].attributes.POSITION]
    assert 1.5 < pos.min[1] and pos.max[1] < 2.0  # the head sits at the top of the body, in body coordinates
    golem = by_file[models["MAGICGOLEM"]["body"].split("/")[1]]
    assert golem["kind"] == "creature" and golem["triangles"] > 500
    for e in entries:
        assert e["bytes"] == (tmp_path / "models" / "characters" / e["file"]).stat().st_size
