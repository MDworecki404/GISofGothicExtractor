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
