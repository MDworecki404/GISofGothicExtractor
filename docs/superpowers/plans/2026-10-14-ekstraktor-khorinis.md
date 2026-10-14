# Ekstraktor Khorinis — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pakiet Pythona `gothic_extract`, który z plików G2NK wyciąga Khorinis (NEWWORLD.ZEN): siatkę świata (.glb), VOBy, przedmioty, skrzynie z zawartością, NPC z ekwipunkiem i rutynami, waynet — do GeoJSON z polskimi nazwami.

**Architecture:** ZenKit (`zenkit` 1.3.0.4) czyta VDF/ZEN/tekstury i ładuje GOTHIC.DAT. Dane z ZEN zbiera rekurencyjny spacer po drzewie VOBów. Dane ze skryptów pochodzą z dwóch mechanizmów: VM ZenKit inicjalizuje instancje (nazwa, gildia, poziom), a **statyczny skaner bajtkodu** znajduje wywołania (`Wld_InsertNpc`, `Wld_InsertItem`, `CreateInvItem(s)`, `TA_*`) z argumentami-stałymi we wszystkich gałęziach. Wszystko trafia do wspólnego modelu rekordów, a potem do eksportera GeoJSON/glb.

**Tech Stack:** Python 3.13, zenkit 1.3.0.4, numpy, pygltflib, Pillow, pytest.

**Spec:** `docs/2026-10-14-ekstraktor-khorinis.md`

## Global Constraints

- Wejście tylko do odczytu: `C:\Moje_Różne\GothicClaudiusz\Gothic II\` — nigdy nie zapisujemy w folderach gier.
- Kod: `tools/gothic_extract/` (pakiet `gothic_extract`), testy: `tools/tests/`, wyniki: `output/g2nk/newworld/`.
- Uruchomienie: `python -m gothic_extract --game g2nk --world NEWWORLD --out output/g2nk/newworld` (z katalogu `tools/`, albo z `PYTHONPATH=tools`).
- Addon nadpisuje bazę: pliki z `*_Addon.vdf` wygrywają z bazowymi.
- Jednostka gry = 1 cm; wyjście w metrach. ENU: East=+X_gry, North=+Z_gry, Up=+Y_gry. Kotwica domyślna lon=0, lat=0, h=0 (parametr w `games.toml`).
- Każdy Feature ma `game_pos: [x, y, z]` (oryginalne jednostki) i `height_m`.
- Wspólne właściwości obiektów: `id`, `code`, `name` (PL), `category`, `game_pos`, `height_m`, `source`.
- Ekwipunek NPC: pole `certainty` ∈ {`"always"`, `"possible"`}.
- Rutyny: wszystkie funkcje `Rtn_<Nazwa>_<id>`; punkt rutyny ma `routine` (np. `"START"`) i `is_default`.
- Wszystkie pliki wyjściowe UTF-8, `ensure_ascii=False`. Polskie znaki muszą przetrwać (test: „Szczaw królewski”).
- glb: metry, Y-up glTF, tekstury PNG osadzone, jeden prymityw na materiał, `alphaMode: MASK` dla materiałów z alfą.
- VOB-y bez geometrii w etapie 1 (tylko pozycje i nazwy visuali w `vobs.geojson`).
- Folder nie jest repo git — Task 1 robi `git init` z `.gitignore` wykluczającym `Gothic/`, `Gothic II/`, `output/`.

## Review Focus

1. **Przedmioty zagnieżdżone pod innymi VOBami** (dzieci VOBów, nie tylko root) — muszą się znaleźć; test w Task 3 porównuje rekurencyjną liczbę `oCItem` z liczbą root-only i wymaga, by wynik był ≥ rekurencyjnej.
2. **Różne formaty `contents` skrzyń** (`"ItMi_Gold:50, ItFo_Apple"`, spacje, brak ilości, końcowy przecinek, małe litery) — test parsera w Task 3.
3. **Nieznany kod przedmiotu** (literówka w ZEN, brak w skryptach) — rekord zostaje z `name: null`, ostrzeżenie w raporcie, brak wyjątku; test w Task 8.
4. **Wielkość liter i źródło punktów** — skrypty piszą `"NW_CITY_HABOUR_01"`, waynet ma mieszane litery, a `FP_*` to VOBy `zCVobSpot`, nie waypointy; resolver szuka bez względu na wielkość liter w obu zbiorach; test w Task 3.
5. **Polskie znaki w plikach wyjściowych** (UTF-8, nie `\u0142`) — test w Task 8 czyta surowe bajty pliku.

---

### Task 1: Szkielet, konfiguracja gier, VFS

**Files:**
- Create: `tools/gothic_extract/__init__.py`, `tools/gothic_extract/games.toml`, `tools/gothic_extract/config.py`, `tools/gothic_extract/vfs.py`
- Create: `tools/requirements.txt`, `tools/tests/conftest.py`, `.gitignore`
- Test: `tools/tests/test_vfs.py`

**Interfaces:**
- Produces:
  - `@dataclass GameConfig(key: str, root: Path, version: zenkit.GameVersion, vdf_files: list[str], script_dat: Path, anchor_lon: float, anchor_lat: float, anchor_h: float)`
  - `load_game(key: str) -> GameConfig` (czyta `games.toml`; ścieżki względne liczone od katalogu projektu `C:\Moje_Różne\GothicClaudiusz`)
  - `open_vfs(cfg: GameConfig) -> zenkit.Vfs`
  - `read_file(vfs: zenkit.Vfs, name: str) -> bytes | None` (bez względu na wielkość liter)
  - pytest fixtures w `conftest.py`: `g2_cfg`, `g2_vfs` (scope=session), skip, gdy folder gry nie istnieje.

`games.toml` wpis `g2nk`: root `Gothic II`, version `GOTHIC2`, `vdf_files` = wszystkie `Data/*.vdf` poza `Speech*` i `Sounds*`, `script_dat = "_work/Data/Scripts/_compiled/GOTHIC.DAT"`, kotwica 0/0/0. Dodaj też wpis `g1` (root `Gothic`, `GOTHIC1`, `_work/DATA/scripts/_compiled/Gothic.dat`) — tylko konfiguracja, bez testów.

- [ ] **Step 1:** `git init` w `C:\Moje_Różne\GothicClaudiusz`; `.gitignore` z `Gothic/`, `Gothic II/`, `output/`, `__pycache__/`, `.pytest_cache/`. `requirements.txt`: `zenkit==1.3.0.4`, `numpy`, `pygltflib`, `Pillow`, `pytest`. `pip install -r tools/requirements.txt`.
- [ ] **Step 2: Failing tests** w `test_vfs.py`:

```python
def test_newworld_zen_comes_from_addon(g2_vfs):
    data = read_file(g2_vfs, "NEWWORLD.ZEN")
    assert data is not None
    # addon wersja jest inna niż bazowa z Worlds.vdf
    assert len(data) != len(base_newworld_bytes())  # helper: montuje TYLKO Worlds.vdf

def test_case_insensitive_lookup(g2_vfs):
    assert read_file(g2_vfs, "newworld.zen") == read_file(g2_vfs, "NEWWORLD.ZEN")

def test_textures_mounted(g2_vfs):
    # dowolna skompilowana tekstura z Textures.vdf, np. tekstura mapy Khorinis
    assert any(n.name.upper().endswith("-C.TEX") for n in walk(g2_vfs.root))  # walk: rekurencja po VfsNode.children
```

- [ ] **Step 3:** Run `pytest tools/tests/test_vfs.py -v` → FAIL (import error).
- [ ] **Step 4:** Implement. Montowanie: `Vfs.mount_disk` dla każdego VDF; kolejność bazowe → `_Addon`, z `VfsOverwriteBehavior.NEWER` (albo `ALL` przy montowaniu addonu po bazie — wybierz to, co daje test 1 zielony).
- [ ] **Step 5:** `pytest tools/tests/test_vfs.py -v` → PASS.
- [ ] **Step 6:** Commit `feat: game config and VFS mounting`.

---

### Task 2: Układ współrzędnych

**Files:**
- Create: `tools/gothic_extract/coords.py`
- Test: `tools/tests/test_coords.py`

**Interfaces:**
- Produces:
  - `game_to_enu(x: float, y: float, z: float) -> tuple[float, float, float]` → `(east_m, north_m, up_m) = (x/100, z/100, y/100)`
  - `enu_to_lonlat(e: float, n: float, u: float, lon0: float, lat0: float, h0: float) -> tuple[float, float, float]` — płaszczyzna styczna na elipsoidzie WGS84 (promienie M i N przy `lat0`)
  - `game_to_lonlat(pos: tuple[float,float,float], cfg: GameConfig) -> tuple[float,float,float]`

- [ ] **Step 1: Failing tests:**

```python
def test_axes():
    assert game_to_enu(100, 200, 300) == (1.0, 3.0, 2.0)

def test_origin_maps_to_anchor():
    assert enu_to_lonlat(0, 0, 0, 10.0, 50.0, 5.0) == pytest.approx((10.0, 50.0, 5.0))

def test_1km_east_at_equator():
    lon, lat, h = enu_to_lonlat(1000, 0, 0, 0, 0, 0)
    assert lon == pytest.approx(0.0089831528, rel=1e-6) and lat == pytest.approx(0)

def test_1km_north_at_equator():
    lon, lat, _ = enu_to_lonlat(0, 1000, 0, 0, 0, 0)
    assert lat == pytest.approx(0.0090437173, rel=1e-6)
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit `feat: game→ENU→lon/lat transforms`.

---

### Task 3: Odczyt świata ZEN (VOBy, przedmioty, skrzynie, waynet, freepointy)

**Files:**
- Create: `tools/gothic_extract/records.py`, `tools/gothic_extract/world_data.py`
- Test: `tools/tests/test_world_data.py`

**Interfaces:**
- Consumes: `open_vfs`, `read_file` (Task 1).
- Produces (`records.py`, dataclasses):
  - `Vec3 = tuple[float, float, float]`
  - `VobRec(id: int, vob_type: str, name: str, visual: str | None, pos: Vec3, rot: list[float] /*9, row-major*/, parent_id: int | None)`
  - `ItemRec(code: str, amount: int, pos: Vec3, source: str /*"zen"|"script"*/, vob_id: int | None, spot: str | None)`
  - `ContainerRec(vob_id: int, name: str, visual: str | None, pos: Vec3, locked: bool, key: str | None, pick_string: str | None, contents: list[tuple[str, int]])`
  - `WaypointRec(name: str, pos: Vec3, is_free_point: bool, under_water: bool)`; `WayEdgeRec(a: str, b: str)`
  - `WorldData(vobs: list[VobRec], items: list[ItemRec], containers: list[ContainerRec], waypoints: list[WaypointRec], edges: list[WayEdgeRec], freepoints: list[WaypointRec])`
- Produces (`world_data.py`):
  - `load_world(vfs: zenkit.Vfs, world_file: str, version: zenkit.GameVersion) -> tuple[zenkit.World, WorldData]`
  - `parse_contents(s: str) -> list[tuple[str, int]]` — kody upper-case, domyślna ilość 1
  - `class PointResolver(waypoints, freepoints)` z `resolve(name: str) -> Vec3 | None` (case-insensitive, najpierw waynet, potem freepointy)

Freepointy = VOBy typu `zCVobSpot` (pozycja + nazwa). Przedmioty = VOBy `oCItem` (`Item.instance`, `Item.amount`) na **każdym** poziomie drzewa. Skrzynie = `oCMobContainer` (`Container.contents` oraz `Container.items`, jeśli niepuste — połącz oba źródła).

- [ ] **Step 1: Failing tests:**

```python
def test_parse_contents_variants():
    assert parse_contents("ItMi_Gold:50, ItFo_Apple") == [("ITMI_GOLD", 50), ("ITFO_APPLE", 1)]
    assert parse_contents(" itpl_health_herb_01:2 ,") == [("ITPL_HEALTH_HERB_01", 2)]
    assert parse_contents("") == []

def test_world_has_expected_counts(newworld):         # fixture: load_world(..., "NEWWORLD.ZEN", GOTHIC2)
    _, wd = newworld
    assert len(wd.vobs) > 5000
    assert len(wd.waypoints) > 1000
    assert len(wd.containers) > 50

def test_items_found_recursively(newworld):
    world, wd = newworld
    root_only = sum(1 for v in world.root_objects if v.type == zenkit.VobType.oCItem)
    assert len([i for i in wd.items if i.source == "zen"]) >= root_only
    assert any(i.code == "ITPL_PERM_HERB" for i in wd.items)

def test_resolver_case_insensitive_and_freepoints(newworld):
    _, wd = newworld
    r = PointResolver(wd.waypoints, wd.freepoints)
    wp = wd.waypoints[0].name
    assert r.resolve(wp.lower()) == r.resolve(wp.upper()) is not None
    fp = wd.freepoints[0].name
    assert r.resolve(fp) is not None
    assert r.resolve("NIE_ISTNIEJE_123") is None
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS (jeśli progi liczbowe są nietrafione o rząd wielkości, zbadaj — nie obniżaj ich bez sprawdzenia, czego brakuje).
- [ ] **Step 5:** Commit `feat: read VOBs, items, containers and waynet from ZEN`.

---

### Task 4: Katalog przedmiotów ze skryptów

**Files:**
- Create: `tools/gothic_extract/script_vm.py`, `tools/gothic_extract/catalog.py`
- Test: `tools/tests/test_catalog.py`

**Interfaces:**
- Consumes: `GameConfig.script_dat`.
- Produces:
  - `make_vm(script_path: Path) -> zenkit.DaedalusVm` — VM z `register_external_default`, który zdejmuje ze stosu argumenty externala (typy parametrów = symbole o indeksach `sym.index+1 … sym.index+sym.size`) i odkłada wartość domyślną (0 / 0.0 / "" / instancja pusta) wg `sym.return_type`, gdy `sym.has_return`.
  - `@dataclass ItemDef(code: str, name: str, category: str, main_flag: int, flags: int, value: int, visual: str, description: str)`
  - `build_item_catalog(vm: zenkit.DaedalusVm) -> dict[str, ItemDef]` — klucz: kod upper-case; wszystkie symbole typu INSTANCE, których rodzicem (przez prototyp) jest klasa `C_ITEM`; `vm.init_instance(sym, DaedalusInstanceType.ITEM)`.
  - `CATEGORY_BY_MAINFLAG: dict[int, str]` — zgodnie z `ITEM_KAT_*` w skryptach: `ITEM_KAT_NONE=1 Różne`, `ITEM_KAT_NF=2 Broń biała`, `ITEM_KAT_FF=4 Broń dystansowa`, `ITEM_KAT_MUN=8 Amunicja`, `ITEM_KAT_ARMOR=16 Pancerze`, `ITEM_KAT_FOOD=32 Jedzenie i rośliny`, `ITEM_KAT_DOCS=64 Dokumenty`, `ITEM_KAT_POTIONS=128 Mikstury`, `ITEM_KAT_LIGHT=256 Światło`, `ITEM_KAT_RUNE=512 Runy i zwoje`, `ITEM_KAT_MAGIC=0x80000000 Magia`. Wartości stałych odczytaj z GOTHIC.DAT (symbole `ITEM_KAT_*`), nie z pamięci. Dodatkowo podkategoria `Rośliny` dla kodów `ITPL_*`.

- [ ] **Step 1: Failing tests:**

```python
def test_royal_sorrel_polish_name(catalog):
    assert catalog["ITPL_PERM_HERB"].name == "Szczaw królewski"

def test_catalog_size(catalog):
    assert len(catalog) > 500

def test_gold_category(catalog):
    assert catalog["ITMI_GOLD"].category

def test_herb_is_plant(catalog):
    assert catalog["ITPL_HEALTH_HERB_01"].category == "Rośliny"
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. Jeśli nazwa wychodzi z krzaczkami, dekoduj surowe bajty z cp1250 (sprawdź, co zwraca `ItemInstance.name`). **Step 4:** Run → PASS. **Step 5:** Commit `feat: item catalog with Polish names from GOTHIC.DAT`.

---

### Task 5: Statyczny skaner bajtkodu Daedalus

**Files:**
- Create: `tools/gothic_extract/daedalus_scan.py`
- Test: `tools/tests/test_daedalus_scan.py`

**Interfaces:**
- Consumes: `zenkit.DaedalusScript` (VM z Task 4 dziedziczy po nim).
- Produces:
  - `@dataclass CallSite(caller: str, callee: str, args: list[int | str | None], conditional: bool, address: int)` — `args` w kolejności parametrów; int z `PUSHI`, nazwa symbolu z `PUSHVI`/`PUSHV` (dla stałych stringów — wartość stringu), `None`, gdy argument nie jest stałą (np. wynik wyrażenia).
  - `functions(script) -> list[DaedalusSymbol]` — symbole FUNCTION/INSTANCE z kodem (nie externale).
  - `scan_function(script, sym) -> list[CallSite]` — dekoduje instrukcje od `sym.address` do `RSR` kończącego funkcję (zakres = do adresu następnej funkcji w posortowanej liście adresów); wywołania to `BL` (funkcja skryptowa) i `BE` (external).
  - `find_calls(script, callee_names: set[str]) -> list[CallSite]` — po wszystkich funkcjach.
  - `reachable_calls(script, root: str, callee_names: set[str]) -> list[CallSite]` — DFS po grafie `BL` od `root`; `conditional=True`, jeśli wywołanie leży w zasięgu jakiegokolwiek skoku `BZ` w danej funkcji **lub** którakolwiek ramka na ścieżce była warunkowa.

Algorytm argumentów: przy `BL/BE` weź liczbę parametrów callee (`sym.size`) i cofnij się po instrukcjach `PUSH*` bez pośrednich operacji; jeśli sekwencja jest przerwana operacją arytmetyczną/wywołaniem — dany argument `None`.
Warunkowość: instrukcja o adresie `a` jest warunkowa, gdy istnieje `BZ` o adresie `b < a` i celu `t > a` w tej samej funkcji.

- [ ] **Step 1: Failing tests** (na prawdziwym GOTHIC.DAT):

```python
def test_wld_insertnpc_calls_have_constant_waypoints(script):
    calls = find_calls(script, {"WLD_INSERTNPC"})
    assert len(calls) > 200
    assert sum(isinstance(c.args[1], str) for c in calls) / len(calls) > 0.95

def test_startup_newworld_reaches_inserts(script):
    calls = reachable_calls(script, "STARTUP_NEWWORLD", {"WLD_INSERTNPC"})
    assert len(calls) > 50

def test_conditional_detection(script):
    # B_CreateAmbientInv rozgałęzia się na Hlp_Random → część wywołań warunkowa
    calls = reachable_calls(script, "B_CREATEAMBIENTINV", {"CREATEINVITEMS", "CREATEINVITEM"})
    assert any(c.conditional for c in calls)
```

Jeśli w GOTHIC.DAT funkcja nazywa się inaczej (np. `B_CREATEAMBIENTINV` nie istnieje), znajdź helper ekwipunku z `Hlp_Random` i użyj go w teście — zanotuj nazwę w komentarzu.

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit `feat: static Daedalus call-site scanner`.

---

### Task 6: NPC — wstawienia, właściwości, ekwipunek, rutyny; przedmioty wstawiane skryptem

**Files:**
- Create: `tools/gothic_extract/npcs.py`
- Test: `tools/tests/test_npcs.py`

**Interfaces:**
- Consumes: `make_vm` (T4), `find_calls`, `reachable_calls`, `scan_function` (T5), `PointResolver`, `ItemRec` (T3), `build_item_catalog` (T4).
- Produces:
  - `InvItem(code: str, amount: int, certainty: str)`
  - `RoutinePoint(routine: str, is_default: bool, start: str /*"HH:MM"*/, end: str, action: str /*np. "TA_SMITH_FIRE"*/, waypoint: str, pos: Vec3 | None)`
  - `NpcRec(code: str, name: str, guild: int, guild_name: str, level: int, insert_waypoint: str, insert_function: str, chapter: int | None, pos: Vec3 | None, inventory: list[InvItem], routines: list[RoutinePoint])`
  - `extract_npcs(vm, resolver: PointResolver, world_waypoint_names: set[str]) -> list[NpcRec]`
  - `extract_script_items(vm, resolver) -> list[ItemRec]` (source=`"script"`, `spot` = nazwa FP/WP)

Reguły:
- **Wstawienia:** `find_calls(script, {"WLD_INSERTNPC"})` ze **wszystkich** funkcji; zostają tylko te, których waypoint (case-insensitive) istnieje w waynecie/freepointach tego świata. `chapter` z nazwy funkcji wywołującej (`KAPITEL_(\d)` lub `_KAP(\d)`), inaczej `None`. NPC wstawiony kilka razy (różne rozdziały) → osobne rekordy.
- **Właściwości:** `vm.init_instance(code, NPC)` → `name`, `guild`, `level`; nazwa gildii ze stałych `GIL_*` w skrypcie.
- **Ekwipunek:** `reachable_calls(script, <instancja NPC>, {"CREATEINVITEM","CREATEINVITEMS"})` + wywołania w helperach; `args`: (npc, item, [amount]); `certainty = "possible" if conditional else "always"`; sumuj ilości per (code, certainty). Argument `item` będący `None` → pomiń i policz w raporcie.
- **Rutyny:** dla NPC o kodzie `XXX` (np. `VLK_400_LARIUS` → nazwa bazowa `LARIUS`; ogólnie: wszystkie funkcje `RTN_*` wywołujące TA_* z `self`, a powiązanie z NPC przez to, że `daily_routine` NPC = jedna z nich, **oraz** przez wspólny prefiks `RTN_<NAZWA>_<ID>` z ID instancji). `is_default` = funkcja jest `daily_routine` NPC. Wywołania `TA_*` (funkcje skryptowe, parametry: self, h1, m1, h2, m2, waypoint) → `RoutinePoint`; `routine` = segment nazwy między `RTN_` a `_<ID>` (np. `RTN_START_400` → `START`).
- **Przedmioty skryptowe:** `find_calls(script, {"WLD_INSERTITEM"})`, filtrowane jak wstawienia NPC.

- [ ] **Step 1: Failing tests:**

```python
def test_many_npcs_in_khorinis(npcs):
    assert len({n.code for n in npcs}) > 300

def test_npcs_have_positions(npcs):
    assert sum(n.pos is not None for n in npcs) / len(npcs) > 0.98

def test_harad_smith_routine(npcs):           # kowal Harad w mieście
    harad = next(n for n in npcs if n.name == "Harad")
    assert any(rp.is_default and rp.action.startswith("TA_SMITH") for rp in harad.routines)
    assert all(rp.pos is not None for rp in harad.routines)

def test_inventory_certainty_values(npcs):
    vals = {i.certainty for n in npcs for i in n.inventory}
    assert vals <= {"always", "possible"} and "always" in vals

def test_script_items_have_positions(script_items):
    assert script_items and all(i.source == "script" and i.pos for i in script_items)
```

Jeśli Harad ma inną nazwę w polskiej wersji, wybierz innego NPC z miasta ze stałą rutyną kowala lub handlarza i zanotuj.

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit `feat: NPC inserts, inventories, routines and script items`.

---

### Task 7: Siatka świata → glb

**Files:**
- Create: `tools/gothic_extract/mesh_export.py`
- Test: `tools/tests/test_mesh_export.py`

**Interfaces:**
- Consumes: `zenkit.World.mesh` (T3), `open_vfs`/`read_file` (T1).
- Produces: `export_world_glb(world: zenkit.World, vfs: zenkit.Vfs, out_path: Path) -> MeshStats` gdzie `MeshStats(triangles: int, materials: int, textures_ok: int, textures_missing: list[str], bbox_min: Vec3, bbox_max: Vec3)` (bbox w metrach, w osiach glTF).

Szczegóły:
- Wierzchołki z `Polygon.position_indices` + `feature_indices` (UV z `Feature.texture`, normalne z `Feature.normal`); wielokąty o > 3 wierzchołkach → wachlarz trójkątów. Pomijaj `is_portal`, `is_lod` i materiały o nazwie zaczynającej się od `GHOSTOCCLUDER`.
- Konwersja do glTF: `(x, y, z)_gry → (x/100, y/100, -z/100)` — Y-up, lewoskrętny → prawoskrętny przez negację Z; kolejność wierzchołków trójkąta odwrócona, żeby zachować normalne na zewnątrz. Zapisz to w `metadata.json` (T8), bo GeoJSON używa North=+Z_gry: punkt glTF `(e, u, -n)`.
- Tekstura: nazwa z materiału `X.TGA` → w VFS szukaj `X-C.TEX`; `zenkit.Texture` → `mipmap_rgba(0)` → PNG (Pillow) osadzony. Brak tekstury → materiał w kolorze `Material.color`, nazwa w `textures_missing`.
- Alfa: jeśli tekstura ma jakikolwiek piksel z alfą < 255 → `alphaMode: "MASK"`, `alphaCutoff: 0.5`, `doubleSided: true`.

- [ ] **Step 1: Failing tests:**

```python
def test_glb_written_and_valid(tmp_path, newworld, g2_vfs):
    world, _ = newworld
    stats = export_world_glb(world, g2_vfs, tmp_path / "w.glb")
    g = pygltflib.GLTF2().load(str(tmp_path / "w.glb"))
    assert stats.triangles > 100_000
    assert len(g.meshes[0].primitives) == stats.materials
    assert stats.textures_ok / stats.materials > 0.9

def test_bbox_matches_waynet(tmp_path, newworld, g2_vfs):
    world, wd = newworld
    stats = export_world_glb(world, g2_vfs, tmp_path / "w.glb")
    xs = [w.pos[0] / 100 for w in wd.waypoints]
    assert stats.bbox_min[0] <= min(xs) and max(xs) <= stats.bbox_max[0]
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit `feat: export world mesh to glb`.

---

### Task 8: Eksport GeoJSON, metadane, raport, CLI + weryfikacja orientacji

**Files:**
- Create: `tools/gothic_extract/export_geojson.py`, `tools/gothic_extract/report.py`, `tools/gothic_extract/__main__.py`
- Test: `tools/tests/test_export.py`

**Interfaces:**
- Consumes: wszystko powyżej.
- Produces:
  - `write_outputs(out_dir: Path, cfg: GameConfig, world_name: str, wd: WorldData, catalog: dict[str, ItemDef], npcs: list[NpcRec], script_items: list[ItemRec], mesh: MeshStats) -> Report`
  - `Report(counts: dict[str, int], warnings: list[str])` zapisany do `report.txt`
  - CLI `python -m gothic_extract --game g2nk --world NEWWORLD --out <dir> [--skip-mesh]`

Pliki i ich Feature (geometria zawsze `[lon, lat, h]` przez `game_to_lonlat`):
- `items.geojson` — z `wd.items` + `script_items`; `code`, `name`, `category`, `amount`, `source`, `spot`.
- `containers.geojson` — `locked`, `key`, `pick_string`, `contents: [{code, name, category, amount}]`.
- `npcs.geojson` — Feature na `NpcRec` z `pos`; `inventory: [{code, name, amount, certainty}]`, `guild_name`, `level`, `chapter`, `routines` (lista bez pozycji).
- `npc_routines.geojson` — Feature na `RoutinePoint` z `pos`; `npc_code`, `npc_name`, `routine`, `is_default`, `start`, `end`, `action`, `waypoint`.
- `vobs.geojson` — `vob_type`, `name`, `visual`, `rot`, `parent_id`.
- `waypoints.geojson` — Point na waypoint + LineString na krawędź (`a`, `b`).
- `freepoints.geojson`.
- `catalog_items.json` — `{code: ItemDef}`.
- `metadata.json` — `game`, `world`, `anchor`, `axes: {"east": "+X", "north": "+Z", "up": "+Y", "unit_cm": true}`, `gltf_axes: "glTF = (E, U, -N) w metrach"`, `zenkit_version`, `generated_at`.
- Nieznany kod (brak w katalogu) → `name: null`, `category: null`, ostrzeżenie `unknown item code: X (n occurrences)`; nierozwiązany waypoint → ostrzeżenie.

- [ ] **Step 1: Failing tests:**

```python
def test_end_to_end(tmp_path):                 # run CLI z --skip-mesh dla szybkości
    run_cli(["--game", "g2nk", "--world", "NEWWORLD", "--out", str(tmp_path), "--skip-mesh"])
    items = json.loads((tmp_path / "items.geojson").read_text("utf-8"))
    names = {f["properties"]["name"] for f in items["features"]}
    assert "Szczaw królewski" in names

def test_utf8_raw_bytes(tmp_path):
    run_cli([... , "--skip-mesh"])
    raw = (tmp_path / "items.geojson").read_bytes()
    assert "królewski".encode("utf-8") in raw and b"\\u00f3" not in raw

def test_unknown_code_does_not_crash(tmp_path, small_inputs):
    # small_inputs: fixture budujący minimalne WorldData/katalog/MeshStats w pamięci,
    # z jednym ItemRec(code="ITXX_NIE_MA", amount=1, pos=(0,0,0), source="zen", vob_id=None, spot=None)
    write_outputs(tmp_path, **small_inputs)
    items = json.loads((tmp_path / "items.geojson").read_text("utf-8"))
    feat = next(f for f in items["features"] if f["properties"]["code"] == "ITXX_NIE_MA")
    assert feat["properties"]["name"] is None
    assert "ITXX_NIE_MA" in (tmp_path / "report.txt").read_text("utf-8")

def test_every_feature_has_game_pos(tmp_path):
    for fn in ["items", "containers", "npcs", "npc_routines", "vobs", "freepoints"]:
        fc = json.loads((tmp_path / f"{fn}.geojson").read_text("utf-8"))
        assert all("game_pos" in f["properties"] and "height_m" in f["properties"] for f in fc["features"])
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5: Pełne uruchomienie:** `python -m gothic_extract --game g2nk --world NEWWORLD --out output/g2nk/newworld` → istnieją wszystkie pliki z §5 specu; `report.txt` pokazuje liczności; `world.glb` < 500 MB.
- [ ] **Step 6: Weryfikacja orientacji (ręczna, z dowodem):** wyrenderuj PNG z góry (matplotlib, scatter waypointów w ENU: oś X=East, Y=North), obok tekstury mapy z gry (`MAP_NEWWORLD*.TEX` → PNG z VFS). Port/miasto, farma Onara i klasztor muszą leżeć w tych samych względnych miejscach (nie lustrzane). Jeśli są lustrzane — zmień znak w `game_to_enu` **i** w glTF, popraw test w Task 2, zapisz wniosek w `metadata.json`. Zapisz oba obrazy do `output/g2nk/newworld/_check/`.
- [ ] **Step 7:** Commit `feat: GeoJSON export, report and CLI`.
