"""Gothic 3 road network from the NavZones sectors (Projects_compiled/<world>/<region>/**/*NavZones_01*/*.node).

G3 has no waypoint net. Roads are nav entities: gCNavZone_PS (polygon `Point`) and gCNavPath_PS (polyline `Point`
between two zones, ZoneA/ZoneBEntityID = GUIDs of zone entities, ZoneA/BIntersectionCenter = where the path meets the
zone, in the path entity's local space). `Point` is a bTValArray<bCVector>: u8 version (1), u32 count, count x 3 f32.

Graph (records shared with G1/G2, see records.WaypointRec/WayEdgeRec):
- nodes NAVPATH_<n>_<i>: point i of path n (n counts the kept paths, in file order);
- nodes NAVZONE_<n>_<A|B>: intersection center of path n with its zone A or B; joined to the nearest point of the path;
- edges: consecutive points of a path; within a zone every pair of intersection centers of the paths ending in it.
Paths with no recognised zone (zone GUID is not an entity of the loaded files, e.g. the shared "no zone" GUIDs) are
skipped; of a path with one recognised zone only that side gets a NAVZONE node.

python -m gothic_extract.g3.navnet --out output/g3/g3_world_01   # rewrites only waypoints.geojson there
"""
import argparse
import itertools
import struct
import sys
from pathlib import Path

import numpy as np

from ..config import GameConfig, load_game
from ..export_geojson import _Builder, write_waypoints
from ..records import WayEdgeRec, WaypointRec, WorldData
from ..report import Report
from .archive import G3Fs
from .entities import read_node_file, to_world, walk
from .genome import FormatError

NAV_REGION = "Myrtana"  # folder below the world folder; Varant and Nordmar have NavZones too but are not exported
SOURCE = "navzones"


def vector_array(raw: bytes) -> np.ndarray:
    """bTValArray<bCVector> property bytes -> (n, 3) float64 (entity-local)."""
    if len(raw) < 5 or raw[0] != 1:
        raise FormatError(f"unexpected vector array header {raw[:5]!r}")
    n = struct.unpack_from("<I", raw, 1)[0]
    if len(raw) != 5 + 12 * n:
        raise FormatError(f"vector array of {n} points has {len(raw)} bytes")
    return np.frombuffer(raw, "<f4", count=3 * n, offset=5).reshape(n, 3).astype(np.float64)


def nav_files(fs: G3Fs, world: str, region: str = NAV_REGION) -> list[str]:
    return sorted(p for p in fs.list(world + "/", ".node")
                  if p.split("/")[1].lower() == region.lower() and "navzones" in p.split("/")[-2].lower())


def nav_net(fs: G3Fs, world: str, region: str = NAV_REGION) -> tuple[list[WaypointRec], list[WayEdgeRec]]:
    zones, paths = {}, []
    for p in nav_files(fs, world, region):
        for e in walk(read_node_file(fs.find(p))):
            if "gCNavZone_PS" in e.props and e.guid:
                zones[e.guid] = e
            if "gCNavPath_PS" in e.props:
                paths.append(e)

    waypoints: list[WaypointRec] = []
    edges: list[WayEdgeRec] = []
    zone_centers: dict[str, list[str]] = {}
    n = 0
    for e in paths:
        props = e.props["gCNavPath_PS"].props
        sides = [s for s in "AB" if props[f"Zone{s}EntityID"].value in zones]
        if not sides:
            continue
        local = vector_array(props["Point"].value)
        if len(local) == 0:
            continue
        points = to_world(e.world, local)
        names = [f"NAVPATH_{n}_{i}" for i in range(len(points))]
        waypoints += [WaypointRec(nm, tuple(float(v) for v in pt), False, False, SOURCE)
                      for nm, pt in zip(names, points)]
        edges += [WayEdgeRec(a, b) for a, b in zip(names, names[1:])]
        for s in sides:
            center = np.array([props[f"Zone{s}IntersectionCenter"].value], dtype=np.float64)
            name = f"NAVZONE_{n}_{s}"
            waypoints.append(WaypointRec(name, tuple(float(v) for v in to_world(e.world, center)[0]),
                                         False, False, SOURCE))
            edges.append(WayEdgeRec(name, names[int(np.argmin(np.linalg.norm(local - center, axis=1)))]))
            zone_centers.setdefault(props[f"Zone{s}EntityID"].value, []).append(name)
        n += 1
    for centers in zone_centers.values():
        edges += [WayEdgeRec(a, b) for a, b in itertools.combinations(centers, 2)]
    return waypoints, edges


def main(argv: list[str] | None = None) -> int:
    from .archive import open_g3fs

    ap = argparse.ArgumentParser(prog="gothic_extract.g3.navnet",
                                 description="Write waypoints.geojson (G3 nav net) into an existing extraction")
    ap.add_argument("--out", required=True, type=Path, help="extraction folder, e.g. output/g3/g3_world_01")
    ap.add_argument("--world", default="G3_World_01")
    ap.add_argument("--game", default="g3")
    args = ap.parse_args(argv)
    cfg: GameConfig = load_game(args.game)
    wd = WorldData()
    wd.waypoints, wd.edges = nav_net(open_g3fs(cfg), args.world)
    write_waypoints(args.out, _Builder(cfg, {}, Report()), wd)
    print(f"  waypoints: {len(wd.waypoints)}, edges: {len(wd.edges)} -> {args.out / 'waypoints.geojson'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
