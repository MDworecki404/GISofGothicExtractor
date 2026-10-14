"""Static scan of compiled Daedalus bytecode for call sites with constant arguments.

Unlike running the VM, this sees every branch, so random or conditional inventory
and chapter-dependent inserts are all found. Arguments that are not plain pushes
of constants come back as None.
"""
from bisect import bisect_right
from dataclasses import dataclass
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


@dataclass
class _Ins:
    address: int
    op: zenkit.DaedalusOpcode
    symbol: int
    immediate: int


class _Index:
    def __init__(self, script: zenkit.DaedalusScript):
        self.script = script
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
        return self.starts[i] if i < len(self.starts) else start + 1_000_000

    def code(self, sym: zenkit.DaedalusSymbol) -> list[_Ins]:
        if sym.address in self._code:
            return self._code[sym.address]
        out, a, end = [], sym.address, self.end_of(sym.address)
        while a < end:
            ins = self.script.get_instruction(a)
            out.append(_Ins(a, ins.op, ins.symbol, ins.immediate))
            if ins.size <= 0:
                break
            a += ins.size
            if ins.op == Op.RSR and a >= end:
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


def _callee(script, ins: _Ins):
    if ins.op == Op.BE:
        return script.get_symbol_by_index(ins.symbol)
    if ins.op == Op.BL:
        return script.get_symbol_by_address(ins.symbol)
    return None


def _cond_ranges(code: list[_Ins]) -> list[tuple[int, int]]:
    return [(i.address, i.immediate) for i in code if i.op == Op.BZ and i.immediate > i.address]


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
        for j in range(n):
            p = k - n + j
            if p >= 0 and all(code[q].op in _PUSHES for q in range(p, k)):
                args[j] = _arg_value(script, code[p])
        conditional = any(b < ins.address < t for b, t in ranges)
        out.append(CallSite(sym.name, callee.name, args, conditional, ins.address))
    return out


def find_calls(script, callee_names: set[str]) -> list[CallSite]:
    names = {n.upper() for n in callee_names}
    return [c for f in functions(script) for c in scan_function(script, f) if c.callee in names]


def reachable_calls(script, root: str, callee_names: set[str]) -> list[CallSite]:
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
                out.append(CallSite(c.caller, c.callee, c.args, c_cond, c.address))
            callee = script.get_symbol_by_name(c.callee)
            if callee is not None and not callee.is_external and callee.address > 0:
                visit(callee, c_cond)

    visit(start, False)
    # a call reached both conditionally and unconditionally counts as unconditional
    best: dict[int, CallSite] = {}
    for c in out:
        if c.address not in best or (best[c.address].conditional and not c.conditional):
            best[c.address] = c
    return list(best.values())


def symbol_name(script, value: int | str | None) -> str | None:
    """Instance arguments are pushed as symbol indices; turn one back into a name."""
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        sym = script.get_symbol_by_index(value)
        return sym.name if sym is not None else None
    return None
