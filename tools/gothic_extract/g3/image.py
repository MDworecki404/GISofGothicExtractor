"""Gothic 3 materials (.xshmat) and compiled images (.ximg) -> PNG.

.xshmat: eCResourceShaderMaterial_PS whose shader holds colour samplers (eCColorSrcSampler) with ImageFilePath
(a .tga path from the editor; the game loads <name>.ximg). The diffuse sampler is the texture for glTF.
.ximg: GENOMFLE + "G3IMG", u16 version, u16, u32 width, u32 height, …, a pixel format (DXT1/DXT3/DXT5),
u32 1, u32 size of all mip levels, u32 0, then the mip levels, **smallest first** (checked on 1024 px textures:
read from the start they show the small levels as strips at the top of a garbled image). The largest level is the
last one; it is wrapped in a DDS header and decoded by Pillow.
"""
import io
import re
import struct
from dataclasses import dataclass

from PIL import Image

from .genome import FormatError, Reader, parse_genomfle, read_property_object

_OBJ_HEAD = b"\x01\x00\x01\x01\x00\x01"
_BLOCK = {b"DXT1": 8, b"DXT3": 16, b"DXT5": 16}


def _strings(data: bytes) -> tuple[list[str] | None, int]:
    if data.startswith(b"GENOMFLE"):
        gf = parse_genomfle(data)
        return gf.strings, gf.body
    return None, 0


_WATER_SHADERS = ("eCShaderRiver", "eCShaderOcean")
WATER_COLOR = (0.16, 0.33, 0.42, 0.7)  # RGBA of water, which the game draws with a shader instead of a colour texture
_ALPHA_MODE = {0: "OPAQUE", 1: "MASK"}  # eCShader*.BlendMode; 2 = alpha blend, 7 = additive (both BLEND)


@dataclass
class MaterialInfo:
    texture: str | None  # .ximg of the diffuse sampler; None for water, whose samplers are normal maps
    shader: str = ""
    blend_mode: int = 0
    mask_reference: int = 0  # alpha-test threshold, 0-255

    @property
    def is_water(self) -> bool:
        return self.shader in _WATER_SHADERS

    @property
    def hidden(self) -> bool:
        """Opaque river/ocean shader: the depth and far-sea helper meshes, never drawn by the game."""
        return self.is_water and self.blend_mode == 0

    @property
    def alpha_mode(self) -> str:
        """glTF alphaMode. In .ximg the alpha channel is often a detail map, so only the shader decides."""
        return _ALPHA_MODE.get(self.blend_mode, "BLEND")


def _objects(data: bytes):
    strings, i = _strings(data)
    while (j := data.find(_OBJ_HEAD, i)) != -1:
        try:
            obj = read_property_object(Reader(data, j), strings)
        except (FormatError, IndexError, UnicodeDecodeError):
            i = j + 1
            continue
        if obj is not None:
            yield obj
        i = j + 1  # samplers sit inside the shader object: keep scanning inside it


def _prop(obj, name: str, kind: type):
    p = obj.props.get(name)
    return p.value if p is not None and isinstance(p.value, kind) else None


def material_info(data: bytes | None) -> MaterialInfo | None:
    """Diffuse texture and blending of an .xshmat (shader: eCShader* with BlendMode and MaskReference)."""
    if not data:
        return None
    info = MaterialInfo(None)
    paths = []
    for obj in _objects(data):
        if obj.cls.startswith("eCShader") and "BlendMode" in obj.props:
            info.shader = obj.cls
            info.blend_mode = int(_prop(obj, "BlendMode", (int, float)) or 0)
            info.mask_reference = int(_prop(obj, "MaskReference", (int, float)) or 0)
        path = _prop(obj, "ImageFilePath", str)
        if path:
            paths.append(path)
    if not paths:  # an older class version the property reader cannot parse: the editor paths are plain text
        paths = [m.decode("latin-1") for m in re.findall(rb"[\w /.-]+\.tga", data, re.I)]
    if paths and not info.is_water:
        path = next((p for p in paths if "diffuse" in p.lower()), paths[0])
        info.texture = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0] + ".ximg"
    return info


def apply_alpha_mode(mat, info: "MaterialInfo | None", has_alpha: bool) -> None:
    """Set a glTF material's alphaMode from its shader; without one (actors name a .ximg) from the image's alpha."""
    mode = info.alpha_mode if info is not None else ("MASK" if has_alpha else "OPAQUE")
    if mode == "MASK":
        cutoff = info.mask_reference / 255 if info is not None and info.mask_reference else 0.5
        mat.alphaMode, mat.alphaCutoff, mat.doubleSided = "MASK", cutoff, True
    elif mode == "BLEND":
        mat.alphaMode, mat.doubleSided = "BLEND", True


def material_texture(data: bytes | None) -> str | None:
    """File name (.ximg) of the material's diffuse texture, or None."""
    info = material_info(data)
    return info.texture if info else None


def _dds(width: int, height: int, fourcc: bytes, top: bytes) -> bytes:
    pixel_format = struct.pack("<II4s5I", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    header = struct.pack("<7I44s", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, height, width, len(top), 0, 1, b"\0" * 44)
    return b"DDS " + header + pixel_format + struct.pack("<5I", 0x1000, 0, 0, 0, 0) + top


def _smaller_levels(width: int, height: int, block_bytes: int) -> int:
    """Bytes of all mip levels below the largest one (each at least one block)."""
    total = 0
    while width > 1 or height > 1:
        width, height = max(1, width // 2), max(1, height // 2)
        total += max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block_bytes
    return total


def ximg_to_png(data: bytes, max_size: int = 512, keep_alpha: bool = True) -> tuple[bytes, bool]:
    """(PNG bytes, PNG has transparent pixels) of the largest mip level, scaled down to max_size.
    keep_alpha=False drops the alpha channel (materials whose shader is opaque)."""
    g = data.find(b"G3IMG")
    if g < 0:
        raise FormatError("not a G3IMG image")
    width, height = struct.unpack_from("<II", data, g + 9)
    f = min((k for k in (data.find(fc, g, g + 96) for fc in _BLOCK) if k >= 0), default=-1)
    if f < 0:
        raise FormatError(f"unsupported image format near {data[g:g + 64]!r}")
    fourcc = data[f:f + 4]
    blocks = max(1, (width + 3) // 4) * max(1, (height + 3) // 4)
    start = f + 16 + _smaller_levels(width, height, _BLOCK[fourcc])  # mip levels are stored smallest first
    top = data[start:start + blocks * _BLOCK[fourcc]]
    if len(top) < blocks * _BLOCK[fourcc]:  # a file too short for that layout: the largest level comes first
        start = f + 16
        top = data[start:start + blocks * _BLOCK[fourcc]]
    img = Image.open(io.BytesIO(_dds(width, height, fourcc, top)))
    img.load()
    img = img.convert("RGBA")
    has_alpha = keep_alpha and img.getextrema()[3][0] < 255
    if not has_alpha:
        img = img.convert("RGB")
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), has_alpha
