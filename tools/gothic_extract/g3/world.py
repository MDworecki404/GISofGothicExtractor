"""Gothic 3 world entities -> the shared records (items on the ground, containers, NPCs with routines).

Rules (spec, section 4):
- an entity with gCNPC_PS is an NPC; its inventory = gCInventoryStack objects of its gCInventory_PS plus the item
  entities below it (weapons it carries); all with certainty "always";
- an entity with gCInventory_PS and no gCNPC_PS is a container (chest, sack); contents = its stacks;
- an entity with gCItem_PS that is not below an NPC or a container lies in the world (source "zen");
- template references (entity creator, stack Template) are GUIDs of template entities (templates.py).
Random loot (TreasureSet1..5) is not resolved here (stage 5).
"""
import fnmatch
import re
from collections import Counter
from dataclasses import dataclass, field

from ..config import GameConfig
from ..npcs import InvItem, NpcRec, RoutinePoint
from ..records import ContainerRec, ItemRec, WorldData
from .archive import G3Fs
from .catalog import is_item_template
from .entities import Entity, read_entity_file, walk
from .genome import FormatError, PropertyObject, Reader, parse_genomfle, read_property_object
from .npc_codes import HUMAN_SPECIES, alignment_code
from .templates import TemplateRec

_OBJ_HEAD = b"\x01\x00\x01\x01\x00\x01"
_ROUTINE_POINTS = [("WorkingPoint", "work", "WORK"), ("RelaxingPoint", "relax", "RELAX"),
                   ("SleepingPoint", "sleep", "SLEEP")]
DASH = "–"
STORY_SECTOR = "sektor fabularny"  # NpcRec.insert_function of NPCs from sectors the quests switch on


@dataclass
class _Loaded:
    sector: str
    enabled: bool  # sector =true in the world file (present from the start of the game)
    entity: Entity
    data: bytes
    strings: list[str]
    parent: Entity | None


@dataclass
class WorldStats:
    sectors: int = 0
    unsupported_sectors: list[str] = field(default_factory=list)
    unknown_templates: Counter = field(default_factory=Counter)


def active_sectors(fs: G3Fs, world: str, exclude: list[str], include_disabled: bool = False) -> list[str]:
    """Entity files (<sector>/<sector>.lrentdat) of the sectors enabled in <world>.wrldatasc, without `exclude`;
    with include_disabled also the sectors set to false (story scenes switched on by quests), after the others."""
    return [p for p, _ in sector_files(fs, world, exclude, include_disabled)]


def sector_files(fs: G3Fs, world: str, exclude: list[str], include_disabled: bool = False) -> list[tuple[str, bool]]:
    """(entity file, enabled at the start) per sector, see active_sectors."""
    text = fs.find(f"{world}/{world}.wrldatasc")
    if text is None:
        raise FileNotFoundError(f"{world}.wrldatasc not found")
    enabled, disabled, section = [], [], ""
    for line in text.decode("latin-1").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
            continue
        name, sep, value = line.partition("=")
        if section != "[Sector.List]" or not sep or any(fnmatch.fnmatch(name.lower(), p.lower()) for p in exclude):
            continue
        (enabled if value.strip().lower() == "true" else disabled).append(name.lower())
    files = {p.split("/")[-1][:-len(".lrentdat")].lower(): p for p in fs.list(world + "/", ".lrentdat")
             if p.split("/")[-2].lower() + ".lrentdat" == p.split("/")[-1].lower()}
    out = [(files[s], True) for s in enabled if s in files]
    if include_disabled:
        out += [(files[s], False) for s in disabled if s in files]
    return out


def stacks(obj: PropertyObject, data: bytes, strings: list[str]) -> list[PropertyObject]:
    """gCInventoryStack objects inside the class data of gCInventory_PS."""
    out, i = [], obj.data_start
    while (j := data.find(_OBJ_HEAD, i, obj.data_end)) != -1:
        try:
            o = read_property_object(Reader(data, j), strings)
        except (FormatError, IndexError):
            i = j + 1
            continue
        if o is not None and o.cls == "gCInventoryStack":
            out.append(o)
        i = o.data_end if o is not None else j + 1
    return out


def treasure_sets(e: Entity) -> list[str]:
    inv = e.props.get("gCInventory_PS")
    if inv is None:
        return []
    return [inv.props[f"TreasureSet{i}"].value for i in range(1, 6)
            if f"TreasureSet{i}" in inv.props and inv.props[f"TreasureSet{i}"].value]


def _value(e: Entity, cls: str, prop: str, default=None):
    obj = e.props.get(cls)
    return obj.props[prop].value if obj is not None and prop in obj.props else default


def _visual(e: Entity) -> str | None:
    for cls in ("eCVisualMeshDynamic_PS", "eCVisualMeshStatic_PS", "eCVisualAnimation_PS"):
        v = _value(e, cls, "ResourceFilePath")
        if isinstance(v, str) and v:
            return v
    return None


def _slot(slot: str) -> tuple[str, str]:
    start, _, end = slot.partition(DASH)
    return start, end


class _Resolver:
    def __init__(self, templates: dict[str, TemplateRec], stats: WorldStats):
        self.templates, self.stats = templates, stats

    def code(self, guid: str | None, fallback: str | None = None) -> str | None:
        """Item code of a template GUID; None for templates that are not items (body parts); '?{guid}' if unknown."""
        if guid is None:
            return fallback
        t = self.templates.get(guid)
        if t is None:
            self.stats.unknown_templates[guid] += 1
            return fallback or "?" + guid
        return t.name if is_item_template(t) else None

    def inventory(self, item: _Loaded) -> list[tuple[str, int]]:
        out = []
        inv = item.entity.props.get("gCInventory_PS")
        if inv is None:
            return out
        for st in stacks(inv, item.data, item.strings):
            code = self.code(st.props["Template"].value if "Template" in st.props else None)
            if code:
                out.append((code, st.props["Amount"].value if "Amount" in st.props else 1))
        return out


def _load(fs: G3Fs, paths: list[tuple[str, bool]], stats: WorldStats) -> list[_Loaded]:
    out, seen = [], set()
    for path, enabled in paths:
        data = fs.find(path)
        if not data.startswith(b"GENOMFLE"):
            stats.unsupported_sectors.append(path)
            continue
        roots, _ = read_entity_file(data)
        strings = parse_genomfle(data).strings
        sector = path.split("/")[-2]
        stats.sectors += 1
        stack = [(r, None) for r in roots]
        while stack:
            e, parent = stack.pop()
            if e.guid and e.guid in seen:  # the same entity in two files: keep the first
                continue
            if e.guid:
                seen.add(e.guid)
            out.append(_Loaded(sector, enabled, e, data, strings, parent))
            stack.extend((c, e) for c in e.children)
    return out


def extract_world(fs: G3Fs, cfg: GameConfig, world: str, templates: dict[str, TemplateRec],
                  strings: dict[str, str], stats: WorldStats | None = None) -> tuple[WorldData, list[NpcRec]]:
    stats = stats if stats is not None else WorldStats()
    res = _Resolver(templates, stats)
    loaded = _load(fs, sector_files(fs, world, cfg.sector_exclude, cfg.include_disabled_sectors), stats)
    by_guid = {x.entity.guid: x.entity for x in loaded if x.entity.guid}
    holders = {id(x.entity) for x in loaded if "gCInventory_PS" in x.entity.props}

    wd = WorldData()
    npcs: list[NpcRec] = []
    for x in loaded:
        e = x.entity
        if "gCItem_PS" in e.props and not (x.parent is not None and id(x.parent) in holders):
            code = res.code(e.creator, fallback=e.name)
            if code:
                # items of story sectors appear during the game: "script" with the sector as the spot
                source, spot = ("zen", None) if x.enabled else ("script", x.sector)
                wd.items.append(ItemRec(code, _value(e, "gCItem_PS", "Amount", 1) or 1, e.pos, source, None, spot))
        elif "gCInventory_PS" in e.props and "gCNPC_PS" not in e.props:
            locked = _value(e, "gCLock_PS", "Status") == 0
            key = res.code(_value(e, "gCLock_PS", "Key")) if locked else None
            wd.containers.append(ContainerRec(len(wd.containers), e.name, _visual(e), e.pos, locked, key, None,
                                              res.inventory(x), treasure_sets(e)))
        elif "gCNPC_PS" in e.props:
            npcs.append(_npc(x, res, by_guid, cfg, strings))

    # inserts_in_game / name_unique_in_game need every NPC
    counts = Counter(n.code for n in npcs)
    codes_by_name: dict[str, set[str]] = {}
    for n in npcs:
        codes_by_name.setdefault(n.name, set()).add(n.code)
    for n in npcs:
        n.inserts_in_game = counts[n.code]
        n.name_unique_in_game = len(codes_by_name[n.name]) == 1
    return wd, npcs


def _npc(x: _Loaded, res: _Resolver, by_guid: dict[str, Entity], cfg: GameConfig,
         strings: dict[str, str]) -> NpcRec:
    e = x.entity
    align = _value(e, "gCNPC_PS", "PoliticalAlignment", 0) or 0
    inventory = [InvItem(code, n, "always") for code, n in res.inventory(x)]
    for c in walk(e.children):
        if "gCItem_PS" in c.props:
            code = res.code(c.creator, fallback=c.name)
            if code:
                inventory.append(InvItem(code, _value(c, "gCItem_PS", "Amount", 1) or 1, "always"))
    return NpcRec(
        code=e.name,
        name=strings.get("FO_" + e.name) or e.name,
        guild=align,
        guild_name=alignment_code(align),
        level=_value(e, "gCNPC_PS", "Level", 0) or 0,
        insert_waypoint=x.sector,
        insert_function="" if x.enabled else STORY_SECTOR,
        chapter=None,
        pos=e.pos,
        inventory=inventory,
        routines=_routines(e, by_guid, cfg),
        is_human=_value(e, "gCNPC_PS", "Species") in HUMAN_SPECIES,
        treasure_sets=treasure_sets(e),
    )


def _routines(e: Entity, by_guid: dict[str, Entity], cfg: GameConfig) -> list[RoutinePoint]:
    nav = e.props.get("gCNavigation_PS")
    if nav is None:
        return []
    routine = nav.props["Routine"].value if "Routine" in nav.props and nav.props["Routine"].value else "START"
    out = []
    for prop, kind, action in _ROUTINE_POINTS:
        guids = []
        single = nav.props.get(prop)
        if single is not None and isinstance(single.value, str):
            guids.append(single.value)
        many = nav.props.get(prop + "s")
        if many is not None and isinstance(many.value, list):
            guids += [g for g in many.value if g and g not in guids]
        for g in guids:
            point = by_guid.get(g)
            if point is None:  # shared "no point" GUIDs (the same in every sector) and points in unloaded sectors
                continue
            for slot in cfg.routine_slots.get(kind, []):
                start, end = _slot(slot)
                out.append(RoutinePoint(routine, True, start, end, action, point.name, point.pos))
    return out
