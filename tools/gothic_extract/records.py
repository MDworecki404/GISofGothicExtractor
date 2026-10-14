from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]


@dataclass
class VobRec:
    id: int
    vob_type: str
    name: str
    visual: str | None
    pos: Vec3
    rot: list[float]  # 3x3, row-major
    parent_id: int | None
    show_visual: bool = True


@dataclass
class ItemRec:
    code: str
    amount: int
    pos: Vec3
    source: str  # "zen" | "script"
    vob_id: int | None
    spot: str | None


@dataclass
class ContainerRec:
    vob_id: int
    name: str
    visual: str | None
    pos: Vec3
    locked: bool
    key: str | None
    pick_string: str | None
    contents: list[tuple[str, int]]


@dataclass
class WaypointRec:
    name: str
    pos: Vec3
    is_free_point: bool
    under_water: bool


@dataclass
class WayEdgeRec:
    a: str
    b: str


@dataclass
class WorldData:
    vobs: list[VobRec] = field(default_factory=list)
    items: list[ItemRec] = field(default_factory=list)
    containers: list[ContainerRec] = field(default_factory=list)
    waypoints: list[WaypointRec] = field(default_factory=list)
    edges: list[WayEdgeRec] = field(default_factory=list)
    freepoints: list[WaypointRec] = field(default_factory=list)
