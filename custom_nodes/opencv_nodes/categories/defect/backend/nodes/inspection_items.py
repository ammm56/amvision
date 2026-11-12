"""逐区域测量的公共数据边界；按标识关联，不以列表位置推断对应关系。"""

from dataclasses import replace
import math

import cv2
import numpy as np

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix


def records(items, format_id="amvision.measurement-items.v1"):
    """测量、规则和汇总共用 item_id/source/result 记录结构。"""
    return build_value_payload(
        {"format_id": format_id, "count": len(items), "items": items}
    )


def read_records(payload, *, expected_format="amvision.measurement-items.v1"):
    """拒绝重复标识、错误结构和空集合，避免空集合被汇总为通过。"""
    body = payload.get("value") if isinstance(payload, dict) else None
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 1024:
        raise InvalidRequestError("测量记录必须包含 1–1024 个 items")
    if body.get("format_id") != expected_format or body.get("count") != len(items):
        raise InvalidRequestError("测量记录格式或数量不一致")
    indexed = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("item_id"), str)
            or not item["item_id"].strip()
        ):
            raise InvalidRequestError("测量记录缺少明确的 item_id")
        if (
            item["item_id"] in indexed
            or not isinstance(item.get("source"), dict)
            or not isinstance(item.get("result"), dict)
        ):
            raise InvalidRequestError("测量记录标识重复或缺少 source/result")
        validate_source(item["source"], item["item_id"])
        indexed[item["item_id"]] = item
    return indexed


def read_masks(payload):
    """mask 使用标准 image-refs.v1，附带 ROI 及共同坐标系信息。"""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 1024:
        raise InvalidRequestError("掩膜列表必须包含 1–1024 张图像")
    if "count" in payload and payload["count"] != len(items):
        raise InvalidRequestError("掩膜列表 count 与实际项数不一致")
    indexed = {}
    for item in items:
        if not isinstance(item, dict):
            raise InvalidRequestError("掩膜记录必须为图片引用")
        key = item.get("roi_id")
        source = item.get("measurement_source")
        if (
            not isinstance(key, str)
            or not key
            or key in indexed
            or not isinstance(source, dict)
        ):
            raise InvalidRequestError("掩膜必须携带唯一 roi_id 和 measurement_source")
        if source.get("roi_id") != key:
            raise InvalidRequestError("掩膜 roi_id 与测量来源不一致")
        validate_source(source, key)
        indexed[key] = item
    return indexed


def validate_source(source, item_id):
    """验证共同图像坐标、整数观察框和允许域；缺失信息不能相互抵消。"""
    size = source.get("image_size")
    box = source.get("observation_bbox_xyxy")
    roi = source.get("bbox_xyxy")
    polygon = source.get("polygon_xy")
    if (
        source.get("roi_id") != item_id
        or not isinstance(source.get("coordinate_space"), str)
        or not source["coordinate_space"].strip()
    ):
        raise InvalidRequestError("测量来源缺少区域标识或坐标系")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or not all(type(v) is int and v > 0 for v in size)
    ):
        raise InvalidRequestError("测量来源必须包含有效图像尺寸")
    if (
        not isinstance(box, list)
        or len(box) != 4
        or not all(type(v) is int for v in box)
        or not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1])
    ):
        raise InvalidRequestError("测量观察框必须是图像内的整数边界")
    if (
        not isinstance(roi, list)
        or len(roi) != 4
        or not all(finite_number(v) for v in roi)
        or not (
            box[0] <= roi[0] < roi[2] <= box[2] and box[1] <= roi[1] < roi[3] <= box[3]
        )
    ):
        raise InvalidRequestError("允许区域必须完整位于观察框内")
    if (
        not isinstance(polygon, list)
        or not 3 <= len(polygon) <= 1024
        or not all(
            isinstance(p, list)
            and len(p) == 2
            and all(finite_number(v) for v in p)
            and roi[0] <= p[0] <= roi[2]
            and roi[1] <= p[1] <= roi[3]
            for p in polygon
        )
    ):
        raise InvalidRequestError("允许区域多边形无效")
    if not finite_number(source.get("area")) or source["area"] <= 0:
        raise InvalidRequestError("允许区域面积必须大于零")


def same_source(a, b):
    """配对时检查共同坐标系、观察框和允许区域，拒绝静默错配。"""
    keys = (
        "coordinate_space",
        "image_size",
        "observation_bbox_xyxy",
        "bbox_xyxy",
        "polygon_xy",
    )
    if any(a.get(key) != b.get(key) for key in keys):
        raise InvalidRequestError("测量记录的坐标系或 ROI 几何不一致")


def pair_items(a, b, *, masks=False):
    """保持 A 顺序，但严格以标识寻找 B。"""
    if a.keys() != b.keys():
        raise InvalidRequestError("两组测量记录的标识集合不一致")
    source_key = "measurement_source" if masks else "source"
    for key, item in a.items():
        same_source(item[source_key], b[key][source_key])
        yield key, item, b[key]


def binary_matrix(request, payload):
    """只接受显式二值图，不在测量节点隐式执行灰度阈值分割。"""
    _, _, image = load_image_matrix(
        replace(request, input_values={"image": payload}),
        imdecode_flags=cv2.IMREAD_UNCHANGED,
    )
    if (
        image.ndim != 2
        or image.dtype != np.uint8
        or np.any((image != 0) & (image != 255))
    ):
        raise InvalidRequestError(
            "掩膜必须是单通道 uint8 的 0/255 二值图；先使用二值化节点"
        )
    source = payload.get("measurement_source")
    if source is not None:
        validate_source(source, payload.get("roi_id"))
        x1, y1, x2, y2 = source["observation_bbox_xyxy"]
        if image.shape != (y2 - y1, x2 - x1):
            raise InvalidRequestError("掩膜尺寸与测量观察框不一致")
    return image


def output_mask(request, mask, source):
    """只登记局部矩阵；不编码图片或写磁盘，随 Run 释放。"""
    payload = register_typed_image_matrix(
        request, image_matrix=np.ascontiguousarray(mask, dtype=np.uint8)
    )
    payload.update(
        roi_id=source["roi_id"],
        measurement_source=source,
        bbox_xyxy=source["observation_bbox_xyxy"],
    )
    return payload


def mask_list(items):
    """构造可直接连接 Gallery Preview 的标准图像引用列表。"""
    return {"items": items, "count": len(items)}


def check_cancelled(request):
    """沿用 Workflow 取消及超时控制，不启动线程。"""
    build_node_execution_control(request).raise_if_cancelled_or_expired()


def finite_number(value):
    """未知值保留为未知，禁止把 null、布尔值或 NaN 当成零。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )
