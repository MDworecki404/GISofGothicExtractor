"""Top-down (orthographic) rasteriser: the highest surface wins, colour comes from the texture or material colour.

Pixel (r, c) of a block has its centre at E = e0 + (c + 0.5) * gsd, N = n1 - (r + 0.5) * gsd. Triangles are
rasterised vectorised in buckets of equal bounding-box size; fragments are merged into a depth buffer.
"""
import numpy as np

from .glbmesh import Part, texel_size_cm

_EPS = 1e-9
_CHUNK_PIXELS = 1 << 21  # fragments evaluated at once


def _bounds(part: Part) -> np.ndarray:
    if part.bounds is None:
        e, n = part.pos[part.tri, 0], part.pos[part.tri, 1]
        part.bounds = np.column_stack([e.min(axis=1), n.min(axis=1), e.max(axis=1), n.max(axis=1)])
    return part.bounds


def _mip_for(part: Part, gsd: float) -> np.ndarray:
    """Texture level whose texel is about one pixel wide on the ground, so coarse pixels average instead of alias."""
    if part.mips is None:
        part.mips = [part.texture]
        part.texel_cm = texel_size_cm(part)
    level = 0
    if part.texel_cm:
        level = max(0, int(np.floor(np.log2(gsd * 100 / part.texel_cm))))
    while len(part.mips) <= level:
        prev = part.mips[-1]
        h, w = prev.shape[0] // 2 * 2, prev.shape[1] // 2 * 2
        if h < 2 or w < 2:
            break
        q = prev[:h, :w].astype(np.float32).reshape(h // 2, 2, w // 2, 2, 4).mean(axis=(1, 3))
        part.mips.append(np.round(q).astype(np.uint8))
    return part.mips[min(level, len(part.mips) - 1)]


def _sample(texture: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w = texture.shape[:2]
    u, v = uv[:, 0] % 1.0, uv[:, 1] % 1.0
    return texture[np.minimum((v * h).astype(np.int64), h - 1), np.minimum((u * w).astype(np.int64), w - 1)]


def _draw_part(part: Part, e0: float, n1: float, gsd: float, width: int, height: int,
               rgba: np.ndarray, depth: np.ndarray) -> None:
    if len(part.tri) == 0:
        return
    eps = _EPS * gsd
    bounds = _bounds(part)
    e_max, n_min = e0 + width * gsd, n1 - height * gsd
    near = np.flatnonzero((bounds[:, 2] >= e0 - gsd) & (bounds[:, 0] <= e_max + gsd)
                          & (bounds[:, 3] >= n_min - gsd) & (bounds[:, 1] <= n1 + gsd))
    if len(near) == 0:
        return
    tri = part.tri[near]
    px = (part.pos[tri, 0] - e0) / gsd - 0.5  # (k, 3) pixel-space x, y of the three corners
    py = (n1 - part.pos[tri, 1]) / gsd - 0.5
    pz = part.pos[tri, 2]
    det = (py[:, 1] - py[:, 2]) * (px[:, 0] - px[:, 2]) + (px[:, 2] - px[:, 1]) * (py[:, 0] - py[:, 2])
    ix0 = np.maximum(np.ceil(px.min(axis=1) - eps), 0).astype(np.int64)
    ix1 = np.minimum(np.floor(px.max(axis=1) + eps), width - 1).astype(np.int64)
    iy0 = np.maximum(np.ceil(py.min(axis=1) - eps), 0).astype(np.int64)
    iy1 = np.minimum(np.floor(py.max(axis=1) + eps), height - 1).astype(np.int64)
    keep = (np.abs(det) > 1e-12) & (ix0 <= ix1) & (iy0 <= iy1)
    if not keep.any():
        return
    sel = np.flatnonzero(keep)
    tri_idx = tri[sel]
    px, py, pz, det = px[sel], py[sel], pz[sel], det[sel]
    ix0, iy0 = ix0[sel], iy0[sel]
    bw, bh = ix1[sel] - ix0 + 1, iy1[sel] - iy0 + 1
    kw, kh = 1 << np.ceil(np.log2(bw)).astype(np.int64), 1 << np.ceil(np.log2(bh)).astype(np.int64)
    key = kw * 65536 + kh
    uv = part.uv
    mip = _mip_for(part, gsd) if part.texture is not None else None
    for k in np.unique(key):
        group = np.flatnonzero(key == k)
        gw, gh = int(k // 65536), int(k % 65536)
        step = max(1, _CHUNK_PIXELS // (gw * gh))
        oy, ox = np.divmod(np.arange(gw * gh), gw)
        for s in range(0, len(group), step):
            g = group[s:s + step]
            X = (ix0[g][:, None] + ox).astype(np.float64)  # (k, gw*gh)
            Y = (iy0[g][:, None] + oy).astype(np.float64)
            x0, x1, x2 = px[g, 0][:, None], px[g, 1][:, None], px[g, 2][:, None]
            y0, y1, y2 = py[g, 0][:, None], py[g, 1][:, None], py[g, 2][:, None]
            d = det[g][:, None]
            w0 = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / d
            w1 = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / d
            w2 = 1.0 - w0 - w1
            tol = -1e-9
            inside = (w0 >= tol) & (w1 >= tol) & (w2 >= tol) & (X < ix0[g][:, None] + bw[g][:, None]) \
                & (Y < iy0[g][:, None] + bh[g][:, None])
            ti, fi = np.nonzero(inside)
            if len(ti) == 0:
                continue
            a, b, c = w0[ti, fi], w1[ti, fi], w2[ti, fi]
            z = a * pz[g][ti, 0] + b * pz[g][ti, 1] + c * pz[g][ti, 2]
            pix = (Y[ti, fi].astype(np.int64) * width + X[ti, fi].astype(np.int64))
            tv = tri_idx[g][ti]
            if part.texture is not None:
                t_uv = a[:, None] * uv[tv[:, 0]] + b[:, None] * uv[tv[:, 1]] + c[:, None] * uv[tv[:, 2]]
                color = _sample(mip, t_uv)
                opaque = color[:, 3] >= 128
                pix, z, color = pix[opaque], z[opaque], color[opaque]
                color = color.copy()
                color[:, 3] = 255
            else:
                color = np.empty((len(pix), 4), np.uint8)
                color[:, :3] = np.round(np.array(part.color) * 255)
                color[:, 3] = 255
            if len(pix) == 0:
                continue
            order = np.lexsort((z, pix))  # per pixel, the last fragment is the highest
            pix, z, color = pix[order], z[order], color[order]
            last = np.append(pix[1:] != pix[:-1], True)
            pix, z, color = pix[last], z[last], color[last]
            win = z > depth[pix]
            depth[pix[win]] = z[win]
            rgba[pix[win]] = color[win]


def render_block(parts: list[Part], e0: float, n1: float, gsd: float, width: int, height: int) -> np.ndarray:
    rgba = np.zeros((height * width, 4), np.uint8)
    depth = np.full(height * width, -np.inf)
    for part in parts:
        _draw_part(part, e0, n1, gsd, width, height, rgba, depth)
    return rgba.reshape(height, width, 4)
