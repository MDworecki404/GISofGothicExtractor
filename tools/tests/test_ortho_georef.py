import pytest

from gothic_extract.coords import enu_to_lonlat
from gothic_extract.ortho.georef import make_grid, pixel_size_deg


@pytest.mark.parametrize("lat0", [0.0, 50.0])
def test_pixel_size_matches_enu_to_lonlat(lat0):
    dx, dy = pixel_size_deg(1.0, lat0)
    assert dx == pytest.approx(enu_to_lonlat(1, 0, 0, 0, lat0, 0)[0], rel=1e-9)
    assert dy == pytest.approx(enu_to_lonlat(0, 1, 0, 0, lat0, 0)[1] - lat0, rel=1e-9)


def test_grid_size_and_corner():
    g = make_grid((0, 0, 10, 5), 0.25, 0.0, 0.0)
    assert (g.width, g.height) == (40, 20)
    lon, lat, _ = enu_to_lonlat(0, 5, 0, 0.0, 0.0, 0)
    assert g.lon_min == pytest.approx(lon) and g.lat_max == pytest.approx(lat)
    assert (g.e0, g.n1) == (0, 5)


def test_grid_rounds_up():
    assert make_grid((0, 0, 10.1, 5), 1.0, 0.0, 0.0).width == 11
