"""Random loot (treasure sets) of Gothic 3 in the geoportal package.

Runs after build_geoportal: copies treasure_sets.json, puts `treasure_sets` on the NPC layer and the character
cards (containers already carry it), and adds to the search index, per item:
- `loot`: every set the item can drop from, with its kind and number of holders (containers / NPCs using it);
- `places` with `certainty: "possible"` for sets used by at most MAX_HOLDERS holders (unique chests, traders,
  rare monsters). Widespread sets (gold in hundreds of chests) stay in `loot` only, so they do not flood the map.
"""
import json
import shutil
from collections import defaultdict
from pathlib import Path

MAX_HOLDERS = 50
KIND_LABEL = {"chest": "w skrzyni, losowo", "npc": "u postaci, losowo", "monster": "u potwora, losowo",
              "trader": "u handlarza", "mining": "do wydobycia"}


def _read(path: Path):
    return json.loads(path.read_text("utf-8"))


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _holders(src: Path) -> list[tuple[str, dict]]:
    """(layer kind of place, feature) for every container and NPC that names treasure sets."""
    out = [("container", f) for f in _read(src / "containers.geojson")["features"]]
    out += [("npc", f) for f in _read(src / "npcs.geojson")["features"]]
    return [(k, f) for k, f in out if f["properties"].get("treasure_sets")]


def add_loot(src: Path, pkg: Path, max_holders: int = MAX_HOLDERS) -> dict:
    sets = _read(src / "treasure_sets.json")["sets"]
    shutil.copy2(src / "treasure_sets.json", pkg / "treasure_sets.json")
    holders = _holders(src)

    sets_by_npc = {f["properties"]["id"]: f["properties"]["treasure_sets"] for k, f in holders if k == "npc"}
    for layer in ("npcs", "characters"):
        fc = _read(pkg / f"{layer}.geojson")
        for f in fc["features"]:
            if f["properties"]["id"] in sets_by_npc:
                f["properties"]["treasure_sets"] = sets_by_npc[f["properties"]["id"]]
        _write(pkg / f"{layer}.geojson", fc)

    holders_by_set: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for kind, f in holders:
        for code in f["properties"]["treasure_sets"]:
            holders_by_set[code].append((kind, f))

    index = _read(pkg / "search_index.json")
    entries = {e["id"]: e for e in index["entries"]}
    added_places = 0
    for code, s in sorted(sets.items()):
        for it in s["items"]:
            entry = entries.get(f"item:{it['code']}")
            if entry is None:
                entry = {"id": f"item:{it['code']}", "type": "item", "code": it["code"],
                         "name": it["name"] or it["code"], "category": it["category"], "model": None, "total": 0,
                         "places": []}
                entries[entry["id"]] = entry
                index["entries"].append(entry)
            loot = entry.setdefault("loot", [])
            if not any(l["set"] == code for l in loot):
                loot.append({"set": code, "kind": s["kind"], "holders": s["holders"]})
            if s["holders"] > max_holders:
                continue
            for kind, f in holders_by_set[code]:
                lon, lat, h = f["geometry"]["coordinates"]
                p = f["properties"]
                who = p["name"] if kind == "npc" else None
                label = KIND_LABEL.get(s["kind"], "losowo") + (f": {who}" if who else "")
                entry["places"].append({"kind": kind, "lon": lon, "lat": lat, "h": h, "label": label,
                                        "ref": p["id"], "amount": it["amount"], "certainty": "possible",
                                        "set": code})
                added_places += 1
    _write(pkg / "search_index.json", index)

    meta = _read(pkg / "metadata.json")
    package = meta["package"]
    items = [e for e in index["entries"] if e["type"] == "item"]
    package["counts"]["search_items"] = len(items)
    package["counts"]["search_items_with_model"] = sum(e.get("model") is not None for e in items)
    package["files"] = sorted(set(package["files"]) | {"treasure_sets.json"})
    _write(pkg / "metadata.json", meta)
    return {"sets": len(sets), "holders": len(holders), "possible_places": added_places}
