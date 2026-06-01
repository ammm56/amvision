"""SAM3 segmentation 节点公共 helper。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.nodes.runtime_support import load_image_bytes, register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SAM3_PRETRAINED_ROOT = REPOSITORY_ROOT / "data" / "files" / "models" / "pretrained" / "sam3" / "segmentation"
SUPPORTED_MODEL_SCALES = frozenset({"nano", "tiny", "s", "m", "l", "x", "xx"})
SUPPORTED_PRECISIONS = frozenset({"fp32", "fp16", "bf16"})
SUPPORTED_POINT_LABELS = frozenset({"positive", "negative"})
DEFAULT_MODEL_SCALE = "l"
DEFAULT_VARIANT_NAME = "default"
DEFAULT_DEVICE = "cpu"
DEFAULT_PRECISION = "fp32"


@dataclass(frozen=True)
class Sam3TextPromptItem:
    """描述一条 SAM3 语义提示。"""

    prompt_id: str
    text: str
    display_name: str


@dataclass(frozen=True)
class Sam3InteractivePromptItem:
    """描述一条 SAM3 交互提示。"""

    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None = None
    point_xy: tuple[float, float] | None = None
    point_label: str | None = None


@dataclass(frozen=True)
class Sam3PretrainedVariant:
    """描述一个 SAM3 预训练权重目录。"""

    model_scale: str
    variant_name: str
    manifest_path: Path
    checkpoint_path: Path
    model_name: str
    task_type: str
    metadata: dict[str, object]


def resolve_sam3_pretrained_variant(
    *,
    model_scale: object,
    variant_name: object = DEFAULT_VARIANT_NAME,
) -> Sam3PretrainedVariant:
    """按 scale/variant 解析 SAM3 预训练目录。"""

    normalized_scale = normalize_model_scale(model_scale)
    normalized_variant_name = str(variant_name or DEFAULT_VARIANT_NAME).strip() or DEFAULT_VARIANT_NAME
    variant_dir = SAM3_PRETRAINED_ROOT / normalized_scale / normalized_variant_name
    manifest_path = variant_dir / "manifest.json"
    if not manifest_path.is_file():
        raise InvalidRequestError(
            "找不到指定的 SAM3 预训练 manifest",
            details={
                "model_scale": normalized_scale,
                "variant_name": normalized_variant_name,
                "manifest_path": str(manifest_path),
            },
        )
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InvalidRequestError(
            "SAM3 预训练 manifest 不是合法 JSON",
            details={"manifest_path": str(manifest_path)},
        ) from exc
    checkpoint_path_value = manifest_payload.get("checkpoint_path")
    if not isinstance(checkpoint_path_value, str) or not checkpoint_path_value.strip():
        raise InvalidRequestError(
            "SAM3 预训练 manifest 缺少 checkpoint_path",
            details={"manifest_path": str(manifest_path)},
        )
    checkpoint_path = (variant_dir / checkpoint_path_value).resolve()
    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "SAM3 预训练 checkpoint 文件不存在",
            details={
                "manifest_path": str(manifest_path),
                "checkpoint_path": str(checkpoint_path),
            },
        )
    metadata = manifest_payload.get("metadata")
    return Sam3PretrainedVariant(
        model_scale=normalized_scale,
        variant_name=normalized_variant_name,
        manifest_path=manifest_path,
        checkpoint_path=checkpoint_path,
        model_name=str(manifest_payload.get("model_name") or "sam3"),
        task_type=str(manifest_payload.get("task_type") or "segmentation"),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def read_text_prompt_items(payload: object) -> tuple[Sam3TextPromptItem, ...]:
    """把 text-prompts.v1 payload 规范化为语义提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("SAM3 语义分割节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("SAM3 语义分割节点要求 prompts.items 必须是非空数组")
    prompt_items: list[Sam3TextPromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("SAM3 语义分割节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        text = str(item.get("text") or "").strip()
        display_name = str(item.get("display_name") or text).strip()
        negative = bool(item.get("negative"))
        if not prompt_id:
            raise InvalidRequestError("SAM3 语义分割节点要求 prompt_id 不能为空")
        if not text:
            raise InvalidRequestError("SAM3 语义分割节点要求 text 不能为空")
        if negative:
            raise InvalidRequestError("SAM3 语义分割节点第一阶段暂不支持 negative prompts")
        prompt_items.append(Sam3TextPromptItem(prompt_id=prompt_id, text=text, display_name=display_name or text))
    return tuple(prompt_items)


def read_interactive_prompt_items(payload: object) -> tuple[Sam3InteractivePromptItem, ...]:
    """把 prompt-regions.v1 payload 规范化为第一阶段交互提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("SAM3 交互分割节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("SAM3 交互分割节点要求 prompts.items 必须是非空数组")
    prompt_items: list[Sam3InteractivePromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("SAM3 交互分割节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        prompt_kind = str(item.get("prompt_kind") or "").strip().lower()
        display_name = str(item.get("display_name") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("SAM3 交互分割节点要求 prompt_id 不能为空")
        if prompt_kind == "box":
            bbox_xyxy = item.get("bbox_xyxy")
            if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
                raise InvalidRequestError("SAM3 交互分割节点要求 bbox_xyxy 必须是长度为 4 的数组")
            try:
                normalized_bbox = tuple(float(value) for value in bbox_xyxy)
            except Exception as exc:
                raise InvalidRequestError("SAM3 交互分割节点要求 bbox_xyxy 必须是数字数组") from exc
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    bbox_xyxy=normalized_bbox,
                )
            )
            continue
        if prompt_kind == "point":
            point_xy = item.get("point_xy")
            if not isinstance(point_xy, list) or len(point_xy) != 2:
                raise InvalidRequestError("SAM3 交互分割节点要求 point_xy 必须是长度为 2 的数组")
            try:
                normalized_point = tuple(float(value) for value in point_xy)
            except Exception as exc:
                raise InvalidRequestError("SAM3 交互分割节点要求 point_xy 必须是数字数组") from exc
            point_label = str(item.get("point_label") or "positive").strip().lower()
            if point_label not in SUPPORTED_POINT_LABELS:
                raise InvalidRequestError(
                    "SAM3 交互分割节点要求 point_label 只能是 positive 或 negative",
                    details={"prompt_id": prompt_id, "point_label": point_label},
                )
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    point_xy=normalized_point,
                    point_label=point_label,
                )
            )
            continue
        if prompt_kind in {"polygon", "mask"}:
            raise InvalidRequestError(
                "SAM3 交互分割节点第一阶段只支持 box 与 point prompt",
                details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
            )
        raise InvalidRequestError(
            "SAM3 交互分割节点要求 prompt_kind 只能是 box 或 point",
            details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
        )
    return tuple(prompt_items)


def read_image_bytes(request: WorkflowNodeExecutionRequest, *, input_name: str = "image") -> tuple[dict[str, object], bytes]:
    """读取节点图片输入。"""

    return load_image_bytes(request, input_name=input_name)


def normalize_model_scale(value: object) -> str:
    """规范化模型 scale。"""

    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        normalized_value = DEFAULT_MODEL_SCALE
    if normalized_value not in SUPPORTED_MODEL_SCALES:
        raise InvalidRequestError(
            "SAM3 节点要求 model_scale 使用统一 scale 命名",
            details={"model_scale": value, "supported": sorted(SUPPORTED_MODEL_SCALES)},
        )
    return normalized_value


def normalize_device(value: object) -> str:
    """规范化运行设备。"""

    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        return DEFAULT_DEVICE
    return normalized_value


def normalize_precision(value: object) -> str:
    """规范化精度参数。"""

    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        return DEFAULT_PRECISION
    if normalized_value not in SUPPORTED_PRECISIONS:
        raise InvalidRequestError(
            "SAM3 节点 precision 只能是 fp32、fp16 或 bf16",
            details={"precision": value, "supported": sorted(SUPPORTED_PRECISIONS)},
        )
    return normalized_value


def build_source_image_summary_payload(image_payload: dict[str, object]) -> dict[str, object]:
    """提取图片摘要里需要保留的 source image 字段。"""

    return {
        key: image_payload.get(key)
        for key in ("transport_kind", "media_type", "width", "height", "object_key", "image_handle")
        if image_payload.get(key) is not None
    }


def build_regions_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    prediction: object,
    image_payload: dict[str, object],
) -> dict[str, object]:
    """把内部 region 结果转换成 workflow regions.v1 payload。"""

    region_items: list[dict[str, object]] = []
    for item in prediction.regions:
        normalized_item = {
            "region_id": item.region_id,
            "score": item.score,
            "class_id": item.class_id,
            "class_name": item.class_name,
            "bbox_xyxy": list(item.bbox_xyxy),
            "polygon_xy": [list(point) for point in item.polygon_xy],
            "area": int(item.area),
        }
        prompt_id = getattr(item, "prompt_id", None)
        source_prompt_text = getattr(item, "source_prompt_text", None)
        if prompt_id is not None:
            normalized_item["prompt_id"] = prompt_id
        if source_prompt_text is not None:
            normalized_item["source_prompt_text"] = source_prompt_text
        normalized_item["mask_image"] = register_image_bytes(
            request,
            content=item.mask_png_bytes,
            media_type="image/png",
            width=item.mask_width,
            height=item.mask_height,
        )
        region_items.append(normalized_item)
    return {
        "source_image": build_source_image_summary_payload(image_payload),
        "count": len(region_items),
        "items": region_items,
    }


def build_interactive_summary_payload(
    *,
    prediction: object,
    image_payload: dict[str, object],
    prompt_items: tuple[Sam3InteractivePromptItem, ...],
) -> dict[str, object]:
    """构建 interactive 节点 summary。"""

    return {
        **prediction.summary,
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_ids": [item.prompt_id for item in prompt_items],
    }


def build_semantic_summary_payload(
    *,
    prediction: object,
    image_payload: dict[str, object],
    prompt_items: tuple[Sam3TextPromptItem, ...],
) -> dict[str, object]:
    """构建 semantic 节点 summary。"""

    return {
        **prediction.summary,
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_ids": [item.prompt_id for item in prompt_items],
    }


def get_or_create_sam3_interactive_runtime_session(
    *,
    model_scale: str,
    device: str,
    precision: str,
):
    """返回可复用的 SAM3 interactive 会话。"""

    normalized_scale = normalize_model_scale(model_scale)
    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_sam3_pretrained_variant(model_scale=normalized_scale)

    from custom_nodes.sam3_segment_nodes.backend.nodes._project_native_runtime import (
        get_or_create_interactive_runtime_session,
    )

    return get_or_create_interactive_runtime_session(
        checkpoint_path=variant.checkpoint_path,
        model_scale=variant.model_scale,
        variant_name=variant.variant_name,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def get_or_create_sam3_semantic_runtime_session(
    *,
    model_scale: str,
    device: str,
    precision: str,
):
    """返回可复用的 SAM3 semantic 会话。"""

    normalized_scale = normalize_model_scale(model_scale)
    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_sam3_pretrained_variant(model_scale=normalized_scale)

    from custom_nodes.sam3_segment_nodes.backend.nodes._project_native_runtime import (
        get_or_create_semantic_runtime_session,
    )

    return get_or_create_semantic_runtime_session(
        checkpoint_path=variant.checkpoint_path,
        model_scale=variant.model_scale,
        variant_name=variant.variant_name,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def raise_not_implemented(
    request: WorkflowNodeExecutionRequest,
    *,
    mode_name: str,
    model_scale: str,
    device: str,
    precision: str,
) -> dict[str, object]:
    """抛出统一的“骨架已注册但推理未接通”错误。"""

    variant = resolve_sam3_pretrained_variant(model_scale=model_scale)
    raise InvalidRequestError(
        f"SAM3 {mode_name} 节点骨架已注册，但 project-native 推理实现尚未接通",
        details={
            "node_id": request.node_id,
            "node_type_id": request.node_type_id,
            "model_scale": variant.model_scale,
            "variant_name": variant.variant_name,
            "task_type": variant.task_type,
            "manifest_path": str(variant.manifest_path),
            "checkpoint_path": str(variant.checkpoint_path),
            "device": device,
            "precision": precision,
            "pretrained_root": "data/files/models/pretrained/sam3",
        },
    )


__all__ = [
    "Sam3InteractivePromptItem",
    "Sam3PretrainedVariant",
    "Sam3TextPromptItem",
    "build_interactive_summary_payload",
    "build_semantic_summary_payload",
    "build_regions_payload",
    "build_source_image_summary_payload",
    "get_or_create_sam3_interactive_runtime_session",
    "get_or_create_sam3_semantic_runtime_session",
    "normalize_device",
    "normalize_model_scale",
    "normalize_precision",
    "raise_not_implemented",
    "read_image_bytes",
    "read_interactive_prompt_items",
    "read_text_prompt_items",
    "resolve_sam3_pretrained_variant",
]
