"""内建 core nodes 与 payload 规则 目录。"""

from __future__ import annotations

from functools import lru_cache

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowPayloadContract,
)
from backend.nodes.core_nodes import get_core_node_specs


def _build_image_ref_json_schema(*, extra_properties: dict[str, object] | None = None) -> dict[str, object]:
    """构造统一的 image-ref.v1 JSON schema。

    参数：
    - extra_properties：调用方需要额外挂到 schema 上的字段。

    返回：
    - dict[str, object]：支持 memory、storage、buffer、frame 和 raw image metadata 的 schema。
    """

    properties: dict[str, object] = {
        "transport_kind": {
            "type": "string",
            "enum": ["memory", "storage", "buffer", "frame"],
        },
        "object_key": {"type": "string"},
        "image_handle": {"type": "string"},
        "buffer_ref": {"type": "object"},
        "frame_ref": {"type": "object"},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "media_type": {"type": "string"},
        "shape": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
            "maxItems": 4,
        },
        "dtype": {"type": "string"},
        "layout": {"type": "string"},
        "pixel_format": {"type": "string"},
    }
    if extra_properties:
        properties.update(extra_properties)
    return {
        "type": "object",
        "properties": properties,
        "required": ["transport_kind", "media_type"],
        "oneOf": [
            {
                "properties": {
                    "transport_kind": {"const": "storage"},
                },
                "required": ["object_key"],
            },
            {
                "properties": {
                    "transport_kind": {"const": "memory"},
                },
                "required": ["image_handle"],
            },
            {
                "properties": {
                    "transport_kind": {"const": "buffer"},
                },
                "required": ["buffer_ref"],
            },
            {
                "properties": {
                    "transport_kind": {"const": "frame"},
                },
                "required": ["frame_ref"],
            },
        ],
    }


@lru_cache(maxsize=1)
def get_core_workflow_payload_contracts() -> tuple[WorkflowPayloadContract, ...]:
    """返回 backend 内建的最小 payload 规则 目录。

    返回：
    - tuple[WorkflowPayloadContract, ...]：内建 payload 规则 列表。
    """

    return (
        WorkflowPayloadContract(
            payload_type_id="value.v1",
            display_name="Value Payload",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "value": {},
                },
                "required": ["value"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="boolean.v1",
            display_name="Boolean Payload",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "value": {"type": "boolean"},
                },
                "required": ["value"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="image-ref.v1",
            display_name="Image Reference",
            transport_kind="hybrid",
            json_schema=_build_image_ref_json_schema(),
            artifact_kinds=("image",),
        ),
        WorkflowPayloadContract(
            payload_type_id="image-base64.v1",
            display_name="Image Base64 Input",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "image_base64": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "media_type": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["image_base64"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="dataset-package.v1",
            display_name="Dataset Package Upload",
            transport_kind="multipart-upload",
            json_schema={
                "type": "object",
                "properties": {
                    "package_file_name": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "package_bytes": {
                        "type": "string",
                        "format": "binary",
                    },
                    "media_type": {"type": "string"},
                },
                "required": ["package_file_name", "package_bytes"],
            },
            artifact_kinds=("dataset-package",),
        ),
        WorkflowPayloadContract(
            payload_type_id="image-refs.v1",
            display_name="Image References",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            **_build_image_ref_json_schema(
                                extra_properties={
                                    "bbox_xyxy": {"type": "array"},
                                    "crop_index": {"type": "integer"},
                                }
                            ),
                        },
                    },
                    "count": {"type": "integer"},
                    "source_image": _build_image_ref_json_schema(),
                    "source_object_key": {"type": "string"},
                },
                "required": ["items"],
            },
            artifact_kinds=("image",),
        ),
        WorkflowPayloadContract(
            payload_type_id="video-ref.v1",
            display_name="Video Reference",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "transport_kind": {
                        "type": "string",
                        "enum": ["local-path", "storage"],
                    },
                    "local_path": {"type": "string"},
                    "object_key": {"type": "string"},
                    "media_type": {"type": "string"},
                    "frame_count": {"type": "integer", "minimum": 0},
                    "fps": {"type": "number", "minimum": 0},
                    "width": {"type": "integer", "minimum": 0},
                    "height": {"type": "integer", "minimum": 0},
                    "duration_ms": {"type": "number", "minimum": 0},
                },
                "required": ["transport_kind", "media_type"],
                "oneOf": [
                    {
                        "properties": {"transport_kind": {"const": "local-path"}},
                        "required": ["local_path"],
                    },
                    {
                        "properties": {"transport_kind": {"const": "storage"}},
                        "required": ["object_key"],
                    },
                ],
            },
            artifact_kinds=("video",),
        ),
        WorkflowPayloadContract(
            payload_type_id="frame-window.v1",
            display_name="Frame Window",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_video": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "window_start_index": {"type": "integer", "minimum": 0},
                    "window_end_index": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "frame_index": {"type": "integer", "minimum": 0},
                                "timestamp_ms": {"type": "number", "minimum": 0},
                                "image": {"type": "object"},
                            },
                            "required": ["frame_index", "timestamp_ms", "image"],
                        },
                    },
                },
                "required": ["count", "items"],
            },
            artifact_kinds=("video-frame-window",),
        ),
        WorkflowPayloadContract(
            payload_type_id="tracks.v1",
            display_name="Tracks",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_video": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "track_id": {"type": "string"},
                                "frame_index": {"type": "integer", "minimum": 0},
                                "timestamp_ms": {"type": "number", "minimum": 0},
                                "score": {"type": "number"},
                                "class_id": {"type": "integer"},
                                "class_name": {"type": "string"},
                                "bbox_xyxy": {"type": "array"},
                                "polygon_xy": {"type": "array"},
                                "mask_image": {"type": "object"},
                                "region_id": {"type": "string"},
                                "state": {"type": "string"},
                                "prompt_id": {"type": "string"},
                                "area": {"type": "integer", "minimum": 0},
                                "source_prompt_text": {"type": "string"},
                                "source_prompt_positive_texts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "source_prompt_negative_texts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["track_id", "frame_index", "score"],
                        },
                    },
                },
                "required": ["count", "items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="segments.v1",
            display_name="Segments",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_image": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "selected_frame_index": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "segment_id": {"type": "string"},
                                "score": {"type": "number"},
                                "class_id": {"type": "integer"},
                                "class_name": {"type": "string"},
                                "bbox_xyxy": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "polygon_xy": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "mask_image": {"type": "object"},
                                "prompt_id": {"type": "string"},
                                "source_prompt_text": {"type": "string"},
                                "source_prompt_positive_texts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "source_prompt_negative_texts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "track_id": {"type": "string"},
                                "frame_index": {"type": "integer", "minimum": 0},
                                "timestamp_ms": {"type": "number", "minimum": 0},
                                "state": {"type": "string"},
                            },
                            "required": ["score"],
                        },
                    },
                },
                "required": ["items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="regions.v1",
            display_name="Regions",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_image": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "selected_frame_index": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "region_id": {"type": "string"},
                                "score": {"type": "number"},
                                "class_id": {"type": "integer"},
                                "class_name": {"type": "string"},
                                "bbox_xyxy": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "polygon_xy": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "mask_image": {"type": "object"},
                                "area": {"type": "integer", "minimum": 0},
                                "prompt_id": {"type": "string"},
                                "source_prompt_text": {"type": "string"},
                                "source_prompt_positive_texts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "source_prompt_negative_texts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "track_id": {"type": "string"},
                                "frame_index": {"type": "integer", "minimum": 0},
                                "timestamp_ms": {"type": "number", "minimum": 0},
                                "state": {"type": "string"},
                            },
                            "required": [
                                "region_id",
                                "score",
                                "class_id",
                                "class_name",
                                "bbox_xyxy",
                                "polygon_xy",
                                "area",
                            ],
                        },
                    },
                },
                "required": ["count", "items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="contours.v1",
            display_name="Contours",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_image": _build_image_ref_json_schema(),
                    "source_object_key": {"type": "string"},
                    "count": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "contour_index": {"type": "integer", "minimum": 0},
                                "point_count": {"type": "integer", "minimum": 0},
                                "bbox_xyxy": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "points": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                            },
                            "required": ["contour_index", "bbox_xyxy", "points"],
                        },
                    },
                },
                "required": ["items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="roi.v1",
            display_name="Region Of Interest",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "roi_id": {"type": "string"},
                    "display_name": {"type": "string"},
                    "roi_kind": {
                        "type": "string",
                        "enum": ["bbox", "polygon"],
                    },
                    "bbox_xyxy": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "polygon_xy": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                    },
                    "area": {"type": "integer", "minimum": 0},
                    "source_image": {"type": "object"},
                },
                "required": ["roi_id", "roi_kind", "bbox_xyxy", "polygon_xy", "area"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="roi-list.v1",
            display_name="ROI List",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "format_id": {
                        "type": "string",
                        "const": "amvision.roi-list.v1",
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "roi_id": {"type": "string"},
                                "display_name": {"type": "string"},
                                "roi_kind": {
                                    "type": "string",
                                    "enum": ["bbox", "polygon"],
                                },
                                "bbox_xyxy": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "polygon_xy": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "area": {"type": "integer", "minimum": 0},
                                "source_image": {"type": "object"},
                            },
                            "required": [
                                "roi_id",
                                "roi_kind",
                                "bbox_xyxy",
                                "polygon_xy",
                                "area",
                            ],
                        },
                    },
                    "count": {"type": "integer", "minimum": 0},
                },
                "required": ["format_id", "items", "count"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="result-record.v1",
            display_name="Inspection Result Record",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "ok_ng": {
                        "type": "string",
                        "enum": ["OK", "NG"],
                    },
                    "ok": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "metrics": {},
                    "conditions": {},
                    "alarm": {"type": "object"},
                    "image": {"type": "object"},
                    "video": {"type": "object"},
                    "metadata": {"type": "object"},
                },
                "required": ["ok_ng", "ok"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="alarm-record.v1",
            display_name="Inspection Alarm Record",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "active": {"type": "boolean"},
                    "level": {
                        "type": "string",
                        "enum": ["info", "warning", "error", "critical"],
                    },
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "metrics": {},
                    "metadata": {"type": "object"},
                    "image": {"type": "object"},
                    "video": {"type": "object"},
                },
                "required": ["active", "level", "message"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="detections.v1",
            display_name="Detection Result",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "bbox_xyxy": {"type": "array"},
                                "score": {"type": "number"},
                                "class_name": {"type": "string"},
                            },
                            "required": ["bbox_xyxy", "score"],
                        },
                    }
                },
                "required": ["items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="categories.v1",
            display_name="Classification Categories",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_image": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "class_id": {"type": "integer"},
                                "class_name": {"type": "string"},
                                "probability": {"type": "number"},
                                "logit": {"type": "number"},
                            },
                            "required": ["class_id", "probability"],
                        },
                    },
                    "top_item": {"type": "object"},
                    "image_width": {"type": "integer", "minimum": 0},
                    "image_height": {"type": "integer", "minimum": 0},
                    "latency_ms": {"type": "number", "minimum": 0},
                    "runtime_session_info": {"type": "object"},
                    "metadata": {"type": "object"},
                },
                "required": ["count", "items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="poses.v1",
            display_name="Pose Instances",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_image": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pose_id": {"type": "string"},
                                "score": {"type": "number"},
                                "class_id": {"type": "integer"},
                                "class_name": {"type": "string"},
                                "bbox_xyxy": {"type": "array"},
                                "keypoints": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "x": {"type": "number"},
                                            "y": {"type": "number"},
                                            "confidence": {"type": "number"},
                                        },
                                        "required": ["x", "y"],
                                    },
                                },
                                "kpt_shape": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "minItems": 2,
                                    "maxItems": 2,
                                },
                            },
                            "required": ["pose_id", "score", "bbox_xyxy", "keypoints"],
                        },
                    },
                    "image_width": {"type": "integer", "minimum": 0},
                    "image_height": {"type": "integer", "minimum": 0},
                    "latency_ms": {"type": "number", "minimum": 0},
                    "runtime_session_info": {"type": "object"},
                    "metadata": {"type": "object"},
                },
                "required": ["count", "items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="obbs.v1",
            display_name="OBB Instances",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "source_image": {"type": "object"},
                    "count": {"type": "integer", "minimum": 0},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "obb_id": {"type": "string"},
                                "score": {"type": "number"},
                                "class_id": {"type": "integer"},
                                "class_name": {"type": "string"},
                                "bbox_xyxy": {"type": "array"},
                                "angle": {"type": "number"},
                            },
                            "required": ["obb_id", "score", "bbox_xyxy"],
                        },
                    },
                    "image_width": {"type": "integer", "minimum": 0},
                    "image_height": {"type": "integer", "minimum": 0},
                    "latency_ms": {"type": "number", "minimum": 0},
                    "runtime_session_info": {"type": "object"},
                    "metadata": {"type": "object"},
                },
                "required": ["count", "items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="response-body.v1",
            display_name="Response Body",
            transport_kind="inline-json",
            json_schema={"type": "object"},
        ),
        WorkflowPayloadContract(
            payload_type_id="http-response.v1",
            display_name="HTTP Response",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "object"},
                },
                "required": ["status_code", "body"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="workflow-result.v1",
            display_name="Workflow Result",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["succeeded", "failed", "accepted", "partial"],
                    },
                    "code": {"type": "integer"},
                    "message": {"type": "string"},
                    "data": {},
                    "metrics": {},
                    "files": {},
                    "trace_id": {"type": "string"},
                    "event_id": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["status", "code", "message"],
            },
        ),
    )


@lru_cache(maxsize=1)
def get_core_workflow_node_definitions() -> tuple[NodeDefinition, ...]:
    """返回 backend 内建的最小 core node 目录。

    返回：
    - tuple[NodeDefinition, ...]：从 core_nodes 目录扫描得到的 NodeDefinition 列表。
    """

    return tuple(
        core_node_spec.node_definition for core_node_spec in get_core_node_specs()
    )
