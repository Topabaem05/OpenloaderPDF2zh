from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    source: str
    target: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Glossary source term must not be empty")
        if not self.target.strip():
            raise ValueError("Glossary target term must not be empty")


class Glossary:
    def __init__(self, entries: list[GlossaryEntry] | None = None) -> None:
        self._entries: dict[str, GlossaryEntry] = {}
        for entry in entries or []:
            self.add(entry.source, entry.target)

    @classmethod
    def from_csv(cls, path: Path | str) -> "Glossary":
        entries: list[GlossaryEntry] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            normalized_fields = {
                str(field or "").strip().lower(): field for field in (reader.fieldnames or [])
            }
            source_field = normalized_fields.get("source")
            target_field = normalized_fields.get("target")
            if source_field is None or target_field is None:
                raise ValueError("Glossary CSV must contain source,target columns")
            for row in reader:
                source = str(row.get(source_field, "") or "").strip()
                target = str(row.get(target_field, "") or "").strip()
                if source and target:
                    entries.append(GlossaryEntry(source=source, target=target))
        return cls(entries)

    def add(self, source: str, target: str) -> None:
        entry = GlossaryEntry(source=source.strip(), target=target.strip())
        self._entries[entry.source.casefold()] = entry

    def merge(self, other: "Glossary", *, prefer_other: bool = True) -> "Glossary":
        merged = Glossary(list(self._entries.values()))
        for entry in other.entries:
            key = entry.source.casefold()
            if prefer_other or key not in merged._entries:
                merged._entries[key] = entry
        return merged

    @property
    def entries(self) -> list[GlossaryEntry]:
        return sorted(
            self._entries.values(),
            key=lambda entry: (-len(entry.source), entry.source.casefold()),
        )

    def matches(self, text: str) -> list[GlossaryEntry]:
        folded = text.casefold()
        return [entry for entry in self.entries if entry.source.casefold() in folded]

    def mapping_for_text(self, text: str) -> dict[str, str]:
        return {entry.source: entry.target for entry in self.matches(text)}

    def __bool__(self) -> bool:
        return bool(self._entries)
