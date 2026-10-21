"""Add quests to a geoportal package (v4): quests.json, `type: "quest"` entries in search_index.json, metadata counts.

Run after gothic_extract.geoportal has built the package:
python -m gothic_extract.quests_package --game g2nk --pkg dist/g2nk/khorinis --out-root output/g2nk
A quest goes into the package of every world where the script proves it takes part (one of its NPCs is inserted
there, or its journal item lies there); its places are limited to that world. Quests that no world claims are
left out of every package and listed on stdout.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .config import load_game
from .quests import extract_quests
from .script_vm import make_vm

SECTION_LABEL = {"mission": "Misja", "note": "Notatka"}
PACKAGE_VERSION = 4
MAX_SPAWNS = 10  # spawn places listed for a non-unique character (guards, bandits...)
_TARGET_ROLES = {"insert", "routine"}


def _read(path: Path):
    return json.loads(path.read_text("utf-8"))


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def load_worlds(out_root: Path) -> dict[str, dict[str, set[str]]]:
    """world -> {"npcs": instance codes inserted there, "items": item codes lying/held/stored there}."""
    worlds = {}
    for meta in sorted(out_root.glob("*/metadata.json")):
        folder = meta.parent
        if not (folder / "npcs.geojson").exists():
            continue
        npcs = _read(folder / "npcs.geojson")["features"]
        items = {f["properties"]["code"] for f in _read(folder / "items.geojson")["features"]}
        for f in _read(folder / "containers.geojson")["features"]:
            items |= {c["code"] for c in f["properties"]["contents"]}
        for f in npcs:
            items |= {i["code"] for i in f["properties"]["inventory"]}
        worlds[_read(meta)["world"]] = {"npcs": {f["properties"]["code"] for f in npcs}, "items": items}
    return worlds


def quest_worlds(q: dict, worlds: dict[str, dict[str, set[str]]]) -> list[str]:
    npc_codes = {c["code"] for c in q["characters"]}
    item_codes = {s["id"].upper() for st in q["stages"] for s in st["sources"] if s["type"] == "item"}
    return sorted(w for w, d in worlds.items() if npc_codes & d["npcs"] or item_codes & d["items"])


class PackageIndex:
    """What the package already knows: unique characters, items, and every NPC insert."""

    def __init__(self, pkg: Path):
        index = _read(pkg / "search_index.json")
        self.entries = [e for e in index["entries"] if e["type"] != "quest"]
        self.version = index.get("version", 1)
        self.char_by_code = {c: e for e in self.entries if e["type"] == "character" for c in e["codes"]}
        self.item_codes = {e["code"] for e in self.entries if e["type"] == "item"}
        self.spawns = defaultdict(list)
        for f in _read(pkg / "npcs.geojson")["features"]:
            self.spawns[f["properties"]["code"]].append(f)


def _spawn_place(f: dict) -> dict:
    lon, lat, h = f["geometry"]["coordinates"]
    p = f["properties"]
    return {"kind": "spawn", "lon": lon, "lat": lat, "h": h, "label": f"pojawia się ({p['insert_waypoint']})",
            "ref": p["id"], "chapter": p["chapter"]}


def quest_places(q: dict, idx: PackageIndex) -> list[dict]:
    """Where the quest's giver, targets and (unique) stage characters are in this world."""
    places, seen = [], set()
    for c in q["characters"]:
        code, role = c["code"], c["role"]
        if role == "giver":
            mark, cert = "giver", "always"
        elif role == "giver_candidate":
            mark, cert = "giver", "possible"
        elif role in _TARGET_ROLES:
            mark, cert = "target", c["certainty"]
        else:
            mark, cert = "stage", "always"
        entry = idx.char_by_code.get(code)
        if entry is not None:
            src = [p for p in entry["places"] if p["kind"] == "spawn" or mark != "stage" or p.get("is_default")]
        elif mark != "stage":
            src = [_spawn_place(f) for f in idx.spawns.get(code, [])[:MAX_SPAWNS]]
            if len(idx.spawns.get(code, [])) > 1:
                cert = "possible"  # one of several instances of a generic NPC
        else:
            src = []
        for p in src:
            key = (code, p["kind"], p.get("ref"), mark)
            if key in seen:
                continue
            seen.add(key)
            places.append({**p, "role": mark, "npc_code": code, "certainty": cert})
    return places


def link_characters_items(q: dict, idx: PackageIndex) -> tuple[list[dict], list[dict]]:
    chars = []
    for c in q["characters"]:
        e = idx.char_by_code.get(c["code"])
        chars.append({**c, "in_index": e is not None, "id": e["id"] if e else None})
    items = [{**i, "in_index": i["code"] in idx.item_codes, "id": f"item:{i['code']}" if i["code"] in idx.item_codes else None}
             for i in q["items"]]
    return chars, items


def build_world_quests(quests: list[dict], world: str, worlds, idx: PackageIndex) -> list[dict]:
    out = []
    for q in quests:
        ws = quest_worlds(q, worlds)
        if world not in ws:
            continue
        chars, items = link_characters_items(q, idx)
        out.append({**q, "worlds": ws, "characters": chars, "items": items, "places": quest_places(q, idx)})
    return out


def search_entry(q: dict) -> dict:
    """Slim index entry: only the giver's and targets' spawn points (the full list is in quests.json), so the
    index stays small; a quest whose giver/targets have no spawn keeps its first place of any kind."""
    places = [p for p in q["places"] if p["kind"] == "spawn" and p["role"] in ("giver", "target")] or q["places"][:1]
    return {"id": q["id"], "type": "quest", "code": q["code"], "name": q["name"], "category": SECTION_LABEL[q["section"]],
            "giver": q["giver"]["name"] if q["giver"] else None, "chapter": q["chapter"], "places": places}


def summarize(world: str, qs: list[dict]) -> str:
    sure = sum(1 for q in qs if q["giver"])
    cand = sum(1 for q in qs if not q["giver"] and q["giver_candidates"])
    none = sum(1 for q in qs if not q["giver"] and not q["giver_candidates"])
    noplace = sum(1 for q in qs if not q["places"])
    return (f"  {world}: {len(qs)} questów; zleceniodawca pewny {sure}, kilku kandydatów {cand}, brak {none}; "
            f"bez miejsc na mapie {noplace}")


def build(game: str, pkg: Path, out_root: Path) -> dict:
    meta = _read(pkg / "metadata.json")
    world = meta["world"]
    worlds = load_worlds(out_root)
    quests = extract_quests(make_vm(load_game(game).script_dat))
    unassigned = [q for q in quests if not quest_worlds(q, worlds)]
    idx = PackageIndex(pkg)
    mine = build_world_quests(quests, world, worlds, idx)
    _write(pkg / "quests.json", {"version": 1, "game": game, "world": world, "quests": mine})
    _write(pkg / "search_index.json", {"version": idx.version, "entries": idx.entries + [search_entry(q) for q in mine]})
    package = meta["package"]
    package["version"] = PACKAGE_VERSION  # 4: quests (quests.json, type "quest" in the search index)
    package["counts"]["quests"] = len(mine)
    package["files"] = sorted(set(package["files"]) | {"quests.json"})
    _write(pkg / "metadata.json", meta)
    return {"world": world, "quests": mine, "unassigned": unassigned, "all": len(quests)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.quests_package", description="Add quests to a geoportal package")
    ap.add_argument("--game", required=True, help="key from games.toml, e.g. g2nk")
    ap.add_argument("--pkg", required=True, type=Path, help="package built by gothic_extract.geoportal, e.g. dist/g2nk/khorinis")
    ap.add_argument("--out-root", required=True, type=Path, help="folder with the full extractions of all worlds, e.g. output/g2nk")
    args = ap.parse_args(argv)
    r = build(args.game, args.pkg, args.out_root)
    print(summarize(r["world"], r["quests"]))
    if r["unassigned"]:
        print(f"  bez świata (pominięte w każdej paczce, {len(r['unassigned'])} z {r['all']}): "
              + "; ".join(f"{q['code']} ({q['name']})" for q in r["unassigned"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
