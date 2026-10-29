import json

import numpy as np
import pytest
import tifffile
from test_ortho_glbmesh import make_glb

from gothic_extract.ortho.__main__ import build_ortho, check_size


def make_package(tmp_path, pos_scale=1.0, texel_px=100):
    """Package with a 1 m quad at E 0..1, N 0..1 (flat, red), anchor on the equator."""
    pkg = tmp_path / "dist" / "g2nk" / "tiny"
    pkg.mkdir(parents=True)
    (pkg / "metadata.json").write_text(json.dumps({"anchor": {"lon": 0.0, "lat": 0.0, "h": 0.0}}), "utf-8")
    tex = np.full((texel_px, texel_px, 4), 255, np.uint8)
    tex[..., 1:3] = 0
    make_glb(pkg / "world.glb", pos=np.array([[0, 0, 0], [1, 0, 0], [1, 0, -1], [0, 0, -1]], np.float32) * pos_scale,
             texture=tex)
    return pkg


def test_check_size_refuses_whole_world_at_1cm():
    with pytest.raises(ValueError, match="--bbox"):
        check_size(300_000, 300_000, bbox_given=False)


def test_check_size_allows_with_bbox():
    check_size(300_000, 300_000, bbox_given=True)
    check_size(1000, 1000, bbox_given=False)


def test_build_ortho_writes_tif_and_json(tmp_path):
    pkg = make_package(tmp_path)
    info = build_ortho(pkg, gsd=0.25, bbox=None, include_vobs=False, out=None)
    tif = pkg / "ortho" / "tiny_25cm.tif"
    assert tif.exists()
    assert info["crs"] == "EPSG:4326" and (info["width"], info["height"]) == (4, 4)
    assert json.loads(tif.with_suffix(".json").read_text("utf-8"))["gsd"] == 0.25
    data = tifffile.imread(tif)
    assert data.shape == (4, 4, 4) and (data[..., 3] == 255).all() and (data[..., 0] == 255).all()


def test_bbox_outside_world_gives_transparent_file(tmp_path):
    pkg = make_package(tmp_path)
    build_ortho(pkg, gsd=0.5, bbox=(100, 100, 102, 102), include_vobs=False, out=tmp_path / "o.tif")
    assert (tifffile.imread(tmp_path / "o.tif")[..., 3] == 0).all()


def test_warns_when_finer_than_texture(tmp_path):
    pkg = make_package(tmp_path, texel_px=10)  # 10 cm per texel
    info = build_ortho(pkg, gsd=0.01, bbox=(0, 0, 1, 1), include_vobs=False, out=tmp_path / "o.tif")
    assert any("tekstur" in w for w in info["warnings"])
    assert info["texel_cm_median"] == pytest.approx(10.0)
