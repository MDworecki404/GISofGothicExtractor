"""Gothic 3 object and item models: models/*.glb (instanced), vobs.glb (everything in one file), item previews.

Same files and frame as the G1/G2 export (vob_models.py): glTF = (x/100, y/100, -z/100) of game coordinates.
Placements come from static entities of .node files (buildings, props, rocks…: eCVisualMeshStatic_PS) and from
world entities with a mesh (chests, doors, items on the ground: eCVisualMeshStatic_PS / eCVisualMeshDynamic_PS).
An entity's world matrix uses row vectors (p @ R + t, translation in elements 12-14; checked against the boxes the
game stores); for glTF it becomes A = F Rᵀ F and T = F t / 100 with F = diag(1, 1, -1). SpeedTree trees (.spt) are
not exported (reported in index.json as unhandled).
"""
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pygltflib as gl

from ..catalog import ItemDef
from ..mesh_export import Blob
from ..vob_models import INSTANCING, _quat_from_matrix
from .archive import G3Fs
from .entities import read_node_file, walk
from .genome import FormatError
from .image import WATER_COLOR, apply_alpha_mode, material_info, ximg_to_png
from .mesh import MeshElement, load_mesh

_F = np.diag([1.0, 1.0, -1.0])
VISUAL_CLASSES = ("eCVisualMeshStatic_PS", "eCVisualMeshDynamic_PS", "eCVisualAnimation_PS")


@dataclass
class Placement:
    mesh: str  # .xcmsh / .xlmsh name as in the game
    kind: str  # "vob" | "item"
    world: list[float]  # 4x4 world matrix of the entity (row vectors)


@dataclass
class ModelsReport:
    models: int = 0
    instances: int = 0
    missing: Counter = field(default_factory=Counter)  # mesh -> placements without a readable mesh
    unhandled: dict[str, int] = field(default_factory=dict)  # kind of visual -> placements not exported
    hidden: int = 0  # placements of water helper meshes (depth, far sea), which the game does not draw


def _linear(world: list[float]) -> tuple[np.ndarray, np.ndarray]:
    m = np.asarray(world, dtype=np.float64).reshape(4, 4)
    return _F @ m[:3, :3].T @ _F, (_F @ m[3, :3]) / 100.0


def instance_matrix(world: list[float]) -> list[float]:
    """glTF node matrix (column-major) of a placement."""
    a, t = _linear(world)
    n = np.eye(4)
    n[:3, :3], n[:3, 3] = a, t
    return [float(v) for v in n.flatten(order="F")]


def instance_trs(world: list[float]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """(translation, rotation quaternion xyzw, scale) for EXT_mesh_gpu_instancing; a mirror becomes -x scale."""
    a, t = _linear(world)
    s = np.linalg.norm(a, axis=0)
    s[s == 0] = 1.0
    rot = a / s
    if np.linalg.det(rot) < 0:
        s[0], rot[:, 0] = -s[0], -rot[:, 0]
    u, _, vt = np.linalg.svd(rot)  # remove shear/rounding so the quaternion is a pure rotation
    rot = u @ vt
    return tuple(float(v) for v in t), _quat_from_matrix(rot), tuple(float(v) for v in s)


def spatial_parts(worlds: list[list[float]], parts: int) -> list[int]:
    """Part number (0-based) of every placement: a balanced split by x, then by z inside each half (and x, z, x… for
    more parts), so parts have equal counts and are compact. `parts` is a power of two; parts are numbered
    west-south, west-north, east-south, east-north for 4."""
    t = np.array([_linear(w)[1] for w in worlds]).reshape(-1, 3)
    out = [0] * len(worlds)

    def split(idx: np.ndarray, k: int, first: int, axis: int) -> None:
        if k == 1:
            for i in idx:
                out[i] = first
            return
        idx = idx[np.argsort(t[idx, axis], kind="stable")]
        half = len(idx) // 2
        split(idx[:half], k // 2, first, 2 - axis)
        split(idx[half:], k // 2, first + k // 2, 2 - axis)

    if parts < 1 or parts & (parts - 1):
        raise ValueError("parts must be a power of two")
    split(np.arange(len(worlds)), parts, 0, 0)
    return out


def node_files(fs: G3Fs, world: str, sector_names: list[str]) -> list[str]:
    """.node files of the given sectors and of the world's SysDyn cells (developer and low-poly layers left out)."""
    wanted = {s.lower() for s in sector_names}
    out = []
    for p in fs.list(world + "/", ".node"):
        folder = p.split("/")[-2]
        if "lowpoly" in p.lower() or "test" in p.lower():
            continue
        if folder.lower() in wanted or folder.startswith("SysDyn_"):
            out.append(p)
    return out


def node_placements(fs: G3Fs, paths: list[str]) -> list[Placement]:
    out = []
    for p in paths:
        try:
            roots = read_node_file(fs.find(p))
        except (FormatError, IndexError):
            continue  # a few layers in the older inline-string variant (VFX, magic barrier)
        for e in walk(roots):
            vis = e.props.get("eCVisualMeshStatic_PS")
            if vis is not None and isinstance(vis.props["ResourceFilePath"].value, str):
                out.append(Placement(vis.props["ResourceFilePath"].value, "vob", e.world))
    return out


def visual_path(e) -> str | None:
    """Mesh of an entity's visual: ResourceFilePath, or ResourceFileName when the path is empty (torches,
    scrolls, maps)."""
    vis = next((e.props[c] for c in VISUAL_CLASSES if c in e.props), None)
    if vis is None:
        return None
    for prop in ("ResourceFilePath", "ResourceFileName"):
        v = vis.props[prop].value if prop in vis.props else None
        if isinstance(v, str) and v:
            return v
    return None


def world_placements(fs: G3Fs, cfg, world: str, templates: dict | None = None) -> tuple[list[Placement], int]:
    """Meshes of world entities → (placements, animated visuals whose actor cannot be read).

    Items on the ground, props, chests, doors (animated meshes: their rest pose, see actor.py). NPCs and everything
    below an NPC or a container (body parts, carried things) are left out. An entity with an empty mesh path
    (torches, scrolls) shows the mesh of the template it was made from (`templates`)."""
    from .world import WorldStats, _load, sector_files

    loaded = _load(fs, sector_files(fs, world, cfg.sector_exclude, cfg.include_disabled_sectors), WorldStats())
    holders = {id(x.entity) for x in loaded if "gCInventory_PS" in x.entity.props}
    out, animated = [], 0
    for x in loaded:
        e = x.entity
        if "gCNPC_PS" in e.props or (x.parent is not None and id(x.parent) in holders):
            continue
        path = visual_path(e)
        if path is None and templates and e.creator in templates and any(c in e.props for c in VISUAL_CLASSES):
            path = visual_path(templates[e.creator].entity)
        if path is None:
            continue
        if path.lower().endswith(".fxa") and not load_mesh(fs, path):
            animated += 1
            continue
        out.append(Placement(path, "item" if "gCItem_PS" in e.props else "vob", e.world))
    return out, animated


def speedtrees(fs: G3Fs, paths: list[str]) -> int:
    n = 0
    for p in paths:
        try:
            n += sum(1 for e in walk(read_node_file(fs.find(p))) if "eCSpeedTree_PS" in e.props)
        except (FormatError, IndexError):
            continue
    return n


class _Builder:
    """Meshes and nodes of one .glb; textures go to `texture_dir` (relative URI, written once) or are embedded."""

    def __init__(self, fs: G3Fs, out_path: Path, tex_cache: dict, texture_dir: str | None, max_texture: int):
        self.fs, self.out_path, self.tex_cache, self.texture_dir = fs, out_path, tex_cache, texture_dir
        self.max_texture = max_texture
        self.blob = Blob()
        self.accessors, self.materials, self.images, self.textures = [], [], [], []
        self.meshes, self.nodes = [], []
        self.material_idx: dict[str, int] = {}
        self.instanced = False

    def accessor(self, arr, kind, comp, target=None, minmax=False):
        view = self.blob.add(np.ascontiguousarray(arr).tobytes(), target)
        acc = gl.Accessor(bufferView=view, componentType=comp, count=len(arr), type=kind)
        if minmax:
            acc.min, acc.max = arr.min(axis=0).tolist(), arr.max(axis=0).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def _resolved(self, material: str):
        """(MaterialInfo | None, (stem, png, has_alpha) | None); None info for actors, which name a .ximg directly."""
        if material not in self.tex_cache:
            info = None if material.lower().endswith(".ximg") else material_info(self.fs.find_name(material))
            name = material if info is None else info.texture
            data = self.fs.find_name(name) if name else None
            try:
                png = ximg_to_png(data, self.max_texture, info is None or info.alpha_mode != "OPAQUE") if data else None
            except FormatError:
                png = None
            self.tex_cache[material] = (info, (name.rsplit(".", 1)[0].lower(), *png) if png else None)
        return self.tex_cache[material]

    def hidden(self, material: str) -> bool:
        """Depth and far-sea helper meshes of the water: not drawn by the game, would cover the terrain."""
        info = self._resolved(material)[0]
        return info is not None and info.hidden

    def material(self, material: str) -> int:
        if material in self.material_idx:
            return self.material_idx[material]
        pbr = gl.PbrMetallicRoughness(metallicFactor=0.0, roughnessFactor=1.0)
        mat = gl.Material(name=material, pbrMetallicRoughness=pbr)
        info, tex = self._resolved(material)
        if info is not None and info.is_water:  # samplers are normal maps: flat translucent colour instead
            pbr.baseColorFactor = list(WATER_COLOR)
            mat.alphaMode = "BLEND"
        elif tex is None:
            pbr.baseColorFactor = [0.6, 0.6, 0.6, 1.0]
        else:
            stem, png, has_alpha = tex
            if self.texture_dir is None:
                self.images.append(gl.Image(bufferView=self.blob.add(png), mimeType="image/png", name=stem))
            else:
                uri = f"{self.texture_dir}/{stem}.png"
                target = self.out_path.parent / uri
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(png)
                self.images.append(gl.Image(uri=uri, mimeType="image/png", name=stem))
            self.textures.append(gl.Texture(source=len(self.images) - 1, sampler=0))
            pbr.baseColorTexture = gl.TextureInfo(index=len(self.textures) - 1)
            apply_alpha_mode(mat, info, has_alpha)
        self.materials.append(mat)
        self.material_idx[material] = len(self.materials) - 1
        return self.material_idx[material]

    def add_mesh(self, elements: list[MeshElement], name: str, recenter: bool = False) -> tuple[int, int]:
        """→ (mesh index, triangles of one copy)."""
        elements = [el for el in elements if not self.hidden(el.material)]
        pts = [(el.positions.astype(np.float64) @ _F) / 100.0 for el in elements]
        shift = np.zeros(3)
        if recenter:
            allp = np.vstack(pts)
            lo, hi = allp.min(axis=0), allp.max(axis=0)
            shift = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        primitives, triangles = [], 0
        for el, pos in zip(elements, pts):
            if not len(el.indices):
                continue
            n = len(pos)
            nrm = (el.normals @ _F) if el.normals is not None else np.tile([0.0, 1.0, 0.0], (n, 1))
            uv = el.uvs if el.uvs is not None else np.zeros((n, 2))
            attrs = gl.Attributes(
                POSITION=self.accessor((pos - shift).astype(np.float32), gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER, True),
                NORMAL=self.accessor(nrm.astype(np.float32), gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER),
                TEXCOORD_0=self.accessor(uv.astype(np.float32), gl.VEC2, gl.FLOAT, gl.ARRAY_BUFFER),
            )
            idx = self.accessor(el.indices.astype(np.uint32), gl.SCALAR, gl.UNSIGNED_INT, gl.ELEMENT_ARRAY_BUFFER)
            primitives.append(gl.Primitive(attributes=attrs, indices=idx, material=self.material(el.material)))
            triangles += len(el.indices) // 3
        self.meshes.append(gl.Mesh(primitives=primitives, name=name))
        return len(self.meshes) - 1, triangles

    def add_instances(self, mesh: int, name: str, worlds: list[list[float]]) -> None:
        trs = [instance_trs(w) for w in worlds]
        attrs = {
            "TRANSLATION": self.accessor(np.array([t for t, _, _ in trs], np.float32), gl.VEC3, gl.FLOAT, minmax=True),
            "ROTATION": self.accessor(np.array([q for _, q, _ in trs], np.float32), gl.VEC4, gl.FLOAT),
            "SCALE": self.accessor(np.array([s for _, _, s in trs], np.float32), gl.VEC3, gl.FLOAT),
        }
        self.nodes.append(gl.Node(mesh=mesh, name=name, extensions={INSTANCING: {"attributes": attrs}}))
        self.instanced = True

    def add_nodes(self, mesh: int, name: str, worlds: list[list[float]] | None) -> None:
        if worlds is None:
            self.nodes.append(gl.Node(mesh=mesh, name=name))
            return
        for w in worlds:
            self.nodes.append(gl.Node(mesh=mesh, name=name, matrix=instance_matrix(w)))

    def save(self) -> None:
        data = self.blob.bytes()
        gltf = gl.GLTF2(
            asset=gl.Asset(generator="gothic_extract", version="2.0"),
            extensionsUsed=[INSTANCING] if self.instanced else [],
            scene=0, scenes=[gl.Scene(nodes=list(range(len(self.nodes))))], nodes=self.nodes, meshes=self.meshes,
            accessors=self.accessors, bufferViews=self.blob.views, buffers=[gl.Buffer(byteLength=len(data))],
            materials=self.materials, images=self.images, textures=self.textures,
            samplers=[gl.Sampler(magFilter=gl.LINEAR, minFilter=gl.LINEAR_MIPMAP_LINEAR, wrapS=gl.REPEAT,
                                 wrapT=gl.REPEAT)],
        )
        gltf.set_binary_blob(data)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        gltf.save_binary(str(self.out_path))


def _file_name(mesh: str) -> str:
    return mesh.rsplit(".", 1)[0].lower() + ".glb"


def export_models(fs: G3Fs, placements: list[Placement], out_dir: Path, max_texture: int = 512,
                  unhandled: dict[str, int] | None = None, vobs_parts: int = 1) -> ModelsReport:
    """models/<mesh>.glb per mesh (EXT_mesh_gpu_instancing, textures in models/textures/) and ../vobs.glb with
    every placement as a plain node (textures embedded), plus models/index.json. vobs_parts > 1 also writes
    ../vobs_czesci/vobs_czesc_<n>.glb: the same nodes in equal spatial parts, each with only its own textures."""
    report = ModelsReport(unhandled=dict(unhandled or {}))
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(out_dir.glob("*.glb")) + list((out_dir / "textures").glob("*.png")):
        stale.unlink()
    groups: dict[str, list[Placement]] = defaultdict(list)
    for p in placements:
        groups[p.mesh].append(p)
    tex_shared: dict = {}
    combined = _Builder(fs, out_dir.parent / "vobs.glb", tex_shared, None, max_texture)
    entries = []
    exported: list[tuple[str, list[MeshElement], list[list[float]]]] = []
    for mesh in sorted(groups):
        places = groups[mesh]
        elements = load_mesh(fs, mesh) if mesh else None
        if not elements:
            report.missing[mesh or "<no mesh>"] += len(places)
            continue
        elements = [el for el in elements if not combined.hidden(el.material)]
        if not elements:  # water helper meshes only
            report.hidden += len(places)
            continue
        worlds = [p.world for p in places]
        one = _Builder(fs, out_dir / _file_name(mesh), tex_shared, "textures", max_texture)
        m, tris = one.add_mesh(elements, mesh)
        one.add_instances(m, mesh, worlds)
        one.save()
        cm, _ = combined.add_mesh(elements, mesh)
        combined.add_nodes(cm, mesh, worlds)
        exported.append((mesh, elements, worlds))
        kind = "item" if any(p.kind == "item" for p in places) else "vob"
        entries.append({"visual": mesh, "file": _file_name(mesh), "kind": kind, "instances": len(places),
                        "triangles": tris})
        report.models += 1
        report.instances += len(places)
    combined.save()
    if vobs_parts > 1:
        _save_parts(fs, exported, out_dir.parent / "vobs_czesci", tex_shared, max_texture, vobs_parts)
    (out_dir / "index.json").write_text(json.dumps(
        {"frame": "same as world.glb: (x/100, y/100, -z/100) of game coordinates", "extension": INSTANCING,
         "models": entries, "missing": sorted(report.missing), "missing_instances": sum(report.missing.values()), "hidden_instances": report.hidden,
         "unhandled": report.unhandled}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _save_parts(fs: G3Fs, exported, folder: Path, tex_cache: dict, max_texture: int, parts: int) -> None:
    """vobs_czesc_<n>.glb: every placement once, in the part of its position; one mesh per model and part."""
    flat = [(i, w) for i, (_, _, worlds) in enumerate(exported) for w in worlds]
    part_of = spatial_parts([w for _, w in flat], parts)
    wanted: list[dict[int, list]] = [defaultdict(list) for _ in range(parts)]
    for (i, w), part in zip(flat, part_of):
        wanted[part][i].append(w)
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("vobs_czesc_*.glb"):
        stale.unlink()
    for n, models in enumerate(wanted, 1):
        b = _Builder(fs, folder / f"vobs_czesc_{n}.glb", tex_cache, None, max_texture)
        for i, worlds in sorted(models.items()):
            mesh, elements, _ = exported[i]
            m, _ = b.add_mesh(elements, mesh)
            b.add_nodes(m, mesh, worlds)
        b.save()


@dataclass
class PreviewReport:
    entries: list[dict] = field(default_factory=list)
    reason: dict[str, str | None] = field(default_factory=dict)  # item code -> why there is no preview


def export_item_previews(fs: G3Fs, catalog: dict[str, ItemDef], out_dir: Path, max_texture: int = 512,
                         extra_visuals: list[str] = ()) -> PreviewReport:
    """One .glb per item mesh: a single copy, centred horizontally, lowest vertex at y = 0, metres; textures in
    the sibling textures/ folder shared with the world models. Reasons for no preview: no_visual, no_mesh.
    extra_visuals: further meshes to preview without an item code (containers: the chest's own model)."""
    report = PreviewReport()
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.glb"):
        stale.unlink()
    tex_cache: dict = {}
    done: dict[str, str | None] = {}
    codes: dict[str, list[str]] = defaultdict(list)
    wanted = [(code, d.visual or "") for code, d in sorted(catalog.items())]
    wanted += [(None, v) for v in sorted(set(extra_visuals)) if v]
    for code, vis in wanted:
        if not vis:
            report.reason[code] = "no_visual"
            continue
        if vis not in done:
            b = _Builder(fs, out_dir / _file_name(vis), tex_cache, "../textures", max_texture)
            elements = [el for el in load_mesh(fs, vis) or [] if not b.hidden(el.material)]
            if not elements:
                done[vis] = None
            else:
                m, tris = b.add_mesh(elements, vis, recenter=True)
                b.add_nodes(m, vis, None)
                b.save()
                pts = np.vstack([(el.positions.astype(np.float64) @ _F) / 100.0 for el in elements])
                size = pts.max(axis=0) - pts.min(axis=0)
                report.entries.append({"file": _file_name(vis), "visual": vis, "triangles": tris,
                                       "bounds_m": {k: round(float(v), 4) for k, v in zip("xyz", size)}})
                done[vis] = _file_name(vis)
        if code is None:
            continue
        if done[vis] is None:
            report.reason[code] = "no_mesh"
        else:
            report.reason[code] = None
            codes[done[vis]].append(code)
    for e in report.entries:
        e["codes"] = codes[e["file"]]
    (out_dir / "index.json").write_text(json.dumps(
        {"frame": "glTF (east, up, -north) in metres; centred horizontally, lowest vertex at y = 0",
         "textures": "../textures/", "previews": report.entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
