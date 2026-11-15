

def _lossless_zkstring() -> None:
    """ZenKit decodes native strings as strict windows-1252, which raises on bytes the code page leaves undefined
    (0x81, 0x8D, 0x8F, 0x90, 0x9D: Polish "Ź" and others in windows-1250 scripts). Map those to U+0080–U+009F so
    text.game_text can restore the original bytes."""
    try:
        from zenkit import _native
    except ImportError:
        return

    def value(self) -> str:
        raw = _native.c_char_p.value.__get__(self)
        if raw is None:
            raise ValueError("Failed to load native string")
        return raw.decode("windows-1252", errors="surrogateescape").translate(_UNDEFINED)

    _native.ZkString.value = property(value)


_UNDEFINED = {0xDC00 + b: b for b in (0x81, 0x8D, 0x8F, 0x90, 0x9D)}
_lossless_zkstring()
