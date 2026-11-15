"""Add quests to a geoportal package (v6): quests.json, `type: "quest"` entries in search_index.json, metadata counts.

Run after gothic_extract.geoportal has built the package:
python -m gothic_extract.quests_package --game g2nk --pkg dist/g2nk/khorinis --out-root output/g2nk
A quest goes into the package of every world where the script proves it takes part (one of its NPCs is inserted
there, or its journal item lies there); its places are limited to that world. Quests that no world claims are
left out of every package and listed on stdout.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .config import load_game
from .quests import extract_quests
from .script_vm import make_vm

SECTION_LABEL = {"mission": "Misja", "note": "Notatka"}
PACKAGE_VERSION = 6  # 6: stage order and places (quests.json version 2); 4 introduced quests
QUESTS_VERSION = 2
MAX_SPAWNS = 10  # spawn places listed for a non-unique character (guards, bandits...)
_TARGET_ROLES = {"insert", "routine", "target"}  # target: G3 quest targets (.quest DeliveryEntities)


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


_WINDOW = re.compile(r"(\d{2}):(\d{2})\u2013(\d{2}):(\d{2})")


def _minutes(h: str, m: str) -> int:
    return int(h) * 60 + int(m)


def _windows(label: str) -> list[tuple[int, int]] | None:
    """Time windows of a routine place label ("07:20\u201301:20", "[HOME] 08:00\u201309:00, 10:00\u201322:10"); None = all day."""
    found = [(_minutes(a, b), _minutes(c, d)) for a, b, c, d in _WINDOW.findall(label)]
    return found or None


def _covers(windows: list[tuple[int, int]] | None, t: int) -> bool:
    if windows is None:
        return True
    return any(a <= t < b if a <= b else t >= a or t < b for a, b in windows)


def _overlaps(windows: list[tuple[int, int]] | None, want: list[tuple[int, int]]) -> bool:
    """Does the place's schedule share a minute with any wanted window (checked on a 10-minute grid)?"""
    return any(_covers(windows, t % 1440) for a, b in want for t in range(a, b if a <= b else b + 1440, 10))


def _waypoint(p: dict) -> str | None:
    if p["kind"] == "routine":
        return p["ref"].split(":", 2)[-1]
    m = re.search(r"\(([^()]+)\)\s*$", p.get("label", ""))
    return m.group(1) if m else None


def stage_place(st: dict, idx: "PackageIndex") -> dict | None:
    """Where the player has to be for the stage to happen: for a dialog, the dialog NPC's place in this world.
    A unique character has routine places: the default routines (not sleeping) that fit the dialog's hours
    (`Wld_IsTime` in its condition), else the one that covers midday. A character without routines has spawn
    places; with exactly one it is the place. Other NPCs, item use and script triggers have no place."""
    npcs = sorted({src["npc"] for src in st["sources"] if src["type"] == "dialog" and src.get("npc")
                   and src["npc"] not in ("PC_HERO", "HERO")})
    if len(npcs) != 1:
        return None
    code = npcs[0]
    entry = idx.char_by_code.get(code)
    places = entry["places"] if entry else [_spawn_place(f) for f in idx.spawns.get(code, [])]
    routines = [p for p in places if p["kind"] == "routine" and p.get("is_default")]
    awake = [p for p in routines if "TA_SLEEP" not in p.get("actions", [])] or routines
    name = next((src.get("npc_name") for src in st["sources"] if src.get("npc") == code), None) or code
    if awake:
        want = [(_minutes(*a.split(":")), _minutes(*b.split(":"))) for a, b in st.get("hours", [])]
        fits = [p for p in awake if want and _overlaps(_windows(p["label"]), want)]
        noon = [p for p in awake if _covers(_windows(p["label"]), 12 * 60)]
        pick = (fits or noon or awake)[0]
        candidates = len(fits or noon or awake)
        source = "routine"
    elif len(places) == 1:
        pick, candidates, source = places[0], 1, "spawn"
    else:
        return None
    return {"lon": pick["lon"], "lat": pick["lat"], "h": pick["h"], "label": f"{name}: {pick['label']}",
            "npc_code": code, "waypoint": _waypoint(pick), "source": source,
            "certainty": "only" if candidates == 1 else "default"}


def add_stage_places(q: dict, idx: "PackageIndex") -> int:
    """`place` on every stage (None when unknown) and `stages_with_place` on the quest; returns the count."""
    n = 0
    for st in q["stages"]:
        st["place"] = stage_place(st, idx)
        n += st["place"] is not None
    q["stages_with_place"] = n
    return n


def link_characters_items(q: dict, idx: PackageIndex) -> tuple[list[dict], list[dict]]:
    chars = []
    for c in q["characters"]:
        e = idx.char_by_code.get(c["code"])
        chars.append({**c, "in_index": e is not None, "id": e["id"] if e else None})
    items = [{**i, "in_index": i["code"] in idx.item_codes, "id": f"item:{i['code']}" if i["code"] in idx.item_codes else None}
             for i in q["items"]]
    return chars, items


def build_world_quests(quests: list[dict], world: str, worlds, idx: PackageIndex,
                       single_world: bool = False) -> list[dict]:
    """single_world: the game has one world (G3), so every quest belongs to it."""
    out = []
    for q in quests:
        ws = [world] if single_world else quest_worlds(q, worlds)
        if world not in ws:
            continue
        chars, items = link_characters_items(q, idx)
        built = {**q, "worlds": ws, "characters": chars, "items": items, "places": quest_places(q, idx),
                 "stages": [dict(st) for st in q["stages"]]}
        add_stage_places(built, idx)
        out.append(built)
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


def build(game: str, pkg: Path, out_root: Path, quests: list[dict] | None = None,
          worlds: dict[str, dict[str, set[str]]] | None = None, single_world: bool = False) -> dict:
    """quests / worlds: already extracted quests and load_worlds(out_root), to share them between packages."""
    meta = _read(pkg / "metadata.json")
    world = meta["world"]
    worlds = worlds if worlds is not None else load_worlds(out_root)
    quests = quests if quests is not None else extract_quests(make_vm(load_game(game).script_dat))
    unassigned = [] if single_world else [q for q in quests if not quest_worlds(q, worlds)]
    idx = PackageIndex(pkg)
    mine = build_world_quests(quests, world, worlds, idx, single_world)
    _write(pkg / "quests.json", {"version": QUESTS_VERSION, "game": game, "world": world, "quests": mine})
    _write(pkg / "search_index.json", {"version": idx.version, "entries": idx.entries + [search_entry(q) for q in mine]})
    package = meta["package"]
    package["version"] = max(package.get("version", 0), PACKAGE_VERSION)  # 6: stage order and places in quests.json (4: quests)
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
