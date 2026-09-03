from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import TranslationUnit
from openpdf2zh.services.translation_service import TranslationService


def test_sanitize_translated_text_collapses_spaced_single_token_repetition() -> None:
    service = TranslationService(AppSettings())

    sanitized = service._sanitize_translated_text("T T T T T T T T")

    assert sanitized == "T"


def test_sanitize_translated_text_collapses_repeated_fragment_repetition() -> None:
    service = TranslationService(AppSettings())

    sanitized = service._sanitize_translated_text("소용소용소용소용소용소용소용")

    assert sanitized == "소용"


def test_sanitize_translated_text_collapses_spaced_word_repetition() -> None:
    service = TranslationService(AppSettings())

    sanitized = service._sanitize_translated_text("인덱스 인덱스 인덱스 인덱스 인덱스")

    assert sanitized == "인덱스"


def test_translation_preserves_code_and_rejects_token_floods() -> None:
    class _Translator:
        def __init__(self) -> None:
            self.calls = 0

        def translate(self, text: str, *, target_language: str, model: str) -> str:
            _ = text, target_language, model
            self.calls += 1
            return "우분투 우 우분투 우 우분투 우 우분투 우 우분투 우"

    service = TranslationService(AppSettings())
    translator = _Translator()
    code = TranslationUnit(
        unit_id="u00001",
        page_number=1,
        label="paragraph",
        bbox=[10.0, 10.0, 100.0, 20.0],
        original='"class_name": "page_header_hybrid",',
    )
    word = TranslationUnit(
        unit_id="u00002",
        page_number=1,
        label="paragraph",
        bbox=[10.0, 30.0, 100.0, 40.0],
        original="Ubuntu",
    )
    terminal_output = TranslationUnit(
        unit_id="u00003",
        page_number=1,
        label="paragraph",
        bbox=[10.0, 40.0, 200.0, 50.0],
        original="bjones is not in the sudoers file.",
        font_name="UbuntuMono-Regular",
    )

    assert service._translate_unit_text(
        translator, code, target_language="Korean", model="local"
    ) == code.original
    email_list = TranslationUnit(
        unit_id="u00003",
        page_number=1,
        label="paragraph",
        bbox=[10.0, 20.0, 100.0, 30.0],
        original="yang-qi@shu.edu.cn, aw@funstory.ai",
    )
    assert service._translate_unit_text(
        translator, email_list, target_language="Korean", model="local"
    ) == email_list.original
    assert service._translate_unit_text(
        translator, word, target_language="Korean", model="local"
    ) == word.original
    assert service._translate_unit_text(
        translator,
        terminal_output,
        target_language="Korean",
        model="local",
    ) == terminal_output.original
    assert translator.calls == 1


def test_postprocess_translated_text_removes_exact_appended_source() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=12,
        label="paragraph",
        bbox=[89.995, 137.319, 432.001, 176.683],
        original="Used for program listings and variable names.",
    )

    translated = service._postprocess_translated_text(
        unit,
        "프로그램 목록과 변수 이름에 사용됩니다.Used for program listings and variable names.",
    )

    assert translated == "프로그램 목록과 변수 이름에 사용됩니다."


def test_postprocess_translated_text_removes_case_changed_appended_source() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=12,
        label="heading",
        bbox=[72.0, 589.0, 203.0, 612.0],
        original="System Health Guide",
    )

    translated = service._postprocess_translated_text(
        unit,
        "시스템 상태 안내System health guide",
    )

    assert translated == "시스템 상태 안내"


def test_postprocess_translated_text_removes_fuzzy_appended_source() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=5,
        label="list item",
        bbox=[39.0, 100.0, 240.0, 114.0],
        original="Creating a Sudoer",
    )

    translated = service._postprocess_translated_text(
        unit,
        "sudo 사용자 생성Create a Sudoer",
    )

    assert translated == "sudo 사용자 생성"


def test_postprocess_translated_text_removes_partial_appended_source() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=7,
        label="list item",
        bbox=[39.0, 100.0, 240.0, 114.0],
        original="Uninstalling a Source-Installed Software Package",
    )

    translated = service._postprocess_translated_text(
        unit,
        "소스 설치 소프트웨어 패키지 제거Unstalled Software Package",
    )

    assert translated == "소스 설치 소프트웨어 패키지 제거"


def test_postprocess_translated_text_removes_trailing_hallucinated_word() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=8,
        label="list item",
        bbox=[39.0, 100.0, 240.0, 114.0],
        original="Formatting System Activity Reports",
    )

    translated = service._postprocess_translated_text(
        unit,
        "시스템 활동 보고서 서식 지정Specifying",
    )

    assert translated == "시스템 활동 보고서 서식 지정"


def test_postprocess_translated_text_removes_only_added_source_glosses() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=8,
        label="paragraph",
        bbox=[95.0, 469.0, 432.0, 483.0],
        original="Normalizing, Scaling, and/or Standardizing a Random Variable",
    )

    translated = service._postprocess_translated_text(
        unit,
        "확률 변수의 정규화(Normalizing), 스케일링(Scaling) 및 표준화(Standardizing)",
    )

    assert translated == "확률 변수의 정규화, 스케일링 및 표준화"
    source_parentheses = replace(
        unit,
        original="Continuous Distributions (Density Versus Mass)",
    )
    assert service._postprocess_translated_text(
        source_parentheses,
        "연속 확률 분포 (Density Versus Mass)",
    ) == "연속 확률 분포 (Density Versus Mass)"
    assert service._postprocess_translated_text(
        replace(unit, original="Directory in which software is installed."),
        "소프트웨어가 설치된 디렉터리입니다.The",
    ) == "소프트웨어가 설치된 디렉터리입니다."


def test_postprocess_translated_text_restores_dropped_inline_links() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=14,
        label="paragraph",
        bbox=[72.0, 200.0, 340.0, 214.0],
        original="Find us on LinkedIn: https://linkedin.com/company/oreilly-media",
    )

    translated = service._postprocess_translated_text(unit, "LinkedIn에서 찾기:")

    assert translated == (
        "LinkedIn에서 찾기: https://linkedin.com/company/oreilly-media"
    )


def test_postprocess_translated_text_restores_dropped_social_handle() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=2,
        label="paragraph",
        bbox=[313.0, 104.0, 402.0, 116.0],
        original="Twitter: @oreillymedia",
    )

    translated = service._postprocess_translated_text(unit, "트위터: @")

    assert translated == "Twitter: @oreillymedia"


def test_postprocess_translated_text_preserves_contact_literals() -> None:
    service = TranslationService(AppSettings())
    originals = (
        "O’Reilly Media, Inc.",
        "1005 Gravenstein Highway North",
        "Sebastopol, CA 95472",
        "707-829-0515 (international or local)",
        "Twitter: @oreillymedia",
        "linkedin.com/company/oreilly-media",
    )

    for index, original in enumerate(originals):
        unit = TranslationUnit(
            unit_id=f"u{index:05d}",
            page_number=14,
            label="paragraph",
            bbox=[90.0, 260.0, 300.0, 275.0],
            original=original,
        )
        assert service._postprocess_translated_text(unit, "손상된 번역") == original


def test_unchanged_sentence_with_trailing_url_is_retried_without_url() -> None:
    class _Translator:
        def __init__(self) -> None:
            self.sources: list[str] = []

        def translate(self, text: str, *, target_language: str, model: str) -> str:
            _ = target_language, model
            self.sources.append(text)
            if "https://" in text:
                return text
            return "보충 자료를 다운로드할 수 있습니다."

    service = TranslationService(AppSettings())
    translator = _Translator()
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=13,
        label="paragraph",
        bbox=[72.0, 360.0, 432.0, 388.0],
        original=(
            "Supplemental material is available for download at "
            "https://example.com/material."
        ),
    )

    translated = service._translate_unit_text(
        translator,
        unit,
        target_language="Korean",
        model="local",
    )

    assert translator.sources == [
        unit.original,
        "Supplemental material is available for download at",
    ]
    assert translated == (
        "보충 자료를 다운로드할 수 있습니다. https://example.com/material"
    )


def test_discretionary_line_hyphen_is_removed_before_translation() -> None:
    class _Translator:
        def __init__(self) -> None:
            self.source = ""

        def translate(self, text: str, *, target_language: str, model: str) -> str:
            _ = target_language, model
            self.source = text
            return "기관 영업 부서에 문의하십시오."

    service = TranslationService(AppSettings())
    translator = _Translator()
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=4,
        label="paragraph",
        bbox=[72.0, 494.0, 432.0, 526.0],
        original=(
            "Contact our corporate/institu‐ tional sales department at "
            "https://example.com/up-to-date."
        ),
    )

    translated = service._translate_unit_text(
        translator,
        unit,
        target_language="Korean",
        model="local",
    )

    assert translator.source == (
        "Contact our corporate/institutional sales department at "
        "https://example.com/up-to-date."
    )
    assert translated == (
        "기관 영업 부서에 문의하십시오. https://example.com/up-to-date"
    )


def test_unchanged_compound_text_is_retried_by_segment() -> None:
    translations = {
        "Satisfying Prerequisites:": "필수 조건 충족:",
        "Building a Development Environment": "개발 환경 구축",
        "The O’Reilly logo is a registered trademark of O’Reilly Media, Inc.": (
            "O’Reilly 로고는 O’Reilly Media, Inc.의 등록 상표입니다."
        ),
        "Practical Linux System Administration and related trade dress are "
        "trademarks of O’Reilly Media, Inc.": (
            "Practical Linux System Administration과 관련 트레이드 드레스는 "
            "O’Reilly Media, Inc.의 상표입니다."
        ),
    }

    class _Translator:
        def translate(self, text: str, *, target_language: str, model: str) -> str:
            _ = target_language, model
            return translations.get(text, text)

    service = TranslationService(AppSettings())
    translator = _Translator()
    heading = TranslationUnit(
        unit_id="u00001",
        page_number=7,
        label="paragraph",
        bbox=[95.0, 393.0, 432.0, 408.0],
        original="Satisfying Prerequisites: Building a Development Environment",
    )
    trademark = TranslationUnit(
        unit_id="u00002",
        page_number=4,
        label="paragraph",
        bbox=[72.0, 318.0, 432.0, 340.0],
        original=(
            "The O’Reilly logo is a registered trademark of O’Reilly Media, Inc. "
            "Practical Linux System Administration and related trade dress are "
            "trademarks of O’Reilly Media, Inc."
        ),
    )

    assert service._translate_unit_text(
        translator,
        heading,
        target_language="Korean",
        model="local",
    ) == "필수 조건 충족: 개발 환경 구축"
    assert "등록 상표입니다" in service._translate_unit_text(
        translator,
        trademark,
        target_language="Korean",
        model="local",
    )


def test_postprocess_translated_text_preserves_source_bullet() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=12,
        label="list item",
        bbox=[80.0, 100.0, 370.0, 114.0],
        original="• Chapter 1 introduces Linux.",
    )

    translated = service._postprocess_translated_text(
        unit, "1장에서는 Linux를 소개합니다."
    )

    assert translated == "• 1장에서는 Linux를 소개합니다."


def test_restore_source_rows_rebuilds_toc_entries(tmp_path: Path) -> None:
    source_pdf = tmp_path / "toc.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 40), "Table of Contents", fontsize=18)
    page.insert_text((40, 100), "Chapter One . . . . .  1", fontsize=10)
    page.insert_text((40, 120), "Chapter Two . . . . .  10", fontsize=10)
    document.save(source_pdf)
    document.close()

    service = TranslationService(AppSettings())
    restored = service._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="paragraph",
                bbox=[35.0, 270.0, 260.0, 315.0],
                original="Chapter One 1 Chapter Two 10",
                font_size=10.0,
            )
        ],
        source_pdf,
    )

    assert [unit.original for unit in restored] == ["Chapter One", "Chapter Two"]
    assert [unit.toc_page_number for unit in restored] == ["1", "10"]


def test_restore_source_rows_rebuilds_wrapped_toc_entry(tmp_path: Path) -> None:
    source_pdf = tmp_path / "wrapped-toc.pdf"
    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_text((40, 40), "Table of Contents", fontsize=18)
    page.insert_text(
        (40, 100),
        "6. Singular Value Decomposition: Image Processing,",
        fontsize=12,
    )
    page.insert_text(
        (54, 114),
        "and Social Media . . . . . . . . . . . . . . . . 187",
        fontsize=12,
    )
    page.insert_text((54, 140), "Matrix Factorization . . . . . . 188", fontsize=10)
    document.save(source_pdf)
    document.close()

    service = TranslationService(AppSettings())
    restored = service._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="paragraph",
                bbox=[35.0, 250.0, 460.0, 315.0],
                original="and Social Media 187 Matrix Factorization 188",
                font_size=12.0,
            )
        ],
        source_pdf,
    )

    wrapped = next(unit for unit in restored if unit.toc_page_number == "187")
    assert wrapped.original == (
        "6. Singular Value Decomposition: Image Processing, and Social Media"
    )
    assert wrapped.estimated_line_count == 2



def test_restore_source_rows_splits_parser_merged_blocks(tmp_path: Path) -> None:
    source_pdf = tmp_path / "credits.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 100), "Editor: Jane", fontsize=10)
    page.insert_text((40, 120), "Designer: Kim", fontsize=10)
    document.save(source_pdf)
    document.close()

    service = TranslationService(AppSettings())
    restored = service._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="paragraph",
                bbox=[35.0, 270.0, 180.0, 315.0],
                original="Editor: Jane Designer: Kim",
                font_size=10.0,
            )
        ],
        source_pdf,
    )

    assert [unit.original for unit in restored] == ["Editor: Jane", "Designer: Kim"]


def test_restore_source_rows_rebuilds_table_cells(monkeypatch, tmp_path: Path) -> None:
    source_pdf = tmp_path / "table.pdf"
    document = fitz.open()
    document.new_page(width=300, height=400)
    document.save(source_pdf)
    document.close()
    source_lines = [
        {
            "text": "Body text reaching the column edge",
            "bbox": [8.0, 115.0, 240.0, 125.0],
            "font_size": 9.0,
            "font_name": "ArialMT",
            "font_color": 0,
            "block_index": 3,
        },
        {
            "text": "Directory Description",
            "bbox": [10.0, 100.0, 100.0, 110.0],
            "font_size": 9.0,
            "font_name": "ArialMT",
            "font_color": 0xFFFFFF,
            "block_index": 4,
        },
        {
            "text": "/",
            "bbox": [10.0, 80.0, 14.0, 90.0],
            "font_size": 9.0,
            "font_name": "ArialMT",
            "font_color": 0,
            "block_index": 4,
        },
        {
            "text": "Root filesystem",
            "bbox": [50.0, 80.0, 130.0, 90.0],
            "font_size": 9.0,
            "font_name": "ArialMT",
            "font_color": 0,
            "block_index": 4,
        },
        {
            "text": "/bin",
            "bbox": [10.0, 60.0, 25.0, 70.0],
            "font_size": 9.0,
            "font_name": "ArialMT",
            "font_color": 0,
            "block_index": 4,
        },
        {
            "text": "Executable files",
            "bbox": [50.0, 60.0, 140.0, 70.0],
            "font_size": 9.0,
            "font_name": "ArialMT",
            "font_color": 0,
            "block_index": 4,
        },
    ]
    service = TranslationService(AppSettings())
    monkeypatch.setattr(service, "_extract_source_lines", lambda _page: source_lines)

    restored = service._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="paragraph",
                bbox=[10.0, 59.0, 140.0, 111.0],
                original=(
                    "Directory Description / Root filesystem /bin Executable files"
                ),
                font_size=9.0,
            )
        ],
        source_pdf,
    )

    assert [unit.original for unit in restored] == [
        "Directory Description",
        "/",
        "Root filesystem",
        "/bin",
        "Executable files",
    ]
    assert restored[0].label == "table header"
    assert restored[1].label == "table cell"
    assert restored[1].bbox[2] == 48.0
    assert restored[2].bbox[2] == 240.0
    assert restored[2].line_height_pt == 10.35


def test_restore_source_rows_merges_display_fragments_from_one_block(
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "title.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 60), "Practical Linux System", fontsize=20)
    page.insert_text((40, 82), "Administration", fontsize=20)
    document.save(source_pdf)
    document.close()

    service = TranslationService(AppSettings())
    document = fitz.open(source_pdf)
    lines = service._extract_source_lines(document[0])
    document.close()
    units = [
        service._source_line_unit(1, line, str(line["text"]), "", label="heading")
        for line in lines
    ]

    restored = service._restore_source_rows(units, source_pdf)

    assert len(restored) == 1
    assert restored[0].original == "Practical Linux System Administration"


def test_address_is_not_misclassified_as_toc_entry() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=14,
        label="paragraph",
        bbox=[90.0, 350.0, 300.0, 365.0],
        original="1005 Gravenstein Highway North Sebastopol CA 95472",
    )

    assert service._extract_inline_page_number_unit(unit, unit.original) is None


def test_url_wrapped_paragraph_is_not_split_as_labeled_rows() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=4,
        label="paragraph",
        bbox=[72.0, 494.0, 432.0, 526.0],
        original="wrapped paragraph",
    )
    source_lines = [
        {
            "text": "Read more at https://example.com and continue reading",
            "bbox": [72.0, 515.0, 432.0, 526.0],
            "block_index": 6,
        },
        {
            "text": "the same paragraph at https://example.org for details",
            "bbox": [72.0, 504.0, 432.0, 515.0],
            "block_index": 6,
        },
        {
            "text": "on the final line.",
            "bbox": [72.0, 494.0, 180.0, 504.0],
            "block_index": 6,
        },
    ]

    assert not service._should_restore_individual_rows(unit, source_lines)


def test_same_baseline_fragments_are_not_split_into_separate_rows() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=1,
        label="paragraph",
        bbox=[10.0, 50.0, 210.0, 65.0],
        original="Beijing Boston Farnham",
    )
    source_lines = [
        {
            "text": text,
            "bbox": [left, 50.0, left + 35.0, 65.0],
            "block_index": 4,
        }
        for text, left in (("Beijing", 10.0), ("Boston", 70.0), ("Farnham", 130.0))
    ]

    assert not service._should_restore_individual_rows(unit, source_lines)


def test_split_list_item_content_splits_combined_numbered_toc_entries() -> None:
    service = TranslationService(AppSettings())

    parts = service._split_list_item_content(
        "8.3 Speed of Sound 573 8.3.1 Comments 581"
    )

    assert parts == ["8.3 Speed of Sound 573", "8.3.1 Comments 581"]


def test_split_toc_unit_extracts_trailing_page_number_for_list_item() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=5,
        label="list item",
        bbox=[39.425, 167.92, 219.449, 191.417],
        original="3.1 Introduction and Road Map 210",
        font_size=12.0,
        font_name="ArialMT",
    )

    split_units = service._split_toc_unit(unit)

    assert len(split_units) == 1
    assert split_units[0].original == "3.1 Introduction and Road Map"
    assert split_units[0].toc_page_number == "210"


def test_postprocess_units_splits_combined_toc_entries_before_page_extraction() -> None:
    service = TranslationService(AppSettings())
    units = [
        TranslationUnit(
            unit_id="u00001",
            page_number=4,
            label="list item",
            bbox=[86.645, 384.069, 265.125, 432.579],
            original="1.4 Some Fundamental Aerodynamic Variables 15 1.4.1 Units 18",
            font_size=12.0,
            font_name="ArialMT",
        )
    ]

    processed = service._postprocess_units(units)

    assert [unit.original for unit in processed] == [
        "1.4 Some Fundamental Aerodynamic Variables",
        "1.4.1 Units",
    ]
    assert [unit.toc_page_number for unit in processed] == ["15", "18"]


def test_postprocess_units_converts_part_toc_entry_into_heading() -> None:
    service = TranslationService(AppSettings())
    units = [
        TranslationUnit(
            unit_id="u00001",
            page_number=5,
            label="list item",
            bbox=[39.425, 245.93, 92.009, 296.598],
            original="PART 2",
            font_size=18.0,
            font_name="ArialMT",
        )
    ]

    processed = service._postprocess_units(units)

    assert len(processed) == 1
    assert processed[0].label == "paragraph"
    assert processed[0].original == "PART 2"
    assert processed[0].toc_page_number == ""


def test_postprocess_units_joins_word_split_by_discretionary_hyphen() -> None:
    service = TranslationService(AppSettings())
    processed = service._postprocess_units(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="paragraph",
                bbox=[10.0, 20.0, 200.0, 32.0],
                original="worldwide enter‐",
                font_size=10.0,
                estimated_line_count=1,
            ),
            TranslationUnit(
                unit_id="u00002",
                page_number=1,
                label="paragraph",
                bbox=[10.0, 8.0, 200.0, 20.5],
                original="prise adoption",
                font_size=10.0,
                estimated_line_count=1,
            ),
        ]
    )

    assert len(processed) == 1
    assert processed[0].original == "worldwide enterprise adoption"
    assert processed[0].estimated_line_count == 2


def test_postprocess_translated_text_rewrites_structural_chapter_label() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=7,
        label="heading",
        bbox=[39.425, 484.466, 87.071, 510.346],
        original="Chapter 7",
    )

    translated = service._postprocess_translated_text(unit, "Chapter 7")

    assert translated == "7장"


def test_postprocess_translated_text_rewrites_common_front_matter_title() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=5,
        label="heading",
        bbox=[287.0, 561.0, 432.0, 591.0],
        original="Table of Contents",
    )

    assert service._postprocess_translated_text(unit, "Table of Contents") == "목차"
    assert service._postprocess_translated_text(
        replace(unit, original="User"),
        "Please provide the text you would like me to translate.",
    ) == "사용자"


def test_postprocess_translated_text_falls_back_for_suspicious_toc_spam() -> None:
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=7,
        label="list item",
        bbox=[39.425, 682.539, 256.152, 718.725],
        original="6.7 Applied Aerodynamics: Airplane Lift and Drag",
    )

    translated = service._postprocess_translated_text(
        unit,
        "정 피곤와 관련검색온라인어디서나수 있습다운로드 전자 Applied Aerodynamics: Airplane Lift and Drag ,가필니다.",
    )

    assert translated == "6.7 응용 공기역학: 비행기 양력과 항력"


def test_postprocess_translated_text_uses_fallback_for_untranslated_known_phrase() -> (
    None
):
    service = TranslationService(AppSettings())
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=7,
        label="list item",
        bbox=[280.125, 683.222, 406.427, 700.973],
        original="8.3.1 Comments",
    )

    translated = service._postprocess_translated_text(unit, "8.3.1 Comments")

    assert translated == "8.3.1 논평"


def test_postprocess_units_extracts_inline_page_number_from_numbered_paragraph() -> (
    None
):
    service = TranslationService(AppSettings())
    units = [
        TranslationUnit(
            unit_id="u00001",
            page_number=6,
            label="paragraph",
            bbox=[112.257, 547.294, 276.223, 573.541],
            original="4.5.1 Without Friction Could We Have Lift? 346",
            font_size=12.0,
            font_name="ArialMT",
        )
    ]

    processed = service._postprocess_units(units)

    assert len(processed) == 1
    assert processed[0].label == "list item"
    assert processed[0].original == "4.5.1 Without Friction Could We Have Lift?"
    assert processed[0].toc_page_number == "346"


def test_restore_source_rows_recovers_ruled_table_cells(tmp_path: Path) -> None:
    source_pdf = tmp_path / "ruled-table.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    for x in (40, 100, 160, 220):
        page.draw_line((x, 40), (x, 100))
    for y in (40, 70, 100):
        page.draw_line((40, y), (220, y))
    for text, point in (
        ("A", (50, 60)),
        ("B", (110, 60)),
        ("C", (170, 60)),
        ("1", (50, 90)),
        ("2", (110, 90)),
        ("3", (170, 90)),
    ):
        page.insert_text(point, text, fontsize=9)
    document.save(source_pdf)
    document.close()

    restored = TranslationService(AppSettings())._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="table",
                bbox=[40.0, 100.0, 220.0, 160.0],
                original="A B C 1 2 3",
                font_size=9.0,
            )
        ],
        source_pdf,
    )

    cells = [unit for unit in restored if unit.label.startswith("table ")]
    assert [unit.original for unit in cells] == ["A", "B", "C", "1", "2", "3"]
    assert len({tuple(unit.bbox) for unit in cells}) == 6
    assert max(abs(a - b) for a, b in zip(cells[0].bbox, [40, 130, 100, 160])) <= 1


def test_restore_source_rows_recovers_clipped_borderless_table(
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "borderless-table.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    for text, point in (
        ("Alpha", (50, 60)),
        ("One", (160, 60)),
        ("Beta", (50, 90)),
        ("Two", (160, 90)),
    ):
        page.insert_text(point, text, fontsize=9)
    document.save(source_pdf)
    document.close()

    restored = TranslationService(AppSettings())._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="table",
                bbox=[40.0, 90.0, 230.0, 160.0],
                original="Alpha One Beta Two",
                font_size=9.0,
            )
        ],
        source_pdf,
    )

    cells = [unit for unit in restored if unit.label.startswith("table ")]
    assert [unit.original for unit in cells] == ["Alpha", "One", "Beta", "Two"]
    assert len({tuple(unit.bbox) for unit in cells}) == 4


def test_restore_source_rows_does_not_treat_two_columns_as_a_table(
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "two-columns.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_textbox(fitz.Rect(30, 30, 130, 150), "Left body text\ncontinues here")
    page.insert_textbox(fitz.Rect(170, 30, 270, 150), "Right body text\ncontinues here")
    document.save(source_pdf)
    document.close()

    restored = TranslationService(AppSettings())._restore_source_rows(
        [
            TranslationUnit(
                unit_id="u00001",
                page_number=1,
                label="paragraph",
                bbox=[30.0, 50.0, 130.0, 170.0],
                original="Left body text continues here",
                font_size=11.0,
            ),
            TranslationUnit(
                unit_id="u00002",
                page_number=1,
                label="paragraph",
                bbox=[170.0, 50.0, 270.0, 170.0],
                original="Right body text continues here",
                font_size=11.0,
            ),
        ],
        source_pdf,
    )

    assert not any(unit.label.startswith("table ") for unit in restored)


def test_table_literals_bypass_translation_without_preserving_prose() -> None:
    class _Translator:
        def __init__(self) -> None:
            self.calls = 0

        def translate(self, text: str, *, target_language: str, model: str) -> str:
            _ = text, target_language, model
            self.calls += 1
            return "정확도가 개선됩니다"

    service = TranslationService(AppSettings())
    translator = _Translator()
    for original in ("42", "1.25", "50%", "x = y + 1"):
        unit = TranslationUnit(
            unit_id="u00001",
            page_number=1,
            label="table cell",
            bbox=[0.0, 0.0, 100.0, 20.0],
            original=original,
        )
        assert service._translate_unit_text(
            translator,
            unit,
            target_language="Korean",
            model="local",
        ) == original

    prose = replace(unit, original="Model 1 improves accuracy")
    assert service._translate_unit_text(
        translator,
        prose,
        target_language="Korean",
        model="local",
    ) == "정확도가 개선됩니다"
    assert translator.calls == 1
