"""Export static VOB and item models (.3DS → compiled .MRM) as instanced glTF.

One .glb per visual. Every placement of that visual goes into the file as an
EXT_mesh_gpu_instancing instance, in the same frame as world.glb:
glTF = (x/100, y/100, -z/100) of game coordinates.
"""
import json
from collections import Counter, defaultdict
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
# parts of the static world mesh (already in world.glb) and editor-only helpers invisible in game
_SKIP_TYPES = {"zCVobLevelCompo", "zCVobStartpoint", "zCPFXController"}
_SKIP_PREFIXES = ("INVISIBLE_",)


@dataclass
class ModelsReport:
    models: int = 0
    instances: int = 0
    missing: list[str] = field(default_factory=list)
    unhandled: dict[str, int] = field(default_factory=dict)  # visual extension → placements not exported


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


def _gltf_positions(mrm: zenkit.MultiResolutionMesh) -> np.ndarray:
    """MRM vertex positions in the glTF frame: (x/100, y/100, -z/100)."""
    positions = np.array([(p.x, p.y, p.z) for p in mrm.positions], dtype=np.float64) / 100.0
    positions[:, 2] *= -1
    return positions


def _used_bounds(mrm: zenkit.MultiResolutionMesh, positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bounding box of the vertices actually referenced by triangles (MRMs can carry unused LOD vertices)."""
    used = [w.index for sm in mrm.submeshes if len(sm.triangles) for w in sm.wedges]
    pts = positions[np.array(sorted(set(used)), dtype=np.int64)] if used else positions
    return pts.min(axis=0), pts.max(axis=0)


class _GlbBuilder:
    """Accumulates meshes and nodes of one .glb; textures are stored once however many models use them."""

    def __init__(self, out_path: Path, vfs: zenkit.Vfs, tex_cache: dict, texture_dir: str | None,
                 bake: bool = False):
        self.bake = bake  # one plain node per placement instead of EXT_mesh_gpu_instancing (Cesium ion drops it)
        self.out_path, self.vfs, self.tex_cache, self.texture_dir = out_path, vfs, tex_cache, texture_dir
        self.blob = Blob()
        self.accessors: list[gl.Accessor] = []
        self.materials: list[gl.Material] = []
        self.images: list[gl.Image] = []
        self.textures: list[gl.Texture] = []
        self.meshes: list[gl.Mesh] = []
        self.nodes: list[gl.Node] = []
        self.image_idx: dict[str, tuple[int, bool] | None] = {}

    def accessor(self, arr, kind, comp, target=None, minmax=False):
        view = self.blob.add(np.ascontiguousarray(arr).tobytes(), target)
        acc = gl.Accessor(bufferView=view, componentType=comp, count=len(arr), type=kind)
        if minmax:
            acc.min, acc.max = arr.min(axis=0).tolist(), arr.max(axis=0).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def _texture(self, tex_name: str):
        if tex_name not in self.image_idx:
            if tex_name not in self.tex_cache:
                self.tex_cache[tex_name] = load_png(self.vfs, tex_name)
            loaded = self.tex_cache[tex_name]
            if loaded is None:
                self.image_idx[tex_name] = None
            else:
                png, has_alpha = loaded
                if self.texture_dir is None:
                    self.images.append(gl.Image(bufferView=self.blob.add(png), mimeType="image/png", name=tex_name))
                else:
                    uri = f"{self.texture_dir}/{tex_name.rsplit('.', 1)[0].lower()}.png"
                    target = self.out_path.parent / uri
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(png)
                    self.images.append(gl.Image(uri=uri, mimeType="image/png", name=tex_name))
                self.textures.append(gl.Texture(source=len(self.images) - 1, sampler=0))
                self.image_idx[tex_name] = (len(self.textures) - 1, has_alpha)
        return self.image_idx[tex_name]

    def add_model(self, mrm: zenkit.MultiResolutionMesh, placements: list[tuple[Vec3, list[float]]] | None,
                  name: str, recenter: bool = False) -> int:
        """Add one mesh + node; returns the triangle count of one copy."""
        positions = _gltf_positions(mrm)
        if recenter:
            lo, hi = _used_bounds(mrm, positions)
            positions -= np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        primitives, triangles = [], 0
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
                POSITION=self.accessor(pos, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER, minmax=True),
                NORMAL=self.accessor(nrm, gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER),
                TEXCOORD_0=self.accessor(uv, gl.VEC2, gl.FLOAT, gl.ARRAY_BUFFER),
            )
            idx = self.accessor(tris.reshape(-1), gl.SCALAR, gl.UNSIGNED_INT, gl.ELEMENT_ARRAY_BUFFER)

            mat = sm.material
            tex = self._texture((mat.texture or "").upper())
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
            self.materials.append(gm)
            primitives.append(gl.Primitive(attributes=attrs, indices=idx, material=len(self.materials) - 1))

        self.meshes.append(gl.Mesh(primitives=primitives, name=name))
        node = gl.Node(mesh=len(self.meshes) - 1, name=name)
        if placements is not None and self.bake:
            for p, r in placements:
                t, q = game_instance(p, r)
                self.nodes.append(gl.Node(mesh=node.mesh, name=name, translation=list(t), rotation=list(q)))
            return triangles
        if placements is not None:
            inst = [game_instance(p, r) for p, r in placements]
            t_acc = self.accessor(np.array([t for t, _ in inst], dtype=np.float32), gl.VEC3, gl.FLOAT, minmax=True)
            r_acc = self.accessor(np.array([q for _, q in inst], dtype=np.float32), gl.VEC4, gl.FLOAT)
            node.extensions = {INSTANCING: {"attributes": {"TRANSLATION": t_acc, "ROTATION": r_acc}}}
        self.nodes.append(node)
        return triangles

    def save(self, instanced: bool) -> None:
        data = self.blob.bytes()
        gltf = gl.GLTF2(
            asset=gl.Asset(generator="gothic_extract", version="2.0"),
            extensionsUsed=[INSTANCING] if instanced else [],
            scene=0,
            scenes=[gl.Scene(nodes=list(range(len(self.nodes))))],
            nodes=self.nodes,
            meshes=self.meshes,
            accessors=self.accessors,
            bufferViews=self.blob.views,
            buffers=[gl.Buffer(byteLength=len(data))],
            materials=self.materials,
            images=self.images,
            textures=self.textures,
            samplers=[gl.Sampler(magFilter=gl.LINEAR, minFilter=gl.LINEAR_MIPMAP_LINEAR, wrapS=gl.REPEAT,
                                 wrapT=gl.REPEAT)],
        )
        gltf.set_binary_blob(data)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        gltf.save_binary(str(self.out_path))


def mrm_to_glb(mrm: zenkit.MultiResolutionMesh, vfs: zenkit.Vfs, placements: list[tuple[Vec3, list[float]]] | None,
               out_path: Path, tex_cache: dict | None = None, texture_dir: str | None = None,
               recenter: bool = False) -> int:
    """Write one .glb for an MRM; returns the triangle count of one copy.

    placements: every placement becomes an EXT_mesh_gpu_instancing instance (world models). With None the
    file holds one plain copy and no instancing extension (previews).
    recenter: move the mesh so it is centred on the origin horizontally and its lowest vertex sits at y = 0.
    texture_dir (relative to out_path's folder, e.g. "textures" or "../textures"): textures are written there
    once as PNG and referenced by URI, never overwritten; otherwise they are embedded.
    """
    b = _GlbBuilder(out_path, vfs, {} if tex_cache is None else tex_cache, texture_dir)
    triangles = b.add_model(mrm, placements, out_path.stem, recenter)
    b.save(placements is not None)
    return triangles


_IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def collect_placements(wd: WorldData, catalog: dict[str, ItemDef], script_items: list[ItemRec]):
    """→ ({visual (upper-case .3DS name): (kind, [(pos, rot)])}, {unhandled extension: placements})."""
    out: dict[str, tuple[str, list]] = {}
    unhandled: Counter = Counter()
    groups: dict[str, list] = defaultdict(list)
    kinds: dict[str, str] = {}
    for v in wd.vobs:
        vis = (v.visual or "").upper()
        if not vis or not v.show_visual or v.vob_type in _SKIP_TYPES or vis.startswith(_SKIP_PREFIXES):
            continue
        if not vis.endswith(".3DS"):
            unhandled[vis.rsplit(".", 1)[-1]] += 1
            continue
        groups[vis].append((v.pos, v.rot))
        kinds.setdefault(vis, "vob")
    # item VOBs store no visual in the ZEN (the engine takes it from the script instance)
    rot_by_vob = {v.id: v.rot for v in wd.vobs}
    for i in wd.items + script_items:
        d = catalog.get(i.code)
        vis = (d.visual if d else "").upper()
        if not vis or i.pos is None:
            continue
        if not vis.endswith(".3DS"):
            unhandled[vis.rsplit(".", 1)[-1]] += 1
            continue
        # script items sit on freepoints, which carry no usable orientation for items
        groups[vis].append((i.pos, rot_by_vob.get(i.vob_id, _IDENTITY) if i.vob_id else _IDENTITY))
        kinds.setdefault(vis, "item")
    for vis, places in groups.items():
        out[vis] = (kinds[vis], places)
    return out, dict(unhandled)


def export_vob_models(vfs: zenkit.Vfs, wd: WorldData, catalog: dict[str, ItemDef], script_items: list[ItemRec],
                      out_dir: Path) -> ModelsReport:
    report = ModelsReport()
    entries = []
    tex_cache: dict = {}
    combined = _GlbBuilder(out_dir.parent / "vobs.glb", vfs, tex_cache, None, bake=True)  # all world VOBs and ground items, textures embedded
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(out_dir.glob("*.glb")) + list((out_dir / "textures").glob("*.png")):
        stale.unlink()
    placements, unhandled = collect_placements(wd, catalog, script_items)
    report.unhandled = unhandled
    for vis, (kind, places) in sorted(placements.items()):
        node = vfs.find(vis[: -len(".3DS")] + ".MRM")
        if node is None:
            report.missing.append(vis)
            continue
        mrm = zenkit.MultiResolutionMesh.load(node.open())
        fname = vis[: -len(".3DS")].lower() + ".glb"
        tris = mrm_to_glb(mrm, vfs, places, out_dir / fname, tex_cache, texture_dir="textures")
        combined.add_model(mrm, places, vis[: -len(".3DS")].lower())
        entries.append({"visual": vis, "file": fname, "kind": kind, "instances": len(places), "triangles": tris})
        report.models += 1
        report.instances += len(places)
    combined.save(False)
    (out_dir / "index.json").write_text(json.dumps(
        {"frame": "same as world.glb: (x/100, y/100, -z/100) of game coordinates", "extension": INSTANCING,
         "models": entries, "missing": report.missing,
         "unhandled": unhandled}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


@dataclass
class PreviewReport:
    entries: list[dict] = field(default_factory=list)  # one per preview file (see previews/index.json)
    file_for: dict[str, str | None] = field(default_factory=dict)  # item code -> preview file name or None
    reason: dict[str, str | None] = field(default_factory=dict)  # item code -> why there is no preview
    new_textures: list[str] = field(default_factory=list)  # PNGs this run added to the shared textures folder


def export_item_previews(vfs: zenkit.Vfs, catalog: dict[str, ItemDef], out_dir: Path) -> PreviewReport:
    """One standalone .glb per item visual: a single copy, no instancing, centred, standing on y = 0, in metres.

    Items sharing a visual share a file. Only static meshes (.3DS -> compiled .MRM) are exported; textures go
    to the sibling `textures/` folder shared with the world models (existing files are never touched).
    Reasons for no preview: "no_visual", "unsupported_visual" (e.g. .MMS bows), "no_mesh" (MRM not in the VFS).
    """
    report = PreviewReport()
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.glb"):
        stale.unlink()
    textures_dir = out_dir.parent / "textures"
    before = {f.name for f in textures_dir.glob("*.png")} if textures_dir.is_dir() else set()
    tex_cache: dict = {}
    done: dict[str, str | None] = {}
    fail: dict[str, str] = {}
    codes_by_file: dict[str, list[str]] = defaultdict(list)
    for code, d in sorted(catalog.items()):
        vis = (d.visual or "").upper()
        if not vis:
            report.file_for[code], report.reason[code] = None, "no_visual"
            continue
        if not vis.endswith(".3DS"):
            report.file_for[code], report.reason[code] = None, "unsupported_visual"
            continue
        if vis not in done and vis not in fail:
            node = vfs.find(vis[: -len(".3DS")] + ".MRM")
            if node is None:
                fail[vis] = "no_mesh"
            else:
                mrm = zenkit.MultiResolutionMesh.load(node.open())
                fname = vis[: -len(".3DS")].lower() + ".glb"
                tris = mrm_to_glb(mrm, vfs, None, out_dir / fname, tex_cache, texture_dir="../textures",
                                  recenter=True)
                lo, hi = _used_bounds(mrm, _gltf_positions(mrm))
                size = hi - lo
                report.entries.append({"file": fname, "visual": vis, "triangles": tris,
                                       "bounds_m": {"x": round(float(size[0]), 4), "y": round(float(size[1]), 4),
                                                    "z": round(float(size[2]), 4)}})
                done[vis] = fname
        if vis in fail:
            report.file_for[code], report.reason[code] = None, fail[vis]
        else:
            report.file_for[code], report.reason[code] = done[vis], None
            codes_by_file[done[vis]].append(code)
    for e in report.entries:
        e["codes"] = codes_by_file[e["file"]]
    after = {f.name for f in textures_dir.glob("*.png")} if textures_dir.is_dir() else set()
    report.new_textures = sorted(after - before)
    (out_dir / "index.json").write_text(json.dumps(
        {"frame": "glTF (east, up, -north) in metres; centred horizontally, lowest vertex at y = 0",
         "textures": "../textures/", "previews": report.entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
