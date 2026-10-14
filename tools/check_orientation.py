"""Overlay extracted waypoints (in ENU metres) on the in-game world map.

The map document's Doc_SetLevelCoords(left_x, top_z, right_x, bottom_z) says which game
coordinates the map image spans. If the points line up with roads and towns on the map,
the axis convention East=+X, North=+Z is right (not mirrored).

Usage: python tools/check_orientation.py output/g2nk/newworld
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import zenkit  # noqa: E402

from gothic_extract.config import load_game  # noqa: E402
from gothic_extract.vfs import open_vfs  # noqa: E402

MAP_TEX = "MAP_NEWWORLD-C.TEX"
LEVEL_COORDS = (-28000, 50500, 95500, -42500)  # USE_MAP_NEWWORLD → Doc_SetLevelCoords


def main(out_dir: Path) -> None:
    cfg = load_game("g2nk")
    vfs = open_vfs(cfg)  # must outlive the node read
    tex = zenkit.Texture.load(vfs.find(MAP_TEX).open())
    w, h = tex.width_mipmap(0), tex.height_mipmap(0)
    img = np.frombuffer(tex.mipmap_rgba(0), dtype=np.uint8).reshape(h, w, 4)

    left, top, right, bottom = (v / 100 for v in LEVEL_COORDS)  # game X/Z → East/North metres
    fc = json.loads((out_dir / "waypoints.geojson").read_text("utf-8"))
    pts = [f["properties"] for f in fc["features"] if f["geometry"]["type"] == "Point"]
    east = np.array([p["game_pos"][0] / 100 for p in pts])
    north = np.array([p["game_pos"][2] / 100 for p in pts])
    city = np.array(["CITY" in p["name"] for p in pts])

    fig, ax = plt.subplots(figsize=(12, 9), dpi=110)
    ax.imshow(img, extent=(left, right, bottom, top))
    ax.scatter(east[~city], north[~city], s=2, c="red", label="waypoints")
    ax.scatter(east[city], north[city], s=3, c="blue", label="NW_CITY_* waypoints")
    ax.set_xlabel("East [m] (+X game)")
    ax.set_ylabel("North [m] (+Z game)")
    ax.legend(loc="lower right")
    ax.set_title("Khorinis: extracted waypoints over in-game map")
    dst = out_dir / "_check"
    dst.mkdir(exist_ok=True)
    fig.savefig(dst / "orientation_overlay.png", bbox_inches="tight")
    print(dst / "orientation_overlay.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
