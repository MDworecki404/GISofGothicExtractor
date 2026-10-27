"""Gothic 3 animated meshes (.xact: EMotion FX actor "FXA ", exported from 3ds Max) in their rest pose.

Used for chests, doors, grindstones, bows and crossbows (eCVisualAnimation_PS -> <name>.FXA -> <name>.xact).
The actor is a list of chunks after b"FXA " + 2 version bytes: u32 id, u32 size, u32 version, body.
Rest-pose meshes are enough for a static map (checked: chests placed with the entity's world matrix sit in the
boxes the game stores), so nodes, skinning and motions are not read.

Chunks used (layout found on the game's files, 2026-10-27; all 379 actors read to the end of every mesh chunk):
- 6 (version 5) standard material, in order (material index 0, 1, …);
- 7 (version 4) material layer: u8 type (1 = diffuse), u8, u16 material index, …, u32 length + texture name
  at the end of the chunk;
- 3 (version 3) mesh: u32 node, u32 original vertices, u32 vertices, u32 indices, u32 submeshes, u32 uv sets,
  u32; then per submesh: u32 (lowest byte = material index), u32 a, u32 n vertices, u32 bones,
  n × (3 f32 position, 3 f32 normal, uv sets × 2 f32, u32 original vertex), (a - 1) u32 of which the first two are
  not triangle indices and the remaining a - 3 are a triangle list (counter-clockwise; reversed here to match the
  clockwise .xcmsh convention). Sums of vertices and of `a` equal the mesh header.
"""
import struct

import numpy as np

from .genome import FormatError
from .mesh import MeshElement

DIFFUSE = 1


def _chunks(data: bytes):
    i = data.find(b"FXA ")
    if i < 0:
        raise FormatError("not an EMotion FX actor (no FXA)")
    r = i + 6
    while r + 12 <= len(data):
        cid, size, ver = struct.unpack_from("<III", data, r)
        if r + 12 + size > len(data):
            break
        yield cid, ver, data[r + 12:r + 12 + size]
        r += 12 + size


def _trailing_string(body: bytes) -> str | None:
    for k in range(len(body) - 4, -1, -1):
        n = struct.unpack_from("<I", body, k)[0]
        if k + 4 + n == len(body) and 0 < n < 260:
            return body[k + 4:].decode("latin-1")
    return None


def _mesh(body: bytes, textures: dict[int, str]) -> list[MeshElement]:
    _node, _org, total_v, total_i, subs, uv_sets, _ = struct.unpack_from("<7I", body, 0)
    stride = 28 + 8 * uv_sets
    q, sum_v, sum_i, out = 28, 0, 0, []
    for _ in range(subs):
        head, a, n, _bones = struct.unpack_from("<4I", body, q)
        q += 16
        verts = np.frombuffer(body[q:q + n * stride], dtype=np.float32).reshape(n, stride // 4)
        q += n * stride
        tris = np.frombuffer(body[q + 8:q + 4 * (a - 1)], dtype=np.uint32).reshape(-1, 3)
        q += 4 * (a - 1)
        if len(tris) and tris.max() >= n:
            raise FormatError("actor triangle index outside its submesh")
        sum_v, sum_i = sum_v + n, sum_i + a
        material = textures.get(head & 0xFF)
        out.append(MeshElement(material or "", verts[:, 0:3].copy(), verts[:, 3:6].copy(), verts[:, 6:8].copy(),
                               tris[:, ::-1].reshape(-1).copy()))
    if q != len(body) or sum_v != total_v or sum_i != total_i:
        raise FormatError("actor mesh chunk not read to its end")
    return out


def read_xact(data: bytes) -> list[MeshElement]:
    """Rest-pose mesh elements of an actor; material = '<diffuse texture>.ximg' (empty when the actor has none)."""
    textures: dict[int, str] = {}
    meshes = []
    for cid, ver, body in _chunks(data):
        if cid == 7 and ver == 4 and body[0] == DIFFUSE:
            name = _trailing_string(body)
            index = struct.unpack_from("<H", body, 2)[0]
            if name:
                textures.setdefault(index, name + ".ximg")
        elif cid == 3 and ver == 3:
            meshes.append(body)
    return [el for body in meshes for el in _mesh(body, textures)]
