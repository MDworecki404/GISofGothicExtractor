"""Entity trees of Gothic 3 world sectors (.lrentdat, version 83) and templates (.tple, version 62).

Layout: docs/formats/g3-entity.md. Entities are stored flat; the hierarchy is a list of (parent, child)
index pairs after them, ended by (0xFFFFFFFF, 0xFFFFFFFF).
"""
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from .genome import FormatError, GenomeFile, PropertyObject, Reader, parse_genomfle, read_property_object

PS_MARK = 0xDEADC0DE
NO_INDEX = 0xFFFFFFFF
Vec3 = tuple[float, float, float]


@dataclass
class Entity:
    name: str
    guid: str | None
    creator: str | None  # GUID of the template the entity was made from
    world: list[float]
    local: list[float]
    pos: Vec3
    props: dict[str, PropertyObject] = field(default_factory=dict)
    children: list["Entity"] = field(default_factory=list)
    box: tuple[Vec3, Vec3] | None = None  # world bounding box (min, max) the game stores for the entity


def to_world(m: list[float], points: np.ndarray) -> np.ndarray:
    """Entity-local points (n, 3) -> world, with the entity's world matrix (row vectors: p @ R + t)."""
    mat = np.asarray(m, dtype=np.float64).reshape(4, 4)
    return np.asarray(points, dtype=np.float64) @ mat[:3, :3] + mat[3, :3]


def _box(r: Reader) -> tuple[Vec3, Vec3] | None:
    lo, hi = r.vec3(), r.vec3()
    return (lo, hi) if all(a <= b for a, b in zip(lo, hi)) else None


def translation(m: list[float]) -> Vec3:
    return (m[12], m[13], m[14])


def walk(entities: list[Entity]) -> Iterator[Entity]:
    stack = list(reversed(entities))
    while stack:
        e = stack.pop()
        yield e
        stack.extend(reversed(e.children))


def _property_id(r: Reader) -> str | None:
    from .genome import guid_str

    raw = r.take(20)
    return guid_str(raw[:16]) if any(raw[:16]) else None


def _property_sets(r: Reader, strings: list[str], sized: bool, where: str) -> dict[str, PropertyObject]:
    props: dict[str, PropertyObject] = {}
    for _ in range(r.u32()):
        r.u16()
        if sized:
            size = r.u32()
            r.u16()  # per-class version (2, 17 …)
            start = r.pos
        obj = read_property_object(r, strings)
        if sized and r.pos != start + size:
            raise FormatError(f"{where}: property set size {size}, read {r.pos - start}")
        r.expect(PS_MARK, 4, f"{where}: property set end mark")
        if obj is not None:
            props.setdefault(obj.cls, obj)
    return props


def _world_entity(r: Reader, strings: list[str]) -> Entity:
    at = r.pos
    r.expect(0x40, 2, f"entity at {at}")
    r.expect(0x53, 2, f"entity at {at}")
    creator = _property_id(r) if r.u8() else None
    r.expect(0x53, 2, f"entity at {at}")
    r.expect(1, 2, f"entity at {at}")
    guid = _property_id(r)
    r.take(7 + 4 + 4)
    r.expect(0, 2, f"entity at {at}")
    name = strings[r.u16()]
    world, local = r.floats(16), r.floats(16)
    box = _box(r)
    r.take(2 * 24 + 2 * 16 + 19)
    props = _property_sets(r, strings, sized=False, where=f"{name} at {at}")
    return Entity(name, guid, creator, world, local, translation(world), props, box=box)


NODE_RECORD = 89  # spatial tree record before every entity of a .node file (not needed here)


def _static_entity(r: Reader, strings: list[str]) -> Entity:
    """Entity of a .node file (static geometry): the spatial part of a world entity, without the creator."""
    at = r.pos
    r.expect(0x53, 2, f"static entity at {at}")
    r.expect(1, 2, f"static entity at {at}")
    guid = _property_id(r)
    r.take(7 + 4 + 4 + 2)
    name = strings[r.u16()]
    world, local = r.floats(16), r.floats(16)
    box = _box(r)
    r.take(2 * 24 + 2 * 16 + 19)
    props = _property_sets(r, strings, sized=False, where=f"{name} at {at}")
    return Entity(name, guid, None, world, local, translation(world), props, box=box)


def read_node_file(data: bytes) -> list[Entity]:
    """Top-level entities of a .node file (static meshes, SpeedTrees, lights of a sector or world cell):
    u16 0x53, u32 n, n × (89-byte spatial record, entity), then the hierarchy pairs."""
    gf = parse_genomfle(data)
    r = Reader(data, gf.body)
    r.expect(0x53, 2, "node file version")
    flat = []
    for _ in range(r.u32()):
        r.take(NODE_RECORD)
        flat.append(_static_entity(r, gf.strings))
    roots = _hierarchy(r, flat)
    end = struct.unpack_from("<I", data, 10)[0]
    if r.pos != end:
        raise FormatError(f"node file ends at {end}, read to {r.pos}")
    return roots


def _template_entity(r: Reader, strings: list[str]) -> Entity:
    at = r.pos
    r.expect(0x3E, 2, f"template entity at {at}")
    r.expect(0, 2, f"template entity at {at}")
    guid = _property_id(r)
    r.take(8)
    creator = _property_id(r) if r.u8() else None
    r.take(4 + 1)
    r.expect(0, 2, f"template entity at {at}")
    name = strings[r.u16()]
    world, local = r.floats(16), r.floats(16)
    r.take(3 * 24 + 21)
    props = _property_sets(r, strings, sized=True, where=f"{name} at {at}")
    return Entity(name, guid, creator, world, local, translation(world), props)


def _hierarchy(r: Reader, flat: list[Entity]) -> list[Entity]:
    has_parent = set()
    while True:
        parent, child = r.u32(), r.u32()
        if parent == NO_INDEX and child == NO_INDEX:
            break
        if parent >= len(flat) or child >= len(flat):
            raise FormatError(f"hierarchy pair ({parent}, {child}) outside {len(flat)} entities")
        flat[parent].children.append(flat[child])
        has_parent.add(child)
    return [e for i, e in enumerate(flat) if i not in has_parent]


def read_entity_file(data: bytes) -> tuple[list[Entity], tuple[Vec3, Vec3]]:
    """Top-level entities of a .lrentdat sector and its ContextBox (min, max)."""
    gf = parse_genomfle(data)
    r = Reader(data, gf.body)
    if r.take(8) != b"GENOMEDL":
        raise FormatError("not an entity file (no GENOMEDL)")
    r.expect(0x53, 2, "GENOMEDL version")
    ctx = read_property_object(r, gf.strings)
    if ctx is None or ctx.cls != "eCEntityDynamicContext":
        raise FormatError("no eCEntityDynamicContext")
    box = ctx.props["ContextBox"].raw
    lo = Reader(box).vec3()
    hi = Reader(box, 12).vec3()
    r.pos = ctx.data_start
    r.expect(0x53, 2, "context version")
    r.take(1 + 4 + 4 + 24)
    flat = [_world_entity(r, gf.strings) for _ in range(r.u32())]
    roots = _hierarchy(r, flat)
    if r.pos != ctx.data_end:
        raise FormatError(f"entity context ends at {ctx.data_end}, read to {r.pos}")
    return roots, (lo, hi)


def read_template(data: bytes) -> Entity:
    """The template of a .tple file: entity 0 (its GUID is the template's GUID) with the property sets of the
    entities below it merged in (the first occurrence of a class wins)."""
    gf: GenomeFile = parse_genomfle(data)
    r = Reader(data, gf.body)
    size = r.u32()
    end = r.pos + size
    flat = [_template_entity(r, gf.strings) for _ in range(r.u32())]
    roots = _hierarchy(r, flat)
    if r.pos != end:
        raise FormatError(f"template ends at {end}, read to {r.pos}")
    if not roots:
        raise FormatError("template without entities")
    t = roots[0]
    for e in walk(t.children):
        for cls, obj in e.props.items():
            t.props.setdefault(cls, obj)
    return t
