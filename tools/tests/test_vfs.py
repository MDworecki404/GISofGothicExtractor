import zenkit

from gothic_extract.config import native_path
from gothic_extract.vfs import read_file


def walk(node):
    for child in node.children:
        yield child
        if child.is_dir():
            yield from walk(child)


def base_newworld_bytes(cfg):
    vfs = zenkit.Vfs()
    vfs.mount_disk(native_path(cfg.root / "Data" / "Worlds.vdf"))
    return read_file(vfs, "NEWWORLD.ZEN")


def test_newworld_zen_comes_from_addon(g2_cfg, g2_vfs):
    data = read_file(g2_vfs, "NEWWORLD.ZEN")
    assert data is not None
    assert len(data) != len(base_newworld_bytes(g2_cfg))


def test_case_insensitive_lookup(g2_vfs):
    assert read_file(g2_vfs, "newworld.zen") == read_file(g2_vfs, "NEWWORLD.ZEN")


def test_textures_mounted(g2_vfs):
    assert any(n.name.upper().endswith("-C.TEX") for n in walk(g2_vfs.root))
