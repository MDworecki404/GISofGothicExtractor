"""Localized texts of Gothic 3: stringtable.ini (UTF-16).

[LocAdmin_Languages] Languages=Polish;… lists the columns; [LocAdmin_Strings] has KEY=value1;value2;…
(one value per language, each followed by ';').
"""
from .archive import G3Fs


def _decode(data: bytes) -> str:
    return data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("cp1250")


def load_strings(fs: G3Fs, lang: str = "Polish") -> dict[str, str]:
    data = fs.find("stringtable.ini")
    if data is None:
        raise FileNotFoundError("stringtable.ini not found in the archives")
    section, column, out = "", 0, {}
    for line in _decode(data).splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if section == "LocAdmin_Languages" and key == "Languages":
            langs = [v for v in value.split(";") if v]
            if lang not in langs:
                raise ValueError(f"language {lang} not in {langs}")
            column = langs.index(lang)
        elif section == "LocAdmin_Strings":
            values = value.split(";")
            if column < len(values):
                out[key] = values[column]
    return out
