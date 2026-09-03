from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.services.layout_planner import LayoutBlock
from openpdf2zh.services.render_service import RenderService


def _font_file(tmp_path: Path, name: str, glyph_source: str) -> Path:
    target = tmp_path / name
    target.write_bytes(Path(glyph_source).read_bytes())
    return target


def test_font_size_is_clamped_to_configured_range() -> None:
    settings = replace(
        AppSettings(),
        render_font_size_min=9.0,
        render_font_size_max=11.0,
    )
    service = RenderService(settings)

    def body(size: float) -> float:
        return service._resolve_font_size(
            {"font_size": size, "label": "paragraph"}, 10.0
        )

    # Parser labels are imperfect: cover titles can arrive as paragraphs. Display
    # sizes keep their hierarchy instead of being crushed to body text.
    assert body(67.0) == 67.0
    assert body(15.0) == 11.0
    assert body(10.5) == 10.5
    # Source text that is genuinely smaller than the minimum (imprint pages, ISBN
    # lines) is left alone so it still fits its original box.
    assert body(7.0) == 7.0

    # Headings carry the visual hierarchy and are never clamped.
    assert (
        service._resolve_font_size({"font_size": 31.5, "label": "heading"}, 10.0)
        == 31.5
    )
    # No range configured keeps the original behaviour.
    assert (
        RenderService(AppSettings())._resolve_font_size(
            {"font_size": 67.0, "label": "paragraph"}, 10.0
        )
        == 67.0
    )


def test_line_height_never_falls_below_the_render_glyph_box() -> None:
    cjk = Path("/Users/guribbong/Library/Fonts/KoPubWorld Batang Light.ttf")
    if not cjk.is_file():  # pragma: no cover - user font
        return

    service = RenderService(replace(AppSettings(), render_cjk_font_path=str(cjk)))
    # KoPubWorld Batang spans ~1.54em, so a source line height of 11.5pt at 10.5pt
    # would overlap the next line.
    resolved = service._resolve_line_height_pt({"line_height_pt": 11.5}, 10.5)
    assert resolved is not None and resolved >= 10.5 * 1.5

    # A generous source line height is preserved as-is.
    assert service._resolve_line_height_pt({"line_height_pt": 40.0}, 10.5) == 40.0


def test_line_height_uses_configured_font_metrics_instead_of_fixed_padding() -> None:
    latin = Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf")
    cjk = Path("/Users/guribbong/Library/Fonts/BookkMyungjo_Light.ttf")
    if not latin.is_file() or not cjk.is_file():  # pragma: no cover - user fonts
        return

    service = RenderService(
        replace(
            AppSettings(),
            render_font_path=str(latin),
            render_cjk_font_path=str(cjk),
        )
    )

    assert service._resolve_line_height_pt({"line_height_pt": 10.25}, 9.0) == 10.25


def test_cjk_runs_render_with_the_configured_cjk_font(tmp_path: Path) -> None:
    latin = Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf")
    cjk = Path("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf")
    if not latin.is_file() or not cjk.is_file():  # pragma: no cover - platform fonts
        return

    settings = replace(
        AppSettings(),
        render_font_path=str(latin),
        render_cjk_font_path=str(cjk),
    )
    service = RenderService(settings)
    css, archive, family = service._build_render_resources()
    assert family == "customrenderfont"

    html_block = service._build_html(
        "Linux kernel 시스템 관리자",
        "paragraph",
        10.0,
        family,
        "MinionPro-Regular",
        1,
        12.0,
        None,
    )
    assert RenderService.CJK_FONT_FAMILY in html_block
    assert "white-space: nowrap" in html_block
    assert (
        RenderService.CJK_FONT_FAMILY
        in service._resolve_measurement_font_family_css(
            family,
            "MinionPro-Regular",
        )
    )

    document = fitz.open()
    page = document.new_page()
    page.insert_htmlbox(
        fitz.Rect(40, 40, 400, 160),
        html_block,
        css=css,
        archive=archive,
    )
    embedded = {entry[3] for entry in page.get_fonts()}
    assert any("Times New Roman" in name for name in embedded)
    assert not any("Droid Sans" in name for name in embedded)
    document.close()


def test_inline_url_moves_as_one_run_when_it_fits_the_column() -> None:
    service = RenderService(AppSettings())
    url = "https://oreil.ly/practical-linux-system-admin-code"
    html_block = service._build_html(
        f"Location: {url}",
        "paragraph",
        10.0,
        None,
        "Helvetica",
        2,
        15.0,
        None,
    )
    plain_url_html = service._build_html(
        "Contact: corporate@oreilly.com or https://oreilly.com",
        "paragraph",
        10.0,
        None,
        "Helvetica",
        1,
        15.0,
        None,
    )

    document = fitz.open()
    page = document.new_page(width=400, height=300)
    spare_height, scale = page.insert_htmlbox(
        fitz.Rect(40, 40, 270, 260),
        html_block,
        scale_low=1.0,
    )
    lines: dict[tuple[int, int], list[str]] = {}
    for word in page.get_text("words"):
        lines.setdefault((word[5], word[6]), []).append(word[4])
    rendered_lines = [" ".join(lines[key]) for key in sorted(lines)]
    document.close()

    assert spare_height != -1 and scale == 1.0
    assert rendered_lines == ["Location:", url]
    assert "display: inline-block" not in plain_url_html


def test_planner_scale_hints_respect_the_font_size_floor() -> None:
    from openpdf2zh.services.layout_planner import (
        LayoutPlanner,
        PretextMeasurementClient,
    )

    class _NoopClient(PretextMeasurementClient):
        def __init__(self) -> None:  # pragma: no cover - never measures
            pass

    planner = LayoutPlanner(
        replace(AppSettings(), render_font_size_min=9.0),
        measurement_client=_NoopClient(),
    )
    hints = planner._scale_hints(10.0)
    assert min(hints) * 10.0 >= 9.0 - 1e-9
    assert 1.0 in hints

    # Without a floor the original hint ladder is preserved.
    unbounded = LayoutPlanner(AppSettings(), measurement_client=_NoopClient())
    assert min(unbounded._scale_hints(10.0)) < 0.7


def test_scale_policy_never_shrinks_below_the_font_size_floor() -> None:
    class _Page:
        def __init__(self) -> None:
            self.scales: list[float] = []

        def insert_htmlbox(self, rect, html_block, **kwargs):
            self.scales.append(kwargs["scale_low"])
            return -1.0, 0.0

    service = RenderService(replace(AppSettings(), render_font_size_min=9.0))
    page = _Page()
    spare, scale = service._insert_with_scale_policy(
        page, fitz.Rect(0, 0, 100, 20), "<div>x</div>", None, None, 11.0
    )
    assert spare == -1.0 and scale == 0.0
    assert page.scales, "at least one candidate must be attempted"
    assert min(page.scales) * 11.0 >= 9.0 - 1e-6
    assert 0.0 not in page.scales

    # Unbounded settings keep the legacy ladder, including the free-shrink candidate.
    unbounded_page = _Page()
    RenderService(AppSettings())._insert_with_scale_policy(
        unbounded_page, fitz.Rect(0, 0, 100, 20), "<div>x</div>", None, None, 11.0
    )
    assert 0.0 in unbounded_page.scales


def test_body_boxes_only_grow_when_a_cjk_font_is_configured() -> None:
    cjk = Path("/Users/guribbong/Library/Fonts/KoPubWorld Batang Light.ttf")
    source = fitz.Rect(0, 0, 200, 40)

    # No CJK font: the source box is used exactly, as before.
    assert RenderService(AppSettings())._resolve_render_rect(source, 10.5) == source

    if not cjk.is_file():  # pragma: no cover - user font
        return
    grown = RenderService(
        replace(AppSettings(), render_cjk_font_path=str(cjk))
    )._resolve_render_rect(source, 10.5)
    assert grown.y1 > source.y1
    assert (grown.x0, grown.y0, grown.x1) == (source.x0, source.y0, source.x1)
    # Growth stays bounded so a block cannot swallow the one below it.
    assert grown.y1 - source.y1 <= source.height * 0.5 + 1e-6

    heading = RenderService(AppSettings())._resolve_render_rect(source, 20.0)
    assert heading.y0 == source.y0
    assert heading.y1 > source.y1


def test_pretext_body_uses_source_box_and_bottom_footer_is_fixed() -> None:
    service = RenderService(AppSettings(render_layout_engine="pretext"))
    page = fitz.Rect(0, 0, 612, 792)
    body = service._plan_render_blocks(
        [
            (
                fitz.Rect(72, 100, 432, 160),
                "body",
                "paragraph",
                10.0,
                "",
                4,
                12.0,
                None,
                "",
                False,
            )
        ],
        "legacy",
        page,
        None,
        None,
        None,
    )[0]
    body.fixed_position = False
    assert service._resolve_pretext_render_rect(body) == body.original_rect

    display = service._plan_render_blocks(
        [
            (
                fitz.Rect(72, 100, 240, 130),
                "heading",
                "heading",
                20.0,
                "",
                1,
                24.0,
                None,
                "",
                False,
            )
        ],
        "legacy",
        page,
        None,
        None,
        None,
    )[0]
    display.fixed_position = False
    display_rect = service._resolve_pretext_render_rect(display)
    assert display_rect.height == display.original_rect.height
    assert display_rect.width > display.original_rect.width
    assert service._is_fixed_position(fitz.Rect(380, 760, 432, 772), page, 9.0)
    assert service._is_fixed_position(fitz.Rect(144, 714, 343, 730), page, 9.0)
    assert not service._is_fixed_position(fitz.Rect(72, 0, 432, 20), page, 10.0)


def test_unchanged_text_and_page_markers_keep_the_original_render() -> None:
    service = RenderService(AppSettings())
    page = fitz.Rect(0, 0, 504, 661.5)

    assert service._should_preserve_original(
        {"content": "Table of Contents"},
        "Table of Contents",
        fitz.Rect(72, 70, 432, 100),
        page,
        25.0,
        "",
    )
    assert service._should_preserve_original(
        {"content": "iii"},
        "III)",
        fitz.Rect(426, 610, 432, 621),
        page,
        9.0,
        "",
    )
    assert service._should_preserve_original(
        {"content": "Table of Contents |"},
        "Table of Contents 를",
        fitz.Rect(357, 610, 432, 621),
        page,
        9.0,
        "v",
    )


def test_short_body_boxes_expand_to_their_column_width() -> None:
    service = RenderService(AppSettings())

    def block(text: str, rect: fitz.Rect) -> LayoutBlock:
        return LayoutBlock(
            element={},
            original_rect=fitz.Rect(rect),
            render_rect=fitz.Rect(rect),
            translated=text,
            label="list item",
            font_size=10.0,
            font_name="",
            font_family_css="serif",
            estimated_line_count=1,
            line_height_pt=12.0,
            letter_spacing_em=None,
            toc_page_number="",
        )

    short = block("short source", fitz.Rect(80, 100, 250, 114))
    full = block("full source", fitz.Rect(80, 120, 432, 134))
    service._expand_narrow_flow_blocks([short, full])

    assert short.render_rect.x1 == 432
    assert full.render_rect.x1 == 432

    left = block("left column", fitz.Rect(80, 160, 180, 200))
    right = block("right column", fitz.Rect(260, 160, 380, 200))
    wide = block("wide anchor", fitz.Rect(80, 145, 432, 158))
    service._expand_narrow_flow_blocks([wide, left, right])

    assert left.render_rect.x1 == 258


if __name__ == "__main__":
    test_font_size_is_clamped_to_configured_range()
    test_planner_scale_hints_respect_the_font_size_floor()
    test_scale_policy_never_shrinks_below_the_font_size_floor()
    test_cjk_runs_render_with_the_configured_cjk_font(Path("/tmp"))
    print("ok")
