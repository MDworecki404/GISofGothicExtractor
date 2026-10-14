"""Export the static world mesh to binary glTF (metres, Y-up, embedded PNG textures).

Axis convention: glTF = (x/100, y/100, -z/100). Negating Z turns Gothic's
left-handed frame into glTF's right-handed one; that mirror also turns Gothic's
clockwise front faces into glTF's counter-clockwise ones, so indices keep their order.
In ENU terms a glTF point is (East, Up, -North).
"""
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pygltflib as gl
import zenkit
from PIL import Image

from .records import Vec3

_SKIP_PREFIXES = ("GHOSTOCCLUDER",)


@dataclass
class MeshStats:
    triangles: int = 0
    materials: int = 0
    textures_ok: int = 0
    textures_missing: list[str] = field(default_factory=list)
    bbox_min: Vec3 = (0.0, 0.0, 0.0)
    bbox_max: Vec3 = (0.0, 0.0, 0.0)


def _compiled_texture_name(tga: str) -> str:
    stem = tga.rsplit(".", 1)[0]
    return f"{stem}-C.TEX"


def _load_png(vfs: zenkit.Vfs, tga: str) -> tuple[bytes, bool] | None:
    """Returns (png bytes, has transparent pixels) or None when the texture is missing."""
    if not tga:
        return None
    node = vfs.find(_compiled_texture_name(tga))
    if node is None:
        return None
    tex = zenkit.Texture.load(node.open())
    w, h = tex.width_mipmap(0), tex.height_mipmap(0)
    rgba = np.frombuffer(tex.mipmap_rgba(0), dtype=np.uint8).reshape(h, w, 4)
    has_alpha = bool((rgba[:, :, 3] < 255).any())
    buf = io.BytesIO()
    Image.fromarray(rgba if has_alpha else rgba[:, :, :3]).save(buf, format="PNG", optimize=False)
    return buf.getvalue(), has_alpha


class _Blob:
    def __init__(self):
        self.parts: list[bytes] = []
        self.size = 0
        self.views: list[gl.BufferView] = []

    def add(self, data: bytes, target: int | None = None) -> int:
        pad = (-self.size) % 4
        if pad:
            self.parts.append(b"\0" * pad)
            self.size += pad
        self.views.append(gl.BufferView(buffer=0, byteOffset=self.size, byteLength=len(data), target=target))
        self.parts.append(data)
        self.size += len(data)
        return len(self.views) - 1

    def bytes(self) -> bytes:
        return b"".join(self.parts)


def _triangulate(mesh) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fan-triangulate polygons → (pos idx (n,3), feature idx (n,3), material idx (n,))."""
    mats = mesh.materials
    skip_mat = {i for i, m in enumerate(mats) if m.name.upper().startswith(_SKIP_PREFIXES)}
    P, F, M = [], [], []
    for poly in mesh.polygons:
        if poly.is_portal or poly.is_lod or poly.material_index in skip_mat:
            continue
        pi, fi = poly.position_indices, poly.feature_indices
        for k in range(1, len(pi) - 1):
            P.append((pi[0], pi[k], pi[k + 1]))
            F.append((fi[0], fi[k], fi[k + 1]))
            M.append(poly.material_index)
    return np.asarray(P, dtype=np.int64), np.asarray(F, dtype=np.int64), np.asarray(M, dtype=np.int64)


def export_world_glb(world: zenkit.World, vfs: zenkit.Vfs, out_path: Path) -> MeshStats:
    mesh = world.mesh
    positions = np.array([(p.x, p.y, p.z) for p in mesh.positions], dtype=np.float64)
    feats = mesh.features
    uvs = np.array([(f.texture.x, f.texture.y) for f in feats], dtype=np.float32)
    normals = np.array([(f.normal.x, f.normal.y, f.normal.z) for f in feats], dtype=np.float32)
    materials = mesh.materials

    # Gothic → glTF axes and units
    positions = positions / 100.0
    positions[:, 2] *= -1
    normals[:, 2] *= -1

    P, F, M = _triangulate(mesh)

    stats = MeshStats(triangles=int(len(P)))
    blob = _Blob()
    accessors: list[gl.Accessor] = []
    gl_materials: list[gl.Material] = []
    images: list[gl.Image] = []
    textures: list[gl.Texture] = []
    image_by_tex: dict[str, tuple[int, bool] | None] = {}
    primitives: list[gl.Primitive] = []
    bb_min = np.full(3, np.inf)
    bb_max = np.full(3, -np.inf)

    def accessor(arr: np.ndarray, kind: str, comp: int, target: int, minmax: bool = False) -> int:
        view = blob.add(arr.tobytes(), target)
        acc = gl.Accessor(bufferView=view, componentType=comp, count=len(arr), type=kind)
        if minmax:
            acc.min = arr.min(axis=0).tolist()
            acc.max = arr.max(axis=0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    for mi in np.unique(M):
        sel = M == mi
        keys = P[sel].ravel() * len(feats) + F[sel].ravel()
        uniq, inverse = np.unique(keys, return_inverse=True)
        vp, vf = uniq // len(feats), uniq % len(feats)
        pos = positions[vp].astype(np.float32)
        bb_min = np.minimum(bb_min, pos.min(axis=0))
        bb_max = np.maximum(bb_max, pos.max(axis=0))
        attrs = gl.Attributes(
            POSITION=accessor(pos, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER, minmax=True),
            NORMAL=accessor(normals[vf], gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER),
            TEXCOORD_0=accessor(uvs[vf], gl.VEC2, gl.FLOAT, gl.ARRAY_BUFFER),
        )
        idx = accessor(inverse.astype(np.uint32), gl.SCALAR, gl.UNSIGNED_INT, gl.ELEMENT_ARRAY_BUFFER)

        mat = materials[int(mi)]
        tex_name = (mat.texture or "").upper()
        if tex_name not in image_by_tex:
            loaded = _load_png(vfs, tex_name)
            if loaded is None:
                image_by_tex[tex_name] = None
            else:
                png, has_alpha = loaded
                images.append(gl.Image(bufferView=blob.add(png), mimeType="image/png", name=tex_name))
                textures.append(gl.Texture(source=len(images) - 1, sampler=0))
                image_by_tex[tex_name] = (len(textures) - 1, has_alpha)
        tex = image_by_tex[tex_name]
        c = mat.color
        pbr = gl.PbrMetallicRoughness(metallicFactor=0.0, roughnessFactor=1.0)
        gm = gl.Material(name=mat.name, pbrMetallicRoughness=pbr)
        if tex is None:
            pbr.baseColorFactor = [c.r / 255, c.g / 255, c.b / 255, 1.0]
            stats.textures_missing.append(tex_name or f"<none:{mat.name}>")
        else:
            pbr.baseColorTexture = gl.TextureInfo(index=tex[0])
            stats.textures_ok += 1
            if mat.alpha_function == zenkit.AlphaFunction.BLEND:
                gm.alphaMode, gm.doubleSided = gl.BLEND, True
            elif tex[1]:
                gm.alphaMode, gm.alphaCutoff, gm.doubleSided = gl.MASK, 0.5, True
        gl_materials.append(gm)
        primitives.append(gl.Primitive(attributes=attrs, indices=idx, material=len(gl_materials) - 1))

    stats.materials = len(primitives)
    stats.bbox_min = tuple(float(v) for v in bb_min)
    stats.bbox_max = tuple(float(v) for v in bb_max)

    data = blob.bytes()
    gltf = gl.GLTF2(
        asset=gl.Asset(generator="gothic_extract", version="2.0"),
        scene=0,
        scenes=[gl.Scene(nodes=[0])],
        nodes=[gl.Node(mesh=0, name="world")],
        meshes=[gl.Mesh(primitives=primitives, name="world")],
        accessors=accessors,
        bufferViews=blob.views,
        buffers=[gl.Buffer(byteLength=len(data))],
        materials=gl_materials,
        images=images,
        textures=textures,
        samplers=[gl.Sampler(magFilter=gl.LINEAR, minFilter=gl.LINEAR_MIPMAP_LINEAR, wrapS=gl.REPEAT, wrapT=gl.REPEAT)],
    )
    gltf.set_binary_blob(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(out_path))
    return stats
