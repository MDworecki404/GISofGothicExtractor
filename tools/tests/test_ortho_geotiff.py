import numpy as np
import pytest
import tifffile

from gothic_extract.ortho.georef import make_grid
from gothic_extract.ortho.geotiff import write_geotiff


def pattern(row0, col0, rows, cols):
    r, c = np.mgrid[row0:row0 + rows, col0:col0 + cols]
    return np.stack([r % 256, c % 256, (r + c) % 256, np.full_like(r, 255)], axis=-1).astype(np.uint8)


def test_roundtrip_pixels_and_tags(tmp_path):
    grid = make_grid((0, 0, 70, 30), 0.1, 0.0, 0.0)  # 700 x 300 px
    path = tmp_path / "o.tif"
    write_geotiff(path, grid, pattern)
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        assert (page.imagewidth, page.imagelength, page.samplesperpixel) == (700, 300, 4)
        assert page.is_tiled and page.tilewidth == 512 and page.tilelength == 512
        assert page.dtype == np.uint8
        scale = page.tags[33550].value
        tie = page.tags[33922].value
        keys = page.tags[34735].value
        data = page.asarray()
    assert (data == pattern(0, 0, 300, 700)).all()
    assert scale[:2] == pytest.approx((grid.dx_deg, grid.dy_deg))
    assert tie[3:5] == pytest.approx((grid.lon_min, grid.lat_max))
    assert tuple(keys[-4:]) == (2048, 0, 1, 4326)


def test_render_tile_called_per_tile_with_bounded_size(tmp_path):
    grid = make_grid((0, 0, 70, 30), 0.1, 0.0, 0.0)
    calls = []

    def render(row0, col0, rows, cols):
        calls.append((row0, col0, rows, cols))
        return pattern(row0, col0, rows, cols)

    write_geotiff(tmp_path / "o.tif", grid, render)
    assert len(calls) == 2  # 700 x 300 px -> 2 x 1 tiles of 512
    assert all(rows <= 512 and cols <= 512 for _, _, rows, cols in calls)
    assert calls[1] == (0, 512, 300, 188)
