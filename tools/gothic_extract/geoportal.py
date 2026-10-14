"""Build the geoportal v1 data package from a full extraction output.

v1 does one thing: search items and unique characters and show where they are.
Usage: python -m gothic_extract.geoportal --src output/g2nk/newworld --dst dist/g2nk/khorinis
"""
import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

SOURCE_KIND = {"zen": "ground", "script": "script"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _place(feature: dict, kind: str, label: str, **extra) -> dict:
    lon, lat, h = feature["geometry"]["coordinates"]
    return {"kind": kind, "lon": lon, "lat": lat, "h": h, "label": label, "ref": feature["properties"]["id"], **extra}


def _lock_label(p: dict) -> str:
    if not p.get("locked"):
        return "otwarta"
    parts = ["zamknięta"]
    if p.get("key"):
        parts.append(f"klucz: {p['key']}")
    if p.get("pick_string"):
        parts.append(f"zamek: {p['pick_string']}")
    return " · ".join(parts)


def unique_character_codes(npcs: list[dict]) -> set[str]:
    """Named, unique characters.

    - people: exactly one NPC instance in this world carries the name (the same person may have a second
      instance in another world, e.g. on the ship to Irdorath);
    - monsters: the name is unique in the whole game and the instance is inserted once here, so bosses like
      Inubis count but a species that happens to appear once (a single beetle) does not.
    """
    codes_by_name: dict[str, set[str]] = defaultdict(set)
    inserts = Counter(f["properties"]["code"] for f in npcs)
    for f in npcs:
        p = f["properties"]
        if not p["name"]:
            continue
        if p.get("is_human", True) or (p.get("name_unique_in_game", False) and inserts[p["code"]] == 1):
            codes_by_name[p["name"]].add(p["code"])
    return {next(iter(codes)) for codes in codes_by_name.values() if len(codes) == 1}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def summarize_times(times: list[str]) -> str:
    """'HH:MM–HH:MM' slots → short label: touching slots merged, many gaps collapsed to one span."""
    spans = sorted((t.split("–") for t in times), key=lambda se: _minutes(se[0]))
    merged: list[list[str]] = []
    for start, end in spans:
        if merged and merged[-1][1] == start:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    if len(merged) <= 3:
        return ", ".join(f"{s}–{e}" for s, e in merged)
    return f"{merged[0][0]}–{merged[-1][1]} (z przerwami)"


def _routine_groups(routine_feats: list[dict], codes: set[str]) -> list[dict]:
    """Merge routine points of one character at one waypoint (per routine) into a single place."""
    groups: dict[tuple, dict] = {}
    for f in routine_feats:
        p = f["properties"]
        if p["npc_code"] not in codes:
            continue
        key = (p["npc_code"], p["routine"], p["waypoint"])
        g = groups.setdefault(key, {"feature": f, "times": [], "actions": []})
        g["times"].append(f"{p['start']}–{p['end']}")
        if p["action"] not in g["actions"]:
            g["actions"].append(p["action"])
    return list(groups.values())


def build_geoportal(src: Path, dst: Path) -> dict:
    dst.mkdir(parents=True, exist_ok=True)
    catalog = _read(src / "catalog_items.json")
    items = _read(src / "items.geojson")["features"]
    containers = _read(src / "containers.geojson")["features"]
    npcs = _read(src / "npcs.geojson")["features"]
    routines = _read(src / "npc_routines.geojson")["features"]

    item_places: dict[str, list[dict]] = defaultdict(list)
    for f in items:
        p = f["properties"]
        item_places[p["code"]].append(_place(f, SOURCE_KIND[p["source"]], "na ziemi" if p["source"] == "zen"
                                             else f"wstawiany skryptem ({p['spot']})", amount=p["amount"]))
    for f in containers:
        p = f["properties"]
        for c in p["contents"]:
            item_places[c["code"]].append(_place(f, "container", f"w skrzyni ({_lock_label(p)})", amount=c["amount"]))
    for f in npcs:
        p = f["properties"]
        for i in p["inventory"]:
            certainty = "" if i["certainty"] == "always" else ", możliwe"
            item_places[i["code"]].append(_place(f, "npc", f"u NPC: {p['name']}{certainty}", amount=i["amount"]))

    entries = []
    for code, places in sorted(item_places.items()):
        d = catalog.get(code, {})
        entries.append({"id": f"item:{code}", "type": "item", "code": code, "name": d.get("name") or code,
                        "category": d.get("category"), "total": sum(pl.get("amount", 1) for pl in places),
                        "places": places})

    unique = unique_character_codes(npcs)
    groups = _routine_groups(routines, unique)
    groups_by_code: dict[str, list[dict]] = defaultdict(list)
    place_feats = []
    for g in groups:
        f, p = g["feature"], g["feature"]["properties"]
        groups_by_code[p["npc_code"]].append(g)
        place_feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            "id": f"{p['npc_code']}:{p['routine']}:{p['waypoint']}", "npc_code": p["npc_code"], "npc_name": p["npc_name"],
            "routine": p["routine"], "is_default": p["is_default"], "waypoint": p["waypoint"],
            "times": g["times"], "actions": g["actions"]}})

    char_feats, seen = [], set()
    for f in npcs:
        p = f["properties"]
        if p["code"] not in unique:
            continue
        spawn = _place(f, "spawn", f"pojawia się ({p['insert_waypoint']})", chapter=p["chapter"])
        if p["code"] in seen:  # inserted again (e.g. later chapter): another spawn place
            next(e for e in entries if e["id"] == f"character:{p['code']}")["places"].append(spawn)
            continue
        seen.add(p["code"])
        char_feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            k: p[k] for k in ("id", "code", "name", "guild_name", "level", "chapter", "inventory", "game_pos", "height_m")}})
        places = [spawn]
        for g in sorted(groups_by_code[p["code"]], key=lambda g: (not g["feature"]["properties"]["is_default"],
                                                                  g["feature"]["properties"]["routine"])):
            rp = g["feature"]["properties"]
            prefix = "" if rp["is_default"] else f"[{rp['routine']}] "
            places.append(_place(g["feature"], "routine", prefix + summarize_times(g["times"]), routine=rp["routine"],
                                 is_default=rp["is_default"], actions=g["actions"]))
        entries.append({"id": f"character:{p['code']}", "type": "character", "code": p["code"], "name": p["name"],
                        "category": p["guild_name"], "level": p["level"], "places": places})

    _write(dst / "search_index.json", {"version": 1, "entries": entries})
    _write(dst / "items.geojson", _fc([{"type": "Feature", "geometry": f["geometry"], "properties": {
        k: f["properties"][k] for k in ("id", "code", "name", "category", "amount", "source", "spot")}} for f in items]))
    _write(dst / "containers.geojson", _fc(containers))
    _write(dst / "characters.geojson", _fc(char_feats))
    _write(dst / "character_places.geojson", _fc(place_feats))

    copied = []
    if (src / "world.glb").exists():
        shutil.copy2(src / "world.glb", dst / "world.glb")
        copied.append("world.glb")
    if (src / "models").is_dir():
        shutil.rmtree(dst / "models", ignore_errors=True)
        shutil.copytree(src / "models", dst / "models")
        copied.append("models/")

    meta = _read(src / "metadata.json")
    meta.pop("mesh", None)
    meta["package"] = {
        "version": 1,
        "counts": {"search_items": sum(e["type"] == "item" for e in entries),
                   "search_characters": len(char_feats), "items": len(items), "containers": len(containers),
                   "character_places": len(place_feats)},
        "files": sorted(["search_index.json", "items.geojson", "containers.geojson", "characters.geojson",
                         "character_places.geojson", "metadata.json", "README.md"] + copied),
    }
    _write(dst / "metadata.json", meta)
    shutil.copy2(Path(__file__).with_name("geoportal_README.md"), dst / "README.md")
    return meta["package"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.geoportal", description="Build the geoportal v1 package")
    ap.add_argument("--src", required=True, type=Path, help="full extraction output, e.g. output/g2nk/newworld")
    ap.add_argument("--dst", required=True, type=Path, help="package folder, e.g. dist/g2nk/khorinis")
    args = ap.parse_args(argv)
    pkg = build_geoportal(args.src, args.dst)
    for k, v in pkg["counts"].items():
        print(f"  {k}: {v}")
    print(f"  files: {', '.join(pkg['files'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
