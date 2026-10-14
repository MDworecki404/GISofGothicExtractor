from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _unknown: Counter = field(default_factory=Counter)

    def unknown_item(self, code: str) -> None:
        self._unknown[code] += 1

    def finalize(self) -> None:
        for code, n in sorted(self._unknown.items()):
            self.warnings.append(f"unknown item code: {code} ({n} occurrences)")
        self._unknown.clear()

    def write(self, path: Path) -> None:
        self.finalize()
        lines = ["# Counts"] + [f"{k}: {v}" for k, v in self.counts.items()]
        lines += ["", f"# Warnings ({len(self.warnings)})"] + self.warnings
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
