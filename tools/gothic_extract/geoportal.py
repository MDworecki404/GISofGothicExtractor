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
DASH = "–"


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


# The same person with two instance codes in one world (e.g. before/after joining the dragon hunters).
# Counting rules cannot tell these from generic two-instance names, so they are listed by name.
SAME_PERSON = {"Gorn", "Myxir"}


def unique_characters(npcs: list[dict]) -> dict[str, list[str]]:
    """Named, unique characters -> their instance codes in this world.

    - people (guild below GIL_SEPERATOR_HUM, incl. NONE): exactly one NPC instance in this world carries the
      name (the same person may have another instance in a different world, e.g. on the ship to Irdorath);
    - monsters: the name is unique in the whole game and the instance is inserted once in the whole game,
      so bosses like Inubis count but a species that happens to appear once here does not.
    """
    codes_by_name: dict[str, list[str]] = defaultdict(list)
    for f in npcs:
        p = f["properties"]
        if not p["name"]:
            continue
        if p["is_human"] or (p["name_unique_in_game"] and p["inserts_in_game"] == 1):
            if p["code"] not in codes_by_name[p["name"]]:
                codes_by_name[p["name"]].append(p["code"])
    return {name: codes for name, codes in codes_by_name.items() if len(codes) == 1 or name in SAME_PERSON}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return (int(h) * 60 + int(m)) % 1440


def _hhmm(m: int) -> str:
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def summarize_times(times: list[str]) -> str:
    """'HH:MM–HH:MM' slots on a 24 h circle -> short label.

    Touching slots merge (also across midnight); a full circle is "cały dzień"; with more than three
    separate spans the label collapses to "first start–last end (z przerwami)", read from the end of
    the longest gap.
    """
    covered = [False] * 1440
    for t in times:
        s, e = (_minutes(x) for x in t.split(DASH))
        m = s
        while True:
            covered[m] = True
            m = (m + 1) % 1440
            if m == e:
                break
    if all(covered):
        return "cały dzień"
    starts = [m for m in range(1440) if covered[m] and not covered[m - 1]]
    runs = []
    for s in starts:
        e = s
        while covered[e % 1440]:
            e += 1
        runs.append((s, e))
    # begin with the run that follows the longest gap
    gaps = [((runs[(i + 1) % len(runs)][0] - runs[i][1]) % 1440, (i + 1) % len(runs)) for i in range(len(runs))]
    first = max(gaps)[1]
    runs = runs[first:] + runs[:first]
    if len(runs) <= 3:
        return ", ".join(f"{_hhmm(s)}{DASH}{_hhmm(e)}" for s, e in runs)
    return f"{_hhmm(runs[0][0])}{DASH}{_hhmm(runs[-1][1])} (z przerwami)"


def _routine_groups(routine_feats: list[dict], codes: set[str]) -> list[dict]:
    """Merge routine points of one character at one waypoint (per routine) into a single place.

    The pseudo-routine TOT (dead/removed NPCs parked at a hidden waypoint) is skipped.
    """
    groups: dict[tuple, dict] = {}
    for f in routine_feats:
        p = f["properties"]
        if p["npc_code"] not in codes or p["routine"] == "TOT" or p["waypoint"] == "TOT":
            continue
        key = (p["npc_code"], p["routine"], p["waypoint"])
        g = groups.setdefault(key, {"feature": f, "times": [], "actions": [],
                                    "id": f"{p['npc_code']}:{p['routine']}:{p['waypoint']}"})
        g["times"].append(f"{p['start']}{DASH}{p['end']}")
        if p["action"] not in g["actions"]:
            g["actions"].append(p["action"])
    return list(groups.values())


PREVIEWS_DIR = "previews"
STATIC_MESHES = (".3DS", ".XCMSH", ".XLMSH")  # G1/G2 .3DS, G3 compiled meshes


def load_preview_index(index: dict) -> dict[str, str]:
    """models/previews/index.json -> {visual (upper-case) -> model path relative to models/}."""
    return {e["visual"].upper(): f"{PREVIEWS_DIR}/{e['file']}" for e in index.get("previews", [])}


def resolve_model(code: str, catalog: dict, previews: dict[str, str]) -> tuple[str | None, str | None]:
    """Item code -> (preview path relative to models/, e.g. "previews/itfo_apple.glb", None) or (None, reason).

    Path: code -> catalog visual -> models/previews/index.json entry with that visual (case-insensitive).
    Reasons: "no_visual" (no visual in the catalog), "unsupported_visual" (not a static mesh, e.g. .MMS
    bows), "no_preview" (static mesh, but no preview file was exported for it).
    """
    visual = (catalog.get(code, {}).get("visual") or "").upper()
    if not visual:
        return None, "no_visual"
    if not visual.endswith(STATIC_MESHES):
        return None, "unsupported_visual"
    if visual not in previews:
        return None, "no_preview"
    return previews[visual], None


def build_geoportal(src: Path, dst: Path, guild_names: dict[str, str | None] | None = None) -> dict:
    """guild_names: guild code -> Polish name (see guilds.guild_names_pl); the world's metadata gets the codes in use."""
    dst.mkdir(parents=True, exist_ok=True)
    catalog = _read(src / "catalog_items.json")
    items = _read(src / "items.geojson")["features"]
    containers = _read(src / "containers.geojson")["features"]
    npcs = _read(src / "npcs.geojson")["features"]
    routines = _read(src / "npc_routines.geojson")["features"]
    previews_index_path = src / "models" / PREVIEWS_DIR / "index.json"
    models = load_preview_index(_read(previews_index_path)) if previews_index_path.exists() else {}

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
            item_places[i["code"]].append(_place(f, "npc", f"u NPC: {p['name']}{certainty}", amount=i["amount"],
                                                 certainty=i["certainty"]))

    entries = []
    for code, places in sorted(item_places.items()):
        d = catalog.get(code, {})
        entries.append({"id": f"item:{code}", "type": "item", "code": code, "name": d.get("name") or code,
                        "category": d.get("category"), "model": resolve_model(code, catalog, models)[0], "total": sum(pl.get("amount", 1) for pl in places if pl.get("certainty", "always") == "always"),
                        "places": places})

    characters = unique_characters(npcs)
    char_codes = {c for codes in characters.values() for c in codes}
    groups = _routine_groups(routines, char_codes)
    groups_by_code: dict[str, list[dict]] = defaultdict(list)
    place_feats = []
    for g in groups:
        f, p = g["feature"], g["feature"]["properties"]
        groups_by_code[p["npc_code"]].append(g)
        place_feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            "id": g["id"], "npc_code": p["npc_code"], "npc_name": p["npc_name"], "routine": p["routine"],
            "is_default": p["is_default"], "waypoint": p["waypoint"], "times": g["times"], "actions": g["actions"]}})

    inserts_by_code: dict[str, list[dict]] = defaultdict(list)
    for f in npcs:
        inserts_by_code[f["properties"]["code"]].append(f)
    char_feats = []
    for name, codes in sorted(characters.items()):
        first = inserts_by_code[codes[0]][0]
        fp = first["properties"]
        char_feats.append({"type": "Feature", "geometry": first["geometry"], "properties": {
            **{k: fp[k] for k in ("id", "code", "name", "guild_name", "level", "chapter", "inventory", "game_pos",
                                  "height_m")}, "codes": codes}})
        places = [_place(f, "spawn", f"pojawia się ({f['properties']['insert_waypoint']})",
                         chapter=f["properties"]["chapter"]) for c in codes for f in inserts_by_code[c]]
        for g in sorted((g for c in codes for g in groups_by_code[c]),
                        key=lambda g: (not g["feature"]["properties"]["is_default"], g["feature"]["properties"]["routine"])):
            rp = g["feature"]["properties"]
            prefix = "" if rp["is_default"] else f"[{rp['routine']}] "
            pl = _place(g["feature"], "routine", prefix + summarize_times(g["times"]), routine=rp["routine"],
                        is_default=rp["is_default"], actions=g["actions"])
            pl["ref"] = g["id"]
            places.append(pl)
        entries.append({"id": f"character:{codes[0]}", "type": "character", "code": codes[0], "codes": codes,
                        "name": name, "category": fp["guild_name"], "level": fp["level"], "places": places})

    npc_layer = [{"type": "Feature", "geometry": f["geometry"], "properties": {
        k: f["properties"][k] for k in ("id", "code", "name", "guild_name", "level", "chapter", "insert_waypoint")}}
        for f in npcs]

    _write(dst / "search_index.json", {"version": 1, "entries": entries})
    # preview of a chest's own visual, if one exists (chests are .MDS, not exported yet, so null today)
    for f in containers:
        f["properties"]["model"] = models.get((f["properties"].get("visual") or "").upper())
    _write(dst / "items.geojson", _fc([{"type": "Feature", "geometry": f["geometry"], "properties": {
        **{k: f["properties"][k] for k in ("id", "code", "name", "category", "amount", "source", "spot")},
        "model": resolve_model(f["properties"]["code"], catalog, models)[0]}} for f in items]))
    _write(dst / "containers.geojson", _fc(containers))
    _write(dst / "characters.geojson", _fc(char_feats))
    _write(dst / "npcs.geojson", _fc(npc_layer))
    _write(dst / "character_places.geojson", _fc(place_feats))

    copied = []
    if (src / "world.glb").exists():
        shutil.copy2(src / "world.glb", dst / "world.glb")
        copied.append("world.glb")
    if (src / "vobs.glb").exists():
        shutil.copy2(src / "vobs.glb", dst / "vobs.glb")
        copied.append("vobs.glb")
    if (src / "models").is_dir():
        shutil.rmtree(dst / "models", ignore_errors=True)
        shutil.copytree(src / "models", dst / "models")
        copied.append("models/")

    meta = _read(src / "metadata.json")
    meta.pop("mesh", None)
    if guild_names is not None:
        used = sorted({f["properties"]["guild_name"] for f in npcs})
        meta["guild_names"] = {code: guild_names.get(code) for code in used}
    meta["package"] = {
        "version": 3,  # 2: `model` on items and containers; 3: `model` points to models/previews/
        "counts": {"search_items": sum(e["type"] == "item" for e in entries),
                   "search_items_with_model": sum(e["type"] == "item" and e["model"] is not None for e in entries),
                   "search_characters": len(char_feats), "items": len(items), "containers": len(containers),
                   "npcs": len(npc_layer), "character_places": len(place_feats)},
        "files": sorted(["search_index.json", "items.geojson", "containers.geojson", "characters.geojson",
                         "npcs.geojson", "character_places.geojson", "metadata.json", "README.md"] + copied),
    }
    _write(dst / "metadata.json", meta)
    shutil.copy2(Path(__file__).with_name("geoportal_README.md"), dst / "README.md")
    return meta["package"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.geoportal", description="Build the geoportal v1 package")
    ap.add_argument("--src", required=True, type=Path, help="full extraction output, e.g. output/g2nk/newworld")
    ap.add_argument("--dst", required=True, type=Path, help="package folder, e.g. dist/g2nk/khorinis")
    ap.add_argument("--game", help="key from games.toml; adds guild_names (Polish names from the game's scripts)")
    args = ap.parse_args(argv)
    guild_names = None
    if args.game:
        from .config import load_game
        from .guilds import guild_names_pl
        from .script_vm import make_vm

        guild_names = guild_names_pl(make_vm(load_game(args.game).script_dat))
    pkg = build_geoportal(args.src, args.dst, guild_names)
    for k, v in pkg["counts"].items():
        print(f"  {k}: {v}")
    print(f"  files: {', '.join(pkg['files'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
