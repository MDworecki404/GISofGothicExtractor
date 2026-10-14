import re

import zenkit

from .records import ContainerRec, ItemRec, Vec3, VobRec, WayEdgeRec, WaypointRec, WorldData

T = zenkit.VobType


def parse_contents(s: str) -> list[tuple[str, int]]:
    """Parse oCMobContainer.contents, e.g. 'ItMi_Gold:50, ItFo_Apple;ItPo_Health_01' → [('ITMI_GOLD', 50), ('ITFO_APPLE', 1)]."""
    out = []
    for part in re.split(r"[,;]", s or ""):
        part = part.strip()
        if not part:
            continue
        code, _, amount = part.partition(":")
        code = code.strip().upper()
        if not code:
            continue
        try:
            n = int(amount.strip()) if amount.strip() else 1
        except ValueError:
            n = 1
        out.append((code, max(n, 1)))
    return out


def _vec(v) -> Vec3:
    return (float(v.x), float(v.y), float(v.z))


def _rot(m) -> list[float]:
    cols = m.columns
    return [float(cols[c][r]) for r in range(3) for c in range(3)]


def _visual_name(v) -> str | None:
    vis = v.visual
    return vis.name if vis is not None and vis.name else None


def load_world(vfs: zenkit.Vfs, world_file: str, version: zenkit.GameVersion) -> tuple[zenkit.World, WorldData]:
    node = vfs.find(world_file)
    if node is None:
        raise FileNotFoundError(world_file)
    world = zenkit.World.load(node.open(), version)
    wd = WorldData()
    counter = [0]

    def walk(v, parent_id):
        counter[0] += 1
        vid = counter[0]
        pos = _vec(v.position)
        wd.vobs.append(VobRec(vid, v.type.name, v.name or "", _visual_name(v), pos, _rot(v.rotation), parent_id,
                              bool(v.show_visual)))
        if v.type == T.oCItem:
            wd.items.append(ItemRec(v.instance.upper(), max(v.amount, 1), pos, "zen", vid, None))
        elif v.type == T.oCMobContainer:
            contents = parse_contents(v.contents)
            contents += [(i.instance.upper(), max(i.amount, 1)) for i in v.items]
            wd.containers.append(
                ContainerRec(vid, v.name or "", _visual_name(v), pos, bool(v.is_locked),
                             v.key or None, v.pick_string or None, contents)
            )
        elif v.type == T.zCVobSpot:
            wd.freepoints.append(WaypointRec(v.name or "", pos, True, False))
        for ch in v.children:
            walk(ch, vid)

    for root in world.root_objects:
        walk(root, None)

    wn = world.way_net
    points = wn.points
    for p in points:
        wd.waypoints.append(WaypointRec(p.name, _vec(p.position), bool(p.free_point), bool(p.under_water)))
    for e in wn.edges:
        wd.edges.append(WayEdgeRec(points[e.a].name, points[e.b].name))
    return world, wd


class PointResolver:
    """Resolve script waypoint/freepoint names to positions, case-insensitively (waynet first)."""

    def __init__(self, waypoints: list[WaypointRec], freepoints: list[WaypointRec]):
        self._pos: dict[str, Vec3] = {}
        for fp in freepoints:
            if fp.name:
                self._pos.setdefault(fp.name.upper(), fp.pos)
        for wp in waypoints:
            self._pos[wp.name.upper()] = wp.pos

    def resolve(self, name: str) -> Vec3 | None:
        return self._pos.get((name or "").upper())

    def names(self) -> set[str]:
        return set(self._pos)
