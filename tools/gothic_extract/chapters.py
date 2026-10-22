"""Chapter of a script function, read from a chapter dispatcher such as G1's B_KapitelWechsel.

G1 has one function that runs on every chapter change and branches `if (neues_Kapitel == n) { ... }`. A function
called from such a block starts to matter in chapter n. A function that is also reachable from anything outside the
blocks (a dialog, an event) has no certain chapter, so it gets none: the chapter is assigned only when every caller
of the function is itself a block call or has a chapter, and then it is the lowest of them.
"""
from collections import defaultdict

from .daedalus_scan import Op, _idx, functions, scan_function, symbol_name

# calls that take a function as an argument: callee -> argument index
_FUNCTION_ARGS = {"INFO_ADDCHOICE": 2, "AI_STARTSTATE": 1}


def _blocks(script, dispatcher) -> list[tuple[int, int, int]]:
    """(start, end, chapter) of every `if (<param> == n)` body in the dispatcher."""
    code = _idx(script).code(dispatcher)
    out = []
    for k, ins in enumerate(code):
        if ins.op != Op.BZ or ins.immediate <= ins.address or k < 3:
            continue
        push_n, push_var, eq = code[k - 3], code[k - 2], code[k - 1]
        if eq.op != Op.EQ or push_n.op != Op.PUSHI or push_var.op != Op.PUSHV:
            continue
        sym = script.get_symbol_by_index(push_var.symbol)
        if sym is not None and sym.name.startswith(dispatcher.name + "."):
            out.append((ins.address, ins.immediate, push_n.immediate))
    return out


def function_chapters(script, dispatcher: str) -> dict[str, int]:
    """function name -> chapter in which it first runs, for functions only ever reached from the dispatcher."""
    disp = script.get_symbol_by_name(dispatcher.upper())
    if disp is None:
        return {}
    blocks = _blocks(script, disp)
    direct: dict[str, set[int | None]] = defaultdict(set)  # callee -> chapters of the dispatcher blocks calling it
    callers: dict[str, set[str]] = defaultdict(set)
    for f in functions(script):
        for c in scan_function(script, f):
            refs = [c.callee]
            idx = _FUNCTION_ARGS.get(c.callee)
            target = symbol_name(script, c.args[idx]) if idx is not None and idx < len(c.args) else None
            if target:
                refs.append(target.upper())
            for callee in refs:
                if f.name == disp.name:
                    block = next((n for b, e, n in blocks if b < c.address < e), None)
                    direct[callee].add(block)
                else:
                    callers[callee].add(f.name)
    chapter: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for callee in set(direct) | set(callers):
            if callee in chapter or callee == disp.name:
                continue
            contributions = list(direct.get(callee, ()))
            ok = None not in contributions
            for up in callers.get(callee, ()):
                if up in chapter:
                    contributions.append(chapter[up])
                else:
                    ok = False
            if ok and contributions:
                chapter[callee] = min(contributions)
                changed = True
    return chapter
