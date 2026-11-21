"""Gothic 3 character models: models/characters/*.glb + the `model` field (same schema as G1/G2, see
gothic_extract.character_models).

A G3 NPC entity is a skeleton (root visual G3_Hero_Skeleton.FXA) with child entities that carry the looks:
a body actor (`G3_Hero_Body_*.FXA`, clothes and armor are part of it, so `armor` is always null), a head actor
(`G3_Head_*.FXA`) and static hair / beard meshes (`G3_Animation_Head_Hair|Beard_*.xcmsh`, stored in the space of
the head bone). Monsters have one root actor. Actors are read in their rest pose: people stand in a T pose.

Frame: metres, glTF (x/100, y/100, -z/100) of game coordinates. People of the hero skeleton keep the game's own
frame, in which the body is centred on x = z = 0 with its feet at y ~ 0, so body and head line up with no offset;
monsters (one mesh each) are centred horizontally with their lowest vertex at y = 0.
Hair and beards are merged into the head file, moved from head-bone space to the head (HEAD_BONE_M).
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..character_models import apply_models
from .archive import G3Fs
from .mesh import MeshElement, load_mesh
from .models import _Builder, _F, _file_name
from . import world as W
from .entities import walk

HERO_SKELETON = "g3_hero_skeleton.fxa"
# The hair / beard meshes sit around the head bone; the bone is not read from the actor, this offset (game cm)
# was fitted by eye on the head meshes (see the README note).
import os
HEAD_BONE_CM = np.array([float(v) for v in os.environ.get("G3_HEAD_BONE", "0,172,4").split(",")])


def _is_head(vis: str) -> bool:
    n = vis.lower()
    return "head" in n and "body" not in n


def npc_looks(fs: G3Fs, cfg, world: str, codes: set[str]) -> dict[str, dict]:
    """NPC code -> {root, parts: [(entity name, visual)]} from the first entity of the world with that code."""
    loaded = W._load(fs, W.sector_files(fs, world, cfg.sector_exclude, cfg.include_disabled_sectors), W.WorldStats())
    out: dict[str, dict] = {}
    for x in loaded:
        e = x.entity
        if "gCNPC_PS" in e.props and e.name in codes and e.name not in out:
            out[e.name] = {"root": W._visual(e),
                           "parts": [(c.name, W._visual(c)) for c in walk(e.children) if W._visual(c)]}
    return out


def _plan(look: dict) -> tuple[dict | None, str | None]:
    """-> (parts {body, head, hair: [..], creature}, None) or (None, reason)."""
    body = head = None
    extras: list[str] = []
    for _, vis in look["parts"]:
        low = vis.lower()
        if low.endswith(".fxa"):
            if _is_head(vis):
                head = head or vis
            else:
                body = body or vis
        elif _is_head(vis):
            extras.append(vis)
    root = look["root"]
    if body:
        return {"body": body, "head": head, "extras": sorted(extras)}, None
    if root and root.lower().endswith(".fxa") and root.lower() != HERO_SKELETON:
        return {"creature": root}, None
    if root and not root.lower().endswith(".fxa"):
        return None, "not_a_character_mesh"
    return None, "no_body"


def build_parts(fs: G3Fs, looks: dict[str, dict], out_dir: Path) -> tuple[dict, dict, list]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_cache: dict = {}
    parts: dict[str, dict] = {}
    models: dict[str, dict] = {}
    reasons: dict[str, str] = {}

    def write(fname: str, kind: str, elements_fn, recenter: bool) -> str | None:
        if fname not in parts:
            path = out_dir / fname
            b = _Builder(fs, path, tex_cache, "../textures", 512)
            elements = [el for el in elements_fn() if not b.hidden(el.material)]
            if not elements:
                parts[fname] = None
                return None
            mesh, tris = b.add_mesh(elements, path.stem, recenter=recenter)
            b.add_nodes(mesh, path.stem, None)
            b.save()
            pts = np.vstack([(el.positions.astype(np.float64) @ _F) / 100.0 for el in elements])
            size = pts.max(axis=0) - pts.min(axis=0)
            uris = {i.uri for i in b.images if i.uri}
            parts[fname] = {"file": fname, "kind": kind, "triangles": tris, "bytes": path.stat().st_size,
                            "texture_bytes": sum((out_dir / u).stat().st_size for u in uris if (out_dir / u).exists()),
                            "bounds_m": {k: round(float(v), 4) for k, v in zip("xyz", size)}}
        return f"characters/{fname}" if parts[fname] else None

    def stem(vis: str) -> str:
        return _file_name(vis)[:-4].lower()

    for code, look in looks.items():
        plan, reason = _plan(look)
        if plan is None:
            reasons[code] = reason
            continue
        m = {"body": None, "head": None, "armor": None, "weapon": None}
        if "creature" in plan:
            m["body"] = write(f"creature_{stem(plan['creature'])}.glb", "creature",
                              lambda v=plan["creature"]: load_mesh(fs, v) or [], True)
        else:
            m["body"] = write(f"body_{stem(plan['body'])}.glb", "body", lambda v=plan["body"]: load_mesh(fs, v) or [],
                              False)
            if plan["head"]:
                tag = "".join("__" + stem(x).replace("g3_animation_head_", "") for x in plan["extras"])

                def head_elements(h=plan["head"], ex=plan["extras"]):
                    els = list(load_mesh(fs, h) or [])
                    for x in ex:
                        for el in load_mesh(fs, x) or []:
                            els.append(MeshElement(el.material, el.positions + HEAD_BONE_CM, el.normals, el.uvs,
                                                   el.indices))
                    return els
                m["head"] = write(f"head_{stem(plan['head'])}{tag}.glb", "head", head_elements, False)
        if m["body"] is None:
            reasons[code] = "no_mesh"
            continue
        models[code] = m
    entries = sorted((p for p in parts.values() if p), key=lambda e: (e["kind"], e["file"]))
    return models, reasons, entries


def add_g3_character_models(fs: G3Fs, cfg, world: str, pkg: Path) -> dict:
    chars = json.loads((pkg / "characters.geojson").read_text("utf-8"))
    codes = {c for f in chars["features"] for c in f["properties"]["codes"]}
    out_dir = pkg / "models" / "characters"
    for stale in out_dir.glob("*.glb") if out_dir.is_dir() else []:
        stale.unlink()
    looks = npc_looks(fs, cfg, world, codes)
    models, reasons, entries = build_parts(fs, looks, out_dir)
    for c in codes - set(looks):
        reasons[c] = "not_in_world"
    return apply_models(pkg, models, reasons, entries)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from ..config import PROJECT_ROOT, load_game
    from .archive import open_g3fs

    ap = argparse.ArgumentParser(prog="gothic_extract.g3.character_models", description="Gothic 3 character models")
    ap.add_argument("--dist-root", type=Path, default=PROJECT_ROOT / "dist")
    ap.add_argument("--slug", default="myrtana")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_game("g3")
    world = next(iter(cfg.worlds))
    r = add_g3_character_models(open_g3fs(cfg), cfg, world, args.dist_root / "g3" / args.slug)
    print(f"g3/{args.slug}: {r['with_model']}/{r['characters']} z modelem, {r['files']} plików "
          f"({r['glb_bytes'] / 1e6:.1f} MB glb), null: {r['null']} {r['null_codes']}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
