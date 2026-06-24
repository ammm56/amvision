"""Barcode/QR 节点 ZXing 解码执行工具。"""

from __future__ import annotations

import base64
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.runtime.images import load_image_matrix
from custom_nodes.barcode_protocol_nodes.backend.runtime.imports import require_barcode_runtime_imports
from custom_nodes.barcode_protocol_nodes.backend.runtime.results import build_bounds_xyxy
from custom_nodes.barcode_protocol_nodes.backend.runtime.validators import (
    normalize_json_safe_value,
    read_bool_parameter,
    stringify_enum_like,
)


_TEXT_MODE_MEMBER_NAMES = {
    "plain": "Plain",
    "hri": "HRI",
    "escaped": "Escaped",
    "hex": "Hex",
    "eci": "ECI",
    "hex-eci": "HexECI",
}

_BINARIZER_MEMBER_NAMES = {
    "local-average": "LocalAverage",
    "global-histogram": "GlobalHistogram",
    "fixed-threshold": "FixedThreshold",
    "bool-cast": "BoolCast",
}

_EAN_ADD_ON_SYMBOL_MEMBER_NAMES = {
    "ignore": "Ignore",
    "read": "Read",
    "require": "Require",
}


def decode_barcodes(
    request: WorkflowNodeExecutionRequest,
    *,
    barcode_format: object,
    requested_format: str,
) -> dict[str, object]:
    """执行指定制式的条码解码，并构造统一结果 payload。

    参数：
    - request：当前节点执行请求。
    - barcode_format：zxingcpp 中的目标 BarcodeFormat。
    - requested_format：当前节点面向 workflow 暴露的目标格式名称。

    返回：
    - dict[str, object]：统一 barcode-results.v1 payload。
    """

    _, _, zxing_module = require_barcode_runtime_imports()
    source_payload, source_object_key, image_matrix = load_image_matrix(request)
    decoded_items = zxing_module.read_barcodes(
        image_matrix,
        formats=barcode_format,
        try_rotate=read_bool_parameter(request, field_name="try_rotate", default=True),
        try_downscale=read_bool_parameter(request, field_name="try_downscale", default=True),
        try_invert=read_bool_parameter(request, field_name="try_invert", default=True),
        text_mode=_resolve_text_mode(request, zxing_module=zxing_module),
        binarizer=_resolve_binarizer(request, zxing_module=zxing_module),
        is_pure=read_bool_parameter(request, field_name="is_pure", default=False),
        ean_add_on_symbol=_resolve_ean_add_on_symbol(request, zxing_module=zxing_module),
        return_errors=read_bool_parameter(request, field_name="return_errors", default=False),
    )

    items = [
        _build_barcode_item(index=index, barcode=barcode)
        for index, barcode in enumerate(decoded_items, start=1)
    ]
    payload: dict[str, object] = {
        "requested_format": requested_format,
        "source_image": dict(source_payload),
        "count": len(items),
        "matched_formats": list(dict.fromkeys(item["format"] for item in items if isinstance(item.get("format"), str))),
        "items": items,
    }
    if source_object_key is not None:
        payload["source_object_key"] = source_object_key
    return payload


def build_decode_handler(*, format_member_name: str, requested_format: str):
    """为指定 zxingcpp BarcodeFormat 构造统一 decode handler。

    参数：
    - format_member_name：zxingcpp.BarcodeFormat 的成员名称。
    - requested_format：workflow 输出中的目标格式标签。

    返回：
    - Callable[[WorkflowNodeExecutionRequest], dict[str, object]]：对应节点 handler。
    """

    def _handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        """执行单个 Barcode 节点的条码解码。"""

        _, _, zxing_module = require_barcode_runtime_imports()
        return {
            "results": decode_barcodes(
                request,
                barcode_format=getattr(zxing_module.BarcodeFormat, format_member_name),
                requested_format=requested_format,
            )
        }

    return _handle_node


def _build_barcode_item(*, index: int, barcode: object) -> dict[str, object]:
    """把单个 zxingcpp Barcode 结果规范化为 JSON 安全结构。

    参数：
    - index：当前条码结果序号。
    - barcode：zxingcpp 返回的单个 Barcode 对象。

    返回：
    - dict[str, object]：可放入 barcode-results.v1.items 的结果对象。
    """

    position_payload = _build_position_payload(getattr(barcode, "position"))
    raw_bytes = getattr(barcode, "bytes", b"")
    if not isinstance(raw_bytes, bytes):
        raw_bytes = bytes(raw_bytes)

    item: dict[str, object] = {
        "index": index,
        "format": stringify_enum_like(getattr(barcode, "format", "")),
        "symbology": stringify_enum_like(getattr(barcode, "symbology", "")),
        "text": str(getattr(barcode, "text", "")),
        "raw_bytes_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "content_type": stringify_enum_like(getattr(barcode, "content_type", "")),
        "orientation": int(getattr(barcode, "orientation", 0)),
        "valid": bool(getattr(barcode, "valid", False)),
        "position": position_payload,
    }
    symbology_identifier = getattr(barcode, "symbology_identifier", None)
    if isinstance(symbology_identifier, str) and symbology_identifier:
        item["symbology_identifier"] = symbology_identifier
    ec_level = getattr(barcode, "ec_level", None)
    if isinstance(ec_level, str) and ec_level:
        item["ec_level"] = ec_level
    error = getattr(barcode, "error", None)
    if error is not None:
        item["error"] = str(error)
    extra = getattr(barcode, "extra", None)
    if isinstance(extra, dict) and extra:
        item["extra"] = normalize_json_safe_value(extra)
    return item


def _build_position_payload(position: object) -> dict[str, object]:
    """把 zxingcpp Position 转换为独立位置参考结构。"""

    top_left_xy = _build_point_xy(getattr(position, "top_left"))
    top_right_xy = _build_point_xy(getattr(position, "top_right"))
    bottom_right_xy = _build_point_xy(getattr(position, "bottom_right"))
    bottom_left_xy = _build_point_xy(getattr(position, "bottom_left"))
    polygon_xy = [top_left_xy, top_right_xy, bottom_right_xy, bottom_left_xy]
    bounds_xyxy = build_bounds_xyxy(polygon_xy)
    min_x, min_y, max_x, max_y = bounds_xyxy
    return {
        "top_left_xy": top_left_xy,
        "top_right_xy": top_right_xy,
        "bottom_right_xy": bottom_right_xy,
        "bottom_left_xy": bottom_left_xy,
        "polygon_xy": polygon_xy,
        "bounds_xyxy": bounds_xyxy,
        "center_xy": [
            (float(min_x) + float(max_x)) / 2.0,
            (float(min_y) + float(max_y)) / 2.0,
        ],
        "size_wh": [max_x - min_x, max_y - min_y],
    }


def _build_point_xy(point: object) -> list[int]:
    """把 zxingcpp Point 转换为 [x, y]。"""

    point_x = getattr(point, "x", None)
    point_y = getattr(point, "y", None)
    if not isinstance(point_x, (int, float)) or not isinstance(point_y, (int, float)):
        raise ServiceConfigurationError("Barcode 结果中的点坐标格式无效")
    return [int(round(float(point_x))), int(round(float(point_y)))]


def _resolve_ean_add_on_symbol(request: WorkflowNodeExecutionRequest, *, zxing_module: Any) -> object:
    """把 workflow 参数中的 ean_add_on_symbol 映射到 zxingcpp EanAddOnSymbol。"""

    raw_value = request.parameters.get("ean_add_on_symbol")
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        raw_value = "ignore"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(
            "ean_add_on_symbol 参数必须是字符串",
            details={"node_id": request.node_id},
        )
    normalized_value = raw_value.strip().lower()
    member_name = _EAN_ADD_ON_SYMBOL_MEMBER_NAMES.get(normalized_value)
    if member_name is None:
        raise InvalidRequestError(
            "ean_add_on_symbol 参数不受支持",
            details={"node_id": request.node_id, "ean_add_on_symbol": raw_value},
        )
    return getattr(zxing_module.EanAddOnSymbol, member_name)


def _resolve_text_mode(request: WorkflowNodeExecutionRequest, *, zxing_module: Any) -> object:
    """把 workflow 参数中的 text_mode 映射到 zxingcpp TextMode。"""

    raw_value = request.parameters.get("text_mode")
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        raw_value = "hri"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("text_mode 参数必须是字符串", details={"node_id": request.node_id})
    normalized_value = raw_value.strip().lower()
    member_name = _TEXT_MODE_MEMBER_NAMES.get(normalized_value)
    if member_name is None:
        raise InvalidRequestError(
            "text_mode 参数不受支持",
            details={"node_id": request.node_id, "text_mode": raw_value},
        )
    return getattr(zxing_module.TextMode, member_name)


def _resolve_binarizer(request: WorkflowNodeExecutionRequest, *, zxing_module: Any) -> object:
    """把 workflow 参数中的 binarizer 映射到 zxingcpp Binarizer。"""

    raw_value = request.parameters.get("binarizer")
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        raw_value = "local-average"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("binarizer 参数必须是字符串", details={"node_id": request.node_id})
    normalized_value = raw_value.strip().lower()
    member_name = _BINARIZER_MEMBER_NAMES.get(normalized_value)
    if member_name is None:
        raise InvalidRequestError(
            "binarizer 参数不受支持",
            details={"node_id": request.node_id, "binarizer": raw_value},
        )
    return getattr(zxing_module.Binarizer, member_name)
