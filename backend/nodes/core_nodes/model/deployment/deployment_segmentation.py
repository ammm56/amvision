"""deployment 分割节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.deployment_model import (
    DEFAULT_DIRECT_MODEL_MASK_THRESHOLD,
    DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD,
    run_direct_model_inference,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE


def _deployment_segmentation_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """通过 PublishedInferenceGateway 调用已发布 segmentation 推理服务。"""

    inference_result, source_image = run_direct_model_inference(
        request,
        task_type=SEGMENTATION_TASK_TYPE,
    )
    return {
        "segments": _build_segments_payload(
            source_image=source_image,
            items=inference_result.instances,
            image_width=inference_result.image_width,
            image_height=inference_result.image_height,
            latency_ms=inference_result.latency_ms,
            runtime_session_info=inference_result.runtime_session_info,
            metadata=inference_result.metadata,
        )
    }


def _build_segments_payload(
    *,
    source_image: dict[str, object],
    items: tuple[dict[str, object], ...],
    image_width: int,
    image_height: int,
    latency_ms: float | None,
    runtime_session_info: dict[str, object],
    metadata: dict[str, object],
) -> dict[str, object]:
    """把 segmentation inference 结果转换成 segments.v1。"""

    segment_items: list[dict[str, object]] = []
    for index, item in enumerate(items, start=1):
        segment_item = _build_segment_item(item=item, index=index)
        segment_items.append(segment_item)
    return {
        "source_image": dict(source_image),
        "count": len(segment_items),
        "items": segment_items,
        "image_width": image_width,
        "image_height": image_height,
        "latency_ms": latency_ms,
        "runtime_session_info": dict(runtime_session_info),
        "metadata": dict(metadata),
    }


def _build_segment_item(*, item: dict[str, object], index: int) -> dict[str, object]:
    """构造单条 segments.v1 item。"""

    polygons = item.get("segments")
    normalized_polygons = [
        polygon
        for polygon in polygons
        if isinstance(polygon, list) and polygon
    ] if isinstance(polygons, list) else []
    primary_polygon = _select_primary_polygon(normalized_polygons)
    bbox_xyxy = list(item.get("bbox_xyxy")) if isinstance(item.get("bbox_xyxy"), list) else []
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
    """从多个 polygon 中选出面积近似最大的一个。"""

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
        bbox_area = max(0.0, max(x_values) - min(x_values)) * max(0.0, max(y_values) - min(y_values))
        if bbox_area > best_area:
            best_area = bbox_area
            best_polygon = normalized_polygon
    return best_polygon


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.model.segmentation",
        display_name="Segmentation",
        category="model.inference",
        description="调用独立推理 worker 产出标准 segmentation 结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
            NodePortDefinition(
                name="dependency",
                display_name="Dependency",
                payload_type_id="response-body.v1",
                required=False,
            ),
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="segments",
                display_name="Segments",
                payload_type_id="segments.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "deployment_instance_id": {"type": "string"},
                "score_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD,
                },
                "mask_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": DEFAULT_DIRECT_MODEL_MASK_THRESHOLD,
                },
                "auto_start_process": {"type": "boolean"},
                "save_result_image": {"type": "boolean"},
                "return_preview_image_base64": {"type": "boolean"},
                "extra_options": {"type": "object"},
            },
            "required": ["deployment_instance_id"],
        },
        capability_tags=("model.inference", "segmentation"),
        runtime_requirements={"deployment_process": "sync"},
    ),
    handler=_deployment_segmentation_handler,
)
