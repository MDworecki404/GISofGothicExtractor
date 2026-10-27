from gothic_extract.g3.strings import load_strings


def test_polish_strings(g3_fs):
    s = load_strings(g3_fs)
    assert s["FO_It_Plant_Perm_01"] == "Szczaw królewski"
    assert s["FO_It_Bread"] == "Chleb" and s["FO_Inog"] == "Inog"


def test_catalog(g3_catalog):
    sorrel = g3_catalog["It_Plant_Perm_01"]
    assert sorrel.name == "Szczaw królewski"
    assert sorrel.category == "Rośliny"
    assert sorrel.visual == "G3_Item_Perm_01.xcmsh"
    assert len(g3_catalog) > 750  # 783 real items on 2026-10-26 (body parts, props and deleted excluded)


def test_every_category_has_label(g3_catalog):
    assert all(d.category for d in g3_catalog.values())


def test_patched_template_wins(g3_fs, g3_templates):
    patched = [t for t in g3_templates.values() if g3_fs.source(t.path).lower().endswith(".p01")]
    assert patched


def test_template_guid_matches_index(g3_templates):
    t = g3_templates["{ff68c3ea-4b6b-49a1-9866-adf806250707}"]
    assert t.name == "It_Plant_Perm_01" and t.path.endswith("Plants_Story_It_Plant_Perm_01.tple")


def test_world_references_resolve_to_template(g3_templates):
    # world entities (creator) and inventory stacks point at the template's content entity (entity 1)
    assert g3_templates["{949268a2-8274-4859-8903-bf7a7fec50aa}"].name == "It_Plant_Perm_01"
    assert g3_templates["{aa968670-912b-40a6-9241-715851931dd2}"].name == "It_Gold"


def test_entity_inside_unreadable_group_template_resolves(g3_templates, g3_catalog):
    # NPC stacks (Abbas, Campa, Giacomo) point at an entity of the group template
    # Nature_Misc_Groups_01_G3_ItemGroup_Tablestuff_02.tple, which the entity reader cannot parse;
    # its creator (the item template) is read from the raw template-entity header instead
    t = g3_templates["{6d38c316-ef3e-445c-801e-08647deaa5a3}"]
    assert t.name in g3_catalog


def test_bow_visual_is_its_animated_actor(g3_catalog):
    # bows and crossbows have an animated mesh (eCVisualAnimation_PS) instead of a static one
    assert g3_catalog["It_Bow_01"].visual.lower().endswith(".fxa")


def test_visual_from_file_name_when_path_is_empty(g3_catalog):
    assert g3_catalog["It_Torch"].visual == "G3_Item_Misc_Torch_01.xcmsh"
