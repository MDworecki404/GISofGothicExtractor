"""Gothic 3 terrain -> world.glb (metres, Y-up, embedded PNG textures), like the G1/G2 world mesh.

The landscape meshes (G3_<region>_Landscape_*/…/*.xcmsh) are already in world coordinates (checked: every NPC
stands over a cell, inside its height range), so they are merged as they are, one primitive per material.
Axes as in mesh_export: glTF = (x/100, y/100, -z/100); the mirror keeps G3's clockwise front faces
counter-clockwise for glTF, so indices keep their order. Terrain materials blend several layers in the game;
glTF gets the diffuse texture of each material, scaled down to max_texture pixels.
"""
from collections import defaultdict
from pathlib import Path

import numpy as np
import pygltflib as gl

from ..mesh_export import Blob, MeshStats
from .archive import G3Fs
from .genome import FormatError
from .image import apply_alpha_mode, material_info, ximg_to_png
from .mesh import read_xcmsh

REGIONS = ("Myrtana", "Varant", "Nordmar")


def landscape_meshes(fs: G3Fs) -> list[str]:
    """Terrain meshes of every region (cells and landscape locations), without the low-poly horizon."""
    return [p for p in fs.list(suffix=".xcmsh")
            if p.split("/")[0].startswith(tuple(f"G3_{r}_Landscape" for r in REGIONS))]


def _texture(fs: G3Fs, material: str, max_texture: int):
    """(MaterialInfo | None, (PNG bytes, has_alpha) | None) of a terrain material."""
    info = material_info(fs.find_name(material))
    data = fs.find_name(info.texture) if info and info.texture else None
    if data is None:
        return info, None
    try:
        return info, ximg_to_png(data, max_texture, info.alpha_mode != "OPAQUE")
    except FormatError:
        return info, None


def export_terrain_glb(fs: G3Fs, paths: list[str], out_path: Path, max_texture: int = 512) -> MeshStats:
    parts: dict[str, list] = defaultdict(list)
    for p in paths:
        for el in read_xcmsh(fs.find(p)):
            parts[el.material].append(el)

    stats = MeshStats()
    blob = Blob()
    accessors: list[gl.Accessor] = []
    materials: list[gl.Material] = []
    images: list[gl.Image] = []
    textures: list[gl.Texture] = []
    primitives: list[gl.Primitive] = []
    bb_min, bb_max = np.full(3, np.inf), np.full(3, -np.inf)

    def accessor(arr: np.ndarray, kind: str, comp: int, target: int, minmax: bool = False) -> int:
        acc = gl.Accessor(bufferView=blob.add(arr.tobytes(), target), componentType=comp, count=len(arr), type=kind)
        if minmax:
            acc.min, acc.max = arr.min(axis=0).tolist(), arr.max(axis=0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    for material in sorted(parts):
        els = parts[material]
        pos, nrm, uv, idx, base = [], [], [], [], 0
        for el in els:
            n = len(el.positions)
            pos.append(el.positions)
            nrm.append(el.normals if el.normals is not None else np.tile([0.0, 1.0, 0.0], (n, 1)).astype(np.float32))
            uv.append(el.uvs if el.uvs is not None else np.zeros((n, 2), np.float32))
            idx.append(el.indices.astype(np.uint32) + base)
            base += n
        positions = np.vstack(pos).astype(np.float32) / 100.0
        positions[:, 2] *= -1
        normals = np.vstack(nrm).astype(np.float32).copy()
        normals[:, 2] *= -1
        indices = np.concatenate(idx).astype(np.uint32)
        stats.triangles += len(indices) // 3
        bb_min, bb_max = np.minimum(bb_min, positions.min(axis=0)), np.maximum(bb_max, positions.max(axis=0))
        attrs = gl.Attributes(
            POSITION=accessor(positions, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER, minmax=True),
            NORMAL=accessor(normals, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER),
            TEXCOORD_0=accessor(np.vstack(uv).astype(np.float32), gl.VEC2, gl.FLOAT, gl.ARRAY_BUFFER),
        )
        pbr = gl.PbrMetallicRoughness(metallicFactor=0.0, roughnessFactor=1.0)
        mat = gl.Material(name=material, pbrMetallicRoughness=pbr)
        info, tex = _texture(fs, material, max_texture)
        if tex is None:
            pbr.baseColorFactor = [0.5, 0.5, 0.5, 1.0]
            stats.textures_missing.append(material)
        else:
            png, has_alpha = tex
            images.append(gl.Image(bufferView=blob.add(png), mimeType="image/png", name=material))
            textures.append(gl.Texture(source=len(images) - 1, sampler=0))
            pbr.baseColorTexture = gl.TextureInfo(index=len(textures) - 1)
            stats.textures_ok += 1
            apply_alpha_mode(mat, info, has_alpha)
        materials.append(mat)
        primitives.append(gl.Primitive(attributes=attrs, material=len(materials) - 1,
                                       indices=accessor(indices, gl.SCALAR, gl.UNSIGNED_INT, gl.ELEMENT_ARRAY_BUFFER)))

    stats.materials = len(primitives)
    stats.bbox_min = tuple(float(v) for v in bb_min)
    stats.bbox_max = tuple(float(v) for v in bb_max)
    data = blob.bytes()
    gltf = gl.GLTF2(
        asset=gl.Asset(generator="gothic_extract", version="2.0"),
        scene=0, scenes=[gl.Scene(nodes=[0])], nodes=[gl.Node(mesh=0, name="world")],
        meshes=[gl.Mesh(primitives=primitives, name="world")], accessors=accessors, bufferViews=blob.views,
        buffers=[gl.Buffer(byteLength=len(data))], materials=materials, images=images, textures=textures,
        samplers=[gl.Sampler(magFilter=gl.LINEAR, minFilter=gl.LINEAR_MIPMAP_LINEAR, wrapS=gl.REPEAT, wrapT=gl.REPEAT)],
    )
    gltf.set_binary_blob(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(out_path))
    return stats
