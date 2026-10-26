import json


def test_outputs_and_utf8(g3_out):
    raw = (g3_out / "items.geojson").read_bytes() + (g3_out / "catalog_items.json").read_bytes()
    assert "Szczaw królewski".encode("utf-8") in raw
    meta = json.loads((g3_out / "metadata.json").read_text("utf-8"))
    assert meta["game"] == "g3" and meta["world"] == "G3_WORLD_01"
    assert meta["engine"] == "genome" and "zenkit_version" not in meta
    for name in ("npcs", "npc_routines", "containers", "items"):
        assert json.loads((g3_out / f"{name}.geojson").read_text("utf-8"))["features"]


def test_unknown_items_reported(g3_out):
    catalog = json.loads((g3_out / "catalog_items.json").read_text("utf-8"))
    feats = json.loads((g3_out / "items.geojson").read_text("utf-8"))["features"]
    codes = {f["properties"]["code"] for f in feats}
    if codes - set(catalog):
        assert "unknown item code" in (g3_out / "report.txt").read_text("utf-8")


def test_treasure_sets_written(g3_out):
    sets = json.loads((g3_out / "treasure_sets.json").read_text("utf-8"))["sets"]
    small = sets["TS_Treasure_Small"]
    assert small["kind"] == "chest" and small["min_stacks"] == 3 and small["holders"] == 480
    assert {"code": "It_Bread", "name": "Chleb", "category": "Jedzenie", "amount": 2} in small["items"]
    tjalf = next(f for f in json.loads((g3_out / "containers.geojson").read_text("utf-8"))["features"]
                 if f["properties"]["key"] == "It_Key_Tjalf")
    assert tjalf["properties"]["treasure_sets"] == ["TS_Unique_Weapons"]
