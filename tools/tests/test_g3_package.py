import json

from gothic_extract.package import build_game
from gothic_extract.validate import validate_game


def test_g3_package_validates(tmp_path, g3_out):
    pkgs = build_game("g3", g3_out.parent, tmp_path)
    pkg = pkgs["G3_WORLD_01"]
    assert pkg == tmp_path / "g3" / "myrtana"
    report = validate_game("g3", tmp_path)
    assert report.ok, report.text()
    index = json.loads((pkg / "search_index.json").read_text("utf-8"))
    sorrel = next(e for e in index["entries"] if e["id"] == "item:It_Plant_Perm_01")
    assert sorrel["name"] == "Szczaw królewski" and sorrel["places"]
    assert any(e["type"] == "character" and e["name"] == "Inog" for e in index["entries"])
    meta = json.loads((pkg / "metadata.json").read_text("utf-8"))
    assert meta["package"]["version"] == 4 and meta["movement_speeds_m_s"] is None
    assert meta["guild_names"]["REB"] == "Buntownicy"
    quests = json.loads((pkg / "quests.json").read_text("utf-8"))["quests"]
    assert len(quests) == 641  # one world: every quest of the game is in this package
    abe = next(q for q in quests if q["code"] == "Abe_BringBread")
    assert any(p["role"] == "giver" and p["npc_code"] == "Abe" for p in abe["places"])
    arakos = next(q for q in quests if q["code"] == "Arakos_KillOrcs")
    assert any(p["role"] == "target" for p in arakos["places"])
    assert meta["package"]["counts"]["quests"] == 641


def test_g3_loot_in_package(tmp_path, g3_out):
    pkg = build_game("g3", g3_out.parent, tmp_path)["G3_WORLD_01"]
    assert validate_game("g3", tmp_path).ok
    meta = json.loads((pkg / "metadata.json").read_text("utf-8"))
    assert "treasure_sets.json" in meta["package"]["files"]
    entries = {e["id"]: e for e in json.loads((pkg / "search_index.json").read_text("utf-8"))["entries"]}
    # rare source (unique chests, 46 holders): every chest is a "possible" place
    amulet = entries["item:It_Am_Assassin_01"]
    assert {"set": "TS_Unique_Magic", "kind": "chest", "holders": 46} in amulet["loot"]
    possible = [p for p in amulet["places"] if p.get("set") == "TS_Unique_Magic"]
    assert len(possible) == 46 and all(p["kind"] == "container" and p["certainty"] == "possible" for p in possible)
    # widespread source (480 small chests): summary only, no places
    gold = entries["item:It_Gold"]
    assert any(l["set"] == "TS_Treasure_Small" for l in gold["loot"])
    assert not any(p.get("set") == "TS_Treasure_Small" for p in gold["places"])
    # NPC layer and character cards carry their sets
    npcs = json.loads((pkg / "npcs.geojson").read_text("utf-8"))["features"]
    inog = next(f for f in npcs if f["properties"]["code"] == "Inog")
    assert inog["properties"]["treasure_sets"][0] == "TS_Plunder_Reb_Elite"
    sets = json.loads((pkg / "treasure_sets.json").read_text("utf-8"))["sets"]
    assert sets["TS_Unique_Magic"]["holders"] == 46


def test_validator_catches_unknown_loot_set(tmp_path, g3_out):
    pkg = build_game("g3", g3_out.parent, tmp_path)["G3_WORLD_01"]
    path = pkg / "search_index.json"
    index = json.loads(path.read_text("utf-8"))
    next(e for e in index["entries"] if e.get("loot"))["loot"].append({"set": "TS_Nie_Ma", "kind": "chest",
                                                                         "holders": 1})
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    report = validate_game("g3", tmp_path)
    assert not report.ok and "TS_Nie_Ma" in report.text()
