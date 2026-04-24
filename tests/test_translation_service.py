from __future__ import annotations

from openpdf2zh.config import AppSettings
from openpdf2zh.models import TranslationUnit
from openpdf2zh.services.translation_service import TranslationService


def test_sanitize_translated_text_collapses_spaced_single_token_repetition() -> None:
    service = TranslationService(AppSettings())

    sanitized = service._sanitize_translated_text("T T T T T T T T")

    assert sanitized == "T"


def test_sanitize_translated_text_collapses_repeated_fragment_repetition() -> None:
    service = TranslationService(AppSettings())

    sanitized = service._sanitize_translated_text(
        "소용소용소용소용소용소용소용"
    )

    assert sanitized == "소용"


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


def test_postprocess_translated_text_uses_fallback_for_untranslated_known_phrase() -> None:
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


def test_postprocess_units_extracts_inline_page_number_from_numbered_paragraph() -> None:
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
