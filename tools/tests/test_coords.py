import pytest

from gothic_extract.coords import enu_to_lonlat, game_to_enu


def test_axes():
    assert game_to_enu(100, 200, 300) == (1.0, 3.0, 2.0)


def test_origin_maps_to_anchor():
    assert enu_to_lonlat(0, 0, 0, 10.0, 50.0, 5.0) == pytest.approx((10.0, 50.0, 5.0))


def test_1km_east_at_equator():
    lon, lat, h = enu_to_lonlat(1000, 0, 0, 0, 0, 0)
    assert lon == pytest.approx(0.0089831528, rel=1e-6)
    assert lat == pytest.approx(0)


def test_1km_north_at_equator():
    lon, lat, _ = enu_to_lonlat(0, 1000, 0, 0, 0, 0)
    assert lat == pytest.approx(0.0090436948, rel=1e-6)
