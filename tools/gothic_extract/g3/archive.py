"""Gothic 3 .pak archives (format G3V0) mounted as one read-only file system.

Header (48 bytes, `<6I3Q`): version, b"G3V0", revision, encryption, compression, reserved, offset of files,
offset of the folder tree, volume size. The root folder entry sits at the folder offset. Every entry: 3 × u64
file times, u64 size, u32 attributes. A folder (attr & 0x10): name, then two lists — u32 n + n entries
(sub-folders), u32 m + m entries (files). A file: u64 offset, u64 packed size, u64 size, u32 encryption,
u32 compression, name (full path), comment. A string is u32 length and, when > 0, length + 1 bytes (with the
terminating zero). Compression 2 with different sizes = zlib.

Patches: X.p00 overrides X.pak, X.p01 overrides X.p00, and so on.
"""
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from ..config import GameConfig


@dataclass
class PakEntry:
    path: str
    offset: int
    packed: int
    size: int
    compression: int


def _string(f) -> str:
    (n,) = struct.unpack("<I", f.read(4))
    return f.read(n + 1)[:-1].decode("latin-1") if n else ""


def read_pak_index(path: Path) -> list[PakEntry]:
    out: list[PakEntry] = []
    with open(path, "rb") as f:
        header = struct.unpack("<6I3Q", f.read(48))
        if header[1] != 0x30563347:  # b"G3V0"
            raise ValueError(f"{path}: not a G3V0 archive")
        f.seek(header[7])

        def folder_body():
            _string(f)
            for _ in range(2):
                (n,) = struct.unpack("<I", f.read(4))
                for _ in range(n):
                    entry()

        def entry():
            f.read(32)
            (attr,) = struct.unpack("<I", f.read(4))
            if attr & 0x10:
                folder_body()
                return
            offset, packed, size, _enc, comp = struct.unpack("<QQQII", f.read(32))
            name = _string(f)
            _string(f)  # comment: source path on the developers' machine
            out.append(PakEntry(name, offset, packed, size, comp))

        entry()
    return out


_PATCH_RE = re.compile(r"\.p(\d\d)$", re.I)


def _mount_order(path: str) -> tuple[str, int]:
    """X.pak first, then X.p00, X.p01 … (a later mount overrides an earlier one)."""
    p = Path(path)
    m = _PATCH_RE.search(p.name)
    return (p.stem.lower(), int(m.group(1)) + 1 if m else 0)


class G3Fs:
    def __init__(self, paths: list[Path]):
        self._files: dict[str, tuple[Path, PakEntry]] = {}
        for pak in sorted(paths, key=lambda p: _mount_order(str(p))):
            for e in read_pak_index(pak):
                self._files[e.path.lower()] = (pak, e)

    def _get(self, path: str):
        return self._files.get(path.replace("\\", "/").lower())

    def find(self, path: str) -> bytes | None:
        hit = self._get(path)
        if hit is None:
            return None
        pak, e = hit
        with open(pak, "rb") as f:
            f.seek(e.offset)
            data = f.read(e.packed)
        return zlib.decompress(data) if e.compression == 2 and e.packed != e.size else data

    def find_name(self, name: str) -> bytes | None:
        """A file by its name alone (any folder), as materials and meshes reference textures and materials."""
        if not hasattr(self, "_by_name"):
            self._by_name = {key.rsplit("/", 1)[-1]: key for key in self._files}
        key = self._by_name.get(name.replace("\\", "/").rsplit("/", 1)[-1].lower())
        return self.find(key) if key else None

    def source(self, path: str) -> str | None:
        hit = self._get(path)
        return hit[0].name if hit else None

    def list(self, prefix: str = "", suffix: str = "") -> list[str]:
        pre, suf = prefix.lower(), suffix.lower()
        return sorted(e.path for key, (_, e) in self._files.items() if key.startswith(pre) and key.endswith(suf))


def open_g3fs(cfg: GameConfig) -> G3Fs:
    return G3Fs([cfg.root / rel for rel in cfg.pak_files])
