import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gothic_extract.config import load_game  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: reads every file of a game (run with -m \"not slow\" to skip)")


@pytest.fixture(scope="session")
def g2_cfg():
    cfg = load_game("g2nk")
    if not cfg.root.exists():
        pytest.skip("Gothic II folder not present")
    return cfg


@pytest.fixture(scope="session")
def g2_vfs(g2_cfg):
    from gothic_extract.vfs import open_vfs

    return open_vfs(g2_cfg)


@pytest.fixture(scope="session")
def newworld(g2_cfg, g2_vfs):
    from gothic_extract.world_data import load_world

    return load_world(g2_vfs, "NEWWORLD.ZEN", g2_cfg.version)


@pytest.fixture(scope="session")
def g2_vm(g2_cfg):
    from gothic_extract.script_vm import make_vm

    return make_vm(g2_cfg.script_dat)


@pytest.fixture(scope="session")
def catalog(g2_vm):
    from gothic_extract.catalog import build_item_catalog

    return build_item_catalog(g2_vm)


@pytest.fixture(scope="session")
def resolver(newworld):
    from gothic_extract.world_data import PointResolver

    _, wd = newworld
    return PointResolver(wd.waypoints, wd.freepoints)


@pytest.fixture(scope="session")
def other_world_fns(g2_vm, g2_cfg):
    from gothic_extract.daedalus_scan import other_world_functions

    return other_world_functions(g2_vm, g2_cfg.world_roots, "NEWWORLD")


@pytest.fixture(scope="session")
def npcs(g2_vm, resolver, other_world_fns):
    from gothic_extract.npcs import extract_npcs

    return extract_npcs(g2_vm, resolver, other_world_fns)


@pytest.fixture(scope="session")
def script_items(g2_vm, resolver, other_world_fns):
    from gothic_extract.npcs import extract_script_items

    return extract_script_items(g2_vm, resolver, other_world_fns)


@pytest.fixture(scope="session")
def g3_cfg():
    cfg = load_game("g3")
    if not cfg.root.exists():
        pytest.skip("Gothic 3 folder not present")
    return cfg


@pytest.fixture(scope="session")
def g3_fs(g3_cfg):
    from gothic_extract.g3.archive import open_g3fs

    return open_g3fs(g3_cfg)
