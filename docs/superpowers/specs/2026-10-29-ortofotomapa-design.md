# Ortofotomapy światów gier (GeoTIFF dla Cesium ion) — projekt

Data: 2026-10-29. Status: do zatwierdzenia.

## Po co
Geoportal ma mieć wariant 2D obok widoku 3D. Potrzebna jest warstwa obrazowa, czyli widok z góry na teren i
budynki każdego świata, którą można wgrać do Cesium ion jako imagery. Ion sam tnie plik na kafelki i serwuje je
do Cesium (3D) i do widoku 2D. Dzięki temu nie trzeba stawiać własnego hostingu kafelków.

## Cele
- Nowy, osobny moduł `gothic_extract/ortho/` generuje georeferencjonowany GeoTIFF (EPSG:4326) dla wskazanego świata.
- Działa dla G1, G2 (Khorinis i pozostałe) i G3 (Myrtana).
- Rozdzielczość to parametr (`--gsd`, w metrach na piksel). Domyślnie 0,25 m. Dla całego świata realne jest
  0,10–0,25 m. 0,01 m jest dozwolone tylko dla wycinka (`--bbox`).
- Wynik ma wejść do ion bez dalszej obróbki: kafelkowany GeoTIFF, kompresja bezstratna, kanał alfa poza obrysem świata.
- Pozycje w ortofoto zgadzają się z warstwami GeoJSON (ten sam wzór `enu_to_lonlat` z [coords.py](../../../tools/gothic_extract/coords.py)).

## Poza zakresem (v1)
- Własna piramida kafelków XYZ/PMTiles oraz hosting (wybrano wariant A: ion).
- Mieszanie warstw terenu G3 (gra miesza kilka tekstur na materiał; mamy tylko teksturę bazową).
- Cieniowanie, oświetlenie i cienie. Ortofoto to płaska albedo.
- Zmiany w paczce geoportalu (`package.version` zostaje 4). Moduł tylko dokłada pliki.
- Dzielenie wyniku na wiele plików (patrz „Zostawione wykonawcy”).

## Anty-cele
- Obraz, który wygląda dobrze, ale jest przesunięty względem punktów geoportalu: gorsze niż brak ortofoto.
- Rozdzielczość deklarowana wyższa niż gęstość tekstur: nie udawać szczegółów. Moduł ma to raportować.

## Ograniczenia i ryzyka
- Tekstury w `world.glb` G3 są zmniejszone do 512 px. Ortofoto G3 z paczki będzie więc rozmyte poniżej ok. 25 cm.
  Ponowny eksport terenu G3 z większym `max_texture` jest możliwy (parametr już istnieje w [g3/terrain.py](../../../tools/gothic_extract/g3/terrain.py)).
- Układ w glb (`eastNorthUpToFixedFrame`, prawdziwa płaszczyzna styczna) różni się od liniowego wzoru w stopniach
  rzędu krzywizny Ziemi (rząd metrów na 10 km). Trzeba sprawdzić w Cesium, czy ortofoto nie rozjeżdża się z modelem.
- Teren G3 ma ~2,4 mln trójkątów. Rasteryzacja w czystym numpy musi być wsadowa (po kafelkach), inaczej trwa za długo.
- Limity rozmiaru uploadu w ion trzeba sprawdzić przed generowaniem największych plików.

## Rozważone podejścia
- **A. GeoTIFF na ion.** Wybrane. Jeden plik na świat, ion tnie i hostuje, ten sam obraz dla 3D i 2D. Zależność od ion.
- **B. Własna piramida XYZ (lub PMTiles) na statycznym hostingu.** Niezależność od ion, ale wymaga hostingu (np. R2)
  i tysięcy plików. Odłożone.
- **C. Wspólny rdzeń i oba zapisy.** Przyjęta architektura: rdzeń renderuje raster, a warstwa zapisu jest wymienna,
  więc kafelki XYZ można dodać później jako drugi zapis bez zmiany rdzenia. W v1 powstaje tylko zapis GeoTIFF.

## Decyzje
Zdecydowane z użytkownikiem: wariant A (GeoTIFF), mniejsza dokładność jest akceptowalna, moduł osobny.

Moje wybory (do skorygowania):
- **Źródło siatek:** gotowe `world.glb` (i opcjonalnie `vobs.glb`) z `dist/<gra>/<świat>/`. Jedno wejście dla wszystkich
  gier, bez instalacji gry. Osie glTF: `(E, Up, -N)`, kotwica z `metadata.json`.
- **Zawartość:** teren plus budynki ze statycznej siatki świata. Drzewa i drobne obiekty z `vobs.glb` tylko z `--include-vobs`.
- **Rzut:** prostopadły z góry. Dla każdego piksela wygrywa najwyższy punkt (z-bufor po osi Up). Kolor to próbka
  tekstury w UV (bilinearnie), bez oświetlenia. Piksele bez trójkąta są przezroczyste.
- **Georeferencja:** siatka EPSG:4326 w stopniach, rozmiar piksela `dx = gsd/(N·cos φ)`, `dy = gsd/M` (promienie
  krzywizny jak w `enu_to_lonlat`), więc piksel ma w przybliżeniu `gsd × gsd` metrów. Znaczniki GeoTIFF: ModelPixelScale,
  ModelTiepoint, GeoKeyDirectory.
- **Format:** RGBA 8-bit, kafelki 512×512, kompresja Deflate (bezstratna), zapis strumieniowy kafelek po kafelku
  (stała pamięć), bez zapisu całego rastra naraz. Biblioteka: `tifffile` (nowa zależność w `requirements.txt`);
  bez GDAL i bez rasterio.
- **Interfejs:**
  `python -m gothic_extract.ortho --game g2nk --world khorinis --gsd 0.25 [--bbox E0 N0 E1 N1] [--include-vobs] [--out ...]`.
  Domyślne wyjście: `dist/<gra>/<świat>/ortho/<slug>_<gsd>.tif` oraz `ortho.json` (CRS, bbox, gsd, rozmiar w pikselach,
  źródło tekstur, ostrzeżenia).
- **Zabezpieczenie:** zanim ruszy rendering, program liczy rozmiar w pikselach i zatrzymuje się z komunikatem, gdy
  przekracza próg (np. 2·10⁹ px) bez jawnego `--bbox`. To chroni przed przypadkowym `--gsd 0.01` na całym świecie.
- **Raport jakości:** moduł szacuje gęstość tekstur (cm na teksel dla każdego materiału) i ostrzega, gdy `gsd` jest
  drobniejsze niż najgrubsza istotna tekstura.
- **Testy:** `tools/tests/test_ortho_*.py` na małych syntetycznych siatkach (trójkąt z teksturą daje oczekiwane
  piksele; wzór georeferencji zgadza się z `enu_to_lonlat`; kafelki GeoTIFF odczytywalne i z poprawnymi tagami).

## Zostawione wykonawcy
- Konkretny algorytm rasteryzacji (wsadowy numpy z barycentrycznymi; `moderngl` tylko, jeśli numpy okaże się za wolne).
- Sprawdzenie aktualnych limitów uploadu GeoTIFF w ion i ewentualne `--split` na kilka plików.
- Obsługa świata G3 (duży `world.glb`): sposób ładowania bez zjadania pamięci.
- Opcjonalne łagodne cieniowanie (`--shade`), jeśli płaskie ortofoto okaże się nieczytelne.
