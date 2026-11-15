import struct

import numpy as np
import pytest

from gothic_extract.g3.genome import FormatError
from gothic_extract.g3.navnet import nav_files, nav_net, vector_array


def _raw(points):
    return b"\x01" + struct.pack("<I", len(points)) + b"".join(struct.pack("<3f", *p) for p in points)


def test_vector_array_reads_points():
    assert vector_array(_raw([(1, 2, 3), (4.5, 5, 6)])).tolist() == [[1, 2, 3], [4.5, 5, 6]]
    assert vector_array(_raw([])).shape == (0, 3)


@pytest.mark.parametrize("raw", [b"", b"\x02\x00\x00\x00\x00", _raw([(1, 2, 3)])[:-1]])
def test_vector_array_rejects_bad_data(raw):
    with pytest.raises(FormatError):
        vector_array(raw)


@pytest.fixture(scope="module")
def net(g3_fs):
    return nav_net(g3_fs, "G3_World_01")


def test_only_myrtana_navzones(g3_fs):
    files = nav_files(g3_fs, "G3_World_01")
    assert len(files) == 25 and all("/Myrtana/" in p for p in files)


def test_net_is_a_valid_graph(net):
    waypoints, edges = net
    names = [w.name for w in waypoints]
    assert len(names) == len(set(names)) and names
    known = set(names)
    pairs = {(e.a, e.b) for e in edges}
    assert all(a in known and b in known and a != b for a, b in pairs)
    assert any(n.startswith("NAVPATH_") for n in names) and any(n.startswith("NAVZONE_") for n in names)
    assert all(w.source == "navzones" and not w.under_water for w in waypoints)


def test_net_lies_in_the_world(net):
    pos = np.array([w.pos for w in net[0]]) / 100  # metres
    assert abs(pos[:, 0]).max() < 6000 and abs(pos[:, 2]).max() < 6000
    assert -300 < pos[:, 1].min() and pos[:, 1].max() < 600
