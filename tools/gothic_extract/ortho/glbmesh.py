"""Read a geoportal glb into ENU metres (E, N, Up) with decoded textures.

glTF = (E, Up, -N), so a glTF point (x, y, z) becomes (E=x, N=-z, Up=y). Node transforms are applied.
"""
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygltflib as gl
from PIL import Image

_DTYPE = {gl.BYTE: np.int8, gl.UNSIGNED_BYTE: np.uint8, gl.SHORT: np.int16, gl.UNSIGNED_SHORT: np.uint16,
          gl.UNSIGNED_INT: np.uint32, gl.FLOAT: np.float32}
_WIDTH = {gl.SCALAR: 1, gl.VEC2: 2, gl.VEC3: 3, gl.VEC4: 4}


@dataclass
class Part:
    pos: np.ndarray  # (n, 3) float64: E, N, Up in metres
    uv: np.ndarray  # (n, 2) float32
    tri: np.ndarray  # (m, 3) int64
    texture: np.ndarray | None  # (h, w, 4) uint8
    color: tuple[float, float, float]
    name: str = ""
    bounds: np.ndarray | None = None  # (m, 4) cached per-triangle emin, nmin, emax, nmax (see raster)
    mips: list | None = None  # cached mip chain of texture, level 0 first (see raster)
    texel_cm: float | None = None  # cached texel_size_cm


def _read(g: gl.GLTF2, blob: bytes, index: int) -> np.ndarray:
    acc = g.accessors[index]
    view = g.bufferViews[acc.bufferView]
    width = _WIDTH[acc.type]
    dtype = np.dtype(_DTYPE[acc.componentType])
    start = (view.byteOffset or 0) + (acc.byteOffset or 0)
    arr = np.frombuffer(blob, dtype=dtype, count=acc.count * width, offset=start)
    return arr.reshape(acc.count, width) if width > 1 else arr


def _local_matrix(node: gl.Node) -> np.ndarray:
    if node.matrix:
        return np.array(node.matrix, np.float64).reshape(4, 4).T
    m = np.eye(4)
    if node.scale:
        m[:3, :3] = np.diag(node.scale)
    if node.rotation:
        x, y, z, w = node.rotation
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m[:3, :3] = r @ m[:3, :3]
    if node.translation:
        m[:3, 3] = node.translation
    return m


def load_parts(path: Path) -> list[Part]:
    g = gl.GLTF2().load(str(path))
    blob = g.binary_blob()
    images: dict[int, np.ndarray | None] = {}

    def image(index: int) -> np.ndarray | None:
        if index not in images:
            img = g.images[index]
            images[index] = None
            if img.bufferView is not None:
                view = g.bufferViews[img.bufferView]
                raw = blob[view.byteOffset or 0:(view.byteOffset or 0) + view.byteLength]
                images[index] = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))
        return images[index]

    parts: list[Part] = []

    def visit(ni: int, parent: np.ndarray) -> None:
        node = g.nodes[ni]
        world = parent @ _local_matrix(node)
        if node.mesh is not None:
            for prim in g.meshes[node.mesh].primitives:
                pos = _read(g, blob, prim.attributes.POSITION).astype(np.float64)
                pos = pos @ world[:3, :3].T + world[:3, 3]
                enu = np.column_stack([pos[:, 0], -pos[:, 2], pos[:, 1]])
                n = len(enu)
                uv = (_read(g, blob, prim.attributes.TEXCOORD_0).astype(np.float32)
                      if prim.attributes.TEXCOORD_0 is not None else np.zeros((n, 2), np.float32))
                idx = (_read(g, blob, prim.indices).astype(np.int64) if prim.indices is not None
                       else np.arange(n, dtype=np.int64))
                mat = g.materials[prim.material] if prim.material is not None else gl.Material()
                pbr = mat.pbrMetallicRoughness or gl.PbrMetallicRoughness()
                tex = None
                if pbr.baseColorTexture is not None:
                    src = g.textures[pbr.baseColorTexture.index].source
                    tex = image(src) if src is not None else None
                rgb = tuple((pbr.baseColorFactor or [0.5, 0.5, 0.5, 1.0])[:3])
                parts.append(Part(enu, uv, idx[: len(idx) // 3 * 3].reshape(-1, 3), tex, rgb, mat.name or ""))
        for child in node.children or []:
            visit(child, world)

    for ni in g.scenes[g.scene or 0].nodes:
        visit(ni, np.eye(4))
    return parts


def texel_size_cm(part: Part) -> float | None:
    """Median size of one texel on the ground, in cm; None for untextured or degenerate parts."""
    if part.texture is None or len(part.tri) == 0:
        return None
    a, b = part.tri[:, 0], part.tri[:, 1]
    world = np.linalg.norm(part.pos[b] - part.pos[a], axis=1)
    uv = np.linalg.norm(part.uv[b].astype(np.float64) - part.uv[a], axis=1)
    ok = (uv > 1e-9) & (world > 1e-9)
    if not ok.any():
        return None
    return float(np.median(world[ok] / (uv[ok] * part.texture.shape[1])) * 100)
