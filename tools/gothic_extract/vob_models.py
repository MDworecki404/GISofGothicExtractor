"""Export static VOB and item models (.3DS → compiled .MRM) as instanced glTF.

One .glb per visual. Every placement of that visual goes into the file as an
EXT_mesh_gpu_instancing instance, in the same frame as world.glb:
glTF = (x/100, y/100, -z/100) of game coordinates.
"""
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pygltflib as gl
import zenkit

from .catalog import ItemDef
from .mesh_export import Blob, load_png
from .records import ItemRec, Vec3, WorldData

INSTANCING = "EXT_mesh_gpu_instancing"
_FLIP = np.diag([1.0, 1.0, -1.0])
_SKIP_TYPES = {"zCVobLevelCompo"}  # parts of the static world mesh, already in world.glb


@dataclass
class ModelsReport:
    models: int = 0
    instances: int = 0
    missing: list[str] = field(default_factory=list)


def _quat_from_matrix(m: np.ndarray) -> tuple[float, float, float, float]:
    """Rotation matrix → unit quaternion (x, y, z, w)."""
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q)
    return tuple(float(v) for v in q)


def _orthonormal(m: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    return r


def game_instance(pos: Vec3, rot: list[float]) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """Game placement (cm, row-major 3x3) → glTF instance (translation in m, quaternion xyzw)."""
    r = _orthonormal(np.array(rot, dtype=float).reshape(3, 3))
    m = _FLIP @ r @ _FLIP
    t = (_FLIP @ np.array(pos, dtype=float)) / 100.0
    return tuple(float(v) for v in t), _quat_from_matrix(m)


def mrm_to_glb(mrm: zenkit.MultiResolutionMesh, vfs: zenkit.Vfs, placements: list[tuple[Vec3, list[float]]],
               out_path: Path, tex_cache: dict | None = None) -> int:
    """Write one instanced .glb for an MRM; returns the triangle count of one copy."""
    tex_cache = {} if tex_cache is None else tex_cache
    positions = np.array([(p.x, p.y, p.z) for p in mrm.positions], dtype=np.float64) / 100.0
    positions[:, 2] *= -1

    blob = Blob()
    accessors: list[gl.Accessor] = []
    materials, images, textures, primitives = [], [], [], []
    image_idx: dict[str, tuple[int, bool] | None] = {}
    triangles = 0

    def accessor(arr, kind, comp, target=None, minmax=False):
        view = blob.add(np.ascontiguousarray(arr).tobytes(), target)
        acc = gl.Accessor(bufferView=view, componentType=comp, count=len(arr), type=kind)
        if minmax:
            acc.min, acc.max = arr.min(axis=0).tolist(), arr.max(axis=0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    for sm in mrm.submeshes:
        wedges = sm.wedges
        tris = np.array([tuple(t.wedges) for t in sm.triangles], dtype=np.uint32)
        if len(tris) == 0 or len(wedges) == 0:
            continue
        triangles += len(tris)
        widx = np.array([w.index for w in wedges], dtype=np.int64)
        uv = np.array([(w.texture.x, w.texture.y) for w in wedges], dtype=np.float32)
        nrm = np.array([(w.normal.x, w.normal.y, -w.normal.z) for w in wedges], dtype=np.float32)
        pos = positions[widx].astype(np.float32)
        attrs = gl.Attributes(
            POSITION=accessor(pos, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER, minmax=True),
            NORMAL=accessor(nrm, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER),
            TEXCOORD_0=accessor(uv, gl.VEC2, gl.FLOAT, gl.ARRAY_BUFFER),
        )
        idx = accessor(tris.reshape(-1), gl.SCALAR, gl.UNSIGNED_INT, gl.ELEMENT_ARRAY_BUFFER)

        mat = sm.material
        tex_name = (mat.texture or "").upper()
        if tex_name not in image_idx:
            if tex_name not in tex_cache:
                tex_cache[tex_name] = load_png(vfs, tex_name)
            loaded = tex_cache[tex_name]
            if loaded is None:
                image_idx[tex_name] = None
            else:
                png, has_alpha = loaded
                images.append(gl.Image(bufferView=blob.add(png), mimeType="image/png", name=tex_name))
                textures.append(gl.Texture(source=len(images) - 1, sampler=0))
                image_idx[tex_name] = (len(textures) - 1, has_alpha)
        tex = image_idx[tex_name]
        pbr = gl.PbrMetallicRoughness(metallicFactor=0.0, roughnessFactor=1.0)
        gm = gl.Material(name=mat.name, pbrMetallicRoughness=pbr)
        if tex is None:
            c = mat.color
            pbr.baseColorFactor = [c.r / 255, c.g / 255, c.b / 255, 1.0]
        else:
            pbr.baseColorTexture = gl.TextureInfo(index=tex[0])
            if mat.alpha_function == zenkit.AlphaFunction.BLEND:
                gm.alphaMode, gm.doubleSided = gl.BLEND, True
            elif tex[1] or mrm.alpha_test:
                gm.alphaMode, gm.alphaCutoff, gm.doubleSided = gl.MASK, 0.5, True
        materials.append(gm)
        primitives.append(gl.Primitive(attributes=attrs, indices=idx, material=len(materials) - 1))

    inst = [game_instance(p, r) for p, r in placements]
    t_acc = accessor(np.array([t for t, _ in inst], dtype=np.float32), gl.VEC3, gl.FLOAT)
    r_acc = accessor(np.array([q for _, q in inst], dtype=np.float32), gl.VEC4, gl.FLOAT)

    data = blob.bytes()
    gltf = gl.GLTF2(
        asset=gl.Asset(generator="gothic_extract", version="2.0"),
        extensionsUsed=[INSTANCING],
        scene=0,
        scenes=[gl.Scene(nodes=[0])],
        nodes=[gl.Node(mesh=0, name=out_path.stem,
                       extensions={INSTANCING: {"attributes": {"TRANSLATION": t_acc, "ROTATION": r_acc}}})],
        meshes=[gl.Mesh(primitives=primitives, name=out_path.stem)],
        accessors=accessors,
        bufferViews=blob.views,
        buffers=[gl.Buffer(byteLength=len(data))],
        materials=materials,
        images=images,
        textures=textures,
        samplers=[gl.Sampler(magFilter=gl.LINEAR, minFilter=gl.LINEAR_MIPMAP_LINEAR, wrapS=gl.REPEAT, wrapT=gl.REPEAT)],
    )
    gltf.set_binary_blob(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(out_path))
    return triangles


_IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def collect_placements(wd: WorldData, catalog: dict[str, ItemDef], script_items: list[ItemRec]):
    """visual (upper-case .3DS name) → (kind, [(pos, rot)])."""
    out: dict[str, tuple[str, list]] = {}
    groups: dict[str, list] = defaultdict(list)
    kinds: dict[str, str] = {}
    for v in wd.vobs:
        vis = (v.visual or "").upper()
        if not vis.endswith(".3DS") or not v.show_visual or v.vob_type in _SKIP_TYPES:
            continue
        groups[vis].append((v.pos, v.rot))
        kinds.setdefault(vis, "vob")
    # item VOBs store no visual in the ZEN (the engine takes it from the script instance)
    rot_by_vob = {v.id: v.rot for v in wd.vobs}
    for i in wd.items + script_items:
        d = catalog.get(i.code)
        vis = (d.visual if d else "").upper()
        if not vis.endswith(".3DS") or i.pos is None:
            continue
        # script items sit on freepoints, which carry no usable orientation for items
        groups[vis].append((i.pos, rot_by_vob.get(i.vob_id, _IDENTITY) if i.vob_id else _IDENTITY))
        kinds.setdefault(vis, "item")
    for vis, places in groups.items():
        out[vis] = (kinds[vis], places)
    return out


def export_vob_models(vfs: zenkit.Vfs, wd: WorldData, catalog: dict[str, ItemDef], script_items: list[ItemRec],
                      out_dir: Path) -> ModelsReport:
    report = ModelsReport()
    entries = []
    tex_cache: dict = {}
    for vis, (kind, places) in sorted(collect_placements(wd, catalog, script_items).items()):
        node = vfs.find(vis[: -len(".3DS")] + ".MRM")
        if node is None:
            report.missing.append(vis)
            continue
        mrm = zenkit.MultiResolutionMesh.load(node.open())
        fname = vis[: -len(".3DS")].lower() + ".glb"
        tris = mrm_to_glb(mrm, vfs, places, out_dir / fname, tex_cache)
        entries.append({"visual": vis, "file": fname, "kind": kind, "instances": len(places), "triangles": tris})
        report.models += 1
        report.instances += len(places)
    (out_dir / "index.json").write_text(json.dumps(
        {"frame": "same as world.glb: (x/100, y/100, -z/100) of game coordinates", "extension": INSTANCING,
         "models": entries, "missing": report.missing}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
