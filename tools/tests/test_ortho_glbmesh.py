import io

import numpy as np
import pygltflib as gl
import pytest
from PIL import Image

from gothic_extract.ortho.glbmesh import load_parts, texel_size_cm

QUAD = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32)  # glTF xyz, lying flat
QUAD_UV = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
QUAD_IDX = np.array([0, 1, 2, 0, 2, 3], np.uint32)


def make_glb(path, pos=QUAD, uv=QUAD_UV, idx=QUAD_IDX, texture=None, color=None, translation=None):
    """One-mesh glb; texture is an (h, w, 4) uint8 array."""
    chunks, views, accessors = [], [], []

    def add(data: bytes, target=None) -> int:
        offset = sum(len(c) for c in chunks)
        pad = (-offset) % 4
        chunks.append(b"\0" * pad)
        chunks.append(data)
        views.append(gl.BufferView(buffer=0, byteOffset=offset + pad, byteLength=len(data), target=target))
        return len(views) - 1

    def acc(arr, kind, comp):
        accessors.append(gl.Accessor(bufferView=add(arr.tobytes()), componentType=comp, count=len(arr), type=kind))
        return len(accessors) - 1

    attrs = gl.Attributes(POSITION=acc(pos, gl.VEC3, gl.FLOAT), TEXCOORD_0=acc(uv, gl.VEC2, gl.FLOAT))
    pbr = gl.PbrMetallicRoughness()
    images, textures = [], []
    if texture is not None:
        buf = io.BytesIO()
        Image.fromarray(texture).save(buf, format="PNG")
        images.append(gl.Image(bufferView=add(buf.getvalue()), mimeType="image/png"))
        textures.append(gl.Texture(source=0))
        pbr.baseColorTexture = gl.TextureInfo(index=0)
    if color is not None:
        pbr.baseColorFactor = list(color) + [1.0]
    prim = gl.Primitive(attributes=attrs, indices=acc(idx, gl.SCALAR, gl.UNSIGNED_INT), material=0)
    data = b"".join(chunks)
    g = gl.GLTF2(scene=0, scenes=[gl.Scene(nodes=[0])], nodes=[gl.Node(mesh=0, translation=translation)],
                 meshes=[gl.Mesh(primitives=[prim])], accessors=accessors, bufferViews=views,
                 buffers=[gl.Buffer(byteLength=len(data))], materials=[gl.Material(pbrMetallicRoughness=pbr)],
                 images=images, textures=textures)
    g.set_binary_blob(data)
    g.save_binary(str(path))
    return path


def test_axes_conversion(tmp_path):
    pos = np.array([[1, 2, -3], [2, 2, -3], [1, 2, -2]], np.float32)
    parts = load_parts(make_glb(tmp_path / "a.glb", pos=pos, uv=QUAD_UV[:3], idx=np.array([0, 1, 2], np.uint32)))
    assert parts[0].pos[0].tolist() == [1, 3, 2]  # E = x, N = -z, Up = y


def test_node_transform_applied(tmp_path):
    parts = load_parts(make_glb(tmp_path / "a.glb", translation=[10, 0, 0]))
    assert parts[0].pos[:, 0].min() == pytest.approx(10)


def test_untextured_material_uses_color(tmp_path):
    p = load_parts(make_glb(tmp_path / "a.glb", color=(1, 0, 0)))[0]
    assert p.texture is None and p.color == (1, 0, 0)


def test_texture_decoded(tmp_path):
    tex = np.zeros((4, 8, 4), np.uint8)
    tex[..., 0] = 200
    tex[..., 3] = 255
    p = load_parts(make_glb(tmp_path / "a.glb", texture=tex))[0]
    assert p.texture.shape == (4, 8, 4) and p.texture[0, 0, 0] == 200


def test_texel_size_cm(tmp_path):
    tex = np.full((100, 100, 4), 255, np.uint8)
    p = load_parts(make_glb(tmp_path / "a.glb", texture=tex))[0]
    assert texel_size_cm(p) == pytest.approx(1.0)
    assert texel_size_cm(load_parts(make_glb(tmp_path / "b.glb"))[0]) is None
