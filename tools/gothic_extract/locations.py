"""Named places of a world -> locations.json of the geoportal package (package version 5).

Sources (ZenKit games, G1/G2/Archolos), all read from the world's ZEN:
- oCTriggerChangeLevel: one `passage` per trigger (levelName, startVobName = arrival point in the target world);
- oCZoneMusic: the only zone with a name and an extent. The game names it with a code (OLDCAMP_OC), so the place name
  is OUR mapping (location_names.toml, name_source "derived"); zones of one base name that touch each other are one
  place (a camp has several zones), distant ones are separate places.
Waypoint prefixes, FP_* spots and start points are not places (they only help: nearest waypoint, arrival point).
Gothic 3 is read by g3/locations.py. Both end in `write_locations`.

python -m gothic_extract.locations --game g1 [--world WORLD]   # add locations.json to existing packages
"""
import argparse
import json
import math
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zenkit

from .config import PROJECT_ROOT, GameConfig, load_game
from .coords import game_to_lonlat, lonlat_to_enu

LOCATIONS_FILE = "locations.json"
NAMES_FILE = Path(__file__).with_name("location_names.toml")
KINDS = ["camp", "town", "district", "building", "cave", "region", "landmark", "passage"]
NAME_SOURCES = ["game", "derived", "code"]
PASSAGE_PREFIX = "Przejście do: "
WAYPOINT_MAX_M = 150.0  # nearest waypoint farther than this is not reported
CLUSTER_MARGIN_CM = 500.0  # zones closer than this (in the ground plane) are one place
T = zenkit.VobType


def load_names(game: str) -> dict:
    with open(NAMES_FILE, "rb") as f:
        return tomllib.load(f).get(game, {})


def zone_base(name: str) -> str:
    """OLDCAMP_OC -> OLDCAMP, ARCHOLOS2_CIT -> ARCHOLOS, NEWCAMP_SNOW_NCO -> NEWCAMP."""
    return re.sub(r"\d+$", "", name.upper().split("_")[0]) or name.upper()


def lonlat(cfg: GameConfig, pos) -> list[float]:
    lon, lat, h = game_to_lonlat(tuple(float(v) for v in pos), cfg)
    return [round(lon, 9), round(lat, 9), round(h, 2)]


class WaypointIndex:
    """Nearest node of the package's waypoints.json."""

    def __init__(self, pkg: Path, cfg: GameConfig):
        path = pkg / "waypoints.json"
        self.names: list[str] = []
        pts = []
        if path.is_file():
            for name, lon, lat, h, _ in json.loads(path.read_text("utf-8"))["nodes"]:
                e, n = lonlat_to_enu(lon, lat, cfg.anchor_lon, cfg.anchor_lat)
                self.names.append(name)
                pts.append((e, n, h))
        self.pts = np.array(pts, dtype=np.float64).reshape(-1, 3)

    def nearest(self, center: list[float], cfg: GameConfig) -> str | None:
        if not len(self.pts):
            return None
        e, n = lonlat_to_enu(center[0], center[1], cfg.anchor_lon, cfg.anchor_lat)
        d = np.linalg.norm(self.pts - np.array([e, n, center[2]]), axis=1)
        i = int(np.argmin(d))
        return self.names[i] if d[i] <= WAYPOINT_MAX_M else None


@dataclass
class Box:
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    y: float  # y of the zone vob


@dataclass
class Raw:
    """What a ZEN gives for locations."""
    passages: list[dict] = field(default_factory=list)  # name, level, start, pos, box
    zones: list[tuple[str, Box]] = field(default_factory=list)


def _walk(vobs):
    for v in vobs:
        yield v
        yield from _walk(v.children)


def _box(v) -> Box:
    b = v.bbox
    return Box((float(b.min.x), float(b.min.y), float(b.min.z)), (float(b.max.x), float(b.max.y), float(b.max.z)),
               float(v.position.y))


def read_raw(world: zenkit.World) -> Raw:
    raw = Raw()
    for v in _walk(world.root_objects):
        if v.type == T.oCTriggerChangeLevel:
            raw.passages.append({"name": v.name or "", "level": v.level_name or "", "start": v.start_vob or "",
                                 "pos": (float(v.position.x), float(v.position.y), float(v.position.z)),
                                 "box": _box(v)})
        elif v.type == T.oCZoneMusic and v.name:
            raw.zones.append((v.name.upper(), _box(v)))
    return raw


def cluster(boxes: list[Box], margin: float = CLUSTER_MARGIN_CM) -> list[list[Box]]:
    """Connected groups of boxes that overlap (or are closer than `margin`) in the ground plane."""
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if (a.lo[0] - margin <= b.hi[0] and b.lo[0] - margin <= a.hi[0]
                    and a.lo[2] - margin <= b.hi[2] and b.lo[2] - margin <= a.hi[2]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Box]] = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    return list(groups.values())


def extent(group: list[Box], cfg: GameConfig) -> tuple[list[float], float | None, list[list[float]] | None]:
    """center [lon, lat, h], radius_m (circle around the union box, None for a point) and polygon (the box itself,
    closed ring; only for a single box, a union of boxes has no honest outline)."""
    lo_x, hi_x = min(b.lo[0] for b in group), max(b.hi[0] for b in group)
    lo_z, hi_z = min(b.lo[2] for b in group), max(b.hi[2] for b in group)
    y = sum(b.y for b in group) / len(group)
    center = lonlat(cfg, ((lo_x + hi_x) / 2, y, (lo_z + hi_z) / 2))
    radius = math.hypot(hi_x - lo_x, hi_z - lo_z) / 2 / 100
    polygon = None
    if len(group) == 1 and radius > 0:
        ring = [lonlat(cfg, (x, y, z))[:2] for x, z in ((lo_x, lo_z), (hi_x, lo_z), (hi_x, hi_z), (lo_x, hi_z))]
        polygon = ring + [ring[0]]
    return center, (round(radius, 1) if radius > 0 else None), polygon


def zone_locations(raw: Raw, cfg: GameConfig, names: dict, wp: WaypointIndex) -> tuple[list[dict], list[str]]:
    """Places from oCZoneMusic. Second value: zone bases missing from location_names.toml (they get kind region
    and the code as the name)."""
    table = names.get("zones", {})
    by_base: dict[str, list[Box]] = {}
    for name, box in raw.zones:
        base = zone_base(name)
        base = table.get(base, {}).get("alias", base)
        by_base.setdefault(base, []).append(box)
    out, unknown = [], []
    for base, boxes in sorted(by_base.items()):
        entry = table.get(base)
        if entry is None:
            unknown.append(base)
            entry = {}
        groups = sorted(cluster(boxes), key=lambda g: (min(b.lo[0] for b in g), min(b.lo[2] for b in g)))
        for n, group in enumerate(groups, 1):
            center, radius, polygon = extent(group, cfg)
            out.append({
                "id": f"location:{base}" + (f"-{n}" if len(groups) > 1 else ""),
                "kind": entry.get("kind", "region"),
                "name": entry.get("name", base), "name_source": "derived" if "name" in entry else "code",
                "code": base, "center": center, "radius_m": radius, "polygon": polygon,
                "waypoint": wp.nearest(center, cfg)})
    return out, unknown


def target_key(level: str) -> str:
    """'Oldworld\\OldWorld.ZEN' -> 'OLDWORLD'."""
    return re.split(r"[\\/]", level)[-1].rsplit(".", 1)[0].upper()


def arrival_index(out_dir: Path) -> dict[str, list[float]]:
    """Name (upper case) -> [lon, lat, h] in an extraction: vobs (start points first), then waypoints and
    free points."""
    rank = {"zCVobStartpoint": 0, "zCVob": 1, "zCVobSpot": 2}
    best: dict[str, tuple[int, list[float]]] = {}
    for fn, default_rank in (("vobs.geojson", None), ("waypoints.geojson", 4), ("freepoints.geojson", 5)):
        path = out_dir / fn
        if not path.is_file():
            continue
        for f in json.loads(path.read_text("utf-8"))["features"]:
            p = f["properties"]
            if f["geometry"]["type"] != "Point" or not p.get("name"):
                continue
            r = default_rank if default_rank is not None else rank.get(p["vob_type"], 3)
            key = p["name"].upper()
            if key not in best or r < best[key][0]:
                best[key] = (r, f["geometry"]["coordinates"])
    return {k: v[1] for k, v in best.items()}


def passage_locations(raw: Raw, cfg: GameConfig, out_root: Path, wp: WaypointIndex) -> list[dict]:
    out, used = [], {}
    arrivals: dict[str, dict[str, list[float]]] = {}
    for p in sorted(raw.passages, key=lambda p: (p["name"], p["pos"])):
        target = target_key(p["level"])
        entry = cfg.worlds.get(target)
        center, radius, _ = extent([p["box"]], cfg)
        if p["box"].lo == p["box"].hi:
            center = lonlat(cfg, p["pos"])
        base = f"location:passage:{p['name'] or target}"
        used[base] = used.get(base, 0) + 1
        arrival = None
        if entry is not None and p["start"]:
            if target not in arrivals:
                arrivals[target] = arrival_index(out_root / target.lower())
            found = arrivals[target].get(p["start"].upper())
            arrival = [round(found[0], 9), round(found[1], 9), round(found[2], 2)] if found else None
        out.append({
            "id": base if used[base] == 1 else f"{base}-{used[base]}", "kind": "passage",
            "name": PASSAGE_PREFIX + (entry.name_pl if entry is not None else target),
            "name_source": "derived", "code": p["name"] or None, "center": center, "radius_m": radius, "polygon": None,
            "waypoint": wp.nearest(center, cfg),
            "passage": {"to_world": f"{cfg.key}/{entry.slug}" if entry is not None else None,
                        "to_level": p["level"], "arrival": arrival}})
    return out


def write_locations(pkg: Path, game: str, locations: list[dict]) -> dict:
    """Write locations.json (order: kind, id) and register it in metadata.json: package version 5, counts.locations,
    files."""
    order = {k: i for i, k in enumerate(KINDS)}
    locations = sorted(locations, key=lambda l: (order[l["kind"]], l["id"]))
    meta_path = pkg / "metadata.json"
    meta = json.loads(meta_path.read_text("utf-8"))
    (pkg / LOCATIONS_FILE).write_text(json.dumps(
        {"version": 1, "game": game, "world": meta["world"], "locations": locations},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    package = meta["package"]
    package["version"] = max(package.get("version", 0), 5)
    package["counts"]["locations"] = len(locations)
    package["files"] = sorted(set(package["files"]) | {LOCATIONS_FILE})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"locations": locations, "kinds": {k: sum(l["kind"] == k for l in locations) for k in KINDS}}


def add_locations(cfg: GameConfig, zen: str, pkg: Path, out_root: Path, vfs) -> dict:
    """ZenKit games: read the world's ZEN and write pkg/locations.json."""
    node = vfs.find(zen + ".ZEN")
    if node is None:
        raise FileNotFoundError(zen + ".ZEN")
    raw = read_raw(zenkit.World.load(node.open(), cfg.version))
    wp = WaypointIndex(pkg, cfg)
    zones, unknown = zone_locations(raw, cfg, load_names(cfg.key), wp)
    result = write_locations(pkg, cfg.key, zones + passage_locations(raw, cfg, out_root, wp))
    result["unknown_zone_bases"] = unknown
    return result


def summarize(zen: str, r: dict) -> str:
    locs = r["locations"]
    src = {s: sum(l["name_source"] == s for l in locs) for s in NAME_SOURCES}
    kinds = ", ".join(f"{k} {n}" for k, n in r["kinds"].items() if n)
    text = f"  lokacje {zen}: {len(locs)} ({kinds}; nazwy: " + ", ".join(f"{s} {n}" for s, n in src.items()) + ")"
    if r.get("unknown_zone_bases"):
        text += f"; strefy bez wpisu w location_names.toml: {', '.join(r['unknown_zone_bases'])}"
    return text


def main(argv: list[str] | None = None) -> int:
    from .vfs import open_vfs

    ap = argparse.ArgumentParser(prog="gothic_extract.locations", description="Add locations.json to built packages")
    ap.add_argument("--game", required=True, help="ZenKit game key from games.toml (g1, g2nk, archolos)")
    ap.add_argument("--world", action="append", help="ZEN name (repeatable); default: all worlds of the game")
    ap.add_argument("--dist-root", type=Path, default=PROJECT_ROOT / "dist")
    ap.add_argument("--out-root", type=Path)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_game(args.game)
    out_root = args.out_root or PROJECT_ROOT / "output" / args.game
    vfs = open_vfs(cfg)
    for zen in [w.upper() for w in args.world] if args.world else list(cfg.worlds):
        r = add_locations(cfg, zen, args.dist_root / args.game / cfg.worlds[zen].slug, out_root, vfs)
        print(summarize(zen, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
