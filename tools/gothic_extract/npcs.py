import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import zenkit
from zenkit.daedalus.npc import NpcInstanceNameSlot

from .catalog import instances_of
from .daedalus_scan import find_calls, functions, reachable_calls, scan_function, symbol_name
from .records import ItemRec, Vec3
from .text import game_text
from .world_data import PointResolver

_INV_CALLS = {"CREATEINVITEM", "CREATEINVITEMS", "EQUIPITEM"}
# Random filler loot shared by ambient NPCs (apples, booze, small gold); not useful on the map.
_SKIP_INV_HELPERS = ["B_CREATEAMBIENTINV*"]
_CHAPTER_RE = re.compile(r"(?:KAPITEL|_KAP)_?(\d)")


@dataclass
class InvItem:
    code: str
    amount: int
    certainty: str  # "always" | "possible"


@dataclass
class RoutinePoint:
    routine: str
    is_default: bool
    start: str
    end: str
    action: str
    waypoint: str
    pos: Vec3 | None


@dataclass
class NpcRec:
    code: str
    name: str
    guild: int
    guild_name: str
    level: int
    insert_waypoint: str
    insert_function: str
    chapter: int | None
    pos: Vec3 | None
    inventory: list[InvItem] = field(default_factory=list)
    routines: list[RoutinePoint] = field(default_factory=list)
    name_unique_in_game: bool = False  # no other NPC instance in the whole script has this name
    is_human: bool = False  # guild below GIL_SEPERATOR_HUM, incl. GIL_NONE (people, not monsters/orcs)
    inserts_in_game: int = 0  # Wld_InsertNpc calls for this instance across all worlds
    treasure_sets: list[str] = field(default_factory=list)  # G3: random loot sets (codes); empty in G1/G2


def _chapter(func_name: str) -> int | None:
    m = _CHAPTER_RE.search(func_name)
    return int(m.group(1)) if m else None


def _guild_names(script) -> dict[int, str]:
    out: dict[int, str] = {}
    for s in script.symbols:
        if s.name.startswith("GIL_") and s.is_const and s.type == zenkit.DaedalusDataType.INT and "." not in s.name:
            out.setdefault(s.get_int(), s.name[4:])
    return out


def _hhmm(h, m) -> str:
    return f"{h:02d}:{m:02d}" if isinstance(h, int) and isinstance(m, int) else "??:??"


def merge_inventory(entries: list[tuple[str, int, bool]]) -> list[InvItem]:
    """(code, amount, conditional) call sites → inventory.

    Unconditional amounts add up; conditional branches are usually mutually exclusive
    (Hlp_Random, guild, chapter), so the largest one is reported.
    """
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for code, amount, conditional in entries:
        amount = max(amount, 1)
        key = (code, "possible" if conditional else "always")
        totals[key] = max(totals[key], amount) if conditional else totals[key] + amount
    return [InvItem(code, n, cert) for (code, cert), n in sorted(totals.items())]


def _inventory(vm, code: str) -> list[InvItem]:
    entries = []
    for c in reachable_calls(vm, code, _INV_CALLS, skip=_SKIP_INV_HELPERS):
        item = symbol_name(vm, c.args[1] if len(c.args) > 1 else None)
        if not item or not item.upper().startswith("IT"):
            continue
        amount = c.args[2] if c.callee == "CREATEINVITEMS" and isinstance(c.args[2], int) else 1
        entries.append((item.upper(), amount, c.conditional))
    return merge_inventory(entries)


def _routine_points(vm, npc_id: int, default_fn: str | None, resolver: PointResolver, rtn_by_id) -> list[RoutinePoint]:
    out = []
    for fn in rtn_by_id.get(npc_id, []):
        routine = fn.name[len("RTN_"): -len(f"_{npc_id}")]
        for c in scan_function(vm, fn):
            if c.callee == "TA_MIN" and len(c.args) >= 7:
                h1, m1, h2, m2, action, wp = c.args[1], c.args[2], c.args[3], c.args[4], symbol_name(vm, c.args[5]), c.args[6]
            elif c.callee.startswith("TA_") and len(c.args) == 5:
                h1, m1, h2, m2, wp = c.args
                action = c.callee
            else:
                continue
            wp = wp if isinstance(wp, str) else ""
            out.append(RoutinePoint(routine, fn.name == default_fn, _hhmm(h1, m1), _hhmm(h2, m2),
                                    action or "", wp, resolver.resolve(wp)))
    return out


def _routines_by_id(vm) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    rx = re.compile(r"^RTN_.+_(\d+)$")
    for f in functions(vm):
        m = rx.match(f.name)
        if m:
            out[int(m.group(1))].append(f)
    return out


def game_name_counts(vm: zenkit.DaedalusVm) -> Counter:
    """How many NPC instances across all worlds share each display name."""
    out: Counter = Counter()
    for sym in instances_of(vm, "C_NPC"):
        npc = vm.init_instance(sym, zenkit.DaedalusInstanceType.NPC)
        out[game_text(npc.get_name(NpcInstanceNameSlot.SLOT0))] += 1
    return out


def extract_npcs(vm: zenkit.DaedalusVm, resolver: PointResolver, exclude: set[str] = frozenset(),
                 first_chapter: int | None = None, chapter_of: dict[str, int] | None = None) -> list[NpcRec]:
    """exclude: names of functions whose inserts belong to other worlds.

    first_chapter: chapter given to inserts outside any chapter function (None = leave empty).
    chapter_of: function name -> chapter, for games whose chapter functions are not named after the chapter (G1).
    """
    name_counts = game_name_counts(vm)
    all_inserts = find_calls(vm, {"WLD_INSERTNPC"})
    inserts_in_game = Counter((symbol_name(vm, c.args[0]) or "").upper() for c in all_inserts)
    sep = vm.get_symbol_by_name("GIL_SEPERATOR_HUM")
    human_below = sep.get_int() if sep is not None else 16
    known = resolver.names()
    guilds = _guild_names(vm)
    rtn_by_id = _routines_by_id(vm)
    cache: dict[str, tuple] = {}
    out = []
    for c in all_inserts:
        if c.caller in exclude:
            continue
        code = symbol_name(vm, c.args[0])
        wp = c.args[1]
        if not code or not isinstance(wp, str) or wp.upper() not in known:
            continue
        code = code.upper()
        if code not in cache:
            npc = vm.init_instance(code, zenkit.DaedalusInstanceType.NPC)
            rtn = vm.get_symbol_by_index(npc.daily_routine) if npc.daily_routine > 0 else None
            cache[code] = (
                game_text(npc.get_name(NpcInstanceNameSlot.SLOT0)),
                npc.guild,
                npc.level,
                _inventory(vm, code),
                _routine_points(vm, npc.id, rtn.name if rtn else None, resolver, rtn_by_id),
            )
        name, guild, level, inv, routines = cache[code]
        out.append(NpcRec(code, name, guild, guilds.get(guild, str(guild)), level, wp.upper(), c.caller,
                          _chapter(c.caller) or (chapter_of or {}).get(c.caller) or first_chapter, resolver.resolve(wp), inv, routines, name_counts[name] == 1,
                          guild < human_below, inserts_in_game[code]))
    return out


def extract_script_items(vm: zenkit.DaedalusVm, resolver: PointResolver, exclude: set[str] = frozenset()) -> list[ItemRec]:
    known = resolver.names()
    out = []
    for c in find_calls(vm, {"WLD_INSERTITEM"}):
        if c.caller in exclude:
            continue
        code = symbol_name(vm, c.args[0])
        spot = c.args[1]
        if not code or not isinstance(spot, str) or spot.upper() not in known:
            continue
        out.append(ItemRec(code.upper(), 1, resolver.resolve(spot), "script", None, spot.upper()))
    return out
