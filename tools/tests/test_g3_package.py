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
    assert json.loads((pkg / "quests.json").read_text("utf-8"))["quests"] == []
