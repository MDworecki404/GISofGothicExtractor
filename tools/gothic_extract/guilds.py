import zenkit

from .npcs import _guild_names
from .text import game_text


def guild_names_pl(vm: zenkit.DaedalusVm) -> dict[str, str | None]:
    """Guild code (as in NPC `guild_name`, e.g. GRD) -> Polish name from the game's TXT_GUILDS table.

    TXT_GUILDS is indexed by the GIL_* value. None where the game has no text (empty entry, or past the table's end).
    """
    table = vm.get_symbol_by_name("TXT_GUILDS")
    texts = [game_text(table.get_string(i)) for i in range(table.size)] if table is not None else []
    return {code: (texts[value] if value < len(texts) and texts[value] else None)
            for value, code in _guild_names(vm).items()}
