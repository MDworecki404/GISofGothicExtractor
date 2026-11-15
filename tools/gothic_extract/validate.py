"""Validate built geoportal packages (every world of g1 and g2nk).

python -m gothic_extract.validate [--dist dist] [--game g1 ...]
Checks per package: files listed in package.files exist, JSON parses, counts match the content, search index ids are
unique, every `ref` points at an existing object, every quest in the index has an entry in quests.json (and back),
every character/item marked in_index points at an index entry, quest stage order (package version 6: requires exist and
form no cycle, level = longest path, `order` follows the 80 % rule, places finite, stages_with_place), locations.json: unique ids,
order (kind, id), kinds and name sources, finite coordinates, `waypoint` exists in waypoints.json, `passage` only on
kind passage with an existing `to_world`, models referenced by the data exist, optional item
`description` is a non-empty text different from `name` (warning: names shared by several codes without one),
waypoints.json (if present): format version, edge indices in range, no loops or duplicate edges, no TOT, unique
names, nodes inside the world outline (world.glb bounds), graph components (largest one is reported).
Exit code 1 when any package has errors.
"""
import argparse
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import PROJECT_ROOT
from .coords import lonlat_to_enu
from .descriptions import iter_item_records

PACKAGE_VERSION = 6
WAYPOINTS_VERSION = 1
LOCATIONS_VERSION = 1
LOCATION_KINDS = ["camp", "town", "district", "building", "cave", "region", "landmark", "passage"]
LOCATION_NAME_SOURCES = {"game", "derived", "code"}
OUTLINE_MARGIN_M = 50.0  # waypoints may sit slightly outside the rendered mesh
# place kind -> layer whose feature ids its `ref` must match
REF_LAYER = {"ground": "items", "script": "items", "container": "containers", "npc": "npcs", "spawn": "npcs",
             "routine": "character_places"}
LAYERS = ["items", "containers", "characters", "npcs", "character_places"]


@dataclass
class PackageReport:
    name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    info: list[str] = field(default_factory=list)


@dataclass
class Report:
    packages: list[PackageReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.errors for p in self.packages)

    def text(self, max_lines: int = 8) -> str:
        lines = [f"Walidacja paczek: {len(self.packages)}, błędy: {sum(len(p.errors) for p in self.packages)}, "
                 f"ostrzeżenia: {sum(len(p.warnings) for p in self.packages)}"]
        for p in self.packages:
            status = "OK" if not p.errors else "BŁĘDY"
            lines.append(f"  {p.name}: {status} (błędy {len(p.errors)}, ostrzeżenia {len(p.warnings)})")
            lines += [f"    {m}" for m in p.info]
            for label, items in (("błąd", p.errors), ("ostrzeżenie", p.warnings)):
                lines += [f"    {label}: {m}" for m in items[:max_lines]]
                if len(items) > max_lines:
                    lines.append(f"    … i {len(items) - max_lines} więcej ({label})")
        return "\n".join(lines)


def _load(pkg: Path, name: str, r: PackageReport):
    try:
        return json.loads((pkg / name).read_text("utf-8"))
    except (OSError, ValueError) as e:
        r.errors.append(f"{name}: nie da się wczytać ({e})")
        return None


def _check_metadata(pkg: Path, game: str, meta: dict, r: PackageReport) -> None:
    package = meta.get("package", {})
    if meta.get("game") != game:
        r.errors.append(f"metadata.game = {meta.get('game')!r}, oczekiwano {game!r}")
    if package.get("version") != PACKAGE_VERSION:
        r.errors.append(f"package.version = {package.get('version')!r}, oczekiwano {PACKAGE_VERSION}")
    for key in ("anchor", "axes", "gltf_axes", "movement_speeds_m_s", "movement_speeds_animations", "guild_names"):
        if key not in meta:
            r.errors.append(f"metadata.json: brak pola {key}")
    for f in package.get("files", []):
        target = pkg / f
        if not (target.is_dir() if f.endswith("/") else target.is_file()):
            r.errors.append(f"package.files: brak {f}")
    for p in sorted(pkg.rglob("*.json")) + sorted(pkg.rglob("*.geojson")):
        try:
            json.loads(p.read_text("utf-8"))
        except ValueError as e:
            r.errors.append(f"{p.relative_to(pkg).as_posix()}: niepoprawny JSON ({e})")


REQUIRES_SOURCES = {"condition", "dialog_order", "script_order"}
_PLACE_KEYS = {"lon", "lat", "h", "label", "npc_code", "waypoint"}


def _check_quest_order(q: dict, r: PackageReport) -> None:
    """Stage order (package v6): requires point at existing stages, the graph has no cycle, level = longest path from a
    start, `order` follows the 80% rule, places are finite, stages_with_place matches."""
    stages = q["stages"]
    by_seq = {s["seq"]: s for s in stages}
    if len(by_seq) != len(stages):
        r.errors.append(f"{q['id']}: seq etapów się powtarzają")
        return
    for s in stages:
        missing = [k for k in ("requires", "requires_source", "level", "alternative_group", "place") if k not in s]
        if missing:
            r.errors.append(f"{q['id']} etap {s['seq']}: brak pól {missing}")
            return
        if s["requires_source"] not in REQUIRES_SOURCES:
            r.errors.append(f"{q['id']} etap {s['seq']}: requires_source {s['requires_source']!r}")
        bad = [x for x in s["requires"] if x not in by_seq or x == s["seq"]]
        if bad or s["requires"] != sorted(set(s["requires"])):
            r.errors.append(f"{q['id']} etap {s['seq']}: requires {s['requires']} wskazuje poza etapy / siebie / bez porządku")
            return
        if s["alternative_group"] is not None and not isinstance(s["alternative_group"], str):
            r.errors.append(f"{q['id']} etap {s['seq']}: alternative_group {s['alternative_group']!r}")
        pl = s["place"]
        if pl is not None and (not _PLACE_KEYS <= set(pl) or not all(math.isfinite(pl[k]) for k in ("lon", "lat", "h"))):
            r.errors.append(f"{q['id']} etap {s['seq']}: place niepoprawne {pl!r}")
    level: dict[int, int] = {}

    def depth(seq: int, path: tuple[int, ...]) -> int | None:
        if seq in path:
            return None
        if seq not in level:
            ds = [depth(p, path + (seq,)) for p in by_seq[seq]["requires"]]
            if any(d is None for d in ds):
                return None
            level[seq] = 1 + max(ds, default=-1)
        return level[seq]

    for seq in by_seq:
        if depth(seq, ()) is None:
            r.errors.append(f"{q['id']}: cykl w requires (etap {seq})")
            return
    for s in stages:
        if s["level"] != level[s["seq"]]:
            r.errors.append(f"{q['id']} etap {s['seq']}: level {s['level']} zamiast {level[s['seq']]}")
    known = sum(s["requires_source"] != "script_order" for s in stages)
    want = "dependency" if stages and known * 5 >= len(stages) * 4 else "script"
    if q["order"] != want:
        r.errors.append(f"{q['id']}: order {q['order']!r}, a {known} z {len(stages)} etapów ma znane źródło (-> {want!r})")
    if q.get("stages_with_place") != sum(s["place"] is not None for s in stages):
        r.errors.append(f"{q['id']}: stages_with_place {q.get('stages_with_place')} nie zgadza się z etapami")


def _check_quests(qlist: list[dict], meta: dict, entries: list[dict], entry_set: set[str],
                  ids: dict[str, set[str]], r: PackageReport) -> None:
    quest_entries = {e["id"] for e in entries if e["type"] == "quest"}
    quest_ids = {q["id"] for q in qlist}
    if quest_entries - quest_ids:
        r.errors.append(f"quest w indeksie bez wpisu w quests.json: {sorted(quest_entries - quest_ids)[:5]}")
    if quest_ids - quest_entries:
        r.errors.append(f"wpis w quests.json bez wpisu w indeksie: {sorted(quest_ids - quest_entries)[:5]}")
    if len(quest_ids) != len(qlist):
        r.errors.append("quests.json: id się powtarzają")
    bad_places = 0
    for q in qlist:
        for key in ("characters", "items"):
            for x in q[key]:
                if x["in_index"] != (x["id"] is not None) or (x["id"] is not None and x["id"] not in entry_set):
                    r.errors.append(f"{q['id']}: {key} {x['code']} in_index={x['in_index']} id={x['id']!r} "
                                    "nie pasuje do indeksu")
        bad_places += sum(pl.get("ref") not in ids.get(REF_LAYER.get(pl["kind"], "npcs"), ()) for pl in q["places"])
        if meta.get("world") not in q.get("worlds", []):
            r.errors.append(f"{q['id']}: świat {meta.get('world')} nie występuje w worlds {q.get('worlds')}")
        if meta.get("package", {}).get("version", 0) >= 6:
            _check_quest_order(q, r)
    if bad_places:
        r.errors.append(f"quests.json: {bad_places} miejsc ze ref spoza warstw")


def _check_descriptions(pkg: Path, layers: dict, index: dict, quests: dict, r: PackageReport) -> None:
    """Optional `description` on item records: a non-empty, trimmed string different from `name`. Warns about
    names still carried by several item codes without a description (the app cannot tell those apart)."""
    data = {f"{n}.geojson": v for n, v in layers.items()} | {"search_index.json": index, "quests.json": quests}
    if (pkg / "treasure_sets.json").is_file():
        data["treasure_sets.json"] = _load(pkg, "treasure_sets.json", r)
    bad = Counter()
    plain: dict[str, set[str]] = defaultdict(set)
    for name, rec in iter_item_records({k: v for k, v in data.items() if v is not None}):
        if "description" not in rec:
            if rec.get("name"):
                plain[rec["name"]].add(rec["code"])
            continue
        d = rec["description"]
        if not isinstance(d, str) or not d.strip() or d != d.strip() or d == rec.get("name"):
            bad[name] += 1
    for name, n in sorted(bad.items()):
        r.errors.append(f"{name}: {n} rekordów z niepoprawnym description (ma być niepustym tekstem bez spacji "
                        "na brzegach, innym niż name)")
    groups = {n: cs for n, cs in plain.items() if len(cs) > 1}
    if groups:
        sample = "; ".join(f"„{n}” ({len(cs)})" for n, cs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:5])
        r.warnings.append(f"{len(groups)} nazw przy kilku kodach przedmiotów bez description, np. {sample}")


def _glb_bounds(path: Path) -> tuple[list[float], list[float]] | None:
    """Union of the POSITION accessor min/max of a .glb (glTF metres), or None when it cannot be read."""
    try:
        with path.open("rb") as f:
            head = f.read(20)
            length = struct.unpack("<I", head[12:16])[0]
            doc = json.loads(f.read(length))
    except (OSError, ValueError, struct.error):
        return None
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            acc = doc["accessors"][prim["attributes"]["POSITION"]]
            if "min" in acc and "max" in acc:
                lo = [min(a, b) for a, b in zip(lo, acc["min"])]
                hi = [max(a, b) for a, b in zip(hi, acc["max"])]
    return (lo, hi) if math.isfinite(lo[0]) else None


def _check_waypoints(pkg: Path, meta: dict, feats_npcs: list[dict], places: list[dict], r: PackageReport) -> None:
    """waypoints.json (absent in G3): format version, edge indices in range, no loops or duplicate edges, no TOT,
    unique names, every node inside the world's outline (world.glb bounds + margin), graph components (the largest
    one is reported)."""
    package = meta.get("package", {})
    path = pkg / "waypoints.json"
    if (pkg / "waypoints.geojson").exists():
        r.errors.append("waypoints.geojson w paczce (do paczki trafia tylko waypoints.json)")
    if not path.is_file():
        if "waypoints" in package.get("counts", {}):
            r.errors.append("package.counts ma waypoints, ale brak waypoints.json")
        return
    data = _load(pkg, "waypoints.json", r)
    if data is None:
        return
    if data.get("version") != WAYPOINTS_VERSION:
        r.errors.append(f"waypoints.json: version = {data.get('version')!r}, oczekiwano {WAYPOINTS_VERSION}")
    for key in ("game", "world"):
        if data.get(key) != meta.get(key):
            r.errors.append(f"waypoints.json: {key} = {data.get(key)!r}, w metadata {meta.get(key)!r}")
    nodes, edges = data.get("nodes", []), data.get("edges", [])
    malformed = [n for n in nodes if not (isinstance(n, list) and len(n) == 5 and isinstance(n[0], str)
                                          and n[4] in (0, 1))]
    if malformed:
        r.errors.append(f"waypoints.json: {len(malformed)} węzłów w złym formacie, np. {malformed[:2]}")
        return
    r.counts["waypoints"], r.counts["waypoint_edges"] = len(nodes), len(edges)
    for key, value in (("waypoints", len(nodes)), ("waypoint_edges", len(edges))):
        if package.get("counts", {}).get(key) != value:
            r.errors.append(f"counts.{key} = {package.get('counts', {}).get(key)!r}, w danych {value}")
    names = [n[0] for n in nodes]
    dup = [n for n, c in Counter(names).items() if c > 1]
    if dup:
        r.errors.append(f"waypoints.json: {len(dup)} powtórzonych nazw węzłów, np. {dup[:3]}")
    if "TOT" in names:
        r.errors.append("waypoints.json: węzeł TOT (ma być usunięty z paczki)")
    count = len(nodes)
    bad_range = [e for e in edges if not (isinstance(e, list) and len(e) == 2 and all(
        isinstance(i, int) and 0 <= i < count for i in e))]
    if bad_range:
        r.errors.append(f"waypoints.json: {len(bad_range)} krawędzi z indeksem spoza nodes, np. {bad_range[:3]}")
    good = [e for e in edges if e not in bad_range]
    loops = [e for e in good if e[0] == e[1]]
    if loops:
        r.errors.append(f"waypoints.json: {len(loops)} pętli, np. {loops[:3]}")
    unordered = [e for e in good if e[0] > e[1]]
    if unordered:
        r.errors.append(f"waypoints.json: {len(unordered)} krawędzi z większym indeksem na pierwszym miejscu")
    pairs = Counter((min(e), max(e)) for e in good)
    dup_edges = [e for e, c in pairs.items() if c > 1]
    if dup_edges:
        r.errors.append(f"waypoints.json: {len(dup_edges)} powtórzonych krawędzi, np. {dup_edges[:3]}")
    # components (union-find)
    parent = list(range(count))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j in good:
        parent[find(i)] = find(j)
    sizes = Counter(find(i) for i in range(count))
    largest = max(sizes.values(), default=0)
    r.counts["waypoint_components"], r.counts["waypoints_in_largest_component"] = len(sizes), largest
    r.info.append(f"waypointy: {count} węzłów, {len(edges)} krawędzi, składowych {len(sizes)}, "
                  f"w największej {largest} z {count}")
    # outline of the world
    bounds = _glb_bounds(pkg / "world.glb")
    anchor = meta.get("anchor")
    if bounds is None or not anchor:
        r.warnings.append("waypoints.json: brak world.glb lub anchor, nie sprawdzono obrysu świata")
    else:
        lo, hi = bounds
        out = []
        for name, lon, lat, *_ in nodes:
            e, n = lonlat_to_enu(lon, lat, anchor["lon"], anchor["lat"])
            n = -n  # glTF = (E, U, -N)
            if not (lo[0] - OUTLINE_MARGIN_M <= e <= hi[0] + OUTLINE_MARGIN_M
                    and lo[2] - OUTLINE_MARGIN_M <= n <= hi[2] + OUTLINE_MARGIN_M):
                out.append(name)
        if out:
            r.errors.append(f"waypoints.json: {len(out)} węzłów poza obrysem świata (+{OUTLINE_MARGIN_M} m), "
                            f"np. {out[:3]}")
    # names used by the other layers should be found in the network
    known = set(names)
    used = {f["properties"].get("insert_waypoint") for f in feats_npcs} | {f["properties"].get("waypoint") for f in places}
    missing = sorted(n for n in used if n and n not in known)
    if missing:
        # mostly freepoints (FP_*) and spawn markers, which are not waypoints: informational only
        r.info.append(f"{len(missing)} nazw z npcs/character_places nie jest waypointem sieci (np. {missing[:2]})")


def _finite(values, n: int) -> bool:
    return (isinstance(values, list) and len(values) == n
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values))


def _check_locations(pkg: Path, meta: dict, r: PackageReport) -> None:
    """locations.json: format, unique ids, order (kind, id), kinds, name sources (code = the name is the code),
    finite coordinates, `waypoint` exists in waypoints.json (or the package has none: null), `passage` exactly on
    kind passage with an existing `to_world` (<game>/<slug> next to this package) and a finite `arrival` or null."""
    package = meta.get("package", {})
    path = pkg / "locations.json"
    if not path.is_file():
        r.errors.append("brak locations.json (paczka v5)")
        return
    data = _load(pkg, "locations.json", r)
    if data is None:
        return
    if data.get("version") != LOCATIONS_VERSION:
        r.errors.append(f"locations.json: version = {data.get('version')!r}, oczekiwano {LOCATIONS_VERSION}")
    for key in ("game", "world"):
        if data.get(key) != meta.get(key):
            r.errors.append(f"locations.json: {key} = {data.get(key)!r}, w metadata {meta.get(key)!r}")
    locs = data.get("locations", [])
    r.counts["locations"] = len(locs)
    if package.get("counts", {}).get("locations") != len(locs):
        r.errors.append(f"counts.locations = {package.get('counts', {}).get('locations')!r}, w danych {len(locs)}")
    waypoint_names = None
    if (pkg / "waypoints.json").is_file():
        wdata = _load(pkg, "waypoints.json", r)
        waypoint_names = {n[0] for n in (wdata or {}).get("nodes", [])}
    ids = [l.get("id") for l in locs]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        r.errors.append(f"locations.json: {len(dup)} powtórzonych id, np. {dup[:3]}")
    order = [(LOCATION_KINDS.index(l["kind"]) if l.get("kind") in LOCATION_KINDS else len(LOCATION_KINDS), l.get("id") or "")
             for l in locs]
    if order != sorted(order):
        r.errors.append("locations.json: lokacje nie są posortowane (kind, id)")
    bad = Counter()
    for l in locs:
        lid = l.get("id")
        if not isinstance(lid, str) or not lid.startswith("location:"):
            bad["id"] += 1
        if l.get("kind") not in LOCATION_KINDS:
            bad["kind"] += 1
        if not isinstance(l.get("name"), str) or not l["name"].strip():
            bad["name"] += 1
        if l.get("name_source") not in LOCATION_NAME_SOURCES:
            bad["name_source"] += 1
        elif l["name_source"] == "code" and l.get("name") != l.get("code"):
            bad["name_source=code, name != code"] += 1
        if not _finite(l.get("center"), 3) or not (-180 <= l["center"][0] <= 180 and -90 <= l["center"][1] <= 90):
            bad["center"] += 1
        radius = l.get("radius_m")
        if radius is not None and not (_finite([radius], 1) and radius > 0):
            bad["radius_m"] += 1
        poly = l.get("polygon")
        if poly is not None and not (isinstance(poly, list) and len(poly) >= 3 and all(_finite(p, 2) for p in poly)):
            bad["polygon"] += 1
        wp = l.get("waypoint")
        if wp is not None and (waypoint_names is None or wp not in waypoint_names):
            r.errors.append(f"{lid}: waypoint {wp!r} nie istnieje w waypoints.json")
        has_passage = "passage" in l
        if has_passage != (l.get("kind") == "passage"):
            bad["passage tylko przy kind=passage"] += 1
        if has_passage:
            p = l["passage"]
            to_world = p.get("to_world") if isinstance(p, dict) else None
            if not isinstance(p, dict) or not isinstance(p.get("to_level"), str) or not {"to_world", "arrival"} <= set(p):
                bad["passage"] += 1
            else:
                if to_world is not None and not (pkg.parent.parent / to_world / "metadata.json").is_file():
                    r.errors.append(f"{lid}: to_world {to_world!r} nie istnieje wśród paczek")
                if p["arrival"] is not None and not _finite(p["arrival"], 3):
                    bad["passage.arrival"] += 1
    for what, n in bad.items():
        r.errors.append(f"locations.json: {n} lokacji z niepoprawnym polem: {what}")
    kinds = Counter(l.get("kind") for l in locs)
    r.info.append("lokacje: " + (", ".join(f"{k} {kinds[k]}" for k in LOCATION_KINDS if kinds[k]) or "0"))


def validate_package(pkg: Path, game: str) -> PackageReport:
    r = PackageReport(f"{game}/{pkg.name}")
    meta = _load(pkg, "metadata.json", r)
    if meta is None:
        return r
    package = meta.get("package", {})
    _check_metadata(pkg, game, meta, r)

    layers = {n: _load(pkg, f"{n}.geojson", r) for n in LAYERS}
    index = _load(pkg, "search_index.json", r)
    quests = _load(pkg, "quests.json", r)
    if index is None or quests is None or any(v is None for v in layers.values()):
        return r
    feats = {n: v["features"] for n, v in layers.items()}
    ids = {n: {f["properties"]["id"] for f in fs} for n, fs in feats.items()}
    for n, fs in feats.items():
        if len(ids[n]) != len(fs):
            r.errors.append(f"{n}.geojson: id się powtarzają")

    entries = index["entries"]
    by_type = Counter(e["type"] for e in entries)
    qlist = quests["quests"]
    r.counts = {
        "search_items": by_type["item"],
        "search_items_with_model": sum(e["type"] == "item" and e.get("model") is not None for e in entries),
        "search_characters": by_type["character"], "items": len(feats["items"]),
        "containers": len(feats["containers"]), "npcs": len(feats["npcs"]),
        "character_places": len(feats["character_places"]), "quests": len(qlist),
    }
    for key, value in r.counts.items():
        if package.get("counts", {}).get(key) != value:
            r.errors.append(f"counts.{key} = {package.get('counts', {}).get(key)!r}, w danych {value}")
    if len(feats["characters"]) != by_type["character"]:
        r.errors.append(f"characters.geojson ma {len(feats['characters'])} obiektów, indeks {by_type['character']} postaci")

    entry_ids = [e["id"] for e in entries]
    dup = [i for i, n in Counter(entry_ids).items() if n > 1]
    if dup:
        r.errors.append(f"search_index: {len(dup)} powtórzonych id, np. {dup[:3]}")
    bad_refs = Counter()
    for e in entries:
        for pl in e["places"]:
            layer = REF_LAYER.get(pl["kind"])
            if layer is None:
                r.errors.append(f"{e['id']}: nieznany kind {pl['kind']!r}")
            elif pl.get("ref") not in ids[layer]:
                bad_refs[(pl["kind"], layer)] += 1
    for (kind, layer), n in bad_refs.items():
        r.errors.append(f"search_index: {n} miejsc kind={kind} ze ref spoza {layer}.geojson")
    _check_quests(qlist, meta, entries, set(entry_ids), ids, r)

    loot_sets = {l["set"] for e in entries for l in e.get("loot", [])}
    if loot_sets:  # G3: random loot must point at sets described in treasure_sets.json
        sets = _load(pkg, "treasure_sets.json", r)
        unknown = sorted(loot_sets - set((sets or {}).get("sets", {})))
        if unknown:
            r.errors.append(f"search_index: zestawy łupu spoza treasure_sets.json: {unknown[:5]}")

    _check_descriptions(pkg, layers, index, quests, r)
    _check_waypoints(pkg, meta, feats["npcs"], feats["character_places"], r)
    _check_locations(pkg, meta, r)

    refs = {e["model"] for e in entries if e.get("model")}
    refs |= {f["properties"]["model"] for n in ("items", "containers") for f in feats[n] if f["properties"].get("model")}
    missing = sorted(m for m in refs if not (pkg / "models" / m).is_file())
    if missing:
        r.errors.append(f"{len(missing)} modeli z `model` nie ma w models/, np. {missing[:3]}")
    if not refs:
        r.warnings.append("brak modeli podglądu przedmiotów (models/previews)")

    used = {f["properties"]["guild_name"] for f in feats["npcs"]}
    names = meta.get("guild_names", {})
    if "guild_names" in meta and used - set(names):
        r.errors.append(f"guild_names bez gildii: {sorted(used - set(names))}")
    nulls = sorted(c for c, v in names.items() if v is None)
    if nulls:
        r.warnings.append(f"guild_names bez polskiej nazwy w grze (null): {nulls}")
    for fn in ("world.glb", "vobs.glb"):
        if not (pkg / fn).is_file():
            r.warnings.append(f"brak {fn}")
    return r


def validate_game(game: str, dist_root: Path) -> Report:
    report = Report()
    for meta in sorted((dist_root / game).glob("*/metadata.json")):
        report.packages.append(validate_package(meta.parent, game))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.validate", description="Validate geoportal packages")
    ap.add_argument("--dist", type=Path, default=PROJECT_ROOT / "dist")
    ap.add_argument("--game", action="append", help="game folder in dist (repeatable); default: all")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    games = args.game or sorted(p.name for p in args.dist.iterdir() if p.is_dir())
    report = Report()
    for g in games:
        report.packages += validate_game(g, args.dist).packages
    print(report.text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
