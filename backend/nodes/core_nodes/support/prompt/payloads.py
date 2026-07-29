"""共享 Prompt payload 的构造、合并和边界校验。"""

from __future__ import annotations

from collections.abc import Iterable

from backend.service.application.errors import InvalidRequestError


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
    else:
        mask_image = value.get("mask_image")
        if not isinstance(mask_image, dict):
            raise InvalidRequestError("mask_image 必须是 image-ref.v1 对象")
        item["mask_image"] = dict(mask_image)
    return item


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
