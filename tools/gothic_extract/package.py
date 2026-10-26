"""Build the complete geoportal packages of every world of a game with one command.

python -m gothic_extract.package --game g1            # from existing extractions in output/g1/<zen>
python -m gothic_extract.package --game g2nk --extract  # run the full extraction of each world first

Per world: geoportal package (layers, search index, glb, models, guild_names) -> quests (quests.json, quest entries,
package version 4) -> movement speeds. The steps run in this order for all worlds of the game, so a rebuilt
package is always a finished v4 package (the geoportal step alone writes v3). Finishes with the package validator.
"""
import argparse
import json
import sys
from pathlib import Path

from .__main__ import main as extract_world
from .config import PROJECT_ROOT, load_game
from .geoportal import build_geoportal
from .guilds import guild_names_pl
from .movement_speeds import ANIMATIONS, movement_speeds
from .quests import extract_quests
from .quests_package import build as build_quests, load_worlds, summarize
from .script_vm import make_vm
from .validate import validate_game
from .vfs import open_vfs


def _selected(cfg, only: list[str] | None) -> list[str]:
    if not only:
        return list(cfg.worlds)
    unknown = [w for w in only if w.upper() not in cfg.worlds]
    if unknown:
        raise SystemExit(f"unknown world(s) for {cfg.key}: {', '.join(unknown)}; known: {', '.join(cfg.worlds)}")
    return [w.upper() for w in only]


def _set_meta(pkg: Path, **fields) -> None:
    path = pkg / "metadata.json"
    meta = json.loads(path.read_text("utf-8"))
    meta.update(fields)
    path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_genome_game(cfg, zens: list[str], out_root: Path, dist_root: Path, extract: bool) -> dict[str, Path]:
    """Gothic 3: extraction by gothic_extract.g3, quests from .quest/.info (one world), no movement speeds."""
    from .g3.__main__ import main as extract_g3
    from .g3.archive import open_g3fs
    from .g3.loot_package import add_loot
    from .g3.catalog import build_g3_catalog
    from .g3.npc_codes import alignment_names_pl
    from .g3.quests import extract_g3_quests
    from .g3.strings import load_strings
    from .g3.templates import load_templates

    if extract:
        for zen in zens:
            print(f"== {cfg.key}/{zen}: extraction", flush=True)
            extract_g3(["--game", cfg.key, "--world", zen, "--out", str(out_root / zen.lower())])
    missing = [z for z in zens if not (out_root / z.lower() / "npcs.geojson").exists()]
    if missing:
        raise SystemExit(f"no extraction in {out_root} for: {', '.join(missing)} (run with --extract)")
    fs = open_g3fs(cfg)
    strings = load_strings(fs)
    names = alignment_names_pl(strings)
    catalog = build_g3_catalog(load_templates(fs), strings)
    pkgs = {}
    for zen in zens:
        pkgs[zen] = dist_root / cfg.key / cfg.worlds[zen].slug
        print(f"== {cfg.key}/{zen} -> {pkgs[zen]}", flush=True)
        build_geoportal(out_root / zen.lower(), pkgs[zen], names)
        loot = add_loot(out_root / zen.lower(), pkgs[zen])
        print(f"  random loot: {loot['sets']} sets, {loot['holders']} holders, "
              f"{loot['possible_places']} possible places", flush=True)
        npc_codes = {f["properties"]["code"] for f in
                     json.loads((out_root / zen.lower() / "npcs.geojson").read_text("utf-8"))["features"]}
        quests = extract_g3_quests(fs, strings, catalog, npc_codes)
        r = build_quests(cfg.key, pkgs[zen], out_root, quests=quests, worlds={}, single_world=True)
        print(summarize(r["world"], r["quests"]), flush=True)
        _set_meta(pkgs[zen], movement_speeds_m_s=None, movement_speeds_animations=[])
    return pkgs


def build_game(game: str, out_root: Path, dist_root: Path, only: list[str] | None = None, extract: bool = False,
               extract_args: list[str] = ()) -> dict[str, Path]:
    cfg = load_game(game)
    zens = _selected(cfg, only)
    if cfg.engine == "genome":
        return build_genome_game(cfg, zens, out_root, dist_root, extract)
    if extract:
        for zen in zens:
            print(f"== {game}/{zen}: extraction", flush=True)
            extract_world(["--game", game, "--world", zen, "--out", str(out_root / zen.lower()), *extract_args])
    missing = [z for z in cfg.worlds if not (out_root / z.lower() / "npcs.geojson").exists()]
    if missing:
        raise SystemExit(f"no extraction in {out_root} for: {', '.join(missing)} (run with --extract)")
    vm = make_vm(cfg.script_dat)
    names = guild_names_pl(vm)
    pkgs = {}
    for zen in zens:
        pkgs[zen] = dist_root / game / cfg.worlds[zen].slug
        print(f"== {game}/{zen} -> {pkgs[zen]}", flush=True)
        build_geoportal(out_root / zen.lower(), pkgs[zen], names)
    # quests are matched against the extraction of every world, not only the selected ones
    quests, worlds = extract_quests(vm), load_worlds(out_root)
    for zen, pkg in pkgs.items():
        r = build_quests(game, pkg, out_root, quests, worlds)
        print(summarize(r["world"], r["quests"]), flush=True)
        if r["unassigned"]:
            print(f"  bez świata (pominięte w każdej paczce, {len(r['unassigned'])} z {r['all']}): "
                  + "; ".join(f"{q['code']} ({q['name']})" for q in r["unassigned"]))
    speeds = movement_speeds(open_vfs(cfg))
    print(f"  movement_speeds_m_s: {speeds}")
    for pkg in pkgs.values():
        _set_meta(pkg, movement_speeds_m_s=speeds, movement_speeds_animations=ANIMATIONS)
    return pkgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.package", description="Build the geoportal packages of a game")
    ap.add_argument("--game", required=True, help="key from games.toml, e.g. g1")
    ap.add_argument("--world", action="append", help="ZEN name to build (repeatable); default: all worlds of the game")
    ap.add_argument("--extract", action="store_true", help="run the full extraction of the selected worlds first")
    ap.add_argument("--skip-mesh", action="store_true", help="with --extract: no world.glb")
    ap.add_argument("--skip-models", action="store_true", help="with --extract: no VOB/item models")
    ap.add_argument("--skip-previews", action="store_true", help="with --extract: no item previews")
    ap.add_argument("--out-root", type=Path, help="extractions folder (default: output/<game>)")
    ap.add_argument("--dist-root", type=Path, default=PROJECT_ROOT / "dist", help="packages go to <dist-root>/<game>/<slug>")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    extract_args = [f for f, on in [("--skip-mesh", args.skip_mesh), ("--skip-models", args.skip_models),
                                    ("--skip-previews", args.skip_previews)] if on]
    out_root = args.out_root or PROJECT_ROOT / "output" / args.game
    build_game(args.game, out_root, args.dist_root, args.world, args.extract, extract_args)
    report = validate_game(args.game, args.dist_root)
    print(report.text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
