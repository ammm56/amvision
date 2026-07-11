"""Template Match 节点实现。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import build_regions_payload
from backend.nodes.core_nodes.support.roi import bbox_to_polygon_xy
from backend.nodes.debug_image_panel import (
    build_bbox_overlay,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_numeric_control,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    ResolvedSearchRoi,
    build_search_roi_overlay,
    build_search_roi_summary,
    clip_bbox_xyxy,
    resolve_search_roi,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.template-match"


def _read_match_method(raw_value: object) -> str:
    """读取模板匹配方法。"""

    if raw_value in {None, ""}:
        return "ccoeff-normed"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("method 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"ccoeff-normed", "ccorr-normed", "sqdiff-normed"}:
        raise InvalidRequestError("method 仅支持 ccoeff-normed、ccorr-normed 或 sqdiff-normed")
    return normalized_value


def _resolve_match_method(method_name: str, *, cv2_module: Any) -> int:
    """把方法名解析为 OpenCV matchTemplate 常量。"""

    if method_name == "ccoeff-normed":
        return cv2_module.TM_CCOEFF_NORMED
    if method_name == "ccorr-normed":
        return cv2_module.TM_CCORR_NORMED
    if method_name == "sqdiff-normed":
        return cv2_module.TM_SQDIFF_NORMED
    raise InvalidRequestError("不支持的模板匹配方法", details={"method": method_name})


def _read_score_threshold(raw_value: object) -> float:
    """读取匹配分数阈值。"""

    if raw_value in {None, ""}:
        return 0.8
    normalized_value = require_non_negative_float(raw_value, field_name="score_threshold")
    if normalized_value > 1.0:
        raise InvalidRequestError("score_threshold 必须在 0 到 1 之间")
    return float(normalized_value)


def _read_nms_iou_threshold(raw_value: object) -> float:
    """读取匹配框去重 IoU 阈值。"""

    if raw_value in {None, ""}:
        return 0.3
    normalized_value = require_non_negative_float(raw_value, field_name="nms_iou_threshold")
    if normalized_value > 1.0:
        raise InvalidRequestError("nms_iou_threshold 必须在 0 到 1 之间")
    return float(normalized_value)


def _read_max_matches(raw_value: object) -> int:
    """读取最多返回的匹配数。"""

    if raw_value in {None, ""}:
        return 1
    return require_positive_int(raw_value, field_name="max_matches")


def _read_bool_parameter(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _read_region_id_prefix(raw_value: object) -> str:
    """读取输出 region_id 前缀。"""

    if raw_value is None:
        return "tmpl"
    normalized_value = str(raw_value).strip()
    return normalized_value or "tmpl"


def _read_class_id_default(raw_value: object) -> int:
    """读取缺省 class_id。"""

    if raw_value is None:
        return -1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("class_id_default 必须是整数")
    return int(raw_value)


def _read_class_name_default(raw_value: object) -> str:
    """读取缺省 class_name。"""

    if raw_value is None:
        return "template-match"
    normalized_value = str(raw_value).strip()
    return normalized_value or "template-match"


def _normalize_score_map(*, raw_result_map: Any, method_name: str, np_module: Any) -> Any:
    """把不同模板匹配方法的原始结果规整为统一 0 到 1 分数图。"""

    normalized_result_map = raw_result_map.astype(np_module.float32, copy=False)
    if method_name == "ccoeff-normed":
        score_map = (normalized_result_map + 1.0) / 2.0
    elif method_name == "ccorr-normed":
        score_map = normalized_result_map
    else:
        score_map = 1.0 - normalized_result_map
    return np_module.clip(score_map, 0.0, 1.0)


def _compute_bbox_iou(bbox_a_xyxy: list[float], bbox_b_xyxy: list[float]) -> float:
    """计算两个 bbox 的 IoU。"""

    inter_x1 = max(float(bbox_a_xyxy[0]), float(bbox_b_xyxy[0]))
    inter_y1 = max(float(bbox_a_xyxy[1]), float(bbox_b_xyxy[1]))
    inter_x2 = min(float(bbox_a_xyxy[2]), float(bbox_b_xyxy[2]))
    inter_y2 = min(float(bbox_a_xyxy[3]), float(bbox_b_xyxy[3]))
    inter_width = max(0.0, inter_x2 - inter_x1)
    inter_height = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_width * inter_height
    if inter_area <= 0.0:
        return 0.0
    area_a = max(0.0, float(bbox_a_xyxy[2]) - float(bbox_a_xyxy[0])) * max(
        0.0,
        float(bbox_a_xyxy[3]) - float(bbox_a_xyxy[1]),
    )
    area_b = max(0.0, float(bbox_b_xyxy[2]) - float(bbox_b_xyxy[0])) * max(
        0.0,
        float(bbox_b_xyxy[3]) - float(bbox_b_xyxy[1]),
    )
    union_area = area_a + area_b - inter_area
    if union_area <= 0.0:
        return 0.0
    return float(inter_area / union_area)


def _build_match_candidate(
    *,
    match_x: int,
    match_y: int,
    score_value: float,
    raw_score_value: float,
    template_width: int,
    template_height: int,
    search_bbox_xyxy: list[int],
) -> dict[str, object]:
    """构造单个候选匹配记录。"""

    search_x1, search_y1, _search_x2, _search_y2 = search_bbox_xyxy
    bbox_xyxy = [
        float(search_x1 + match_x),
        float(search_y1 + match_y),
        float(search_x1 + match_x + template_width),
        float(search_y1 + match_y + template_height),
    ]
    return {
        "top_left_xy": [int(search_x1 + match_x), int(search_y1 + match_y)],
        "bbox_xyxy": bbox_xyxy,
        "score": float(score_value),
        "raw_score": float(raw_score_value),
    }


def _select_match_candidates(
    *,
    score_map: Any,
    raw_result_map: Any,
    score_threshold: float,
    max_matches: int,
    nms_iou_threshold: float,
    template_width: int,
    template_height: int,
    search_bbox_xyxy: list[int],
    np_module: Any,
) -> tuple[list[dict[str, object]], int, bool]:
    """从匹配分数图里选出最终候选。"""

    if max_matches == 1:
        flat_best_index = int(np_module.argmax(score_map))
        best_match_y, best_match_x = np_module.unravel_index(flat_best_index, score_map.shape)
        best_score = float(score_map[best_match_y, best_match_x])
        if best_score < score_threshold:
            return [], 1, False
        return (
            [
                _build_match_candidate(
                    match_x=int(best_match_x),
                    match_y=int(best_match_y),
                    score_value=best_score,
                    raw_score_value=float(raw_result_map[best_match_y, best_match_x]),
                    template_width=template_width,
                    template_height=template_height,
                    search_bbox_xyxy=search_bbox_xyxy,
                )
            ],
            1,
            False,
        )

    candidate_indices = np_module.argwhere(score_map >= score_threshold)
    candidate_count = int(candidate_indices.shape[0])
    if candidate_count <= 0:
        return [], 0, False

    candidate_limit = max(256, max_matches * 64)
    candidate_truncated = False
    candidate_scores = score_map[candidate_indices[:, 0], candidate_indices[:, 1]]
    if candidate_count > candidate_limit:
        top_indices = np_module.argpartition(candidate_scores, -candidate_limit)[-candidate_limit:]
        candidate_indices = candidate_indices[top_indices]
        candidate_scores = candidate_scores[top_indices]
        candidate_truncated = True
    sort_order = np_module.argsort(-candidate_scores, kind="stable")

    selected_candidates: list[dict[str, object]] = []
    for order_index in sort_order.tolist():
        match_y = int(candidate_indices[order_index][0])
        match_x = int(candidate_indices[order_index][1])
        candidate = _build_match_candidate(
            match_x=match_x,
            match_y=match_y,
            score_value=float(candidate_scores[order_index]),
            raw_score_value=float(raw_result_map[match_y, match_x]),
            template_width=template_width,
            template_height=template_height,
            search_bbox_xyxy=search_bbox_xyxy,
        )
        if any(
            _compute_bbox_iou(candidate["bbox_xyxy"], selected_candidate["bbox_xyxy"]) > nms_iou_threshold
            for selected_candidate in selected_candidates
        ):
            continue
        selected_candidates.append(candidate)
        if len(selected_candidates) >= max_matches:
            break
    return selected_candidates, candidate_count, candidate_truncated


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在输入图片中搜索模板位置，并输出可直接进入工业规则链的 regions.v1。"""

    cv2_module, np_module = require_opencv_imports()
    method_name = _read_match_method(request.parameters.get("method"))
    score_threshold = _read_score_threshold(request.parameters.get("score_threshold"))
    max_matches = _read_max_matches(request.parameters.get("max_matches"))
    nms_iou_threshold = _read_nms_iou_threshold(request.parameters.get("nms_iou_threshold"))
    convert_to_grayscale = _read_bool_parameter(
        request.parameters.get("convert_to_grayscale"),
        field_name="convert_to_grayscale",
        default_value=True,
    )
    region_id_prefix = _read_region_id_prefix(request.parameters.get("region_id_prefix"))
    class_id_default = _read_class_id_default(request.parameters.get("class_id_default"))
    class_name_default = _read_class_name_default(request.parameters.get("class_name_default"))
    imdecode_flags = cv2_module.IMREAD_GRAYSCALE if convert_to_grayscale else cv2_module.IMREAD_COLOR

    source_image_payload, _source_object_key, source_image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=imdecode_flags,
    )
    source_height = int(source_image_matrix.shape[0])
    source_width = int(source_image_matrix.shape[1])
    raw_template_bbox_xyxy = request.parameters.get("template_bbox_xyxy")
    template_bbox_xyxy: list[int] | None = None
    if raw_template_bbox_xyxy is not None and raw_template_bbox_xyxy != "":
        template_bbox_xyxy = clip_bbox_xyxy(
            raw_template_bbox_xyxy,
            image_width=source_width,
            image_height=source_height,
            field_name="template_bbox_xyxy",
        )
        template_x1, template_y1, template_x2, template_y2 = template_bbox_xyxy
        template_image_matrix = source_image_matrix[template_y1:template_y2, template_x1:template_x2].copy()
        template_source = "template-bbox"
    else:
        _template_image_payload, _template_object_key, template_image_matrix = load_image_matrix(
            request,
            input_name="template_image",
            imdecode_flags=imdecode_flags,
        )
        template_source = "template-image-input"
    search_roi = resolve_search_roi(request, image_matrix=source_image_matrix)
    search_image_matrix = search_roi.image_matrix
    search_bbox_xyxy = search_roi.bbox_xyxy or [0, 0, source_width, source_height]

    template_height = int(template_image_matrix.shape[0])
    template_width = int(template_image_matrix.shape[1])
    search_height = int(search_image_matrix.shape[0])
    search_width = int(search_image_matrix.shape[1])
    if template_width <= 0 or template_height <= 0:
        raise InvalidRequestError("template_image 不能为空")
    if template_width > search_width or template_height > search_height:
        raise InvalidRequestError(
            "template_image 尺寸不能大于搜索区域",
            details={
                "template_width": template_width,
                "template_height": template_height,
                "search_width": search_width,
                "search_height": search_height,
            },
        )

    raw_result_map = cv2_module.matchTemplate(
        search_image_matrix,
        template_image_matrix,
        _resolve_match_method(method_name, cv2_module=cv2_module),
    )
    score_map = _normalize_score_map(
        raw_result_map=raw_result_map,
        method_name=method_name,
        np_module=np_module,
    )
    selected_candidates, candidate_count, candidate_truncated = _select_match_candidates(
        score_map=score_map,
        raw_result_map=raw_result_map,
        score_threshold=score_threshold,
        max_matches=max_matches,
        nms_iou_threshold=nms_iou_threshold,
        template_width=template_width,
        template_height=template_height,
        search_bbox_xyxy=search_bbox_xyxy,
        np_module=np_module,
    )

    region_items: list[dict[str, object]] = []
    summary_items: list[dict[str, object]] = []
    for match_index, candidate in enumerate(selected_candidates, start=1):
        bbox_xyxy = [float(value) for value in candidate["bbox_xyxy"]]
        top_left_xy = [int(candidate["top_left_xy"][0]), int(candidate["top_left_xy"][1])]
        center_xy = [
            round(float((bbox_xyxy[0] + bbox_xyxy[2]) / 2.0), 4),
            round(float((bbox_xyxy[1] + bbox_xyxy[3]) / 2.0), 4),
        ]
        region_id = f"{region_id_prefix}-{match_index}"
        region_items.append(
            {
                "region_id": region_id,
                "score": round(float(candidate["score"]), 6),
                "class_id": int(class_id_default),
                "class_name": class_name_default,
                "bbox_xyxy": bbox_xyxy,
                "polygon_xy": bbox_to_polygon_xy(bbox_xyxy),
                "area": int(template_width * template_height),
                "center_xy": center_xy,
                "match_top_left_xy": top_left_xy,
                "template_width_pixels": int(template_width),
                "template_height_pixels": int(template_height),
                "match_method": method_name,
                "raw_score": round(float(candidate["raw_score"]), 6),
            }
        )
        summary_items.append(
            {
                "region_id": region_id,
                "top_left_xy": top_left_xy,
                "center_xy": center_xy,
                "bbox_xyxy": [round(float(value), 4) for value in bbox_xyxy],
                "score": round(float(candidate["score"]), 6),
                "raw_score": round(float(candidate["raw_score"]), 6),
            }
        )

    score_values = [float(item["score"]) for item in region_items]
    summary_payload = {
        "method": method_name,
        "score_threshold": score_threshold,
        "max_matches": max_matches,
        "nms_iou_threshold": nms_iou_threshold,
        "convert_to_grayscale": convert_to_grayscale,
        "search_bbox_xyxy": [int(value) for value in search_bbox_xyxy],
        "search_width": search_width,
        "search_height": search_height,
        "template_source": template_source,
        "template_bbox_xyxy": template_bbox_xyxy,
        "template_width": template_width,
        "template_height": template_height,
        "candidate_count": candidate_count,
        "candidate_truncated": candidate_truncated,
        "match_count": len(region_items),
        "region_id_prefix": region_id_prefix,
        "class_id_default": class_id_default,
        "class_name_default": class_name_default,
        "max_score": round(max(score_values), 6) if score_values else None,
        "min_score": round(min(score_values), 6) if score_values else None,
        "mean_score": round(sum(score_values) / len(score_values), 6) if score_values else None,
        "items": summary_items,
    }
    summary_payload.update(build_search_roi_summary(search_roi))

    outputs: dict[str, object] = {
        "regions": build_regions_payload(
            source_image=source_image_payload,
            selected_frame_index=None,
            items=region_items,
        ),
        "summary": build_value_payload(summary_payload),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=source_image_payload,
            title="Template Match",
            artifact_name="template-match-debug-preview",
            overlays=_build_template_match_overlays(
                region_items,
                search_roi=search_roi,
                template_bbox_xyxy=template_bbox_xyxy,
            ),
            interaction=_build_template_match_interaction(
                score_threshold=score_threshold,
                max_matches=max_matches,
                nms_iou_threshold=nms_iou_threshold,
            ),
        )
    )
    return outputs


def _build_template_match_interaction(
    *,
    score_threshold: float,
    max_matches: int,
    nms_iou_threshold: float,
) -> dict[str, object]:
    """声明 Template Match 在图片面板中的搜索区域和调参能力。"""

    return build_debug_panel_interaction(
        tools=[
            build_interaction_tool(
                "template-region",
                "模板 / 搜索区域",
                ["template_bbox_xyxy", "search_bbox_xyxy"],
            ),
        ],
        controls=[
            build_numeric_control(
                "score_threshold",
                "Score Threshold",
                score_threshold,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
            ),
            build_numeric_control("max_matches", "Max Matches", max_matches, min_value=1.0, max_value=200.0, step=1.0),
            build_numeric_control(
                "nms_iou_threshold",
                "NMS IoU",
                nms_iou_threshold,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
            ),
        ],
    )


def _build_template_match_overlays(
    region_items: list[dict[str, object]],
    *,
    search_roi: ResolvedSearchRoi,
    template_bbox_xyxy: list[int] | None,
) -> list[dict[str, object]]:
    """把模板匹配结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    if template_bbox_xyxy is not None:
        overlays.append(
            build_bbox_overlay(
                overlay_id="template-roi",
                label="Template ROI",
                bbox_xyxy=[float(value) for value in template_bbox_xyxy],
                target_parameters=["template_bbox_xyxy"],
            )
        )
    search_roi_overlay = build_search_roi_overlay(search_roi)
    if search_roi_overlay is not None:
        overlays.append(search_roi_overlay)
    for region_item in region_items[:100]:
        bbox_xyxy = region_item.get("bbox_xyxy")
        if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) < 4:
            continue
        region_id = str(region_item.get("region_id") or f"match-{len(overlays) + 1}")
        score = region_item.get("score")
        overlays.append(
            build_bbox_overlay(
                overlay_id=region_id,
                label=f"{region_id} {float(score):.3f}" if isinstance(score, (int, float)) else region_id,
                bbox_xyxy=[float(value) for value in bbox_xyxy[:4]],
            )
        )
    return overlays
