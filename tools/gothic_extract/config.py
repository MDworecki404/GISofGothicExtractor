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
    version: zenkit.GameVersion | None  # None for the Genome engine (G3)
    vdf_files: list[str]
    script_dat: Path | None
    anchor_lon: float
    anchor_lat: float
    anchor_h: float
    world_roots: dict[str, list[str]] = field(default_factory=dict)
    exclude_functions: dict[str, list[str]] = field(default_factory=dict)  # per-world fnmatch patterns (debug/unused code)
    first_chapters: dict[str, int] = field(default_factory=dict)  # chapter in which a world is first entered
    chapter_dispatcher: str | None = None  # function that branches on the new chapter (G1: B_KAPITELWECHSEL)
    worlds: dict[str, "WorldEntry"] = field(default_factory=dict)  # ZEN name (upper case) -> package slug and Polish name
    engine: str = "zengin"  # "zengin" (G1, G2) or "genome" (G3)
    pak_files: list[str] = field(default_factory=list)  # G3: .pak/.pNN archives relative to root
    sector_exclude: list[str] = field(default_factory=list)  # G3: fnmatch patterns of sectors left out
    routine_slots: dict[str, list[str]] = field(default_factory=dict)  # G3: routine point kind -> "HH:MM–HH:MM" slots
    include_disabled_sectors: bool = False  # G3: also sectors =false in the world file (switched on by quests)


def _list_vdfs(root: Path, pattern: str | list[str], exclude: list[str]) -> list[str]:
    patterns = [pattern] if isinstance(pattern, str) else pattern
    files = sorted({p for pat in patterns for p in root.glob(pat) if p.is_file()}, key=lambda p: p.name.lower())
    return [
        str(p.relative_to(root))
        for p in files
        if not any(fnmatch.fnmatch(p.name.lower(), e.lower()) for e in exclude)
    ]


def _materialize_script_dat(root: Path, vdf_files: list[str], inner: str, key: str) -> Path:
    """Mods keep the compiled scripts inside a .mod archive (the loose GOTHIC.DAT is an empty placeholder), but
    ZenKit's script loader needs a real file: copy it from the mounted archives to output/<key>/_scripts/."""
    from .vfs import open_vfs, read_file

    dst = PROJECT_ROOT / "output" / key / "_scripts" / Path(inner).name
    cfg = GameConfig(key, root, None, vdf_files, None, 0.0, 0.0, 0.0)
    data = read_file(open_vfs(cfg), Path(inner).name)
    if data is None:
        raise FileNotFoundError(f"{inner} not found in the archives of {key}")
    if not dst.exists() or dst.read_bytes() != data:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    return dst


def load_game(key: str) -> GameConfig:
    with open(GAMES_FILE, "rb") as f:
        entry = tomllib.load(f)[key]
    root = PROJECT_ROOT / entry["root"]
    anchor = entry.get("anchor", {})
    engine = entry.get("engine", "zengin")
    vdf_files = _list_vdfs(root, entry["vdf_glob"], entry.get("vdf_exclude", [])) if "vdf_glob" in entry and root.exists() else []
    if "script_dat_in_archive" in entry and vdf_files:
        script_dat = _materialize_script_dat(root, vdf_files, entry["script_dat_in_archive"], key)
    else:
        script_dat = root / entry["script_dat"] if "script_dat" in entry else None
    return GameConfig(
        key=key,
        root=root,
        version=zenkit.GameVersion[entry["version"]] if "version" in entry else None,
        vdf_files=vdf_files,
        script_dat=script_dat,
        anchor_lon=float(anchor.get("lon", 0.0)),
        anchor_lat=float(anchor.get("lat", 0.0)),
        anchor_h=float(anchor.get("h", 0.0)),
        world_roots={k.upper(): v for k, v in entry.get("world_roots", {}).items()},
        exclude_functions={k.upper(): v for k, v in entry.get("exclude_functions", {}).items()},
        first_chapters={k.upper(): int(v) for k, v in entry.get("first_chapter", {}).items()},
        chapter_dispatcher=entry.get("chapter_dispatcher"),
        worlds={k.upper(): WorldEntry(v["slug"], v["name_pl"], v.get("provisional_name", False))
                for k, v in entry.get("worlds", {}).items()},
        engine=engine,
        pak_files=_list_vdfs(root, entry["pak_glob"], entry.get("pak_exclude", [])) if "pak_glob" in entry and root.exists() else [],
        sector_exclude=entry.get("sector_exclude", []),
        routine_slots=entry.get("routine_slots", {}),
        include_disabled_sectors=entry.get("include_disabled_sectors", False),
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
