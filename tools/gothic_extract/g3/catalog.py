"""Item catalog of Gothic 3 built from templates with gCItem_PS, with Polish names from stringtable.ini."""
from ..catalog import ItemDef
from .templates import TemplateRec

# gEItemCategory value -> label (values seen in the game's templates, 2026-10-26):
# 0 none (armour sets, helmets, props), 1 weapons and ammunition, 2 amulets/rings/shields/helmets,
# 3 scrolls/teleport and druid stones, 4 food/potions/plants, 6 misc (keys, gold, trophies),
# 7 documents (recipes, maps, letters), 9 spells, 10 perks (skills).
ITEM_CATEGORY_PL: dict[int, str] = {
    0: "Różne",
    1: "Broń biała",
    2: "Biżuteria",
    3: "Runy i zwoje",
    4: "Jedzenie",
    5: "Różne",
    6: "Różne",
    7: "Dokumenty",
    8: "Różne",
    9: "Magia",
    10: "Umiejętności",
}
PLANT_LABEL = "Rośliny"
# Code prefix -> label; refines the game category (same labels as G1/G2 where they exist).
_PREFIX_LABELS = [
    ("It_Plant", PLANT_LABEL),
    ("It_Potion", "Mikstury"),
    ("It_Armor", "Pancerze"),
    ("It_Helmet", "Pancerze"),
    ("It_Shield", "Pancerze"),
    ("It_Bow", "Broń dystansowa"),
    ("It_Crossbow", "Broń dystansowa"),
]
_AMMO = ("Arrow", "Bolt")


def category_label(code: str, category: int) -> str:
    for prefix, label in _PREFIX_LABELS:
        if code.startswith(prefix):
            return label
    if category == 1 and code.endswith(_AMMO):
        return "Amunicja"
    return ITEM_CATEGORY_PL.get(category, "Różne")


def is_item_template(t: TemplateRec) -> bool:
    """Real items: not deleted templates, not body parts of characters, not the bare fists."""
    return ("gCItem_PS" in t.entity.props and not t.path.startswith("_deleted/") and "BodyParts" not in t.path
            and t.name not in ("Fist", "TrollFist"))


def build_g3_catalog(templates: dict[str, TemplateRec], strings: dict[str, str]) -> dict[str, ItemDef]:
    from .models import visual_path  # static item mesh, or the animated actor of bows (models imports this module)

    catalog: dict[str, ItemDef] = {}
    for t in sorted(templates.values(), key=lambda t: t.path):
        if not is_item_template(t):
            continue
        item = t.entity.props["gCItem_PS"].props
        category = item["Category"].value if "Category" in item else 0
        catalog[t.name] = ItemDef(
            code=t.name,
            name=strings.get("FO_" + t.name),
            category=category_label(t.name, category),
            main_flag=category,
            flags=0,
            value=item["GoldValue"].value if "GoldValue" in item else 0,
            visual=visual_path(t.entity) or "",
            description=strings.get("ITEMDESC_" + t.name, ""),
        )
    return catalog
