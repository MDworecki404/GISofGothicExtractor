"""Item descriptions (`description`) in geoportal packages: the text that tells apart items with one generic name.

Many items share a name ("Mikstura", "Zwój", "Amulet"); the game tells them apart by another text:
- G1/G2: C_ITEM.description from the scripts (the title the inventory shows), e.g. ITPO_HEALTH_01 "Esencja lecznicza";
- G3: ITEMDESC_<code> from stringtable.ini. It is the tooltip text ("Soczyste jabłko.", "Bohater zadaje…", "-"),
  so it is used only where it names a variant of a shared name ("Amulet" -> "Amulet Asasyna"); see
  _g3_descriptions. The final period of a one-sentence text is dropped, since the app shows it as a name.

`description` is left out when it is empty or equal to `name`. It goes on every item record of the package:
search index item entries, items.geojson, containers `contents`, npcs/characters `inventory`,
treasure_sets.json `items` (G3) and quests.json `items`.

Patch mode (no world/mesh extraction, only the scripts or the string table):
python -m gothic_extract.descriptions --game g2nk --world khorinis
python -m gothic_extract.descriptions --game all
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

from .config import PROJECT_ROOT

GAMES = ("g1", "g2nk", "archolos", "g3")
PLACEHOLDERS = {"", "-", "–"}
G3_KINDS = ("It_Recipe_", "It_Scroll_", "It_Spell_", "It_Perk_")
MAX_NAME_WORDS = 6
# package file -> how to reach its item records
FILES = ("search_index.json", "items.geojson", "containers.geojson", "npcs.geojson", "characters.geojson",
         "treasure_sets.json", "quests.json")


def _clean_g3(text: str) -> str:
    text = text.strip()
    if text.endswith(".") and "." not in text[:-1]:
        text = text[:-1].rstrip()
    return text


def item_descriptions(catalog: dict[str, dict], engine: str = "zengin") -> dict[str, str]:
    """catalog: code -> {"name", "description"} (catalog_items.json or ItemDef.to_dict()) -> code -> description.

    Only codes whose description differs from the name; for G3 (engine "genome") only codes whose name is
    shared by another item code.
    """
    out = {}
    for code, d in catalog.items():
        text = (d.get("description") or "").strip()
        if text not in PLACEHOLDERS and text != (d.get("name") or "").strip():
            out[code] = text
    if engine != "genome":
        return out
    return _g3_descriptions(catalog, out)


def _kind(code: str) -> str:
    for prefix in G3_KINDS:
        if code.startswith(prefix):
            return prefix
    return "item"


def _g3_descriptions(catalog: dict[str, dict], raw: dict[str, str]) -> dict[str, str]:
    """G3 tooltip texts that work as a variant name. A code gets one only when
    - its name is shared by another code of the same kind (a recipe, scroll, spell or perk carries the name of its
      product/spell/item; `_Snow` plants are twins of the normal ones: those pairs are not variants and keep the name);
    - no other item has the same text (a text shared by several codes tells nothing apart);
    - the text reads as a name: at most MAX_NAME_WORDS words and contains the first word of the name
      ("Amulet" -> "Amulet magii", "Hełm" -> "Rogaty hełm"), or every code of that name gets a text
      (a described family: "Mikstura przemiany" -> "Przemienia w wilka").
    """
    def name(c: str) -> str:
        return (catalog[c].get("name") or "").strip()

    members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for c in catalog:
        if not c.endswith("_Snow"):
            members[(_kind(c), name(c))].append(c)
    texts = {c: _clean_g3(t) for c, t in raw.items()}
    uses = Counter(texts.values())
    cand = {c: texts[c] for codes in members.values() if len(codes) > 1 for c in codes
            if c in texts and uses[texts[c]] == 1 and texts[c] not in PLACEHOLDERS and texts[c] != name(c)}

    def reads_as_name(c: str) -> bool:
        head = name(c).split()[0].casefold()[:4] if name(c) else ""
        words = cand[c].casefold().split()
        return bool(head) and len(words) <= MAX_NAME_WORDS and any(w.startswith(head) for w in words)

    return {c: t for c, t in cand.items()
            if reads_as_name(c) or all(m in cand for m in members[(_kind(c), name(c))])}


def iter_item_records(data: dict[str, object]) -> Iterator[tuple[str, dict]]:
    """(file, record) for every item record of a package; data: file name -> parsed JSON (missing files skipped)."""
    if (index := data.get("search_index.json")) is not None:
        for e in index["entries"]:
            if e.get("type") == "item":
                yield "search_index.json", e
    if (fc := data.get("items.geojson")) is not None:
        for f in fc["features"]:
            yield "items.geojson", f["properties"]
    for name, key in (("containers.geojson", "contents"), ("npcs.geojson", "inventory"),
                      ("characters.geojson", "inventory")):
        if (fc := data.get(name)) is not None:
            for f in fc["features"]:
                for rec in f["properties"].get(key) or []:
                    yield name, rec
    if (sets := data.get("treasure_sets.json")) is not None:
        for s in sets["sets"].values():
            for rec in s.get("items", []):
                yield "treasure_sets.json", rec
    if (quests := data.get("quests.json")) is not None:
        for q in quests["quests"]:
            for rec in q.get("items", []):
                yield "quests.json", rec


def set_description(rec: dict, desc: str | None) -> bool:
    """Put `description` right after `name` (or drop it when not wanted); True when the record changed."""
    name = (rec.get("name") or "").strip()
    want = desc if desc and desc != name else None
    if rec.get("description") == want and (want is not None or "description" not in rec):
        return False
    items = [(k, v) for k, v in rec.items() if k != "description"]
    rec.clear()
    for k, v in items:
        rec[k] = v
        if k == "name" and want is not None:
            rec["description"] = want
    if want is not None and "description" not in rec:
        rec["description"] = want
    return True


def _read(path: Path):
    return json.loads(path.read_text("utf-8"))


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))  # same as every package writer


def label_groups(records: list[dict]) -> dict[str, list[str]]:
    """Shown label (description, else name) -> item codes, for labels carried by several codes."""
    codes: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        codes[rec.get("description") or rec.get("name") or rec["code"]].add(rec["code"])
    return {label: sorted(cs) for label, cs in sorted(codes.items()) if len(cs) > 1}


def add_descriptions(pkg: Path, descs: dict[str, str], known: set[str] | None = None) -> dict:
    """Write `description` into the package files in place; only changed files are rewritten.

    known: every item code of the game (to count package codes missing from the scripts); default: keys of descs.
    """
    data, original = {}, {}
    for name in FILES:
        path = pkg / name
        if path.is_file():
            original[name] = path.read_text("utf-8")
            data[name] = json.loads(original[name])
    changed = 0
    for _, rec in iter_item_records(data):
        changed += set_description(rec, descs.get(rec["code"]))
    written = []
    for name, obj in data.items():
        text = _dump(obj)
        if text != original[name]:
            (pkg / name).write_text(text, encoding="utf-8")
            written.append(name)
    entries = [rec for f, rec in iter_item_records(data) if f == "search_index.json"]
    all_codes = {rec["code"] for _, rec in iter_item_records(data)}
    known = known if known is not None else set(descs)
    return {
        "items": len(entries),
        "with_description": sum("description" in e for e in entries),
        "records_changed": changed,
        "files_written": written,
        "missing_codes": sorted(all_codes - known),
        "same_label": label_groups(entries),
    }


def load_game_catalog(game: str) -> tuple[dict[str, dict], str]:
    """Item catalog straight from the game (scripts for G1/G2, templates + string table for G3) and its engine."""
    from .config import load_game

    cfg = load_game(game)
    if cfg.engine == "genome":
        from .g3.archive import open_g3fs
        from .g3.catalog import build_g3_catalog
        from .g3.strings import load_strings
        from .g3.templates import load_templates

        fs = open_g3fs(cfg)
        catalog = build_g3_catalog(load_templates(fs), load_strings(fs))
    else:
        from .catalog import build_item_catalog
        from .script_vm import make_vm

        catalog = build_item_catalog(make_vm(cfg.script_dat))
    return {k: v.to_dict() for k, v in catalog.items()}, cfg.engine


def _packages(game: str, worlds: list[str] | None, dist_root: Path) -> list[Path]:
    from .config import load_game

    cfg = load_game(game)
    slugs = {w.slug: w.slug for w in cfg.worlds.values()} | {z.lower(): w.slug for z, w in cfg.worlds.items()}
    if worlds:
        unknown = [w for w in worlds if w.lower() not in slugs]
        if unknown:
            raise SystemExit(f"unknown world(s) for {game}: {', '.join(unknown)}; known: {', '.join(sorted(set(slugs.values())))}")
        chosen = [slugs[w.lower()] for w in worlds]
    else:
        chosen = [w.slug for w in cfg.worlds.values()]
    return [dist_root / game / s for s in chosen if (dist_root / game / s / "metadata.json").is_file()]


def summary(name: str, r: dict) -> str:
    lines = [f"  {name}: przedmiotów w indeksie {r['items']}, z opisem {r['with_description']}; "
             f"zmienione rekordy {r['records_changed']}; zapisane pliki: {', '.join(r['files_written']) or 'brak'}; "
             f"kodów spoza skryptów {len(r['missing_codes'])}; nierozróżnionych grup nazw {len(r['same_label'])}"]
    if r["missing_codes"]:
        lines.append(f"    spoza skryptów: {', '.join(c or '(pusty kod)' for c in r['missing_codes'])}")
    for label, codes in r["same_label"].items():
        lines.append(f"    „{label}”: {', '.join(codes)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gothic_extract.descriptions",
                                 description="Add item descriptions to existing geoportal packages (in place)")
    ap.add_argument("--game", required=True, help=f"{', '.join(GAMES)} or all")
    ap.add_argument("--world", action="append", help="package slug or ZEN name (repeatable); default: all worlds")
    ap.add_argument("--dist-root", type=Path, default=PROJECT_ROOT / "dist")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    games = GAMES if args.game == "all" else (args.game,)
    if args.game == "all" and args.world:
        raise SystemExit("--world needs a single --game")
    for game in games:
        pkgs = _packages(game, args.world, args.dist_root)
        if not pkgs:
            print(f"== {game}: brak paczek w {args.dist_root / game}")
            continue
        catalog, engine = load_game_catalog(game)
        descs = item_descriptions(catalog, engine)
        print(f"== {game}: katalog {len(catalog)} przedmiotów, z opisem do paczek {len(descs)}", flush=True)
        for pkg in pkgs:
            print(summary(f"{game}/{pkg.name}", add_descriptions(pkg, descs, set(catalog))), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
