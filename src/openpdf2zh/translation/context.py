from __future__ import annotations

from dataclasses import dataclass

from openpdf2zh.document.ir import DocumentIR, DocumentRun, ParagraphIR
from openpdf2zh.translation.contracts import TranslationRequestItem
from openpdf2zh.translation.glossary import Glossary


@dataclass(slots=True)
class _ParagraphContext:
    paragraph: ParagraphIR
    section_title: str
    previous_text: str
    next_text: str


class TranslationContextBuilder:
    TOKEN_PREFIX = "OPENPDF2ZH_PROTECTED"

    def build(
        self,
        document: DocumentIR,
        *,
        target_language: str,
        glossary: Glossary | None = None,
    ) -> list[TranslationRequestItem]:
        paragraphs = self._collect_translatable_paragraphs(document)
        items: list[TranslationRequestItem] = []
        for contextual in paragraphs:
            paragraph = contextual.paragraph
            masked_text, protected_tokens = self._mask_paragraph(paragraph)
            glossary_mapping = (
                glossary.mapping_for_text(paragraph.original_text) if glossary else {}
            )
            items.append(
                TranslationRequestItem(
                    segment_id=paragraph.paragraph_id,
                    text=masked_text,
                    target_language=target_language,
                    section_title=contextual.section_title,
                    previous_text=contextual.previous_text,
                    next_text=contextual.next_text,
                    glossary=glossary_mapping,
                    protected_tokens=protected_tokens,
                )
            )
        return items

    def build_runs(
        self,
        document: DocumentIR,
        *,
        target_language: str,
        glossary: Glossary | None = None,
    ) -> list[TranslationRequestItem]:
        items: list[TranslationRequestItem] = []
        for contextual in self._collect_translatable_paragraphs(document):
            paragraph = contextual.paragraph
            glossary_mapping = (
                glossary.mapping_for_text(paragraph.original_text) if glossary else {}
            )
            for run in paragraph.runs:
                if not run.translatable or not run.text.strip():
                    continue
                items.append(
                    TranslationRequestItem(
                        segment_id=run.run_id,
                        text=run.text,
                        target_language=target_language,
                        section_title=contextual.section_title,
                        previous_text=contextual.previous_text,
                        next_text=contextual.next_text,
                        glossary=dict(glossary_mapping),
                    )
                )
        return items

    def restore_protected_tokens(
        self,
        translated_text: str,
        protected_tokens: dict[str, str],
    ) -> str:
        restored = translated_text
        for token, original in protected_tokens.items():
            if token not in restored:
                raise ValueError(f"Protected token was modified or removed: {token}")
            restored = restored.replace(token, original)
        return restored

    def _collect_translatable_paragraphs(
        self,
        document: DocumentIR,
    ) -> list[_ParagraphContext]:
        ordered: list[ParagraphIR] = []
        for page in sorted(document.pages, key=lambda page: page.page_number):
            ordered.extend(
                sorted(
                    page.paragraphs,
                    key=lambda paragraph: paragraph.reading_order,
                )
            )

        collected: list[_ParagraphContext] = []
        section_title = ""
        translatable_indexes = [
            index
            for index, paragraph in enumerate(ordered)
            if any(run.translatable and run.text.strip() for run in paragraph.runs)
        ]
        index_to_position = {
            paragraph_index: position
            for position, paragraph_index in enumerate(translatable_indexes)
        }

        for index, paragraph in enumerate(ordered):
            if paragraph.label.strip().lower() == "heading":
                section_title = paragraph.original_text.strip()
            if index not in index_to_position:
                continue
            position = index_to_position[index]
            previous_text = (
                ordered[translatable_indexes[position - 1]].original_text
                if position > 0
                else ""
            )
            next_text = (
                ordered[translatable_indexes[position + 1]].original_text
                if position + 1 < len(translatable_indexes)
                else ""
            )
            collected.append(
                _ParagraphContext(
                    paragraph=paragraph,
                    section_title=section_title,
                    previous_text=previous_text,
                    next_text=next_text,
                )
            )
        return collected

    def _mask_paragraph(self, paragraph: ParagraphIR) -> tuple[str, dict[str, str]]:
        chunks: list[str] = []
        protected: dict[str, str] = {}
        for run in paragraph.runs:
            if run.translatable:
                chunks.append(run.text)
                continue
            token = self._token_for_run(run)
            chunks.append(token)
            protected[token] = run.text
        return "".join(chunks), protected

    def _token_for_run(self, run: DocumentRun) -> str:
        safe_id = "".join(char if char.isalnum() else "_" for char in run.run_id)
        return f"<{self.TOKEN_PREFIX}_{safe_id}>"
