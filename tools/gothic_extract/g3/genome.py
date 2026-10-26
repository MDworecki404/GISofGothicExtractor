"""GENOMFLE files and Genome property objects.

File: b"GENOMFLE", u16 1, u32 offset of the string table, body. String table: u32 0xDEADBEEF, u8 1, u32 n,
n × (u16 length, latin-1 bytes). Strings in the body are u16 indexes into this table.

The body starts with an 8-byte tag (b"GENOMEDL" in .lrentdat, b"GENOMETP" in .tple). In .tple the tag is
followed by u16 62, u16 1, u8 1, u32 n and n strings: u16 indexes into the end table (GENOMFLE files) or,
in templates saved without the GENOMFLE header (enclaves, navigation, VFX…), inline strings (u16 length +
bytes). In the inline variant this list is the string table of the file. `GenomeFile.body` points past it.

Property object (bCAccessorPropertyObject): u16 1, u8 present; when present: u16 1, u8 1, u16 class (string),
u16 1, u8 0, u16 class version, u16 class version, u32 size (from the next byte to the end of the object),
u16 30, u32 property count, properties (u16 name, u16 type, u16 30, u32 size, data), then the class's own data
up to the end of the object. Objects of class version 1 (old templates and meshes) have the object's name
(a string) and a GUID (16 bytes + u32) before the u16 30.
"""
import struct
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

MAGIC = b"GENOMFLE"
STRINGS_MARK = 0xDEADBEEF
PROP_VERSION = 30


class FormatError(Exception):
    pass


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data, self.pos = data, pos

    def _unpack(self, fmt: str, size: int):
        if self.pos + size > len(self.data):
            raise FormatError(f"read past end at {self.pos}")
        v = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return v

    def string(self, strings: list[str] | None) -> str:
        """A string reference: u16 index into `strings`, or (strings None: files saved without the GENOMFLE
        header) an inline string, u16 length + latin-1 bytes."""
        if strings is None:
            return self.take(self.u16()).decode("latin-1")
        return strings[self.u16()]

    def u16_at(self, pos: int) -> int | None:
        return struct.unpack_from("<H", self.data, pos)[0] if pos + 2 <= len(self.data) else None

    def u8(self) -> int:
        return self._unpack("<B", 1)[0]

    def u16(self) -> int:
        return self._unpack("<H", 2)[0]

    def i16(self) -> int:
        return self._unpack("<h", 2)[0]

    def u32(self) -> int:
        return self._unpack("<I", 4)[0]

    def i32(self) -> int:
        return self._unpack("<i", 4)[0]

    def f32(self) -> float:
        return self._unpack("<f", 4)[0]

    def vec3(self) -> tuple[float, float, float]:
        return self._unpack("<3f", 12)

    def floats(self, n: int) -> list[float]:
        return list(self._unpack(f"<{n}f", 4 * n))

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise FormatError(f"read of {n} bytes past end at {self.pos}")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def guid(self) -> str | None:
        """bCGuid: 16 bytes + u8 valid + 3 bytes padding."""
        raw = self.take(20)
        return guid_str(raw[:16]) if raw[16] else None

    def expect(self, value: int, size: int, what: str) -> None:
        at = self.pos
        got = {1: self.u8, 2: self.u16, 4: self.u32}[size]()
        if got != value:
            raise FormatError(f"{what}: expected {value}, got {got} at {at}")


def guid_str(raw16: bytes) -> str:
    return "{" + str(uuid.UUID(bytes_le=bytes(raw16))) + "}"


TEMPLATE_TAG = b"GENOMETP"


@dataclass
class GenomeFile:
    data: bytes
    strings: list[str]
    body: int  # first byte after the file header (and, in .tple, after the template string list)


def _template_list(r: Reader, inline: bool) -> list:
    r.expect(62, 2, "template version")
    r.expect(1, 2, "template flag")
    r.expect(1, 1, "template flag")
    return [r.take(r.u16()).decode("latin-1") if inline else r.u16() for _ in range(r.u32())]


def parse_genomfle(data: bytes) -> GenomeFile:
    if data[:8] == TEMPLATE_TAG:
        r = Reader(data, 8)
        strings = _template_list(r, inline=True)
        return GenomeFile(data, strings, r.pos)
    if data[:8] != MAGIC:
        raise FormatError("not a GENOMFLE file")
    r = Reader(data, 8)
    r.expect(1, 2, "GENOMFLE version")
    table = r.u32()
    body = r.pos
    if data[body:body + 8] == TEMPLATE_TAG:
        r.pos = body + 8
        _template_list(r, inline=False)
        body = r.pos
    r.pos = table
    r.expect(STRINGS_MARK, 4, "string table mark")
    r.expect(1, 1, "string table version")
    strings = []
    for _ in range(r.u32()):
        strings.append(r.take(r.u16()).decode("latin-1"))
    return GenomeFile(data, strings, body)


@dataclass
class Prop:
    name: str
    type: str
    raw: bytes
    value: object


@dataclass
class PropertyObject:
    cls: str
    class_version: int
    props: dict[str, Prop]
    data_start: int
    data_end: int


def decode_value(type_name: str, raw: bytes, strings: list[str] | None) -> object:
    n = len(raw)
    if strings is None and "String" in type_name and n >= 2 and n == 2 + struct.unpack_from("<H", raw)[0]:
        return raw[2:].decode("latin-1")
    if type_name in ("bool", "char") and n == 1:
        return raw[0]
    if type_name == "short" and n == 2:
        return struct.unpack("<h", raw)[0]
    if type_name in ("int", "long") and n == 4:
        return struct.unpack("<i", raw)[0]
    if type_name == "float" and n == 4:
        return struct.unpack("<f", raw)[0]
    if "String" in type_name and n == 2:
        return strings[struct.unpack("<H", raw)[0]]
    if type_name == "bCVector" and n == 12:
        return struct.unpack("<3f", raw)
    if type_name == "bCGuid" and n == 20:
        return guid_str(raw[:16]) if raw[16] else None
    if type_name.startswith("bTPropertyContainer<enum") and n == 6:
        return struct.unpack("<I", raw[2:6])[0]
    if type_name in ("eCTemplateEntityProxy", "eCEntityProxy"):
        return _proxy_guid(raw)
    if type_name == "bCPropertyID" and n == 20:
        return _property_id(raw)
    if type_name == "bTValArray<class bCPropertyID>" and n >= 5:
        count = struct.unpack_from("<I", raw, 1)[0]
        return [_property_id(raw[5 + 20 * i:25 + 20 * i]) for i in range(count)] if n == 5 + 20 * count else raw
    if type_name == "bTObjArray<class bCString>" and n >= 5:
        count = struct.unpack_from("<I", raw, 1)[0]
        return [strings[i] for i in struct.unpack_from(f"<{count}H", raw, 5)] if n == 5 + 2 * count else raw
    return raw


def _property_id(raw: bytes) -> str | None:
    """bCPropertyID: 16-byte GUID + u32 (always 0 in the data); all-zero GUID = not set."""
    return guid_str(raw[:16]) if any(raw[:16]) else None


def _proxy_guid(raw: bytes) -> str | None:
    """Entity proxy: u16 version, u8 has-guid, then a bCPropertyID (16-byte GUID + u32 0) when set."""
    if len(raw) >= 23 and raw[2] and any(raw[3:19]):
        return guid_str(raw[3:19])
    return None


def read_property_object(r: Reader, strings: list[str] | None) -> PropertyObject | None:
    """strings None: the file has no GENOMFLE string table and names every string inline."""
    r.expect(1, 2, "accessor version")
    if not r.u8():
        return None
    r.expect(1, 2, "object version")
    r.expect(1, 1, "persistable")
    cls = r.string(strings)
    r.expect(1, 2, "object flag")
    r.expect(0, 1, "object flag")
    class_version = r.u16()
    r.u16()
    size = r.u32()
    end = r.pos + size
    if class_version == 1:
        # old objects (templates and meshes saved without GENOMFLE, …): object name + GUID (16 bytes + u32)
        r.string(strings)
        r.take(20)
    r.expect(PROP_VERSION, 2, f"{cls} property version")
    props: dict[str, Prop] = {}
    for _ in range(r.u32()):
        name = r.string(strings)
        type_name = r.string(strings)
        r.expect(PROP_VERSION, 2, f"{cls}.{name} version")
        raw = r.take(r.u32())
        props[name] = Prop(name, type_name, raw, decode_value(type_name, raw, strings))
    if r.pos > end:
        raise FormatError(f"{cls}: properties overrun the object ({r.pos} > {end})")
    obj = PropertyObject(cls, class_version, props, r.pos, end)
    r.pos = end
    return obj


_OBJ_HEAD = b"\x01\x00\x01\x01\x00\x01"


def iter_property_objects(gf: GenomeFile) -> Iterator[PropertyObject]:
    """Scan the body for property set objects (class name ending in _PS). For exploration and tests only:
    the entity reader (entities.py) walks the real structure."""
    data, i = gf.data, gf.body
    while (i := data.find(_OBJ_HEAD, i)) != -1:
        cls_idx = struct.unpack_from("<H", data, i + 6)[0] if i + 8 <= len(data) else None
        if cls_idx is not None and cls_idx < len(gf.strings) and gf.strings[cls_idx].endswith("_PS"):
            try:
                r = Reader(data, i)
                obj = read_property_object(r, gf.strings)
            except (FormatError, IndexError):
                obj = None
            if obj is not None:
                yield obj
                i = obj.data_end
                continue
        i += 1
