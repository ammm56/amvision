"""frame-window 单帧读取节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _video_frame_window_item_get_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按索引从 frame-window.v1 中读取单帧 image-ref 和元数据。"""

    frame_window_payload = _require_frame_window_payload(request.input_values.get("frames"), node_id=request.node_id)
    resolved_index = _resolve_index(request)
    allow_negative = _read_optional_bool(request.parameters.get("allow_negative"), default=True)
    normalized_index = resolved_index
    items = frame_window_payload["items"]
    if normalized_index < 0 and allow_negative:
        normalized_index += len(items)
    if 0 <= normalized_index < len(items):
        frame_item = items[normalized_index]
        frame_meta = {
            "frame_index": frame_item["frame_index"],
            "timestamp_ms": frame_item["timestamp_ms"],
            "selected_index": normalized_index,
            "source_video": frame_window_payload.get("source_video"),
        }
        return {
            "image": dict(frame_item["image"]),
            "frame_meta": build_value_payload(frame_meta),
        }
    raise InvalidRequestError(
        "frame-window-item-get 节点索引越界",
        details={
            "node_id": request.node_id,
            "index": resolved_index,
            "normalized_index": normalized_index,
            "size": len(items),
        },
    )


def _require_frame_window_payload(payload: object, *, node_id: str) -> dict[str, object]:
    """校验 frame-window.v1 payload 并返回规范化结果。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "frame-window-item-get 节点要求 frames payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError(
            "frame-window-item-get 节点要求 frames.items 必须是非空数组",
            details={"node_id": node_id},
        )
    normalized_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                "frame-window-item-get 节点要求每个 frames.items 都必须是对象",
                details={"node_id": node_id, "item_index": item_index},
            )
        frame_index = raw_item.get("frame_index")
        timestamp_ms = raw_item.get("timestamp_ms")
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise InvalidRequestError(
                "frame-window-item-get 节点要求每个 frames.items.frame_index 都必须是非负整数",
                details={"node_id": node_id, "item_index": item_index, "frame_index": frame_index},
            )
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, (int, float))
            or float(timestamp_ms) < 0
        ):
            raise InvalidRequestError(
                "frame-window-item-get 节点要求每个 frames.items.timestamp_ms 都必须是非负数",
                details={"node_id": node_id, "item_index": item_index, "timestamp_ms": timestamp_ms},
            )
        try:
            normalized_image = require_image_payload(raw_item.get("image"))
        except InvalidRequestError as exc:
            raise InvalidRequestError(
                "frame-window-item-get 节点要求每个 frames.items.image 都必须是有效 image-ref",
                details={"node_id": node_id, "item_index": item_index, **(exc.details or {})},
            ) from exc
        normalized_items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(timestamp_ms),
                "image": normalized_image,
            }
        )
    return {
        "items": tuple(normalized_items),
        "source_video": payload.get("source_video"),
    }


def _resolve_index(request: WorkflowNodeExecutionRequest) -> int:
    """从输入端口或参数读取索引。"""

    index_payload = request.input_values.get("index")
    if index_payload is not None:
        raw_index = require_value_payload(index_payload, field_name="index")["value"]
    else:
        raw_index = request.parameters.get("index", 0)
    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        raise InvalidRequestError(
            "frame-window-item-get 节点要求 index 必须是整数",
            details={"node_id": request.node_id, "index": raw_index},
        )
    return raw_index


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("frame-window-item-get 节点的 allow_negative 必须是布尔值")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.frame-window-item-get",
        display_name="Get Frame",
        category="io.video",
        description="按索引从 frame-window.v1 中选出单帧 image-ref.v1，并输出对应帧元数据。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="frames",
                display_name="Frames",
                payload_type_id="frame-window.v1",
            ),
            NodePortDefinition(
                name="index",
                display_name="Index",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
            NodePortDefinition(
                name="frame_meta",
                display_name="Frame Meta",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "default": 0,
                    "title": "索引",
                    "description": "默认选第 1 帧；也可以从 index 输入端口动态指定。",
                },
                "allow_negative": {
                    "type": "boolean",
                    "default": True,
                    "title": "允许负索引",
                    "description": "为 true 时，-1 表示最后一帧。",
                },
            },
        },
        capability_tags=("io.video", "video.frame-window", "video.frame.read"),
    ),
    handler=_video_frame_window_item_get_handler,
)
