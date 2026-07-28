"""多尺度和旋转尺度模板匹配共享实现。"""

from __future__ import annotations

import math
from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import build_regions_payload
from backend.nodes.core_nodes.support.roi import bbox_to_polygon_xy
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.template_match import (
    _normalize_score_map,
    _resolve_match_method,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.search_roi import resolve_search_roi


def handle_scaled_template_match(request: Any, *, include_rotation: bool) -> dict[str, object]:
    """执行尺度或旋转尺度模板搜索。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, source = load_image_matrix(request, input_name="image")
    _, _, template = load_image_matrix(request, input_name="template_image")
    source_gray = ensure_gray(source, cv2_module=cv2_module)
    template_gray = ensure_gray(template, cv2_module=cv2_module)
    search_roi = resolve_search_roi(request, image_matrix=source_gray)
    search = search_roi.image_matrix
    search_bbox = search_roi.bbox_xyxy or [0, 0, int(source.shape[1]), int(source.shape[0])]
    scale_min = read_float(request.parameters.get("scale_min"), field_name="scale_min", default=0.8, minimum=0.05)
    scale_max = read_float(request.parameters.get("scale_max"), field_name="scale_max", default=1.2, minimum=0.05)
    scale_step = read_float(request.parameters.get("scale_step"), field_name="scale_step", default=0.05, minimum=0.001)
    if scale_max < scale_min:
        raise InvalidRequestError("scale_max 不能小于 scale_min")
    angle_min = read_float(request.parameters.get("angle_min_deg"), field_name="angle_min_deg", default=-15.0)
    angle_max = read_float(request.parameters.get("angle_max_deg"), field_name="angle_max_deg", default=15.0)
    angle_step = read_float(request.parameters.get("angle_step_deg"), field_name="angle_step_deg", default=2.0, minimum=0.1)
    if angle_max < angle_min:
        raise InvalidRequestError("angle_max_deg 不能小于 angle_min_deg")
    score_threshold = read_float(
        request.parameters.get("score_threshold"),
        field_name="score_threshold",
        default=0.8,
        minimum=0.0,
        maximum=1.0,
    )
    max_matches = read_int(request.parameters.get("max_matches"), field_name="max_matches", default=1, minimum=1, maximum=200)
    nms_iou = read_float(
        request.parameters.get("nms_iou_threshold"),
        field_name="nms_iou_threshold",
        default=0.3,
        minimum=0.0,
        maximum=1.0,
    )
    method_name = str(request.parameters.get("method") or "ccoeff-normed").strip().lower()
    method = _resolve_match_method(method_name, cv2_module=cv2_module)

    scales = _float_range(scale_min, scale_max, scale_step)
    angles = _float_range(angle_min, angle_max, angle_step) if include_rotation else [0.0]
    if len(scales) * len(angles) > 2000:
        raise InvalidRequestError(
            "模板搜索组合数不能超过 2000",
            details={"scale_count": len(scales), "angle_count": len(angles)},
        )
    candidates: list[dict[str, object]] = []
    evaluated = 0
    for scale in scales:
        scaled_width = max(1, int(round(template_gray.shape[1] * scale)))
        scaled_height = max(1, int(round(template_gray.shape[0] * scale)))
        if scaled_width > search.shape[1] or scaled_height > search.shape[0]:
            continue
        scaled_template = cv2_module.resize(
            template_gray,
            (scaled_width, scaled_height),
            interpolation=cv2_module.INTER_AREA if scale < 1.0 else cv2_module.INTER_LINEAR,
        )
        for angle in angles:
            transformed = _rotate_template(scaled_template, angle, cv2_module=cv2_module, np_module=np_module)
            height, width = transformed.shape[:2]
            if width > search.shape[1] or height > search.shape[0]:
                continue
            raw_scores = cv2_module.matchTemplate(search, transformed, method)
            scores = _normalize_score_map(raw_result_map=raw_scores, method_name=method_name, np_module=np_module)
            evaluated += 1
            candidate_indices = np_module.argwhere(scores >= score_threshold)
            if candidate_indices.size == 0:
                continue
            candidate_scores = scores[candidate_indices[:, 0], candidate_indices[:, 1]]
            per_transform_limit = min(256, max_matches * 16)
            if candidate_indices.shape[0] > per_transform_limit:
                top_indices = np_module.argpartition(candidate_scores, -per_transform_limit)[-per_transform_limit:]
                candidate_indices = candidate_indices[top_indices]
                candidate_scores = candidate_scores[top_indices]
            for candidate_index in np_module.argsort(-candidate_scores).tolist():
                match_y = int(candidate_indices[candidate_index, 0])
                match_x = int(candidate_indices[candidate_index, 1])
                x = int(search_bbox[0] + match_x)
                y = int(search_bbox[1] + match_y)
                candidates.append(
                    {
                        "bbox_xyxy": [float(x), float(y), float(x + width), float(y + height)],
                        "score": float(candidate_scores[candidate_index]),
                        "scale": float(scale),
                        "angle_deg": float(angle),
                        "template_width": width,
                        "template_height": height,
                    }
                )
    selected: list[dict[str, object]] = []
    for candidate in sorted(candidates, key=lambda item: float(item["score"]), reverse=True):
        if any(_bbox_iou(candidate["bbox_xyxy"], item["bbox_xyxy"]) > nms_iou for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= max_matches:
            break
    region_items = []
    for index, candidate in enumerate(selected, start=1):
        bbox = candidate["bbox_xyxy"]
        region_items.append(
            {
                "region_id": f"template-{index}",
                "class_id": -1,
                "class_name": "rotation-scale-template" if include_rotation else "multi-scale-template",
                "score": round(float(candidate["score"]), 6),
                "bbox_xyxy": bbox,
                "polygon_xy": bbox_to_polygon_xy(bbox),
                "area": int(candidate["template_width"]) * int(candidate["template_height"]),
                "center_xy": [
                    round((float(bbox[0]) + float(bbox[2])) / 2.0, 4),
                    round((float(bbox[1]) + float(bbox[3])) / 2.0, 4),
                ],
                "scale": round(float(candidate["scale"]), 6),
                "angle_deg": round(float(candidate["angle_deg"]), 6),
            }
        )
    return {
        "regions": build_regions_payload(source_image=source_payload, selected_frame_index=None, items=region_items),
        "summary": build_value_payload(
            {
                "include_rotation": include_rotation,
                "scale_min": scale_min,
                "scale_max": scale_max,
                "scale_step": scale_step,
                "angle_min_deg": angle_min if include_rotation else 0.0,
                "angle_max_deg": angle_max if include_rotation else 0.0,
                "angle_step_deg": angle_step if include_rotation else 0.0,
                "evaluated_template_count": evaluated,
                "candidate_count": len(candidates),
                "match_count": len(region_items),
            }
        ),
    }


def _float_range(start: float, stop: float, step: float) -> list[float]:
    """构造包含末端的浮点序列，并限制搜索组合数量。"""

    count = int(math.floor((stop - start) / step + 1e-9)) + 1
    if count > 500:
        raise InvalidRequestError("模板搜索步数过多，单一维度不能超过 500")
    values = [start + index * step for index in range(max(1, count))]
    if values[-1] < stop - step * 1e-6:
        values.append(stop)
    return values


def _rotate_template(template: Any, angle_deg: float, *, cv2_module: Any, np_module: Any) -> Any:
    """旋转模板并扩展画布，避免裁掉边缘。"""

    if abs(angle_deg) < 1e-9:
        return template
    height, width = template.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2_module.getRotationMatrix2D(center, angle_deg, 1.0)
    cosine = abs(float(matrix[0, 0]))
    sine = abs(float(matrix[0, 1]))
    output_width = max(1, int(math.ceil(height * sine + width * cosine)))
    output_height = max(1, int(math.ceil(height * cosine + width * sine)))
    matrix[0, 2] += output_width / 2.0 - center[0]
    matrix[1, 2] += output_height / 2.0 - center[1]
    return cv2_module.warpAffine(
        template,
        matrix,
        (output_width, output_height),
        flags=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_CONSTANT,
        borderValue=0,
    )


def _bbox_iou(a: list[float], b: list[float]) -> float:
    """计算两个 bbox 的 IoU。"""

    x1, y1 = max(float(a[0]), float(b[0])), max(float(a[1]), float(b[1]))
    x2, y2 = min(float(a[2]), float(b[2])), min(float(a[3]), float(b[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    area_b = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0
