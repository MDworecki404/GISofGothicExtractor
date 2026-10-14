from gothic_extract.text import game_text


def test_cp1250_letters_on_cp1252_undefined_bytes():
    # 0x8F is 'Ź' in cp1250 but undefined in cp1252; arrives as U+008F
    assert game_text("\x8fr\xf3d\xb3o") == "Źródło"


def test_regular_mojibake_fixed():
    assert game_text("Z³oto") == "Złoto"
