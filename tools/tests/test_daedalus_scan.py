from gothic_extract.daedalus_scan import find_calls, reachable_calls, symbol_name


def test_wld_insertnpc_calls_have_constant_waypoints(g2_vm):
    calls = find_calls(g2_vm, {"WLD_INSERTNPC"})
    assert len(calls) > 200
    assert sum(isinstance(c.args[1], str) for c in calls) / len(calls) > 0.95


def test_startup_newworld_reaches_inserts(g2_vm):
    calls = reachable_calls(g2_vm, "STARTUP_NEWWORLD", {"WLD_INSERTNPC"})
    assert len(calls) > 50


def test_conditional_detection(g2_vm):
    # G2NK has per-guild helpers (B_CreateAmbientInv_VLK, ...) branching on Hlp_Random
    calls = reachable_calls(g2_vm, "B_CREATEAMBIENTINV_VLK", {"CREATEINVITEMS", "CREATEINVITEM"})
    assert any(c.conditional for c in calls)
    assert any((symbol_name(g2_vm, c.args[1]) or "").startswith("IT") for c in calls)
