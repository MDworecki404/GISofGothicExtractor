import json

from gothic_extract.descriptions import add_descriptions, item_descriptions, set_description


def test_zengin_descriptions_differ_from_name():
    cat = {"ITPO_HEALTH_01": {"name": "Mikstura", "description": "Esencja lecznicza"},
           "ITFO_APPLE": {"name": "Jabłko", "description": "Jabłko"},
           "ITMI_X": {"name": "X", "description": "  "}}
    assert item_descriptions(cat) == {"ITPO_HEALTH_01": "Esencja lecznicza"}


def test_genome_only_shared_names_and_no_final_period():
    cat = {"It_Am_A": {"name": "Amulet", "description": "Amulet Asasyna."},
           "It_Am_B": {"name": "Amulet", "description": "-"},
           "It_Apple": {"name": "Jabłko", "description": "Soczyste jabłko."},
           "It_Helm": {"name": "Hełm", "description": "Pierwsze zdanie. Drugie."},
           "It_Helm2": {"name": "Hełm", "description": "Hełm."},
           "It_Plant": {"name": "Ziele", "description": "Ziele z gór."},
           "It_Plant_Snow": {"name": "Ziele", "description": "Ziele ze śniegu."},
           "It_Potion_Wolf": {"name": "Mikstura przemiany", "description": "Przemienia w wilka."},
           "It_Potion_Boar": {"name": "Mikstura przemiany", "description": "Przemienia w dzika."},
           "It_Scroll_Sleep": {"name": "Sen", "description": "Bohater zsyła sen."},
           "It_Spell_Sleep": {"name": "Sen", "description": "Bohater wprawia cel w sen."},
           "It_Recipe_Mana_1": {"name": "Mikstura many", "description": "Mikstura many z ziół."},
           "It_Potion_Mana": {"name": "Mikstura many", "description": "Regeneruje manę."}}
    assert item_descriptions(cat, "genome") == {
        "It_Am_A": "Amulet Asasyna", "It_Potion_Wolf": "Przemienia w wilka", "It_Potion_Boar": "Przemienia w dzika"}


def test_set_description_goes_after_name_and_is_idempotent():
    rec = {"code": "A", "name": "Mikstura", "amount": 1}
    assert set_description(rec, "Esencja")
    assert list(rec) == ["code", "name", "description", "amount"]
    assert not set_description(rec, "Esencja")
    assert set_description(rec, None) and "description" not in rec


def test_add_descriptions_patches_every_place(tmp_path):
    item = {"code": "ITPO_HEALTH_01", "name": "Mikstura", "category": "Mikstury", "amount": 1}
    feat = lambda **p: {"type": "Feature", "geometry": None, "properties": p}  # noqa: E731
    files = {
        "search_index.json": {"version": 1, "entries": [{"id": "item:ITPO_HEALTH_01", "type": "item",
                                                          "code": "ITPO_HEALTH_01", "name": "Mikstura", "places": []}]},
        "items.geojson": {"type": "FeatureCollection", "features": [feat(id="item-0", **item)]},
        "containers.geojson": {"type": "FeatureCollection", "features": [feat(id="c-0", contents=[dict(item)])]},
        "characters.geojson": {"type": "FeatureCollection", "features": [feat(id="n-0", inventory=[dict(item)])]},
        "quests.json": {"version": 1, "quests": [{"id": "q", "items": [dict(item)]}]},
    }
    for name, obj in files.items():
        (tmp_path / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    r = add_descriptions(tmp_path, {"ITPO_HEALTH_01": "Esencja lecznicza"})
    assert r["records_changed"] == 5 and r["with_description"] == 1
    assert '"name":"Mikstura","description":"Esencja lecznicza"' in (tmp_path / "quests.json").read_text("utf-8")
    again = add_descriptions(tmp_path, {"ITPO_HEALTH_01": "Esencja lecznicza"})
    assert again["records_changed"] == 0 and again["files_written"] == []
