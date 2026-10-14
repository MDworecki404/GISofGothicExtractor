def game_text(s: str | None, encoding: str = "windows-1250") -> str:
    """ZenKit decodes game strings as windows-1252; re-decode them with the game's real code page."""
    if not s:
        return s or ""
    try:
        return s.encode("windows-1252").decode(encoding)
    except UnicodeError:
        return s
