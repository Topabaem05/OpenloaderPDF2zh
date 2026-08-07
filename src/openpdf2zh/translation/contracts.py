from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TranslationRequestItem:
    segment_id: str
    text: str
    target_language: str
    section_title: str = ""
    paragraph_text: str = ""
    previous_text: str = ""
    next_text: str = ""
    glossary: dict[str, str] = field(default_factory=dict)
    protected_tokens: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("segment_id must not be empty")
        if not self.target_language.strip():
            raise ValueError("target_language must not be empty")
