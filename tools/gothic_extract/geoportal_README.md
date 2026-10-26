# Dane geoportalu — paczka v4

Dane jednego świata gry dla geoportalu: **wyszukać przedmiot, unikatową postać albo zadanie (quest)
i pokazać, gdzie są**. Paczki wszystkich światów gry buduje jedno polecenie (z `PYTHONPATH=tools`
w repozytorium ekstraktora):

```
python -m gothic_extract.package --game g1              # z istniejącej ekstrakcji output/g1/<zen>
python -m gothic_extract.package --game g2nk --extract  # najpierw pełna ekstrakcja każdego świata
python -m gothic_extract.package --game g3 --extract    # Gothic 3 (osobny czytnik silnika Genome)
python -m gothic_extract.validate                       # sama walidacja paczek wszystkich gier w dist/
```

`package` robi dla każdego świata: warstwy i indeks (`gothic_extract.geoportal`), questy
(`gothic_extract.quests_package`, wersja paczki 4) i prędkości ruchu (`gothic_extract.movement_speeds`),
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
| `package.version` | 4 |
| `package.counts` | `search_items`, `search_items_with_model`, `search_characters`, `items`, `containers`, `npcs`, `character_places`, `quests`; zgadzają się z zawartością plików (sprawdza `gothic_extract.validate`) |
| `package.files` | pliki i katalogi paczki (katalog z `/` na końcu) |
| `guild_names` | kod gildii → polska nazwa **z gry** (tablica `TXT_GUILDS` skryptów), dla gildii występujących w tym świecie; `null`, gdy gra nie ma tekstu. Kody to wartości `guild_name` w `npcs.geojson` i `characters.geojson`. |
| `movement_speeds_m_s` | prędkości gracza w m/s: `walk`, `run`, `sneak`, `walk_armed`, liczone z pętli animacji szkieletu HUMANS |
| `movement_speeds_animations` | nazwy animacji `.MAN`, z których policzono prędkości |
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
| `order` | `"script"`: etapy w kolejności występowania w skryptach, nie w kolejności gry |
| `stages` | etapy: `kind` (`create`/`entry`/`status`/`close`), `text`, `status`, `function`, `sources` (dialog / użycie przedmiotu), `conditional` |
| `characters`, `items` | postacie i przedmioty zadania z `role` (w G3 także `target`) i `certainty`; `in_index: true` ⇒ `id` wskazuje wpis w `search_index.json`, inaczej `id: null` |
| `rewards` | `xp` i `xp_certainty` |
| `worlds` | wszystkie światy gry (nazwy ZEN), w których zadanie ma udział; zadanie wielo-światowe jest w paczce **każdego** z nich pod tym samym `id`, a `places` zawiera tylko miejsca z danego świata |
| `places` | miejsca na mapie: jak w indeksie (`kind`, `lon`, `lat`, `h`, `ref`…) plus `role` (`giver`/`target`/`stage`), `npc_code`, `certainty` |

Zadanie, w którym żaden świat nie ma udziału, nie trafia do żadnej paczki.

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
| `dist/g3/myrtana` | `G3_WORLD_01` | Cały kontynent Gothic 3: Myrtana, Nordmar i Varant w jednym świecie (nazwa robocza „Myrtana”). Teren jest, budynków i modeli obiektów jeszcze nie ma (patrz „Różnice Gothic 3”). |

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
  w kolejności z danych gry (`order: "script"`), bez statusów. `characters`: `giver`/`giver_candidate`, `stage`
  (inne postacie z dialogami zadania) i **`target`** (cel zadania: kogo zabić, pokonać, przyprowadzić, komu
  zanieść). `items`: `handover` (co oddać) i `reward` (co dostaje gracz). `rewards.xp` = doświadczenie za zadanie.
- **Teren** (`world.glb`): cały kontynent (komórki terenu Myrtany, Nordmaru i Varantu, ~2,4 mln trójkątów, ~150 MB),
  w tych samych osiach i jednostkach co w G1/G2. Teren w grze miesza kilka tekstur na materiał; w glTF każdy z 89
  materiałów ma swoją teksturę podstawową, zmniejszoną do 512 px. Budynki i obiekty jeszcze nie są w modelu.
- **Brakuje jeszcze**: `vobs.glb` i `models/` (budynki, obiekty, modele przedmiotów) oraz prędkości ruchu
  (`movement_speeds_m_s = null`). Przyjdą w kolejnych etapach.

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
