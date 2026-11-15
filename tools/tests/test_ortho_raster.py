import numpy as np

from gothic_extract.ortho.glbmesh import Part
from gothic_extract.ortho.raster import render_block


def quad(e0, n0, e1, n1, up, uv=None, texture=None, color=(1.0, 0.0, 0.0)):
    pos = np.array([[e0, n0, up], [e1, n0, up], [e1, n1, up], [e0, n1, up]], float)
    if uv is None:
        uv = np.zeros((4, 2), np.float32)
    return Part(pos, np.asarray(uv, np.float32), np.array([[0, 1, 2], [0, 2, 3]]), texture, color)


def uv_by_position(e0, n0, e1, n1, scale_e, scale_n):
    return [[e0 / scale_e, n0 / scale_n], [e1 / scale_e, n0 / scale_n], [e1 / scale_e, n1 / scale_n],
            [e0 / scale_e, n1 / scale_n]]


def test_flat_quad_fills_expected_pixels():
    out = render_block([quad(0, 2, 2, 4, 0)], e0=0, n1=4, gsd=1.0, width=4, height=4)
    assert out.shape == (4, 4, 4) and out.dtype == np.uint8
    assert (out[:2, :2] == [255, 0, 0, 255]).all()
    assert (out[2:, :, 3] == 0).all() and (out[:, 2:, 3] == 0).all()


def test_highest_wins_in_both_orders():
    low, high = quad(0, 0, 2, 2, 1, color=(0, 0, 1)), quad(0, 0, 2, 2, 5, color=(1, 0, 0))
    for parts in ([low, high], [high, low]):
        out = render_block(parts, 0, 2, 1.0, 2, 2)
        assert (out[..., :3] == [255, 0, 0]).all()


def test_texture_sampled_by_uv():
    tex = np.array([[[10, 0, 0, 255], [20, 0, 0, 255]], [[30, 0, 0, 255], [40, 0, 0, 255]]], np.uint8)
    q = quad(0, 0, 2, 2, 0, uv=uv_by_position(0, 0, 2, 2, 2, 2), texture=tex)
    out = render_block([q], 0, 2, 1.0, 2, 2)
    # v grows with N; row 0 is the northern row
    assert out[0, 0, 0] == 30 and out[0, 1, 0] == 40 and out[1, 0, 0] == 10 and out[1, 1, 0] == 20


def test_uv_wraps():
    tex = np.array([[[10, 0, 0, 255], [20, 0, 0, 255]]], np.uint8)
    q = quad(0, 0, 4, 1, 0, uv=uv_by_position(0, 0, 4, 1, 2, 1), texture=tex)
    out = render_block([q], 0, 1, 1.0, 4, 1)
    assert out[0, :, 0].tolist() == [10, 20, 10, 20]


def test_masked_alpha_shows_lower_geometry():
    tex = np.zeros((1, 2, 4), np.uint8)
    tex[0, 1] = [0, 255, 0, 255]  # left half transparent, right half green
    top = quad(0, 0, 2, 2, 5, uv=uv_by_position(0, 0, 2, 2, 2, 2), texture=tex)
    out = render_block([quad(0, 0, 2, 2, 1), top], 0, 2, 1.0, 2, 2)
    assert (out[:, 0, :3] == [255, 0, 0]).all() and (out[:, 1, :3] == [0, 255, 0]).all()


def test_untextured_uses_color():
    out = render_block([quad(0, 0, 1, 1, 0, color=(0.0, 0.5, 1.0))], 0, 1, 1.0, 1, 1)
    assert out[0, 0].tolist() == [0, 128, 255, 255]


def test_degenerate_and_vertical_triangles_ignored():
    wall = Part(np.array([[0, 0, 0], [2, 0, 0], [2, 0, 5]], float), np.zeros((3, 2), np.float32),
                np.array([[0, 1, 2]]), None, (1.0, 1.0, 1.0))
    line = Part(np.array([[0, 0, 0], [1, 1, 0], [2, 2, 0]], float), np.zeros((3, 2), np.float32),
                np.array([[0, 1, 2]]), None, (1.0, 1.0, 1.0))
    out = render_block([wall, line], 0, 2, 1.0, 2, 2)
    assert (out == 0).all()


def test_block_outside_parts_is_transparent():
    out = render_block([quad(100, 100, 102, 102, 0)], 0, 2, 1.0, 2, 2)
    assert (out == 0).all()
    assert render_block([], 0, 2, 1.0, 2, 2).shape == (2, 2, 4)


def test_coarse_pixels_use_mipmap_instead_of_aliasing():
    checker = np.zeros((8, 8, 4), np.uint8)
    checker[..., 3] = 255
    checker[::2, ::2, :3] = 255
    checker[1::2, 1::2, :3] = 255
    q = quad(0, 0, 8, 8, 0, uv=uv_by_position(0, 0, 8, 8, 8, 8), texture=checker)  # 1 m texels
    out = render_block([q], 0, 8, 4.0, 2, 2)  # 4 m pixels
    assert np.abs(out[..., :3].astype(int) - 127).max() <= 1


def test_non_finite_uv_does_not_crash_and_draws_nothing():
    tex = np.full((2, 2, 4), 255, np.uint8)
    bad = np.full((4, 2), np.nan, np.float32)
    out = render_block([quad(0, 0, 2, 2, 0, uv=bad, texture=tex)], 0, 2, 1.0, 2, 2)
    assert (out == 0).all()
