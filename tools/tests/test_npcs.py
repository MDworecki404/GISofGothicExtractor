def test_many_npcs_in_khorinis(npcs):
    assert len({n.code for n in npcs}) > 300


def test_npcs_have_positions(npcs):
    assert sum(n.pos is not None for n in npcs) / len(npcs) > 0.98


def test_harad_smith_routine(npcs):
    harad = next(n for n in npcs if n.name == "Harad")
    assert any(rp.is_default and rp.action.startswith("TA_SMITH") for rp in harad.routines)
    assert all(rp.pos is not None for rp in harad.routines)


def test_inventory_certainty_values(npcs):
    vals = {i.certainty for n in npcs for i in n.inventory}
    assert vals <= {"always", "possible"} and "always" in vals


def test_script_items_have_positions(script_items):
    assert script_items and all(i.source == "script" and i.pos for i in script_items)


def test_no_npcs_from_other_worlds(npcs):
    callers = {n.insert_function for n in npcs}
    assert not any(c.startswith("STARTUP_DRAGONISLAND") for c in callers)
    assert "B_ENTER_OLDWORLD_KAPITEL_4" not in callers


def test_no_script_items_from_other_worlds(g2_vm, script_items):
    from gothic_extract.daedalus_scan import find_calls, symbol_name

    def pairs(prefixes):
        return {(symbol_name(g2_vm, c.args[0]).upper(), c.args[1].upper())
                for c in find_calls(g2_vm, {"WLD_INSERTITEM"})
                if c.caller.startswith(prefixes) and isinstance(c.args[1], str)}

    # the ship freepoints are shared with Khorinis' own STARTUP_NEWWORLD_* items
    di_only = pairs(("STARTUP_DRAGONISLAND", "ENTER_DI_")) - pairs(("STARTUP_NEWWORLD",))
    assert di_only
    assert not any((i.code, i.spot) in di_only for i in script_items)


def _expected_inventory(vm, npc_code):
    from gothic_extract.daedalus_scan import reachable_calls, symbol_name

    always, possible = {}, {}
    for c in reachable_calls(vm, npc_code, {"CREATEINVITEMS", "CREATEINVITEM", "EQUIPITEM"},
                             skip=["B_CREATEAMBIENTINV*"]):
        code = (symbol_name(vm, c.args[1]) or "").upper()
        if not code.startswith("IT"):
            continue
        amount = c.args[2] if c.callee == "CREATEINVITEMS" and isinstance(c.args[2], int) else 1
        if c.conditional:
            possible[code] = max(possible.get(code, 0), max(amount, 1))
        else:
            always[code] = always.get(code, 0) + max(amount, 1)
    return always, possible


def test_possible_amount_is_max_of_branches_not_sum():
    from gothic_extract.npcs import InvItem, merge_inventory

    inv = merge_inventory([("ITMI_GOLD", 5, True), ("ITMI_GOLD", 20, True), ("ITFO_APPLE", 2, False),
                           ("ITFO_APPLE", 3, False), ("ITFO_APPLE", 4, True)])
    assert inv == [InvItem("ITFO_APPLE", 5, "always"), InvItem("ITFO_APPLE", 4, "possible"),
                   InvItem("ITMI_GOLD", 20, "possible")]


def test_ambient_loot_tables_are_excluded(g2_vm, npcs):
    # Hodges gets only random ambient loot (B_CreateAmbientInv_*), which is not useful on the map
    hodges = next(n for n in npcs if n.name == "Hodges")
    always, possible = _expected_inventory(g2_vm, hodges.code)
    assert {i.code for i in hodges.inventory} == set(always) | set(possible)
    assert not any(i.code == "ITFO_BOOZE" and i.certainty == "possible" for i in hodges.inventory)
