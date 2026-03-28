from __future__ import annotations


def bbox_area(bbox: list[float]) -> float:
    left, bottom, right, top = _normalize_bbox(bbox)
    return max(right - left, 0.0) * max(top - bottom, 0.0)


def bbox_intersection_area(bbox_a: list[float], bbox_b: list[float]) -> float:
    left_a, bottom_a, right_a, top_a = _normalize_bbox(bbox_a)
    left_b, bottom_b, right_b, top_b = _normalize_bbox(bbox_b)

    overlap_left = max(left_a, left_b)
    overlap_bottom = max(bottom_a, bottom_b)
    overlap_right = min(right_a, right_b)
    overlap_top = min(top_a, top_b)

    if overlap_left >= overlap_right or overlap_bottom >= overlap_top:
        return 0.0

    return (overlap_right - overlap_left) * (overlap_top - overlap_bottom)


def bbox_iou(bbox_a: list[float], bbox_b: list[float]) -> float:
    area_a = bbox_area(bbox_a)
    area_b = bbox_area(bbox_b)
    intersection_area = bbox_intersection_area(bbox_a, bbox_b)
    if intersection_area <= 0:
        return 0.0

    union_area = area_a + area_b - intersection_area
    if union_area <= 0:
        return 0.0

    return intersection_area / union_area


def bbox_iom(bbox_a: list[float], bbox_b: list[float]) -> float:
    area_a = bbox_area(bbox_a)
    area_b = bbox_area(bbox_b)
    min_area = min(area_a, area_b)
    if min_area <= 0:
        return 0.0

    return bbox_intersection_area(bbox_a, bbox_b) / min_area


def bbox_overlap_ratio(bbox_a: list[float], bbox_b: list[float]) -> float:
    return bbox_iom(bbox_a, bbox_b)


def bbox_area_ratio(bbox_a: list[float], bbox_b: list[float]) -> float:
    area_a = bbox_area(bbox_a)
    area_b = bbox_area(bbox_b)
    max_area = max(area_a, area_b)
    if max_area <= 0:
        return 0.0

    return min(area_a, area_b) / max_area


def _normalize_bbox(bbox: list[float]) -> tuple[float, float, float, float]:
    left = min(float(bbox[0]), float(bbox[2]))
    right = max(float(bbox[0]), float(bbox[2]))
    bottom = min(float(bbox[1]), float(bbox[3]))
    top = max(float(bbox[1]), float(bbox[3]))
    return left, bottom, right, top
