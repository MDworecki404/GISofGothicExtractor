"""Gothic 3 treasure sets (random loot): templates under Treasure/ with gCTreasureSet_PS.

Each set lists candidate item stacks; the game draws MinTransferStacks..MaxTransferStacks of them (0/0 in the
"unique" chest sets: one item that drops once per game). Containers and NPCs name up to five sets in
gCInventory_PS.TreasureSet1..5. The kind comes from the template folder (Treasure/<Chests|NPC|Monster|Trader|Misc>),
which is more reliable than the meaning of the TreasureDistribution value.
"""
from dataclasses import asdict, dataclass, field

from .archive import G3Fs
from .catalog import is_item_template
from .genome import parse_genomfle
from .templates import TemplateRec

KIND_BY_FOLDER = {"Chests": "chest", "NPC": "npc", "Monster": "monster", "Trader": "trader", "Misc": "mining"}


@dataclass
class TreasureSet:
    code: str
    kind: str  # chest | npc | monster | trader | mining
    distribution: int  # gCTreasureSet_PS.TreasureDistribution (raw)
    min_stacks: int
    max_stacks: int
    items: list[tuple[str, int]] = field(default_factory=list)  # (item code, amount)

    def to_dict(self) -> dict:
        return asdict(self)


def load_treasure_sets(fs: G3Fs, templates: dict[str, TemplateRec]) -> dict[str, TreasureSet]:
    from .world import stacks  # same stack reader as the world inventories

    out: dict[str, TreasureSet] = {}
    for t in {id(t): t for t in templates.values()}.values():
        props = t.entity.props
        if not t.path.startswith("Treasure/") or "gCTreasureSet_PS" not in props or "gCInventory_PS" not in props:
            continue
        data = fs.find(t.path)
        strings = parse_genomfle(data).strings
        items = []
        for st in stacks(props["gCInventory_PS"], data, strings):
            tmpl = templates.get(st.props["Template"].value) if "Template" in st.props else None
            if tmpl is not None and is_item_template(tmpl):
                items.append((tmpl.name, st.props["Amount"].value if "Amount" in st.props else 1))
        ts = props["gCTreasureSet_PS"].props
        out[t.name] = TreasureSet(
            code=t.name,
            kind=KIND_BY_FOLDER.get(t.path.split("/")[1], "other"),
            distribution=ts["TreasureDistribution"].value if "TreasureDistribution" in ts else 0,
            min_stacks=ts["MinTransferStacks"].value if "MinTransferStacks" in ts else 0,
            max_stacks=ts["MaxTransferStacks"].value if "MaxTransferStacks" in ts else 0,
            items=items,
        )
    return out
