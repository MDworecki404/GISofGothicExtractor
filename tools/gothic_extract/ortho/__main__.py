"""Orthophoto of a geoportal package: python -m gothic_extract.ortho --pkg dist/g2nk/khorinis --gsd 0.25"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

from .geotiff import write_geotiff
from .georef import make_grid
from .glbmesh import load_parts, texel_size_cm
from .raster import render_block

MAX_PIXELS = 2_000_000_000
WATER_HELPERS = ("water_sea", "rivermesh_depth")  # untextured depth/far-sea meshes that z-fight with the terrain
WATER_COLOR = (0.24, 0.38, 0.47)  # flat water colour of the orthophoto
MAX_VOB_EXTENT_M = 1000.0  # wider "objects" are backdrops (G3: Landscape_Border, 4 km) and would cover the terrain


def check_size(width: int, height: int, bbox_given: bool, limit: int = MAX_PIXELS) -> None:
    if not bbox_given and width * height > limit:
        raise ValueError(f"Obraz miałby {width}×{height} = {width * height:,} px (limit bez --bbox: {limit:,}). "
                         "Zawęź obszar przez --bbox albo zwiększ --gsd.")


def _water(parts: list) -> tuple[list, int]:
    """Drop untextured water helper meshes; paint water a flat colour (its texture is tinted by the game's shader)."""
    kept, changed = [], 0
    for p in parts:
        name = p.name.lower()
        if p.texture is None and any(h in name for h in WATER_HELPERS):
            changed += 1
            continue
        if "water" in name:
            p.texture, p.color, p.mips = None, WATER_COLOR, None
            changed += 1
        kept.append(p)
    return kept, changed


def build_ortho(pkg: Path, gsd: float, bbox: tuple[float, float, float, float] | None, include_vobs: bool,
                out: Path | None) -> dict:
    anchor = json.loads((pkg / "metadata.json").read_text("utf-8"))["anchor"]
    parts = load_parts(pkg / "world.glb")
    bbox_given = bbox is not None
    if bbox is None:  # from the world mesh only: vobs include stray objects far outside the playable area
        if not parts:
            raise ValueError("Paczka nie ma geometrii.")
        lo = np.min([p.pos[:, :2].min(axis=0) for p in parts], axis=0)
        hi = np.max([p.pos[:, :2].max(axis=0) for p in parts], axis=0)
        bbox = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))
    warnings = []
    if include_vobs:
        vobs = load_parts(pkg / "vobs.glb")
        kept = [p for p in vobs if np.isfinite(p.pos).all()
                and (p.pos[:, :2].max(axis=0) - p.pos[:, :2].min(axis=0)).max() <= MAX_VOB_EXTENT_M]
        if len(kept) < len(vobs):
            warnings.append(f"pominięto {len(vobs) - len(kept)} części vobów jako tło lub błędną geometrię "
                            f"(szersze niż {MAX_VOB_EXTENT_M:g} m albo z NaN)")
        kept, water = _water(kept)
        if water:
            warnings.append(f"woda: {water} części vobów wody pominięto (pomocnicze) lub namalowano jednolitym kolorem")
        parts += kept
    grid = make_grid(bbox, gsd, anchor["lon"], anchor["lat"])
    check_size(grid.width, grid.height, bbox_given=bbox_given)
    out = out or pkg / "ortho" / f"{pkg.name}_{gsd * 100:g}cm.tif"

    texels = [t for t in (texel_size_cm(p) for p in parts) if t is not None]
    if texels and gsd * 100 < statistics.median(texels) * 0.5:
        warnings.append(f"gsd {gsd * 100:g} cm jest drobniejsze niż mediana tekstur ({statistics.median(texels):.1f} cm "
                        "na teksel): obraz będzie rozmyty, bez nowych szczegółów")

    done = [0]
    total = -(-grid.height // 512) * -(-grid.width // 512)

    def render_tile(row0: int, col0: int, rows: int, cols: int) -> np.ndarray:
        done[0] += 1
        if done[0] % max(1, total // 20) == 0:
            print(f"  {100 * done[0] // total}%", file=sys.stderr, flush=True)
        return render_block(parts, grid.e0 + col0 * gsd, grid.n1 - row0 * gsd, gsd, cols, rows)

    write_geotiff(out, grid, render_tile)
    info = {"crs": "EPSG:4326", "bbox_enu_m": list(bbox), "gsd": gsd, "width": grid.width, "height": grid.height,
            "anchor": anchor, "lon_min": grid.lon_min, "lat_max": grid.lat_max, "dx_deg": grid.dx_deg,
            "dy_deg": grid.dy_deg, "include_vobs": include_vobs, "file": out.name,
            "texel_cm_min": min(texels) if texels else None,
            "texel_cm_median": statistics.median(texels) if texels else None,
            "texel_cm_max": max(texels) if texels else None, "warnings": warnings}
    out.with_suffix(".json").write_text(json.dumps(info, indent=2, ensure_ascii=False), "utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.ortho", description="GeoTIFF orthophoto (EPSG:4326) for Cesium ion")
    ap.add_argument("--pkg", required=True, type=Path, help="package folder with world.glb, e.g. dist/g2nk/khorinis")
    ap.add_argument("--gsd", type=float, default=0.25, help="metres per pixel (default 0.25)")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("E0", "N0", "E1", "N1"),
                    help="area in ENU metres from the anchor (game X/100, Z/100); default: whole world")
    ap.add_argument("--include-vobs", action="store_true", help="also draw vobs.glb (trees, props)")
    ap.add_argument("--out", type=Path, help="output .tif (default: <pkg>/ortho/<slug>_<gsd>cm.tif)")
    args = ap.parse_args(argv)
    try:
        info = build_ortho(args.pkg, args.gsd, tuple(args.bbox) if args.bbox else None, args.include_vobs, args.out)
    except ValueError as e:
        print(f"Błąd: {e}", file=sys.stderr)
        return 2
    print(f"{info['file']}: {info["width"]}x{info["height"]} px, gsd {info['gsd']} m")
    for w in info["warnings"]:
        print(f"UWAGA: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
