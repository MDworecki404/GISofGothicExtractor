# Ekstraktor Gothic 3 → paczka geoportalu v4

Data: 2026-10-26
Status: projekt do akceptacji

## 1. Po co to jest

Geoportal ma już paczki G1 (5 światów) i G2NK (4 światy) w kontrakcie v4 (`tools/gothic_extract/geoportal_README.md`).
Teraz dochodzi **Gothic 3** (z Community Patchem, polska wersja, folder `Gothic 3/`). Cel jest ten sam:
wyszukać przedmiot, unikatową postać albo zadanie i pokazać, gdzie są. **Paczka G3 ma mieć dokładnie ten sam
układ plików i współrzędnych**, żeby aplikacja (`C:\Moje_Apki\GisOfGothic`) wczytała ją jak kolejny świat.

G3 działa na innym silniku (Genome zamiast ZenGin), więc ZenKit i skrypty Daedalusa odpadają. Potrzebny jest
własny czytnik formatów Genome w Pythonie.

## 2. Decyzje (uzgodnione 2026-10-26)

- **Ten sam kontrakt v4**: `metadata.json`, `search_index.json`, `quests.json`, warstwy GeoJSON
  (`items`, `containers`, `npcs`, `characters`, `character_places`), `world.glb`, `vobs.glb`, `models/`.
  Te same osie i kotwica (lon/lat 0,0; E=+X, N=+Z, U=+Y; cm → m).
- **Brak rozdziałów**: `chapter` / `first_chapter` zawsze `null`.
- **Cały świat jako jedna paczka**: `G3_World_01` (Myrtana + Nordmar + Varant) → `dist/g3/myrtana`
  (nazwa robocza „Myrtana”, `provisional_name = true`). Podział na regiony ewentualnie później.
- **Dane specyficzne dla G3** (frakcje/enklawy, losowy łup ze skrzyń i potworów, trudność zamków, handlarze)
  wchodzą jako **pola opcjonalne**; dotychczasowe pola nie zmieniają znaczenia. Opis w README w sekcji
  „Różnice Gothic 3”, jak „Różnice Gothic 1”.
- Gra tylko do odczytu, nic nie zapisujemy w `Gothic 3/`.

## 3. Co jest w plikach gry (rozpoznane)

| Dane | Plik | Format |
|---|---|---|
| Archiwa | `Data/*.pak` + łatki `*.p00`, `*.p01` (późniejsza wygrywa) | `G3V0`: nagłówek 48 B, drzewo katalogów na końcu, pliki surowe albo zlib |
| Lista aktywnych sektorów świata | `Projects_compiled` → `G3_World_01/G3_World_01.wrldatasc` | tekst INI, `[Sector.List]`, `<sektor>=true/false` |
| Encje świata (przedmioty, skrzynie, NPC, zamki, drzwi, mapy, listy) | `Projects_compiled` → `G3_World_01/**/<sektor>.lrentdat` (+ jeden `SysDyn_{…}.lrentdat`, 81 MB) | `GENOMFLE`: drzewo encji, każda z macierzą świata i zestawami właściwości (`gCItem_PS`, `gCInventory_PS`, `gCLock_PS`, `gCNPC_PS`, `gCNavigation_PS`, `gCInteraction_PS`, `gCEnclave_PS`…) |
| Szablony (definicje przedmiotów, NPC, łupu) | `Templates` → `*.tple`, indeks GUID → plik w `*.lrtpldatasc` (tekst) | `GENOMFLE` z tymi samymi zestawami właściwości |
| Polskie teksty | `Strings` → `stringtable.ini` | UTF-16, poprawny Unicode; klucze `FO_<kod>` (nazwy przedmiotów i postaci), `ITEMDESC_*`, `QUEST_*`, `INFO_*` |
| Zadania (637) | `Quests` → `*.quest` | tekst INI (zleceniodawca, przedmioty do dostarczenia, cel, XP) |
| Dialogi (4260) | `Infos` → `*.info` | tekst INI (`InfoScript_Commands` z `Give`/`Take` przedmiotów) |
| Teren | `_compiledMesh` → `G3_<Region>_Landscape_01/LOD/*.xcmsh` (~300 MB), `G3_World_Lowpoly_Landscape_01` | `GENOMFLE` (siatka skompilowana) |
| Modele obiektów | `_compiledMesh` → `*.xcmsh` | jw. |
| Tekstury | `_compiledImage` → `*.ximg` | `GENOMFLE` + DDS (DXT1/3/5) |

Format obiektu właściwości (potwierdzony na `.lrentdat` i `.tple`): `u16 1, u8 1, u16 1, u8 1, u16 klasa (indeks
w tablicy napisów), u16 1, u8 0, u16 wersja klasy, u16 wersja klasy, u32 rozmiar, u16 30, u32 liczba właściwości`,
potem dla każdej właściwości `u16 nazwa, u16 typ, u16 30, u32 rozmiar, dane`, a po niej dane własne klasy.
Tablica napisów na końcu pliku: znacznik `DEADBEEF`, `u8 1`, `u32 n`, n × (`u16 długość`, znaki).
Układ drzewa encji (`eCEntity`/`eCSpatialEntity`/`eCDynamicEntity` w `.lrentdat`) **trzeba jeszcze rozpracować**.
To największe ryzyko etapu 1.

Nie znaleziono otwartej biblioteki do tych formatów (odpowiednika ZenKit), więc czytnik piszemy sami.

## 4. Mapowanie na kontrakt v4

| Kontrakt | Źródło G3 |
|---|---|
| `items` (`source: "zen"` = leży w świecie) | encje z `gCItem_PS` poza ekwipunkami; kod = nazwa szablonu (np. `It_Plant_Perm_01`), ilość = `Amount` |
| `containers` | encje z `gCInventory_PS` i bez `gCNPC_PS` (skrzynie, worki); `locked`/`key` z `gCLock_PS`; `pick_string` = `null` (G3 nie ma kombinacji zamków) |
| `npcs`, `characters` | encje z `gCNPC_PS`; imię z `FO_<nazwa encji>`; ekwipunek z `gCInventory_PS` (`certainty: "always"`); `insert_waypoint` = nazwa sektora |
| `character_places` | punkty pracy/odpoczynku/snu z `gCNavigation_PS`; godziny z tabeli w `games.toml` (do sprawdzenia w grze) |
| katalog przedmiotów | szablony z `gCItem_PS`: nazwa `FO_<kod>`, kategoria z `gEItemCategory`, wartość `GoldValue`, model `.xcmsh` |
| `guild_names` | wartości `gEGuild` z `gCNPC_PS` → polskie nazwy |
| `quests.json` | `.quest` + `.info` (etap 2) |
| `world.glb` | teren `.xcmsh` (etap 3) |
| `vobs.glb`, `models/` | modele obiektów i przedmiotów (etap 4) |
| `movement_speeds_m_s` | etap 1: `null`; animacje `_compiledAnimation` w etapie 6 |

## 5. Etapy (każdy to osobny plan, każdy kończy się działającą, zwalidowaną paczką)

1. **Dane**: archiwa, czytnik `GENOMFLE`, szablony, polskie nazwy, drzewo encji, przedmioty, skrzynie, NPC,
   paczka `dist/g3/myrtana` bez modeli i z pustym `quests.json`. Plan:
   `docs/superpowers/plans/2026-10-26-g3-etap1-dane.md`.
2. **Zadania**: `.quest` + `.info` → `quests.json` w kontrakcie (etapy z `QUEST_*`, zleceniodawca, przedmioty,
   miejsca, XP).
3. **Teren**: `.xcmsh` + `.ximg` → `world.glb`. Najpierw uproszczona siatka całego świata, potem pełna rozdzielczość.
   Tu wyjdzie, czy jeden plik nie jest za duży (wtedy opcjonalny wariant kafelkowy w kontrakcie).
4. **Modele**: `vobs.glb`, `models/*.glb`, podglądy przedmiotów `models/previews/`.
5. **Dane specyficzne G3**: losowy łup (`Treasure/*`) jako `certainty: "possible"`, handlarze, enklawy/frakcje,
   trudność zamków. Wszystko jako pola opcjonalne + README.
6. **Prędkości ruchu** z animacji gracza.

## 6. Ryzyka i otwarte pytania

- **Drzewo encji `.lrentdat`** — format niezbadany. Etap 1 zaczyna się od rozpoznania z testami, które
  wymagają, żeby każdy plik został przeczytany do ostatniego bajtu.
- **Sektory testowe** (`BjoernTest_01`, `Hoshi_*_Test`, `Story_Test_Final`…) — część jest `=true`
  w `wrldatasc`. Pomijamy sektory, których nazwa pasuje do listy wykluczeń w `games.toml`.
- **Godziny rutyn NPC** — G3 trzyma tylko punkty (praca, odpoczynek, sen), godziny są w kodzie gry.
  Tabela w `games.toml` jest robocza, do potwierdzenia przez użytkownika.
- **Postacie „unikatowe”** — G3 nie ma flag gildii jak Daedalus; człowiek/potwór rozróżniamy po `gCNPC_PS.Species`.
- **Nazwa świata** „Myrtana” jest robocza.
