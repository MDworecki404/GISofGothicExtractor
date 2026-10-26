"""Codes for Gothic 3 NPC properties.

G3 has no guilds; the closest is the political alignment (gEPoliticalAlignment) in gCNPC_PS, which the
game's reputation screen names with HUD_<code> strings. The value order was checked against the data
(2026-10-26): 1 orcs (Agenak, Arokkh), 2 Nordmar (Bogir, Grauhaar), 3 rebels (Anog, Abe), 4 rangers (Arakos,
Bozep, Ranger_01), 5 assassins (Abbas, Achmed), 6 nomads (Cronos, Kayor), 7 outlaws/novices (Ardea_OutNovice_*),
8 slaves (Ass_Babe_Dance_*). 0 = none (animals, monsters, most extras).
"""

ALIGNMENT_CODES: dict[int, str] = {
    0: "NONE",
    1: "ORC",
    2: "NRD",
    3: "REB",
    4: "MID",
    5: "ASS",
    6: "NOM",
    7: "OUT",
    8: "SLAVE",
}

# gESpecies value of people (orcs are species 5 and count as monsters, like in G1/G2).
HUMAN_SPECIES = {0}

_HUD_KEYS = {"ORC": "HUD_Orc", "NRD": "HUD_Nrd", "REB": "HUD_Reb", "MID": "HUD_Mid", "ASS": "HUD_Ass", "NOM": "HUD_Nom"}


def alignment_code(value: int) -> str:
    return ALIGNMENT_CODES.get(value, f"ALIGN_{value}")


def alignment_names_pl(strings: dict[str, str]) -> dict[str, str | None]:
    """Alignment code -> Polish name from the game (HUD_* strings); None where the game has no text."""
    return {code: (strings.get(_HUD_KEYS[code]) or None) if code in _HUD_KEYS else None
            for code in ALIGNMENT_CODES.values()}
