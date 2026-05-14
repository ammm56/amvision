"""Barcode/QR 协议节点包 backend 共享 helper。"""

from __future__ import annotations

import base64
import re
from typing import Any

from backend.nodes.runtime_support import load_image_bytes, register_image_bytes, require_image_payload, write_image_bytes
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


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


def require_barcode_runtime_imports() -> tuple[Any, Any, Any]:
    """加载 Barcode/QR 节点运行所需的依赖。

    返回：
    - tuple[Any, Any, Any]：cv2、numpy、zxingcpp 模块。
    """

    try:
        import cv2
        import numpy as np
        import zxingcpp
    except ImportError as error:  # pragma: no cover - 仅在运行环境缺依赖时触发
        raise ServiceConfigurationError("当前运行环境缺少 zxing-cpp、opencv-python 或 numpy 依赖") from error
    return cv2, np, zxingcpp


def build_output_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    source_payload: dict[str, object],
    content: bytes,
    width: int,
    height: int,
    media_type: str,
    variant_name: str,
    output_extension: str,
    object_key: str | None = None,
) -> dict[str, object]:
    """根据可选 object_key 选择 storage 或 memory 模式输出图片。"""

    normalized_object_key = normalize_optional_object_key(object_key)
    if normalized_object_key is not None:
        return write_image_bytes(
            request,
            source_payload=source_payload,
            content=content,
            object_key=normalized_object_key,
            variant_name=variant_name,
            output_extension=output_extension,
            width=width,
            height=height,
            media_type=media_type,
        )
    return register_image_bytes(
        request,
        content=content,
        media_type=media_type,
        width=width,
        height=height,
    )


def load_image_matrix(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
    imdecode_flags: int | None = None,
) -> tuple[dict[str, object], str | None, Any]:
    """按多来源 image-ref 规则读取图片输入，并解码为 OpenCV matrix。

    参数：
    - request：当前节点执行请求。
    - input_name：输入端口名称。
    - imdecode_flags：OpenCV 解码标志；未提供时使用 IMREAD_COLOR。

    返回：
    - tuple[dict[str, object], str | None, Any]：规范化图片 payload、可选 source_object_key 和解码后的图片矩阵。
    """

    cv2_module, np_module, _ = require_barcode_runtime_imports()
    image_payload, image_bytes = load_image_bytes(request, input_name=input_name)
    image_buffer = np_module.frombuffer(image_bytes, dtype=np_module.uint8)
    image_matrix = cv2_module.imdecode(
        image_buffer,
        cv2_module.IMREAD_COLOR if imdecode_flags is None else imdecode_flags,
    )
    if image_matrix is None:
        error_details = {
            "node_id": request.node_id,
            "transport_kind": image_payload.get("transport_kind"),
            "media_type": image_payload.get("media_type"),
        }
        source_object_key = image_payload.get("object_key")
        if isinstance(source_object_key, str) and source_object_key:
            error_details["object_key"] = source_object_key
        raise InvalidRequestError(
            "Barcode 节点无法读取输入图片",
            details=error_details,
        )
    resolved_source_object_key = image_payload.get("object_key")
    return (
        image_payload,
        resolved_source_object_key if isinstance(resolved_source_object_key, str) and resolved_source_object_key else None,
        image_matrix,
    )


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
        try_rotate=_read_bool_parameter(request, field_name="try_rotate", default=True),
        try_downscale=_read_bool_parameter(request, field_name="try_downscale", default=True),
        try_invert=_read_bool_parameter(request, field_name="try_invert", default=True),
        text_mode=_resolve_text_mode(request, zxing_module=zxing_module),
        binarizer=_resolve_binarizer(request, zxing_module=zxing_module),
        is_pure=_read_bool_parameter(request, field_name="is_pure", default=False),
        ean_add_on_symbol=_resolve_ean_add_on_symbol(request, zxing_module=zxing_module),
        return_errors=_read_bool_parameter(request, field_name="return_errors", default=False),
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


def require_barcode_results_payload(payload: object) -> dict[str, object]:
    """校验并规范化 barcode-results payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("barcode 节点要求 barcode-results payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("barcode-results.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("barcode-results.items 中的每一项都必须是对象")
        normalized_item = dict(item)
        normalized_item["index"] = int(item.get("index", index))
        normalized_item["position"] = require_barcode_position_payload(item.get("position"))
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    matched_formats = payload.get("matched_formats")
    if isinstance(matched_formats, list):
        normalized_payload["matched_formats"] = [str(item) for item in matched_formats]
    else:
        normalized_payload["matched_formats"] = [
            str(item.get("format")) for item in normalized_items if isinstance(item.get("format"), str)
        ]
    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        normalized_payload["source_image"] = require_image_payload(source_image)
    resolved_source_object_key = normalized_payload.get("source_object_key")
    if not isinstance(resolved_source_object_key, str) or not resolved_source_object_key:
        normalized_source_image = normalized_payload.get("source_image")
        if isinstance(normalized_source_image, dict):
            source_object_key = normalized_source_image.get("object_key")
            if isinstance(source_object_key, str) and source_object_key:
                normalized_payload["source_object_key"] = source_object_key
    return normalized_payload


def filter_barcode_results_payload(
    results_payload: object,
    *,
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    """按参数条件筛选 barcode-results payload。

    参数：
    - results_payload：输入的 barcode-results.v1 payload。
    - parameters：筛选参数字典。

    返回：
    - dict[str, object]：筛选后的 barcode-results.v1 payload。
    """

    normalized_payload = require_barcode_results_payload(results_payload)
    normalized_parameters = parameters if isinstance(parameters, dict) else {}
    filtered_items = [
        item for item in normalized_payload["items"] if _barcode_item_matches_parameters(item, normalized_parameters)
    ]
    return _rebuild_barcode_results_payload(normalized_payload, filtered_items)


def build_barcode_results_summary(results_payload: object) -> dict[str, object]:
    """把 barcode-results payload 转换为更轻量的业务摘要对象。

    参数：
    - results_payload：输入的 barcode-results.v1 payload。

    返回：
    - dict[str, object]：便于 workflow 分支直接读取的摘要结构。
    """

    normalized_payload = require_barcode_results_payload(results_payload)
    items = normalized_payload["items"]
    summary_items = [_build_summary_item(item) for item in items]
    format_counts: dict[str, int] = {}
    texts: list[str] = []
    indices: list[int] = []
    valid_count = 0

    for item in items:
        item_format = item.get("format")
        if isinstance(item_format, str) and item_format:
            format_counts[item_format] = format_counts.get(item_format, 0) + 1
        item_text = item.get("text")
        if isinstance(item_text, str):
            texts.append(item_text)
        indices.append(int(item.get("index", 0)))
        if bool(item.get("valid", False)):
            valid_count += 1

    first_item = items[0] if items else None
    return {
        "type": "barcode-results-summary.v1",
        "requested_format": normalized_payload.get("requested_format"),
        "source_object_key": normalized_payload.get("source_object_key"),
        "count": len(items),
        "has_items": bool(items),
        "matched_formats": list(normalized_payload.get("matched_formats", [])),
        "items": summary_items,
        "indices": indices,
        "texts": texts,
        "format_counts": format_counts,
        "valid_count": valid_count,
        "invalid_count": len(items) - valid_count,
        "all_valid": valid_count == len(items),
        "first_index": int(first_item.get("index", 0)) if isinstance(first_item, dict) else None,
        "first_text": first_item.get("text") if isinstance(first_item, dict) else None,
        "first_format": first_item.get("format") if isinstance(first_item, dict) else None,
        "first_item": _build_summary_item(first_item) if isinstance(first_item, dict) else None,
    }


def require_barcode_position_payload(payload: object) -> dict[str, object]:
    """校验并规范化单个条码结果中的 position 结构。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("barcode 结果中的 position 必须是对象")
    polygon_xy = payload.get("polygon_xy")
    if not isinstance(polygon_xy, list) or len(polygon_xy) < 4:
        raise InvalidRequestError("barcode position.polygon_xy 至少包含四个点")
    normalized_polygon_xy = [_normalize_xy_point(point) for point in polygon_xy[:4]]

    normalized_payload = dict(payload)
    normalized_payload["polygon_xy"] = normalized_polygon_xy
    for field_name in ("top_left_xy", "top_right_xy", "bottom_right_xy", "bottom_left_xy"):
        if field_name in payload:
            normalized_payload[field_name] = _normalize_xy_point(payload[field_name])
    if "top_left_xy" not in normalized_payload:
        normalized_payload["top_left_xy"] = normalized_polygon_xy[0]
    if "top_right_xy" not in normalized_payload:
        normalized_payload["top_right_xy"] = normalized_polygon_xy[1]
    if "bottom_right_xy" not in normalized_payload:
        normalized_payload["bottom_right_xy"] = normalized_polygon_xy[2]
    if "bottom_left_xy" not in normalized_payload:
        normalized_payload["bottom_left_xy"] = normalized_polygon_xy[3]

    bounds_xyxy = payload.get("bounds_xyxy")
    if isinstance(bounds_xyxy, (list, tuple)) and len(bounds_xyxy) >= 4:
        normalized_payload["bounds_xyxy"] = [int(round(float(value))) for value in bounds_xyxy[:4]]
    else:
        normalized_payload["bounds_xyxy"] = _build_bounds_xyxy(normalized_polygon_xy)

    center_xy = payload.get("center_xy")
    if isinstance(center_xy, (list, tuple)) and len(center_xy) >= 2:
        normalized_payload["center_xy"] = [float(center_xy[0]), float(center_xy[1])]
    else:
        x1, y1, x2, y2 = normalized_payload["bounds_xyxy"]
        normalized_payload["center_xy"] = [(float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0]

    size_wh = payload.get("size_wh")
    if isinstance(size_wh, (list, tuple)) and len(size_wh) >= 2:
        normalized_payload["size_wh"] = [int(round(float(size_wh[0]))), int(round(float(size_wh[1])))]
    else:
        x1, y1, x2, y2 = normalized_payload["bounds_xyxy"]
        normalized_payload["size_wh"] = [int(x2 - x1), int(y2 - y1)]
    return normalized_payload


def iter_barcode_result_items(results_payload: object) -> list[dict[str, object]]:
    """把 barcode-results payload 规范化为结果项列表。"""

    return list(require_barcode_results_payload(results_payload)["items"])


def _build_summary_item(item: dict[str, object]) -> dict[str, object]:
    """提取单个条码结果的轻量摘要。"""

    summary_item: dict[str, object] = {
        "index": int(item.get("index", 0)),
        "format": item.get("format"),
        "text": item.get("text"),
        "valid": bool(item.get("valid", False)),
    }
    item_position = item.get("position")
    if isinstance(item_position, dict) and "bounds_xyxy" in item_position:
        summary_item["bounds_xyxy"] = list(item_position["bounds_xyxy"])
    return summary_item


def _rebuild_barcode_results_payload(
    normalized_payload: dict[str, object],
    filtered_items: list[dict[str, object]],
) -> dict[str, object]:
    """基于筛选后的结果项重建 barcode-results payload。"""

    rebuilt_payload: dict[str, object] = {
        "requested_format": normalized_payload.get("requested_format"),
        "count": len(filtered_items),
        "matched_formats": list(
            dict.fromkeys(
                item.get("format")
                for item in filtered_items
                if isinstance(item.get("format"), str) and item.get("format")
            )
        ),
        "items": [dict(item) for item in filtered_items],
    }
    source_image = normalized_payload.get("source_image")
    if isinstance(source_image, dict):
        rebuilt_payload["source_image"] = dict(source_image)
    source_object_key = normalized_payload.get("source_object_key")
    if isinstance(source_object_key, str) and source_object_key:
        rebuilt_payload["source_object_key"] = source_object_key
    return rebuilt_payload


def _barcode_item_matches_parameters(item: dict[str, object], parameters: dict[str, object]) -> bool:
    """判断单个条码结果项是否满足筛选条件。"""

    ignore_case = _read_optional_bool(parameters.get("ignore_case"), default=True)
    if not _match_formats(item, parameters.get("formats"), ignore_case=ignore_case):
        return False
    if not _match_text(item, parameters, ignore_case=ignore_case):
        return False
    if not _match_index(item, parameters):
        return False
    if not _match_region(item, parameters):
        return False
    return True


def _match_formats(item: dict[str, object], raw_formats: object, *, ignore_case: bool) -> bool:
    """按 format 条件判断是否匹配。"""

    formats = _normalize_string_list(raw_formats, field_name="formats")
    if not formats:
        return True
    item_candidates = [item.get("format"), item.get("symbology")]
    normalized_candidates = {
        _normalize_match_text(candidate, ignore_case=ignore_case)
        for candidate in item_candidates
        if isinstance(candidate, str) and candidate.strip()
    }
    normalized_formats = {_normalize_match_text(value, ignore_case=ignore_case) for value in formats}
    return bool(normalized_candidates.intersection(normalized_formats))


def _match_text(item: dict[str, object], parameters: dict[str, object], *, ignore_case: bool) -> bool:
    """按 text 条件判断是否匹配。"""

    item_text = item.get("text")
    normalized_item_text = item_text if isinstance(item_text, str) else ""
    comparable_text = _normalize_match_text(normalized_item_text, ignore_case=ignore_case)

    text_equals = parameters.get("text_equals")
    if isinstance(text_equals, str) and text_equals.strip():
        if comparable_text != _normalize_match_text(text_equals, ignore_case=ignore_case):
            return False

    text_contains = parameters.get("text_contains")
    if isinstance(text_contains, str) and text_contains.strip():
        if _normalize_match_text(text_contains, ignore_case=ignore_case) not in comparable_text:
            return False

    text_regex = parameters.get("text_regex")
    if isinstance(text_regex, str) and text_regex.strip():
        regex_flags = re.IGNORECASE if ignore_case else 0
        if re.search(text_regex, normalized_item_text, flags=regex_flags) is None:
            return False

    return True


def _match_index(item: dict[str, object], parameters: dict[str, object]) -> bool:
    """按 index 条件判断是否匹配。"""

    item_index = int(item.get("index", 0))
    indices = _normalize_int_list(parameters.get("indices"), field_name="indices")
    if indices and item_index not in set(indices):
        return False

    min_index = parameters.get("min_index")
    if min_index is not None and item_index < int(min_index):
        return False

    max_index = parameters.get("max_index")
    if max_index is not None and item_index > int(max_index):
        return False
    return True


def _match_region(item: dict[str, object], parameters: dict[str, object]) -> bool:
    """按区域范围条件判断是否匹配。"""

    region_bounds = _normalize_region_bounds(parameters.get("region_bounds_xyxy"))
    if region_bounds is None:
        return True
    position_payload = require_barcode_position_payload(item.get("position"))
    item_bounds = _normalize_region_bounds(position_payload.get("bounds_xyxy"))
    if item_bounds is None:
        return False

    region_match_mode = parameters.get("region_match_mode", "intersects")
    if not isinstance(region_match_mode, str):
        raise InvalidRequestError("region_match_mode 必须是字符串")
    normalized_mode = region_match_mode.strip().lower()
    if normalized_mode == "intersects":
        return _bounds_intersect(item_bounds, region_bounds)
    if normalized_mode == "center-in":
        center_xy = position_payload.get("center_xy")
        if not isinstance(center_xy, list) or len(center_xy) < 2:
            return False
        return _point_in_bounds(float(center_xy[0]), float(center_xy[1]), region_bounds)
    if normalized_mode == "bounds-in":
        return _bounds_in_bounds(item_bounds, region_bounds)
    raise InvalidRequestError("region_match_mode 不受支持")


def _normalize_match_text(value: str, *, ignore_case: bool) -> str:
    """规范化匹配用文本。"""

    normalized_value = value.strip()
    return normalized_value.casefold() if ignore_case else normalized_value


def _normalize_string_list(value: object, *, field_name: str) -> list[str]:
    """把数组或逗号分隔字符串解析为字符串列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list):
        raise InvalidRequestError(f"{field_name} 必须是数组或字符串")
    normalized_values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidRequestError(f"{field_name} 中的每一项都必须是字符串")
        if item.strip():
            normalized_values.append(item.strip())
    return normalized_values


def _normalize_int_list(value: object, *, field_name: str) -> list[int]:
    """把数组或逗号分隔字符串解析为整数列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
        return [int(item) for item in raw_items]
    if not isinstance(value, list):
        raise InvalidRequestError(f"{field_name} 必须是数组或字符串")
    return [int(item) for item in value]


def _normalize_region_bounds(value: object) -> list[int] | None:
    """把区域范围参数解析为 [x1, y1, x2, y2]。"""

    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        raise InvalidRequestError("region_bounds_xyxy 必须是长度为 4 的数组")
    x1, y1, x2, y2 = [int(round(float(item))) for item in value[:4]]
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def _bounds_intersect(bounds_a: list[int], bounds_b: list[int]) -> bool:
    """判断两个矩形范围是否相交。"""

    return not (
        bounds_a[2] < bounds_b[0]
        or bounds_a[0] > bounds_b[2]
        or bounds_a[3] < bounds_b[1]
        or bounds_a[1] > bounds_b[3]
    )


def _bounds_in_bounds(inner_bounds: list[int], outer_bounds: list[int]) -> bool:
    """判断一个矩形是否完全位于另一个矩形内部。"""

    return (
        inner_bounds[0] >= outer_bounds[0]
        and inner_bounds[1] >= outer_bounds[1]
        and inner_bounds[2] <= outer_bounds[2]
        and inner_bounds[3] <= outer_bounds[3]
    )


def _point_in_bounds(x_value: float, y_value: float, bounds: list[int]) -> bool:
    """判断点是否位于指定矩形范围内。"""

    return bounds[0] <= x_value <= bounds[2] and bounds[1] <= y_value <= bounds[3]


def _read_optional_bool(value: object, *, default: bool) -> bool:
    """读取可选布尔值。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
    raise InvalidRequestError("布尔参数格式无效")


def build_barcode_label(
    *,
    item: dict[str, object],
    draw_text: bool,
    draw_format: bool,
    draw_index: bool,
) -> str:
    """根据 barcode 结果项生成叠加绘制标签文本。"""

    label_parts: list[str] = []
    if draw_index:
        label_parts.append(f"#{int(item.get('index', 0))}")
    if draw_format:
        item_format = item.get("format")
        if isinstance(item_format, str) and item_format.strip():
            label_parts.append(item_format.strip())
    if draw_text:
        item_text = item.get("text")
        if isinstance(item_text, str) and item_text.strip():
            label_parts.append(item_text.strip())
    return " | ".join(label_parts)


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
        "format": _stringify_enum_like(getattr(barcode, "format", "")),
        "symbology": _stringify_enum_like(getattr(barcode, "symbology", "")),
        "text": str(getattr(barcode, "text", "")),
        "raw_bytes_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "content_type": _stringify_enum_like(getattr(barcode, "content_type", "")),
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
        item["extra"] = _normalize_json_safe_value(extra)
    return item


def _build_position_payload(position: object) -> dict[str, object]:
    """把 zxingcpp Position 转换为独立位置参考结构。"""

    top_left_xy = _build_point_xy(getattr(position, "top_left"))
    top_right_xy = _build_point_xy(getattr(position, "top_right"))
    bottom_right_xy = _build_point_xy(getattr(position, "bottom_right"))
    bottom_left_xy = _build_point_xy(getattr(position, "bottom_left"))
    polygon_xy = [top_left_xy, top_right_xy, bottom_right_xy, bottom_left_xy]
    bounds_xyxy = _build_bounds_xyxy(polygon_xy)
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


def _normalize_xy_point(raw_point: object) -> list[int]:
    """把任意两点数组规范化为 [x, y] 整数坐标。"""

    if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
        raise InvalidRequestError("position 中的点必须包含 x 与 y")
    return [int(round(float(raw_point[0]))), int(round(float(raw_point[1])))]


def _build_bounds_xyxy(polygon_xy: list[list[int]]) -> list[int]:
    """从四点 polygon 计算位置参考矩形。"""

    x_values = [point[0] for point in polygon_xy]
    y_values = [point[1] for point in polygon_xy]
    return [min(x_values), min(y_values), max(x_values), max(y_values)]


def _resolve_ean_add_on_symbol(request: WorkflowNodeExecutionRequest, *, zxing_module: Any) -> object:
    """把 workflow 参数中的 ean_add_on_symbol 映射到 zxingcpp EanAddOnSymbol。"""

    raw_value = request.parameters.get("ean_add_on_symbol", "ignore")
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


def _read_bool_parameter(
    request: WorkflowNodeExecutionRequest,
    *,
    field_name: str,
    default: bool,
) -> bool:
    """读取布尔参数，并允许有限字符串形式。"""

    raw_value = request.parameters.get(field_name, default)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
    if raw_value is None:
        return default
    raise InvalidRequestError(
        f"{field_name} 参数必须是布尔值",
        details={"node_id": request.node_id, "field_name": field_name},
    )


def _resolve_text_mode(request: WorkflowNodeExecutionRequest, *, zxing_module: Any) -> object:
    """把 workflow 参数中的 text_mode 映射到 zxingcpp TextMode。"""

    raw_value = request.parameters.get("text_mode", "hri")
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

    raw_value = request.parameters.get("binarizer", "local-average")
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


def _stringify_enum_like(value: object) -> str:
    """把 enum 或类似对象转换为稳定字符串。"""

    if value is None:
        return ""
    normalized_text = str(value).strip()
    if normalized_text:
        return normalized_text
    member_name = getattr(value, "name", None)
    return member_name if isinstance(member_name, str) else ""


def _normalize_json_safe_value(value: object) -> object:
    """递归把对象转换为 JSON 安全结构。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        normalized_object: dict[str, object] = {}
        for key, item_value in value.items():
            normalized_object[str(key)] = _normalize_json_safe_value(item_value)
        return normalized_object
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json_safe_value(item) for item in value]
    return str(value)


def normalize_optional_object_key(value: object) -> str | None:
    """规范化可选 output_object_key 参数。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def require_positive_int(value: object, *, field_name: str) -> int:
    """把输入值解析为正整数。"""

    normalized_value = int(value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def require_non_negative_float(value: object, *, field_name: str) -> float:
    """把输入值解析为非负浮点数。"""

    normalized_value = float(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


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
