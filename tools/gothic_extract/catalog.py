from dataclasses import asdict, dataclass

import zenkit

from .text import game_text

# ITEM_KAT_* constant name → Polish category label. Values are read from the script.
_KAT_LABELS = {
    "ITEM_KAT_NONE": "Różne",
    "ITEM_KAT_NF": "Broń biała",
    "ITEM_KAT_FF": "Broń dystansowa",
    "ITEM_KAT_MUN": "Amunicja",
    "ITEM_KAT_ARMOR": "Pancerze",
    "ITEM_KAT_FOOD": "Jedzenie",
    "ITEM_KAT_DOCS": "Dokumenty",
    "ITEM_KAT_POTIONS": "Mikstury",
    "ITEM_KAT_LIGHT": "Światło",
    "ITEM_KAT_RUNE": "Runy i zwoje",
    "ITEM_KAT_MAGIC": "Magia",
}
PLANT_LABEL = "Rośliny"


@dataclass
class ItemDef:
    code: str
    name: str
    category: str
    main_flag: int
    flags: int
    value: int
    visual: str
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


def category_by_mainflag(script: zenkit.DaedalusScript) -> dict[int, str]:
    out: dict[int, str] = {}
    for const, label in _KAT_LABELS.items():
        sym = script.get_symbol_by_name(const)
        if sym is not None:
            out.setdefault(sym.get_int(), label)
    return out


def _class_of(script: zenkit.DaedalusScript, sym: zenkit.DaedalusSymbol) -> str | None:
    seen = 0
    while sym is not None and sym.type != zenkit.DaedalusDataType.CLASS and seen < 8:
        if sym.parent < 0:
            return None
        sym = script.get_symbol_by_index(sym.parent)
        seen += 1
    return sym.name if sym is not None and sym.type == zenkit.DaedalusDataType.CLASS else None


def instances_of(script: zenkit.DaedalusScript, class_name: str) -> list[zenkit.DaedalusSymbol]:
    return [
        s for s in script.symbols
        if s.type == zenkit.DaedalusDataType.INSTANCE and s.address > 0 and _class_of(script, s) == class_name
    ]


def build_item_catalog(vm: zenkit.DaedalusVm) -> dict[str, ItemDef]:
    cats = category_by_mainflag(vm)
    catalog: dict[str, ItemDef] = {}
    for sym in instances_of(vm, "C_ITEM"):
        it = vm.init_instance(sym, zenkit.DaedalusInstanceType.ITEM)
        code = sym.name.upper()
        category = PLANT_LABEL if code.startswith("ITPL_") else cats.get(it.main_flag, "Różne")
        catalog[code] = ItemDef(
            code=code,
            name=game_text(it.name),
            category=category,
            main_flag=it.main_flag,
            flags=it.flags,
            value=it.value,
            visual=it.visual,
            description=game_text(it.description),
        )
    return catalog
