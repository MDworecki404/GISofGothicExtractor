import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gothic_extract.config import load_game  # noqa: E402


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
