"""共享 Prompt payload 的构造、合并和边界校验。"""

from __future__ import annotations

from collections.abc import Iterable

from backend.service.application.errors import InvalidRequestError


def build_image_reference_identity(image_payload: object) -> str:
    """构造用于判断 Prompt 源图是否变化的稳定标识。"""

    if not isinstance(image_payload, dict):
        return ""
    for field_name in (
        "content_sha256",
        "source_sha256",
        "image_handle",
        "object_key",
    ):
        field_value = str(image_payload.get(field_name) or "").strip()
        if field_value:
            return f"{field_name}:{field_value}"
    return ""


def require_non_empty_text(value: object, *, field_name: str) -> str:
    """读取必填文本参数。

    参数：
    - value：待校验的参数值。
    - field_name：错误详情中使用的字段名。

    返回：
    - str：去除首尾空白后的文本。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            f"{field_name} 必须是非空字符串",
            details={"field_name": field_name},
        )
    return value.strip()


def build_text_prompts_payload(items: Iterable[dict[str, object]]) -> dict[str, object]:
    """构造标准 text-prompts.v1 payload。"""

    normalized_items = [_normalize_text_prompt_item(item) for item in items]
    if not normalized_items:
        raise InvalidRequestError("Text Prompts 至少需要一项")
    return {"items": normalized_items}


def merge_text_prompts_payloads(payloads: object) -> dict[str, object]:
    """按输入顺序合并多个 text-prompts.v1 payload。"""

    normalized_payloads = _require_multiple_payloads(
        payloads, payload_name="Text Prompts"
    )
    merged_items: list[dict[str, object]] = []
    for payload_index, payload in enumerate(normalized_payloads, start=1):
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise InvalidRequestError(
                "Text Prompts Merge 收到无效 payload",
                details={"payload_index": payload_index},
            )
        merged_items.extend(
            _normalize_text_prompt_item(item) for item in payload["items"]
        )
    return build_text_prompts_payload(merged_items)


def build_prompt_regions_payload(
    items: Iterable[dict[str, object]],
    *,
    source_image: object | None = None,
) -> dict[str, object]:
    """构造标准 prompt-regions.v1 payload。"""

    normalized_items = [_normalize_prompt_region_item(item) for item in items]
    if not normalized_items:
        raise InvalidRequestError("Prompt Regions 至少需要一项")
    payload: dict[str, object] = {"items": normalized_items}
    if source_image is not None:
        if not isinstance(source_image, dict):
            raise InvalidRequestError("source_image 必须是 image-ref.v1 对象")
        payload["source_image"] = dict(source_image)
    return payload


def merge_prompt_regions_payloads(payloads: object) -> dict[str, object]:
    """按输入顺序合并多个 prompt-regions.v1 payload。"""

    normalized_payloads = _require_multiple_payloads(
        payloads, payload_name="Prompt Regions"
    )
    merged_items: list[dict[str, object]] = []
    source_image: dict[str, object] | None = None
    for payload_index, payload in enumerate(normalized_payloads, start=1):
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise InvalidRequestError(
                "Prompt Regions Merge 收到无效 payload",
                details={"payload_index": payload_index},
            )
        payload_source_image = payload.get("source_image")
        if payload_source_image is not None:
            if not isinstance(payload_source_image, dict):
                raise InvalidRequestError(
                    "Prompt Regions 的 source_image 必须是对象",
                    details={"payload_index": payload_index},
                )
            if source_image is not None and source_image != payload_source_image:
                raise InvalidRequestError(
                    "Prompt Regions Merge 不能合并不同 source_image 的提示",
                    details={"payload_index": payload_index},
                )
            source_image = dict(payload_source_image)
        merged_items.extend(
            _normalize_prompt_region_item(item) for item in payload["items"]
        )
    _validate_merged_prompt_region_groups(merged_items)
    return build_prompt_regions_payload(merged_items, source_image=source_image)


def _require_multiple_payloads(
    payloads: object, *, payload_name: str
) -> tuple[object, ...]:
    """读取多值输入端口 payload。"""

    if not isinstance(payloads, tuple) or not payloads:
        raise InvalidRequestError(f"{payload_name} Merge 至少需要一路输入")
    return payloads


def _normalize_text_prompt_item(value: object) -> dict[str, object]:
    """校验并规范化单条文本 Prompt。"""

    if not isinstance(value, dict):
        raise InvalidRequestError("Text Prompt item 必须是对象")
    prompt_id = require_non_empty_text(value.get("prompt_id"), field_name="prompt_id")
    text = require_non_empty_text(value.get("text"), field_name="text")
    display_name = str(value.get("display_name") or text).strip() or text
    item: dict[str, object] = {
        "prompt_id": prompt_id,
        "text": text,
        "display_name": display_name,
        "negative": bool(value.get("negative")),
    }
    language = str(value.get("language") or "").strip()
    if language:
        item["language"] = language
    return item


def _normalize_prompt_region_item(value: object) -> dict[str, object]:
    """校验并规范化单条视觉 Prompt。"""

    if not isinstance(value, dict):
        raise InvalidRequestError("Prompt Region item 必须是对象")
    prompt_id = require_non_empty_text(value.get("prompt_id"), field_name="prompt_id")
    prompt_kind = require_non_empty_text(
        value.get("prompt_kind"), field_name="prompt_kind"
    ).lower()
    if prompt_kind not in {"point", "box", "polygon", "mask"}:
        raise InvalidRequestError(
            "prompt_kind 必须是 point、box、polygon 或 mask",
            details={"prompt_kind": prompt_kind},
        )
    item = dict(value)
    item["prompt_id"] = prompt_id
    item["prompt_kind"] = prompt_kind
    item["display_name"] = (
        str(value.get("display_name") or prompt_id).strip() or prompt_id
    )
    if prompt_kind == "point":
        item["point_xy"] = _normalize_numeric_pair(
            value.get("point_xy"), field_name="point_xy"
        )
        point_label = str(value.get("point_label") or "positive").strip().lower()
        if point_label not in {"positive", "negative"}:
            raise InvalidRequestError(
                "point_label 必须是 positive 或 negative",
                details={"point_label": value.get("point_label")},
            )
        item["point_label"] = point_label
    elif prompt_kind == "box":
        bbox_xyxy = _normalize_numeric_sequence(
            value.get("bbox_xyxy"),
            field_name="bbox_xyxy",
            expected_length=4,
        )
        if bbox_xyxy[2] <= bbox_xyxy[0] or bbox_xyxy[3] <= bbox_xyxy[1]:
            raise InvalidRequestError("bbox_xyxy 必须满足 x2 > x1 且 y2 > y1")
        item["bbox_xyxy"] = bbox_xyxy
    elif prompt_kind == "polygon":
        raw_polygon_xy = value.get("polygon_xy")
        if not isinstance(raw_polygon_xy, (list, tuple)) or len(raw_polygon_xy) < 3:
            raise InvalidRequestError("polygon_xy 至少需要三个点")
        item["polygon_xy"] = [
            _normalize_numeric_pair(point, field_name="polygon_xy")
            for point in raw_polygon_xy
        ]
        if _polygon_has_self_intersection(item["polygon_xy"]):
            raise InvalidRequestError("polygon_xy 不能包含自交边")
    else:
        mask_image = value.get("mask_image")
        if not isinstance(mask_image, dict):
            raise InvalidRequestError("mask_image 必须是 image-ref.v1 对象")
        item["mask_image"] = dict(mask_image)
    return item


def validate_prompt_geometry_bounds(
    coordinates: Iterable[Iterable[float]],
    *,
    source_image: dict[str, object] | None,
    field_name: str,
) -> None:
    """校验视觉 Prompt 坐标没有超出已知源图边界。"""

    if source_image is None:
        return
    width = source_image.get("width")
    height = source_image.get("height")
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
        or float(width) <= 0
        or float(height) <= 0
    ):
        return
    for point_index, point in enumerate(coordinates):
        values = list(point)
        if len(values) != 2:
            raise InvalidRequestError(f"{field_name} 包含无效坐标点")
        x_value, y_value = float(values[0]), float(values[1])
        if not (0 <= x_value < float(width) and 0 <= y_value < float(height)):
            raise InvalidRequestError(
                f"{field_name} 坐标超出源图边界",
                details={
                    "point_index": point_index,
                    "point_xy": [x_value, y_value],
                    "image_size": [float(width), float(height)],
                },
            )


def validate_applied_prompt_source_identity(
    *,
    prompt_name: str,
    applied: bool,
    source_identity: str,
    stored_source_identity: object,
) -> None:
    """拒绝把旧图上的已应用几何静默迁移到新源图。"""

    if not applied:
        return
    if not source_identity:
        raise InvalidRequestError(
            f"{prompt_name} 的源图缺少稳定标识，不能应用几何"
        )
    if str(stored_source_identity or "").strip() != source_identity:
        raise InvalidRequestError(
            f"{prompt_name} 的源图已变化，请重新创建并应用几何",
            details={"source_identity": source_identity},
        )


def _validate_merged_prompt_region_groups(
    items: list[dict[str, object]],
) -> None:
    """校验合并后的对象分组，避免把互斥提示伪装成同一对象。"""

    grouped_items: dict[str, list[dict[str, object]]] = {}
    for item in items:
        grouped_items.setdefault(str(item["prompt_id"]), []).append(item)
    for prompt_id, group in grouped_items.items():
        prompt_kinds = {str(item["prompt_kind"]) for item in group}
        if len(prompt_kinds) != 1:
            raise InvalidRequestError(
                "同一 prompt_id 不能混合不同视觉提示类型",
                details={
                    "prompt_id": prompt_id,
                    "prompt_kinds": sorted(prompt_kinds),
                },
            )
        prompt_kind = next(iter(prompt_kinds))
        if prompt_kind == "point":
            if not any(item.get("point_label") == "positive" for item in group):
                raise InvalidRequestError(
                    "Point 对象至少需要一个 Positive 点",
                    details={"prompt_id": prompt_id},
                )
        elif len(group) != 1:
            raise InvalidRequestError(
                "Box、Polygon、Mask 的 prompt_id 不能重复",
                details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
            )


def _polygon_has_self_intersection(points: list[list[float]]) -> bool:
    """判断简单多边形是否存在非相邻边相交。"""

    edge_count = len(points)
    for first_index in range(edge_count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if second_index in {
                first_index,
                (first_index + 1) % edge_count,
                (first_index - 1) % edge_count,
            }:
                continue
            if first_index == 0 and second_index == edge_count - 1:
                continue
            second_start = points[second_index]
            second_end = points[(second_index + 1) % edge_count]
            if _segments_intersect(
                first_start, first_end, second_start, second_end
            ):
                return True
    return False


def _segments_intersect(
    first_start: list[float],
    first_end: list[float],
    second_start: list[float],
    second_end: list[float],
) -> bool:
    """判断两条非相邻闭线段是否严格相交。"""

    def orientation(
        point_a: list[float],
        point_b: list[float],
        point_c: list[float],
    ) -> float:
        return (point_b[0] - point_a[0]) * (
            point_c[1] - point_a[1]
        ) - (point_b[1] - point_a[1]) * (point_c[0] - point_a[0])

    first_a = orientation(first_start, first_end, second_start)
    first_b = orientation(first_start, first_end, second_end)
    second_a = orientation(second_start, second_end, first_start)
    second_b = orientation(second_start, second_end, first_end)
    epsilon = 1e-9
    return (
        first_a * first_b < -epsilon
        and second_a * second_b < -epsilon
    )


def _normalize_numeric_pair(value: object, *, field_name: str) -> list[float]:
    """校验二维坐标。"""

    return _normalize_numeric_sequence(value, field_name=field_name, expected_length=2)


def _normalize_numeric_sequence(
    value: object,
    *,
    field_name: str,
    expected_length: int,
) -> list[float]:
    """校验固定长度的有限数值序列。"""

    import math

    if not isinstance(value, (list, tuple)) or len(value) != expected_length:
        raise InvalidRequestError(
            f"{field_name} 必须包含 {expected_length} 个数值",
            details={"field_name": field_name},
        )
    normalized_values: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise InvalidRequestError(f"{field_name} 只能包含数值")
        normalized_item = float(item)
        if not math.isfinite(normalized_item):
            raise InvalidRequestError(f"{field_name} 只能包含有限数值")
        normalized_values.append(normalized_item)
    return normalized_values
