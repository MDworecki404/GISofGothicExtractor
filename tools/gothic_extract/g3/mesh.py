"""Gothic 3 compiled meshes (.xcmsh): eCResourceMeshComplex_PS with one element per material.

An element starts with its material (a .xshmat name: u16 string index, or an inline string in files without the
GENOMFLE header) and u32 n, followed by n vertex streams: u32 type, u16 1, u8 1, u32 count, count × element.
Stream types and element sizes (checked on the landscape and low-poly meshes, 2026-10-26):
0 indices (u32, triangle list), 1 positions (3 × f32, world centimetres for terrain), 3 tangents (3 × f32),
4 and 5 colours (u32), 12 texture coordinates (2 × f32), 15, 18, 21 and 73 further coordinate sets (2 × f32),
64 normals (3 × f32). Between elements there is per-element data that is not needed here; elements are found
by their header and every stream is checked (version bytes, known type, inside the object).
"""
import struct
from dataclasses import dataclass

import numpy as np

from .genome import FormatError, Reader, parse_genomfle, read_property_object

STREAM_SIZE = {0: 4, 1: 12, 3: 12, 4: 4, 5: 4, 12: 8, 15: 8, 18: 8, 21: 8, 64: 12, 73: 8}
INDICES, POSITIONS, UVS, NORMALS = 0, 1, 12, 64
_MAX_STREAMS = 32


@dataclass
class MeshElement:
    material: str
    positions: np.ndarray  # (n, 3) float32, game units
    normals: np.ndarray | None  # (n, 3) float32
    uvs: np.ndarray | None  # (n, 2) float32
    indices: np.ndarray  # (3 m,) uint32


def _material(data: bytes, i: int, strings: list[str] | None) -> tuple[str, int] | None:
    if i + 2 > len(data):
        return None
    k = struct.unpack_from("<H", data, i)[0]
    if strings is not None:
        name = strings[k] if k < len(strings) else ""
        return (name, i + 2) if name.lower().endswith(".xshmat") else None
    raw = data[i + 2:i + 2 + k]
    if 7 < k < 260 and raw.lower().endswith(b".xshmat"):
        return raw.decode("latin-1"), i + 2 + k
    return None


def _element(data: bytes, i: int, end: int, strings: list[str] | None) -> tuple[MeshElement, int] | None:
    mat = _material(data, i, strings)
    if mat is None or mat[1] + 4 > end:
        return None
    material, r = mat
    n = struct.unpack_from("<I", data, r)[0]
    if not 0 < n <= _MAX_STREAMS:
        return None
    r += 4
    streams: dict[int, np.ndarray] = {}
    for _ in range(n):
        if r + 11 > end:
            return None
        t, version, flag, count = struct.unpack_from("<IHBI", data, r)
        size = STREAM_SIZE.get(t)
        if version != 1 or flag != 1 or size is None or r + 11 + size * count > end:
            return None
        if t not in streams:
            raw = data[r + 11:r + 11 + size * count]
            streams[t] = np.frombuffer(raw, dtype=np.uint32 if t in (0, 4, 5) else np.float32)
        r += 11 + size * count
    if POSITIONS not in streams or INDICES not in streams:
        return None
    pos = streams[POSITIONS].reshape(-1, 3)
    idx = streams[INDICES]
    if len(idx) % 3 or (len(idx) and idx.max() >= len(pos)):
        return None
    normals = streams[NORMALS].reshape(-1, 3) if NORMALS in streams else None
    uvs = streams[UVS].reshape(-1, 2) if UVS in streams else None
    if normals is not None and len(normals) != len(pos):
        normals = None
    if uvs is not None and len(uvs) != len(pos):
        uvs = None
    return MeshElement(material, pos, normals, uvs, idx), r


def read_xcmsh(data: bytes) -> list[MeshElement]:
    if data.startswith(b"GENOMFLE"):
        gf = parse_genomfle(data)
        strings, r = gf.strings, Reader(data, gf.body)
    else:
        strings, r = None, Reader(data, 0)
    obj = read_property_object(r, strings)
    if obj is None or obj.cls != "eCResourceMeshComplex_PS":
        raise FormatError(f"not a complex mesh: {obj.cls if obj else None}")
    elements, i = [], obj.data_start
    while i < obj.data_end - 6:
        found = _element(data, i, obj.data_end, strings)
        if found is None:
            i += 1
            continue
        elements.append(found[0])
        i = found[1]
    if not elements:
        raise FormatError("mesh without elements")
    return elements
