"""deployment 单图与 Batch 节点共享的标准结果 payload 构造。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)

if TYPE_CHECKING:
    from backend.service.application.deployments import PublishedInferenceResult


def build_deployment_result_payload(
    *,
    task_type: str,
    inference_result: PublishedInferenceResult,
    source_image: dict[str, object] | None,
) -> dict[str, object]:
    """把 gateway 结果转换为对应的现有单项 payload contract。"""

    if task_type == DETECTION_TASK_TYPE:
        payload: dict[str, object] = {
            "items": [dict(item) for item in inference_result.detections],
            "metadata": dict(inference_result.metadata),
        }
        if source_image is not None:
            payload["source_image"] = dict(source_image)
            payload["count"] = len(inference_result.detections)
        return payload
    if task_type == CLASSIFICATION_TASK_TYPE:
        return _build_categories_payload(
            inference_result=inference_result,
            source_image=source_image,
        )
    if task_type == SEGMENTATION_TASK_TYPE:
        return _build_segments_payload(
            inference_result=inference_result,
            source_image=source_image,
        )
    if task_type == POSE_TASK_TYPE:
        return _build_poses_payload(
            inference_result=inference_result,
            source_image=source_image,
        )
    if task_type == OBB_TASK_TYPE:
        return _build_obbs_payload(
            inference_result=inference_result,
            source_image=source_image,
        )
    raise InvalidRequestError(
        "deployment 结果使用了不支持的 task_type",
        details={"task_type": task_type},
    )


def _build_categories_payload(
    *,
    inference_result: PublishedInferenceResult,
    source_image: dict[str, object] | None,
) -> dict[str, object]:
    """构造 categories.v1。"""

    payload: dict[str, object] = {
        "count": len(inference_result.categories),
        "items": [dict(item) for item in inference_result.categories],
        "top_item": (
            dict(inference_result.top_category)
            if isinstance(inference_result.top_category, dict)
            else None
        ),
        "image_width": inference_result.image_width,
        "image_height": inference_result.image_height,
        "latency_ms": inference_result.latency_ms,
        "runtime_session_info": dict(inference_result.runtime_session_info),
        "metadata": dict(inference_result.metadata),
    }
    if source_image is not None:
        payload["source_image"] = dict(source_image)
    return payload


def _build_segments_payload(
    *,
    inference_result: PublishedInferenceResult,
    source_image: dict[str, object] | None,
) -> dict[str, object]:
    """构造 segments.v1。"""

    segment_items = [
        _build_segment_item(item=item, index=index)
        for index, item in enumerate(inference_result.instances, start=1)
    ]
    payload: dict[str, object] = {
        "count": len(segment_items),
        "items": segment_items,
        "image_width": inference_result.image_width,
        "image_height": inference_result.image_height,
        "latency_ms": inference_result.latency_ms,
        "runtime_session_info": dict(inference_result.runtime_session_info),
        "metadata": dict(inference_result.metadata),
    }
    if source_image is not None:
        payload["source_image"] = dict(source_image)
    return payload


def _build_segment_item(*, item: dict[str, object], index: int) -> dict[str, object]:
    """构造单条 segments.v1 item。"""

    polygons = item.get("segments")
    normalized_polygons = (
        [polygon for polygon in polygons if isinstance(polygon, list) and polygon]
        if isinstance(polygons, list)
        else []
    )
    primary_polygon = _select_primary_polygon(normalized_polygons)
    bbox_xyxy = (
        list(item.get("bbox_xyxy"))
        if isinstance(item.get("bbox_xyxy"), list)
        else []
    )
    if primary_polygon is None and len(bbox_xyxy) == 4:
        primary_polygon = [
            [float(bbox_xyxy[0]), float(bbox_xyxy[1])],
            [float(bbox_xyxy[2]), float(bbox_xyxy[1])],
            [float(bbox_xyxy[2]), float(bbox_xyxy[3])],
            [float(bbox_xyxy[0]), float(bbox_xyxy[3])],
        ]
    segment_item: dict[str, object] = {
        "segment_id": str(item.get("segment_id") or f"segment-{index}"),
        "score": float(item.get("score") or 0.0),
        "bbox_xyxy": bbox_xyxy,
        "polygon_xy": primary_polygon or [],
        "all_polygons_xy": normalized_polygons,
        "polygon_count": len(normalized_polygons),
    }
    if isinstance(item.get("class_id"), int):
        segment_item["class_id"] = int(item["class_id"])
    if isinstance(item.get("class_name"), str):
        segment_item["class_name"] = item["class_name"]
    if isinstance(item.get("mask_area"), int | float):
        segment_item["mask_area"] = float(item["mask_area"])
    return segment_item


def _select_primary_polygon(polygons: list[list[object]]) -> list[list[float]] | None:
    """从多个 polygon 中选出外接框面积最大的一个。"""

    best_polygon: list[list[float]] | None = None
    best_area = -1.0
    for polygon in polygons:
        normalized_polygon = [
            [float(point[0]), float(point[1])]
            for point in polygon
            if isinstance(point, list) and len(point) == 2
        ]
        if len(normalized_polygon) < 3:
            continue
        x_values = [point[0] for point in normalized_polygon]
        y_values = [point[1] for point in normalized_polygon]
        bbox_area = max(0.0, max(x_values) - min(x_values)) * max(
            0.0,
            max(y_values) - min(y_values),
        )
        if bbox_area > best_area:
            best_area = bbox_area
            best_polygon = normalized_polygon
    return best_polygon


def _build_poses_payload(
    *,
    inference_result: PublishedInferenceResult,
    source_image: dict[str, object] | None,
) -> dict[str, object]:
    """构造 poses.v1。"""

    pose_items = [
        {
            "pose_id": str(item.get("pose_id") or f"pose-{index}"),
            "score": float(item.get("score") or 0.0),
            "class_id": int(item.get("class_id") or 0),
            "class_name": item.get("class_name"),
            "bbox_xyxy": (
                list(item.get("bbox_xyxy"))
                if isinstance(item.get("bbox_xyxy"), list)
                else []
            ),
            "keypoints": [
                dict(point)
                for point in item.get("keypoints", [])
                if isinstance(point, dict)
            ],
            "kpt_shape": (
                list(item.get("kpt_shape"))
                if isinstance(item.get("kpt_shape"), list)
                else []
            ),
        }
        for index, item in enumerate(inference_result.instances, start=1)
    ]
    payload: dict[str, object] = {
        "count": len(pose_items),
        "items": pose_items,
        "image_width": inference_result.image_width,
        "image_height": inference_result.image_height,
        "latency_ms": inference_result.latency_ms,
        "runtime_session_info": dict(inference_result.runtime_session_info),
        "metadata": dict(inference_result.metadata),
    }
    if source_image is not None:
        payload["source_image"] = dict(source_image)
    return payload


def _build_obbs_payload(
    *,
    inference_result: PublishedInferenceResult,
    source_image: dict[str, object] | None,
) -> dict[str, object]:
    """构造 obbs.v1。"""

    obb_items = [
        {
            "obb_id": str(item.get("obb_id") or f"obb-{index}"),
            "score": float(item.get("score") or 0.0),
            "class_id": int(item.get("class_id") or 0),
            "class_name": item.get("class_name"),
            "bbox_xyxy": (
                list(item.get("bbox_xyxy"))
                if isinstance(item.get("bbox_xyxy"), list)
                else []
            ),
            "angle": (
                float(item["angle"])
                if isinstance(item.get("angle"), int | float)
                else None
            ),
        }
        for index, item in enumerate(inference_result.instances, start=1)
    ]
    payload: dict[str, object] = {
        "count": len(obb_items),
        "items": obb_items,
        "image_width": inference_result.image_width,
        "image_height": inference_result.image_height,
        "latency_ms": inference_result.latency_ms,
        "runtime_session_info": dict(inference_result.runtime_session_info),
        "metadata": dict(inference_result.metadata),
    }
    if source_image is not None:
        payload["source_image"] = dict(source_image)
    return payload
