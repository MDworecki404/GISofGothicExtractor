"""Pixel grid of the orthophoto: ENU metres around the anchor <-> a regular EPSG:4326 grid."""
import math
from dataclasses import dataclass

from ..coords import enu_to_lonlat


@dataclass(frozen=True)
class Grid:
    e0: float  # upper-left corner, ENU metres from the anchor
    n1: float
    gsd: float  # metres per pixel
    width: int
    height: int
    lon_min: float
    lat_max: float
    dx_deg: float
    dy_deg: float


def pixel_size_deg(gsd: float, lat0: float) -> tuple[float, float]:
    lon, lat, _ = enu_to_lonlat(gsd, gsd, 0.0, 0.0, lat0, 0.0)
    return lon, lat - lat0


def make_grid(bbox: tuple[float, float, float, float], gsd: float, lon0: float, lat0: float) -> Grid:
    """bbox = (e0, n0, e1, n1) in ENU metres from the anchor."""
    e0, n0, e1, n1 = bbox
    lon, lat, _ = enu_to_lonlat(e0, n1, 0.0, lon0, lat0, 0.0)
    dx, dy = pixel_size_deg(gsd, lat0)
    return Grid(e0, n1, gsd, math.ceil((e1 - e0) / gsd), math.ceil((n1 - n0) / gsd), lon, lat, dx, dy)
