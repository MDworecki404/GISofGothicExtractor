# Dane geoportalu — paczka v1

Dane jednego świata gry dla geoportalu, którego v1 służy do jednego: **wyszukać przedmiot albo
unikatową postać i pokazać, gdzie są**. Paczkę generuje `python -m gothic_extract.geoportal`
z pełnego wyniku ekstrakcji (`output/...`). Nie edytuj jej ręcznie, tylko wygeneruj ponownie.

## Układ współrzędnych

- Świat gry jest „przyklejony” do globusa w punkcie z `metadata.json → anchor`
  (domyślnie lon 0°, lat 0°, h 0 m), w skali 1:1 (1 jednostka gry = 1 cm).
- Wszystkie współrzędne w plikach to WGS84 `[lon, lat, h]`, `h` w metrach nad elipsoidą.
  Część terenu leży poniżej 0 m, więc **wyłącz globus** albo test głębokości względem terenu.
- `game_pos` (w `containers` i `characters`) to oryginalne współrzędne gry (cm), do przeliczeń i debugowania.

## Modele 3D

| Plik | Co | Uwagi |
|---|---|---|
| `world.glb` | siatka świata (teren, budynki) | metry, glTF Y-up, tekstury w środku |
| `vobs.glb` | wszystkie statyczne obiekty świata (VOB-y: drzewa, beczki, belki, budynki z ZEN) w **jednym pliku** | metry, glTF Y-up, tekstury w środku; jeden zwykły węzeł na każde wystąpienie (bez `EXT_mesh_gpu_instancing`, bo Cesium ion go gubi; siatki są współdzielone); razem z przedmiotami leżącymi na ziemi |
| `models/*.glb` | obiekty i przedmioty (drzewa, beczki, zioła…) | jeden plik na model, wszystkie wystąpienia jako instancje `EXT_mesh_gpu_instancing` |
| `models/index.json` | lista modeli: plik, rodzaj (`vob`/`item`), liczba instancji | także `unhandled`: typy obiektów jeszcze nieeksportowanych |
| `models/textures/*.png` | wspólne tekstury modeli | odwołania przez URI z plików `.glb` |

Wszystkie `.glb` mają ten sam układ: glTF = (Wschód, Góra, −Północ) w metrach względem kotwicy.
W CesiumJS wczytuj je **z tą samą macierzą i osiami**, inaczej Cesium obróci model:

```js
const modelMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(Cesium.Cartesian3.fromDegrees(lon0, lat0, h0));
const model = await Cesium.Model.fromGltfAsync({
  url: "world.glb", modelMatrix, upAxis: Cesium.Axis.Y, forwardAxis: Cesium.Axis.X,
});
```

## `search_index.json` — wyszukiwarka

```json
{ "version": 1, "entries": [
  { "id": "item:ITPL_PERM_HERB", "type": "item", "code": "ITPL_PERM_HERB",
    "name": "Szczaw królewski", "category": "Rośliny", "model": "previews/itpl_perm_herb.glb", "total": 11,
    "places": [ { "kind": "ground", "lon": 0.0019, "lat": 0.0036, "h": 79.5,
                  "label": "na ziemi", "ref": "item-123", "amount": 1 } ] },
  { "id": "character:VLK_412_HARAD", "type": "character", "code": "VLK_412_HARAD",
    "name": "Harad", "category": "VLK", "level": 30,
    "places": [ { "kind": "spawn", "label": "pojawia się (NW_CITY_…)", "chapter": null, … },
                { "kind": "routine", "label": "07:00–21:30 (z przerwami)", "routine": "START",
                  "is_default": true, "actions": ["TA_SMITH_ANVIL", …], … } ] }
] }
```

`kind` miejsca:

| `kind` | dla | znaczenie |
|---|---|---|
| `ground` | przedmiot | leży w świecie od początku gry |
| `script` | przedmiot | wstawiany przez skrypt przy starcie świata |
| `container` | przedmiot | w skrzyni; `label` mówi, czy zamknięta, klucz, kombinacja zamka |
| `npc` | przedmiot | w ekwipunku NPC (także zwykłych NPC i potworów); `ref` → `npcs.geojson`; `certainty`: `always`/`possible` |
| `spawn` | postać | gdzie skrypt wstawia postać do świata; `chapter`: numer rozdziału, gdy wstawienie należy do funkcji rozdziału, `null` = start świata albo dialog (w światach, do których wchodzi się dopiero w którymś rozdziale — Górnicza Dolina, rozdział 2 — te wstawienia dostają ten rozdział, bo wcześniej nie mogą zajść; wstawienia z dialogów i zdarzeń mogą w rzeczywistości nastąpić później); `ref` → `npcs.geojson` |
| `routine` | postać | gdzie postać przebywa w ciągu dnia; `is_default: false` = rutyna po zadaniu/zdarzeniu (nazwa w `routine`); `ref` → `character_places.geojson` |

`amount` = liczba sztuk w tym miejscu. `ref` = `id` obiektu w warstwie podanej w tabeli. `total` liczy tylko sztuki pewne (bez `possible`).

Wiele różnych przedmiotów ma tę samą nazwę („Klucz”, „Miecz”, „Runa”, „Zwój”…), więc w podpowiedziach wyszukiwarki pokazuj też `category`. Postać może mieć kilka kodów instancji (`codes`), np. Gorn przed i po dołączeniu do łowców smoków.

Etykieta rutyny łączy przyległe przedziały czasu; gdy przerw jest dużo, pokazuje zakres
„od–do (z przerwami)”, a całą dobę jako „cały dzień”. Pełna lista przedziałów jest w `character_places.geojson → times`.

Postać jest „unikatowa”:
- **ludzie** (także bez gildii, np. Diego, Lester) — imię nosi dokładnie jedna postać w tym świecie (Harad, Lothar, Wilk-najemnik — tak;
  Bandyta, Strażnik miejski — nie);
- **potwory** — imię jest jedyne w całej grze i potwór jest wstawiony raz w całej grze (Pan cienia Inubis, Czarny troll — tak;
  wilki, dziki, chrząszcze — nie).

## Model 3D przedmiotu (`model`)

Każdy wpis `type: "item"` w `search_index.json`, każdy obiekt w `items.geojson` i każda skrzynia
w `containers.geojson` ma pole `model`:

- **ścieżka do modelu podglądu względem `models/`**, np. `"previews/itfo_apple.glb"`;
- **`null`** — brak podglądu: przedmiot nie ma modelu w katalogu (`visual`), albo jego model nie jest
  statyczną siatką (np. łuki i kusze `.mms` — animowane, jeszcze nieeksportowane).
  Skrzynie mają dziś zawsze `null` (ich modele `.MDS` nie są jeszcze eksportowane).

Pełny adres buduje aplikacja, np. przy hostingu modeli pod
`https://gisofgothicmodels.dworecki.dev/g2nk/khorinis/models/`:

```js
const MODELS_BASE_URL = "https://gisofgothicmodels.dworecki.dev/g2nk/khorinis/models/";
const url = item.model ? MODELS_BASE_URL + item.model : null; // …/models/previews/itfo_apple.glb
```

### Modele podglądu (`models/previews/`)

- Jeden plik glTF Binary na model przedmiotu (`visual`). Przedmioty o tym samym modelu (np. kilka kluczy)
  wskazują ten sam plik.
- **Jedna kopia** przedmiotu, bez instancji (`EXT_mesh_gpu_instancing`) i bez pozycji świata —
  gotowe do pokazania w karcie przedmiotu.
- Układ jak pozostałe `.glb` (glTF Y-up: Wschód, Góra, −Północ), **w metrach** (realny rozmiar);
  przedmiot jest **wyśrodkowany w poziomie** na początku układu, a jego **najniższy punkt ma y = 0**
  (stoi na „podłodze”).
- Tekstury: odwołania względne `../textures/*.png`, czyli do wspólnego `models/textures/`.
  Na hostingu `previews/` musi leżeć obok `textures/` pod tym samym adresem bazowym.
- `models/previews/index.json`: dla każdego pliku `file`, `visual`, `triangles`,
  `bounds_m` (`{x, y, z}` — rozmiar pudełka w metrach) i `codes` (kody przedmiotów z tym modelem).

Pliki `models/*.glb` (bez `previews/`) to nadal modele **świata** z instancjami: jeden plik zawiera wszystkie
wystąpienia obiektu w pozycjach świata. Używaj ich do mapy, nie do karty przedmiotu.

## Warstwy GeoJSON

| Plik | Obiekt | Najważniejsze pola |
|---|---|---|
| `items.geojson` | przedmiot w świecie | `code`, `name`, `category`, `amount`, `source` (`zen`/`script`), `spot`, `model` |
| `containers.geojson` | skrzynia | `locked`, `key`, `pick_string`, `contents: [{code, name, category, amount}]`; `name` to surowa nazwa z gry (np. `MOBNAME_CHEST`), `visual` = model skrzyni, `model` = ścieżka podglądu względem `models/` albo `null` |
| `characters.geojson` | unikatowa postać (miejsce pojawienia się) | `code`, `codes`, `name`, `guild_name`, `level`, `chapter`, `inventory`, `game_pos`, `height_m` |
| `npcs.geojson` | każde wstawienie NPC (także zwykłych i potworów) | `code`, `name`, `guild_name`, `level`, `chapter`, `insert_waypoint` |
| `character_places.geojson` | miejsce z rutyny postaci | `npc_code`, `npc_name`, `routine`, `is_default`, `waypoint`, `times`, `actions` |

Wszystkie teksty są po polsku, w UTF-8.

## Rozmiar

Warstwy i indeks to ~2 MB, `world.glb` ~150 MB, `models/` ~60 MB. Modele dobrze jest serwować z CDN albo Cesium ion (który sam tnie `.glb` na 3D Tiles).

## Światy w paczkach

| Katalog | `world` | Uwagi |
|---|---|---|
| `dist/g2nk/khorinis` | `NEWWORLD` | Khorinis; `chapter = null` = start gry |
| `dist/g2nk/gornicza-dolina` | `OLDWORLD` | Górnicza Dolina; `chapter` zawsze wypełnione (najwcześniej 2). Wstawienia startowe, z dialogów i zdarzeń mają rozdział 2 (pierwsze wejście do Doliny) — to dolna granica, nie dokładny moment. Łuki i kusze nie mają modelu podglądu (`model: null`), jak w Khorinis. |
| `dist/g2nk/jarkendar` | `ADDONWORLD` | Jarkendar (Noc Kruka); `chapter` zawsze wypełnione (3 albo 4). Wstawienia startowe, z dialogów i zdarzeń mają rozdział 3 (`first_chapter` — pierwsze wejście do Jarkendaru) — to dolna granica, nie dokładny moment. Pominięto deweloperskie listy `USEJOLY*` (przedmioty, których gra nigdy nie wydaje; zdublowałyby potwory z rozdziału 4). Łuki i kusze nie mają modelu podglądu (`model: null`); skrzynie nie mają modelu (MDS nie jest eksportowany), jak w pozostałych światach. |

Układ plików, osie i kotwica są takie same we wszystkich paczkach; światy ogląda się osobno.
