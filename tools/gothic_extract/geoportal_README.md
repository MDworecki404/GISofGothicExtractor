# Dane geoportalu — paczka v6

Dane jednego świata gry dla geoportalu: **wyszukać przedmiot, unikatową postać albo zadanie (quest)
i pokazać, gdzie są**. Paczki wszystkich światów gry buduje jedno polecenie (z `PYTHONPATH=tools`
w repozytorium ekstraktora):

```
python -m gothic_extract.package --game g1              # z istniejącej ekstrakcji output/g1/<zen>
python -m gothic_extract.package --game g2nk --extract  # najpierw pełna ekstrakcja każdego świata
python -m gothic_extract.package --game g3 --extract    # Gothic 3 (osobny czytnik silnika Genome)
python -m gothic_extract.validate                       # sama walidacja paczek wszystkich gier w dist/
python -m gothic_extract.descriptions --game all        # tylko dopisanie opisów przedmiotów do gotowych paczek
```

`package` robi dla każdego świata: warstwy i indeks (`gothic_extract.geoportal`), questy
(`gothic_extract.quests_package`, wersja paczki 6: kolejność etapów), prędkości ruchu (`gothic_extract.movement_speeds`) i lokacje
(`gothic_extract.locations`, `gothic_extract.g3.locations`, wersja paczki 5),
a na końcu waliduje paczki. Nie edytuj paczki ręcznie, tylko wygeneruj ją ponownie. Same `geoportal`
i `quests_package` uruchamiane osobno zostawiają paczkę niedokończoną (`geoportal` zapisuje wersję 3).

## Układ współrzędnych

- Świat gry jest „przyklejony” do globusa w punkcie z `metadata.json → anchor`
  (domyślnie lon 0°, lat 0°, h 0 m), w skali 1:1 (1 jednostka gry = 1 cm).
- Wszystkie współrzędne w plikach to WGS84 `[lon, lat, h]`, `h` w metrach nad elipsoidą.
  Część terenu leży poniżej 0 m, więc **wyłącz globus** albo test głębokości względem terenu.
- `game_pos` (w `containers` i `characters`) to oryginalne współrzędne gry (cm), do przeliczeń i debugowania.

## `metadata.json`

| Pole | Znaczenie |
|---|---|
| `game` | `g2nk`, `g1` albo `g3` |
| `engine` | tylko w `g3`: `genome` (silnik Gothic 3) |
| `world` | nazwa pliku ZEN świata bez rozszerzenia (`NEWWORLD`, `WORLD`…) |
| `anchor`, `axes`, `gltf_axes` | kotwica WGS84 `{lon, lat, h}` i osie świata (opis wyżej) |
| `package.version` | 6 (5 = bez kolejności etapów i miejsc etapów w `quests.json`, wersja `quests.json` 1; 4 = bez `locations.json`: aplikacja czyta taką paczkę jako „brak lokacji”) |
| `package.counts` | `search_items`, `search_items_with_model`, `search_characters`, `items`, `containers`, `npcs`, `character_places`, `quests`, `locations`, a tam gdzie jest sieć dróg też `waypoints`, `waypoint_edges`; zgadzają się z zawartością plików (sprawdza `gothic_extract.validate`) |
| `package.files` | pliki i katalogi paczki (katalog z `/` na końcu) |
| `guild_names` | kod gildii → polska nazwa **z gry** (tablica `TXT_GUILDS` skryptów), dla gildii występujących w tym świecie; `null`, gdy gra nie ma tekstu. Kody to wartości `guild_name` w `npcs.geojson` i `characters.geojson`. |
| `movement_speeds_m_s` | prędkości gracza w m/s: `walk`, `run`, `sneak`, `walk_armed`, liczone z pętli animacji szkieletu HUMANS |
| `movement_speeds_animations` | nazwy animacji `.MAN`, z których policzono prędkości (w G3 puste) |
| `movement_speeds_parameters` | tylko G3: `{source, properties}` — parametry ruchu, z których policzono prędkości |
| `zenkit_version`, `generated_at` | informacyjne |

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
  Skrzynie G1/G2 mają dziś zawsze `null` (ich modele `.MDS` nie są jeszcze eksportowane); w G3 mają podgląd.

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

## Opis przedmiotu (`description`)

Opcjonalne pole tekstowe (UTF-8, bez spacji na brzegach) przy **każdym rekordzie przedmiotu** z `name`:

- wpisy `type: "item"` w `search_index.json`;
- `properties` w `items.geojson`;
- pozycje `contents` w `containers.geojson`;
- pozycje `inventory` w `npcs.geojson` i `characters.geojson`;
- `items[]` zestawów w `treasure_sets.json` (tylko G3);
- `items[]` zadań w `quests.json`.

Wiele przedmiotów ma w grze tę samą ogólną nazwę („Mikstura”, „Zwój”, „Amulet”), a różni je dopiero opis,
np. `ITPO_HEALTH_01`: `name` „Mikstura”, `description` „Esencja lecznicza”. Pokazuj `description` jako nazwę
przedmiotu, a `name` zostaw w wyszukiwaniu. Pola **nie ma**, gdy gra nie ma opisu albo jest on taki sam jak `name`;
`name`, `code` i pozostałe pola się nie zmieniają. Wersja paczki zostaje 4 (pole jest wstecznie zgodne).

- **G1, G2**: `C_ITEM.description` ze skryptów (tytuł przedmiotu w ekwipunku gry).
- **G3**: tekst `ITEMDESC_<kod>` to opis z dymka („Soczyste jabłko.”), nie nazwa, więc trafia do paczki tylko tam,
  gdzie nazywa odmianę wspólnej nazwy: nazwę nosi kilka kodów tego samego rodzaju, tekstu nie ma żaden inny przedmiot
  i brzmi jak nazwa (zawiera pierwsze słowo nazwy, najwyżej 6 słów — „Amulet” → „Amulet magii”) albo opis ma cała
  rodzina tej nazwy („Mikstura przemiany” → „Przemienia w wilka”). Kropka na końcu jednozdaniowego tekstu jest
  usuwana. Przepis, zwój, zaklęcie i umiejętność o nazwie swojego produktu oraz rośliny `_Snow` nie są odmianami
  i zostają z samą nazwą.

Część nazw zostaje wspólna, bo gra ich nie rozróżnia (np. klucze „Klucz do kufra”, runa i zwój tego samego czaru,
rośliny `_Snow`); wtedy pomaga `category` i `code`. Do istniejącej paczki opisy dopisuje
`python -m gothic_extract.descriptions --game <gra> [--world <slug>]` (bez ponownej ekstrakcji; zmienia tylko
pliki JSON/GeoJSON wymienione wyżej).

## Warstwy GeoJSON

| Plik | Obiekt | Najważniejsze pola |
|---|---|---|
| `items.geojson` | przedmiot w świecie | `code`, `name`, `description`, `category`, `amount`, `source` (`zen`/`script`), `spot`, `model` |
| `containers.geojson` | skrzynia | `locked`, `key`, `pick_string`, `contents: [{code, name, description?, category, amount}]`; `name` to surowa nazwa z gry (np. `MOBNAME_CHEST`), `visual` = model skrzyni, `model` = ścieżka podglądu względem `models/` albo `null` |
| `characters.geojson` | unikatowa postać (miejsce pojawienia się) | `code`, `codes`, `name`, `guild_name`, `level`, `chapter`, `inventory`, `game_pos`, `height_m` |
| `npcs.geojson` | każde wstawienie NPC (także zwykłych i potworów) | `code`, `name`, `guild_name`, `level`, `chapter`, `insert_waypoint` |
| `character_places.geojson` | miejsce z rutyny postaci | `npc_code`, `npc_name`, `routine`, `is_default`, `waypoint`, `times`, `actions` |

Wszystkie teksty są po polsku, w UTF-8.

### `waypoints.json` — sieć dróg (waynet)

Sieć waypointów świata: po niej gra prowadzi NPC, więc nadaje się do wyznaczania tras po drogach z gry.
Zwarty JSON (bez spacji, UTF-8), w paczkach wszystkich światów z siecią: G1, G2 NK, Archolos i G3. Pełny
`waypoints.geojson` zostaje tylko w `output/<gra>/<świat>/` (debug) i nie trafia do paczki. **Źródło sieci różni się
między grami**: G1, G2 i Archolos mają waynet zapisany w świecie (punkty nazwane, krawędzie z gry), a G3 go nie ma —
patrz „Różnice Gothic 3” niżej.

```json
{"version":1,"game":"g2nk","world":"NEWWORLD","nodes":[["NAZWA",lon,lat,height,under_water],…],"edges":[[i,j],…]}
```

| Pole | Znaczenie |
|---|---|
| `version` | wersja formatu, obecnie `1` |
| `game`, `world` | klucz gry i nazwa ZEN świata (jak w `metadata.json`) |
| `nodes` | punkty: `[name, lon, lat, height, under_water]`; `lon` i `lat` zaokrąglone do 6 miejsc (~0,1 m), `height` do 0,1 m, `under_water` to `0`/`1`; w kolejności sieci z gry bez `TOT` |
| `edges` | krawędzie `[i, j]` = indeksy w `nodes`, `i < j`, każda krawędź raz, bez pętli; krawędź jest dwukierunkowa |

- `name` jest taki sam jak `waypoint` w `character_places.geojson` i `insert_waypoint` w `npcs.geojson` — po nim łączy się
  miejsca z siecią (w G1/G2 i Archolosie). Nazwa jest unikatowa w świecie. Część nazw z tych warstw to freepointy (`FP_*`)
  i znaczniki (`EVT_*`), których w sieci nie ma. W G3 `insert_waypoint` to nazwa sektora i do sieci nie pasuje.
- Waypoint `TOT` (miejsce odstawienia usuniętych NPC) i jego krawędzie są usunięte z paczki.
- Nie ma `game_pos`, `id` ani `source`; linię krawędzi składa się z pozycji dwóch węzłów.
- Sieć nie musi być spójna: `gothic_extract.validate` podaje liczbę składowych i liczbę węzłów w największej (Khorinis:
  2952 z 2958). Węzły poza największą składową są nieosiągalne po krawędziach z reszty sieci.

## `quests.json` — zadania

Wpis `type: "quest"` w `search_index.json` jest skrócony (`id`, `code`, `name`, `category`: `Misja`/`Notatka`,
`giver`, `chapter`, `places` — tylko miejsca pojawienia się zleceniodawcy i celów). Pełne dane są w `quests.json`
(`{version, game, world, quests: [...]}`). Klucz zadania to jego nazwa w dzienniku; stałe tematu o tej samej nazwie
(`TOPIC_X` w G2, `CH3_X` w G1) są aliasami jednego zadania (`aliases`), `id` = `quest:<code>`.

| Pole | Znaczenie |
|---|---|
| `section` | `mission` albo `note` |
| `chapter`, `chapter_source` | rozdział, który zadanie wymaga (`function`/`condition`), albo `null` |
| `giver`, `giver_certainty`, `giver_candidates` | zleceniodawca (`{code, name}`) albo lista kandydatów |
| `order` | `"dependency"`: co najmniej 80 % etapów ma `requires_source` inne niż `script_order`, więc `requires`/`level` nadają się do narysowania trasy; `"script"`: etapy są w kolejności występowania w skryptach (nie gry) i aplikacja nie powinna rysować trasy |
| `stages_with_place` | liczba etapów z `place` ≠ `null` |
| `stages` | etapy: `kind` (`create`/`entry`/`status`/`close`), `text`, `status`, `function`, `sources` (dialog / użycie przedmiotu), `conditional`, a od v6 kolejność i miejsce (niżej) |
| `characters`, `items` | postacie i przedmioty zadania z `role` (w G3 także `target`) i `certainty`; `in_index: true` ⇒ `id` wskazuje wpis w `search_index.json`, inaczej `id: null` |
| `rewards` | `xp` i `xp_certainty` |
| `worlds` | wszystkie światy gry (nazwy ZEN), w których zadanie ma udział; zadanie wielo-światowe jest w paczce **każdego** z nich pod tym samym `id`, a `places` zawiera tylko miejsca z danego świata |
| `places` | miejsca na mapie: jak w indeksie (`kind`, `lon`, `lat`, `h`, `ref`…) plus `role` (`giver`/`target`/`stage`), `npc_code`, `certainty` |

Zadanie, w którym żaden świat nie ma udziału, nie trafia do żadnej paczki.

### Kolejność i miejsce etapów (quests.json v2, paczka v6)

Każdy etap ma dodatkowo (stare pola bez zmian):

| Pole | Znaczenie |
|---|---|
| `requires` | `seq` etapów **tego** zadania, które muszą zajść wcześniej (rosnąco; `[]` = początek). To redukcja przechodnia: nie ma krawędzi, którą da się wyprowadzić z innych. Graf nie ma cykli |
| `requires_source` | skąd to wiemy: `condition` (odczytane z warunków), `dialog_order` (heurystyka), `script_order` (zgadywanie) |
| `level` | głębokość: 0 = start, inaczej 1 + największy `level` z `requires` (najdłuższa ścieżka) |
| `alternative_group` | litera (`"A"`, `"B"`…) grupy etapów **wzajemnie się wykluczających**, albo `null`. Etapy tej samej grupy nie zajdą oba |
| `place` | gdzie gracz ma być, by etap zaszedł, albo `null`: `{lon, lat, h, label, npc_code, waypoint, source, certainty}` |
| `hours` | przedziały `[od, do]` (`"HH:MM"`) z `Wld_IsTime` w warunku dialogu; `[]` = bez ograniczenia (tylko G1/G2/Archolos) |

`requires_source` — co jest pewne, a co nie:

- **`condition` (pewne w granicach analizy)**: funkcja warunku dialogu (`C_INFO.condition`, G1/G2/Archolos) jest
  wykonywana symbolicznie na bajtkodzie (bez uruchamiania VM). Z warunku czytamy `Npc_KnowsInfo(hero, DIA_X)`,
  `MIS_<zadanie> == LOG_*`, `Npc_HasItems`, `Kapitel`, `Npc_IsDead`, `Wld_IsTime`, zmienne-flagi i `&&`/`||`/`!`;
  alternatywy (`||`) dają wspólną część wymagań. Atom wskazuje etap, jeśli dialog/funkcja, która go spełnia, jest etapem
  tego zadania: dialog poznany (`KnowsInfo`), stan zadania (`LOG_RUNNING` ⇒ etap `RUNNING`), flaga przypisana przez
  funkcję etapu (z dokładnością do bloku `if`; gdy flagę ustawia też coś poza zadaniem, nie ma krawędzi), przedmiot
  wydany graczowi w etapie. Dochodzą `if` wokół samego wpisu do dziennika (to jedyne źródło dla zadań Archolosa
  wyzwalanych w `EVENTSMANAGER_*`). **`requires: []` przy `condition`** znaczy: warunek jest w pełni zrozumiany i
  żaden jego element nie wskazuje innego etapu tego zadania (np. tylko rozdział, godzina, inne zadanie) — to nie
  jest „nie wiadomo”. G3: `Parent` dialogu i `CondPlayerKnows` (zdarzenie, które podnosi `SetGameEvent` w innych
  dialogach); dialog startowy (`ConditionType` 6) bez takich warunków to początek.
- **`dialog_order` (heurystyka)**: warunków nie dało się rozstrzygnąć; wymagany jest etap poprzedniego dialogu tej
  samej postaci w zadaniu (niższe `C_INFO.nr`). Tylko G1/G2/Archolos.
- **`script_order` (zgadywanie)**: brak danych (etap z wyzwalacza bez warunku, warunek odwołuje się do funkcji
  pomocniczej lub zmiennej bez źródła, G3 bez jawnego warunku); `requires` = poprzedni etap w kolejności skryptu
  (poprzedni z innej funkcji), `[]` dla pierwszego.

`alternative_group` powstaje tylko z wzajemnych wykluczeń: etap A wymaga `!Npc_KnowsInfo(B)` lub flagi `== FALSE`
ustawianej w B, a B odwrotnie względem A.

`place` (G1/G2/Archolos i G3): dla etapu z dialogiem tej jednej postaci — jej miejsce w tym świecie. Postać z rutynami:
domyślne rutyny (`is_default`) bez snu; z godzin dialogu, jeśli są, inaczej ta, która obejmuje południe
(`source: "routine"`); postać bez rutyn z dokładnie jednym miejscem pojawienia się: `source: "spawn"`. `certainty`:
`only` = był jeden kandydat, `default` = wybrano pierwszego z kilku. `waypoint` = węzeł z rutyny/pojawienia się,
`label` = „<imię>: <godziny>”. **Rutyna jest domyślna**: zmiany rutyn w trakcie gry (`B_StartOtherRoutine`) nie są
śledzone. Etapy użycia przedmiotu, wyzwalane skryptem i dialogi gracza (`PC_HERO`) nie mają `place`.

## `locations.json` — lokacje i przejścia między światami

Trzeci rodzaj wpisu obok przedmiotów i postaci: **nazwane miejsca** (obozy, miasta, budynki, jaskinie, regiony,
punkty orientacyjne) i **przejścia między światami**. Zwarty JSON (UTF-8, bez BOM), w każdej paczce v5; lokacje są
posortowane po `kind` (kolejność poniżej), potem po `id`.

```json
{"version":1,"game":"g2nk","world":"NEWWORLD","locations":[
 {"id":"location:KHORINIS","kind":"town","name":"Khorinis","name_source":"derived","code":"KHORINIS",
  "center":[lon,lat,h],"radius_m":150.3,"polygon":null,"waypoint":"NW_CITY_MAINSTREET_01"},
 {"id":"location:passage:NW_2_ADDON_CHANGELEVEL","kind":"passage","name":"Przejście do: Jarkendar",
  "name_source":"derived","code":"NW_2_ADDON_CHANGELEVEL","center":[lon,lat,h],"radius_m":3.2,"polygon":null,
  "waypoint":"NW_TROLLAREA_PORTAL_10",
  "passage":{"to_world":"g2nk/jarkendar","to_level":"ADDON\ADDONWORLD.ZEN","arrival":[lon,lat,h]}}]}
```

| Pole | Znaczenie |
|---|---|
| `id` | `location:<KOD>`; kilka rozłącznych miejsc o jednym kodzie: `-1`, `-2`… (od zachodu); przejścia: `location:passage:<nazwa wyzwalacza>`. Stabilny, unikatowy w świecie |
| `kind` | `camp`, `town`, `district`, `building`, `cave`, `region`, `landmark`, `passage` (w tej kolejności sortowania). **Rodzaj to nasza ocena**, nie dana z gry |
| `name` | nazwa po polsku |
| `name_source` | `game` = tekst z gry; `derived` = nasza nazwa z mapowania `location_names.toml` (do zatwierdzenia); `code` = tylko kod z gry (`name` = `code`) |
| `code` | kod z gry: nazwa strefy bez numeru i przyrostka (`OLDCAMP_OC` → `OLDCAMP`), nazwa wyzwalacza przejścia, nazwa encji G3; `null` dla przejścia bez nazwy |
| `center` | `[lon, lat, h]` WGS84 (jak reszta paczki; `h` w metrach nad elipsoidą) |
| `radius_m` | przybliżony zasięg: promień okręgu opisanego na prostokącie strefy (albo na sumie prostokątów); `null` dla punktu |
| `polygon` | obrys `[[lon, lat], …]` (zamknięty pierścień) — tylko gdy gra go daje: prostokąt pojedynczej strefy G1/G2 albo wielokąt areny G3; suma kilku stref nie ma uczciwego obrysu, więc `null` |
| `waypoint` | nazwa najbliższego węzła `waypoints.json` w promieniu 150 m, inaczej `null` |
| `passage` | tylko `kind = passage`: `to_world` = `<gra>/<slug>` katalogu docelowego świata w paczkach albo `null` (świat poza paczką); `to_level` = surowa wartość `levelName` z gry; `arrival` = `[lon, lat, h]` obiektu `startVobName` w świecie docelowym albo `null` (świat poza paczką, pusta nazwa albo gra nie ma w nim takiego obiektu) |

Źródła (G1, G2 NK, Archolos — ZEN świata):

- **Przejścia**: każdy `oCTriggerChangeLevel` to jedna lokacja, `name` = „Przejście do: <nazwa świata docelowego>” (nazwa
  z `games.toml`; świat spoza paczki: nazwa pliku, np. „Przejście do: ORCCITY”). `name_source` przejścia to zawsze
  `derived` (gra nie ma tekstu przejścia). Pozycja i `radius_m` z pola wyzwalacza.
- **Miejsca**: strefy muzyczne `oCZoneMusic` (jedyne strefy z nazwą i zasięgiem). Strefy jednej nazwy bazowej, które się
  stykają (margines 5 m), to jedno miejsce (obóz ma kilka stref), odległe — osobne miejsca. Prefiksy waypointów, punkty
  `FP_*` i punkty startowe nie są lokacjami (waypoint służy tylko do pola `waypoint`).

Gothic 3 (`gothic_extract.g3.locations`): osady z encji `gCEnclave_PS` (nazwa z tekstów gry `GO_Enclave_*` i
`MAP_World_*` → `game`; reszta z mapowania → `derived`) oraz areny (`gCNavZone_PS` + `gCArena_PS`, z wielokątem, nazwa
`derived`). G3 ma jeden świat, więc nie ma przejść. Strefy pogody `eCWeatherZone_PS` (Cave, Dungeon…) to oświetlenie, nie
miejsca.

`gothic_extract.validate` sprawdza: unikatowe `id`, kolejność, `kind` i `name_source`, skończone współrzędne, `waypoint`
istnieje w `waypoints.json`, `passage` tylko przy `kind = passage`, `to_world` istnieje wśród paczek, `counts.locations`.

## Rozmiar

Khorinis: warstwy i indeks ~2 MB, `world.glb` ~150 MB, `models/` ~60 MB. Światy G1 są mniejsze (Kolonia: `world.glb` ~40 MB, `vobs.glb` ~15 MB, `models/` ~31 MB; pozostałe cztery światy po kilka MB na plik `.glb`). Modele dobrze jest serwować z CDN albo Cesium ion (który sam tnie `.glb` na 3D Tiles).

## Światy w paczkach

| Katalog | `world` | Uwagi |
|---|---|---|
| `dist/g2nk/khorinis` | `NEWWORLD` | Khorinis; `chapter = null` = start gry |
| `dist/g2nk/gornicza-dolina` | `OLDWORLD` | Górnicza Dolina; `chapter` zawsze wypełnione (najwcześniej 2). Wstawienia startowe, z dialogów i zdarzeń mają rozdział 2 (pierwsze wejście do Doliny) — to dolna granica, nie dokładny moment. Łuki i kusze nie mają modelu podglądu (`model: null`), jak w Khorinis. |
| `dist/g2nk/jarkendar` | `ADDONWORLD` | Jarkendar (Noc Kruka); `chapter` zawsze wypełnione (3 albo 4). Wstawienia startowe, z dialogów i zdarzeń mają rozdział 3 (`first_chapter` — pierwsze wejście do Jarkendaru) — to dolna granica, nie dokładny moment. Pominięto deweloperskie listy `USEJOLY*` (przedmioty, których gra nigdy nie wydaje; zdublowałyby potwory z rozdziału 4). Łuki i kusze nie mają modelu podglądu (`model: null`); skrzynie nie mają modelu (MDS nie jest eksportowany), jak w pozostałych światach. |

| `dist/g1/kolonia` | `WORLD` | Kolonia Karna (nazwa robocza). Główny świat G1 z obozami (Stary, Nowy, Bractwa), Wieżą Demonów i powierzchnią. `chapter = 2` dla potworów z respawnu rozdziału 2, reszta `null` (start gry, dialogi, zdarzenia). |
| `dist/g1/wolna-kopalnia` | `FREEMINE` | Wolna Kopalnia (nazwa robocza); `chapter = null` (patrz „Różnice Gothic 1”). |
| `dist/g1/stara-kopalnia` | `OLDMINE` | Stara Kopalnia (nazwa robocza); `chapter = null`. |
| `dist/g1/cmentarzysko-orkow` | `ORCGRAVEYARD` | Cmentarzysko orków (nazwa z dziennika gry, temat `CH3_ORCGRAVEYARD`); `chapter = null`. |
| `dist/g1/swiatynia-orkow` | `ORCTEMPEL` | Świątynia orków (nazwa robocza); `chapter = null`. |
| `dist/g3/myrtana` | `G3_WORLD_01` | Cały kontynent Gothic 3: Myrtana, Nordmar i Varant w jednym świecie (nazwa robocza „Myrtana”). Teren, budynki i obiekty, bez drzew i obiektów animowanych (patrz „Różnice Gothic 3”). |

Układ plików, osie i kotwica są takie same we wszystkich paczkach; światy ogląda się osobno.

## Różnice Gothic 1 względem Gothic 2

- `metadata.json → game` = `g1`; poza tą listą kontrakt jest ten sam co w g2nk.
- **Gildie**: kody G1 to m.in. `GRD`, `STT`, `ORG`, `SLD`, `TPL`, `GUR`, `KDF`, `KDW`, `NOV`, `BAU`, `SFB`, `DMB`, `VLK`, `BAB`; potwory i orkowie też mają „gildie” (`SCAVENGER`, `ORCWARRIOR`…). Polskie nazwy bierz z `guild_names`, nie z kodu. Wartość 1 to w G1 jednocześnie `GIL_EBR` (Magnat) i `GIL_HUMAN`; `guild_name` ma kod `HUMAN`, a `guild_names.HUMAN` = „Magnat”. Gildia `NONE` ma w grze tekst „(brak)”.
- **Rozdziały**: G1 nie ma funkcji nazwanych rozdziałem ani `B_ENDCHAPTER`; zmiana rozdziału to bloki `if (neues_Kapitel == n)` w `B_KAPITELWECHSEL`. `chapter` wstawienia NPC wypełnia się tylko dla funkcji wołanych wyłącznie z takiego bloku (dziś: respawn potworów, rozdział 2). Pozostałe wstawienia (start świata, dialogi, zdarzenia) mają `null`. W Wolnej Kopalni, Starej Kopalni, na cmentarzysku i w świątyni `null` znaczy „nie ustalono”, bo skrypty nie wiążą pierwszego wejścia do nich z rozdziałem (w Kolonii `null` to start gry). Zadania G1 mają `chapter` głównie `null`.
- **Światy**: pięć plików ZEN; jedna instancja NPC może być w kilku z nich (np. `TPL_1400_GORNABAR` w Kolonii i Starej Kopalni) i trafia do indeksu każdego świata, w którym jej imię jest tam unikatowe. Nazwy światów (poza cmentarzyskiem) są robocze.
- **Skrypty**: punkty startowe to `STARTUP_<ZEN>`; obozy Kolonii to podfunkcje `STARTUP_SUB_*` wołane z `STARTUP_WORLD`. Zadania nie mają zmiennych `MIS_*`, tylko jawne statusy (`LOG_RUNNING`, `LOG_SUCCESS`).
- **Siatka świata**: ZenKit ustawia w G1 flagę LOD na prawie każdym wielokącie, więc nie służy ona do odrzucania geometrii (w g2nk wielokąty LOD są pomijane). Kilka materiałów nie ma tekstury i ma kolor materiału.
- **Animacje**: prędkości ruchu liczone z tych samych animacji HUMANS co w G2 (`HUMANS-S_WALKL`, `RUNL`, `SNEAKL`, `HUMANS_1HST1-S_1HWALKL`).

## Różnice Gothic 3 względem Gothic 1 i 2

- `metadata.json → game` = `g3`, `engine` = `genome`, `world` = `G3_WORLD_01`. Gothic 3 ma jeden ciągły świat,
  więc jest jedna paczka (`dist/g3/myrtana`). Nazwa „Myrtana” jest robocza.
- **Kody** przedmiotów i postaci mają oryginalną wielkość liter z gry (`It_Plant_Perm_01`, `Inog`), nie same wielkie
  litery jak w G1/G2. Polska nazwa pochodzi z tekstu gry `FO_<kod>`.
- **Sieć dróg**: G3 nie ma waynetu (0 punktów w świecie), więc `waypoints.json` jest zbudowany z encji nawigacyjnych
  sektorów `*NavZones_01` regionu Myrtana (`gCNavZone_PS` = wielokąt strefy, `gCNavPath_PS` = łamana drogi między dwiema
  strefami). Format ten sam co w G1/G2, ale to **przybliżenie, nie sieć z gry**:
  - węzły `NAVPATH_<n>_<i>` = punkt `i` ścieżki `n`, krawędzie = kolejne punkty łamanej;
  - węzły `NAVZONE_<n>_<A|B>` = miejsce, w którym ścieżka `n` styka się ze strefą A lub B; połączone z najbliższym
    punktem ścieżki, a w obrębie jednej strefy wszystkie takie węzły są połączone prostymi odcinkami (odcinek może
    wyjść poza obrys strefy);
  - ścieżki bez rozpoznanej strefy (identyfikator strefy spoza wczytanych plików) są pominięte;
  - nazwy węzłów nie występują w innych warstwach (brak powiązania z `waypoint`/`insert_waypoint`), `under_water`
    zawsze `0`; sieć nie jest spójna (liczba składowych w raporcie `validate`).
- **Rozdziały**: G3 ich nie ma, `chapter` jest zawsze `null`.
- **Gildie**: G3 nie ma gildii. `guild_name` to stronnictwo postaci (`gEPoliticalAlignment`): `ORC` (Orkowie),
  `NRD` (Barbarzyńcy), `REB` (Buntownicy), `MID` (Druid), `ASS` (Asasyn), `NOM` (Koczownicy) — polskie nazwy z ekranu
  reputacji gry w `guild_names` — oraz `OUT`, `SLAVE` i `NONE` bez tekstu w grze (`null`). Zwierzęta i potwory mają `NONE`.
- **Przedmioty** (`items.geojson`): `source: "zen"` = leżą w świecie od początku gry (w G3 w większości rośliny),
  `spot` = `null`. `source: "script"` = przedmiot ze **sceny fabularnej**: sektora świata, który gra włącza dopiero
  w trakcie zadań (np. pobłogosławione kielichy w klasztorze, kolejne stany kopalni w Geldern); `spot` = nazwa
  tego sektora, a etykieta w wyszukiwarce to „wstawiany skryptem (<sektor>)”.
- **Sceny fabularne**: postacie z takich sektorów (biały cieniostwór, orkowie Kalana, demon i szkielety z kronik
  klasztoru…) mają `insert_function` = `"sektor fabularny"`, a `insert_waypoint` = nazwa sektora. Kolejne stany
  jednego miejsca (np. kopalnia w Geldern przed i po wyzwoleniu) są w paczce razem.
- **Skrzynie**: `pick_string` jest zawsze `null` (G3 nie ma kombinacji zamków; zamek ma trudność, klucz w `key`).
  `contents` to tylko stałe przedmioty (w G3 rzadkie). **Większość zawartości skrzyń i postaci G3 jest losowana**
  z zestawów łupu — patrz „Losowy łup (tylko G3)” niżej.
- **NPC**: `insert_waypoint` to nazwa sektora świata, w którym postać stoi; `insert_function` jest puste. `inventory`
  to stały ekwipunek (w G3 rzadki; resztę dają zestawy łupu). `level` to wartość z danych postaci.
- **Rutyny**: G3 zapisuje tylko punkty pracy, odpoczynku i snu (`action`: `WORK`/`RELAX`/`SLEEP`). Godziny są w kodzie
  gry, więc w `times` są **robocze** (praca 08:00–18:00, odpoczynek 18:00–22:00, sen 22:00–08:00, `games.toml`).
  `waypoint` to nazwa obiektu punktu w świecie.
- **Zadania** (`quests.json`): wszystkie 641 zadań gry (jeden świat, więc każde jest w tej paczce, `worlds` =
  `["G3_WORLD_01"]`). `name` = tytuł z dziennika, `section` = `mission`, `chapter` = `null`. Zleceniodawca to postać,
  której dialog rozpoczyna zadanie; gdy takich dialogów jest kilka u różnych postaci — `giver_candidates`.
  `stages` to dialogi zadania (`kind: "entry"`, `text` = pierwsza kwestia dialogu, `sources` = dialog i postać),
  w kolejności `SortID` z danych gry (to kolejność pisania; zależności tylko z `Parent`/`CondPlayerKnows`, patrz „Kolejność i miejsce etapów”), bez statusów. `characters`: `giver`/`giver_candidate`, `stage`
  (inne postacie z dialogami zadania) i **`target`** (cel zadania: kogo zabić, pokonać, przyprowadzić, komu
  zanieść). `items`: `handover` (co oddać) i `reward` (co dostaje gracz). `rewards.xp` = doświadczenie za zadanie.
- **Teren** (`world.glb`): cały kontynent (komórki terenu Myrtany, Nordmaru i Varantu, ~2,4 mln trójkątów, ~150 MB),
  w tych samych osiach i jednostkach co w G1/G2. Teren w grze miesza kilka tekstur na materiał; w glTF każdy z 89
  materiałów ma swoją teksturę podstawową, zmniejszoną do 512 px.
- **Budynki i obiekty** (`vobs.glb`, `models/*.glb`): 3237 modeli, ~123 800 wystąpień (budynki, mury, skały,
  meble, skrzynie, drzwi, przedmioty leżące w świecie), tekstury zmniejszone do 256 px. `vobs.glb` ma ~360 MB,
  `models/` ~340 MB (G3 ma wielokrotnie więcej obiektów niż Khorinis). W `vobs.glb` położenie węzła jest macierzą
  (`matrix`), w `models/*.glb` instancje mają oprócz `TRANSLATION` i `ROTATION` także **`SCALE`** (obiekty G3 bywają
  skalowane i odbite lustrzanie — odbicie to ujemna skala). Obiekty z animowaną siatką (skrzynie, drzwi, łuki,
  kusze, żarna) są w **pozie spoczynkowej** (skrzynia zamknięta). **Nie ma** drzew SpeedTree (~57 400, osobny format
  `.spt`) — `models/index.json` liczy je w `unhandled.speedtree`; modele, których nie ma w plikach gry, są w
  `missing` i `missing_instances`.
- **Podglądy** (`models/previews/`): 220 plików — modele przedmiotów (także łuków, kusz, zwojów i pochodni) oraz
  skrzyń. `model` mają 1062 z 1072 skrzyń i 301 z 533 przedmiotów w wyszukiwarce. Bez podglądu: przedmioty bez modelu
  w grze (czary, umiejętności…) i 24 przedmioty, których modelu brakuje w plikach gry (np. część tarcz wieżowych).
- **Prędkości ruchu** (`movement_speeds_m_s`): z parametrów ruchu bohatera (`PC_Hero`, `gCCharacterMovement_PS`),
  nie z animacji jak w G1/G2: bieg = `ForwardSpeedMax` (4,0 m/s), chód = bieg × `SlowModifier` (1,5 m/s),
  skradanie = chód × `SneakModifier` (1,05 m/s), `walk_armed` = chód. `movement_speeds_animations` jest puste,
  źródło jest w `movement_speeds_parameters`.

### Losowy łup (tylko G3)

Gra losuje zawartość skrzyń, ekwipunek postaci, trofea potworów i towar handlarzy z **zestawów łupu**.
Wszystkie pola poniżej są opcjonalne (w G1/G2 ich nie ma).

- **`treasure_sets.json`** (`{version, sets: {kod: {...}}}`) — zestawy użyte w świecie: `kind` (`chest` — skrzynia,
  `npc` — postać, `monster` — potwór, `trader` — handlarz, `mining` — wydobycie), `min_stacks`/`max_stacks` (ile
  pozycji gra losuje z listy; `0`/`0` w zestawach unikatowych skrzyń: jeden przedmiot, który wypada w grze raz),
  `distribution` (surowa wartość z gry), `holders` (ile skrzyń i postaci ma ten zestaw) i `items`
  (`{code, name, category, amount}` — wszystkie możliwe pozycje).
- **`treasure_sets`** — lista kodów zestawów w `containers.geojson`, `npcs.geojson` i `characters.geojson`
  (karta skrzyni lub postaci: „może zawierać…” = pozycje tych zestawów z `treasure_sets.json`).
- **`loot`** we wpisie przedmiotu w `search_index.json` — z jakich zestawów przedmiot może wypaść:
  `[{set, kind, holders}]`. Przedmiot, który jest **tylko** w łupie, też ma wpis (`total: 0`, `places` mogą być puste).
- **Miejsca `possible`** — dla zestawów, które ma **co najwyżej 50** skrzyń lub postaci (skrzynie unikatowe,
  handlarze, rzadkie potwory), każda taka skrzynia/postać jest miejscem w `places` z `certainty: "possible"`,
  `set` (kod zestawu) i `kind` `container` albo `npc` (`ref` jak zwykle). Zestawy powszechne (np. złoto w setkach
  skrzyń) są tylko w `loot`, żeby nie zalewać mapy; aplikacja może na żądanie pokazać ich skrzynie, filtrując
  `containers.geojson`/`npcs.geojson` po `treasure_sets`.
- `total` nadal liczy tylko sztuki pewne, więc łup go nie zmienia.

## Ortofotomapa (GeoTIFF dla Cesium ion)

Widok z góry świata jako georeferencjonowany GeoTIFF (EPSG:4326, RGBA, kafelki 512×512, Deflate). Renderowany z
`world.glb` (opcjonalnie `vobs.glb`) tej samej paczki, więc działa dla G1, G2 i G3 bez instalacji gier.

```
python -m gothic_extract.ortho --pkg dist/g2nk/khorinis --gsd 0.25
python -m gothic_extract.ortho --pkg dist/g2nk/khorinis --gsd 0.10 --bbox -20 -70 120 90   # wycinek, ENU w metrach od kotwicy
```

- `--gsd` w metrach na piksel (domyślnie 0,25). `--bbox E0 N0 E1 N1` w metrach od kotwicy (X/100, Z/100 gry);
  bez niego renderuje cały świat i odmawia, gdy obraz przekracza 2·10⁹ px. `--include-vobs` rysuje też drzewa i drobne obiekty.
- Wynik: `<paczka>/ortho/<slug>_<gsd>cm.tif` i obok `*.json` (CRS, bbox, rozmiar, gęstość tekstur, ostrzeżenia).
  Poza obrysem świata alfa = 0.
- Do ion: wgraj plik `.tif` jako imagery (GeoTIFF); ion sam go kafelkuje dla 3D i 2D.
- Rzut prostopadły, najwyższa powierzchnia wygrywa; kolor z tekstury (bez oświetlenia i bez mieszania warstw terenu G3).
  Przy grubych pikselach używa mipmap tekstur, więc nie ma szumu.
- Gęstość tekstur jest raportowana (`texel_cm_*`); gdy `--gsd` jest drobniejsze niż połowa mediany, program ostrzega,
  że obraz będzie tylko powiększony. Tekstury terenu G3 w `world.glb` mają 512 px, więc Myrtana poniżej ok. 25 cm/px jest rozmyta.
- Georeferencja używa tego samego wzoru co GeoJSON (`enu_to_lonlat`), więc obraz leży na punktach warstw. Model 3D w Cesium
  stoi na prawdziwej płaszczyźnie stycznej, więc na kilku km możliwe jest przesunięcie rzędu krzywizny Ziemi.
