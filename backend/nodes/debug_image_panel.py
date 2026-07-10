"""Workflow 节点编辑态 debug image panel helper。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from backend.nodes.runtime_support import (
    RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64,
    RESPONSE_IMAGE_TRANSPORT_STORAGE_REF,
    build_response_image_payload,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.preview_display_outputs import (
    build_preview_run_artifact_object_key,
    read_preview_run_id,
)


DEBUG_IMAGE_PANEL_ENABLED_PARAMETER = "debug_image_panel_enabled"
DEBUG_IMAGE_PANEL_TRANSPORT_PARAMETER = "debug_image_panel_transport_mode"
DEBUG_IMAGE_PANELS_ENABLED_METADATA = "debug_image_panels_enabled"
DEFAULT_DEBUG_IMAGE_PANEL_TRANSPORT_MODE = RESPONSE_IMAGE_TRANSPORT_STORAGE_REF


def is_debug_image_panel_enabled(request: WorkflowNodeExecutionRequest) -> bool:
    """判断当前节点是否应该生成编辑态 debug 图片面板。

    参数：
    - request：当前节点执行请求。

    返回：
    - bool：节点参数和 Preview Run 执行元数据同时打开时返回 True。
    """

    return (
        request.parameters.get(DEBUG_IMAGE_PANEL_ENABLED_PARAMETER) is True
        and request.execution_metadata.get(DEBUG_IMAGE_PANELS_ENABLED_METADATA) is True
    )


def build_debug_image_preview_output(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: object,
    title: str,
    overlays: Iterable[Mapping[str, Any]] | None = None,
    interaction: Mapping[str, Any] | None = None,
    artifact_name: str = "debug-preview",
) -> dict[str, object]:
    """按约定构造普通节点的 debug_preview 输出。

    参数：
    - request：当前节点执行请求。
    - image_payload：要显示的 image-ref payload，通常是节点输入图。
    - title：图片面板标题。
    - overlays：可选图形覆盖层，用于 ROI、四点、圆、线等取参提示。
    - interaction：可选交互语义，前端据此决定启用哪类取参工具。
    - artifact_name：storage-ref 自动保存时使用的 artifact 名称。

    返回：
    - dict[str, object]：关闭时返回空 dict；打开时返回 {"debug_preview": image-preview body}。
    """

    if not is_debug_image_panel_enabled(request):
        return {}

    normalized_image_payload = require_image_payload(image_payload)
    response_transport_mode = _read_debug_transport_mode(request.parameters.get(DEBUG_IMAGE_PANEL_TRANSPORT_PARAMETER))
    output_object_key = None
    if response_transport_mode == RESPONSE_IMAGE_TRANSPORT_STORAGE_REF:
        output_object_key = _build_debug_preview_artifact_object_key(
            request,
            image_payload=normalized_image_payload,
            artifact_name=artifact_name,
        )
    response_image = build_response_image_payload(
        request,
        image_payload=normalized_image_payload,
        response_transport_mode=response_transport_mode,
        object_key=output_object_key,
        variant_name=artifact_name,
    )
    preview_body: dict[str, object] = {
        "type": "image-preview",
        "title": title,
        "image": response_image,
    }
    normalized_overlays = [dict(overlay) for overlay in overlays or ()]
    if normalized_overlays:
        preview_body["overlays"] = normalized_overlays
    if interaction is not None:
        preview_body["interaction"] = dict(interaction)
    return {"debug_preview": preview_body}


def build_debug_panel_parameter_schema() -> dict[str, object]:
    """返回节点可复用的 debug image panel 参数 schema。"""

    return {
        DEBUG_IMAGE_PANEL_ENABLED_PARAMETER: {
            "type": "boolean",
            "title": "显示调试图",
            "description": "仅编辑 Preview Run 使用；生产 runtime 默认不会生成调试图片。",
            "default": False,
        },
        DEBUG_IMAGE_PANEL_TRANSPORT_PARAMETER: {
            "type": "string",
            "title": "调试图返回方式",
            "description": "storage-ref 会保存为 Preview Run artifact；inline-base64 只适合小图快速调试。",
            "enum": [RESPONSE_IMAGE_TRANSPORT_STORAGE_REF, RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64],
            "default": DEFAULT_DEBUG_IMAGE_PANEL_TRANSPORT_MODE,
        },
    }


def _read_debug_transport_mode(raw_value: object) -> str:
    """读取 debug 图片返回方式。"""

    if raw_value is None or raw_value == "":
        return DEFAULT_DEBUG_IMAGE_PANEL_TRANSPORT_MODE
    if not isinstance(raw_value, str):
        raise InvalidRequestError("debug_image_panel_transport_mode 必须是字符串")
    normalized_value = raw_value.strip()
    if normalized_value not in {RESPONSE_IMAGE_TRANSPORT_STORAGE_REF, RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64}:
        raise InvalidRequestError("debug_image_panel_transport_mode 仅支持 storage-ref 或 inline-base64")
    return normalized_value


def _build_debug_preview_artifact_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: dict[str, object],
    artifact_name: str,
) -> str | None:
    """为 Preview Run 自动生成 debug 图片 artifact object key。"""

    preview_run_id = read_preview_run_id(request.execution_metadata)
    if preview_run_id is None:
        return None
    return build_preview_run_artifact_object_key(
        preview_run_id=preview_run_id,
        node_id=request.node_id,
        artifact_name=artifact_name,
        media_type=str(image_payload.get("media_type") or "image/png"),
    )
