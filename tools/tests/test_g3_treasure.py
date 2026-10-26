def test_chest_set(g3_treasure):
    s = g3_treasure["TS_Treasure_Small"]
    assert s.kind == "chest" and (s.min_stacks, s.max_stacks) == (3, 5)
    assert ("It_Bread", 2) in s.items and ("It_Gold", 20) in s.items


def test_unique_and_trader_sets(g3_treasure):
    assert g3_treasure["TS_Unique_Magic"].kind == "chest" and len(g3_treasure["TS_Unique_Magic"].items) == 50
    assert g3_treasure["TS_Unique_Magic"].distribution == 1
    assert g3_treasure["TS_Trader_Ass_Alchemy"].kind == "trader"
    assert g3_treasure["TS_Mining_Gold"].kind == "mining"


def test_only_item_templates(g3_treasure, g3_catalog):
    codes = {c for s in g3_treasure.values() for c, _ in s.items}
    assert codes and codes <= set(g3_catalog)
