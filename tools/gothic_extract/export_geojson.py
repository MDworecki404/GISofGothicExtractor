import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .catalog import ItemDef
from .config import GameConfig
from .coords import game_to_lonlat
from .mesh_export import MeshStats
from .npcs import NpcRec
from .records import ItemRec, Vec3, WorldData
from .report import Report


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


class _Builder:
    def __init__(self, cfg: GameConfig, catalog: dict[str, ItemDef], report: Report):
        self.cfg, self.catalog, self.report = cfg, catalog, report

    def _coord(self, pos: Vec3) -> list[float]:
        lon, lat, h = game_to_lonlat(pos, self.cfg)
        return [round(lon, 9), round(lat, 9), round(h, 3)]

    def point(self, pos: Vec3, props: dict) -> dict:
        coord = self._coord(pos)
        props = {**props, "game_pos": [round(v, 2) for v in pos], "height_m": coord[2]}
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": coord}, "properties": props}

    def line(self, a: Vec3, b: Vec3, props: dict) -> dict:
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [self._coord(a), self._coord(b)]},
                "properties": props}

    def item_info(self, code: str) -> dict:
        d = self.catalog.get(code)
        if d is None:
            self.report.unknown_item(code)
            return {"code": code, "name": None, "category": None}
        return {"code": code, "name": d.name, "category": d.category}


def write_outputs(out_dir: Path, cfg: GameConfig, world_name: str, wd: WorldData, catalog: dict[str, ItemDef],
                  npcs: list[NpcRec], script_items: list[ItemRec], mesh: MeshStats | None) -> Report:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = Report()
    b = _Builder(cfg, catalog, report)

    items = [
        b.point(i.pos, {"id": f"item-{n}", **b.item_info(i.code), "amount": i.amount, "source": i.source,
                        "spot": i.spot})
        for n, i in enumerate(wd.items + script_items)
        if i.pos is not None
    ]
    _write(out_dir / "items.geojson", _fc(items))

    containers = [
        b.point(c.pos, {
            "id": f"container-{c.vob_id}", "name": c.name, "visual": c.visual, "locked": c.locked, "key": c.key,
            "pick_string": c.pick_string, "source": "zen",
            "contents": [{**b.item_info(code), "amount": n} for code, n in c.contents],
            **({"treasure_sets": c.treasure_sets} if c.treasure_sets else {}),
        })
        for c in wd.containers
    ]
    _write(out_dir / "containers.geojson", _fc(containers))

    npc_feats, routine_feats = [], []
    for k, n in enumerate(npcs):
        if n.pos is None:
            report.warnings.append(f"unresolved NPC insert point: {n.code} @ {n.insert_waypoint}")
            continue
        npc_feats.append(b.point(n.pos, {
            "id": f"npc-{k}", "code": n.code, "name": n.name, "category": "NPC", "guild": n.guild,
            "guild_name": n.guild_name, "level": n.level, "chapter": n.chapter, "insert_waypoint": n.insert_waypoint,
            "insert_function": n.insert_function, "name_unique_in_game": n.name_unique_in_game,
            "is_human": n.is_human, "inserts_in_game": n.inserts_in_game, "source": "script",
            "inventory": [{**b.item_info(i.code), "amount": i.amount, "certainty": i.certainty} for i in n.inventory],
            "routines": [{key: v for key, v in asdict(r).items() if key != "pos"} for r in n.routines],
            **({"treasure_sets": n.treasure_sets} if n.treasure_sets else {}),
        }))
        for r in n.routines:
            if r.pos is None:
                continue
            routine_feats.append(b.point(r.pos, {
                "id": f"npc-{k}-rtn-{len(routine_feats)}", "npc_code": n.code, "npc_name": n.name,
                "routine": r.routine, "is_default": r.is_default, "start": r.start, "end": r.end,
                "action": r.action, "waypoint": r.waypoint, "source": "script",
            }))
    _write(out_dir / "npcs.geojson", _fc(npc_feats))
    _write(out_dir / "npc_routines.geojson", _fc(routine_feats))

    vobs = [
        b.point(v.pos, {"id": f"vob-{v.id}", "vob_type": v.vob_type, "name": v.name, "visual": v.visual,
                        "rot": [round(x, 6) for x in v.rot], "parent_id": v.parent_id, "source": "zen"})
        for v in wd.vobs
    ]
    _write(out_dir / "vobs.geojson", _fc(vobs))

    wp_pos = {w.name: w.pos for w in wd.waypoints}
    wps = [b.point(w.pos, {"id": f"wp-{w.name}", "name": w.name, "under_water": w.under_water, "source": "zen"})
           for w in wd.waypoints]
    wps += [b.line(wp_pos[e.a], wp_pos[e.b], {"a": e.a, "b": e.b}) for e in wd.edges]
    _write(out_dir / "waypoints.geojson", _fc(wps))

    fps = [b.point(f.pos, {"id": f"fp-{k}", "name": f.name, "source": "zen"}) for k, f in enumerate(wd.freepoints)]
    _write(out_dir / "freepoints.geojson", _fc(fps))

    _write(out_dir / "catalog_items.json", {k: v.to_dict() for k, v in sorted(catalog.items())})

    meta = {
        "game": cfg.key,
        "world": world_name,
        "anchor": {"lon": cfg.anchor_lon, "lat": cfg.anchor_lat, "h": cfg.anchor_h},
        "axes": {"east": "+X", "north": "+Z", "up": "+Y", "unit_cm": True},
        "gltf_axes": "glTF = (E, U, -N) in metres, i.e. (x/100, y/100, -z/100) of game coordinates",
        "zenkit_version": "1.3.0.4",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if mesh is not None:
        meta["mesh"] = asdict(mesh)
    _write(out_dir / "metadata.json", meta)

    report.counts.update({
        "items_zen": len(wd.items),
        "items_script": len(script_items),
        "containers": len(containers),
        "container_item_stacks": sum(len(c.contents) for c in wd.containers),
        "npcs": len(npc_feats),
        "npc_routine_points": len(routine_feats),
        "npc_routine_points_unresolved": sum(1 for n in npcs for r in n.routines if r.pos is None),
        "vobs": len(vobs),
        "waypoints": len(wd.waypoints),
        "way_edges": len(wd.edges),
        "freepoints": len(fps),
        "catalog_items": len(catalog),
    })
    if mesh is not None:
        report.counts.update({"mesh_triangles": mesh.triangles, "mesh_materials": mesh.materials})
        report.warnings += [f"missing texture: {t}" for t in mesh.textures_missing]
    report.write(out_dir / "report.txt")
    return report
