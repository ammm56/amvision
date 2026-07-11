"""ORB Keypoints 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import build_roi_mask, require_roi_payload
from backend.nodes.debug_image_panel import build_debug_image_preview_output
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.features import build_local_features_payload
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_int,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.orb-keypoints"


def _read_scale_factor(raw_value: object) -> float:
    """读取 ORB scale_factor。"""

    if raw_value in {None, ""}:
        return 1.2
    normalized_value = require_non_negative_float(raw_value, field_name="scale_factor")
    if normalized_value <= 1.0:
        raise InvalidRequestError("scale_factor 必须大于 1.0")
    return float(normalized_value)


def _read_positive_int(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取正整数参数。"""

    if raw_value in {None, ""}:
        return int(default_value)
    return require_positive_int(raw_value, field_name=field_name)


def _read_non_negative_int_parameter(
    raw_value: object,
    *,
    field_name: str,
    default_value: int,
) -> int:
    """读取非负整数参数。"""

    if raw_value in {None, ""}:
        return int(default_value)
    return require_non_negative_int(raw_value, field_name=field_name)


def _read_wta_k(raw_value: object) -> int:
    """读取 ORB WTA_K。"""

    if raw_value in {None, ""}:
        return 2
    normalized_value = require_positive_int(raw_value, field_name="wta_k")
    if normalized_value not in {2, 3, 4}:
        raise InvalidRequestError("wta_k 仅支持 2、3 或 4")
    return int(normalized_value)


def _read_score_type(raw_value: object) -> str:
    """读取 ORB score_type。"""

    if raw_value in {None, ""}:
        return "harris"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("score_type 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"harris", "fast"}:
        raise InvalidRequestError("score_type 仅支持 harris 或 fast")
    return normalized_value


def _read_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _read_feature_id_prefix(raw_value: object) -> str:
    """读取 feature_id 前缀。"""

    if raw_value is None:
        return "orb"
    normalized_value = str(raw_value).strip()
    return normalized_value or "orb"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片提取 ORB 局部特征与二进制描述子。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    max_features = _read_positive_int(
        request.parameters.get("max_features"),
        field_name="max_features",
        default_value=500,
    )
    scale_factor = _read_scale_factor(request.parameters.get("scale_factor"))
    level_count = _read_positive_int(
        request.parameters.get("level_count"),
        field_name="level_count",
        default_value=8,
    )
    edge_threshold = _read_positive_int(
        request.parameters.get("edge_threshold"),
        field_name="edge_threshold",
        default_value=31,
    )
    first_level = _read_non_negative_int_parameter(
        request.parameters.get("first_level"),
        field_name="first_level",
        default_value=0,
    )
    wta_k = _read_wta_k(request.parameters.get("wta_k"))
    score_type = _read_score_type(request.parameters.get("score_type"))
    patch_size = _read_positive_int(
        request.parameters.get("patch_size"),
        field_name="patch_size",
        default_value=31,
    )
    fast_threshold = _read_non_negative_int_parameter(
        request.parameters.get("fast_threshold"),
        field_name="fast_threshold",
        default_value=20,
    )
    use_roi_mask = _read_bool(
        request.parameters.get("use_roi_mask"),
        field_name="use_roi_mask",
        default_value=True,
    )
    feature_id_prefix = _read_feature_id_prefix(request.parameters.get("feature_id_prefix"))

    raw_roi_payload = request.input_values.get("roi")
    roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id) if raw_roi_payload is not None else None
    mask_matrix = None
    if roi_payload is not None and use_roi_mask:
        mask_matrix = build_roi_mask(
            roi_payload=roi_payload,
            image_width=int(image_matrix.shape[1]),
            image_height=int(image_matrix.shape[0]),
        ).astype(np_module.uint8)
        mask_matrix *= 255

    orb_detector = cv2_module.ORB_create(
        nfeatures=max_features,
        scaleFactor=scale_factor,
        nlevels=level_count,
        edgeThreshold=edge_threshold,
        firstLevel=first_level,
        WTA_K=wta_k,
        scoreType=cv2_module.ORB_HARRIS_SCORE if score_type == "harris" else cv2_module.ORB_FAST_SCORE,
        patchSize=patch_size,
        fastThreshold=fast_threshold,
    )
    keypoints, descriptors = orb_detector.detectAndCompute(image_matrix, mask_matrix)
    descriptor_length = int(orb_detector.descriptorSize())
    feature_items: list[dict[str, object]] = []
    descriptor_rows: list[list[int]] = []
    for feature_index, keypoint in enumerate(keypoints or []):
        point_x = round(float(keypoint.pt[0]), 4)
        point_y = round(float(keypoint.pt[1]), 4)
        feature_items.append(
            {
                "feature_id": f"{feature_id_prefix}-{feature_index + 1}",
                "feature_index": int(feature_index),
                "x": point_x,
                "y": point_y,
                "point_xy": [point_x, point_y],
                "size": round(float(keypoint.size), 4),
                "angle_deg": round(float(keypoint.angle), 4),
                "response": round(float(keypoint.response), 6),
                "octave": int(keypoint.octave),
                "class_id": int(keypoint.class_id),
            }
        )
    if descriptors is not None:
        descriptor_rows = descriptors.astype(np_module.uint8).tolist()
    descriptor_norm = "hamming2" if wta_k in {3, 4} else "hamming"
    features_payload = build_local_features_payload(
        items=feature_items,
        descriptors=descriptor_rows,
        source_image=image_payload,
        source_object_key=source_object_key,
        descriptor_length=descriptor_length,
        descriptor_norm=descriptor_norm,
        wta_k=wta_k,
        roi_payload=roi_payload,
    )
    response_values = [float(item["response"]) for item in feature_items]
    outputs: dict[str, object] = {
        "features": features_payload,
        "summary": build_value_payload(
            {
                "count": len(feature_items),
                "max_features": max_features,
                "scale_factor": scale_factor,
                "level_count": level_count,
                "edge_threshold": edge_threshold,
                "first_level": first_level,
                "wta_k": wta_k,
                "score_type": score_type,
                "patch_size": patch_size,
                "fast_threshold": fast_threshold,
                "descriptor_length": descriptor_length,
                "descriptor_norm": descriptor_norm,
                "use_roi_mask": use_roi_mask,
                "feature_id_prefix": feature_id_prefix,
                "mean_response": round(sum(response_values) / len(response_values), 6) if response_values else None,
                "max_response": round(max(response_values), 6) if response_values else None,
                "min_response": round(min(response_values), 6) if response_values else None,
                "roi_id": roi_payload["roi_id"] if roi_payload is not None else None,
                "roi_kind": roi_payload["roi_kind"] if roi_payload is not None else None,
            }
        ),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=image_payload,
            title="ORB Keypoints",
            artifact_name="orb-keypoints-debug-preview",
            overlays=_build_keypoint_overlays(feature_items, roi_payload=roi_payload),
            interaction=_build_orb_keypoints_interaction(
                max_features=max_features,
                scale_factor=scale_factor,
                level_count=level_count,
                edge_threshold=edge_threshold,
                patch_size=patch_size,
                fast_threshold=fast_threshold,
            ),
        )
    )
    return outputs


def _build_orb_keypoints_interaction(
    *,
    max_features: int,
    scale_factor: float,
    level_count: int,
    edge_threshold: int,
    patch_size: int,
    fast_threshold: int,
) -> dict[str, object]:
    """声明 ORB Keypoints 在图片面板中的调参能力。"""

    return {
        "mode": "edit",
        "coordinate_space": "source-image",
        "tools": [
            {
                "tool": "bbox",
                "label": "参考区域",
                "target_parameters": [],
            },
        ],
        "controls": [
            _build_numeric_control("max_features", "Max Features", max_features, min_value=10.0, max_value=5000.0, step=10.0),
            _build_numeric_control("scale_factor", "Scale Factor", scale_factor, min_value=1.01, max_value=2.5, step=0.01),
            _build_numeric_control("level_count", "Level Count", level_count, min_value=1.0, max_value=16.0, step=1.0),
            _build_numeric_control("edge_threshold", "Edge Threshold", edge_threshold, min_value=0.0, max_value=128.0, step=1.0),
            _build_numeric_control("patch_size", "Patch Size", patch_size, min_value=2.0, max_value=128.0, step=1.0),
            _build_numeric_control("fast_threshold", "FAST Threshold", fast_threshold, min_value=0.0, max_value=255.0, step=1.0),
        ],
    }


def _build_numeric_control(
    parameter_name: str,
    label: str,
    value: float | int,
    *,
    min_value: float,
    max_value: float,
    step: float,
) -> dict[str, object]:
    """构造图片面板实时调参使用的数值控件声明。"""

    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "slider",
        "min": min_value,
        "max": max_value,
        "step": step,
        "value": value,
        "default_value": value,
    }


def _build_keypoint_overlays(
    feature_items: list[dict[str, object]],
    *,
    roi_payload: dict[str, object] | None,
) -> list[dict[str, object]]:
    """把 ORB 关键点和可选 ROI 转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    if roi_payload is not None:
        polygon_xy = roi_payload.get("polygon_xy")
        if isinstance(polygon_xy, list) and len(polygon_xy) >= 3:
            overlays.append(
                {
                    "kind": "polygon",
                    "id": str(roi_payload.get("roi_id") or "roi-mask"),
                    "label": str(roi_payload.get("display_name") or "ROI mask"),
                    "points_xy": polygon_xy,
                }
            )
        else:
            overlays.append(
                {
                    "kind": "bbox",
                    "id": str(roi_payload.get("roi_id") or "roi-mask"),
                    "label": str(roi_payload.get("display_name") or "ROI mask"),
                    "bbox_xyxy": [float(value) for value in roi_payload["bbox_xyxy"]],
                }
            )
    for feature_item in feature_items[:500]:
        point_xy = feature_item.get("point_xy")
        if not isinstance(point_xy, list) or len(point_xy) < 2:
            continue
        feature_index = int(feature_item.get("feature_index", len(overlays) + 1))
        radius = max(2.0, float(feature_item.get("size", 4.0)) / 2.0)
        overlays.append(
            {
                "kind": "circle",
                "id": str(feature_item.get("feature_id") or f"feature-{feature_index}"),
                "label": str(feature_item.get("feature_id") or f"feature {feature_index}"),
                "circle": {
                    "center_x": float(point_xy[0]),
                    "center_y": float(point_xy[1]),
                    "radius": radius,
                },
            }
        )
    return overlays
