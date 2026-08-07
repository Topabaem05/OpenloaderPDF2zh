from __future__ import annotations

from pathlib import Path

import pytest

from openpdf2zh.translation.glossary import Glossary, GlossaryEntry


def test_glossary_csv_requires_source_target_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("term,value\na,b\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source,target"):
        Glossary.from_csv(path)


def test_glossary_csv_and_matching_are_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "terms.csv"
    path.write_text(
        "source,target\nboundary layer,경계층\nlift coefficient,양력 계수\n",
        encoding="utf-8",
    )
    glossary = Glossary.from_csv(path)

    mapping = glossary.mapping_for_text("The Boundary Layer changes the lift coefficient.")

    assert mapping == {
        "lift coefficient": "양력 계수",
        "boundary layer": "경계층",
    }


def test_glossary_prefers_longest_terms_first() -> None:
    glossary = Glossary(
        [
            GlossaryEntry("layer", "층"),
            GlossaryEntry("boundary layer", "경계층"),
        ]
    )

    matches = glossary.matches("boundary layer model")

    assert [entry.source for entry in matches] == ["boundary layer", "layer"]


def test_glossary_merge_can_prioritize_user_terms() -> None:
    automatic = Glossary([GlossaryEntry("drag", "저항")])
    user = Glossary([GlossaryEntry("drag", "항력")])

    merged = automatic.merge(user, prefer_other=True)

    assert merged.mapping_for_text("drag coefficient") == {"drag": "항력"}
