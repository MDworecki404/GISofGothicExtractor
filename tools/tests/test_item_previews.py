import json

import numpy as np
import pygltflib
import pytest

from gothic_extract.catalog import ItemDef
from gothic_extract.vob_models import INSTANCING, export_item_previews

CODES = ["ITPL_PERM_HERB", "ITFO_APPLE", "ITKE_DEXTER", "ITKE_FINGERS", "ITRW_BOW_L_01"]


@pytest.fixture(scope="module")
def previews(tmp_path_factory, g2_vfs, catalog):
    models_dir = tmp_path_factory.mktemp("models")
    subset = {c: catalog[c] for c in CODES}
    subset["ITXX_NO_VISUAL"] = ItemDef("ITXX_NO_VISUAL", "Bez modelu", "Różne", 1, 0, 0, "", "")
    report = export_item_previews(g2_vfs, subset, models_dir / "previews")
    return models_dir, report


def _positions(g, blob, prim):
    acc = g.accessors[prim.attributes.POSITION]
    view = g.bufferViews[acc.bufferView]
    return np.frombuffer(blob, dtype=np.float32, count=acc.count * 3, offset=view.byteOffset).reshape(-1, 3)


def _bounds(path):
    g = pygltflib.GLTF2().load(str(path))
    blob = g.binary_blob()
    pts = np.vstack([_positions(g, blob, p) for p in g.meshes[0].primitives])
    return g, pts.min(axis=0), pts.max(axis=0)


def test_single_copy_without_instancing(previews):
    models_dir, _ = previews
    g, _, _ = _bounds(models_dir / "previews" / "itpl_perm_herb.glb")
    assert INSTANCING not in (g.extensionsUsed or [])
    assert len(g.nodes) == 1 and not (g.nodes[0].extensions or {})
    assert g.nodes[0].translation in (None, [0, 0, 0]) and g.nodes[0].matrix is None


def test_centered_horizontally_and_standing_on_zero(previews):
    models_dir, _ = previews
    _, lo, hi = _bounds(models_dir / "previews" / "itfo_apple.glb")
    assert (lo[0] + hi[0]) / 2 == pytest.approx(0, abs=1e-4)
    assert (lo[2] + hi[2]) / 2 == pytest.approx(0, abs=1e-4)
    assert lo[1] == pytest.approx(0, abs=1e-4)
    assert 0.02 < hi[1] < 1.0  # an apple is a few cm, in metres


def test_same_visual_shares_one_file(previews):
    _, report = previews
    assert report.file_for["ITKE_DEXTER"] == report.file_for["ITKE_FINGERS"] == "itke_key_03.glb"


def test_mms_and_missing_visual_are_null(previews):
    _, report = previews
    assert report.file_for["ITRW_BOW_L_01"] is None and report.reason["ITRW_BOW_L_01"] == "unsupported_visual"
    assert report.file_for["ITXX_NO_VISUAL"] is None and report.reason["ITXX_NO_VISUAL"] == "no_visual"


def test_textures_resolve_through_parent_textures(previews):
    models_dir, _ = previews
    for f in (models_dir / "previews").glob("*.glb"):
        g = pygltflib.GLTF2().load(str(f))
        for img in g.images:
            assert img.uri.startswith("../textures/")
            assert (models_dir / "previews" / img.uri).resolve().exists()


def test_previews_index(previews):
    models_dir, _ = previews
    index = json.loads((models_dir / "previews" / "index.json").read_text("utf-8"))
    by_file = {e["file"]: e for e in index["previews"]}
    assert set(by_file) == {"itpl_perm_herb.glb", "itfo_apple.glb", "itke_key_03.glb"}
    e = by_file["itfo_apple.glb"]
    assert e["visual"] == "ITFO_APPLE.3DS" and e["triangles"] > 0
    assert set(e["bounds_m"]) == {"x", "y", "z"} and all(v > 0 for v in e["bounds_m"].values())
