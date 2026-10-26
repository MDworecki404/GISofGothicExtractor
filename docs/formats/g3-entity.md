# Gothic 3: drzewo encji w `.lrentdat` i `.tple`

Rozpoznane 2026-10-26 na `G3_Myrtana_01_Silden_NPC_01.lrentdat` (1 053 781 B) i
`Plants_Story_It_Plant_Perm_01.tple` (5 731 B), sprawdzone czytnikiem na wszystkich plikach świata.
Typy: `u8/u16/u32` little-endian, `f32`, `id` = `bCPropertyID` (16 B GUID + `u32`, w danych zawsze 0),
`str` = `u16` indeks w tablicy napisów pliku (`genome.py`), `mat` = 16 × `f32` (wiersze; translacja w wierszu 4,
elementy 12–14), `box` = 6 × `f32` (min, max), `sphere` = 4 × `f32` (promień, środek).

## `.lrentdat` (encje świata, wersja 83)

```
"GENOMFLE" u16 1 u32 offset_napisów
"GENOMEDL" u16 0x53
obiekt właściwości eCEntityDynamicContext (ID, ContextBox); jego dane klasy (do końca obiektu = offset_napisów):
    u16 0x53, u8 1, f32 1.0, f32 1.0, box (= ContextBox), u32 liczba_encji
    liczba_encji × encja (płasko, kolejność = indeks)
    hierarchia: pary (u32 rodzic, u32 dziecko) aż do pary (0xFFFFFFFF, 0xFFFFFFFF)
```

Encja (przykład Silden, `Orc_Elite_02` od offsetu 455):

| pole | rozmiar | uwagi |
|---|---|---|
| `u16 0x40` | 2 | |
| `u16 0x53` | 2 | |
| `u8` jest twórca | 1 | 0 u korzenia |
| `id` twórcy | 20 | tylko gdy jest; GUID szablonu (`.lrtpldatasc`) |
| `u16 0x53`, `u16 1` | 4 | |
| `id` encji | 20 | |
| flagi | 7 | `01 01 00 01 00 01 01` |
| `f32` | 4 | 1.0 |
| `u32` | 4 | 0 u korzenia, 1 u pozostałych |
| `u16 0` | 2 | |
| `str` nazwa | 2 | `RootEntity`, `Orc_Elite_02`, `Orc_Head_S02`… |
| `mat` świata | 64 | pozycja = elementy 12–14 |
| `mat` lokalna | 64 | |
| 3 × `box` | 72 | świat, lokalny, drzewo |
| 2 × `sphere` | 32 | |
| ogon | 19 | `f32, u8, f32, u32, f32, u16` (znaczenie nieznane) |
| `u32` liczba zestawów | 4 | |
| zestawy | | każdy: `u16` (stałe dla klasy), obiekt właściwości, `u32 0xDEADC0DE` |

## `.tple` (szablony, wersja 62)

```
["GENOMFLE" u16 1 u32 offset_napisów]   (brak w wariancie z napisami w treści)
"GENOMETP" u16 62 u16 1 u8 1 u32 n, n napisów (indeksy albo napisy wprost)
u32 rozmiar (do końca hierarchii), u32 liczba_encji
liczba_encji × encja szablonu
hierarchia jak wyżej
```

Encja 0 to kontener szablonu: jej `id` = GUID szablonu z `.lrtpldatasc`
(`{ff68c3ea-4b6b-49a1-9866-adf806250707}:0=Plants_Story_It_Plant_Perm_01.tple`). Encja 1 (dziecko 0) niesie
zestawy właściwości. Obie mają tę samą nazwę (`It_Plant_Perm_01`).

| pole | rozmiar | uwagi |
|---|---|---|
| `u16 0x3e` | 2 | |
| `u16 0` | 2 | |
| `id` encji | 20 | |
| flagi | 8 | |
| `u8` jest twórca | 1 | |
| `id` twórcy | 20 | tylko gdy jest (encje w grupach obiektów wstawione z innego szablonu) |
| `f32` | 4 | 1.0 |
| `u8` | 1 | |
| `u16 0` | 2 | |
| `str` nazwa | 2 | |
| `mat` świata, `mat` lokalna | 128 | |
| 3 × `box` | 72 | bez sfer |
| ogon | 21 | `f32, u16, f32, u32, u8, f32, u16` |
| `u32` liczba zestawów | 4 | |
| zestawy | | każdy: `u16`, `u32` rozmiar obiektu, `u16 2`, obiekt właściwości, `u32 0xDEADC0DE` |
