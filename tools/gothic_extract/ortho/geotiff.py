"""Streaming writer of a tiled RGBA GeoTIFF in EPSG:4326 (Deflate), one tile rendered at a time."""
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import tifffile

from .georef import Grid

# GeoKeyDirectory: header (version 1.1.0, 3 keys), GTModelType = geographic, GTRasterType = PixelIsArea, EPSG 4326
_GEO_KEYS = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326)


def _tiles(grid: Grid, render_tile: Callable[[int, int, int, int], np.ndarray], tile: int) -> Iterator[np.ndarray]:
    for row0 in range(0, grid.height, tile):
        for col0 in range(0, grid.width, tile):
            rows, cols = min(tile, grid.height - row0), min(tile, grid.width - col0)
            data = render_tile(row0, col0, rows, cols)
            if data.shape[:2] != (tile, tile):  # edge tiles are padded to the full tile size
                padded = np.zeros((tile, tile, 4), np.uint8)
                padded[:rows, :cols] = data
                data = padded
            yield data


def write_geotiff(path: Path, grid: Grid, render_tile: Callable[[int, int, int, int], np.ndarray],
                  tile: int = 512) -> None:
    """render_tile(row0, col0, rows, cols) -> (rows, cols, 4) uint8; called once per tile, in row order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    extratags = [
        (33550, "d", 3, (grid.dx_deg, grid.dy_deg, 0.0), True),
        (33922, "d", 6, (0.0, 0.0, 0.0, grid.lon_min, grid.lat_max, 0.0), True),
        (34735, "H", len(_GEO_KEYS), _GEO_KEYS, True),
    ]
    bigtiff = grid.width * grid.height * 4 > 3_500_000_000  # classic TIFF where it fits: safest for importers
    with tifffile.TiffWriter(path, bigtiff=bigtiff) as tw:
        tw.write(_tiles(grid, render_tile, tile), shape=(grid.height, grid.width, 4), dtype="uint8", tile=(tile, tile),
                 photometric="rgb", extrasamples=["unassalpha"], compression="deflate", extratags=extratags)
