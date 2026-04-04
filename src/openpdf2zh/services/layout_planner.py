from __future__ import annotations

from collections.abc import Callable
import json
import subprocess
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings

PT_TO_PX = 96.0 / 72.0
PX_TO_PT = 72.0 / 96.0
MeasurementResult = dict[str, float | int | None | str]


@dataclass(slots=True)
class FitValidationResult:
    fits: bool
    actual_render_bbox: fitz.Rect | None
    top_delta_pt: float
    bottom_delta_pt: float
    used_scale: float
    spare_height: float


FitValidator = Callable[
    ["LayoutBlock", fitz.Rect, MeasurementResult], FitValidationResult
]


@dataclass(slots=True)
class LayoutBlock:
    element: dict[str, object]
    original_rect: fitz.Rect
    render_rect: fitz.Rect
    translated: str
    label: str
    font_size: float
    font_name: str
    font_family_css: str
    estimated_line_count: int
    line_height_pt: float
    letter_spacing_em: float | None
    toc_page_number: str


@dataclass(slots=True)
class PlannedLayoutBlock:
    block: LayoutBlock
    planned_rect: fitz.Rect
    actual_render_bbox: fitz.Rect | None = None
    pretext_line_count: int | None = None
    pretext_height_pt: float | None = None
    render_font_size_pt: float = 0.0
    render_line_height_pt: float = 0.0
    render_letter_spacing_em: float | None = None
    vertical_shift_pt: float = 0.0
    top_delta_pt: float = 0.0
    bottom_delta_pt: float = 0.0
    final_scale_used: float = 1.0
    layout_engine: str = "pretext"
    layout_fallback: str = "none"
    planner_candidate_reason: str = "none"
    post_render_overlap_pt: float = 0.0
    scale_hint: float = 1.0


@dataclass(slots=True)
class TypographyCandidate:
    request_id: str
    font_scale: float
    font_size_pt: float
    line_height_pt: float
    letter_spacing_em: float | None
    adjustment_reason: str


class PretextMeasurementClient:
    def __init__(
        self,
        helper_path: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        default_helper_dir = repo_root / "tools" / "pretext_layout_helper"
        if helper_path:
            configured_helper = Path(helper_path).expanduser().resolve()
            if configured_helper.is_dir():
                self.helper_dir = configured_helper
                self.helper_script = configured_helper / "measure.mjs"
            else:
                self.helper_script = configured_helper
                self.helper_dir = configured_helper.parent
        else:
            self.helper_dir = default_helper_dir
            self.helper_script = self.helper_dir / "measure.mjs"
        self.timeout_seconds = max(timeout_seconds, 1.0)

    def measure_batch(
        self,
        requests: list[dict[str, object]],
        *,
        render_font_path: str = "",
    ) -> dict[str, dict[str, float | int]]:
        if not requests:
            return {}
        if not self.helper_script.is_file():
            raise RuntimeError(
                f"Pretext helper script was not found: {self.helper_script}"
            )

        command, payload = self._build_helper_invocation(
            requests,
            render_font_path=render_font_path,
        )
        try:
            completed = subprocess.run(
                command,
                cwd=self.helper_dir,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Pretext helper timed out while measuring text. "
                "Increase OPENPDF2ZH_PRETEXT_HELPER_TIMEOUT_SECONDS or switch to Legacy."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                "Pretext helper could not start. Check the helper runtime and installation."
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                "Pretext helper could not measure text. "
                "Install the helper dependencies, then retry. "
                f"Detail: {detail or 'unknown helper error'}"
            )
        try:
            results = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Pretext helper returned invalid JSON output."
            ) from exc

        if not isinstance(results, dict):
            raise RuntimeError("Pretext helper returned an unexpected payload shape.")

        if "results" in results:
            raw_entries = results.get("results")
            if not isinstance(raw_entries, list):
                raise RuntimeError("Pretext helper response is missing a results list.")
            return self._normalize_python_results(raw_entries)
        return self._normalize_node_results(results)

    def _build_helper_invocation(
        self,
        requests: list[dict[str, object]],
        *,
        render_font_path: str,
    ) -> tuple[list[str], dict[str, object]]:
        suffix = self.helper_script.suffix.lower()
        if suffix == ".py":
            helper_items: list[dict[str, object]] = []
            for request in requests:
                request_id = str(request.get("request_id", "")).strip()
                if not request_id:
                    continue
                helper_items.append(
                    {
                        "id": request_id,
                        "text": str(request.get("text", "")),
                        "font_family": str(request.get("font_family_css", "sans-serif")),
                        "font_size_pt": float(request.get("font_size_px", 0.0))
                        * PX_TO_PT,
                        "line_height_pt": float(request.get("line_height_px", 0.0))
                        * PX_TO_PT,
                        "width_pt": float(request.get("max_width_px", 0.0)) * PX_TO_PT,
                        "letter_spacing_em": request.get("letter_spacing_em"),
                    }
                )
            return [sys.executable, str(self.helper_script)], {"items": helper_items}

        node_path = shutil.which("node")
        if node_path is None:
            raise RuntimeError(
                "Node.js runtime is required for the pretext helper. "
                "Install Node.js or switch the layout engine back to Legacy."
            )
        return [node_path, str(self.helper_script)], {
            "requests": requests,
            "render_font_path": render_font_path,
        }

    def _normalize_python_results(
        self,
        raw_entries: list[object],
    ) -> dict[str, dict[str, float | int]]:
        normalized: dict[str, dict[str, float | int]] = {}
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            request_id = str(entry.get("id", "")).strip()
            if not request_id:
                continue
            try:
                measured_height_pt = float(entry.get("measured_height_pt", 0.0))
            except (TypeError, ValueError):
                measured_height_pt = 0.0
            try:
                measured_line_count = int(entry.get("measured_line_count", 1))
            except (TypeError, ValueError):
                measured_line_count = 1
            normalized[request_id] = {
                "line_count": max(measured_line_count, 1),
                "height_px": round(measured_height_pt * PT_TO_PX, 3),
                "scale_hint": float(request_id.rsplit(":", 1)[-1]),
            }
        return normalized

    def _normalize_node_results(
        self,
        raw_results: dict[str, object],
    ) -> dict[str, dict[str, float | int]]:
        normalized: dict[str, dict[str, float | int]] = {}
        for request_id, entry in raw_results.items():
            if not isinstance(entry, dict):
                continue
            normalized[request_id] = {
                "line_count": max(int(entry.get("line_count", 1)), 1),
                "height_px": float(entry.get("height_px", 0.0)),
                "scale_hint": float(request_id.rsplit(":", 1)[-1]),
            }
        return normalized


class LayoutPlanner:
    def __init__(
        self,
        settings: AppSettings,
        *,
        measurement_client: PretextMeasurementClient | None = None,
    ) -> None:
        self.settings = settings
        self.measurement_client = measurement_client or PretextMeasurementClient(
            settings.pretext_helper_path,
            settings.pretext_helper_timeout_seconds,
        )

    def plan_page(
        self,
        blocks: list[LayoutBlock],
        *,
        render_font_path: str = "",
        fit_validator: FitValidator | None = None,
    ) -> list[PlannedLayoutBlock]:
        if not blocks:
            return []

        paragraph_blocks = [block for block in blocks if self._uses_pretext(block)]
        measurements, candidate_ids_by_block = self._measure_candidates(
            paragraph_blocks,
            render_font_path,
        )
        planned: list[PlannedLayoutBlock] = []

        for cluster in self._build_clusters(blocks):
            cluster_bottom = max(block.render_rect.y1 for block in cluster)
            previous_bottom: float | None = None
            previous_actual_rect: fitz.Rect | None = None

            for block in cluster:
                gap = self._gap_height(block)
                target_y0 = block.render_rect.y0
                if previous_bottom is not None:
                    target_y0 = max(target_y0, previous_bottom + gap)

                if self._uses_pretext(block):
                    measurement, fallback, fit_result = self._select_measurement(
                        block,
                        measurements,
                        candidate_ids_by_block.get(id(block), []),
                        cluster_bottom - target_y0,
                        target_y0=target_y0,
                        fit_validator=fit_validator,
                    )
                    target_height = max(
                        block.render_rect.height,
                        (measurement["height_pt"] or 0.0) + self._safety_margin(block),
                    )
                    pretext_line_count = int(measurement["line_count"])
                    pretext_height_pt = float(measurement["height_pt"])
                    scale_hint = float(measurement["font_scale"])
                    render_font_size_pt = float(measurement["font_size_pt"])
                    render_line_height_pt = float(measurement["line_height_pt"])
                    render_letter_spacing_em = measurement["letter_spacing_em"]
                    actual_render_bbox = (
                        fitz.Rect(fit_result.actual_render_bbox)
                        if fit_result.actual_render_bbox is not None
                        else None
                    )
                    top_delta_pt = fit_result.top_delta_pt
                    bottom_delta_pt = fit_result.bottom_delta_pt
                    final_scale_used = fit_result.used_scale
                    planner_candidate_reason = str(
                        measurement.get("adjustment_reason", "none")
                    )
                else:
                    target_height = block.render_rect.height
                    pretext_line_count = None
                    pretext_height_pt = None
                    scale_hint = 1.0
                    render_font_size_pt = block.font_size
                    render_line_height_pt = block.line_height_pt
                    render_letter_spacing_em = block.letter_spacing_em
                    fallback = "toc_passthrough" if block.toc_page_number else "legacy_passthrough"
                    actual_render_bbox = None
                    top_delta_pt = 0.0
                    bottom_delta_pt = 0.0
                    final_scale_used = 1.0
                    planner_candidate_reason = "none"

                planned_rect = fitz.Rect(
                    block.render_rect.x0,
                    target_y0,
                    block.render_rect.x1,
                    target_y0 + max(target_height, 1.0),
                )
                if actual_render_bbox is None:
                    actual_render_bbox = fitz.Rect(planned_rect)
                post_render_overlap_pt = 0.0
                if previous_actual_rect is not None:
                    overlap = self._vertical_overlap(previous_actual_rect, actual_render_bbox)
                    if overlap > 0 and self._uses_pretext(block):
                        post_render_overlap_pt = round(overlap, 3)
                        shifted_y0 = target_y0 + overlap + gap
                        shifted_available_height = cluster_bottom - shifted_y0
                        if shifted_available_height >= 1.0:
                            shifted_fit = self._revalidate_shifted_candidate(
                                block,
                                measurement,
                                target_height,
                                shifted_y0,
                                fit_validator,
                            )
                            if (
                                shifted_fit is not None
                                and shifted_fit.actual_render_bbox is not None
                                and shifted_fit.actual_render_bbox.y1
                                <= cluster_bottom + 0.01
                            ):
                                planned_rect = fitz.Rect(
                                    block.render_rect.x0,
                                    shifted_y0,
                                    block.render_rect.x1,
                                    shifted_y0 + max(target_height, 1.0),
                                )
                                actual_render_bbox = fitz.Rect(
                                    shifted_fit.actual_render_bbox
                                )
                                top_delta_pt = shifted_fit.top_delta_pt
                                bottom_delta_pt = shifted_fit.bottom_delta_pt
                                final_scale_used = shifted_fit.used_scale
                                post_render_overlap_pt = 0.0
                                fallback = (
                                    fallback
                                    if fallback != "none"
                                    else "postpass_shift"
                                )
                        if post_render_overlap_pt > 0:
                            fallback = "postpass_overlap_overflow"
                            actual_render_bbox = None
                if actual_render_bbox is not None:
                    previous_bottom = actual_render_bbox.y1
                    previous_actual_rect = fitz.Rect(actual_render_bbox)
                planned.append(
                    PlannedLayoutBlock(
                        block=block,
                        planned_rect=planned_rect,
                        actual_render_bbox=actual_render_bbox,
                        pretext_line_count=pretext_line_count,
                        pretext_height_pt=pretext_height_pt,
                        render_font_size_pt=render_font_size_pt,
                        render_line_height_pt=render_line_height_pt,
                        render_letter_spacing_em=render_letter_spacing_em,
                        vertical_shift_pt=round(target_y0 - block.render_rect.y0, 3),
                        top_delta_pt=round(top_delta_pt, 3),
                        bottom_delta_pt=round(bottom_delta_pt, 3),
                        final_scale_used=round(final_scale_used, 3),
                        layout_engine="pretext",
                        layout_fallback=fallback,
                        planner_candidate_reason=planner_candidate_reason,
                        post_render_overlap_pt=post_render_overlap_pt,
                        scale_hint=scale_hint,
                    )
                )

        return planned

    def _measure_candidates(
        self,
        blocks: list[LayoutBlock],
        render_font_path: str,
    ) -> tuple[dict[str, dict[str, float | int | None | str]], dict[int, list[str]]]:
        requests: list[dict[str, object]] = []
        candidate_ids_by_block: dict[int, list[str]] = {}
        for block in blocks:
            candidate_ids_by_block[id(block)] = []
            for index, candidate in enumerate(self._iter_candidates(block)):
                request_id = self._request_id_for_block(block, index)
                candidate_ids_by_block[id(block)].append(request_id)
                requests.append(
                    {
                        "request_id": request_id,
                        "text": block.translated,
                        "font_family_css": block.font_family_css,
                        "font_size_px": round(candidate.font_size_pt * PT_TO_PX, 3),
                        "line_height_px": round(
                            candidate.line_height_pt * PT_TO_PX,
                            3,
                        ),
                        "max_width_px": round(block.render_rect.width * PT_TO_PX, 3),
                        "letter_spacing_em": candidate.letter_spacing_em,
                        "font_scale": candidate.font_scale,
                        "font_size_pt": candidate.font_size_pt,
                        "line_height_pt": candidate.line_height_pt,
                        "adjustment_reason": candidate.adjustment_reason,
                    }
                )
        raw_results = self.measurement_client.measure_batch(
            requests,
            render_font_path=render_font_path,
        )
        normalized: dict[str, dict[str, float | int | None | str]] = {}
        for request in requests:
            request_id = str(request["request_id"])
            result = raw_results.get(request_id)
            if result is None:
                raise RuntimeError(
                    f"Pretext helper did not return a measurement for request {request_id}."
                )
            if "height_pt" in result:
                height_pt = float(result.get("height_pt", 0.0))
            else:
                height_px = float(result.get("height_px", 0.0))
                height_pt = height_px * PX_TO_PT
            normalized[request_id] = {
                "line_count": max(int(result.get("line_count", 1)), 1),
                "height_pt": round(height_pt, 3),
                "font_scale": float(request.get("font_scale", 1.0)),
                "font_size_pt": float(request.get("font_size_pt", 0.0)),
                "line_height_pt": float(request.get("line_height_pt", 0.0)),
                "letter_spacing_em": request.get("letter_spacing_em"),
                "adjustment_reason": str(request.get("adjustment_reason", "none")),
            }
        return normalized, candidate_ids_by_block

    def _select_measurement(
        self,
        block: LayoutBlock,
        measurements: dict[str, MeasurementResult],
        candidate_ids: list[str],
        available_height: float,
        *,
        target_y0: float,
        fit_validator: FitValidator | None = None,
    ) -> tuple[MeasurementResult, str, FitValidationResult]:
        last_measurement: MeasurementResult | None = None
        last_fit_result: FitValidationResult | None = None
        probe_blocked = False
        for request_id in candidate_ids:
            measurement = measurements[request_id]
            last_measurement = measurement
            required_height = float(measurement["height_pt"]) + self._safety_margin(block)
            target_height = max(block.render_rect.height, required_height)
            if target_height > available_height:
                continue
            candidate_rect = fitz.Rect(
                block.render_rect.x0,
                target_y0,
                block.render_rect.x1,
                target_y0 + max(target_height, 1.0),
            )
            if fit_validator is not None:
                fit_result = fit_validator(block, candidate_rect, measurement)
                if isinstance(fit_result, bool):
                    fit_result = FitValidationResult(
                        fits=fit_result,
                        actual_render_bbox=fitz.Rect(candidate_rect) if fit_result else None,
                        top_delta_pt=0.0,
                        bottom_delta_pt=0.0,
                        used_scale=1.0,
                        spare_height=0.0 if fit_result else -1.0,
                    )
            else:
                fit_result = FitValidationResult(
                    fits=True,
                    actual_render_bbox=fitz.Rect(candidate_rect),
                    top_delta_pt=0.0,
                    bottom_delta_pt=0.0,
                    used_scale=1.0,
                    spare_height=max(candidate_rect.height - required_height, 0.0),
                )
            last_fit_result = fit_result
            # A candidate is only safe when both the pretext height budget and
            # a real PyMuPDF dry-run fit agree that it will render without spill.
            if not fit_result.fits or fit_result.actual_render_bbox is None:
                probe_blocked = True
                continue
            if fit_result.actual_render_bbox.y1 > (target_y0 + available_height + 0.01):
                probe_blocked = True
                continue
            return measurement, str(measurement["adjustment_reason"]), fit_result
        if last_measurement is None:
            return {
                "line_count": 1,
                "height_pt": block.render_rect.height,
                "font_scale": 1.0,
                "font_size_pt": block.font_size,
                "line_height_pt": block.line_height_pt,
                "letter_spacing_em": block.letter_spacing_em,
                "adjustment_reason": "none",
            }, (
                "pymupdf_probe_overflow" if probe_blocked else "planner_overflow"
            ), FitValidationResult(
                fits=False,
                actual_render_bbox=None,
                top_delta_pt=0.0,
                bottom_delta_pt=0.0,
                used_scale=0.0,
                spare_height=-1.0,
            )
        return last_measurement, (
            "pymupdf_probe_overflow" if probe_blocked else "planner_overflow"
        ), (
            last_fit_result
            or FitValidationResult(
                fits=False,
                actual_render_bbox=None,
                top_delta_pt=0.0,
                bottom_delta_pt=0.0,
                used_scale=0.0,
                spare_height=-1.0,
            )
        )

    def _revalidate_shifted_candidate(
        self,
        block: LayoutBlock,
        measurement: MeasurementResult,
        target_height: float,
        target_y0: float,
        fit_validator: FitValidator | None,
    ) -> FitValidationResult | None:
        if fit_validator is None:
            candidate_rect = fitz.Rect(
                block.render_rect.x0,
                target_y0,
                block.render_rect.x1,
                target_y0 + max(target_height, 1.0),
            )
            return FitValidationResult(
                fits=True,
                actual_render_bbox=candidate_rect,
                top_delta_pt=0.0,
                bottom_delta_pt=0.0,
                used_scale=1.0,
                spare_height=max(candidate_rect.height - float(measurement["height_pt"]), 0.0),
            )
        candidate_rect = fitz.Rect(
            block.render_rect.x0,
            target_y0,
            block.render_rect.x1,
            target_y0 + max(target_height, 1.0),
        )
        fit_result = fit_validator(block, candidate_rect, measurement)
        if isinstance(fit_result, bool):
            return FitValidationResult(
                fits=fit_result,
                actual_render_bbox=fitz.Rect(candidate_rect) if fit_result else None,
                top_delta_pt=0.0,
                bottom_delta_pt=0.0,
                used_scale=1.0,
                spare_height=0.0 if fit_result else -1.0,
            )
        return fit_result

    def _vertical_overlap(self, upper: fitz.Rect, lower: fitz.Rect) -> float:
        return min(upper.y1, lower.y1) - max(upper.y0, lower.y0)

    def _build_clusters(self, blocks: list[LayoutBlock]) -> list[list[LayoutBlock]]:
        clusters: list[list[LayoutBlock]] = []
        anchors: list[fitz.Rect] = []
        ordered = sorted(blocks, key=lambda block: (block.render_rect.x0, block.render_rect.y0))

        for block in ordered:
            assigned = False
            for index, anchor in enumerate(anchors):
                if self._same_column(block.render_rect, anchor):
                    clusters[index].append(block)
                    assigned = True
                    break
            if not assigned:
                clusters.append([block])
                anchors.append(block.render_rect)

        for cluster in clusters:
            cluster.sort(key=lambda block: (block.render_rect.y0, block.render_rect.x0))
        clusters.sort(key=lambda cluster: (cluster[0].render_rect.x0, cluster[0].render_rect.y0))
        return clusters

    def _same_column(self, rect: fitz.Rect, anchor: fitz.Rect) -> bool:
        overlap = min(rect.x1, anchor.x1) - max(rect.x0, anchor.x0)
        min_width = max(min(rect.width, anchor.width), 1.0)
        if overlap / min_width >= 0.55:
            return True
        tolerance = max(12.0, min_width * 0.18)
        return (
            abs(rect.x0 - anchor.x0) <= tolerance
            and abs(rect.x1 - anchor.x1) <= tolerance
        )

    def _uses_pretext(self, block: LayoutBlock) -> bool:
        return (
            not block.toc_page_number
            and block.label.strip().lower()
            in {"paragraph", "list item", "heading", "caption"}
        )

    def _scale_hints(self, font_size: float) -> list[float]:
        scale_hints = [1.0]
        if font_size >= 16.0:
            scale_hints.extend([0.96, 0.92, 0.86, 0.82, 0.74, 0.68])
        elif font_size <= 11.5:
            scale_hints.extend([0.96, 0.92, 0.86, 0.82, 0.74, 0.68])
        else:
            scale_hints.extend([0.96, 0.92, 0.88, 0.82, 0.76, 0.68, 0.62])
        unique: list[float] = []
        for value in scale_hints:
            rounded = round(value, 3)
            if rounded not in unique:
                unique.append(rounded)
        return unique

    def _iter_candidates(self, block: LayoutBlock) -> list[TypographyCandidate]:
        base_letter_spacing = (
            float(block.letter_spacing_em)
            if block.letter_spacing_em is not None
            else 0.0
        )
        letter_spacing_values: list[float | None] = [
            block.letter_spacing_em if block.letter_spacing_em is not None else None
        ]
        for delta in (0.02, 0.04, 0.06, 0.08, 0.1, 0.12, 0.16, 0.2):
            tightened = round(max(base_letter_spacing - delta, -0.22), 3)
            candidate_value: float | None = tightened
            if abs(tightened) < 0.005:
                candidate_value = None
            if candidate_value not in letter_spacing_values:
                letter_spacing_values.append(candidate_value)

        base_line_height_pt = max(block.line_height_pt, round(block.font_size * 1.02, 3))
        line_height_ratios = [1.0, 0.96, 0.92, 0.88, 0.84, 0.8]
        candidates: list[tuple[float, TypographyCandidate]] = []
        seen: set[tuple[float, float, float | None]] = set()
        for scale_hint in self._scale_hints(block.font_size):
            scaled_font_size = round(block.font_size * scale_hint, 3)
            for line_ratio in line_height_ratios:
                scaled_line_height = round(
                    max(
                        scaled_font_size * 1.02,
                        base_line_height_pt * scale_hint * line_ratio,
                    ),
                    3,
                )
                for letter_spacing in letter_spacing_values:
                    candidate_key = (
                        scaled_font_size,
                        scaled_line_height,
                        letter_spacing,
                    )
                    if candidate_key in seen:
                        continue
                    seen.add(candidate_key)
                    adjustment_reason = self._candidate_reason(
                        block,
                        scale_hint,
                        scaled_line_height,
                        letter_spacing,
                    )
                    letter_penalty = abs((letter_spacing or 0.0) - base_letter_spacing)
                    line_penalty = max(
                        0.0,
                        (base_line_height_pt * scale_hint) - scaled_line_height,
                    )
                    scale_penalty = (1.0 - scale_hint) * 100.0
                    cost = (
                        scale_penalty * 10.0
                        + line_penalty * 4.0
                        + letter_penalty * 25.0
                    )
                    candidates.append(
                        (
                            round(cost, 6),
                            TypographyCandidate(
                                request_id="",
                                font_scale=scale_hint,
                                font_size_pt=scaled_font_size,
                                line_height_pt=scaled_line_height,
                                letter_spacing_em=letter_spacing,
                                adjustment_reason=adjustment_reason,
                            ),
                        )
                    )
        candidates.sort(key=lambda item: item[0])
        return [
            TypographyCandidate(
                request_id="",
                font_scale=item.font_scale,
                font_size_pt=item.font_size_pt,
                line_height_pt=item.line_height_pt,
                letter_spacing_em=item.letter_spacing_em,
                adjustment_reason=item.adjustment_reason,
            )
            for _, item in candidates
        ]

    def _candidate_reason(
        self,
        block: LayoutBlock,
        font_scale: float,
        line_height_pt: float,
        letter_spacing_em: float | None,
    ) -> str:
        reasons: list[str] = []
        if font_scale < 0.999:
            reasons.append("font_scale")
        baseline_line_height = block.line_height_pt * font_scale
        if line_height_pt < baseline_line_height - 0.01:
            reasons.append("line_height")
        if abs((letter_spacing_em or 0.0) - (block.letter_spacing_em or 0.0)) >= 0.005:
            reasons.append("letter_spacing")
        return "+".join(reasons) or "none"

    def _gap_height(self, block: LayoutBlock) -> float:
        return max(1.0, round(block.line_height_pt * 0.12, 3))

    def _safety_margin(self, block: LayoutBlock) -> float:
        return max(1.0, round(block.line_height_pt * 0.08, 3))

    def _request_id(self, index: int, candidate_index: int) -> str:
        return f"{index}:{candidate_index:03d}"

    def _request_id_for_block(self, block: LayoutBlock, candidate_index: int) -> str:
        return self._request_id(id(block), candidate_index)
