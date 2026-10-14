def _to_bytes(s: str) -> bytes:
    """Undo ZenKit's windows-1252 decoding; bytes cp1252 leaves undefined come back as U+0080–U+009F."""
    out = bytearray()
    for ch in s:
        try:
            out += ch.encode("windows-1252")
        except UnicodeEncodeError:
            if ord(ch) < 256:
                out.append(ord(ch))
            else:
                raise
    return bytes(out)


def game_text(s: str | None, encoding: str = "windows-1250") -> str:
    """ZenKit decodes game strings as windows-1252; re-decode them with the game's real code page."""
    if not s:
        return s or ""
    try:
        return _to_bytes(s).decode(encoding)
    except UnicodeError:
        return s
