"""Gothic 3 places -> locations.json (see gothic_extract.locations).

- gCEnclave_PS (31 entities): the game's own settlements (cities, camps, clans, temples); a point each. The Polish
  name comes from the game's stringtable.ini (GO_Enclave_<Name>, MAP_World_<Region>_<Name>_01); the rest is in
  location_names.toml ([g3.enclaves], name_source "derived") or stays a code.
- gCNavZone_PS + gCArena_PS: arenas, with the polygon the zone stores (name derived: "Arena: <town>").
G3 has one world file and no level changes, so there are no passages. eCWeatherZone_PS are lighting/weather zones
named after their environment (Cave, Dungeon, Temple...), not places: they are not used.
"""
import re

from ..config import GameConfig
from ..locations import WaypointIndex, load_names, lonlat, write_locations
from .entities import to_world, walk
from .navnet import vector_array
from .world import WorldStats, _load, _value, sector_files

MAP_KEY = re.compile(r"^MAP_World_[^_]+_(.+)_01$")
ARENA_VARIANT = {"village": " (wieś)", "city": " (miasto)"}


def place_names(strings: dict[str, str]) -> dict[str, str]:
    """lower-case place key -> Polish name from the game (map entries first, enclave entries override)."""
    out = {}
    for k, v in strings.items():
        m = MAP_KEY.match(k)
        if m and v:
            out[m.group(1).lower()] = v
    for k, v in strings.items():
        if k.startswith("GO_Enclave_") and v:
            out[k[len("GO_Enclave_"):].lower()] = v
    return out


def enclave_key(name: str) -> str:
    key = name.lower()
    return key[len("enclave_"):] if key.startswith("enclave_") else key


def arena_name(name: str, names: dict[str, str]) -> str:
    """Faring_Arena_City -> "Arena: Faring (miasto)"; Arena_Silden -> "Arena: Silden"."""
    parts = [p for p in name.split("_") if p.lower() != "arena"]
    town = names.get(parts[0].lower(), parts[0]) if parts else name
    variant = next((ARENA_VARIANT[p.lower()] for p in parts[1:] if p.lower() in ARENA_VARIANT), "")
    return f"Arena: {town}{variant}"


def g3_locations(fs, cfg: GameConfig, world: str, strings: dict[str, str], pkg) -> dict:
    loaded = _load(fs, sector_files(fs, world, cfg.sector_exclude, cfg.include_disabled_sectors), WorldStats())
    wp = WaypointIndex(pkg, cfg)
    names = place_names(strings)
    table = load_names(cfg.key).get("enclaves", {})
    out, seen = [], set()
    for x in sorted(loaded, key=lambda x: x.entity.name):
        e = x.entity
        if "gCEnclave_PS" in e.props:
            key = enclave_key(e.name)
            entry = table.get(key, {})
            if key in names:
                name, source = names[key], "game"
            elif "name" in entry:
                name, source = entry["name"], "derived"
            else:
                name, source = e.name, "code"
            center = lonlat(cfg, e.pos)
            out.append({"id": f"location:{e.name}", "kind": entry.get("kind", "town"), "name": name,
                        "name_source": source, "code": e.name, "center": center, "radius_m": None, "polygon": None,
                        "waypoint": wp.nearest(center, cfg)})
        elif "gCNavZone_PS" in e.props and "gCArena_PS" in e.props and e.guid not in seen:
            seen.add(e.guid)
            ring = [lonlat(cfg, p)[:2] for p in to_world(e.world, vector_array(e.props["gCNavZone_PS"].props["Point"].value))]
            radius = _value(e, "gCNavZone_PS", "Radius")
            center = lonlat(cfg, e.pos)
            out.append({"id": f"location:{e.name}", "kind": "landmark", "name": arena_name(e.name, names),
                        "name_source": "derived", "code": e.name, "center": center,
                        "radius_m": round(radius / 100, 1) if radius else None,
                        "polygon": ring + [ring[0]] if len(ring) >= 3 else None,
                        "waypoint": wp.nearest(center, cfg)})
    return write_locations(pkg, cfg.key, out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from pathlib import Path

    from ..config import PROJECT_ROOT, load_game
    from ..locations import summarize
    from .archive import open_g3fs
    from .strings import load_strings

    ap = argparse.ArgumentParser(prog="gothic_extract.g3.locations", description="Add locations.json to the G3 package")
    ap.add_argument("--game", default="g3")
    ap.add_argument("--dist-root", type=Path, default=PROJECT_ROOT / "dist")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_game(args.game)
    fs, strings = open_g3fs(cfg), None
    strings = load_strings(fs)
    for zen, entry in cfg.worlds.items():
        print(summarize(zen, g3_locations(fs, cfg, zen, strings, args.dist_root / args.game / entry.slug)))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
