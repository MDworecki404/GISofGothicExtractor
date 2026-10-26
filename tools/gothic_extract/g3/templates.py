"""Gothic 3 templates (.tple): item, NPC and treasure definitions, keyed by template GUID."""
from dataclasses import dataclass

from .archive import G3Fs
from .entities import Entity, read_template, walk
from .genome import FormatError


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
    for path in fs.list(suffix=".tple"):
        try:
            t = read_template(fs.find(path))
        except (FormatError, IndexError):
            if failed is not None:
                failed.append(path)
            continue
        if t.guid:
            rec = TemplateRec(t.guid, t.name, path, t)
            out[t.guid] = rec
            # world entities (creator) and inventory stacks reference the content entity below entity 0
            for child in walk(t.children):
                if child.guid:
                    out.setdefault(child.guid, rec)
    return out
