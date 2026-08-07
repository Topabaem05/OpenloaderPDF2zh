from __future__ import annotations

from openpdf2zh.document.ir import (
    DocumentIR,
    DocumentRun,
    PageIR,
    ParagraphIR,
    TextStyle,
)
from openpdf2zh.translation.context import TranslationContextBuilder
from openpdf2zh.translation.glossary import Glossary, GlossaryEntry


def _run(
    run_id: str,
    text: str,
    *,
    translatable: bool = True,
    reason: str = "",
) -> DocumentRun:
    return DocumentRun(
        run_id=run_id,
        kind="formula" if reason == "formula" else "text",
        text=text,
        bbox=[0.0, 0.0, 10.0, 10.0],
        char_bboxes=[],
        style=TextStyle(font_name="Times-Roman", font_size=11.0),
        translatable=translatable,
        protection_reason=reason,
    )


def _document() -> DocumentIR:
    return DocumentIR(
        schema_version=1,
        pages=[
            PageIR(
                page_number=1,
                width=612.0,
                height=792.0,
                paragraphs=[
                    ParagraphIR(
                        paragraph_id="p-heading",
                        page_number=1,
                        label="heading",
                        bbox=[0.0, 0.0, 100.0, 20.0],
                        reading_order=0,
                        runs=[_run("r-heading", "Boundary Layer")],
                    ),
                    ParagraphIR(
                        paragraph_id="p-one",
                        page_number=1,
                        label="paragraph",
                        bbox=[0.0, 20.0, 200.0, 60.0],
                        reading_order=1,
                        runs=[
                            _run("r-one-a", "The relation "),
                            _run(
                                "r-one-formula",
                                "Cp = (p-p∞)/q∞",
                                translatable=False,
                                reason="formula",
                            ),
                            _run("r-one-b", " is used here."),
                        ],
                    ),
                    ParagraphIR(
                        paragraph_id="p-two",
                        page_number=1,
                        label="paragraph",
                        bbox=[0.0, 60.0, 200.0, 100.0],
                        reading_order=2,
                        runs=[_run("r-two", "It grows downstream.")],
                    ),
                ],
            )
        ],
    )


def test_context_builder_masks_protected_runs_and_preserves_context() -> None:
    glossary = Glossary([GlossaryEntry("boundary layer", "경계층")])
    items = TranslationContextBuilder().build(
        _document(),
        target_language="Korean",
        glossary=glossary,
    )

    paragraph = next(item for item in items if item.segment_id == "p-one")
    assert paragraph.section_title == "Boundary Layer"
    assert paragraph.previous_text == "Boundary Layer"
    assert paragraph.next_text == "It grows downstream."
    assert "Cp = (p-p∞)/q∞" not in paragraph.text
    assert len(paragraph.protected_tokens) == 1
    token = next(iter(paragraph.protected_tokens))
    assert token in paragraph.text
    assert paragraph.protected_tokens[token] == "Cp = (p-p∞)/q∞"


def test_context_builder_restores_protected_token_exactly() -> None:
    builder = TranslationContextBuilder()
    items = builder.build(_document(), target_language="Korean")
    item = next(item for item in items if item.segment_id == "p-one")
    token = next(iter(item.protected_tokens))

    restored = builder.restore_protected_tokens(
        f"관계식 {token}은 여기서 사용된다.",
        item.protected_tokens,
    )

    assert restored == "관계식 Cp = (p-p∞)/q∞은 여기서 사용된다."


def test_context_builder_rejects_modified_protected_token() -> None:
    import pytest

    builder = TranslationContextBuilder()
    items = builder.build(_document(), target_language="Korean")
    item = next(item for item in items if item.segment_id == "p-one")

    with pytest.raises(ValueError, match="Protected token"):
        builder.restore_protected_tokens("보호 토큰이 사라졌다.", item.protected_tokens)
