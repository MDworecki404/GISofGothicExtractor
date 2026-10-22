"""Validate built geoportal packages (every world of g1 and g2nk).

python -m gothic_extract.validate [--dist dist] [--game g1 ...]
Checks per package: files listed in package.files exist, JSON parses, counts match the content, search index ids are
unique, every `ref` points at an existing object, every quest in the index has an entry in quests.json (and back),
every character/item marked in_index points at an index entry, models referenced by the data exist.
Exit code 1 when any package has errors.
"""
import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import PROJECT_ROOT

PACKAGE_VERSION = 4
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
    if bad_places:
        r.errors.append(f"quests.json: {bad_places} miejsc ze ref spoza warstw")


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
