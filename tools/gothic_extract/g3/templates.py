"""Gothic 3 templates (.tple): item, NPC and treasure definitions, keyed by template GUID."""
from dataclasses import dataclass

from .archive import G3Fs
from .entities import Entity, read_template
from .genome import FormatError


@dataclass
class TemplateRec:
    guid: str
    name: str
    path: str
    entity: Entity


def load_templates(fs: G3Fs, failed: list[str] | None = None) -> dict[str, TemplateRec]:
    """All readable templates (patches included). Paths of templates in unsupported variants go to `failed`
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
            out[t.guid] = TemplateRec(t.guid, t.name, path, t)
    return out
