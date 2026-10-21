"""Static scan of compiled Daedalus bytecode for call sites with constant arguments.

Unlike running the VM, this sees every branch, so random or conditional inventory
and chapter-dependent inserts are all found. Arguments that are not plain pushes
of constants come back as None.
"""
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import lru_cache

import zenkit

from .text import game_text

Op = zenkit.DaedalusOpcode
DT = zenkit.DaedalusDataType
_PUSHES = {Op.PUSHI, Op.PUSHV, Op.PUSHVI, Op.PUSHVV}


@dataclass
class CallSite:
    caller: str
    callee: str
    args: list[int | str | None]
    conditional: bool
    address: int
    arg_syms: list[str | None] = field(default_factory=list)  # symbol name behind each pushed argument


@dataclass
class _Ins:
    address: int
    op: zenkit.DaedalusOpcode
    symbol: int
    immediate: int


_CODE_SIZE: dict[int, int] = {}


def set_code_size(script, size: int) -> None:
    """Record the bytecode length so the last function is not decoded past the end."""
    _CODE_SIZE[id(script)] = size


class _Index:
    def __init__(self, script: zenkit.DaedalusScript):
        self.script = script
        self.code_size = _CODE_SIZE.get(id(script))
        code_syms = [
            s for s in script.symbols
            if s.type in (DT.FUNCTION, DT.INSTANCE, DT.PROTOTYPE) and not s.is_external and s.address > 0
        ]
        self.by_address = {}
        for s in code_syms:
            self.by_address.setdefault(s.address, s)
        self.starts = sorted(self.by_address)
        self._code: dict[int, list[_Ins]] = {}

    def end_of(self, start: int) -> int:
        i = bisect_right(self.starts, start)
        if i < len(self.starts):
            return self.starts[i]
        return self.code_size if self.code_size and self.code_size > start else start + 1_000_000

    def code(self, sym: zenkit.DaedalusSymbol) -> list[_Ins]:
        if sym.address in self._code:
            return self._code[sym.address]
        out, a, end = [], sym.address, self.end_of(sym.address)
        start_is_last = sym.address == self.starts[-1]
        while a < end:
            ins = self.script.get_instruction(a)
            out.append(_Ins(a, ins.op, ins.symbol, ins.immediate))
            if ins.size <= 0:
                break
            a += ins.size
            if ins.op == Op.RSR and (a >= end or self.code_size is None and start_is_last):
                break
        self._code[sym.address] = out
        return out


@lru_cache(maxsize=4)
def _index(script_id: int, script) -> _Index:
    return _Index(script)


def _idx(script) -> _Index:
    return _index(id(script), script)


def functions(script) -> list[zenkit.DaedalusSymbol]:
    ix = _idx(script)
    return [ix.by_address[a] for a in ix.starts]


def _arg_value(script, ins: _Ins) -> int | str | None:
    if ins.op == Op.PUSHI:
        return ins.immediate
    if ins.op in (Op.PUSHV, Op.PUSHVI):
        sym = script.get_symbol_by_index(ins.symbol)
        if sym is None:
            return None
        if ins.op == Op.PUSHV and sym.is_const and sym.type == DT.STRING:
            return game_text(sym.get_string())
        if ins.op == Op.PUSHV and sym.is_const and sym.type == DT.INT:
            return sym.get_int()
        return sym.name
    return None


def _arg_sym(script, ins: _Ins) -> str | None:
    if ins.op in (Op.PUSHV, Op.PUSHVI):
        sym = script.get_symbol_by_index(ins.symbol)
        return sym.name if sym is not None else None
    return None


def _callee(script, ins: _Ins):
    if ins.op == Op.BE:
        return script.get_symbol_by_index(ins.symbol)
    if ins.op == Op.BL:
        return script.get_symbol_by_address(ins.symbol)
    return None


def _cond_ranges(code: list[_Ins]) -> list[tuple[int, int]]:
    """Address ranges (start, end) that do not run on every path through the function.

    - forward BZ: the if-body between the jump and its target;
    - forward B: the else-body it jumps over;
    - an RSR inside an if-body (early return): everything after that if-body.
    """
    ranges = [(i.address, i.immediate) for i in code if i.op in (Op.BZ, Op.B) and i.immediate > i.address]
    if_bodies = [(i.address, i.immediate) for i in code if i.op == Op.BZ and i.immediate > i.address]
    end = code[-1].address + 1 if code else 0
    for r in code:
        if r.op == Op.RSR:
            for b, t in if_bodies:
                if b < r.address < t:
                    ranges.append((t - 1, end))
    return ranges


def is_conditional(code: list[_Ins], address: int) -> bool:
    return any(b < address < t for b, t in _cond_ranges(code))


def scan_function(script, sym) -> list[CallSite]:
    code = _idx(script).code(sym)
    ranges = _cond_ranges(code)
    out = []
    for k, ins in enumerate(code):
        if ins.op not in (Op.BE, Op.BL):
            continue
        callee = _callee(script, ins)
        if callee is None:
            continue
        n = callee.size
        args: list[int | str | None] = [None] * n
        arg_syms: list[str | None] = [None] * n
        for j in range(n):
            p = k - n + j
            if p >= 0 and all(code[q].op in _PUSHES for q in range(p, k)):
                args[j] = _arg_value(script, code[p])
                arg_syms[j] = _arg_sym(script, code[p])
        conditional = any(b < ins.address < t for b, t in ranges)
        out.append(CallSite(sym.name, callee.name, args, conditional, ins.address, arg_syms))
    return out


@dataclass
class Assignment:
    caller: str
    var: str
    value: int | None
    conditional: bool
    address: int


def scan_assignments(script, sym) -> list[Assignment]:
    """Constant integer assignments `VAR = const` (value push, target push, MOVI) in one function."""
    code = _idx(script).code(sym)
    ranges = _cond_ranges(code)
    out = []
    for k, ins in enumerate(code):
        if ins.op != Op.MOVI or k < 2 or code[k - 1].op != Op.PUSHV:
            continue
        target = script.get_symbol_by_index(code[k - 1].symbol)
        if target is None or code[k - 2].op not in _PUSHES:
            continue
        value = _arg_value(script, code[k - 2])
        conditional = any(b < ins.address < t for b, t in ranges)
        out.append(Assignment(sym.name, target.name, value if isinstance(value, int) else None, conditional, ins.address))
    return out


def find_calls(script, callee_names: set[str]) -> list[CallSite]:
    names = {n.upper() for n in callee_names}
    return [c for f in functions(script) for c in scan_function(script, f) if c.callee in names]


def reachable_calls(script, root: str, callee_names: set[str], skip: list[str] = ()) -> list[CallSite]:
    """Calls to callee_names reachable from root; functions matching the fnmatch patterns in skip are not entered."""
    names = {n.upper() for n in callee_names}
    start = script.get_symbol_by_name(root.upper())
    if start is None:
        return []
    out: list[CallSite] = []
    seen: set[tuple[str, bool]] = set()

    def visit(sym, cond: bool):
        key = (sym.name, cond)
        if key in seen:
            return
        seen.add(key)
        for c in scan_function(script, sym):
            c_cond = cond or c.conditional
            if c.callee in names:
                out.append(CallSite(c.caller, c.callee, c.args, c_cond, c.address, c.arg_syms))
            callee = script.get_symbol_by_name(c.callee)
            if callee is not None and not callee.is_external and callee.address > 0 and not _matches(callee.name, skip):
                visit(callee, c_cond)

    visit(start, False)
    # a call reached both conditionally and unconditionally counts as unconditional
    best: dict[int, CallSite] = {}
    for c in out:
        if c.address not in best or (best[c.address].conditional and not c.conditional):
            best[c.address] = c
    return list(best.values())


def _matches(name: str, patterns: list[str]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatchcase(name, p.upper()) for p in patterns)


def reachable_functions(script, root_patterns: list[str], stop_patterns: list[str] = ()) -> set[str]:
    """Names of all code symbols reachable through calls from functions matching the fnmatch patterns.

    Traversal does not enter functions matching stop_patterns (e.g. another world's entry points
    called from a shared chapter-change dispatcher).
    """
    todo = [f for f in functions(script) if _matches(f.name, root_patterns)]
    seen: set[str] = set()
    while todo:
        f = todo.pop()
        if f.name in seen:
            continue
        seen.add(f.name)
        for c in scan_function(script, f):
            callee = script.get_symbol_by_name(c.callee)
            if (callee is not None and not callee.is_external and callee.address > 0 and callee.name not in seen
                    and not _matches(callee.name, stop_patterns)):
                todo.append(callee)
    return seen


def other_world_functions(script, world_roots: dict[str, list[str]], world: str) -> set[str]:
    """Functions reachable from other worlds' entry points but not from this world's."""
    world = world.upper()
    my_pats = world_roots.get(world, [])
    other_pats = [p for w, pats in world_roots.items() if w != world for p in pats]
    mine = reachable_functions(script, my_pats, other_pats)
    others = reachable_functions(script, other_pats, my_pats)
    return others - mine


def symbol_name(script, value: int | str | None) -> str | None:
    """Instance arguments are pushed as symbol indices; turn one back into a name."""
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        sym = script.get_symbol_by_index(value)
        return sym.name if sym is not None else None
    return None
