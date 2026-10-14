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
