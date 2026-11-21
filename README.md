# Gothic geoportal extractor

Narzędzia w Pythonie, które z **Twojej własnej, legalnie zakupionej kopii** Gothica 1, Gothica II (NK),
Archolos / Kroniki Myrtany (mody) i Gothica 3 budują paczkę danych dla geoportalu: wyszukiwanie
przedmiotów, unikatowych postaci i zadań (questów) oraz pokazanie ich na mapie świata gry, osadzonej
na globusie (WGS84, CesiumJS / Cesium ion).

> Projekt nie jest powiązany z Piranha Bytes, THQ Nordic ani innymi właścicielami praw do gier.
> Repozytorium **nie zawiera żadnych plików gry** (modeli, tekstur, map, tekstów) ani wyników ekstrakcji.
> Każdy generuje je sam ze swojej instalacji gry. Nie publikuj wygenerowanych paczek (`dist/`, `output/`).

## Co potrafi

- czyta archiwa gry (VDF dla G1/G2, PAK dla G3) i światy (ZEN, a w G3 encje i `.node`),
- uruchamia skrypty gry (Daedalus), żeby wyciągnąć przedmioty, skrzynie, NPC, ich rozkłady dnia i questy,
- eksportuje teren i obiekty do glTF/GLB (instancje, tekstury, podglądy przedmiotów),
- zapisuje GeoJSON z warstwami, indeks wyszukiwania, `quests.json`, lokacje i sieć dróg,
- buduje ortofotomapy świata (GeoTIFF, EPSG:4326) do wgrania na Cesium ion,
- waliduje gotową paczkę.

Format paczki i układ współrzędnych opisuje [tools/gothic_extract/geoportal_README.md](tools/gothic_extract/geoportal_README.md).
Notatki o formatach G3: [docs/formats/g3-entity.md](docs/formats/g3-entity.md). Założenia projektu:
[docs/](docs/).

## Wymagania

- Python 3.11+ (używany jest `tomllib`),
- własna kopia gry w katalogu projektu (patrz niżej),
- zależności: `pip install -r tools/requirements.txt` (ZenKit, numpy, pygltflib, Pillow, matplotlib, tifffile, pytest).

## Instalacja gry

Skopiuj (lub zrób junction/symlink) zainstalowane gry do katalogu głównego repozytorium. Nazwy katalogów
i ścieżki do archiwów są w [tools/gothic_extract/games.toml](tools/gothic_extract/games.toml):

```
GothicClaudiusz/
├── Gothic/                  # Gothic 1
├── Gothic II/               # Gothic II: Noc Kruka
├── Gothic 3/                # Gothic 3 (najlepiej z Community Patch)
├── TheChroniclesOfMyrtana/  # Archolos
└── tools/
```

Katalogi z grą są w `.gitignore`. Jeśli masz grę gdzie indziej, popraw `root` w `games.toml`.

## Użycie

Wszystkie polecenia uruchamiaj z katalogu głównego repozytorium, z `PYTHONPATH=tools`
(PowerShell: `$env:PYTHONPATH = "tools"`).

```powershell
$env:PYTHONPATH = "tools"

# 1. pełna paczka świata/światów gry: ekstrakcja + warstwy + questy + lokacje + walidacja
python -m gothic_extract.package --game g2nk --extract      # Gothic II (Khorinis i pozostałe światy)
python -m gothic_extract.package --game g1 --extract        # Gothic 1
python -m gothic_extract.package --game archolos --extract  # Archolos
python -m gothic_extract.package --game g3 --extract        # Gothic 3 (osobny czytnik silnika Genome)

# 2. sama walidacja gotowych paczek w dist/
python -m gothic_extract.validate

# 3. ortofotomapa świata (GeoTIFF dla Cesium ion)
python -m gothic_extract.ortho --pkg dist/g2nk/khorinis --gsd 0.25
```

Wyniki: surowa ekstrakcja w `output/<gra>/<świat>/`, gotowe paczki w `dist/<gra>/<świat>/`.
Ekstrakcja G3 jest ciężka (kilka GB wyników, kilkadziesiąt minut); paczka Myrtany to około 850 MB.

Pojedynczy świat można wyciągnąć niższym poziomem:

```powershell
python -m gothic_extract --game g2nk --world NEWWORLD --out output/g2nk/newworld
```

Opcje `--skip-mesh`, `--skip-models`, `--skip-previews` pomijają odpowiednio teren, modele obiektów i podglądy.

### Podgląd

`viewer/index.html` to prosty podgląd paczki w przeglądarce. Uruchom serwer statyczny
(`python -m http.server 8765`) i otwórz `http://localhost:8765/viewer/`. Docelowa aplikacja
(CesiumJS) jest osobnym projektem.

## Testy

```powershell
$env:PYTHONPATH = "tools"
python -m pytest tools/tests
```

Część testów potrzebuje plików gry i zostanie pominięta albo nie przejdzie bez zainstalowanych gier.

## Układ repozytorium

| Ścieżka | Zawartość |
|---|---|
| `tools/gothic_extract/` | ekstraktor (G1/G2/Archolos), `package.py`, `validate.py`, `quests*.py`, `locations.py` |
| `tools/gothic_extract/g3/` | czytnik Gothica 3: archiwa PAK, encje, siatki, tekstury, teren, questy |
| `tools/gothic_extract/ortho/` | generator ortofotomap |
| `tools/tests/` | testy jednostkowe |
| `docs/` | specyfikacje, plany, opisy formatów |
| `viewer/` | podgląd paczki w przeglądarce |

## Licencja i prawa do gier

Kod jest na licencji MIT (plik [LICENSE](LICENSE)). Licencja nie obejmuje danych gier. Wygenerowane
modele, tekstury, mapy, opisy i dialogi pozostają własnością ich właścicieli i służą wyłącznie do użytku
osobistego z własną kopią gry.
