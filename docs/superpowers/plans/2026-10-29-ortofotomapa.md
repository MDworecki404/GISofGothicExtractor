# Ortofotomapa (GeoTIFF dla Cesium ion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Moduł `gothic_extract.ortho` renderuje z `world.glb` (opcjonalnie `vobs.glb`) georeferencjonowany GeoTIFF (EPSG:4326) widoku z góry dla wskazanego świata.

**Architecture:** `glbmesh` wczytuje siatki glb do metrów ENU z teksturami, `raster` rasteryzuje jeden blok (kafelek) rzutem prostopadłym z z-buforem po osi Up, `geotiff` zapisuje kafelki strumieniowo przez `tifffile` z tagami georeferencji, `georef` liczy siatkę EPSG:4326 tym samym wzorem co `coords.enu_to_lonlat`. CLI skleja całość, pilnuje rozmiaru i pisze `ortho.json`.

**Tech Stack:** Python 3.13, numpy, Pillow, pygltflib (już są), `tifffile` (nowa zależność), pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-ortofotomapa-design.md`

## Global Constraints

- GeoTIFF: EPSG:4326, RGBA 8-bit, kafelki 512×512, kompresja Deflate (bezstratna), zapis strumieniowy kafelek po kafelku; bez GDAL i bez rasterio.
- Domyślne `--gsd` = 0.25 m/px; `--bbox` pozwala zejść do 0.10 i 0.01.
- Rozmiar piksela w stopniach: `dx = gsd/(N·cos φ)`, `dy = gsd/M` (promienie krzywizny jak w `coords.enu_to_lonlat`).
- Rzut prostopadły z góry; wygrywa najwyższy punkt (oś Up); bez oświetlenia; piksele bez trójkąta mają alfa 0.
- Osie glTF z paczki: `glTF = (E, Up, -N)` w metrach; kotwica WGS84 z `metadata.json` (`anchor.lon/lat/h`).
- Zabezpieczenie rozmiaru: bez jawnego `--bbox` odmowa, gdy piksele > 2·10⁹.
- Wyjście: `dist/<gra>/<świat>/ortho/<slug>_<gsd>.tif` i `ortho.json`; `package.version` w paczce bez zmian (4).
- Kod w stylu repo: docstring modułu po angielsku, krótkie komentarze, `from __future__` niepotrzebne, testy `tools/tests/test_ortho_*.py`.
- Commity tylko jeśli użytkownik o nie prosi w sesji; kroki „Commit” to punkty kontrolne.

## Review Focus

- bbox całkowicie poza światem: poprawny, przezroczysty plik, bez wyjątku (Task 3 i 5).
- materiał bez tekstury (tylko `baseColorFactor`): jednolity kolor, bez błędu (Task 2 i 3).
- UV poza [0,1]: tekstura się powtarza (wrap REPEAT) (Task 3).
- tekstury z alfa (MASK, liście): dziury pokazują niższą geometrię zamiast czarnych/przezroczystych plam (Task 3).
- trójkąty zdegenerowane i pionowe ściany: brak NaN/dzielenia przez zero, ściany nic nie rysują (Task 3).

---

### Task 1: Siatka georeferencji

**Files:**
- Create: `tools/gothic_extract/ortho/__init__.py` (pusty, docstring modułu)
- Create: `tools/gothic_extract/ortho/georef.py`
- Test: `tools/tests/test_ortho_georef.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Grid`: `e0, n1, gsd: float` (lewy-górny róg w ENU, m), `width, height: int`, `lon_min, lat_max, dx_deg, dy_deg: float`.
  - `make_grid(bbox: tuple[float, float, float, float], gsd: float, lon0: float, lat0: float) -> Grid` — `bbox = (e0, n0, e1, n1)` w ENU m względem kotwicy; `width = ceil((e1-e0)/gsd)`, `height = ceil((n1-n0)/gsd)`; `lon_min`/`lat_max` to `enu_to_lonlat` rogu `(e0, n1)`.
  - `pixel_size_deg(gsd: float, lat0: float) -> tuple[float, float]` — `(dx, dy)`.

- [ ] **Step 1: Napisz testy** `test_pixel_size_matches_enu_to_lonlat` (dla `gsd=1`, `lat0` w `{0, 50}`: `dx` równe `enu_to_lonlat(1,0,0,0,lat0,0)[0]`, `dy` równe `enu_to_lonlat(0,1,0,0,lat0,0)[1]-lat0`, `rel=1e-9`), `test_grid_size_and_corner` (bbox `(0,0,10,5)`, gsd 0.25 → `width==40`, `height==20`, `lat_max` i `lon_min` zgodne z `enu_to_lonlat(0,5,0,...)`), `test_grid_rounds_up` (bbox 10.1×5 przy gsd 1 → width 11).
- [ ] **Step 2: Uruchom** `python -m pytest tools/tests/test_ortho_georef.py -v` (z katalogu `tools`); oczekiwane: FAIL (brak modułu).
- [ ] **Step 3: Zaimplementuj** `Grid`, `make_grid`, `pixel_size_deg` w `georef.py`, wołając `coords.enu_to_lonlat` zamiast powtarzać wzór.
- [ ] **Step 4: Uruchom testy**; oczekiwane: PASS.
- [ ] **Step 5: Commit** `feat: siatka georeferencji ortofotomapy`

### Task 2: Wczytanie siatek glb do ENU

**Files:**
- Create: `tools/gothic_extract/ortho/glbmesh.py`
- Test: `tools/tests/test_ortho_glbmesh.py`

**Interfaces:**
- Consumes: nic.
- Produces:
  - `@dataclass class Part`: `pos: np.ndarray` (n,3 float64, kolumny `E, N, Up` w m), `uv: np.ndarray` (n,2 float32), `tri: np.ndarray` (m,3 int64), `texture: np.ndarray | None` (h,w,4 uint8), `color: tuple[float, float, float]` (z `baseColorFactor`, domyślnie 0.5,0.5,0.5), `name: str`.
  - `load_parts(path: Path) -> list[Part]` — przechodzi po scenie, stosuje transformacje węzłów (TRS lub macierz, hierarchicznie), konwertuje `(x,y,z)_glTF → (E=x, N=-z, Up=y)`, dekoduje PNG-i, nie zmienia kolejności indeksów.
  - `texel_size_cm(part: Part) -> float | None` — mediana (po trójkątach) długości krawędzi w świecie ÷ długość krawędzi w UV ÷ szerokość tekstury, w cm; `None` bez tekstury lub bez poprawnych trójkątów.

- [ ] **Step 1: Napisz testy** na syntetycznym glb zbudowanym w teście przez `pygltflib` (fixture `tmp_path`): (a) `test_axes_conversion` — wierzchołek glTF `(1,2,-3)` daje `pos == (1, 3, 2)` (E=1, N=3, Up=2); (b) `test_node_transform_applied` — węzeł z `translation=[10,0,0]` przesuwa E o 10; (c) `test_untextured_material_uses_color` — `texture is None`, `color == (1,0,0)` dla `baseColorFactor=[1,0,0,1]`; (d) `test_texel_size_cm` — kwadrat 1×1 m z UV 0..1 i teksturą 100 px daje ≈ 1.0 cm.
- [ ] **Step 2: Uruchom** `python -m pytest tools/tests/test_ortho_glbmesh.py -v`; oczekiwane: FAIL.
- [ ] **Step 3: Zaimplementuj** `Part`, `load_parts`, `texel_size_cm`. Wzoruj odczyt accessorów na `_read` w `tools/tests/test_mesh_export.py`; współdzielone siatki (wiele węzłów) rozwijaj do osobnych `Part`-ów z tą samą referencją tekstury (cache po indeksie obrazu).
- [ ] **Step 4: Uruchom testy**; oczekiwane: PASS.
- [ ] **Step 5: Commit** `feat: wczytanie siatek glb do ENU dla ortofotomapy`

### Task 3: Rasteryzacja bloku

**Files:**
- Create: `tools/gothic_extract/ortho/raster.py`
- Test: `tools/tests/test_ortho_raster.py`

**Interfaces:**
- Consumes: `Part` z Task 2.
- Produces: `render_block(parts: list[Part], e0: float, n1: float, gsd: float, width: int, height: int) -> np.ndarray` — zwraca `(height, width, 4) uint8`; piksel `(r, c)` ma środek w `E = e0 + (c+0.5)·gsd`, `N = n1 − (r+0.5)·gsd`; brak trójkąta → `(0,0,0,0)`.

- [ ] **Step 1: Napisz testy** (`Part`-y tworzone ręcznie w teście): `test_flat_triangle_fills_expected_pixels` (kwadrat z dwóch trójkątów o kolorze `(1,0,0)` pokrywa dokładnie piksele wewnątrz, reszta alfa 0); `test_highest_wins` (dwa kwadraty na Up 1 i 5, wygrywa wyższy niezależnie od kolejności); `test_texture_sampled_by_uv` (tekstura 2×2 o czterech kolorach, kwadrat 2×2 px → piksele mają odpowiednie kolory, sampling najbliższy-sąsiad lub bilinearny, ale kolory w środkach teksteli dokładne); `test_uv_wraps` (UV 0..2 na kwadracie powtarza teksturę); `test_masked_alpha_shows_lower_geometry` (górna tekstura z alfa 0 w jednej ćwiartce odsłania niższy kwadrat); `test_untextured_uses_color`; `test_degenerate_and_vertical_triangles_ignored` (trójkąt zerowego pola i pionowa ściana → brak wyjątku, brak NaN, wynik całkowicie przezroczysty); `test_block_outside_parts_is_transparent`.
- [ ] **Step 2: Uruchom** `python -m pytest tools/tests/test_ortho_raster.py -v`; oczekiwane: FAIL.
- [ ] **Step 3: Zaimplementuj `render_block`.** Dla każdego `Part` odfiltruj trójkąty, których bbox przecina blok (wektorowo), odrzuć zdegenerowane (|pole w E,N| < 1e-12). Rasteryzuj wektorowo w numpy: trójkąty grupuj w kubełki po wymiarach bbox w pikselach (potęgi dwójki), dla każdego kubełka licz współrzędne barycentryczne na siatce pikseli bbox, wysokość Up i UV interpoluj barycentrycznie. Fragmenty z teksturą o alfa < 128 odrzuć (MASK). Wynik części scalaj z buforem głębokości bloku (`np.where(z > depth)`), nie przez kolejność rysowania. Próbkowanie tekstury z wrap `uv mod 1`, piksel `floor(uv·size)`.
- [ ] **Step 4: Uruchom testy**; oczekiwane: PASS.
- [ ] **Step 5: Commit** `feat: rasteryzacja bloku ortofotomapy z-buforem`

### Task 4: Zapis GeoTIFF

**Files:**
- Modify: `tools/requirements.txt` (dopisz `tifffile`)
- Create: `tools/gothic_extract/ortho/geotiff.py`
- Test: `tools/tests/test_ortho_geotiff.py`

**Interfaces:**
- Consumes: `Grid` z Task 1.
- Produces: `write_geotiff(path: Path, grid: Grid, render_tile: Callable[[int, int, int, int], np.ndarray], tile: int = 512) -> None` — `render_tile(row0, col0, rows, cols)` zwraca `(rows, cols, 4) uint8`; writer woła go kafelek po kafelku, uzupełnia kafelki brzegowe zerami do pełnych 512×512, zapisuje kompresję Deflate, tagi: ModelPixelScale (33550) `(dx_deg, dy_deg, 0)`, ModelTiepoint (33922) `(0,0,0, lon_min, lat_max, 0)`, GeoKeyDirectory (34735) `[1,1,0,3, 1024,0,1,2, 1025,0,1,1, 2048,0,1,4326]`.

- [ ] **Step 1: Zainstaluj zależność** `pip install tifffile` i dopisz ją do `tools/requirements.txt`.
- [ ] **Step 2: Napisz testy**: `test_roundtrip_pixels_and_tags` (siatka 700×300 px, `render_tile` zwraca wzór zależny od `(row0,col0)`; po zapisie `tifffile.imread` zgadza się co do piksela, strona jest kafelkowana 512×512, dtype uint8, 4 próbki, tagi 33550/33922/34735 mają wartości z Grid), `test_edge_tiles_are_cropped_not_smeared` (poza obrazem nie ma śmieci), `test_render_tile_called_per_tile_not_whole` (licznik wywołań == liczba kafelków, żaden wywołany z `rows > 512`).
- [ ] **Step 3: Uruchom** `python -m pytest tools/tests/test_ortho_geotiff.py -v`; oczekiwane: FAIL.
- [ ] **Step 4: Zaimplementuj `write_geotiff`** przez `tifffile.TiffWriter.write(generator_kafelków, shape=(h,w,4), dtype="uint8", tile=(tile,tile), photometric="rgb", extrasamples=["unassalpha"], compression="deflate", extratags=[...])`, kafelki w kolejności wierszowej.
- [ ] **Step 5: Uruchom testy**; oczekiwane: PASS.
- [ ] **Step 6: Commit** `feat: zapis GeoTIFF EPSG:4326 dla ortofotomapy`

### Task 5: CLI, zabezpieczenia i raport

**Files:**
- Create: `tools/gothic_extract/ortho/__main__.py`
- Modify: `tools/gothic_extract/geoportal_README.md` (sekcja „Ortofotomapa”: komenda, wynik, wgranie do ion jako imagery, uwaga o teksturach G3)
- Test: `tools/tests/test_ortho_cli.py`

**Interfaces:**
- Consumes: `make_grid`, `load_parts`, `texel_size_cm`, `render_block`, `write_geotiff`.
- Produces:
  - `check_size(width: int, height: int, bbox_given: bool, limit: int = 2_000_000_000) -> None` — `ValueError` z komunikatem (zawiera liczbę pikseli i sugestię `--bbox`/większe `--gsd`), gdy `not bbox_given` i `width*height > limit`.
  - `build_ortho(pkg: Path, gsd: float, bbox: tuple | None, include_vobs: bool, out: Path | None) -> dict` — czyta `pkg/metadata.json`, `pkg/world.glb` (i `vobs.glb`), bbox domyślnie z pozycji wszystkich części, zapisuje TIFF i `ortho.json` (`crs`, `bbox`, `gsd`, `width`, `height`, `anchor`, `texel_cm_min/median/max`, `warnings`), zwraca słownik z ortho.json.
  - CLI: `python -m gothic_extract.ortho --pkg dist/g2nk/khorinis --gsd 0.25 [--bbox E0 N0 E1 N1] [--include-vobs] [--out ścieżka.tif]`.
  - W `warnings` wpis, gdy `gsd` < mediana `texel_size_cm` materiałów × 0.5 (obraz drobniejszy niż tekstury).

- [ ] **Step 1: Napisz testy** na syntetycznej paczce (`tmp_path` z `metadata.json` i małym `world.glb` jak w Task 2): `test_check_size_refuses_whole_world_at_1cm`, `test_check_size_allows_with_bbox`, `test_build_ortho_writes_tif_and_json` (plik istnieje, `ortho.json` ma `crs == "EPSG:4326"` i zgodne `width/height`, lewy-górny róg z kotwicy), `test_bbox_outside_world_gives_transparent_file` (alfa wszędzie 0, bez wyjątku), `test_warns_when_finer_than_texture`.
- [ ] **Step 2: Uruchom** `python -m pytest tools/tests/test_ortho_cli.py -v`; oczekiwane: FAIL.
- [ ] **Step 3: Zaimplementuj** `check_size`, `build_ortho`, `main(argv)` z `argparse` (styl `geoportal.main`). `render_tile` przekazywane do writera woła `render_block` dla bboxu kafelka.
- [ ] **Step 4: Uruchom całe testy ortho** `python -m pytest tools/tests -k ortho -v`; oczekiwane: PASS.
- [ ] **Step 5: Commit** `feat: CLI ortofotomapy, zabezpieczenia i dokumentacja`

### Task 6: Weryfikacja na prawdziwych danych

**Files:** brak zmian w kodzie, chyba że weryfikacja ujawni błąd.

- [ ] **Step 1: Mały wycinek Khorinis** `python -m gothic_extract.ortho --pkg dist/g2nk/khorinis --gsd 0.10 --bbox <ok. 200×200 m wokół znanego miasta, współrzędne z dist/g2nk/khorinis/characters.geojson po konwersji>`; oczekiwane: plik powstaje, `ortho.json` bez błędów, obraz czytelny po otwarciu (`tifffile.imread` → PNG do oględzin).
- [ ] **Step 2: Cały Khorinis w 0.5 m** (czas i pamięć zanotuj); sprawdź, że rozmiar pliku mieści się w limitach ion (zajrzyj do aktualnej dokumentacji ion o GeoTIFF).
- [ ] **Step 3: Zgodność z punktami**: nałóż `characters.geojson` na ortofoto (skrypt jednorazowy w scratchpadzie, matplotlib); budynki i postacie mają się zgadzać. Zmierz przesunięcie względem modelu 3D w Cesium (krzywizna), wynik wpisz do README.
- [ ] **Step 4: Myrtana (G3)** w 1 m: potwierdź ostrzeżenie o teksturach 512 px i czas renderu.
- [ ] **Step 5: Commit** poprawek, jeśli były.
