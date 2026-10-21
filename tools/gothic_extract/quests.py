"""Quest (journal topic) extraction from compiled Daedalus.

A topic is identified by its display name: the engine keys the journal by that string, so several
script constants with the same name (TOPIC_X in G2, CH3_X in G1) are aliases of one topic.
Everything is read from call sites and constant assignments, so a link is reported only when the script
proves it; the rest stays empty or carries certainty "possible".

Journal primitives are Log_CreateTopic / Log_AddEntry / Log_SetTopicStatus. Wrappers that pass their own
parameters on (B_LogEntry) are unwrapped at each call site. G2 closes topics through
B_CloseTopic(topic, MIS_var, ...), which ties a topic to its mission variable; assignments `MIS_var = LOG_*`
are then the topic's status changes.
"""
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

import zenkit
from zenkit.daedalus.item import ItemInstanceStateSlot
from zenkit.daedalus.npc import NpcInstanceNameSlot

from .catalog import instances_of
from .daedalus_scan import CallSite, Op, _idx, functions, scan_assignments, scan_function, symbol_name
from .text import game_text

CREATE, ENTRY, STATUS, CLOSE = "create", "entry", "status", "close"
_PRIMITIVES = {"LOG_CREATETOPIC": CREATE, "LOG_ADDENTRY": ENTRY, "LOG_SETTOPICSTATUS": STATUS}
_XP_CALLS = {"B_GIVEXP", "B_GIVEPLAYERXP"}
_ORIGIN_CAP = 40  # a helper reachable from more dialogs than this is a shared utility, not a quest source
_CHAPTER_RE = re.compile(r"(?:KAPITEL|_KAP)_?(\d)")
_PLAYER = {"HERO", "OTHER", "PC_HERO"}
# calls that take a function as an argument: callee -> argument index; the passed function runs on behalf of the caller
_FUNCTION_ARGS = {"INFO_ADDCHOICE": 2, "AI_STARTSTATE": 1}
# NPC-referencing calls in a stage function: callee -> role
_NPC_ROLES = {"WLD_INSERTNPC": "insert", "B_STARTOTHERROUTINE": "routine", "NPC_EXCHANGEROUTINE": "routine",
              "HLP_GETNPC": "stage"}


@dataclass
class Origin:
    kind: str                 # "dialog" | "item"
    name: str                 # C_INFO instance, or item code
    npc: str | None           # dialog NPC instance or None
    function: str             # info/use function the event is reached from
    chapter: int | None = None


@dataclass
class Event:
    kind: str                 # create | entry | status | close
    topic: str                # topic constant (symbol name)
    caller: str               # function holding the call
    conditional: bool
    address: int
    text: str | None = None   # entry text
    value: int | None = None  # status value, or section for create
    title: str | None = None  # create: topic display name
    mission_var: str | None = None  # close: MIS_ variable passed to the closing wrapper
    via: str = "log"          # "log" (journal call) | "mission_var" (MIS_ assignment)
    origins: list[Origin] = field(default_factory=list)


def _param_index(script) -> dict[str, list[str]]:
    """function name -> its parameter symbols ("FUNC.PARAM") in declaration order."""
    out: dict[str, list[str]] = defaultdict(list)
    for s in script.symbols:
        head, dot, tail = s.name.partition(".")
        if dot and "." not in tail and s.type != zenkit.DaedalusDataType.FUNCTION:
            out[head].append(s.name)
    return out


def _event(c: CallSite, kind: str, topic: str, args: list) -> Event:
    if kind == CREATE:
        return Event(kind, topic, c.caller, c.conditional, c.address, title=args[0] if isinstance(args[0], str) else None,
                     value=args[1] if isinstance(args[1], int) else None)
    if kind == ENTRY:
        return Event(kind, topic, c.caller, c.conditional, c.address, text=args[1] if isinstance(args[1], str) else None)
    return Event(kind, topic, c.caller, c.conditional, c.address, value=args[1] if isinstance(args[1], int) else None)


def _log_sites(script, scans: dict[str, list[CallSite]]) -> list[Event]:
    """All journal primitives; a wrapper (B_LogEntry, B_CloseTopic) that passes its own parameters on is unwrapped
    at each of its call sites, so topic and text come from the caller's constants."""
    params_of = _param_index(script)
    prim = [(c, _PRIMITIVES[c.callee]) for cs in scans.values() for c in cs if c.callee in _PRIMITIVES]
    wrappers: dict[str, list[tuple[CallSite, str, dict[int, int]]]] = defaultdict(list)
    events = []
    for c, kind in prim:
        params = params_of.get(c.caller, [])
        passthrough = {j: params.index(a) for j, a in enumerate(c.arg_syms) if a in params}
        if 0 in passthrough:
            wrappers[c.caller].append((c, kind, passthrough))
        elif c.arg_syms[0]:
            events.append(_event(c, kind, c.arg_syms[0], c.args))
    for cs in scans.values() if wrappers else ():
        for call in cs:
            sites = wrappers.get(call.callee)
            if not sites:
                continue
            built = []
            for c, kind, passthrough in sites:
                args = [call.args[passthrough[j]] if j in passthrough and passthrough[j] < len(call.args) else v
                        for j, v in enumerate(c.args)]
                top = call.arg_syms[passthrough[0]] if passthrough[0] < len(call.arg_syms) else None
                if top:
                    built.append((c, kind, top, args))
            statuses = [b for b in built if b[1] == STATUS]
            if len({b[3][1] for b in statuses}) > 1:
                # one wrapper with several state-dependent outcomes (B_CloseTopic): the outcome is decided at run time
                # from the mission variable passed in, so this only ties the topic to that variable
                wparams = params_of.get(call.callee, [])
                var = next((call.arg_syms[i] for i, p in enumerate(wparams)
                            if p.endswith(".MISSIONVAR") and i < len(call.arg_syms)), None)
                events.append(Event(CLOSE, statuses[0][2], call.caller, True, call.address, mission_var=var))
                built = [b for b in built if b[1] != STATUS]
            for c, kind, top, args in built:
                events.append(_event(CallSite(call.caller, c.callee, args, call.conditional or c.conditional,
                                              call.address), kind, top, args))
    return events


def _kapitel_min(script, fn_sym) -> int | None:
    """Lowest chapter a condition function demands: `Kapitel == n`, `>= n`, `> n` against a constant, when it
    tests the chapter exactly once (several tests could be alternatives, so then it is left unknown)."""
    code = _idx(script).code(fn_sym)
    hits = []
    for k, ins in enumerate(code):
        if ins.op not in (Op.PUSHV, Op.PUSHVI):
            continue
        sym = script.get_symbol_by_index(ins.symbol)
        if sym is None or sym.name != "KAPITEL":
            continue
        lo = None
        if k >= 1 and k + 1 < len(code) and code[k - 1].op == Op.PUSHI:
            n, op = code[k - 1].immediate, code[k + 1].op
            lo = n if op in (Op.EQ, Op.GTE) else n + 1 if op == Op.GT else None
        hits.append(lo)
    return hits[0] if len(hits) == 1 else None


def _chapter_of_name(name: str) -> int | None:
    m = _CHAPTER_RE.search(name)
    return int(m.group(1)) if m else None


def _info_table(script) -> dict[str, tuple[str, str | None, int | None]]:
    """information function -> (C_INFO instance, dialog NPC instance, chapter the dialog needs)."""
    out = {}
    for s in instances_of(script, "C_INFO"):
        info = script.init_instance(s, zenkit.DaedalusInstanceType.INFO)
        fn = script.get_symbol_by_index(info.information) if info.information > 0 else None
        npc = script.get_symbol_by_index(info.npc) if info.npc > 0 else None
        cond = script.get_symbol_by_index(info.condition) if info.condition > 0 else None
        if fn is None:
            continue
        chapter = _chapter_of_name(fn.name) or _chapter_of_name(s.name)
        if chapter is None and cond is not None and not cond.is_external and cond.address > 0:
            chapter = _kapitel_min(script, cond)
        out[fn.name] = (s.name, npc.name if npc is not None else None, chapter)
    return out


def _item_use_table(script) -> dict[str, str]:
    """USE function -> item code."""
    out = {}
    for s in instances_of(script, "C_ITEM"):
        it = script.init_instance(s, zenkit.DaedalusInstanceType.ITEM)
        fn_idx = it.get_on_state(ItemInstanceStateSlot.SLOT0)
        fn = script.get_symbol_by_index(fn_idx) if fn_idx > 0 else None
        if fn is not None:
            out[fn.name] = s.name
    return out


def _attach_origins(script, events: list[Event], scans, infos, uses) -> None:
    callers_of: dict[str, set[str]] = defaultdict(set)
    for f, cs in scans.items():
        for c in cs:
            callers_of[c.callee].add(f)
            idx = _FUNCTION_ARGS.get(c.callee)
            target = symbol_name(script, c.args[idx]) if idx is not None and idx < len(c.args) else None
            if target:
                callers_of[target.upper()].add(f)
    cache: dict[str, list[Origin]] = {}

    def origins(fn: str) -> list[Origin]:
        if fn in cache:
            return cache[fn]
        found, seen, todo = [], {fn}, deque([fn])
        while todo and len(seen) < 4000:
            cur = todo.popleft()
            if cur in infos:
                name, npc, chapter = infos[cur]
                found.append(Origin("dialog", name, npc, cur, chapter))
            if cur in uses:
                found.append(Origin("item", uses[cur], None, cur, _chapter_of_name(cur)))
            for up in callers_of.get(cur, ()):
                if up not in seen:
                    seen.add(up)
                    todo.append(up)
        cache[fn] = found if len(found) <= _ORIGIN_CAP else []
        return cache[fn]

    for e in events:
        e.origins = origins(e.caller)
    return origins


def collect_events(vm: zenkit.DaedalusVm) -> tuple[list[Event], dict, object]:
    scans = {f.name: scan_function(vm, f) for f in functions(vm)}
    events = _log_sites(vm, scans)
    origins = _attach_origins(vm, events, scans, _info_table(vm), _item_use_table(vm))
    return events, scans, origins


@dataclass
class Topic:
    code: str
    aliases: list[str]
    name: str
    section: int
    mission_var: str | None
    events: list[Event]


def group_topics(events: list[Event]) -> list[Topic]:
    titles: dict[str, str] = {}
    sections: dict[str, int] = {}
    for e in events:
        if e.kind == CREATE and e.title:
            titles.setdefault(e.topic, e.title)
            if e.value is not None:
                sections.setdefault(e.topic, e.value)
    by_title: dict[str, list[str]] = defaultdict(list)
    for code, title in titles.items():
        by_title[title].append(code)
    topics = []
    for title, codes in by_title.items():
        evs = [e for e in events if e.topic in codes]
        vars_ = sorted({e.mission_var for e in evs if e.kind == CLOSE and e.mission_var and e.mission_var.startswith("MIS_")})
        topics.append(Topic(codes[0], codes, title, sections.get(codes[0], 0), vars_[0] if len(vars_) == 1 else None, evs))
    return topics


def names_of(vm) -> tuple[dict[str, str], dict[str, str]]:
    """(NPC instance -> Polish name, item instance -> Polish name), keys upper-case."""
    npcs, items = {}, {}
    for s in instances_of(vm, "C_NPC"):
        npcs[s.name.upper()] = game_text(vm.init_instance(s, zenkit.DaedalusInstanceType.NPC).get_name(NpcInstanceNameSlot.SLOT0))
    for s in instances_of(vm, "C_ITEM"):
        items[s.name.upper()] = game_text(vm.init_instance(s, zenkit.DaedalusInstanceType.ITEM).name)
    return npcs, items


def _merge(entries: list[tuple[object, int, bool]]) -> dict[object, tuple[int, str]]:
    """(key, amount, conditional) -> key -> (amount, certainty): unconditional adds up, conditional takes the largest."""
    tot: dict[tuple, int] = defaultdict(int)
    for key, amount, cond in entries:
        k = (key, "possible" if cond else "always")
        tot[k] = max(tot[k], amount) if cond else tot[k] + amount
    out: dict[object, tuple[int, str]] = {}
    for (key, cert), n in sorted(tot.items(), key=lambda kv: kv[0][1] != "always"):
        out.setdefault(key, (n, cert))
    return out


def extract_quests(vm: zenkit.DaedalusVm) -> list[dict]:
    """World-independent quest records (one per topic name); fields are described in geoportal_README."""
    events, scans, origins = collect_events(vm)
    npc_names, item_names = names_of(vm)
    status_names = {s.get_int(): s.name[4:].upper() for s in vm.symbols
                    if s.name in ("LOG_RUNNING", "LOG_SUCCESS", "LOG_FAILED", "LOG_OBSOLETE") and s.is_const}
    topics = group_topics(events)
    by_var = {t.mission_var: t for t in topics if t.mission_var}
    # status changes done by `MIS_var = LOG_*`
    for f in functions(vm):
        for a in scan_assignments(vm, f):
            t = by_var.get(a.var)
            if t is not None and a.value in status_names:
                t.events.append(Event(STATUS, t.code, f.name, a.conditional, a.address, value=a.value, via="mission_var",
                                      origins=origins(f.name)))
    # a function that completes several topics cannot tell which one its rewards belong to
    success_topics: dict[str, set[str]] = defaultdict(set)
    for t in topics:
        for e in t.events:
            if e.kind == STATUS and status_names.get(e.value) == "SUCCESS":
                success_topics[e.caller].add(t.code)
    ctx = (scans, npc_names, item_names, status_names, success_topics)
    return [_quest(vm, t, ctx) for t in sorted(topics, key=lambda t: t.code)]


def _quest(vm, t: Topic, ctx) -> dict:
    scans, npc_names, item_names, status_names, success_topics = ctx
    npc_set, item_set = set(npc_names), set(item_names)
    # the giver is the NPC whose dialog starts the quest (sets it RUNNING); failing that, the one whose dialog creates the topic
    def dialog_npcs(kind: str, status: str | None = None) -> list[str]:
        return sorted({o.npc.upper() for e in t.events if e.kind == kind and (status is None or status_names.get(e.value) == status)
                       for o in e.origins if o.kind == "dialog" and o.npc})
    starters, creators = dialog_npcs(STATUS, "RUNNING"), dialog_npcs(CREATE)
    creators = starters if len(starters) == 1 else sorted(set(starters) | set(creators)) if starters and not creators else creators
    giver = creators[0] if len(creators) == 1 else None
    stages_ev = sorted((e for e in t.events if e.kind in (ENTRY, STATUS)), key=lambda e: e.address)
    seen_status: set[tuple[str, int | None]] = set()
    stages = []
    for e in stages_ev:
        if e.kind == STATUS:
            key = (e.caller, e.value)  # explicit call and MIS_ assignment in one function are the same change
            if key in seen_status or e.value not in status_names:
                continue
            seen_status.add(key)
        by_name = _chapter_of_name(e.caller)
        chapters = {o.chapter for o in e.origins if o.chapter is not None}
        chapter = by_name or (next(iter(chapters)) if len(chapters) == 1 else None)
        sources = [{"type": o.kind, "id": o.name, "function": o.function,
                    **({"npc": o.npc.upper(), "npc_name": npc_names.get(o.npc.upper())} if o.npc else {}),
                    **({"name": item_names.get(o.name.upper())} if o.kind == "item" else {})} for o in e.origins]
        st = {"seq": len(stages) + 1, "kind": e.kind, "chapter": chapter,
              "chapter_source": None if chapter is None else ("function" if by_name else "condition"),
              "conditional": e.conditional, "function": e.caller, "sources": sources}
        if e.kind == ENTRY:
            st["text"] = e.text
        else:
            st["status"] = status_names[e.value]
            st["via"] = e.via
        stages.append(st)

    # characters, items and rewards come from the stage functions' own bodies (not their callees)
    stage_fns = {e.caller for e in stages_ev}
    success_fns = {e.caller for e in t.events if e.kind == STATUS and status_names.get(e.value) == "SUCCESS"}
    chars: list[tuple[tuple[str, str], int, bool]] = [((c, "giver" if giver else "giver_candidate"), 1, False) for c in creators]
    for e in stages_ev:
        chars += [((o.npc.upper(), "stage"), 1, False) for o in e.origins if o.kind == "dialog" and o.npc]
    items: list[tuple[tuple[str, str], int, bool]] = []
    xp: list[tuple[str, int, bool]] = []
    for fn in sorted(stage_fns):
        ambiguous = fn in success_fns and len(success_topics[fn]) > 1
        for c in scans.get(fn, []):
            role = _NPC_ROLES.get(c.callee)
            if role and c.args:
                code = (symbol_name(vm, c.args[0]) or "").upper()
                if code in npc_set and code not in _PLAYER:
                    chars.append(((code, role), 1, c.conditional))
            if c.callee == "WLD_INSERTITEM" and c.args:
                code = (symbol_name(vm, c.args[0]) or "").upper()
                if code in item_set:
                    items.append(((code, "placed"), 1, c.conditional))
            if c.callee in ("CREATEINVITEM", "CREATEINVITEMS", "B_GIVEINVITEMS"):
                give = c.callee == "B_GIVEINVITEMS"      # B_GiveInvItems(giver, taker, item, amount)
                ix = 2 if give else 1                    # CreateInvItem(s)(taker, item[, amount])
                giver_sym = (c.arg_syms[0] or "").upper() if give and c.arg_syms else ""
                taker_sym = (c.arg_syms[1 if give else 0] or "").upper() if len(c.arg_syms) > 1 else ""
                code = (symbol_name(vm, c.args[ix]) or "").upper() if len(c.args) > ix else ""
                n = c.args[ix + 1] if len(c.args) > ix + 1 and isinstance(c.args[ix + 1], int) else 1
                if code not in item_set:
                    continue
                if giver_sym in _PLAYER and taker_sym not in _PLAYER:
                    items.append(((code, "handover"), n, c.conditional))
                elif fn in success_fns and taker_sym in _PLAYER:
                    items.append(((code, "reward"), n, c.conditional or ambiguous))
            if c.callee in _XP_CALLS and fn in success_fns and c.args and isinstance(c.args[0], int):
                xp.append((fn, c.args[0], c.conditional or ambiguous))
    characters = [{"code": code, "name": npc_names.get(code), "role": role,
                   "certainty": "possible" if role == "giver_candidate" else cert}
                  for (code, role), (_, cert) in _merge(chars).items()]
    item_out = [{"code": code, "name": item_names.get(code), "role": role, "amount": n, "certainty": cert}
                for (code, role), (n, cert) in _merge(items).items()]
    rewards = {"xp": None, "xp_certainty": None}
    if xp:
        always = [v for _, v, c in xp if not c]
        rewards = {"xp": sum(always) if always else max(v for _, v, _ in xp),
                   "xp_certainty": "always" if always else "possible"}
    staged = next((s for s in stages if s["chapter"] is not None), None)
    return {"id": f"quest:{t.code}", "code": t.code, "aliases": t.aliases[1:], "name": t.name,
            "section": "note" if t.section == 1 else "mission", "mission_var": t.mission_var,
            "chapter": staged["chapter"] if staged else None,
            "chapter_source": staged["chapter_source"] if staged else None,
            "giver": {"code": giver, "name": npc_names.get(giver)} if giver else None,
            "giver_certainty": "always" if giver else ("possible" if creators else None),
            "giver_candidates": [] if giver else [{"code": c, "name": npc_names.get(c)} for c in creators],
            "order": "script", "stages": stages, "characters": characters, "items": item_out, "rewards": rewards}
