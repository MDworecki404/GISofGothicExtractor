def _q(quests, code):
    return next(q for q in quests if q["code"] == code)


def test_delivery_quest(g3_quests):
    q = _q(g3_quests, "Abe_BringBread")
    assert q["id"] == "quest:Abe_BringBread" and q["name"] == "Zanieś Abe chleb dla zamku."
    assert q["section"] == "mission" and q["chapter"] is None
    assert q["giver"] == {"code": "Abe", "name": "Abe"} and q["giver_certainty"] == "always"
    assert {"code": "It_Bread", "name": "Chleb", "role": "handover", "amount": 30, "certainty": "always"} in q["items"]
    assert any(i["code"] == "It_Potion_Mana" and i["role"] == "reward" for i in q["items"])
    assert q["rewards"] == {"xp": 200, "xp_certainty": "always"}


def test_kill_quest_targets(g3_quests):
    q = _q(g3_quests, "Arakos_KillOrcs")
    targets = {c["code"] for c in q["characters"] if c["role"] == "target"}
    assert {"Montera_Orc_Raider_01", "Montera_Orc_Raider_02", "Montera_Orc_Raider_03"} <= targets
    assert any(i["code"] == "It_Gold" and i["role"] == "reward" for i in q["items"])


def test_stages_have_polish_text(g3_quests):
    q = _q(g3_quests, "Arakos_KillOrcs")
    texts = [s.get("text") for s in q["stages"]]
    assert "Patrol orków należy już do przeszłości." in texts
    for q in g3_quests:
        assert q["stages"] and all(s["kind"] in ("create", "entry") for s in q["stages"])
        assert all(not (s.get("text") or "").startswith(("INFO_", "QUEST_")) for s in q["stages"])


def test_every_quest_file(g3_quests, g3_fs):
    assert len(g3_quests) == len(g3_fs.list(suffix=".quest"))
    assert len({q["id"] for q in g3_quests}) == len(g3_quests)
