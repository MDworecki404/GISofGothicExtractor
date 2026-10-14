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


def _code(*ops):
    import zenkit

    from gothic_extract.daedalus_scan import _Ins

    out, a = [], 0
    for op, imm in ops:
        out.append(_Ins(a, getattr(zenkit.DaedalusOpcode, op), 0, imm))
        a += 5
    return out


def test_else_body_is_conditional():
    from gothic_extract.daedalus_scan import is_conditional

    # 0 BZ->15 | 5 call(if) | 10 B->20 | 15 call(else) | 20 call(after) | 25 RSR
    code = _code(("BZ", 15), ("BE", 0), ("B", 20), ("BE", 0), ("BE", 0), ("RSR", 0))
    assert is_conditional(code, 5)
    assert is_conditional(code, 15)
    assert not is_conditional(code, 20)


def test_code_after_early_return_is_conditional():
    from gothic_extract.daedalus_scan import is_conditional

    # 0 BZ->10 | 5 RSR (return inside if) | 10 call | 15 RSR
    code = _code(("BZ", 10), ("RSR", 0), ("BE", 0), ("RSR", 0))
    assert is_conditional(code, 10)


def test_last_function_stops_at_end_of_bytecode(g2_vm):
    from gothic_extract.daedalus_scan import _idx, functions

    last = functions(g2_vm)[-1]
    assert len(_idx(g2_vm).code(last)) < 10_000
