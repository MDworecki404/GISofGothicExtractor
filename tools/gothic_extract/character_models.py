"""3D models of unique characters (G1, G2 NK, Archolos): models/characters/*.glb + the `model` field.

Variant B of the 2026-11 measurement: one .glb per *part* shared by every character that uses it, plus the
`model` object on each character (`{body, head, armor, weapon}`, paths relative to models/, each may be null).

How a character looks is read by running its Daedalus instance with Mdl_SetVisual / Mdl_SetVisualBody registered
(body mesh, body texture, skin colour, head mesh, head texture, teeth texture, armor item). Parts:
- body: softskin .MDM in its bind pose (the vertices of the MRM; a standing human with arms by the sides);
- armor: the armor item's `visual_change` .MDM; it *replaces* the body mesh in the game and carries its own skin
  submesh, which takes the character's body texture (so `body` is null when `armor` is set);
- head: .MMB morph mesh, stored in the space of the head bone; here it is moved to its place on the body, so the
  application only adds it at the origin of the same scene;
- creature: the body mesh of a non-human skeleton (monsters, orcs) as `body`, no head.
Textures: PNG, at most 512 px, in the sibling `textures/` folder shared with the item previews of the same world
(an existing file of the same name is reused when it already fits, never overwritten).

Frame: metres, glTF (x/100, y/100, -z/100) of game coordinates, shifted by ONE offset per skeleton so that the
standing body is centred horizontally with its lowest vertex at y = 0; head (and the body/armor of the same
skeleton) use that same offset, so they line up without any bone maths.
"""
import argparse
import io
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygltflib as gl
import zenkit
from PIL import Image

from .config import PROJECT_ROOT, load_game
from .mesh_export import load_png
from .vob_models import _GlbBuilder, _gltf_positions, _used_bounds

MAX_TEXTURE = 512
HUMAN_MDS = "HUMANS.MDS"
HUMAN_REFERENCE_BODY = "HUM_BODY_NAKED0"
# The head meshes are not centred on the head bone: placed at the bone they sit ~10.6 cm in front of the neck. The
# offset (game cm, model space) makes the bottom ring of HUM_HEAD_BALD coincide with the top ring of HUM_BODY_NAKED0
# (measured on G2, checked against G1 and Archolos renders).
HEAD_SEAT_OFFSET_CM = np.array([0.0, 0.0, -10.6])
WEAPON_CATEGORIES = ("Broń biała", "Broń dystansowa")  # melee first


@dataclass
class Visual:
    mds: str
    body_mesh: str
    body_tex: int
    skin: int
    head_mesh: str
    head_tex: int
    teeth_tex: int
    armor_item: str | None

    @property
    def human(self) -> bool:
        return self.mds.upper().startswith("HUMANS")  # HUMANS.MDS, HUMANS_SPEAR.MDS …


def read_visuals(vm: zenkit.DaedalusVm, codes: list[str]) -> dict[str, Visual | None]:
    """Instance code -> Visual (None: the instance never calls Mdl_SetVisualBody)."""
    cur: dict = {}
    vm.register_external("MDL_SETVISUAL", lambda i, s: cur.setdefault("mds", s), zenkit.DaedalusInstance, str)

    def body(inst, bm, bt, sk, hm, ht, tt, ar):
        cur["body"] = (bm, bt, sk, hm, ht, tt, ar)

    vm.register_external("MDL_SETVISUALBODY", body, zenkit.DaedalusInstance, str, int, int, str, int, int, int)
    out: dict[str, Visual | None] = {}
    for code in codes:
        cur.clear()
        try:
            vm.init_instance(code, zenkit.DaedalusInstanceType.NPC)
        except Exception:
            out[code] = None
            continue
        if "body" not in cur or not cur["body"][0]:
            out[code] = None
            continue
        bm, bt, sk, hm, ht, tt, ar = cur["body"]
        armor = None
        if ar > 0:
            sym = vm.get_symbol_by_index(ar)
            armor = sym.name if sym is not None else None
        out[code] = Visual(cur.get("mds", ""), bm, bt, sk, hm or "", ht, tt, armor)
    return out


def armor_mesh_name(vm: zenkit.DaedalusVm, item: str | None) -> str | None:
    """Mesh of an armor item (`visual_change`, e.g. ARMOR_VLK_M.asc -> ARMOR_VLK_M)."""
    if not item:
        return None
    try:
        vc = vm.init_instance(item, zenkit.DaedalusInstanceType.ITEM).visual_change
    except Exception:
        return None
    return vc.rsplit(".", 1)[0].upper() if vc else None


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")


def _mat4(t) -> np.ndarray:
    return np.array([[t.columns[c][r] for c in range(4)] for r in range(4)], dtype=np.float64)


def node_worlds(vfs: zenkit.Vfs, mdh: str) -> dict[str, np.ndarray] | None:
    """Bone name (upper case) -> bone space to model space (game units, 4x4, column vectors): the chain of the MDH
    node transforms, starting at the hierarchy's root translation."""
    node = vfs.find(mdh)
    if node is None:
        return None
    h = zenkit.ModelHierarchy.load(node.data)
    root = np.eye(4)
    root[:3, 3] = [h.root_translation.x, h.root_translation.y, h.root_translation.z]
    world: list[np.ndarray] = []
    for n in h.nodes:
        world.append((world[n.parent] if n.parent >= 0 else root) @ _mat4(n.transform))
    return {n.name.upper(): w for n, w in zip(h.nodes, world)}


def head_transform(vfs: zenkit.Vfs, mdh: str = "HUMANS.MDH") -> np.ndarray:
    """Head-bone space -> model space of the human skeleton (see HEAD_SEAT_OFFSET_CM)."""
    m = node_worlds(vfs, mdh)["BIP01 HEAD"].copy()
    m[:3, 3] += HEAD_SEAT_OFFSET_CM
    return m


class _PartBuilder(_GlbBuilder):
    """One part per .glb. Textures: PNG <= MAX_TEXTURE in the shared folder, referenced by URI."""

    def __init__(self, out_path, vfs, tex_cache, textures_dir: Path, rename):
        super().__init__(out_path, vfs, tex_cache, "../textures")
        self.textures_dir, self.rename = textures_dir, rename
        self.texture_files: set[Path] = set()

    def _texture(self, tex_name: str):
        tex_name = self.rename(tex_name)
        if tex_name not in self.image_idx:
            entry = self.tex_cache.get(tex_name, False)
            if entry is False:
                entry = self.tex_cache[tex_name] = self._write_texture(tex_name)
            if entry is None:
                self.image_idx[tex_name] = None
            else:
                fname, has_alpha = entry
                self.images.append(gl.Image(uri=f"../textures/{fname}", mimeType="image/png", name=tex_name))
                self.textures.append(gl.Texture(source=len(self.images) - 1, sampler=0))
                self.image_idx[tex_name] = (len(self.textures) - 1, has_alpha)
            if entry is not None:
                self.texture_files.add(self.textures_dir / entry[0])
        return self.image_idx[tex_name]

    def _write_texture(self, tex_name: str) -> tuple[str, bool] | None:
        loaded = load_png(self.vfs, tex_name)
        if loaded is None:
            return None
        png, has_alpha = loaded
        im = Image.open(io.BytesIO(png))
        if max(im.size) > MAX_TEXTURE:
            im.load()
            im.thumbnail((MAX_TEXTURE, MAX_TEXTURE), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            png = buf.getvalue()
        stem = tex_name.rsplit(".", 1)[0].lower()
        fname = f"{stem}.png"
        target = self.textures_dir / fname
        if target.exists():
            try:
                fits = max(Image.open(target).size) <= MAX_TEXTURE
            except OSError:
                fits = False
            if not fits:  # an item texture at full size: ours gets its own file
                fname = f"{stem}_{MAX_TEXTURE}.png"
                target = self.textures_dir / fname
        if not target.exists():
            self.textures_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png)
        return fname, has_alpha

    def add_part(self, mrm: zenkit.MultiResolutionMesh, positions: np.ndarray, rotation: np.ndarray | None,
                 name: str) -> int:
        """positions: glTF-frame vertices of the whole MRM (indexed like mrm.positions)."""
        primitives, triangles = [], 0
        for sm in mrm.submeshes:
            wedges = sm.wedges
            tris = np.array([tuple(t.wedges) for t in sm.triangles], dtype=np.uint32)
            if len(tris) == 0 or len(wedges) == 0:
                continue
            triangles += len(tris)
            widx = np.array([w.index for w in wedges], dtype=np.int64)
            uv = np.array([(w.texture.x, w.texture.y) for w in wedges], dtype=np.float32)
            nrm = np.array([(w.normal.x, w.normal.y, w.normal.z) for w in wedges], dtype=np.float64)
            if rotation is not None:
                nrm = nrm @ rotation.T
            nrm = (nrm * np.array([1, 1, -1])).astype(np.float32)
            attrs = gl.Attributes(
                POSITION=self.accessor(positions[widx].astype(np.float32), gl.VEC3, gl.FLOAT, gl.ARRAY_BUFFER,
                                       minmax=True),
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
        self.nodes.append(gl.Node(mesh=len(self.meshes) - 1, name=name))
        return triangles


def _variant(tex: str, kind: str, v: Visual) -> str:
    """Texture name the engine uses for a material of the mesh: V<n>_C<skin> of the body / head, V<n> of the teeth."""
    t = tex.upper()
    if kind in ("body", "armor"):
        if "BODY_NAKED" in t or kind == "body":
            return re.sub(r"_V\d+_C\d+", f"_V{v.body_tex}_C{v.skin}", t)
    elif kind == "head":
        if "TEETH" in t:
            return re.sub(r"_V\d+", f"_V{v.teeth_tex}", t)
        if "HEAD" in t:
            return re.sub(r"_V\d+_C\d+", f"_V{v.head_tex}_C{v.skin}", t)
    return t


def _load_body(vfs: zenkit.Vfs, name: str):
    """Softskin mesh of a .MDM (its vertices are in the bind pose), or None."""
    node = vfs.find(name.upper() + ".MDM")
    if node is None:
        return None
    meshes = zenkit.ModelMesh.load(node.data).meshes
    return meshes[0].mesh if meshes else None


def _load_attachments(vfs: zenkit.Vfs, name: str, mds: str) -> list[tuple[zenkit.MultiResolutionMesh, np.ndarray]]:
    """Rigid meshes of a .MDM that hangs its parts on bones (golems): (mesh, bone-to-model matrix) each."""
    node = vfs.find(name.upper() + ".MDM")
    worlds = node_worlds(vfs, mds.upper().rsplit(".", 1)[0] + ".MDH") if node is not None else None
    if node is None or worlds is None:
        return []
    atts = zenkit.ModelMesh.load(node.data).attachments
    return [(m, worlds[b.upper()]) for b, m in atts.items() if b.upper() in worlds]


def _load_head(vfs: zenkit.Vfs, name: str):
    node = vfs.find(name.upper() + ".MMB")
    return zenkit.MorphMesh.load(node.data).mesh if node is not None else None


def _skeleton_offset(mrm) -> np.ndarray:
    lo, hi = _used_bounds(mrm, _gltf_positions(mrm))
    return np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])


def build_parts(vfs: zenkit.Vfs, vm, visuals: dict[str, Visual | None], out_dir: Path) -> tuple[dict, dict, list]:
    """Writes the part files. -> (model per instance code, reason per code without one, index entries)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    textures_dir = out_dir.parent / "textures"
    tex_cache: dict = {}
    parts: dict[str, dict] = {}  # file -> index entry
    models: dict[str, dict] = {}
    reasons: dict[str, str] = {}
    human_ref = _load_body(vfs, HUMAN_REFERENCE_BODY)
    human_shift = _skeleton_offset(human_ref) if human_ref is not None else None
    head_m = head_transform(vfs) if vfs.find("HUMANS.MDH") is not None else None

    def write(fname: str, kind: str, v: Visual, build) -> str:
        if fname not in parts:
            path = out_dir / fname
            b = _PartBuilder(path, vfs, tex_cache, textures_dir, lambda t: _variant(t, kind, v))
            tris, lo, hi = build(b)
            b.save(False)
            size = hi - lo
            parts[fname] = {"file": fname, "kind": kind, "triangles": tris, "bytes": path.stat().st_size,
                            "texture_bytes": sum(f.stat().st_size for f in b.texture_files),
                            "bounds_m": {"x": round(float(size[0]), 4), "y": round(float(size[1]), 4),
                                         "z": round(float(size[2]), 4)}}
        return f"characters/{fname}"

    def whole(mrm, shift, rot=None, matrix=None):
        def build(b: _PartBuilder):
            pos = np.array([(p.x, p.y, p.z) for p in mrm.positions], dtype=np.float64)
            if matrix is not None:
                pos = pos @ matrix[:3, :3].T + matrix[:3, 3]
            pos = (pos / 100.0) * np.array([1, 1, -1]) - shift
            tris = b.add_part(mrm, pos, rot, b.out_path.stem)
            lo, hi = _used_bounds(mrm, pos)
            return tris, lo, hi
        return build

    def assembled(atts):
        def build(b: _PartBuilder):
            placed = []
            for mrm, mat in atts:
                pos = np.array([(p.x, p.y, p.z) for p in mrm.positions], dtype=np.float64)
                pos = pos @ mat[:3, :3].T + mat[:3, 3]
                placed.append((mrm, mat, (pos / 100.0) * np.array([1, 1, -1])))
            used = np.vstack([_used_bounds(m, p) for m, _, p in placed])
            lo, hi = used[0::2].min(axis=0), used[1::2].max(axis=0)
            shift = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
            tris = 0
            for k, (mrm, mat, pos) in enumerate(placed):
                tris += b.add_part(mrm, pos - shift, mat[:3, :3], f"{b.out_path.stem}_{k}")
            return tris, lo - shift, hi - shift
        return build

    for code, v in visuals.items():
        if v is None:
            reasons[code] = "no_visual"
            continue
        m = {"body": None, "head": None, "armor": None, "weapon": None}
        try:
            if v.human:
                if human_shift is None:
                    reasons[code] = "no_skeleton"
                    continue
                armor = armor_mesh_name(vm, v.armor_item)
                main_name = armor or v.body_mesh
                mrm = _load_body(vfs, main_name)
                if mrm is None and armor:  # armor without a mesh in the archives: bare body
                    armor, main_name = None, v.body_mesh
                    mrm = _load_body(vfs, main_name)
                if mrm is None:
                    reasons[code] = "no_mesh"
                    continue
                kind = "armor" if armor else "body"
                fname = f"{kind}_{_safe(main_name)}_v{v.body_tex}_c{v.skin}.glb"
                m[kind] = write(fname, kind, v, whole(mrm, human_shift))
                if v.head_mesh:
                    head = _load_head(vfs, v.head_mesh)
                    if head is not None:
                        fname = f"head_{_safe(v.head_mesh)}_v{v.head_tex}_c{v.skin}_t{v.teeth_tex}.glb"
                        m["head"] = write(fname, "head", v, whole(head, human_shift, head_m[:3, :3], head_m))
            else:
                fname = f"creature_{_safe(v.body_mesh)}.glb"
                mrm = _load_body(vfs, v.body_mesh)
                if mrm is not None:
                    m["body"] = write(fname, "creature", v, whole(mrm, _skeleton_offset(mrm)))
                else:
                    atts = _load_attachments(vfs, v.body_mesh, v.mds)
                    if not atts:
                        reasons[code] = "no_mesh"
                        continue
                    m["body"] = write(fname, "creature", v, assembled(atts))
        except Exception as e:  # a corrupt mesh must not stop the package
            reasons[code] = f"error: {type(e).__name__}: {e}"
            continue
        models[code] = m
    entries = sorted(parts.values(), key=lambda e: (e["kind"], e["file"]))
    return models, reasons, entries


def _weapon_model(props: dict, previews: dict[str, str]) -> str | None:
    """G1 only: preview of the first melee (else ranged) weapon in the inventory, when the world has one."""
    for cat in WEAPON_CATEGORIES:
        for it in props.get("inventory", []):
            if it.get("category") == cat and it["code"] in previews:
                return previews[it["code"]]
    return None


def _preview_codes(pkg: Path) -> dict[str, str]:
    p = pkg / "models" / "previews" / "index.json"
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for e in json.loads(p.read_text("utf-8"))["previews"]:
        for c in e.get("codes", []):
            out.setdefault(c, "previews/" + e["file"])
    return out


def apply_models(pkg: Path, models: dict[str, dict], reasons: dict[str, str], entries: list[dict],
                 weapon_previews: dict[str, str] | None = None) -> dict:
    """Write `model` into characters.geojson / search_index.json, models/characters/index.json and the counts.
    models / reasons: per instance code (a character takes the first of its codes that has a model)."""
    chars_path, index_path = pkg / "characters.geojson", pkg / "search_index.json"
    chars = json.loads(chars_path.read_text("utf-8"))
    index = json.loads(index_path.read_text("utf-8"))
    by_code: dict[str, dict | None] = {}
    null_reason: dict[str, str] = {}
    for f in chars["features"]:
        p = f["properties"]
        m = next((models[c] for c in p["codes"] if c in models), None)
        if m is not None:
            m = dict(m, weapon=_weapon_model(p, weapon_previews or {}))
        else:
            null_reason[p["code"]] = next((reasons[c] for c in p["codes"] if c in reasons), "no_visual")
        p["model"] = m
        by_code[p["code"]] = m
    for e in index["entries"]:
        if e["type"] == "character":
            e["model"] = by_code.get(e["code"])
    chars_path.write_text(json.dumps(chars, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    out_dir = pkg / "models" / "characters"
    (out_dir / "index.json").write_text(json.dumps(
        {"frame": "glTF (east, up, -north) in metres; human parts share the skeleton's frame (standing body "
                  "centred horizontally, feet at y = 0), so head and body/armor line up without bone maths",
         "textures": "../textures/", "parts": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    meta_path = pkg / "metadata.json"
    meta = json.loads(meta_path.read_text("utf-8"))
    counts = meta.setdefault("package", {}).setdefault("counts", {})
    counts["characters_with_model"] = sum(1 for m in by_code.values() if m is not None)
    counts["character_model_files"] = len(entries)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"characters": len(by_code), "with_model": counts["characters_with_model"], "files": len(entries),
            "glb_bytes": sum(e["bytes"] for e in entries), "texture_bytes": sum(e["texture_bytes"] for e in entries),
            "null": dict(Counter(null_reason.values())), "null_codes": null_reason,
            "kinds": dict(Counter(e["kind"] for e in entries))}


def add_character_models(game: str, pkg: Path, vm, vfs: zenkit.Vfs) -> dict:
    """Export the parts of the characters of one package (G1, G2, Archolos) and write `model`. -> report."""
    chars = json.loads((pkg / "characters.geojson").read_text("utf-8"))
    codes = sorted({c for f in chars["features"] for c in f["properties"]["codes"]})
    visuals = read_visuals(vm, codes)
    out_dir = pkg / "models" / "characters"
    for stale in out_dir.glob("*.glb") if out_dir.is_dir() else []:
        stale.unlink()
    models, reasons, entries = build_parts(vfs, vm, visuals, out_dir)
    return apply_models(pkg, models, reasons, entries, _preview_codes(pkg) if game == "g1" else {})


def main(argv: list[str] | None = None) -> int:
    from .script_vm import make_vm
    from .vfs import open_vfs

    ap = argparse.ArgumentParser(prog="gothic_extract.character_models",
                                 description="Character models of the packages of a game (G1, G2 NK, Archolos)")
    ap.add_argument("--game", required=True)
    ap.add_argument("--world", action="append", help="package slug (repeatable); default: all worlds")
    ap.add_argument("--dist-root", type=Path, default=PROJECT_ROOT / "dist")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_game(args.game)
    if cfg.engine != "zengin":
        raise SystemExit("zengin games only")
    vm, vfs = make_vm(cfg.script_dat), open_vfs(cfg)
    slugs = args.world or [w.slug for w in cfg.worlds.values()]
    for slug in slugs:
        r = add_character_models(args.game, args.dist_root / args.game / slug, vm, vfs)
        print(f"{args.game}/{slug}: {r['with_model']}/{r['characters']} z modelem, {r['files']} plików "
              f"({r['glb_bytes'] / 1e6:.1f} MB glb, {r['texture_bytes'] / 1e6:.1f} MB tekstur), null: {r['null']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
