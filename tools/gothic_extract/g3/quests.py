"""Gothic 3 quests (.quest) and the dialogs that drive them (.info), as quest dicts of the package contract.

A .quest file gives the journal title (LogTopic -> stringtable), the quest type, its targets (DeliveryEntities:
items, characters or enclaves, with DeliveryAmounts), DestinationEntity and the XP reward. Dialogs (.info) name
their quest in `Quest`; the owner of a dialog with ConditionType 6 (the offer that starts the quest) is the giver.
Every dialog of a quest is a stage (its first spoken line). Give commands hand items between the player and the
NPC: to the player = reward, from the player = handover. Order of stages: the dialogs' SortID ("order": "script").
"""
from collections import defaultdict

from ..catalog import ItemDef
from .archive import G3Fs

START_CONDITION = "6"  # gEInfoCondType of the dialog that offers/starts a quest (checked on Abe, Arakos…)
ENCLAVE_TYPE = "10"  # quest type whose targets are enclaves (towns to free), not characters
_PLAYER = "player"


def _ini(data: bytes) -> dict[str, str]:
    text = data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("cp1252")
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _split(value: str) -> list[str]:
    return value.split(";") if value else []


def _int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_g3_quests(fs: G3Fs, strings: dict[str, str], catalog: dict[str, ItemDef],
                      npc_codes: set[str] | None = None) -> list[dict]:
    """npc_codes: characters that exist in the world; other DeliveryEntities/DestinationEntity names (zones,
    chests, enclaves) are then not listed as characters."""
    infos: dict[str, list[dict]] = defaultdict(list)
    for path in fs.list(suffix=".info"):
        info = _ini(fs.find(path))
        if info.get("Quest"):
            infos[info["Quest"]].append(info)

    def npc(code: str) -> dict:
        return {"code": code, "name": strings.get("FO_" + code) or code}

    def is_npc(code: str) -> bool:
        return code not in catalog and code != _PLAYER and (npc_codes is None or code in npc_codes)

    quests = []
    for path in fs.list(suffix=".quest"):
        q = _ini(fs.find(path))
        code = q.get("Name") or path.split("/")[-1].split("_quest_")[0]
        dialogs = sorted(infos.get(code, []), key=lambda i: (_int(i.get("SortID")), i.get("Name", "")))
        owners = [i["Owner"] for i in dialogs if i.get("Owner")]
        starters = sorted({i["Owner"] for i in dialogs if i.get("ConditionType") == START_CONDITION and i.get("Owner")})
        givers = starters or sorted(set(owners))
        giver = givers[0] if len(givers) == 1 else None

        chars: dict[tuple[str, str], dict] = {}
        for g in givers:
            role = "giver" if giver else "giver_candidate"
            chars[(g, role)] = {**npc(g), "role": role, "certainty": "always" if giver else "possible"}
        items: dict[tuple[str, str], dict] = {}

        targets = _split(q.get("DeliveryEntities", ""))
        amounts = _split(q.get("DeliveryAmounts", ""))
        for k, t in enumerate(targets):
            n = _int(amounts[k] if k < len(amounts) else "1", 1)
            if t in catalog:
                items[(t, "handover")] = {"code": t, "name": catalog[t].name, "role": "handover", "amount": n,
                                          "certainty": "always"}
            elif q.get("Type") != ENCLAVE_TYPE and is_npc(t.lstrip("_")):
                t = t.lstrip("_")  # "_Diego": the player's friend
                chars.setdefault((t, "target"), {**npc(t), "role": "target", "certainty": "always"})
        dest = q.get("DestinationEntity", "")
        if dest and is_npc(dest):
            chars.setdefault((dest, "target"), {**npc(dest), "role": "target", "certainty": "always"})

        stages = []
        for info in dialogs:
            owner = info.get("Owner", "")
            if owner and (owner, "giver") not in chars and (owner, "giver_candidate") not in chars:
                chars.setdefault((owner, "stage"), {**npc(owner), "role": "stage", "certainty": "always"})
            texts = [strings.get(t, "") for t in _split(info.get("InfoScript_Texts", "")) if t]
            source = {"type": "dialog", "id": info.get("Name", ""), "function": info.get("Name", "")}
            if owner:
                source.update(npc=owner, npc_name=npc(owner)["name"])
            stages.append({"seq": len(stages) + 1, "kind": "entry", "chapter": None, "chapter_source": None,
                           "conditional": info.get("ConditionType") != START_CONDITION,
                           "function": info.get("Name", ""), "sources": [source],
                           "text": next((t for t in texts if t), None)})
            cmds = _split(info.get("InfoScript_Commands", ""))
            ent1, ent2 = _split(info.get("InfoScript_Entities1", "")), _split(info.get("InfoScript_Entities2", ""))
            ids1, ids2 = _split(info.get("InfoScript_IDs1", "")), _split(info.get("InfoScript_IDs2", ""))
            for k, cmd in enumerate(cmds):
                if cmd.lower() != "give" or k >= len(ids1) or ids1[k] not in catalog:
                    continue
                item, n = ids1[k], _int(ids2[k] if k < len(ids2) else "1", 1)
                frm, to = (ent1[k] if k < len(ent1) else ""), (ent2[k] if k < len(ent2) else "")
                role = "reward" if to == _PLAYER else "handover" if frm == _PLAYER else None
                if role and (item, role) not in items:
                    items[(item, role)] = {"code": item, "name": catalog[item].name, "role": role, "amount": n,
                                           "certainty": "always"}
        if not stages:  # no dialog: the journal title is the only stage
            stages.append({"seq": 1, "kind": "create", "chapter": None, "chapter_source": None,
                           "conditional": False, "function": code, "sources": [], "text": None})

        xp = _int(q.get("ExperiencePoints", "0"))
        quests.append({
            "id": f"quest:{code}", "code": code, "aliases": [], "name": strings.get(q.get("LogTopic", "")) or code,
            "section": "mission", "mission_var": None, "chapter": None, "chapter_source": None,
            "giver": npc(giver) if giver else None,
            "giver_certainty": "always" if giver else ("possible" if givers else None),
            "giver_candidates": [] if giver else [npc(g) for g in givers],
            "order": "script", "stages": stages, "characters": list(chars.values()), "items": list(items.values()),
            "rewards": {"xp": xp or None, "xp_certainty": "always" if xp else None},
        })
    return quests
