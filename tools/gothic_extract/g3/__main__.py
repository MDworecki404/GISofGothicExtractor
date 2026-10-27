"""Extract the Gothic 3 world to the same files as the G1/G2 extraction (GeoJSON + catalog + metadata).

python -m gothic_extract.g3 --out output/g3/g3_world_01 [--world G3_World_01]
"""
import argparse
import json
import sys
from pathlib import Path

from ..config import load_game
from ..export_geojson import write_outputs
from .archive import open_g3fs
from .catalog import build_g3_catalog
from .strings import load_strings
from .templates import load_templates
from .models import export_item_previews, export_models, node_files, node_placements, speedtrees, world_placements
from .terrain import export_terrain_glb, landscape_meshes
from .treasure import load_treasure_sets
from .world import WorldStats, extract_world, sector_names


def write_treasure_sets(out: Path, sets: dict, catalog: dict, wd, npcs) -> None:
    """treasure_sets.json: every set used in the world, with Polish item names and the number of holders."""
    holders: dict[str, int] = {}
    for rec in [*wd.containers, *npcs]:
        for code in rec.treasure_sets:
            holders[code] = holders.get(code, 0) + 1
    data = {}
    for code in sorted(holders):
        s = sets.get(code)
        if s is None:
            continue
        data[code] = {
            "kind": s.kind, "distribution": s.distribution, "min_stacks": s.min_stacks, "max_stacks": s.max_stacks,
            "holders": holders[code],
            "items": [{"code": c, "name": catalog[c].name if c in catalog else None,
                       "category": catalog[c].category if c in catalog else None, "amount": n} for c, n in s.items],
        }
    (out / "treasure_sets.json").write_text(json.dumps({"version": 1, "sets": data}, ensure_ascii=False,
                                                       separators=(",", ":")), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.g3", description="Extract the Gothic 3 world to GeoJSON")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--world", default="G3_World_01", help="world folder in Projects_compiled")
    ap.add_argument("--game", default="g3", help="key from games.toml")
    ap.add_argument("--skip-mesh", action="store_true", help="do not export world.glb (terrain)")
    ap.add_argument("--skip-models", action="store_true", help="do not export vobs.glb and models/*.glb")
    ap.add_argument("--skip-previews", action="store_true", help="do not export item previews (models/previews)")
    ap.add_argument("--max-texture", type=int, default=512, help="largest terrain texture side (pixels)")
    ap.add_argument("--max-model-texture", type=int, default=256,
                    help="largest texture side of objects and item previews (pixels); 342 textures, keeps vobs.glb smaller")
    args = ap.parse_args(argv)

    cfg = load_game(args.game)
    print(f"[1/4] archives in {cfg.root}", flush=True)
    fs = open_g3fs(cfg)
    print("[2/4] templates and texts", flush=True)
    failed: list[str] = []
    templates = load_templates(fs, failed)
    strings = load_strings(fs)
    catalog = build_g3_catalog(templates, strings)
    print(f"  templates: {len(set(id(t) for t in templates.values()))}, unsupported: {len(failed)}, "
          f"items in catalog: {len(catalog)}", flush=True)
    print(f"[3/4] world {args.world}", flush=True)
    stats = WorldStats()
    wd, npcs = extract_world(fs, cfg, args.world, templates, strings, stats)
    mesh = None
    if not args.skip_mesh:
        print("[4/4] terrain -> world.glb", flush=True)
        mesh = export_terrain_glb(fs, landscape_meshes(fs), args.out / "world.glb", args.max_texture)
        print(f"  triangles: {mesh.triangles}, materials: {mesh.materials}, "
              f"missing textures: {len(mesh.textures_missing)}", flush=True)
    if not args.skip_models:
        print("[4/4] objects and items -> vobs.glb, models/*.glb", flush=True)
        nodes = node_files(fs, args.world, sector_names(fs, args.world, cfg.sector_exclude, cfg.include_disabled_sectors))
        world_places, animated = world_placements(fs, cfg, args.world, templates)
        mr = export_models(fs, node_placements(fs, nodes) + world_places, args.out / "models", args.max_model_texture,
                           {"speedtree": speedtrees(fs, nodes), "animated_unreadable": animated})
        print(f"  models: {mr.models}, instances: {mr.instances}, missing: {sum(mr.missing.values())}, "
              f"unreadable animated: {animated}, "
              f"not supported: {mr.unhandled}", flush=True)
    if not args.skip_previews:
        # after the world models: their export clears models/textures, previews only add to it
        print("[4/4] item previews -> models/previews/*.glb", flush=True)
        pr = export_item_previews(fs, catalog, args.out / "models" / "previews", args.max_model_texture,
                                  extra_visuals=[c.visual for c in wd.containers if c.visual])
        reasons = {r: sum(1 for v in pr.reason.values() if v == r) for r in ("no_visual", "no_mesh")}
        print(f"  previews: {len(pr.entries)}, items without preview: {reasons}", flush=True)
    print(f"[4/4] writing GeoJSON to {args.out}", flush=True)
    report = write_outputs(args.out, cfg, args.world.upper(), wd, catalog, npcs, [], mesh)

    write_treasure_sets(args.out, load_treasure_sets(fs, templates), catalog, wd, npcs)

    meta_path = args.out / "metadata.json"
    meta = json.loads(meta_path.read_text("utf-8"))
    meta.pop("zenkit_version", None)
    meta["engine"] = "genome"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    extra = [f"unsupported sector file: {p}" for p in stats.unsupported_sectors]
    extra += [f"unknown template GUID: {g} ({n} references)" for g, n in sorted(stats.unknown_templates.items())]
    extra += [f"unsupported template file: {p}" for p in failed if not p.startswith("_deleted/")]
    with open(args.out / "report.txt", "a", encoding="utf-8") as f:
        f.write("\n# G3 reader\n" + "\n".join([f"sectors: {stats.sectors}"] + extra) + "\n")
    for k, v in report.counts.items():
        print(f"  {k}: {v}")
    print(f"  warnings: {len(report.warnings) + len(extra)} (see report.txt)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
