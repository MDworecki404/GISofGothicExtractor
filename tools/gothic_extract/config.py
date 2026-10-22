import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import zenkit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAMES_FILE = Path(__file__).with_name("games.toml")


@dataclass
class WorldEntry:
    slug: str
    name_pl: str
    provisional_name: bool = False  # name_pl is a working name, not taken from the game


@dataclass
class GameConfig:
    key: str
    root: Path
    version: zenkit.GameVersion
    vdf_files: list[str]
    script_dat: Path
    anchor_lon: float
    anchor_lat: float
    anchor_h: float
    world_roots: dict[str, list[str]] = field(default_factory=dict)
    exclude_functions: dict[str, list[str]] = field(default_factory=dict)  # per-world fnmatch patterns (debug/unused code)
    first_chapters: dict[str, int] = field(default_factory=dict)  # chapter in which a world is first entered
    skip_lod_polygons: bool = True  # False where ZenKit reports the LOD flag on nearly every polygon (G1)
    chapter_dispatcher: str | None = None  # function that branches on the new chapter (G1: B_KAPITELWECHSEL)
    worlds: dict[str, "WorldEntry"] = field(default_factory=dict)  # ZEN name (upper case) -> package slug and Polish name


def _list_vdfs(root: Path, pattern: str, exclude: list[str]) -> list[str]:
    files = sorted({p for p in root.glob(pattern) if p.is_file()}, key=lambda p: p.name.lower())
    return [
        str(p.relative_to(root))
        for p in files
        if not any(fnmatch.fnmatch(p.name.lower(), e.lower()) for e in exclude)
    ]


def load_game(key: str) -> GameConfig:
    with open(GAMES_FILE, "rb") as f:
        entry = tomllib.load(f)[key]
    root = PROJECT_ROOT / entry["root"]
    anchor = entry.get("anchor", {})
    return GameConfig(
        key=key,
        root=root,
        version=zenkit.GameVersion[entry["version"]],
        vdf_files=_list_vdfs(root, entry["vdf_glob"], entry.get("vdf_exclude", [])) if root.exists() else [],
        script_dat=root / entry["script_dat"],
        anchor_lon=float(anchor.get("lon", 0.0)),
        anchor_lat=float(anchor.get("lat", 0.0)),
        anchor_h=float(anchor.get("h", 0.0)),
        world_roots={k.upper(): v for k, v in entry.get("world_roots", {}).items()},
        exclude_functions={k.upper(): v for k, v in entry.get("exclude_functions", {}).items()},
        first_chapters={k.upper(): int(v) for k, v in entry.get("first_chapter", {}).items()},
        skip_lod_polygons=entry.get("skip_lod_polygons", True),
        chapter_dispatcher=entry.get("chapter_dispatcher"),
        worlds={k.upper(): WorldEntry(v["slug"], v["name_pl"], v.get("provisional_name", False))
                for k, v in entry.get("worlds", {}).items()},
    )


def native_path(path: Path) -> str:
    """Path string ZenKit can take: it encodes paths as windows-1252, so fall back to the 8.3 short name."""
    s = str(path)
    try:
        s.encode("windows-1252")
        return s
    except UnicodeEncodeError:
        pass
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(s, buf, len(buf)) and buf.value:
        try:
            buf.value.encode("windows-1252")
            return buf.value
        except UnicodeEncodeError:
            pass
    raise OSError(f"Path not representable for ZenKit (windows-1252, no 8.3 name): {s}")
