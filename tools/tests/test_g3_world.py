from gothic_extract.g3.npc_codes import ALIGNMENT_CODES, alignment_names_pl
from gothic_extract.g3.world import STORY_SECTOR, active_sectors


def test_sectors_skip_tests_and_disabled(g3_fs, g3_cfg):
    paths = active_sectors(g3_fs, "G3_World_01", g3_cfg.sector_exclude)
    assert not any("test" in p.lower() for p in paths)
    assert any(p.endswith("Silden_NPC_01.lrentdat") for p in paths)
    assert any("/SysDyn_" in p for p in paths)


def test_inog(g3_world):
    _, npcs = g3_world
    inog = next(n for n in npcs if n.code == "Inog")
    assert inog.is_human and inog.chapter is None and inog.pos is not None and inog.name == "Inog"
    anog = next(n for n in npcs if n.code == "Anog")  # Inog is a rebel incognito: alignment 0 in the data
    assert anog.guild_name == "REB"
    assert {r.action for r in anog.routines} == {"WORK", "RELAX", "SLEEP"}


def test_named_people_not_duplicated(g3_world):
    # the same entity must not come twice (SysDyn and a town sector); flocks of birds may share a spot
    _, npcs = g3_world
    keys = [(n.code, tuple(round(c) for c in n.pos)) for n in npcs if n.is_human]
    assert len(keys) == len(set(keys))


def test_king_sorrel_somewhere(g3_world):
    wd, _ = g3_world
    where = [i for i in wd.items if i.code == "It_Plant_Perm_01"]
    where += [c for c in wd.containers if any(k == "It_Plant_Perm_01" for k, _ in c.contents)]
    assert where


def test_locked_chest_with_key(g3_world):
    wd, _ = g3_world
    tjalf = [c for c in wd.containers if c.key == "It_Key_Tjalf"]
    assert tjalf and tjalf[0].locked
    assert ("It_Gold", 1000) in tjalf[0].contents


def test_npc_inventory_without_body_parts(g3_world, g3_catalog):
    # entities below an NPC are mostly its head/body/hair (templates under BodyParts): not items
    wd, npcs = g3_world
    inv = [i.code for n in npcs for i in n.inventory]
    assert len(inv) > 50
    assert all(code in g3_catalog or code.startswith("?") for code in inv)


def test_most_item_codes_in_catalog(g3_world, g3_catalog):
    wd, _ = g3_world
    codes = {i.code for i in wd.items} | {k for c in wd.containers for k, _ in c.contents}
    assert len(codes - set(g3_catalog)) <= 0.05 * len(codes)  # the rest -> warnings in the report (Task 6)


def test_routine_points_resolved(g3_world):
    _, npcs = g3_world
    pts = [r for n in npcs for r in n.routines]
    assert len(pts) > 1000 and all(r.pos is not None for r in pts)
    assert sum(1 for n in npcs if n.is_human and n.routines) > 300


def test_alignment_names_from_game(g3_strings):
    names = alignment_names_pl(g3_strings)
    assert names["ORC"] == "Orkowie" and names["REB"] == "Buntownicy"
    assert set(names) == set(ALIGNMENT_CODES.values())


def test_treasure_sets_on_holders(g3_world):
    wd, npcs = g3_world
    tjalf = next(c for c in wd.containers if c.key == "It_Key_Tjalf")
    assert tjalf.treasure_sets == ["TS_Unique_Weapons"]
    inog = next(n for n in npcs if n.code == "Inog")
    assert inog.treasure_sets == ["TS_Plunder_Reb_Elite", "TS_Weaponry_Merc_2H", "TS_PickPocket_Medium"]


def test_disabled_story_sectors_included_and_marked(g3_world, g3_fs, g3_cfg):
    # sectors =false in wrldatasc are switched on by quests: their content is in, marked as story content
    assert g3_cfg.include_disabled_sectors
    paths = active_sectors(g3_fs, "G3_World_01", g3_cfg.sector_exclude, include_disabled=True)
    assert any(p.endswith("G3_Nordmar_01_WhiteShadowbeast.lrentdat") for p in paths)
    assert not any("test" in p.lower() for p in paths)
    wd, npcs = g3_world
    cups = [i for i in wd.items if i.spot == "G3_Nordmar_01_Monastery_FiremageCups_Blessed"]
    assert len(cups) == 12 and all(i.source == "script" for i in cups)
    beast = next(n for n in npcs if n.code == "WhiteShadowbeast")
    assert beast.insert_function == STORY_SECTOR and beast.insert_waypoint == "G3_Nordmar_01_WhiteShadowbeast"
    inog = next(n for n in npcs if n.code == "Inog")
    assert inog.insert_function == ""
    assert all(i.source == "zen" and i.spot is None for i in wd.items if i not in cups and i.source == "zen")
