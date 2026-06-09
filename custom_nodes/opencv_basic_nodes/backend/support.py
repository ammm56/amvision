"""OpenCV 基础节点包 backend 共享 helper。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from backend.nodes.runtime_support import (
    build_runtime_image_object_key,
    load_image_bytes,
    register_image_bytes,
    require_image_payload,
    write_image_bytes,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


def require_opencv_imports() -> tuple[Any, Any]:
    """加载 OpenCV 与 NumPy 依赖。

    返回：
    - tuple[Any, Any]：cv2 模块和 numpy 模块。
    """

    try:
        import cv2
        import numpy as np
    except ImportError as error:  # pragma: no cover - 仅在运行环境缺依赖时触发
        raise ServiceConfigurationError("当前运行环境缺少 opencv-python 或 numpy 依赖") from error
    return cv2, np


def load_image_matrix(
    request: object,
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

    cv2_module, np_module = require_opencv_imports()
    image_payload, image_bytes = load_image_bytes(request, input_name=input_name)
    image_buffer = np_module.frombuffer(image_bytes, dtype=np_module.uint8)
    image_matrix = cv2_module.imdecode(
        image_buffer,
        cv2_module.IMREAD_COLOR if imdecode_flags is None else imdecode_flags,
    )
    if image_matrix is None:
        error_details = {
            "node_id": getattr(request, "node_id", ""),
            "transport_kind": image_payload.get("transport_kind"),
            "media_type": image_payload.get("media_type"),
        }
        source_object_key = image_payload.get("object_key")
        if isinstance(source_object_key, str) and source_object_key:
            error_details["object_key"] = source_object_key
        raise InvalidRequestError(
            "OpenCV 无法读取输入图片",
            details=error_details,
        )
    resolved_source_object_key = image_payload.get("object_key")
    return (
        image_payload,
        resolved_source_object_key if isinstance(resolved_source_object_key, str) and resolved_source_object_key else None,
        image_matrix,
    )


def build_output_image_payload(
    request: object,
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
    """根据可选 object_key 选择 storage 或 memory 模式输出图片。

    参数：
    - request：当前节点执行请求。
    - source_payload：源图片 payload。
    - content：编码后的图片字节。
    - width：输出图片宽度。
    - height：输出图片高度。
    - media_type：输出图片媒体类型。
    - variant_name：默认输出变体名。
    - output_extension：默认输出扩展名。
    - object_key：显式输出 object key；未提供时返回 memory image-ref。

    返回：
    - dict[str, object]：输出图片 payload。
    """

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


def encode_png_image_bytes(
    request: object,
    *,
    image_matrix: Any,
    error_message: str,
) -> bytes:
    """把 OpenCV matrix 编码为 PNG 字节。"""

    cv2_module, _ = require_opencv_imports()
    success, encoded_image = cv2_module.imencode(".png", image_matrix)
    if success is not True:
        raise ServiceConfigurationError(
            error_message,
            details={"node_id": getattr(request, "node_id", "")},
        )
    return encoded_image.tobytes()


def require_dataset_path(request: object, object_key: str):
    """把 object key 解析为本地绝对路径。

    参数：
    - request：当前节点执行请求。
    - object_key：图片 object key。

    返回：
    - Path：对应的本地绝对路径。
    """

    from backend.nodes.runtime_support import require_dataset_storage

    return require_dataset_storage(request).resolve(object_key)


def iter_detection_items(detections_payload: object) -> list[dict[str, object]]:
    """把 detection payload 规范化为列表。

    参数：
    - detections_payload：原始 detections payload。

    返回：
    - list[dict[str, object]]：规范化后的 detection item 列表。
    """

    if not isinstance(detections_payload, dict):
        raise InvalidRequestError("当前节点要求 detections payload 必须是对象")
    raw_items = detections_payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 detections.items 必须是数组")
    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 detection item 必须是对象")
        normalized_items.append(item)
    return normalized_items


def require_image_refs_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-refs payload。

    参数：
    - payload：待校验的图片集合 payload。

    返回：
    - dict[str, object]：规范化后的图片集合 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("gallery-preview 节点要求 image-refs payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("gallery-preview 节点要求 image-refs.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        normalized_item = require_image_payload(item)
        if isinstance(item, dict):
            if "bbox_xyxy" in item:
                normalized_item["bbox_xyxy"] = list(normalize_bbox(item.get("bbox_xyxy")))
            crop_index = item.get("crop_index")
            if isinstance(crop_index, (int, float)):
                normalized_item["crop_index"] = int(crop_index)
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
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


def require_contours_payload(payload: object) -> dict[str, object]:
    """校验并规范化 contours payload。

    参数：
    - payload：待校验的 contour payload。

    返回：
    - dict[str, object]：规范化后的 contour payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 contours payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 contours.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 contour item 必须是对象")
        raw_points = item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            raise InvalidRequestError("当前节点要求 contour.points 至少包含三个点")
        normalized_points: list[list[int]] = []
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise InvalidRequestError("当前节点要求 contour.points 中的每个点必须包含 x 与 y")
            point_x, point_y = point[:2]
            normalized_points.append([int(round(float(point_x))), int(round(float(point_y)))])
        normalized_item = dict(item)
        normalized_item["contour_index"] = int(item.get("contour_index", index))
        normalized_item["point_count"] = int(item.get("point_count", len(normalized_points)))
        normalized_item["bbox_xyxy"] = list(normalize_bbox(item.get("bbox_xyxy")))
        normalized_item["points"] = normalized_points
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
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


def build_contours_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建规范化后的 contours.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def build_lines_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建规范化后的 lines.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def build_circles_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建规范化后的 circles.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def require_lines_payload(payload: object) -> dict[str, object]:
    """校验并规范化 lines.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 lines payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 lines.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 line item 必须是对象")
        line_index = item.get("line_index", index)
        if isinstance(line_index, bool) or not isinstance(line_index, int):
            raise InvalidRequestError("当前节点要求 line_index 必须是整数")
        normalized_item = dict(item)
        normalized_item["line_index"] = int(line_index)
        normalized_item["start_xy"] = list(normalize_point_xy(item.get("start_xy"), field_name="start_xy"))
        normalized_item["end_xy"] = list(normalize_point_xy(item.get("end_xy"), field_name="end_xy"))
        normalized_item["length_pixels"] = require_number(item.get("length_pixels"), field_name="length_pixels")
        normalized_item["angle_deg"] = require_number(item.get("angle_deg"), field_name="angle_deg")
        if "midpoint_xy" in item:
            normalized_item["midpoint_xy"] = list(normalize_point_xy(item.get("midpoint_xy"), field_name="midpoint_xy"))
        if "bbox_xyxy" in item:
            normalized_item["bbox_xyxy"] = list(normalize_bbox_number(item.get("bbox_xyxy"), field_name="bbox_xyxy"))
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
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


def require_circles_payload(payload: object) -> dict[str, object]:
    """校验并规范化 circles.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 circles payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 circles.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 circle item 必须是对象")
        circle_index = item.get("circle_index", index)
        if isinstance(circle_index, bool) or not isinstance(circle_index, int):
            raise InvalidRequestError("当前节点要求 circle_index 必须是整数")
        normalized_item = dict(item)
        normalized_item["circle_index"] = int(circle_index)
        normalized_item["center_xy"] = list(normalize_point_xy(item.get("center_xy"), field_name="center_xy"))
        normalized_item["radius"] = require_number(item.get("radius"), field_name="radius")
        normalized_item["diameter"] = require_number(item.get("diameter"), field_name="diameter")
        normalized_item["area"] = require_number(item.get("area"), field_name="area")
        if "bbox_xyxy" in item:
            normalized_item["bbox_xyxy"] = list(normalize_bbox_number(item.get("bbox_xyxy"), field_name="bbox_xyxy"))
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
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


def select_line_item(
    items: list[dict[str, object]],
    *,
    strategy: str,
    line_index: int | None,
) -> dict[str, object]:
    """按策略选择一条 line item。"""

    if not items:
        raise InvalidRequestError("lines payload 不能为空")
    if strategy == "first":
        return dict(items[0])
    if strategy == "longest":
        return dict(max(items, key=lambda item: float(item["length_pixels"])))
    if strategy == "shortest":
        return dict(min(items, key=lambda item: float(item["length_pixels"])))
    if strategy == "line-index":
        if line_index is None:
            raise InvalidRequestError("line_strategy 为 line-index 时必须提供 line_index")
        for item in items:
            if int(item["line_index"]) == line_index:
                return dict(item)
        raise InvalidRequestError("指定的 line_index 不存在", details={"line_index": line_index})
    raise InvalidRequestError("line_strategy 不在支持的列表中")


def select_circle_item(
    items: list[dict[str, object]],
    *,
    strategy: str,
    circle_index: int | None,
) -> dict[str, object]:
    """按策略选择一条 circle item。"""

    if not items:
        raise InvalidRequestError("circles payload 不能为空")
    if strategy == "first":
        return dict(items[0])
    if strategy == "largest":
        return dict(max(items, key=lambda item: float(item["radius"])))
    if strategy == "smallest":
        return dict(min(items, key=lambda item: float(item["radius"])))
    if strategy == "circle-index":
        if circle_index is None:
            raise InvalidRequestError("circle_strategy 为 circle-index 时必须提供 circle_index")
        for item in items:
            if int(item["circle_index"]) == circle_index:
                return dict(item)
        raise InvalidRequestError("指定的 circle_index 不存在", details={"circle_index": circle_index})
    raise InvalidRequestError("circle_strategy 不在支持的列表中")


def resolve_contours_source_image(
    *,
    contours_payload: dict[str, object],
    image_payload: object | None,
) -> dict[str, object] | None:
    """优先读取显式 image 输入，否则回退到 contours.source_image。"""

    if image_payload is not None:
        return require_image_payload(image_payload)
    source_image = contours_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    return None


def normalize_bbox(raw_bbox: object) -> tuple[int, int, int, int]:
    """把 detection bbox 规范化为 OpenCV 可用的整数坐标。

    参数：
    - raw_bbox：原始 bbox 数据。

    返回：
    - tuple[int, int, int, int]：规范化后的 xyxy 整数坐标。
    """

    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        raise InvalidRequestError("bbox_xyxy 至少包含四个坐标")
    x1, y1, x2, y2 = raw_bbox[:4]
    return int(round(float(x1))), int(round(float(y1))), int(round(float(x2))), int(round(float(y2)))


def normalize_bbox_number(raw_bbox: object, *, field_name: str) -> tuple[float, float, float, float]:
    """把 bbox 规范化为数值 xyxy 坐标。"""

    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        raise InvalidRequestError(f"{field_name} 至少包含四个坐标")
    x1_value = require_number(raw_bbox[0], field_name=f"{field_name}[0]")
    y1_value = require_number(raw_bbox[1], field_name=f"{field_name}[1]")
    x2_value = require_number(raw_bbox[2], field_name=f"{field_name}[2]")
    y2_value = require_number(raw_bbox[3], field_name=f"{field_name}[3]")
    return x1_value, y1_value, x2_value, y2_value


def normalize_point_xy(raw_value: object, *, field_name: str) -> tuple[float, float]:
    """把点坐标规范化为数值 x/y。"""

    if not isinstance(raw_value, (list, tuple)) or len(raw_value) < 2:
        raise InvalidRequestError(f"{field_name} 必须包含两个坐标")
    point_x = require_number(raw_value[0], field_name=f"{field_name}[0]")
    point_y = require_number(raw_value[1], field_name=f"{field_name}[1]")
    return point_x, point_y


def build_detection_label(*, item: dict[str, object], draw_scores: bool) -> str:
    """根据 detection item 生成要绘制的标签文本。

    参数：
    - item：单个 detection item。
    - draw_scores：是否附带 score。

    返回：
    - str：要绘制的标签文本。
    """

    label_parts: list[str] = []
    class_name = item.get("class_name")
    if isinstance(class_name, str) and class_name.strip():
        label_parts.append(class_name.strip())
    score = item.get("score")
    if draw_scores and isinstance(score, (int, float)):
        label_parts.append(f"{float(score):.2f}")
    return " ".join(label_parts)


def require_positive_int(value: object, *, field_name: str) -> int:
    """把输入值解析为正整数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - int：规范化后的正整数。
    """

    normalized_value = int(value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def require_number(value: object, *, field_name: str) -> float:
    """把输入值解析为数值。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    return float(value)


def require_non_negative_float(value: object, *, field_name: str) -> float:
    """把输入值解析为非负浮点数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - float：规范化后的非负浮点数。
    """

    normalized_value = float(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def require_uint8_int(value: object, *, field_name: str) -> int:
    """把输入值解析为 0 到 255 之间的整数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - int：规范化后的整数。
    """

    normalized_value = require_non_negative_int(value, field_name=field_name)
    if normalized_value > 255:
        raise InvalidRequestError(f"{field_name} 不能大于 255")
    return normalized_value


def normalize_odd_kernel_size(value: object) -> int:
    """把 kernel size 规范化为奇数正整数。

    参数：
    - value：原始 kernel size。

    返回：
    - int：规范化后的奇数 kernel size。
    """

    kernel_size = require_positive_int(value, field_name="kernel_size")
    if kernel_size % 2 == 0:
        raise InvalidRequestError("kernel_size 必须是奇数")
    return kernel_size


def normalize_adaptive_block_size(value: object) -> int:
    """把 adaptive-threshold 的 block size 规范化为大于等于 3 的奇数。"""

    block_size = normalize_odd_kernel_size(value)
    if block_size < 3:
        raise InvalidRequestError("block_size 必须是大于等于 3 的奇数")
    return block_size


def normalize_morphology_operation(value: object) -> str:
    """规范化 morphology 操作名称。

    参数：
    - value：原始操作名称。

    返回：
    - str：规范化后的操作名称。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("operation 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value not in {"erode", "dilate", "open", "close", "gradient", "top-hat", "black-hat"}:
        raise InvalidRequestError("operation 不在支持的 morphology 列表中")
    return normalized_value


def normalize_contour_retrieval_mode(value: object, *, cv2_module: Any) -> int:
    """把 contour retrieval mode 解析为 OpenCV 常量。

    参数：
    - value：原始 mode 名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV retrieval mode 常量。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("retrieval_mode 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "external":
        return cv2_module.RETR_EXTERNAL
    if normalized_value == "list":
        return cv2_module.RETR_LIST
    if normalized_value == "tree":
        return cv2_module.RETR_TREE
    if normalized_value == "ccomp":
        return cv2_module.RETR_CCOMP
    raise InvalidRequestError("retrieval_mode 不在支持的 contour retrieval 列表中")


def normalize_contour_approximation(value: object, *, cv2_module: Any) -> int:
    """把 contour approximation 解析为 OpenCV 常量。

    参数：
    - value：原始 approximation 名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV contour approximation 常量。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("approximation 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "simple":
        return cv2_module.CHAIN_APPROX_SIMPLE
    if normalized_value == "none":
        return cv2_module.CHAIN_APPROX_NONE
    if normalized_value == "tc89-l1":
        return cv2_module.CHAIN_APPROX_TC89_L1
    if normalized_value == "tc89-kcos":
        return cv2_module.CHAIN_APPROX_TC89_KCOS
    raise InvalidRequestError("approximation 不在支持的 contour approximation 列表中")


def normalize_kernel_shape(value: object, *, cv2_module: Any) -> int:
    """规范化 morphology kernel 形状。

    参数：
    - value：原始形状名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV kernel shape 常量。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("shape 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "rect":
        return cv2_module.MORPH_RECT
    if normalized_value == "ellipse":
        return cv2_module.MORPH_ELLIPSE
    if normalized_value == "cross":
        return cv2_module.MORPH_CROSS
    raise InvalidRequestError("shape 不在支持的 morphology 形状列表中")


def normalize_resize_interpolation(value: object, *, cv2_module: Any) -> int:
    """把 resize interpolation 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("interpolation 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "nearest":
        return cv2_module.INTER_NEAREST
    if normalized_value == "linear":
        return cv2_module.INTER_LINEAR
    if normalized_value == "area":
        return cv2_module.INTER_AREA
    if normalized_value == "cubic":
        return cv2_module.INTER_CUBIC
    if normalized_value == "lanczos4":
        return cv2_module.INTER_LANCZOS4
    raise InvalidRequestError("interpolation 不在支持的 resize interpolation 列表中")


def normalize_binary_threshold_mode(value: object, *, cv2_module: Any) -> int:
    """把二值 threshold mode 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("threshold_type 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "binary":
        return cv2_module.THRESH_BINARY
    if normalized_value == "binary-inv":
        return cv2_module.THRESH_BINARY_INV
    raise InvalidRequestError("threshold_type 仅支持 binary 或 binary-inv")


def normalize_image_diff_mode(value: object) -> str:
    """规范化 image-diff 的输出模式。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("diff_mode 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value not in {"grayscale", "color"}:
        raise InvalidRequestError("diff_mode 仅支持 grayscale 或 color")
    return normalized_value


def normalize_adaptive_threshold_method(value: object, *, cv2_module: Any) -> int:
    """把 adaptive threshold method 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("adaptive_method 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "mean":
        return cv2_module.ADAPTIVE_THRESH_MEAN_C
    if normalized_value == "gaussian":
        return cv2_module.ADAPTIVE_THRESH_GAUSSIAN_C
    raise InvalidRequestError("adaptive_method 仅支持 mean 或 gaussian")


def normalize_connected_components_connectivity(value: object) -> int:
    """规范化 connected-components 的 connectivity。"""

    connectivity = require_positive_int(value, field_name="connectivity")
    if connectivity not in {4, 8}:
        raise InvalidRequestError("connectivity 只能是 4 或 8")
    return connectivity


def resolve_morphology_operation(operation_name: str, *, cv2_module: Any) -> int:
    """把 morphology 操作名称解析为 OpenCV 常量。

    参数：
    - operation_name：规范化后的操作名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV morphology 操作常量。
    """

    operation_mapping = {
        "open": cv2_module.MORPH_OPEN,
        "close": cv2_module.MORPH_CLOSE,
        "gradient": cv2_module.MORPH_GRADIENT,
        "top-hat": cv2_module.MORPH_TOPHAT,
        "black-hat": cv2_module.MORPH_BLACKHAT,
    }
    operation_value = operation_mapping.get(operation_name)
    if operation_value is None:
        raise InvalidRequestError("当前 morphology operation 不支持通过 morphologyEx 执行")
    return operation_value


def require_aperture_size(value: object) -> int:
    """把 Canny aperture size 规范化为 3、5 或 7。

    参数：
    - value：原始 aperture size。

    返回：
    - int：规范化后的 aperture size。
    """

    aperture_size = require_positive_int(value, field_name="aperture_size")
    if aperture_size not in {3, 5, 7}:
        raise InvalidRequestError("aperture_size 只能是 3、5 或 7")
    return aperture_size


def require_non_negative_int(value: object, *, field_name: str) -> int:
    """把输入值解析为非负整数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - int：规范化后的非负整数。
    """

    normalized_value = int(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def contour_points_to_matrix(*, points: list[list[int]], np_module: Any):
    """把 contour 点集转换为 OpenCV contour matrix。"""

    if not points:
        raise InvalidRequestError("contour.points 不能为空")
    return np_module.array(points, dtype=np_module.int32).reshape((-1, 1, 2))


def compute_contour_metrics_from_points(
    *,
    points: list[list[int]],
    cv2_module: Any,
    np_module: Any,
) -> dict[str, object]:
    """根据 contour 点集计算面积、bbox、周长等基础度量。"""

    contour_matrix = contour_points_to_matrix(points=points, np_module=np_module)
    bbox_x, bbox_y, bbox_width, bbox_height = cv2_module.boundingRect(contour_matrix)
    bbox_xyxy = [
        int(bbox_x),
        int(bbox_y),
        int(bbox_x + bbox_width),
        int(bbox_y + bbox_height),
    ]
    area = round(float(cv2_module.contourArea(contour_matrix)), 4)
    perimeter = round(float(cv2_module.arcLength(contour_matrix, True)), 4)
    center_x = round((float(bbox_xyxy[0]) + float(bbox_xyxy[2])) / 2.0, 4)
    center_y = round((float(bbox_xyxy[1]) + float(bbox_xyxy[3])) / 2.0, 4)
    aspect_ratio = round(float(bbox_width / bbox_height), 4) if bbox_height > 0 else 0.0
    return {
        "bbox_xyxy": bbox_xyxy,
        "width": int(bbox_width),
        "height": int(bbox_height),
        "area": area,
        "perimeter": perimeter,
        "center_xy": [center_x, center_y],
        "aspect_ratio": aspect_ratio,
    }


def build_contour_item_from_cv_contour(
    *,
    contour: Any,
    contour_index: int,
    cv2_module: Any,
    np_module: Any,
) -> dict[str, object] | None:
    """把 OpenCV contour 转为结构化 contour item。"""

    point_pairs = contour.reshape(-1, 2)
    contour_points = [[int(point_x), int(point_y)] for point_x, point_y in point_pairs.tolist()]
    if len(contour_points) < 3:
        return None
    contour_metrics = compute_contour_metrics_from_points(
        points=contour_points,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    return {
        "contour_index": int(contour_index),
        "point_count": len(contour_points),
        "bbox_xyxy": list(contour_metrics["bbox_xyxy"]),
        "points": contour_points,
    }


def normalize_optional_output_dir(value: object) -> str | None:
    """规范化可选裁剪输出目录。

    参数：
    - value：原始输出目录。

    返回：
    - str | None：规范化后的输出目录。
    """

    if not isinstance(value, str) or not value.strip():
        return None
    normalized_value = value.strip().replace("\\", "/").rstrip("/")
    if ".." in normalized_value.split("/"):
        raise InvalidRequestError("output_dir 不能包含父目录引用")
    return normalized_value


def clip_bbox(
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    image_width: int,
    image_height: int,
    box_padding: int,
) -> tuple[int, int, int, int] | None:
    """把 bbox 限制在图片边界内，并应用 padding。

    参数：
    - x1：左上角 x。
    - y1：左上角 y。
    - x2：右下角 x。
    - y2：右下角 y。
    - image_width：图片宽度。
    - image_height：图片高度。
    - box_padding：padding 像素。

    返回：
    - tuple[int, int, int, int] | None：裁剪后的 bbox；无效时返回 None。
    """

    clipped_x1 = max(0, x1 - box_padding)
    clipped_y1 = max(0, y1 - box_padding)
    clipped_x2 = min(image_width, x2 + box_padding)
    clipped_y2 = min(image_height, y2 + box_padding)
    if clipped_x2 <= clipped_x1 or clipped_y2 <= clipped_y1:
        return None
    return clipped_x1, clipped_y1, clipped_x2, clipped_y2


def build_crop_object_key(
    request: object,
    *,
    source_object_key: str | None,
    output_dir: str | None,
    detection_index: int,
) -> str:
    """为单个裁剪图生成输出 object key。

    参数：
    - request：当前节点执行请求。
    - source_object_key：源图片 object key。
    - output_dir：可选输出目录。
    - detection_index：当前 detection 序号。

    返回：
    - str：裁剪图 object key。
    """

    normalized_source_object_key = source_object_key.strip() if isinstance(source_object_key, str) else ""
    if output_dir is not None:
        source_stem = PurePosixPath(normalized_source_object_key).stem or "image"
        return f"{output_dir}/{source_stem}-crop-{detection_index:03d}.png"
    return build_runtime_image_object_key(
        request,
        source_object_key=normalized_source_object_key or "image.png",
        variant_name=f"crop-{detection_index:03d}",
        output_extension=".png",
    )


def normalize_optional_object_key(value: object) -> str | None:
    """规范化可选 output_object_key 参数。

    参数：
    - value：原始 object key。

    返回：
    - str | None：规范化后的 object key。
    """

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
