"""Gothic 3 templates (.tple): item, NPC and treasure definitions, keyed by template GUID."""
from dataclasses import dataclass

from .archive import G3Fs
from .entities import Entity, read_template, walk
from .genome import FormatError, guid_str


@dataclass
class TemplateRec:
    guid: str
    name: str
    path: str
    entity: Entity


def load_templates(fs: G3Fs, failed: list[str] | None = None) -> dict[str, TemplateRec]:
    """GUID -> template, for the template GUID (entity 0, as in .lrtpldatasc) and the GUIDs of the entities
    below it (what the world references). All readable templates (patches included). Paths of templates in unsupported variants go to `failed`
    (object groups from the editor, deleted and legacy templates; see docs/formats/g3-entity.md)."""
    out: dict[str, TemplateRec] = {}
    created_from: dict[str, str] = {}
    for path in fs.list(suffix=".tple"):
        data = fs.find(path)
        try:
            t = read_template(data)
        except (FormatError, IndexError):
            if failed is not None:
                failed.append(path)
            created_from.update(_creators(data))
            continue
        if t.guid:
            rec = TemplateRec(t.guid, t.name, path, t)
            out[t.guid] = rec
            # world entities (creator) and inventory stacks reference the content entity below entity 0
            for child in walk(t.children):
                if child.guid:
                    out.setdefault(child.guid, rec)
    # entities of unreadable group templates, referenced by the world: resolve through their creator template
    for guid, creator in created_from.items():
        if guid not in out and creator in out:
            out[guid] = out[creator]
    return out


_ENTITY_HEAD = bytes([0x3E, 0, 0, 0])  # u16 0x3e, u16 0


def _creators(data: bytes) -> dict[str, str]:
    """Entity GUID -> creator template GUID from raw template-entity headers (docs/formats/g3-entity.md:
    u16 0x3e, u16 0, id (20), 8 flag bytes, u8 1, creator id (20)). For templates the reader cannot parse."""
    out, i = {}, 0
    while (i := data.find(_ENTITY_HEAD, i)) != -1:
        head = data[i + 4:i + 4 + 20 + 8 + 1 + 20]
        if len(head) == 49 and head[28] == 1 and any(head[:16]) and any(head[29:45]):
            out[guid_str(head[:16])] = guid_str(head[29:45])
        i += 1
    return out
