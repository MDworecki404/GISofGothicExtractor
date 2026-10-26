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
from .treasure import load_treasure_sets
from .world import WorldStats, extract_world


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
    print(f"[4/4] writing GeoJSON to {args.out}", flush=True)
    report = write_outputs(args.out, cfg, args.world.upper(), wd, catalog, npcs, [], None)

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
