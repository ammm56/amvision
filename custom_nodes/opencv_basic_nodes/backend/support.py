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
    """按双模式规则读取图片输入，并解码为 OpenCV matrix。

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
        raise ServiceConfigurationError(
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
        raise InvalidRequestError("measure 节点要求 contours payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("measure 节点要求 contours.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("measure 节点要求每个 contour item 必须是对象")
        raw_points = item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            raise InvalidRequestError("measure 节点要求 contour.points 至少包含三个点")
        normalized_points: list[list[int]] = []
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise InvalidRequestError("measure 节点要求 contour.points 中的每个点必须包含 x 与 y")
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