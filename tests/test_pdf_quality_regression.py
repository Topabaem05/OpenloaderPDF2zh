from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.helpers.pdf_factory import (
    make_colored_background_pdf,
    make_figure_pdf,
    make_formula_pdf,
    make_link_pdf,
    make_two_column_pdf,
    make_vector_table_pdf,
)


def _load_inspector_module():
    path = Path(__file__).parents[1] / "tools" / "quality" / "inspect_pdf.py"
    spec = importlib.util.spec_from_file_location("inspect_pdf_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_quality_inspector_exposes_inspect_pdf() -> None:
    module = _load_inspector_module()
    assert hasattr(module, "inspect_pdf")


def test_quality_inspector_counts_pdf_objects(tmp_path: Path) -> None:
    module = _load_inspector_module()
    source = make_vector_table_pdf(tmp_path / "table.pdf")
    snapshot = module.inspect_pdf(source)

    assert snapshot.page_count == 1
    assert snapshot.drawing_count >= 6
    assert snapshot.text_block_count >= 1


def test_quality_inspector_tracks_images_and_links(tmp_path: Path) -> None:
    module = _load_inspector_module()
    figure = module.inspect_pdf(make_figure_pdf(tmp_path / "figure.pdf"))
    linked = module.inspect_pdf(make_link_pdf(tmp_path / "link.pdf"))

    assert figure.image_count == 1
    assert len(figure.image_digests) == 1
    assert linked.link_count == 1
    assert "https://openai.com/" in linked.links


def test_quality_inspector_tracks_protected_text(tmp_path: Path) -> None:
    module = _load_inspector_module()
    source = make_formula_pdf(tmp_path / "formula.pdf")
    snapshot = module.inspect_pdf(source, protected_text=["Cp = (p-p0)/q0"])

    assert snapshot.protected_text == ["Cp = (p-p0)/q0"]


def test_regression_corpus_builds_expected_document_types(tmp_path: Path) -> None:
    builders = [
        make_two_column_pdf,
        make_formula_pdf,
        make_colored_background_pdf,
        make_vector_table_pdf,
    ]
    for index, builder in enumerate(builders):
        assert builder(tmp_path / f"fixture-{index}.pdf").is_file()
