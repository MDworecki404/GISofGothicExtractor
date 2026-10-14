import argparse
import sys
from pathlib import Path

from .catalog import build_item_catalog
from .config import load_game
from .export_geojson import write_outputs
from .mesh_export import export_world_glb
from .daedalus_scan import other_world_functions
from .npcs import extract_npcs, extract_script_items
from .script_vm import make_vm
from .vfs import open_vfs
from .world_data import PointResolver, load_world


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract", description="Extract a Gothic world to glb + GeoJSON")
    ap.add_argument("--game", required=True, help="key from games.toml, e.g. g2nk")
    ap.add_argument("--world", required=True, help="ZEN name without extension, e.g. NEWWORLD")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--skip-mesh", action="store_true", help="do not export world.glb")
    args = ap.parse_args(argv)

    cfg = load_game(args.game)
    world_file = args.world.upper() + ".ZEN"
    print(f"[1/5] mounting {cfg.root}", flush=True)
    vfs = open_vfs(cfg)
    print(f"[2/5] reading {world_file}", flush=True)
    world, wd = load_world(vfs, world_file, cfg.version)
    resolver = PointResolver(wd.waypoints, wd.freepoints)
    print("[3/5] scripts: items, NPCs, routines", flush=True)
    vm = make_vm(cfg.script_dat)
    catalog = build_item_catalog(vm)
    exclude = other_world_functions(vm, cfg.world_roots, args.world)
    npcs = extract_npcs(vm, resolver, exclude)
    script_items = extract_script_items(vm, resolver, exclude)
    mesh = None
    if not args.skip_mesh:
        print("[4/5] world mesh -> world.glb", flush=True)
        mesh = export_world_glb(world, vfs, args.out / "world.glb")
    print("[5/5] writing GeoJSON", flush=True)
    report = write_outputs(args.out, cfg, args.world.upper(), wd, catalog, npcs, script_items, mesh)
    for k, v in report.counts.items():
        print(f"  {k}: {v}")
    print(f"  warnings: {len(report.warnings)} (see report.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
