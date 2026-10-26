"""Gothic 3 materials (.xshmat) and compiled images (.ximg) -> PNG.

.xshmat: eCResourceShaderMaterial_PS whose shader holds colour samplers (eCColorSrcSampler) with ImageFilePath
(a .tga path from the editor; the game loads <name>.ximg). The diffuse sampler is the texture for glTF.
.ximg: GENOMFLE + "G3IMG", u16 version, u16, u32 width, u32 height, …, a pixel format (DXT1/DXT3/DXT5),
u32 1, u32 size of all mip levels, u32 0, then the mip levels, largest first. The largest level is wrapped in a
DDS header and decoded by Pillow.
"""
import io
import struct

from PIL import Image

from .genome import FormatError, Reader, parse_genomfle, read_property_object

_OBJ_HEAD = b"\x01\x00\x01\x01\x00\x01"
_BLOCK = {b"DXT1": 8, b"DXT3": 16, b"DXT5": 16}


def _strings(data: bytes) -> tuple[list[str] | None, int]:
    if data.startswith(b"GENOMFLE"):
        gf = parse_genomfle(data)
        return gf.strings, gf.body
    return None, 0


def material_texture(data: bytes | None) -> str | None:
    """File name (.ximg) of the material's diffuse texture, or None."""
    if not data:
        return None
    strings, i = _strings(data)
    paths = []
    while (j := data.find(_OBJ_HEAD, i)) != -1:
        try:
            obj = read_property_object(Reader(data, j), strings)
        except (FormatError, IndexError, UnicodeDecodeError):
            i = j + 1
            continue
        if obj is not None and "ImageFilePath" in obj.props and isinstance(obj.props["ImageFilePath"].value, str):
            if obj.props["ImageFilePath"].value:
                paths.append(obj.props["ImageFilePath"].value)
        i = j + 1  # samplers sit inside the shader object: keep scanning inside it
    if not paths:
        return None
    path = next((p for p in paths if "diffuse" in p.lower()), paths[0])
    name = path.replace("\\", "/").split("/")[-1]
    return name.rsplit(".", 1)[0] + ".ximg"


def _dds(width: int, height: int, fourcc: bytes, top: bytes) -> bytes:
    pixel_format = struct.pack("<II4s5I", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    header = struct.pack("<7I44s", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, height, width, len(top), 0, 1, b"\0" * 44)
    return b"DDS " + header + pixel_format + struct.pack("<5I", 0x1000, 0, 0, 0, 0) + top


def ximg_to_png(data: bytes, max_size: int = 512) -> tuple[bytes, bool]:
    """(PNG bytes, has transparent pixels) of the largest mip level, scaled down to max_size."""
    g = data.find(b"G3IMG")
    if g < 0:
        raise FormatError("not a G3IMG image")
    width, height = struct.unpack_from("<II", data, g + 9)
    f = min((k for k in (data.find(fc, g, g + 96) for fc in _BLOCK) if k >= 0), default=-1)
    if f < 0:
        raise FormatError(f"unsupported image format near {data[g:g + 64]!r}")
    fourcc = data[f:f + 4]
    blocks = max(1, (width + 3) // 4) * max(1, (height + 3) // 4)
    start = f + 16
    top = data[start:start + blocks * _BLOCK[fourcc]]
    img = Image.open(io.BytesIO(_dds(width, height, fourcc, top)))
    img.load()
    img = img.convert("RGBA")
    has_alpha = img.getextrema()[3][0] < 255
    if not has_alpha:
        img = img.convert("RGB")
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), has_alpha
