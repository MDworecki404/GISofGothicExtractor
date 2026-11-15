import zenkit

from .config import GameConfig, native_path


def _is_addon(name: str) -> bool:
    return "_addon" in name.lower()


def _is_mod(name: str) -> bool:
    return name.lower().endswith(".mod")


def open_vfs(cfg: GameConfig) -> zenkit.Vfs:
    """Mount all game VDFs; addon archives are mounted after the base ones and mod archives (.mod) last, both
    override earlier files."""
    vfs = zenkit.Vfs()
    ordered = sorted(cfg.vdf_files, key=lambda n: (_is_mod(n), _is_addon(n), n.lower()))
    for rel in ordered:
        behavior = zenkit.VfsOverwriteBehavior.ALL if _is_addon(rel) or _is_mod(rel) else zenkit.VfsOverwriteBehavior.OLDER
        vfs.mount_disk(native_path(cfg.root / rel), clobber=behavior)
    return vfs


def read_file(vfs: zenkit.Vfs, name: str) -> bytes | None:
    node = vfs.find(name)
    if node is None or not node.is_file():
        return None
    return node.data
