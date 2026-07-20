"""Workflow 节点编辑态 debug image panel helper。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from backend.nodes.runtime_support import (
    RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64,
    RESPONSE_IMAGE_TRANSPORT_STORAGE_REF,
    PREVIEW_DISPLAY_MEDIA_TYPE,
    build_preview_response_image_payload,
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
    output_object_key = _build_debug_preview_artifact_object_key(
        request,
        artifact_name=artifact_name,
        media_type=str(normalized_image_payload.get("media_type") or "image/png"),
    )
    display_object_key = _build_debug_preview_artifact_object_key(
        request,
        artifact_name=f"{artifact_name}-display",
        media_type=PREVIEW_DISPLAY_MEDIA_TYPE,
    )
    response_image = build_preview_response_image_payload(
        request,
        image_payload=normalized_image_payload,
        response_transport_mode=response_transport_mode,
        object_key=output_object_key,
        display_object_key=display_object_key,
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


def build_debug_panel_interaction(
    *,
    tools: Iterable[Mapping[str, Any]],
    controls: Iterable[Mapping[str, Any]] | None = None,
    mode: str = "edit",
    coordinate_space: str = "source-image",
) -> dict[str, object]:
    """构造 ImageViewer 交互声明。

    参数：
    - tools：节点支持的图像取参工具，例如 rect、circle、line、template-region。
    - controls：节点支持的实时调参控件，例如 slider、checkbox。
    - mode：交互模式，当前编辑态统一使用 edit。
    - coordinate_space：坐标空间，默认使用原图像素坐标。

    返回：
    - dict[str, object]：前端 ImageViewer 可直接消费的 interaction payload。
    """

    return {
        "mode": mode,
        "coordinate_space": coordinate_space,
        "tools": [dict(tool) for tool in tools],
        "controls": [dict(control) for control in controls or ()],
    }


def build_interaction_tool(
    tool: str,
    label: str,
    target_parameters: Iterable[str],
    *,
    clear_parameters: Iterable[str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """构造 ImageViewer 工具声明。

    参数：
    - tool：工具语义名称，例如 bbox、polygon、circle、match-line。
    - label：界面显示名称。
    - target_parameters：工具写回的节点参数列表。
    - clear_parameters：无草稿时“清除”操作删除的几何参数；不应包含算法调优参数。
    - extra：工具特有扩展字段，按需透传给前端。
    """

    payload: dict[str, object] = {
        "tool": tool,
        "label": label,
        "target_parameters": [str(parameter_name) for parameter_name in target_parameters],
    }
    if clear_parameters is not None:
        payload["clear_parameters"] = [
            str(parameter_name) for parameter_name in clear_parameters
        ]
    if extra:
        payload.update(dict(extra))
    return payload


def build_numeric_control(
    parameter_name: str,
    label: str,
    value: float | int,
    *,
    min_value: float,
    max_value: float,
    step: float,
) -> dict[str, object]:
    """构造 ImageViewer 实时调参使用的数值控件。"""

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


def build_number_control(
    parameter_name: str,
    label: str,
    value: float | int | str | None,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    step: float | None = None,
) -> dict[str, object]:
    """构造 ImageViewer 实时调参使用的可留空数值输入控件。"""

    normalized_value: object = "" if value is None else value
    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "number",
        "min": min_value,
        "max": max_value,
        "step": step,
        "value": normalized_value,
        "default_value": normalized_value,
    }


def build_select_control(
    parameter_name: str,
    label: str,
    value: object,
    *,
    options: Iterable[Mapping[str, Any] | tuple[object, object]],
) -> dict[str, object]:
    """构造 ImageViewer 实时调参使用的枚举选择控件。"""

    normalized_options: list[dict[str, object]] = []
    for option in options:
        if isinstance(option, Mapping):
            option_value = option.get("value")
            option_label = option.get("label", option_value)
        else:
            option_values = tuple(option)
            if len(option_values) < 2:
                continue
            option_value = option_values[0]
            option_label = option_values[1]
        normalized_options.append(
            {
                "value": option_value,
                "label": str(option_label),
            }
        )
    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "select",
        "min": None,
        "max": None,
        "step": None,
        "value": value,
        "default_value": value,
        "options": normalized_options,
    }


def build_checkbox_control(parameter_name: str, label: str, value: bool) -> dict[str, object]:
    """构造 ImageViewer 实时调参使用的布尔控件。"""

    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "checkbox",
        "min": None,
        "max": None,
        "step": None,
        "value": bool(value),
        "default_value": bool(value),
    }


def build_bbox_overlay(
    *,
    overlay_id: str,
    label: str,
    bbox_xyxy: Iterable[float],
    kind: str = "bbox",
    target_parameters: Iterable[str] | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """构造矩形类 overlay。"""

    payload = _build_overlay_base(
        kind=kind,
        overlay_id=overlay_id,
        label=label,
        target_parameters=target_parameters,
        parameters=parameters,
    )
    payload["bbox_xyxy"] = [float(value) for value in bbox_xyxy]
    return payload


def build_circle_overlay(
    *,
    overlay_id: str,
    label: str,
    center_x: float,
    center_y: float,
    radius: float,
    kind: str = "circle",
    target_parameters: Iterable[str] | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """构造圆形类 overlay。"""

    payload = _build_overlay_base(
        kind=kind,
        overlay_id=overlay_id,
        label=label,
        target_parameters=target_parameters,
        parameters=parameters,
    )
    payload["circle"] = {
        "center_x": round(float(center_x), 4),
        "center_y": round(float(center_y), 4),
        "radius": round(float(radius), 4),
    }
    return payload


def build_line_overlay(
    *,
    overlay_id: str,
    label: str,
    line_xyxy: Iterable[float],
    kind: str = "line",
    target_parameters: Iterable[str] | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """构造线段类 overlay。"""

    payload = _build_overlay_base(
        kind=kind,
        overlay_id=overlay_id,
        label=label,
        target_parameters=target_parameters,
        parameters=parameters,
    )
    payload["line_xyxy"] = [round(float(value), 4) for value in line_xyxy]
    return payload


def build_polygon_overlay(
    *,
    overlay_id: str,
    label: str,
    polygon_xy: Iterable[Iterable[float]],
    kind: str = "polygon",
    target_parameters: Iterable[str] | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """构造多边形类 overlay。"""

    payload = _build_overlay_base(
        kind=kind,
        overlay_id=overlay_id,
        label=label,
        target_parameters=target_parameters,
        parameters=parameters,
    )
    # debug preview overlay 协议使用 points_xy，节点 payload 本体才使用 polygon_xy。
    points_xy: list[list[float]] = []
    for point in polygon_xy:
        point_values = list(point)
        if len(point_values) < 2:
            continue
        points_xy.append([round(float(point_values[0]), 4), round(float(point_values[1]), 4)])
    payload["points_xy"] = points_xy
    return payload


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
    artifact_name: str,
    media_type: str,
) -> str | None:
    """为 Preview Run 自动生成 debug 图片 artifact object key。"""

    preview_run_id = read_preview_run_id(request.execution_metadata)
    if preview_run_id is None:
        return None
    return build_preview_run_artifact_object_key(
        preview_run_id=preview_run_id,
        node_id=request.node_id,
        artifact_name=artifact_name,
        media_type=media_type,
    )


def _build_overlay_base(
    *,
    kind: str,
    overlay_id: str,
    label: str,
    target_parameters: Iterable[str] | None,
    parameters: Mapping[str, Any] | None,
) -> dict[str, object]:
    """构造 overlay 公共字段，避免各节点手写协议字段。"""

    payload: dict[str, object] = {
        "kind": kind,
        "id": overlay_id,
        "label": label,
    }
    if target_parameters is not None:
        payload["target_parameters"] = [str(parameter_name) for parameter_name in target_parameters]
    if parameters is not None:
        payload["parameters"] = dict(parameters)
    return payload
