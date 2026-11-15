"""Game coordinates (cm, Y-up) → local ENU metres → WGS84 lon/lat on a tangent plane."""
import math

WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3


def game_to_enu(x: float, y: float, z: float) -> tuple[float, float, float]:
    """East = +X, North = +Z, Up = +Y; centimetres → metres."""
    return (x / 100, z / 100, y / 100)


def enu_to_lonlat(e: float, n: float, u: float, lon0: float, lat0: float, h0: float) -> tuple[float, float, float]:
    phi = math.radians(lat0)
    w = 1 - WGS84_E2 * math.sin(phi) ** 2
    m = WGS84_A * (1 - WGS84_E2) / w**1.5  # meridian radius of curvature
    nr = WGS84_A / math.sqrt(w)  # prime vertical radius of curvature
    lat = lat0 + math.degrees(n / m)
    lon = lon0 + math.degrees(e / (nr * math.cos(phi)))
    return (lon, lat, h0 + u)


def game_to_lonlat(pos: tuple[float, float, float], cfg) -> tuple[float, float, float]:
    e, n, u = game_to_enu(*pos)
    return enu_to_lonlat(e, n, u, cfg.anchor_lon, cfg.anchor_lat, cfg.anchor_h)


def lonlat_to_enu(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    """Inverse of enu_to_lonlat for the horizontal part: (east, north) metres from the anchor."""
    phi = math.radians(lat0)
    w = 1 - WGS84_E2 * math.sin(phi) ** 2
    m = WGS84_A * (1 - WGS84_E2) / w**1.5
    nr = WGS84_A / math.sqrt(w)
    return (math.radians(lon - lon0) * nr * math.cos(phi), math.radians(lat - lat0) * m)
