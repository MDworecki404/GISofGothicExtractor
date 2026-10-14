# Ekstraktor świata Gothic → dane dla geoportalu 3D (etap 1: Khorinis)

Data: 2026-10-14
Status: projekt do akceptacji

## 1. Po co to jest

Użytkownik chce zbudować **interaktywną mapę 3D (geoportal na CesiumJS, ewentualnie three.js)** światów Gothic 1 i Gothic 2 Noc Kruka, której głównym zastosowaniem jest **wyszukiwanie miejsc i przedmiotów** — np. wpisuję „Szczaw królewski” i widzę wszystkie miejsca, gdzie go zdobędę (leży na ziemi, jest w skrzyni, ma go NPC). Model 3D świata jest tłem i orientacją; najważniejsze są **kompletne i dokładne pozycje obiektów z polskimi nazwami**.

Ten dokument opisuje **etap 1: narzędzie ekstrakcji danych**, uruchomione na pierwszym świecie — **Khorinis (NEWWORLD.ZEN z Gothic 2 NK)**. Narzędzie ma być od początku napisane tak, by kolejne światy (Górnicza Dolina, Jarkendar, Irdorath, światy G1) dodawać przez parametr, a nie przepisywanie kodu.

Gry są legalnie zakupione przez użytkownika; dane są używane lokalnie.

## 2. Cele, nie-cele, anty-cele

**Cele (etap 1)**
- Siatka świata Khorinis z teksturami jako **glTF binarny (.glb)**, gotowy do konwersji na 3D Tiles lub wczytania do three.js.
- Wszystkie VOBy świata z pozycją, orientacją, typem i nazwą modelu.
- Wszystkie **przedmioty leżące w świecie** (z ZEN) z polską nazwą i kategorią.
- Wszystkie **skrzynie/pojemniki** z zawartością (przedmiot + ilość), stanem zamka (zamknięta / kombinacja zamka / wymagany klucz).
- Wszystkie **NPC wstawiani do Khorinis** przez skrypty: imię, gildia, poziom, ekwipunek (przedmioty + ilości), miejsce startowe oraz **wszystkie punkty z rutyn dnia** z przedziałami godzin.
- Przedmioty wstawiane skryptem przy starcie świata (`Wld_InsertItem`) — oznaczone jako takie.
- Sieć dróg (waypointy + krawędzie) i freepointy (spawny, miejsca).
- Każdy zbiór w **GeoJSON** (z umownymi lon/lat + oryginalnymi współrzędnymi gry we właściwościach) oraz krótki raport liczbowy.
- Uruchamialne jednym poleceniem, powtarzalne.

**Nie-cele (etap 1)**
- Sam geoportal (CesiumJS / three.js) — osobny etap.
- Generowanie 3D Tiles — osobny etap (wejściem będzie .glb z tego etapu).
- Ortofotomapy — osobny etap.
- Pozostałe światy — po zaakceptowaniu Khorinis.
- **Modele 3D VOBów** (mosty, wieże, skały, drzewa, meble, część budynków) — **decyzja użytkownika: etap 2**. W etapie 1 `world.glb` zawiera tylko statyczną siatkę świata; obiekty położone na VOBach (np. przedmiot na stole) mogą wizualnie „wisieć” nad modelem — to jest akceptowane w etapie 1. Pozycje VOBów i nazwy ich modeli są jednak eksportowane już teraz (`vobs.geojson`), żeby etap 2 tylko dołożył geometrię.
- Symulacja przebiegu fabuły (przedmioty dawane w dialogach, nagrody za questy, handlarze zmieniający asortyment w rozdziałach) — poza zakresem; ekwipunek NPC to stan z ich funkcji instancji.

**Anty-cele (porażka nawet jeśli „działa”)**
- Przedmiot jest w grze w danym miejscu, a na mapie go nie ma (pominięte źródło) — kompletność ważniejsza niż szybkość.
- Pozycje przesunięte / odbite lustrzanie względem modelu świata (punkt „wisi w powietrzu” lub ląduje po drugiej stronie rzeki).
- Nazwy z rozjechanym polskim kodowaniem („Szczaw kr�lewski”).
- Ręczne kroki, których nie da się powtórzyć dla następnego świata.

## 3. Stan obecny (rozpoznanie folderu)

`C:\Moje_Różne\GothicClaudiusz\`
- `Gothic II\` — Gothic 2 NK, wersja polska, bez modów zmieniających świat.
  - `Data\Worlds.vdf`, `Data\Worlds_Addon.vdf` (addon nadpisuje: `NEWWORLD\NEWWORLD.ZEN`, `ADDON\ADDONWORLD.ZEN`, `OLDWORLD\OLDWORLD.ZEN`, `NEWWORLD\DRAGONISLAND.ZEN`).
  - `Data\Textures*.vdf`, `Meshes*.vdf`, `Anims*.vdf`.
  - `_work\Data\Scripts\_compiled\GOTHIC.DAT` — skompilowane skrypty, polskie nazwy (potwierdzono „Szczaw królewski”, „Ziele lecznicze”).
- `Gothic\` — Gothic 1 PL (etap późniejszy): `worlds.VDF` (WORLD, FREEMINE, OLDMINE, ORCGRAVEYARD, ORCTEMPEL), `_work\DATA\scripts\_compiled\Gothic.dat`. Pluginy Union obecne, nie zmieniają światów.
- Środowisko: Windows 11, Python 3.13, **ZenKit (pakiet `zenkit` 1.3.0.4) już zainstalowany** — zawiera `Vfs`, `World`, `MultiResolutionMesh`, `Texture`, `DaedalusScript`, `DaedalusVm`, `NpcInstance`, `ItemInstance`, `WayNet`, `InteractiveObject` (kontenery).

## 4. Jak to działa (ustalone)

### 4.1 Źródła danych w grze
Przedmioty i postacie w Gothicu pochodzą z **dwóch źródeł** i oba muszą być przeczytane:
1. **ZEN (plik świata)**: siatka statyczna, VOBy, przedmioty położone w edytorze, skrzynie z zawartością (`oCMobContainer.contains` – string typu `ItMi_Gold:50,ItPl_Health_Herb_01`), zamki, waynet.
2. **Skrypty Daedalus (GOTHIC.DAT)**: definicje przedmiotów (instancja → polska nazwa, kategoria, wartość), definicje NPC (imię, gildia, poziom, ekwipunek przez `CreateInvItems` w funkcji instancji, rutyna `daily_routine`), funkcje startowe świata (`Startup_NewWorld` / `Init_NewWorld` i podfunkcje) wywołujące `Wld_InsertNpc(npc, "WAYPOINT")` i `Wld_InsertItem(item, "FP_...")`.

### 4.2 Pipeline (kroki)
1. **VFS** — zamontuj VDF-y G2NK z regułą „addon nadpisuje bazę” (tak jak silnik: nowsza data/`_Addon`).
2. **Świat** — wczytaj `NEWWORLD.ZEN`, wyciągnij:
   - siatkę statyczną (mesh świata) → materiały → tekstury (`.TEX` skompilowane, dekodowane przez ZenKit) → **.glb**;
   - drzewo VOBów (rekurencyjnie, z dziećmi) → lista VOBów;
   - waynet → waypointy + krawędzie;
   - freepointy (VOBy typu `zCVobSpot`).
3. **Skrypty** — wczytaj `GOTHIC.DAT` w `DaedalusVm`; zarejestruj externale potrzebne do uruchomienia funkcji startowych świata i instancji NPC jako **„nagrywające”** (np. `Wld_InsertNpc` zapisuje (npc, waypoint), `Wld_InsertItem` zapisuje (item, freepoint), `CreateInvItems`/`CreateInvItem` zapisuje ekwipunek bieżącego NPC, `TA_*`/`TA_Min` w rutynach zapisuje (godzina od, godzina do, akcja, waypoint)); pozostałe externale — bezpieczne atrapy zwracające wartości domyślne.
   - Uruchom funkcję startową Khorinis → lista wstawianych NPC i przedmiotów.
   - Dla każdego NPC: zainicjalizuj instancję (imię, gildia, poziom, ekwipunek), następnie wywołaj jego `daily_routine` → punkty rutyny.
   - Dla każdej instancji przedmiotu (`C_Item`) czytaj nazwę, `mainflag`/`flags` (kategoria), `value`, `visual`.
4. **Rozwiązanie pozycji** — waypoint/freepoint → współrzędne z waynetu/VOBów ZEN.
5. **Złączenie** — kod przedmiotu z ZEN/skrzyni/ekwipunku → polska nazwa i kategoria ze skryptów.
6. **Eksport** — GeoJSON + JSON + .glb + raport.

### 4.3 Układ współrzędnych (moja decyzja — do korekty)
- Gothic: jednostka = 1 cm, układ lewoskrętny, **Y w górę**.
- Konwersja do metrów: `x_m = x/100`, `y_m = y/100` itd.
- Mapowanie na lokalny ENU (East-North-Up): **East = +X_gry, North = +Z_gry, Up = +Y_gry** (zmiana ręczności przez zamianę osi Y/Z; zweryfikować na znanym punkcie — np. że port Khorinis jest po właściwej stronie miasta względem mapy z gry).
- Umowna kotwica na globusie: **lon 0°, lat 0°, wysokość 0 m** (punkt (0,0,0) świata gry). Lon/lat liczone z ENU (lokalna płaszczyzna styczna; przy rozmiarze świata ~kilka km błąd pomijalny). Kotwica jest parametrem w konfiguracji.
- Każdy obiekt w GeoJSON ma też `game_pos: [x,y,z]` w oryginalnych jednostkach i `height_m`, żeby można było przeliczyć inaczej bez ponownej ekstrakcji.
- .glb: zapisany w metrach, Y-up (konwencja glTF), z tym samym odbiciem osi, tak by punkty z GeoJSON i model się pokrywały. Kotwicę zapisujemy w `metadata.json` obok (do późniejszego `transform` w 3D Tiles).

## 5. Wyjście

Folder: `C:\Moje_Różne\GothicClaudiusz\output\g2nk\newworld\`

| Plik | Zawartość |
|---|---|
| `world.glb` | siatka świata z teksturami (metry, Y-up) |
| `textures/` | tylko jeśli glb ma referencje zewnętrzne (domyślnie tekstury osadzone w glb) |
| `items.geojson` | przedmioty: luzem w ZEN (`source: "zen"`) i wstawiane skryptem (`source: "script"`) |
| `containers.geojson` | skrzynie/pojemniki: pozycja, zamek, lista `contents: [{code, name, amount}]` |
| `npcs.geojson` | jeden Feature na NPC (punkt startowy) + `inventory`, `guild`, `level`, `routine: [{from, to, action, waypoint, pos}]` |
| `npc_routines.geojson` | jeden Feature na punkt rutyny (dla wygodnego wyświetlania na mapie) |
| `vobs.geojson` | wszystkie VOBy (typ klasy, nazwa, visual, pozycja, rotacja jako macierz/kwaternion) |
| `waypoints.geojson` | waypointy (Point) + krawędzie (LineString) |
| `freepoints.geojson` | freepointy (spawny, miejsca akcji) |
| `catalog_items.json` | słownik wszystkich instancji przedmiotów: kod → nazwa PL, kategoria, wartość, opis |
| `metadata.json` | wersja gry, świat, kotwica, konwencja osi, wersja narzędzia, data |
| `report.txt` | liczności, ostrzeżenia (nierozwiązane waypointy, nieznane kody przedmiotów, brakujące tekstury) |

Właściwości wspólne dla obiektów: `id`, `code` (np. `ItPl_Perm_Herb`), `name` (PL), `category`, `game_pos`, `height_m`, `source`.

Kodowanie: stringi ze skryptów i ZEN są w **Windows-1250** → wszystkie pliki wyjściowe **UTF-8**.

## 6. Narzędzie

- Folder: `C:\Moje_Różne\GothicClaudiusz\tools\gothic_extract\` (pakiet Python).
- Uruchomienie: `python -m gothic_extract --game g2nk --world NEWWORLD --out output\g2nk\newworld`.
- Konfiguracja gier (ścieżki VDF, plik skryptów, nazwa funkcji startowej świata, kotwica) w jednym pliku `games.toml`, żeby kolejne światy dodawać wpisem.
- Zależności: `zenkit`, `numpy`, `pygltflib` (lub ręczny zapis glTF), biblioteka do PNG/KTX (np. `Pillow`). Lista w `requirements.txt`.
- Testy: lekkie, na prawdziwych danych — np. „w Khorinis istnieje przynajmniej N roślin `ItPl_Perm_Herb`”, „waypoint `NW_CITY_HABOUR_...` leży w obrębie bboxa świata”, „nazwa ma polskie znaki poprawnie”, „każdy NPC z `Wld_InsertNpc` ma rozwiązaną pozycję”.

## 7. Zostawione wykonawcy (decyzje techniczne)
- Dokładny sposób odczytu siatki świata i podział na materiały/prymitywy w glb (jeden prymityw na materiał).
- Format tekstur w glb (PNG — prostsze; KTX2 — później dla 3D Tiles).
- Obsługa przezroczystości (alpha test dla liści/krzaków → `alphaMode: MASK`).
- Lista externali Daedalusa do zaimplementowania jako atrapy — wyznaczona empirycznie (VM zgłasza brakujące).
- Mapowanie `mainflag` → nazwy kategorii PL (Broń biała, Broń dystansowa, Pancerze, Rośliny, Mikstury, Zwoje, Runy, Jedzenie, Różne…).

## 8. Decyzje podjęte przeze mnie (do sprawdzenia przez użytkownika)
1. Kotwica na globusie: lon/lat 0,0 (umowna, zmienialna).
2. Mapowanie osi East=+X, North=+Z, Up=+Y (do weryfikacji na znanym miejscu).
3. NPC: punkt startowy z `Wld_InsertNpc` + wszystkie punkty rutyny z godzinami; brak symulacji fabuły/rozdziałów (tylko stan funkcji startowej świata dla rozdziału 1 — NPC wstawiani w późniejszych rozdziałach będą dodani, jeśli ich wstawianie jest w osobnych funkcjach, które da się zidentyfikować; oznaczone polem `chapter`).
4. GeoJSON + JSON jako formaty danych; .glb z osadzonymi teksturami PNG.
5. Wyniki w `output\`, kod w `tools\gothic_extract\`.
6. **Losowy/warunkowy ekwipunek NPC** (helpery typu `B_CreateAmbientInv` rozgałęziające się na `Hlp_Random`, rozdziale, gildii): zbieramy przedmioty ze **wszystkich gałęzi** (eksploracja rozgałęzień w bajtkodzie zamiast pojedynczego przebiegu VM). Każdy przedmiot ekwipunku ma pole `certainty`: `"always"` (bezwarunkowy) albo `"possible"` (zależny od losowania/warunku). Uzasadnienie: anty-cel „przedmiot jest w grze, a nie ma go na mapie”.
   **Zmiana (decyzja użytkownika, 2026-10-14):** przedmioty z losowych tablic łupu NPC z tłumu (`B_CreateAmbientInv_*`: jabłka, gorzałka, drobne złoto) są pomijane — nie są istotne dla aplikacji. W G2NK oznacza to, że żaden NPC nie ma już przedmiotów `possible`; reguła „maksimum z gałęzi” zostaje dla innych gier.
7. **Rutyny NPC**: nie tylko `daily_routine`, ale **wszystkie funkcje `Rtn_<Nazwa>_<id>`** danego NPC (wykryte konwencją nazw + powiązane przez `Npc_ExchangeRoutine` w skryptach, jeśli da się je powiązać). Każdy punkt w `npc_routines.geojson` ma pole `routine` (np. `"START"`, `"FOLLOW"`, `"FARM"`) i `is_default: true/false`.

## 9. Ryzyka
- **VM Daedalusa w Pythonie**: externale muszą być zarejestrowane; jeśli wiązania Python nie pozwalają na wszystkie potrzebne operacje (np. dostęp do `self` w rutynach), fallback: statyczna analiza bajtkodu (wzorce `push "WP"; call TA_xxx`).
- **Rozmiar siatki**: świat to kilkaset tysięcy trójkątów + setki tekstur → glb rzędu 100–300 MB; akceptowalne dla etapu 1, optymalizacja przy 3D Tiles.
- **Nadpisywanie plików addonu**: musi dać świat NK, nie bazowy G2.
