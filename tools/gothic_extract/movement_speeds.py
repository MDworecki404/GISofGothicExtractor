"""Player movement speeds (m/s) measured from the HUMANS skeleton's looping animations.

Speed = horizontal root displacement over one loop / loop duration. The last frame of a loop repeats the first
pose, so a loop of N frames makes N-1 steps. Animation positions are in cm.
Writes `movement_speeds_m_s` (and the animations used) into a package's metadata.json:
python -m gothic_extract.movement_speeds --game g2nk --pkg dist/g2nk/khorinis [--pkg ...]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import zenkit

from .config import load_game
from .vfs import open_vfs, read_file

# movement -> looping animation (HUMANS.MDS)
ANIMATIONS = {
    "walk": "HUMANS-S_WALKL.MAN",
    "run": "HUMANS-S_RUNL.MAN",
    "sneak": "HUMANS-S_SNEAKL.MAN",
    "walk_armed": "HUMANS_1HST1-S_1HWALKL.MAN",
}


def loop_speed_m_s(data: bytes) -> float:
    anim = zenkit.ModelAnimation.load(data)
    steps = anim.frame_count - 1
    if steps < 1 or anim.fps <= 0 or anim.node_count < 1:
        raise ValueError("animation has no loop")
    first = anim.samples[0].position  # sample [frame * node_count + node]; node 0 is the root
    last = anim.samples[steps * anim.node_count].position
    return math.hypot(last[0] - first[0], last[2] - first[2]) / 100 / (steps / anim.fps)


def movement_speeds(vfs: zenkit.Vfs) -> dict[str, float]:
    out = {}
    for key, name in ANIMATIONS.items():
        data = read_file(vfs, name)
        if data is None:
            raise FileNotFoundError(f"{name} not found in the mounted archives")
        out[key] = round(loop_speed_m_s(data), 2)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.movement_speeds", description="Measure movement speeds from .MAN animations")
    ap.add_argument("--game", required=True, help="key from games.toml, e.g. g2nk")
    ap.add_argument("--pkg", type=Path, action="append", default=[], help="package whose metadata.json gets the speeds (repeatable)")
    args = ap.parse_args(argv)
    speeds = movement_speeds(open_vfs(load_game(args.game)))
    print(f"  movement_speeds_m_s: {speeds}")
    for pkg in args.pkg:
        path = pkg / "metadata.json"
        meta = json.loads(path.read_text("utf-8"))
        meta["movement_speeds_m_s"] = speeds
        meta["movement_speeds_animations"] = ANIMATIONS
        path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
