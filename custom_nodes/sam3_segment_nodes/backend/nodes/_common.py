"""SAM3 segmentation 节点公共 helper。"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from backend.nodes.runtime_support import load_image_bytes, load_image_bytes_from_payload, register_image_bytes
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
    negative: bool = False
    language: str | None = None


@dataclass(frozen=True)
class Sam3TextPromptGroup:
    """描述一个按 prompt_id 聚合后的 SAM3 语义提示组。"""

    prompt_id: str
    display_name: str
    positive_texts: tuple[str, ...]
    negative_texts: tuple[str, ...]
    languages: tuple[str, ...]

    @property
    def source_prompt_text(self) -> str:
        """返回写入结果摘要的可追溯文本组合。"""

        positive_segment = " | ".join(self.positive_texts)
        if not self.negative_texts:
            return positive_segment
        negative_segment = " | ".join(f"!{item}" for item in self.negative_texts)
        return f"{positive_segment} || {negative_segment}"

    @property
    def source_prompt_positive_texts(self) -> tuple[str, ...]:
        """返回正向文本集合。"""

        return self.positive_texts

    @property
    def source_prompt_negative_texts(self) -> tuple[str, ...]:
        """返回负向文本集合。"""

        return self.negative_texts


@dataclass(frozen=True)
class Sam3InteractivePromptItem:
    """描述一条 SAM3 交互提示。"""

    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None = None
    point_xy: tuple[float, float] | None = None
    point_label: str | None = None
    polygon_xy: tuple[tuple[float, float], ...] | None = None
    prompt_mask: np.ndarray | None = None


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
        language = str(item.get("language") or "").strip() or None
        if not prompt_id:
            raise InvalidRequestError("SAM3 语义分割节点要求 prompt_id 不能为空")
        if not text:
            raise InvalidRequestError("SAM3 语义分割节点要求 text 不能为空")
        prompt_items.append(
            Sam3TextPromptItem(
                prompt_id=prompt_id,
                text=text,
                display_name=display_name or text,
                negative=negative,
                language=language,
            )
        )
    return tuple(prompt_items)


def merge_text_prompt_items(prompts: tuple[Sam3TextPromptItem, ...]) -> tuple[Sam3TextPromptGroup, ...]:
    """按 prompt_id 聚合 SAM3 文本提示，支持正负文本组合。"""

    grouped_records: dict[str, list[Sam3TextPromptItem]] = {}
    display_name_map: dict[str, str] = {}
    for item in prompts:
        prompt_id = str(getattr(item, "prompt_id", "") or "").strip()
        display_name = str(getattr(item, "display_name", "") or getattr(item, "text", "") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("SAM3 text prompt 聚合要求 prompt_id 不能为空")
        previous_display_name = display_name_map.get(prompt_id)
        if previous_display_name is not None and previous_display_name != display_name:
            raise InvalidRequestError(
                "同一个 SAM3 text prompt_id 只能对应一个 display_name",
                details={
                    "prompt_id": prompt_id,
                    "display_name": display_name,
                    "previous_display_name": previous_display_name,
                },
            )
        display_name_map[prompt_id] = display_name
        grouped_records.setdefault(prompt_id, []).append(item)

    prompt_groups: list[Sam3TextPromptGroup] = []
    for prompt_id, group_items in grouped_records.items():
        positive_texts = tuple(
            str(getattr(item, "text", "")).strip()
            for item in group_items
            if not bool(getattr(item, "negative", False))
        )
        negative_texts = tuple(
            str(getattr(item, "text", "")).strip()
            for item in group_items
            if bool(getattr(item, "negative", False))
        )
        if not positive_texts:
            raise InvalidRequestError(
                "SAM3 semantic-segment 要求每个 prompt_id 至少包含一条 positive 文本提示",
                details={"prompt_id": prompt_id},
            )
        languages = tuple(
            language
            for language in (
                str(getattr(item, "language", "") or "").strip() or None
                for item in group_items
            )
            if language is not None
        )
        prompt_groups.append(
            Sam3TextPromptGroup(
                prompt_id=prompt_id,
                display_name=display_name_map[prompt_id],
                positive_texts=positive_texts,
                negative_texts=negative_texts,
                languages=languages,
            )
        )
    return tuple(prompt_groups)


def read_interactive_prompt_items(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest | None = None,
    source_image_payload: dict[str, object] | None = None,
    source_image_bytes: bytes | None = None,
) -> tuple[Sam3InteractivePromptItem, ...]:
    """把 prompt-regions.v1 payload 规范化为当前阶段交互提示列表。"""

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
        if prompt_kind == "polygon":
            source_width, source_height = _resolve_source_image_size(
                source_image_payload=source_image_payload,
                source_image_bytes=source_image_bytes,
            )
            normalized_polygon = _normalize_polygon_xy(item.get("polygon_xy"), prompt_id=prompt_id)
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    polygon_xy=normalized_polygon,
                    prompt_mask=_rasterize_polygon_prompt_mask(
                        normalized_polygon,
                        source_width=source_width,
                        source_height=source_height,
                    ),
                )
            )
            continue
        if prompt_kind == "mask":
            if request is None:
                raise InvalidRequestError(
                    "SAM3 交互分割节点解析 mask prompt 时缺少执行请求上下文",
                    details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
                )
            source_width, source_height = _resolve_source_image_size(
                source_image_payload=source_image_payload,
                source_image_bytes=source_image_bytes,
            )
            mask_image_payload = item.get("mask_image")
            _normalized_mask_payload, mask_image_bytes = load_image_bytes_from_payload(
                request,
                image_payload=mask_image_payload,
            )
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    prompt_mask=_decode_prompt_mask_image(
                        mask_image_bytes,
                        source_width=source_width,
                        source_height=source_height,
                    ),
                )
            )
            continue
        raise InvalidRequestError(
            "SAM3 交互分割节点要求 prompt_kind 只能是 box、point、polygon 或 mask",
            details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
        )
    return tuple(prompt_items)


def read_image_bytes(request: WorkflowNodeExecutionRequest, *, input_name: str = "image") -> tuple[dict[str, object], bytes]:
    """读取节点图片输入。"""

    return load_image_bytes(request, input_name=input_name)


def _resolve_source_image_size(
    *,
    source_image_payload: dict[str, object] | None,
    source_image_bytes: bytes | None,
) -> tuple[int, int]:
    """解析 prompt 使用的源图尺寸。"""

    if isinstance(source_image_payload, dict):
        width_value = source_image_payload.get("width")
        height_value = source_image_payload.get("height")
        if isinstance(width_value, (int, float)) and isinstance(height_value, (int, float)):
            normalized_width = int(width_value)
            normalized_height = int(height_value)
            if normalized_width > 0 and normalized_height > 0:
                return normalized_width, normalized_height
    if not isinstance(source_image_bytes, bytes) or not source_image_bytes:
        raise InvalidRequestError("SAM3 polygon prompt 要求能够解析源图尺寸")
    with Image.open(io.BytesIO(source_image_bytes)) as image:
        source_width, source_height = image.size
    if source_width <= 0 or source_height <= 0:
        raise InvalidRequestError("SAM3 polygon prompt 解析出的源图尺寸无效")
    return source_width, source_height


def _normalize_polygon_xy(
    raw_polygon_xy: object,
    *,
    prompt_id: str,
) -> tuple[tuple[float, float], ...]:
    """规范化 polygon prompt 顶点数组。"""

    if not isinstance(raw_polygon_xy, list) or len(raw_polygon_xy) < 3:
        raise InvalidRequestError(
            "SAM3 交互分割节点要求 polygon_xy 至少包含三个点",
            details={"prompt_id": prompt_id},
        )
    normalized_polygon: list[tuple[float, float]] = []
    for point_index, point_value in enumerate(raw_polygon_xy):
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(
                "SAM3 交互分割节点要求 polygon_xy 中的每个点必须是长度为 2 的数组",
                details={"prompt_id": prompt_id, "point_index": point_index},
            )
        try:
            point_x = float(point_value[0])
            point_y = float(point_value[1])
        except Exception as exc:
            raise InvalidRequestError(
                "SAM3 交互分割节点要求 polygon_xy 中的点坐标必须是数字",
                details={"prompt_id": prompt_id, "point_index": point_index},
            ) from exc
        normalized_polygon.append((point_x, point_y))
    return tuple(normalized_polygon)


def _rasterize_polygon_prompt_mask(
    polygon_xy: tuple[tuple[float, float], ...],
    *,
    source_width: int,
    source_height: int,
) -> np.ndarray:
    """把 polygon prompt 栅格化成二值 mask。"""

    if source_width <= 0 or source_height <= 0:
        raise InvalidRequestError("SAM3 polygon prompt 要求源图尺寸必须大于 0")
    mask_image = Image.new("L", (source_width, source_height), color=0)
    draw = ImageDraw.Draw(mask_image)
    draw.polygon([(float(point_x), float(point_y)) for point_x, point_y in polygon_xy], fill=255)
    mask_array = np.asarray(mask_image, dtype=np.uint8)
    return (mask_array > 0).astype(np.uint8)


def _decode_prompt_mask_image(
    image_bytes: bytes,
    *,
    source_width: int,
    source_height: int,
) -> np.ndarray:
    """把 mask_image payload 解码成与源图对齐的二值 mask。"""

    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise InvalidRequestError("SAM3 mask prompt 要求 mask_image 必须包含非空图片字节")
    with Image.open(io.BytesIO(image_bytes)) as image:
        grayscale_image = image.convert("L")
        if grayscale_image.size != (source_width, source_height):
            grayscale_image = grayscale_image.resize((source_width, source_height), resample=Image.Resampling.NEAREST)
        mask_array = np.asarray(grayscale_image, dtype=np.uint8)
    binary_mask = (mask_array > 0).astype(np.uint8)
    if int(binary_mask.sum()) <= 0:
        raise InvalidRequestError("SAM3 mask prompt 解码后的 mask 不能为空")
    return binary_mask


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
        source_prompt_positive_texts = getattr(item, "source_prompt_positive_texts", None)
        source_prompt_negative_texts = getattr(item, "source_prompt_negative_texts", None)
        if prompt_id is not None:
            normalized_item["prompt_id"] = prompt_id
        if source_prompt_text is not None:
            normalized_item["source_prompt_text"] = source_prompt_text
        if source_prompt_positive_texts is not None:
            normalized_item["source_prompt_positive_texts"] = list(source_prompt_positive_texts)
        if source_prompt_negative_texts is not None:
            normalized_item["source_prompt_negative_texts"] = list(source_prompt_negative_texts)
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
    prompt_groups: tuple[Sam3TextPromptGroup, ...] | None = None,
) -> dict[str, object]:
    """构建 semantic 节点 summary。"""

    normalized_prompt_groups = prompt_groups or merge_text_prompt_items(prompt_items)
    return {
        **prediction.summary,
        "prompt_items": [
            {
                "prompt_id": item.prompt_id,
                "text": item.text,
                "display_name": item.display_name,
                "negative": item.negative,
                **({"language": item.language} if item.language is not None else {}),
            }
            for item in prompt_items
        ],
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_ids": [group.prompt_id for group in normalized_prompt_groups],
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
    "Sam3TextPromptGroup",
    "build_interactive_summary_payload",
    "build_semantic_summary_payload",
    "build_regions_payload",
    "build_source_image_summary_payload",
    "get_or_create_sam3_interactive_runtime_session",
    "get_or_create_sam3_semantic_runtime_session",
    "merge_text_prompt_items",
    "normalize_device",
    "normalize_model_scale",
    "normalize_precision",
    "raise_not_implemented",
    "read_image_bytes",
    "read_interactive_prompt_items",
    "read_text_prompt_items",
    "resolve_sam3_pretrained_variant",
]
