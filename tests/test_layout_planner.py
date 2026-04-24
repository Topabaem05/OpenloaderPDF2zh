from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.services.layout_planner import (
    FitValidationResult,
    LayoutBlock,
    LayoutPlanner,
    PretextMeasurementClient,
    build_column_clusters,
)


class _FakeMeasurementClient:
    def measure_batch(
        self,
        requests: list[dict[str, object]],
        *,
        render_font_path: str = "",
    ) -> dict[str, dict[str, float | int]]:
        _ = render_font_path
        results: dict[str, dict[str, float | int]] = {}
        for request in requests:
            request_id = str(request.get("request_id", "")).strip()
            text = str(request.get("text", ""))
            height_px = 24.0
            if text == "Left top":
                height_px = 48.0
            elif text == "Left bottom":
                height_px = 18.0
            elif text == "Right top":
                height_px = 18.0
            results[request_id] = {
                "height_px": height_px,
                "line_count": 1,
            }
        return results


def _block(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> LayoutBlock:
    rect = fitz.Rect(x0, y0, x1, y1)
    return LayoutBlock(
        element={"translated": text},
        original_rect=rect,
        render_rect=fitz.Rect(rect),
        translated=text,
        label="paragraph",
        font_size=12.0,
        font_name="ArialMT",
        font_family_css="'ArialMT', sans-serif",
        estimated_line_count=1,
        line_height_pt=14.0,
        letter_spacing_em=None,
        toc_page_number="",
    )


def test_layout_planner_shifts_later_boxes_within_same_column_cluster() -> None:
    planner = LayoutPlanner(
        AppSettings(render_layout_engine="pretext"),
        measurement_client=_FakeMeasurementClient(),
    )

    planned = planner.plan_page(
        [
            _block("Left top", 10.0, 10.0, 110.0, 30.0),
            _block("Left bottom", 10.0, 24.0, 110.0, 44.0),
            _block("Right top", 150.0, 10.0, 250.0, 30.0),
        ]
    )

    by_text = {item.block.translated: item for item in planned}
    assert by_text["Left top"].planned_rect.y1 > by_text["Left top"].block.original_rect.y1
    assert by_text["Left bottom"].planned_rect.y0 >= by_text["Left top"].planned_rect.y1
    assert by_text["Right top"].planned_rect.y0 == by_text["Right top"].block.original_rect.y0
    assert by_text["Left bottom"].vertical_shift_pt > 0
    assert by_text["Right top"].vertical_shift_pt == 0


def test_build_column_clusters_supports_generic_rect_items() -> None:
    items = [
        {"name": "left-top", "rect": fitz.Rect(0.0, 0.0, 100.0, 20.0)},
        {"name": "left-bottom", "rect": fitz.Rect(0.0, 24.0, 100.0, 44.0)},
        {"name": "right-top", "rect": fitz.Rect(150.0, 0.0, 250.0, 20.0)},
    ]

    clusters = build_column_clusters(
        items,
        rect_getter=lambda item: item["rect"],
    )

    assert [[item["name"] for item in cluster] for cluster in clusters] == [
        ["left-top", "left-bottom"],
        ["right-top"],
    ]


def test_layout_planner_tightens_typography_when_height_budget_is_tight() -> None:
    class _PressureMeasurementClient:
        def measure_batch(self, requests, *, render_font_path: str = ""):
            _ = render_font_path
            results = {}
            for request in requests:
                request_id = str(request["request_id"])
                line_height_pt = float(request["line_height_px"]) * (72.0 / 96.0)
                letter_spacing_em = request.get("letter_spacing_em")
                spacing_bonus = 0.0
                if isinstance(letter_spacing_em, (int, float)) and letter_spacing_em < 0:
                    spacing_bonus = abs(float(letter_spacing_em)) * 8.0
                height_pt = max(12.0, (line_height_pt * 2.1) - spacing_bonus)
                results[request_id] = {
                    "line_count": max(int(round(height_pt / max(line_height_pt, 1.0))), 1),
                    "height_pt": round(height_pt, 3),
                }
            return results

    planner = LayoutPlanner(
        AppSettings(render_layout_engine="pretext"),
        measurement_client=_PressureMeasurementClient(),
    )

    planned = planner.plan_page(
        [
            _block("Crowded first block", 0.0, 0.0, 100.0, 18.0),
            _block("Following block", 0.0, 20.0, 100.0, 30.0),
        ]
    )

    first_block = next(item for item in planned if item.block.translated == "Crowded first block")
    assert first_block.layout_fallback != "planner_overflow"
    assert (
        first_block.render_line_height_pt < first_block.block.line_height_pt
        or (first_block.render_letter_spacing_em or 0.0) < (first_block.block.letter_spacing_em or 0.0)
    )


def test_layout_planner_uses_fit_validator_before_accepting_candidate() -> None:
    class _FlatMeasurementClient:
        def measure_batch(self, requests, *, render_font_path: str = ""):
            _ = render_font_path
            return {
                str(request["request_id"]): {
                    "line_count": 1,
                    "height_pt": 12.0,
                }
                for request in requests
            }

    planner = LayoutPlanner(
        AppSettings(render_layout_engine="pretext"),
        measurement_client=_FlatMeasurementClient(),
    )
    seen: list[tuple[float, float | None]] = []

    planned = planner.plan_page(
        [_block("Probe constrained block", 0.0, 0.0, 100.0, 40.0)],
        fit_validator=lambda _block, _rect, measurement: (
            seen.append(
                (
                    float(measurement["font_size_pt"]),
                    (
                        None
                        if measurement["letter_spacing_em"] is None
                        else float(measurement["letter_spacing_em"])
                    ),
                )
            )
            or (
                measurement["letter_spacing_em"] is not None
                and float(measurement["letter_spacing_em"]) < 0.0
            )
        ),
    )

    assert seen[0] == (12.0, None)
    assert planned[0].render_letter_spacing_em is not None
    assert planned[0].render_letter_spacing_em < 0.0
    assert planned[0].layout_fallback == "letter_spacing"


def test_layout_planner_uses_actual_render_bbox_bottom_for_following_block() -> None:
    class _FlatMeasurementClient:
        def measure_batch(self, requests, *, render_font_path: str = ""):
            _ = render_font_path
            return {
                str(request["request_id"]): {
                    "line_count": 1,
                    "height_pt": 12.0,
                }
                for request in requests
            }

    planner = LayoutPlanner(
        AppSettings(render_layout_engine="pretext"),
        measurement_client=_FlatMeasurementClient(),
    )

    def _fit_validator(block, rect, measurement):
        _ = measurement
        extra_bottom = 8.0 if block.translated == "top" else 0.0
        actual_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + extra_bottom)
        return FitValidationResult(
            fits=True,
            actual_render_bbox=actual_rect,
            top_delta_pt=0.0,
            bottom_delta_pt=extra_bottom,
            used_scale=1.0,
            spare_height=0.0,
        )

    planned = planner.plan_page(
        [
            _block("top", 0.0, 0.0, 100.0, 20.0),
            _block("bottom", 0.0, 20.0, 100.0, 40.0),
        ],
        fit_validator=_fit_validator,
    )

    by_text = {item.block.translated: item for item in planned}
    assert by_text["top"].bottom_delta_pt == 8.0
    assert (
        by_text["bottom"].planned_rect.y0
        >= by_text["top"].actual_render_bbox.y1 + 1.0
    )


def test_pretext_measurement_client_requires_helper_script(tmp_path: Path) -> None:
    client = PretextMeasurementClient(helper_path=str(tmp_path / "missing-helper"))

    with pytest.raises(RuntimeError, match="Pretext helper script was not found"):
        client.measure_batch(
            [
                {
                    "request_id": "request-1",
                    "text": "Example",
                    "font_family_css": "'ArialMT', sans-serif",
                    "font_size_px": 12.0,
                    "line_height_px": 14.0,
                    "max_width_px": 100.0,
                }
            ]
        )


def test_pretext_measurement_client_normalizes_node_helper_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_script = tmp_path / "measure.mjs"
    helper_script.write_text("export {};\n", encoding="utf-8")
    client = PretextMeasurementClient(helper_path=str(helper_script))

    class _CompletedProcess:
        returncode = 0
        stdout = json.dumps(
            {
                "request-1:1.000": {
                    "height_px": 28.5,
                    "line_count": 2,
                }
            }
        )
        stderr = ""

    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(str(kwargs["input"]))
        return _CompletedProcess()

    monkeypatch.setattr(
        "openpdf2zh.services.layout_planner.subprocess.run",
        _fake_run,
    )

    results = client.measure_batch(
        [
            {
                "request_id": "request-1:1.000",
                "text": "Example",
                "font_family_css": "'ArialMT', sans-serif",
                "font_size_px": 12.0,
                "line_height_px": 14.0,
                "max_width_px": 100.0,
                "letter_spacing_em": -0.1,
            }
        ],
        render_font_path="/tmp/font.ttf",
    )

    assert captured["command"][1] == str(helper_script)
    assert captured["payload"]["render_font_path"] == "/tmp/font.ttf"
    assert captured["payload"]["requests"][0]["request_id"] == "request-1:1.000"
    assert captured["payload"]["requests"][0]["letter_spacing_em"] == -0.1
    assert results["request-1:1.000"]["height_px"] == 28.5
    assert results["request-1:1.000"]["line_count"] == 2


def test_app_settings_reads_render_layout_engine_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENPDF2ZH_RENDER_LAYOUT_ENGINE", "pretext")

    settings = AppSettings.from_env()

    assert settings.render_layout_engine == "pretext"
