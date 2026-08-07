from __future__ import annotations

from pathlib import Path


def test_protection_service_module_exists() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "openpdf2zh"
        / "services"
        / "protection_service.py"
    )
    assert module_path.is_file()


def _make_run(text: str):
    from openpdf2zh.document.ir import DocumentRun, TextStyle

    char_bboxes = [
        [float(index * 5), 0.0, float((index + 1) * 5), 10.0]
        for index in range(len(text))
    ]
    return DocumentRun(
        run_id="r000001",
        kind="text",
        text=text,
        bbox=[0.0, 0.0, float(max(len(text), 1) * 5), 10.0],
        char_bboxes=char_bboxes,
        style=TextStyle(font_name="Times-Roman", font_size=11.0, color=0),
    )


def test_protection_splits_inline_assignment_formula_without_text_loss() -> None:
    from openpdf2zh.services.protection_service import ProtectionService

    run = _make_run("The relation Cp = (p-p∞)/q∞ is used here.")
    protected = ProtectionService().protect_run(run)

    assert "".join(part.text for part in protected) == run.text
    formula = next(part for part in protected if part.kind == "formula")
    assert formula.text == "Cp = (p-p∞)/q∞"
    assert formula.translatable is False
    assert formula.protection_reason == "formula"
    assert len(formula.char_bboxes) == len(formula.text)
    assert all(part.translatable for part in protected if part.kind == "text")


def test_protection_marks_urls_dois_emails_and_citations() -> None:
    from openpdf2zh.services.protection_service import ProtectionService

    text = (
        "See https://example.com/a, doi:10.1000/xyz123, "
        "mail test@example.com and Eq. (3.14) [12]."
    )
    protected = ProtectionService().protect_run(_make_run(text))
    reasons = {part.protection_reason for part in protected if not part.translatable}

    assert {"url", "doi", "email", "citation"}.issubset(reasons)
    assert "".join(part.text for part in protected) == text


def test_protection_marks_standalone_math_like_run() -> None:
    from openpdf2zh.services.protection_service import ProtectionService

    run = _make_run("ρVL / μ")
    protected = ProtectionService().protect_run(run)

    assert len(protected) == 1
    assert protected[0].kind == "formula"
    assert protected[0].translatable is False


def test_protection_leaves_plain_sentence_translatable() -> None:
    from openpdf2zh.services.protection_service import ProtectionService

    run = _make_run("The boundary layer becomes turbulent downstream.")
    protected = ProtectionService().protect_run(run)

    assert len(protected) == 1
    assert protected[0].text == run.text
    assert protected[0].translatable is True
    assert protected[0].protection_reason == ""
