"""Order of quest stages (Gothic 1 / 2 / Archolos): which stage must happen before which.

Everything is read from the compiled Daedalus, nothing is invented:

* the CONDITION function of every dialog (C_INFO.condition) is evaluated symbolically (a stack machine over the
  bytecode, no VM run) into alternatives of atoms: `Npc_KnowsInfo(hero, DIA_X)`, `MIS_<quest> == LOG_*`,
  `Npc_HasItems`, `Kapitel`, `Npc_IsDead`, `Wld_IsTime`, and plain flag variables;
* an atom is tied to the quest's stages through the dialog that satisfies it: a dialog is known once its information
  function ran, a flag is set by the functions that assign it (reached from dialogs through the call graph), an item
  is handed over by the functions that give it to the player;
* a stage inherits the requirements of the dialog it comes from.

`requires_source` says how a stage's predecessors are known: "condition" (read from the conditions), "dialog_order"
(heuristic: the previous dialog of the same NPC in the quest, by C_INFO.nr; used only when the conditions could not
be resolved) and "script_order" (no information; the previous stage in script order, a guess).
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from string import ascii_uppercase

import zenkit

from .catalog import instances_of
from .daedalus_scan import _idx, functions, scan_assignments, scan_function, symbol_name

Op = zenkit.DaedalusOpcode
DT = zenkit.DaedalusDataType
_PUSH_VAR = {Op.PUSHV, Op.PUSHVI, Op.PUSHVV}
_CMP = {Op.EQ: "==", Op.NEQ: "!=", Op.LT: "<", Op.LTE: "<=", Op.GT: ">", Op.GTE: ">="}
_ARITH = {Op.ADD: "+", Op.SUB: "-", Op.MUL: "*", Op.DIV: "/", Op.MOD: "%", Op.LSL: "<<", Op.LSR: ">>"}
_AND, _OR = {Op.AND, Op.ANDB}, {Op.OR, Op.ORR}
_PLAYER = {"HERO", "OTHER", "PC_HERO"}
_MAX_ALTERNATIVES = 16
_MAX_DEPTH = 12
_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "==", "!=": "!="}
_NEGATE = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
# `Npc_HasItems`-like calls: callee -> (index of the item argument)
_STATUS_OF = {"LOG_RUNNING": "RUNNING", "LOG_SUCCESS": "SUCCESS", "LOG_FAILED": "FAILED", "LOG_OBSOLETE": "OBSOLETE"}


# ---------------------------------------------------------------------------------------------------------------
# symbolic evaluation of a condition function
# ---------------------------------------------------------------------------------------------------------------

def _truthy_branches(code, vm, sym):
    """Run the function linearly once; return (returns, complex) where returns = [(value_node, [guards])]."""
    stack: list[tuple] = []
    guards: list[tuple[int, int, tuple]] = []   # (bz address, target, expression)
    elses: list[tuple[int, int]] = []           # (forward B address, target): else-bodies
    returns: list[tuple[tuple, list[tuple]]] = []
    complex_ = False

    def pop():
        return stack.pop() if stack else ("unk",)

    for ins in code:
        op = ins.op
        if op == Op.PUSHI:
            stack.append(("int", ins.immediate))
        elif op in _PUSH_VAR:
            s = vm.get_symbol_by_index(ins.symbol)
            if s is None:
                stack.append(("unk",))
            elif s.is_const and s.type == DT.INT:
                stack.append(("const", s.name, s.get_int()))
            else:
                stack.append(("var", s.name))
        elif op in (Op.BE, Op.BL):
            callee = vm.get_symbol_by_index(ins.symbol) if op == Op.BE else vm.get_symbol_by_address(ins.symbol)
            if callee is None:
                stack.append(("unk",))
                continue
            args = [pop() for _ in range(callee.size)][::-1]
            if callee.has_return:
                stack.append(("call", callee.name, tuple(args)))
        elif op in _CMP or op in _ARITH or op in _AND or op in _OR:
            left, right = pop(), pop()      # the compiler pushes the right operand first
            kind = "cmp" if op in _CMP else "and" if op in _AND else "or" if op in _OR else "arith"
            sym_op = _CMP.get(op) or _ARITH.get(op) or kind
            stack.append((kind, sym_op, left, right))
        elif op == Op.NOT:
            stack.append(("not", pop()))
        elif op in (Op.NEGATE, Op.PLUS, Op.CMPL):
            stack.append(("arith", "unary", pop(), ("int", 0)))
        elif op == Op.BZ:
            guards.append((ins.address, ins.immediate, pop()))
        elif op == Op.B:
            if ins.immediate > ins.address:
                elses.append((ins.address, ins.immediate))
        elif op == Op.RSR:
            if not stack:
                continue                    # end of function without a value: returns FALSE
            value = stack.pop()
            active = [g[2] for g in guards if g[0] < ins.address < g[1]]
            if any(b < ins.address < t for b, t in elses):
                complex_ = True
            returns.append((value, active))
        elif op in (Op.MOVI, Op.MOVVI, Op.ADDMOVI, Op.SUBMOVI, Op.MULMOVI, Op.DIVMOVI, Op.MOVS, Op.MOVSS, Op.MOVF, Op.MOVVF):
            pop()
            pop()
        elif op == Op.PUSHVV:
            stack.append(("unk",))
    return returns, complex_, guards


def _node_alternatives(vm, node, negate: bool = False) -> list[list[dict]] | None:
    """Boolean expression -> DNF: list of alternatives, each a list of atoms. None = cannot be understood
    (a constant false: no alternative -> []). `negate` pushes a `!` inward."""
    kind = node[0]
    if kind in ("and", "or"):
        a, b = _node_alternatives(vm, node[2], negate), _node_alternatives(vm, node[3], negate)
        if a is None or b is None:
            return None
        if (kind == "and") != negate:   # AND (or negated OR)
            out = [x + y for x in a for y in b]
        else:
            out = a + b
        return out[:_MAX_ALTERNATIVES]
    if kind == "not":
        return _node_alternatives(vm, node[1], not negate)
    if kind in ("int", "const"):
        value = node[1] if kind == "int" else node[2]
        return [[]] if bool(value) != negate else []
    atom = _atom(vm, node, negate)
    return None if atom is None else [[atom]]


def _inst(vm, node) -> str | None:
    """Instance argument (an item or dialog constant) -> upper-case symbol name."""
    if node[0] == "int":
        return symbol_name(vm, node[1])
    if node[0] in ("var", "const"):
        return node[1]
    return None


def _num(node) -> int | None:
    return node[1] if node[0] == "int" else node[2] if node[0] == "const" else None


def _atom(vm, node, negate: bool) -> dict | None:
    """One non-logical expression -> atom dict. Fields: t (type), neg (the atom must NOT hold), plus type specifics."""
    kind = node[0]
    if kind == "cmp":
        _, op, left, right = node
        if left[0] in ("int", "const") and right[0] not in ("int", "const"):
            left, right, op = right, left, _FLIP[op]
        value = _num(right)
        if value is None:
            return {"t": "other", "text": f"{_describe(left)} {op} {_describe(right)}", "neg": False}
        if negate:
            op = _NEGATE[op]
        if left[0] == "call":
            return _call_atom(vm, left, op, value)
        if left[0] == "var":
            name = left[1]
            if name == "KAPITEL":
                return {"t": "kapitel", "op": op, "n": value, "neg": False}
            status = _STATUS_OF.get(right[1]) if right[0] == "const" else None
            if name.startswith("MIS_") and status:
                return {"t": "mis", "var": name, "op": op, "status": status, "neg": False}
            return {"t": "var", "var": name, "op": op, "n": value, "neg": False}
        return {"t": "other", "text": f"{_describe(left)} {op} {value}", "neg": False}
    if kind == "call":
        return _call_atom(vm, node, "==" if negate else "!=", 0, bare=True)
    if kind == "var":
        return {"t": "var", "var": node[1], "op": "==" if negate else "!=", "n": 0, "neg": False}
    return {"t": "other", "text": _describe(node), "neg": negate}


def _describe(node) -> str:
    kind = node[0]
    if kind == "call":
        return f"{node[1]}(...)"
    if kind in ("var", "const"):
        return node[1]
    if kind == "int":
        return str(node[1])
    return kind


def _call_atom(vm, call, op: str, value: int, bare: bool = False) -> dict:
    """`Fn(args) op value` (bare: truthiness of Fn(args), i.e. op '!=' 0 or '==' 0)."""
    _, name, args = call
    if bare:
        positive = op == "!="
    else:   # compare result with value: positive when it demands "at least one"/true
        positive = (op in (">=", ">") and value >= (1 if op == ">=" else 0)) or (op == "==" and value != 0) \
            or (op == "!=" and value == 0)
    neg = not positive
    if name == "NPC_KNOWSINFO" and len(args) == 2:
        dia = _inst(vm, args[1])
        if dia:
            return {"t": "knows", "dia": dia, "neg": neg}
    if name in ("NPC_HASITEMS", "NPC_HASITEMS") and len(args) == 2:
        item = _inst(vm, args[1])
        if item and _inst(vm, args[0]) is not None:
            return {"t": "has", "item": item, "n": value, "op": op, "neg": neg}
    if name == "NPC_ISDEAD" and len(args) == 1:
        npc = _inst(vm, args[0])
        if npc:
            return {"t": "dead", "npc": npc, "neg": neg}
    if name == "WLD_ISTIME" and len(args) == 4 and all(a[0] == "int" for a in args):
        return {"t": "time", "from": f"{args[0][1]:02d}:{args[1][1]:02d}", "to": f"{args[2][1]:02d}:{args[3][1]:02d}",
                "neg": neg}
    return {"t": "call", "fn": name, "neg": neg}


@dataclass
class Condition:
    alternatives: list[list[dict]]   # DNF; [] = never true
    understood: bool                 # False: the function has a shape the evaluator does not follow


def parse_condition(vm, fn_sym) -> Condition:
    """Condition function -> alternatives of atoms. A function whose result is not a plain `return TRUE` under if-guards
    is reported as not understood; an absent function (no condition) is always true."""
    if fn_sym is None or fn_sym.is_external or fn_sym.address <= 0:
        return Condition([[]], True)
    returns, complex_, _ = _truthy_branches(_idx(vm).code(fn_sym), vm, fn_sym)
    alts: list[list[dict]] = []
    ok = not complex_
    for value, guards in returns:
        if value[0] in ("int", "const"):
            if not (value[1] if value[0] == "int" else value[2]):
                continue                       # `return FALSE`
            paths: list[list[dict]] = [[]]
        else:
            got = _node_alternatives(vm, value)
            if got is None:
                ok = False
                continue
            paths = got
        for g in guards:
            got = _node_alternatives(vm, g)
            if got is None:
                ok = False
                break
            paths = [p + q for p in paths for q in got][:_MAX_ALTERNATIVES]
        else:
            alts += paths
    return Condition(alts[:_MAX_ALTERNATIVES], ok)


# ---------------------------------------------------------------------------------------------------------------
# game-wide tables
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class Dialog:
    name: str
    npc: str | None
    nr: int
    info_fn: str | None
    cond: Condition
    permanent: bool = False


def dialogs_of(vm) -> dict[str, Dialog]:
    """C_INFO instance -> Dialog (npc, nr, parsed condition)."""
    out = {}
    for s in instances_of(vm, "C_INFO"):
        info = vm.init_instance(s, zenkit.DaedalusInstanceType.INFO)
        npc = vm.get_symbol_by_index(info.npc) if info.npc > 0 else None
        fn = vm.get_symbol_by_index(info.information) if info.information > 0 else None
        cond = vm.get_symbol_by_index(info.condition) if info.condition > 0 else None
        out[s.name] = Dialog(s.name, npc.name if npc is not None else None, info.nr, fn.name if fn is not None else None,
                             parse_condition(vm, cond), bool(info.permanent))
    return out


@dataclass
class World:
    """Everything the resolver needs, computed once per game."""
    dialogs: dict[str, Dialog]
    origins: object                                   # function name -> [Origin]
    flag_setters: dict[str, list[tuple[str, int | None, int]]]   # variable -> [(function, constant value, address)]
    item_givers: dict[str, set[str]]                  # item -> functions that hand it to the player
    engine_calls: set[str] = field(default_factory=set)   # external (engine) functions: situation queries, no stage
    vm: object = None
    _guards: dict = field(default_factory=dict)

    def guards(self, fn: str) -> list[tuple[int, int, tuple]]:
        """The if-guards of a function: (start, end, expression) for every conditional jump."""
        if fn not in self._guards:
            sym = self.vm.get_symbol_by_name(fn)
            ok = sym is not None and not sym.is_external and sym.address > 0
            self._guards[fn] = _truthy_branches(_idx(self.vm).code(sym), self.vm, sym)[2] if ok else []
        return self._guards[fn]

    def innermost(self, fn: str, address: int) -> tuple[int, int] | None:
        """Smallest if-body of fn that contains the address (None: top level of the function)."""
        best = None
        for b, t, _ in self.guards(fn):
            if b < address < t and (best is None or t - b < best[1] - best[0]):
                best = (b, t)
        return best


_GIVE = {"CREATEINVITEM": 1, "CREATEINVITEMS": 1}


def build_world(vm, scans, origins) -> World:
    flag_setters: dict[str, list[tuple[str, int | None, int]]] = defaultdict(list)
    for f in functions(vm):
        for a in scan_assignments(vm, f):
            flag_setters[a.var].append((f.name, a.value, a.address))
    item_givers: dict[str, set[str]] = defaultdict(set)
    for fn, calls in scans.items():
        for c in calls:
            code = None
            if c.callee in _GIVE and c.arg_syms and (c.arg_syms[0] or "") in _PLAYER and len(c.args) > 1:
                code = symbol_name(vm, c.args[1])
            elif c.callee == "B_GIVEINVITEMS" and len(c.arg_syms) > 2 and (c.arg_syms[1] or "") in _PLAYER:
                code = symbol_name(vm, c.args[2])
            if code:
                item_givers[code.upper()].add(fn)
    engine = {x.name for x in vm.symbols if x.type == DT.FUNCTION and x.is_external}
    return World(dialogs_of(vm), origins, flag_setters, item_givers, engine, vm)


# ---------------------------------------------------------------------------------------------------------------
# per-quest resolution
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class Need:
    """What a condition (or a set of alternatives) demands of one quest."""
    preds: set[int] = field(default_factory=set)      # stages certainly before
    excludes: set[int] = field(default_factory=set)   # stages that must NOT have happened (negated atoms)
    unknown: bool = False                              # some atom could not be tied to anything
    ored: bool = False                                 # alternatives differed: only the common part is in `preds`
    time: list[tuple[str, str]] = field(default_factory=list)


class QuestResolver:
    def __init__(self, world: World, quest: dict):
        self.w = world
        self.q = quest
        self.stages = quest["stages"]
        self.by_dialog: dict[str, set[int]] = defaultdict(set)
        self.by_function: dict[str, set[int]] = defaultdict(set)
        self.status: dict[str, set[int]] = defaultdict(set)
        for st in self.stages:
            self.by_function[st["function"]].add(st["seq"])
            for src in st["sources"]:
                if src["type"] == "dialog":
                    self.by_dialog[src["id"]].add(st["seq"])
            if st["kind"] == "status":
                self.status[st["status"]].add(st["seq"])
        self.fn_events: dict[str, list[tuple[int, int]]] = defaultdict(list)   # function -> [(address, seq)]
        for st in self.stages:
            if st.get("_address") is not None:
                self.fn_events[st["function"]].append((st["_address"], st["seq"]))
        self._memo: dict[str, Need] = {}
        self._busy: set[str] = set()

    # -- dialogs -------------------------------------------------------------------------------------------------
    def dialog_need(self, name: str, depth: int = 0) -> Need:
        """Requirements of one dialog: its own condition (alternatives -> common part)."""
        if name in self._memo:
            return self._memo[name]
        d = self.w.dialogs.get(name)
        if d is None or not d.cond.understood or depth > _MAX_DEPTH or name in self._busy:
            return Need(unknown=True)
        self._busy.add(name)
        try:
            alts = [self.alt_need(a, depth) for a in d.cond.alternatives]
        finally:
            self._busy.discard(name)
        need = self._merge_alternatives(alts)
        self._memo[name] = need
        return need

    @staticmethod
    def _merge_alternatives(alts: list[Need]) -> Need:
        if not alts:
            return Need(unknown=True)
        if len(alts) == 1:
            return alts[0]
        common = set.intersection(*(a.preds for a in alts))
        return Need(common, set.intersection(*(a.excludes for a in alts)), any(a.unknown for a in alts),
                    any(a.preds != common for a in alts), [t for a in alts for t in a.time])

    def alt_need(self, atoms: list[dict], depth: int) -> Need:
        need = Need()
        for atom in atoms:
            p, ex, unknown = self.atom(atom, depth)
            if atom["neg"]:
                if atom["t"] == "knows":
                    need.excludes |= p          # `!Npc_KnowsInfo`: the dialog must not have run yet
            else:
                need.preds |= p
            need.excludes |= ex
            need.unknown |= unknown
            if atom["t"] == "time" and not atom["neg"]:
                need.time.append((atom["from"], atom["to"]))
        return need

    # -- atoms ---------------------------------------------------------------------------------------------------
    def atom(self, atom: dict, depth: int) -> tuple[set[int], set[int], bool]:
        """(stages that satisfy the atom, stages it excludes, unknown). Negated atoms return the stages they forbid."""
        t = atom["t"]
        if t == "knows":
            return self._dialog_stages(atom["dia"], depth), set(), False
        if t == "mis":
            return self._mission_stages(atom), set(), False
        if t == "has":
            givers = [(fn, None) for fn in self.w.item_givers.get(atom["item"], ())]
            return self._setters_stages(givers, depth, False), set(), False
        if t == "var":
            return self._flag_stages(atom, depth)
        if t in ("kapitel", "time", "dead"):
            return set(), set(), False          # understood: no stage precedes it
        if t == "call" and atom["fn"] in self.w.engine_calls:
            return set(), set(), False          # engine query about the situation (distance, state, guild...)
        return set(), set(), True               # script helper calls / other expressions

    def _dialog_stages(self, dia: str, depth: int) -> set[int]:
        """Stages that happened by the time dialog `dia` is known: its own stages, else what it needed itself."""
        own = self.by_dialog.get(dia)
        if own:
            return set(own)
        return set(self.dialog_need(dia, depth + 1).preds) if depth < _MAX_DEPTH else set()

    def _setter_stages(self, fn: str, address: int | None, depth: int) -> set[int]:
        """Stages that have happened once the code at (fn, address) ran: the stages of that function inside the same
        if-block (all of them for a top-level setter), else those of the dialogs the function is reached from."""
        evs = self.fn_events.get(fn)
        if evs:
            block = self.w.innermost(fn, address) if address is not None else None
            got = {seq for a, seq in evs if block is None or block[0] < a < block[1]}
            if got:
                return got
        got = set()
        for o in self.w.origins(fn):
            if o.kind == "dialog":
                got |= self._dialog_stages(o.name, depth)
        return got

    def _setters_stages(self, setters: list[tuple[str, int | None]], depth: int, strict: bool) -> set[int]:
        """Stages implied by one of the setters having run. strict: every setter must lie in the quest (the
        intersection); otherwise setters outside the quest are ignored."""
        out = [self._setter_stages(fn, a, depth) for fn, a in sorted(set(setters), key=lambda x: (x[0], x[1] or 0))]
        if strict and not all(out):
            return set()
        out = [g for g in out if g]
        return set.intersection(*out) if out else set()

    def _mission_stages(self, atom: dict) -> set[int]:
        if atom["var"] != self.q["mission_var"]:
            return set()                        # another quest's variable
        op, status = atom["op"], atom["status"]
        if op == "==":
            return set(self.status.get(status, ()))
        return set()

    def _flag_stages(self, atom: dict, depth: int) -> tuple[set[int], set[int], bool]:
        """`var op n`: the functions that assign a value satisfying it are the satisfiers; a condition that wants the
        variable to be zero again forbids the stages that raise it."""
        setters = self.w.flag_setters.get(atom["var"])
        if not setters:
            return set(), set(), True           # never assigned in script: engine/other source
        op, n = atom["op"], atom["n"]
        raisers = [(fn, a) for fn, v, a in setters if v != 0]
        if (op, n) in (("==", 0), ("<=", 0), ("<", 1)):
            return set(), self._setters_stages(raisers, depth, False), False
        if op == "==":
            wanted = [(fn, a) for fn, v, a in setters if v == n]
        elif op in (">=", ">"):
            wanted = [(fn, a) for fn, v, a in setters if v is not None and (v >= n if op == ">=" else v > n)]
        elif op == "!=" and n == 0:
            wanted = raisers
        else:
            return set(), set(), True
        if not wanted:
            return set(), set(), True
        return self._setters_stages(wanted, depth, True), set(), False

    # -- stages --------------------------------------------------------------------------------------------------
    def guard_need(self, fn: str, address: int) -> Need | None:
        """Requirements from the if-guards around the stage's call in its own function (None: no guard)."""
        exprs = [e for b, t, e in self.w.guards(fn) if b < address < t]
        if not exprs:
            return None
        paths: list[list[dict]] = [[]]
        for e in exprs:
            got = _node_alternatives(self.w.vm, e)
            if got is None:
                return Need(unknown=True)
            paths = [p + q for p in paths for q in got][:_MAX_ALTERNATIVES]
        return self._merge_alternatives([self.alt_need(a, 0) for a in paths])

    @staticmethod
    def _and(a: Need | None, b: Need | None) -> Need | None:
        if a is None or b is None:
            return a or b
        return Need(a.preds | b.preds, a.excludes | b.excludes, a.unknown or b.unknown, a.ored or b.ored, a.time + b.time)

    def stage_need(self, st: dict) -> Need | None:
        """Requirements of one stage = those of the dialog / item it is reached from (alternatives -> common part)
        and of the if-guards around its call. None: neither (a script trigger without a condition)."""
        needs = []
        for src in st["sources"]:
            if src["type"] == "dialog":
                needs.append(self.dialog_need(src["id"]))
            elif src["type"] == "item":
                givers = [(fn, None) for fn in self.w.item_givers.get(src["id"].upper(), ())]
                needs.append(Need(preds=self._setters_stages(givers, 0, False)))
        need = self._merge_alternatives(needs) if needs else None
        if st.get("_address") is not None:
            need = self._and(need, self.guard_need(st["function"], st["_address"]))
        if need is None:
            return None
        own = {st["seq"]}
        if st.get("_address") is not None:      # stages in the same if-block happen together (a do-once guard)
            block = self.w.innermost(st["function"], st["_address"])
            own |= {seq for a, seq in self.fn_events.get(st["function"], ())
                    if self.w.innermost(st["function"], a) == block}
        if needs:                       # a dialog (item) runs its stages together; a manager function does not
            own |= self.by_function.get(st["function"], set())
            for src in st["sources"]:
                if src["type"] == "dialog":
                    own |= self.by_dialog.get(src["id"], set())
        need.preds -= own
        need.excludes -= own
        return need


# ---------------------------------------------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------------------------------------------

def _find_cycle(requires: dict[int, set[int]]) -> list[tuple[int, int]] | None:
    """One cycle as a list of edges (stage, required stage), or None (iterative DFS)."""
    state: dict[int, int] = {}
    for root in sorted(requires):
        if state.get(root):
            continue
        path: list[int] = [root]
        iters = {root: iter(sorted(requires[root]))}
        state[root] = 1
        while path:
            node = path[-1]
            nxt = next(iters[node], None)
            if nxt is None:
                state[node] = 2
                path.pop()
            elif state.get(nxt) == 1:
                cyc = path[path.index(nxt):]
                return [(cyc[i], cyc[(i + 1) % len(cyc)]) for i in range(len(cyc))]
            elif not state.get(nxt):
                state[nxt] = 1
                path.append(nxt)
                iters[nxt] = iter(sorted(requires[nxt]))
    return None


def _break_cycles(requires: dict[int, set[int]]) -> int:
    """Remove edges until the graph is acyclic. In each cycle the edge that points furthest forward in script order
    (a stage requiring one that the script writes after it) is the suspect. Returns the number of edges removed."""
    removed = 0
    while (cycle := _find_cycle(requires)) is not None:
        s, p = max(cycle, key=lambda e: (e[1] - e[0], e[0]))
        requires[s].discard(p)
        removed += 1
    return removed


def _reduce(requires: dict[int, set[int]]) -> None:
    """Transitive reduction in place (the graph must be acyclic)."""
    reach: dict[int, set[int]] = {}

    def anc(s: int) -> set[int]:
        if s not in reach:
            reach[s] = set()
            for p in requires[s]:
                reach[s] |= {p} | anc(p)
        return reach[s]

    for s in requires:
        for p in list(requires[s]):
            if any(p in anc(o) for o in requires[s] if o != p):
                requires[s].discard(p)


def _levels(requires: dict[int, set[int]]) -> dict[int, int]:
    memo: dict[int, int] = {}

    def lvl(s: int) -> int:
        if s not in memo:
            memo[s] = 1 + max((lvl(p) for p in requires[s]), default=-1)
        return memo[s]

    return {s: lvl(s) for s in requires}


def _dialog_order_pred(world: World, qr: QuestResolver, st: dict) -> set[int] | None:
    """Heuristic: the stages of the same NPC's quest dialog with the next lower C_INFO.nr (None: no such dialog)."""
    mine = [world.dialogs[s["id"]] for s in st["sources"] if s["type"] == "dialog" and s["id"] in world.dialogs]
    if len(mine) != 1 or mine[0].npc is None:
        return None
    me = mine[0]
    best: tuple[int, str] | None = None
    for dia in qr.by_dialog:
        d = world.dialogs.get(dia)
        if d and d.npc == me.npc and dia != me.name and (d.nr, d.name) < (me.nr, me.name):
            if best is None or (d.nr, d.name) > best:
                best = (d.nr, d.name)
    return set(qr.by_dialog[best[1]]) if best else None


def order_quest(world: World, quest: dict) -> dict:
    """Add requires / requires_source / level / alternative_group / hours to the stages and `order` to the quest.
    Returns counters for the report."""
    stages = quest["stages"]
    qr = QuestResolver(world, quest)
    requires: dict[int, set[int]] = {}
    source: dict[int, str] = {}
    excludes: dict[int, set[int]] = {}
    hours: dict[int, list[list[str]]] = {}
    for k, st in enumerate(stages):
        need = qr.stage_need(st)
        seq = st["seq"]
        hours[seq] = [[a, b] for a, b in (need.time if need else [])]
        excludes[seq] = set(need.excludes) if need else set()
        if need is not None and need.preds:
            requires[seq], source[seq] = set(need.preds), "condition"
        elif need is not None and not need.unknown:
            requires[seq], source[seq] = set(), "condition"
        else:
            guess = _dialog_order_pred(world, qr, st) if need is not None else None
            guess = (guess or set()) - {seq} - qr.by_function.get(st["function"], set())
            if guess:
                requires[seq], source[seq] = guess, "dialog_order"
            else:
                prev = next((p["seq"] for p in reversed(stages[:k]) if p["function"] != st["function"]), None)
                requires[seq], source[seq] = ({prev} if prev else set()), "script_order"
    return {"cycles": apply_order(quest, requires, source, excludes, hours)}


def apply_order(quest: dict, requires: dict[int, set[int]], source: dict[int, str], excludes: dict[int, set[int]],
                hours: dict[int, list[list[str]]]) -> int:
    """Finish a quest's order from raw requirements: break cycles, reduce transitively, number the levels, group the
    mutually exclusive stages, write the fields and decide `order`. Returns the number of edges removed as cycles."""
    stages = quest["stages"]
    cycles = _break_cycles(requires)
    _reduce(requires)
    levels = _levels(requires)
    # mutually exclusive stages (each one demands that the other has not happened)
    mutual = {s: {t for t in ex if s in excludes.get(t, ())} for s, ex in excludes.items()}
    group: dict[int, str] = {}
    seen: set[int] = set()
    letters = iter(ascii_uppercase)
    for s in sorted(mutual):
        if not mutual[s] or s in seen:
            continue
        comp, todo = set(), [s]
        while todo:
            x = todo.pop()
            if x not in comp:
                comp.add(x)
                todo += list(mutual.get(x, ()))
        seen |= comp
        letter = next(letters, None)
        if letter:
            group.update({x: letter for x in comp})
    for st in stages:
        seq = st["seq"]
        st.pop("_address", None)
        st["requires"] = sorted(requires[seq])
        st["requires_source"] = source[seq]
        st["level"] = levels[seq]
        st["alternative_group"] = group.get(seq)
        st["hours"] = hours.get(seq, [])
    known = sum(1 for s in stages if s["requires_source"] != "script_order")
    quest["order"] = "dependency" if stages and known * 5 >= len(stages) * 4 else "script"
    return cycles


def add_order(vm, quests: list[dict], scans, origins) -> dict:
    """Annotate every quest (see order_quest). scans/origins come from quests.collect_events."""
    world = build_world(vm, scans, origins)
    cycles = sum(order_quest(world, q)["cycles"] for q in quests)
    return {"cycles": cycles, "dialogs": len(world.dialogs),
            "dialogs_understood": sum(1 for d in world.dialogs.values() if d.cond.understood)}
