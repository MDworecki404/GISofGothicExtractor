"""Stage order of quests: graph finishing, condition atoms, stage places, the package validator."""
from types import SimpleNamespace

from gothic_extract import quest_order as qo
from gothic_extract.g3.quests import _order_stages
from gothic_extract.quests_package import stage_place
from gothic_extract.validate import PackageReport, _check_quest_order


class FakeVm:
    def __init__(self, names):
        self.names = names

    def get_symbol_by_index(self, i):
        return SimpleNamespace(name=self.names[i]) if i in self.names else None


def stage(seq, function="F", **kw):
    return {"seq": seq, "kind": "entry", "function": function, "sources": [], **kw}


def finish(stages, requires, source=None, excludes=None):
    q = {"id": "quest:T", "stages": stages}
    source = source or {s["seq"]: "condition" for s in stages}
    cycles = qo.apply_order(q, {k: set(v) for k, v in requires.items()}, source,
                            {s["seq"]: set((excludes or {}).get(s["seq"], ())) for s in stages}, {})
    return q, cycles


def test_levels_and_transitive_reduction():
    q, cycles = finish([stage(1), stage(2), stage(3)], {1: [], 2: [1], 3: [1, 2]})
    assert cycles == 0
    assert [(s["requires"], s["level"]) for s in q["stages"]] == [([], 0), ([1], 1), ([2], 2)]
    assert q["order"] == "dependency"


def test_cycle_is_broken_and_graph_is_valid():
    q, cycles = finish([stage(1), stage(2)], {1: [2], 2: [1]})
    assert cycles == 1
    r = PackageReport("t")
    q.update(stages_with_place=0)
    for s in q["stages"]:
        s["place"] = None
    _check_quest_order(q, r)
    assert not r.errors, r.errors


def test_order_needs_80_percent_known_sources():
    stages = [stage(i) for i in range(1, 6)]
    src = {1: "condition", 2: "condition", 3: "condition", 4: "condition", 5: "script_order"}
    q, _ = finish(stages, {i: ([i - 1] if i > 1 else []) for i in range(1, 6)}, src)
    assert q["order"] == "dependency"                      # 4 of 5 = 80 %
    src[4] = "script_order"
    q, _ = finish([stage(i) for i in range(1, 6)], {i: ([i - 1] if i > 1 else []) for i in range(1, 6)}, src)
    assert q["order"] == "script"


def test_mutually_exclusive_stages_share_a_group():
    q, _ = finish([stage(1), stage(2), stage(3), stage(4)], {1: [], 2: [], 3: [], 4: [1]},
                  excludes={2: [3], 3: [2], 4: [2]})
    assert [s["alternative_group"] for s in q["stages"]] == [None, "A", "A", None]   # 4 excludes 2, but not mutually


def test_dnf_of_and_or_not():
    vm = FakeVm({7: "DIA_X"})
    knows = ("call", "NPC_KNOWSINFO", (("var", "OTHER"), ("int", 7)))
    running = ("cmp", "==", ("var", "MIS_A"), ("const", "LOG_RUNNING", 1))
    # (knows || running) && !knows  ->  [running, !knows], [knows? no: knows && !knows kept as two atoms]
    expr = ("and", "and", ("or", "or", knows, running), ("not", knows))
    alts = qo._node_alternatives(vm, expr)
    assert len(alts) == 2
    assert {a["t"] for a in alts[0]} == {"knows"} and {a["neg"] for a in alts[0]} == {False, True}
    assert [(a["t"], a["neg"]) for a in alts[1]] == [("mis", False), ("knows", True)]


def test_comparison_atoms():
    vm = FakeVm({})
    kap = ("cmp", ">=", ("var", "KAPITEL"), ("int", 3))
    assert qo._node_alternatives(vm, kap) == [[{"t": "kapitel", "op": ">=", "n": 3, "neg": False}]]
    flipped = ("cmp", "<", ("int", 0), ("var", "FLAG"))          # 0 < FLAG  ==  FLAG > 0
    assert qo._node_alternatives(vm, flipped)[0][0]["op"] == ">"
    assert qo._node_alternatives(vm, ("not", ("var", "FLAG")))[0][0] == {"t": "var", "var": "FLAG", "op": "==", "n": 0, "neg": False}
    assert qo._node_alternatives(vm, ("int", 0)) == []


def test_resolver_ties_dialog_conditions_to_stages():
    d = {"DIA_A": qo.Dialog("DIA_A", "NPC", 1, "A_INFO", qo.Condition([[]], True)),
         "DIA_B": qo.Dialog("DIA_B", "NPC", 2, "B_INFO", qo.Condition([[{"t": "knows", "dia": "DIA_A", "neg": False}]], True)),
         "DIA_C": qo.Dialog("DIA_C", "NPC", 3, "C_INFO", qo.Condition([[{"t": "var", "var": "FLAG", "op": "==", "n": 1, "neg": False}]], True))}
    origin = lambda fn: [SimpleNamespace(kind="dialog", name="DIA_B")] if fn == "B_INFO" else []
    world = qo.World(d, origin, {"FLAG": [("B_INFO", 1, 10)]}, {}, set(), None)
    mk = lambda seq, dia, fn: stage(seq, fn, sources=[{"type": "dialog", "id": dia, "function": fn, "npc": "NPC"}])
    q = {"id": "quest:T", "mission_var": None, "stages": [mk(1, "DIA_A", "A_INFO"), mk(2, "DIA_B", "B_INFO"), mk(3, "DIA_C", "C_INFO")]}
    qo.order_quest(world, q)
    assert [(s["requires"], s["requires_source"]) for s in q["stages"]] == [([], "condition"), ([1], "condition"), ([2], "condition")]
    assert q["order"] == "dependency"


def test_unresolved_condition_falls_back_to_script_order():
    d = {"DIA_A": qo.Dialog("DIA_A", "N1", 1, "A_INFO", qo.Condition([[]], True)),
         "DIA_B": qo.Dialog("DIA_B", "N2", 1, "B_INFO", qo.Condition([[{"t": "call", "fn": "C_SOMEHELPER", "neg": False}]], True))}
    world = qo.World(d, lambda fn: [], {}, {}, set(), None)
    mk = lambda seq, dia, fn, npc: stage(seq, fn, sources=[{"type": "dialog", "id": dia, "function": fn, "npc": npc}])
    q = {"id": "quest:T", "mission_var": None, "stages": [mk(1, "DIA_A", "A_INFO", "N1"), mk(2, "DIA_B", "B_INFO", "N2")]}
    qo.order_quest(world, q)
    assert q["stages"][1]["requires_source"] == "script_order" and q["stages"][1]["requires"] == [1]


def test_g3_order_from_parent_and_game_event():
    dialogs = [{"Name": "D1", "ConditionType": "6"},
               {"Name": "D2", "ConditionType": "3", "CondPlayerKnows": "Event_X"},
               {"Name": "D3", "ConditionType": "10", "Parent": "D2"},
               {"Name": "D4", "ConditionType": "8"}]
    stages = [stage(i + 1, d["Name"]) for i, d in enumerate(dialogs)]
    q = {"stages": stages}
    _order_stages(q, dialogs, {"Event_X": {"D1"}})
    got = [(s["requires"], s["requires_source"]) for s in q["stages"]]
    assert got == [([], "condition"), ([1], "condition"), ([2], "condition"), ([3], "script_order")]
    assert q["order"] == "script"                          # 3 of 4 known = 75 %


def _idx(places, code="NPC_A", spawns=()):
    return SimpleNamespace(char_by_code={code: {"places": places}} if places else {}, spawns={code: list(spawns)})


def _routine(label, wp, lon, actions=("TA_STAND",), default=True):
    return {"kind": "routine", "lon": lon, "lat": 0.0, "h": 1.0, "label": label, "ref": f"NPC_A:START:{wp}",
            "is_default": default, "actions": list(actions)}


def test_stage_place_uses_dialog_hours_and_skips_sleep():
    idx = _idx([_routine("08:00–20:00", "WP_DAY", 1.0), _routine("20:00–08:00", "WP_BED", 2.0, ("TA_SLEEP",)),
                _routine("20:00–08:00", "WP_PUB", 3.0)])
    st = {"sources": [{"type": "dialog", "npc": "NPC_A", "npc_name": "Ala"}], "hours": [["21:00", "23:00"]]}
    p = stage_place(st, idx)
    assert (p["waypoint"], p["lon"], p["npc_code"]) == ("WP_PUB", 3.0, "NPC_A")
    st["hours"] = []
    assert stage_place(st, idx)["waypoint"] == "WP_DAY"
    assert stage_place({"sources": [{"type": "dialog", "npc": "PC_HERO"}], "hours": []}, idx) is None
    assert stage_place({"sources": [{"type": "item", "id": "ITEM"}], "hours": []}, idx) is None


def test_validator_rejects_bad_requires():
    q = {"id": "quest:T", "order": "dependency", "stages_with_place": 0,
         "stages": [{**stage(1), "requires": [9], "requires_source": "condition", "level": 0, "alternative_group": None,
                     "place": None}]}
    r = PackageReport("t")
    _check_quest_order(q, r)
    assert any("requires" in e for e in r.errors)
