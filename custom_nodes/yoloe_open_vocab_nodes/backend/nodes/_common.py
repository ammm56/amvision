"""YOLOE open vocabulary 节点公共 helper。"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from backend.nodes.runtime_support import load_image_bytes, load_image_bytes_from_payload, register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
YOLOE_PRETRAINED_ROOT = REPOSITORY_ROOT / "data" / "files" / "models" / "pretrained" / "yoloe" / "segmentation"
SUPPORTED_MODEL_FAMILIES = frozenset({"v8", "11", "26"})
SUPPORTED_MODEL_SCALES = frozenset({"nano", "tiny", "s", "m", "l", "x", "xx"})
SUPPORTED_PRECISIONS = frozenset({"fp32", "fp16", "bf16"})
DEFAULT_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_IOU_THRESHOLD = 0.7
DEFAULT_MAX_DETECTIONS = 100
DEFAULT_DEVICE = "cpu"
DEFAULT_PRECISION = "fp32"


@dataclass(frozen=True)
class YoloePromptItem:
    """描述一条文本提示。"""

    prompt_id: str
    text: str
    display_name: str
    negative: bool = False
    language: str | None = None


@dataclass(frozen=True)
class YoloePromptGroup:
    """描述一个按 prompt_id 聚合后的文本提示组。"""

    prompt_id: str
    display_name: str
    positive_texts: tuple[str, ...]
    negative_texts: tuple[str, ...]
    languages: tuple[str, ...]


@dataclass(frozen=True)
class YoloeVisualPromptItem:
    """描述一条视觉提示。"""

    prompt_id: str
    prompt_kind: str
    bbox_xyxy: tuple[float, float, float, float] | None
    point_xy: tuple[float, float] | None
    point_label: str | None
    polygon_xy: tuple[tuple[float, float], ...] | None
    prompt_mask: np.ndarray | None
    display_name: str
    prompt_kinds: tuple[str, ...] = ()
    raw_item_count: int = 1


@dataclass(frozen=True)
class YoloePretrainedVariant:
    """描述一个 YOLOE 预训练权重目录。"""

    model_family: str
    model_scale: str
    prompt_free: bool
    variant_name: str
    manifest_path: Path
    checkpoint_path: Path
    model_name: str
    task_type: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class YoloeDetectionPrediction:
    """描述一次 YOLOE 推理结果。"""

    detections: tuple[dict[str, object], ...]
    summary: dict[str, object]
    regions: tuple[dict[str, object], ...] = ()


YoloeTextPromptPrediction = YoloeDetectionPrediction


def raise_project_native_runtime_not_implemented(
    *,
    mode_name: str,
    model_family: str,
    model_scale: str,
    prompt_free: bool,
) -> None:
    """抛出统一的 project-native YOLOE runtime 未接通错误。"""

    variant = resolve_yoloe_pretrained_variant(
        model_family=model_family,
        model_scale=model_scale,
        prompt_free=prompt_free,
    )
    raise InvalidRequestError(
        f"YOLOE {mode_name} 的 project-native 推理实现尚未接通，当前节点不会回退到外部 Python 包或 projectsrc 参考代码",
        details={
            "mode_name": mode_name,
            "model_family": variant.model_family,
            "model_scale": variant.model_scale,
            "prompt_free": variant.prompt_free,
            "task_type": variant.task_type,
            "manifest_path": str(variant.manifest_path),
            "checkpoint_path": str(variant.checkpoint_path),
            "pretrained_root": str(YOLOE_PRETRAINED_ROOT),
        },
    )


def raise_not_implemented(request: WorkflowNodeExecutionRequest, *, mode_name: str) -> dict[str, object]:
    """抛出统一的“骨架已注册但推理未接通”错误。"""

    raise InvalidRequestError(
        f"YOLOE {mode_name} 节点骨架已注册，但 project-native 推理实现尚未接通",
        details={
            "node_id": request.node_id,
            "node_type_id": request.node_type_id,
            "pretrained_root": "data/files/models/pretrained/yoloe",
        },
    )


def resolve_yoloe_pretrained_variant(
    *,
    model_family: str,
    model_scale: str,
    prompt_free: bool,
) -> YoloePretrainedVariant:
    """按 family/scale/variant 解析 YOLOE 预训练目录。"""

    normalized_family = normalize_model_family(model_family)
    normalized_scale = normalize_model_scale(model_scale)
    variant_name = f"{normalized_family}-{'prompt-free' if prompt_free else 'default'}"
    variant_dir = YOLOE_PRETRAINED_ROOT / normalized_scale / variant_name
    manifest_path = variant_dir / "manifest.json"
    if not manifest_path.is_file():
        raise InvalidRequestError(
            "找不到指定的 YOLOE 预训练 manifest",
            details={
                "model_family": normalized_family,
                "model_scale": normalized_scale,
                "prompt_free": prompt_free,
                "manifest_path": str(manifest_path),
            },
        )
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InvalidRequestError(
            "YOLOE 预训练 manifest 不是合法 JSON",
            details={"manifest_path": str(manifest_path)},
        ) from exc
    checkpoint_path_value = manifest_payload.get("checkpoint_path")
    if not isinstance(checkpoint_path_value, str) or not checkpoint_path_value.strip():
        raise InvalidRequestError(
            "YOLOE 预训练 manifest 缺少 checkpoint_path",
            details={"manifest_path": str(manifest_path)},
        )
    checkpoint_path = (variant_dir / checkpoint_path_value).resolve()
    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "YOLOE 预训练 checkpoint 文件不存在",
            details={
                "manifest_path": str(manifest_path),
                "checkpoint_path": str(checkpoint_path),
            },
        )
    metadata = manifest_payload.get("metadata")
    return YoloePretrainedVariant(
        model_family=normalized_family,
        model_scale=normalized_scale,
        prompt_free=prompt_free,
        variant_name=variant_name,
        manifest_path=manifest_path,
        checkpoint_path=checkpoint_path,
        model_name=str(manifest_payload.get("model_name") or f"yoloe-{normalized_family}"),
        task_type=str(manifest_payload.get("task_type") or "segmentation"),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def get_or_create_yoloe_text_prompt_runtime_session(
    *,
    model_family: str,
    model_scale: str,
    device: str,
    precision: str,
) -> object:
    """返回可复用的 YOLOE 文本提示推理会话。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_family=model_family,
        model_scale=model_scale,
        prompt_free=False,
    )
    from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._project_native_runtime import (
        get_or_create_text_prompt_runtime_session,
    )

    return get_or_create_text_prompt_runtime_session(
        variant=variant,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def get_or_create_yoloe_prompt_free_runtime_session(
    *,
    model_family: str,
    model_scale: str,
    device: str,
    precision: str,
) -> object:
    """返回可复用的 YOLOE prompt-free 推理会话。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_family=model_family,
        model_scale=model_scale,
        prompt_free=True,
    )
    from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._project_native_runtime import (
        get_or_create_prompt_free_runtime_session,
    )

    return get_or_create_prompt_free_runtime_session(
        variant=variant,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def decode_image_bytes(image_bytes: bytes) -> Image.Image:
    """把图片字节解码为 RGB PIL Image。"""

    try:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:  # pragma: no cover - 输入图片损坏时由集成调用触发
        raise InvalidRequestError("YOLOE 节点收到的图片不是有效图像") from exc


def build_predict_kwargs(
    *,
    source_image: Image.Image,
    device: str,
    precision: str,
    confidence_threshold: float,
    iou_threshold: float,
    max_detections: int,
) -> dict[str, object]:
    """构造统一的 YOLOE 推理参数。"""

    return {
        "source": source_image,
        "device": device,
        "verbose": False,
        "conf": confidence_threshold,
        "iou": iou_threshold,
        "max_det": max_detections,
        "half": precision == "fp16",
    }


def build_detection_items_from_runtime_result(
    result: object,
    *,
    class_name_map: dict[int, str] | None = None,
    prompt_id_map: dict[int, str] | None = None,
    source_text_map: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    """把 YOLOE 运行时结果规整为 detections.v1 items。"""

    if result is None or getattr(result, "boxes", None) is None:
        return []
    result_names = getattr(result, "names", None)
    detection_items: list[dict[str, object]] = []
    boxes = result.boxes
    for index in range(len(boxes)):
        box = boxes[index]
        class_id = int(box.cls[0].item())
        score = float(box.conf[0].item())
        bbox_xyxy = [float(value) for value in box.xyxy[0].tolist()]
        class_name = (
            (class_name_map or {}).get(class_id)
            or (source_text_map or {}).get(class_id)
            or read_runtime_result_class_name(result_names, class_id)
            or str(class_id)
        )
        item = {
            "bbox_xyxy": bbox_xyxy,
            "score": score,
            "class_id": class_id,
            "class_name": class_name,
        }
        prompt_id = (prompt_id_map or {}).get(class_id)
        if prompt_id is not None:
            item["prompt_id"] = prompt_id
        source_prompt_text = (source_text_map or {}).get(class_id)
        if source_prompt_text is not None:
            item["source_prompt_text"] = source_prompt_text
        detection_items.append(item)
    return detection_items


def build_region_items_from_runtime_result(
    result: object,
    *,
    class_name_map: dict[int, str] | None = None,
    prompt_id_map: dict[int, str] | None = None,
    source_text_map: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    """把 YOLOE 运行时结果规整为 regions.v1 items。"""

    if result is None or getattr(result, "boxes", None) is None:
        return []

    result_names = getattr(result, "names", None)
    boxes = result.boxes
    masks = getattr(result, "masks", None)
    polygon_items = getattr(masks, "xy", None) if masks is not None else None
    mask_tensor_items = getattr(masks, "data", None) if masks is not None else None
    region_items: list[dict[str, object]] = []

    for index in range(len(boxes)):
        box = boxes[index]
        class_id = int(box.cls[0].item())
        score = float(box.conf[0].item())
        bbox_xyxy = [float(value) for value in box.xyxy[0].tolist()]
        class_name = (
            (class_name_map or {}).get(class_id)
            or (source_text_map or {}).get(class_id)
            or read_runtime_result_class_name(result_names, class_id)
            or str(class_id)
        )
        polygon_xy = normalize_runtime_polygon_xy(
            polygon_items[index] if isinstance(polygon_items, (list, tuple)) and index < len(polygon_items) else None,
            fallback_bbox_xyxy=bbox_xyxy,
        )
        mask_tensor = None
        if torch.is_tensor(mask_tensor_items) and index < int(mask_tensor_items.shape[0]):
            mask_tensor = mask_tensor_items[index]
        mask_png_bytes, mask_width, mask_height, mask_area = encode_runtime_mask_png(mask_tensor)
        item = {
            "region_id": f"region-{index + 1}",
            "bbox_xyxy": bbox_xyxy,
            "score": score,
            "class_id": class_id,
            "class_name": class_name,
            "polygon_xy": polygon_xy,
            "area": mask_area,
        }
        prompt_id = (prompt_id_map or {}).get(class_id)
        if prompt_id is not None:
            item["prompt_id"] = prompt_id
        source_prompt_text = (source_text_map or {}).get(class_id)
        if source_prompt_text is not None:
            item["source_prompt_text"] = source_prompt_text
        if mask_png_bytes is not None and mask_width is not None and mask_height is not None:
            item["mask_png_bytes"] = mask_png_bytes
            item["mask_width"] = mask_width
            item["mask_height"] = mask_height
        region_items.append(item)
    return region_items


def read_runtime_result_class_name(result_names: object, class_id: int) -> str | None:
    """从 YOLOE 运行时结果中读取类别名。"""

    if isinstance(result_names, dict):
        raw_value = result_names.get(class_id)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def normalize_runtime_polygon_xy(raw_polygon: object, *, fallback_bbox_xyxy: list[float]) -> list[list[float]]:
    """把运行时 polygon 规整为 workflow 可消费的 polygon_xy。"""

    if isinstance(raw_polygon, np.ndarray) and raw_polygon.ndim == 2 and raw_polygon.shape[1] >= 2:
        return [[float(point[0]), float(point[1])] for point in raw_polygon.tolist()]
    if isinstance(raw_polygon, (list, tuple)) and raw_polygon:
        first_item = raw_polygon[0]
        if isinstance(first_item, np.ndarray) and first_item.ndim == 2 and first_item.shape[1] >= 2:
            return normalize_runtime_polygon_xy(first_item, fallback_bbox_xyxy=fallback_bbox_xyxy)
        if (
            isinstance(first_item, (list, tuple))
            and len(first_item) >= 2
            and isinstance(first_item[0], (int, float))
            and isinstance(first_item[1], (int, float))
        ):
            return [[float(point[0]), float(point[1])] for point in raw_polygon]
        if isinstance(first_item, (list, tuple)) and first_item and isinstance(first_item[0], (list, tuple, np.ndarray)):
            return normalize_runtime_polygon_xy(first_item, fallback_bbox_xyxy=fallback_bbox_xyxy)
    return build_bbox_polygon_xy(fallback_bbox_xyxy)


def build_bbox_polygon_xy(bbox_xyxy: list[float]) -> list[list[float]]:
    """把 bbox_xyxy 转成四点 polygon。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return [
        [float(x1_value), float(y1_value)],
        [float(x2_value), float(y1_value)],
        [float(x2_value), float(y2_value)],
        [float(x1_value), float(y2_value)],
    ]


def encode_runtime_mask_png(mask_tensor: object) -> tuple[bytes | None, int | None, int | None, int]:
    """把运行时 mask tensor 编码成 PNG 字节。"""

    if not torch.is_tensor(mask_tensor):
        return None, None, None, 0
    normalized_mask = (mask_tensor.detach().float().cpu() > 0.5).to(dtype=torch.uint8).numpy() * 255
    if normalized_mask.ndim != 2:
        return None, None, None, 0
    mask_height, mask_width = normalized_mask.shape
    mask_area = int(np.count_nonzero(normalized_mask))
    encoded_image = Image.fromarray(normalized_mask, mode="L")
    buffer = io.BytesIO()
    encoded_image.save(buffer, format="PNG")
    return buffer.getvalue(), int(mask_width), int(mask_height), mask_area


def build_prediction_summary(
    *,
    variant: YoloePretrainedVariant,
    detection_items: list[dict[str, object]],
    region_items: list[dict[str, object]],
    device: str,
    precision: str,
    confidence_threshold: float,
    iou_threshold: float,
    max_detections: int,
    prompt_count: int,
    vocabulary_size: int | None,
) -> dict[str, object]:
    """构造统一的 YOLOE 推理摘要。"""

    summary = {
        "model_family": variant.model_family,
        "model_scale": variant.model_scale,
        "variant_name": variant.variant_name,
        "checkpoint_path": str(variant.checkpoint_path),
        "task_type": variant.task_type,
        "prompt_count": prompt_count,
        "detection_count": len(detection_items),
        "region_count": len(region_items),
        "device": device,
        "precision": precision,
        "confidence_threshold": confidence_threshold,
        "iou_threshold": iou_threshold,
        "max_detections": max_detections,
        "prompt_free": variant.prompt_free,
    }
    if vocabulary_size is not None:
        summary["vocabulary_size"] = vocabulary_size
    return summary


def read_text_prompt_items(payload: object) -> tuple[YoloePromptItem, ...]:
    """把 text-prompts.v1 payload 规范化为提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("YOLOE 文本提示节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("YOLOE 文本提示节点要求 prompts.items 必须是非空数组")
    prompt_items: list[YoloePromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("YOLOE 文本提示节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        text = str(item.get("text") or "").strip()
        display_name = str(item.get("display_name") or text).strip()
        negative = bool(item.get("negative"))
        language = str(item.get("language") or "").strip() or None
        if not prompt_id:
            raise InvalidRequestError("YOLOE 文本提示节点要求 prompt_id 不能为空")
        if not text:
            raise InvalidRequestError("YOLOE 文本提示节点要求 text 不能为空")
        prompt_items.append(
            YoloePromptItem(
                prompt_id=prompt_id,
                text=text,
                display_name=display_name or text,
                negative=negative,
                language=language,
            )
        )
    return tuple(prompt_items)


def merge_text_prompt_items(prompts: tuple[YoloePromptItem, ...]) -> tuple[YoloePromptGroup, ...]:
    """按 prompt_id 聚合文本提示，支持正负文本组合。"""

    grouped_records: dict[str, list[YoloePromptItem]] = {}
    display_name_map: dict[str, str] = {}
    for item in prompts:
        prompt_id = str(getattr(item, "prompt_id", "") or "").strip()
        display_name = str(getattr(item, "display_name", "") or getattr(item, "text", "") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("YOLOE text prompt 聚合要求 prompt_id 不能为空")
        previous_display_name = display_name_map.get(prompt_id)
        if previous_display_name is not None and previous_display_name != display_name:
            raise InvalidRequestError(
                "同一个 YOLOE text prompt_id 只能对应一个 display_name",
                details={
                    "prompt_id": prompt_id,
                    "display_name": display_name,
                    "previous_display_name": previous_display_name,
                },
            )
        display_name_map[prompt_id] = display_name
        grouped_records.setdefault(prompt_id, []).append(item)

    prompt_groups: list[YoloePromptGroup] = []
    for prompt_id, items in grouped_records.items():
        positive_texts = tuple(
            dict.fromkeys(
                str(getattr(item, "text", "") or "").strip()
                for item in items
                if not bool(getattr(item, "negative", False))
            )
        )
        negative_texts = tuple(
            dict.fromkeys(
                str(getattr(item, "text", "") or "").strip()
                for item in items
                if bool(getattr(item, "negative", False))
            )
        )
        positive_texts = tuple(item for item in positive_texts if item)
        negative_texts = tuple(item for item in negative_texts if item)
        if not positive_texts:
            raise InvalidRequestError(
                "YOLOE text prompt 每个 prompt_id 至少要包含一条 positive 文本",
                details={"prompt_id": prompt_id},
            )
        languages = tuple(
            dict.fromkeys(
                str(getattr(item, "language"))
                for item in items
                if getattr(item, "language", None) is not None and str(getattr(item, "language")).strip()
            )
        )
        prompt_groups.append(
            YoloePromptGroup(
                prompt_id=prompt_id,
                display_name=display_name_map[prompt_id],
                positive_texts=positive_texts,
                negative_texts=negative_texts,
                languages=languages,
            )
        )
    return tuple(prompt_groups)


def read_visual_prompt_items(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest | None = None,
    prompt_image_payload: dict[str, object] | None = None,
    prompt_image_bytes: bytes | None = None,
) -> tuple[YoloeVisualPromptItem, ...]:
    """把 prompt-regions.v1 payload 规范化并按 prompt_id 聚合为 YOLOE 视觉提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("YOLOE 视觉提示节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 prompts.items 必须是非空数组")
    prompt_image_size = _resolve_visual_prompt_image_size(
        prompt_image_payload=prompt_image_payload,
        prompt_image_bytes=prompt_image_bytes,
    )
    raw_prompt_records: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("YOLOE 视觉提示节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        prompt_kind = str(item.get("prompt_kind") or "").strip().lower()
        display_name = str(item.get("display_name") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("YOLOE 视觉提示节点要求 prompt_id 不能为空")
        normalized_bbox: tuple[float, float, float, float] | None = None
        normalized_point_xy: tuple[float, float] | None = None
        normalized_point_label: str | None = None
        normalized_polygon_xy: tuple[tuple[float, float], ...] | None = None
        normalized_prompt_mask: np.ndarray | None = None
        if prompt_kind == "box":
            normalized_bbox = _normalize_visual_prompt_bbox(item.get("bbox_xyxy"))
            normalized_prompt_mask = _rasterize_visual_prompt_box_mask(
                prompt_image_size=prompt_image_size,
                bbox_xyxy=normalized_bbox,
            )
        elif prompt_kind == "point":
            normalized_point_xy = _normalize_visual_prompt_point_xy(item.get("point_xy"))
            normalized_point_label = _normalize_visual_prompt_point_label(item.get("point_label"))
            normalized_prompt_mask = _rasterize_visual_prompt_point_mask(
                prompt_image_size=prompt_image_size,
                point_xy=normalized_point_xy,
            )
        elif prompt_kind == "polygon":
            normalized_polygon_xy = _normalize_visual_prompt_polygon(item.get("polygon_xy"))
            normalized_prompt_mask = _rasterize_visual_prompt_polygon_mask(
                prompt_image_size=prompt_image_size,
                polygon_xy=normalized_polygon_xy,
            )
        elif prompt_kind == "mask":
            if request is None:
                raise InvalidRequestError("YOLOE mask visual prompt 需要节点执行上下文")
            normalized_prompt_mask = _load_visual_prompt_mask(
                request=request,
                mask_image_payload=item.get("mask_image"),
                prompt_image_size=prompt_image_size,
            )
        else:
            raise InvalidRequestError(
                "YOLOE visual-prompt 暂不支持指定的 prompt_kind",
                details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
            )
        raw_prompt_records.append(
            {
                "prompt_id": prompt_id,
                "prompt_kind": prompt_kind,
                "bbox_xyxy": normalized_bbox,
                "point_xy": normalized_point_xy,
                "point_label": normalized_point_label,
                "polygon_xy": normalized_polygon_xy,
                "prompt_mask": normalized_prompt_mask,
                "display_name": display_name,
            }
        )
    return _merge_visual_prompt_records(raw_prompt_records, prompt_image_size=prompt_image_size)


def read_image_bytes(request: WorkflowNodeExecutionRequest, *, input_name: str = "image") -> tuple[dict[str, object], bytes]:
    """读取节点图片输入。"""

    return load_image_bytes(request, input_name=input_name)


def normalize_model_family(value: object) -> str:
    """规范化模型 family。"""

    normalized_value = str(value or "").strip().lower()
    if normalized_value not in SUPPORTED_MODEL_FAMILIES:
        raise InvalidRequestError(
            "YOLOE 节点要求 model_family 只能是 v8、11 或 26",
            details={"model_family": value, "supported": sorted(SUPPORTED_MODEL_FAMILIES)},
        )
    return normalized_value


def normalize_model_scale(value: object) -> str:
    """规范化模型 scale。"""

    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        normalized_value = "s"
    if normalized_value not in SUPPORTED_MODEL_SCALES:
        raise InvalidRequestError(
            "YOLOE 节点要求 model_scale 使用统一 scale 命名",
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
            "YOLOE 节点 precision 只能是 fp32、fp16 或 bf16",
            details={"precision": value, "supported": sorted(SUPPORTED_PRECISIONS)},
        )
    if normalized_value == "bf16":
        raise InvalidRequestError("YOLOE 节点第一阶段暂不支持 bf16")
    return normalized_value


def normalize_confidence_threshold(value: object) -> float:
    """规范化 confidence 阈值。"""

    if value in (None, ""):
        return DEFAULT_CONFIDENCE_THRESHOLD
    normalized_value = float(value)
    if normalized_value < 0 or normalized_value > 1:
        raise InvalidRequestError("confidence_threshold 必须位于 0 到 1 之间")
    return normalized_value


def normalize_iou_threshold(value: object) -> float:
    """规范化 IoU 阈值。"""

    if value in (None, ""):
        return DEFAULT_IOU_THRESHOLD
    normalized_value = float(value)
    if normalized_value < 0 or normalized_value > 1:
        raise InvalidRequestError("iou_threshold 必须位于 0 到 1 之间")
    return normalized_value


def normalize_max_detections(value: object) -> int:
    """规范化最大检测数。"""

    if value in (None, ""):
        return DEFAULT_MAX_DETECTIONS
    normalized_value = int(value)
    if normalized_value < 1:
        raise InvalidRequestError("max_detections 必须大于等于 1")
    return normalized_value


def build_text_prompt_summary_payload(
    *,
    prediction: YoloeDetectionPrediction,
    prompts: tuple[YoloePromptItem, ...],
    image_payload: dict[str, object],
) -> dict[str, object]:
    """构建 text-prompt-detect 节点的 summary payload。"""

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
            for item in prompts
        ],
        "source_image": build_source_image_summary_payload(image_payload),
    }


def build_prompt_free_summary_payload(
    *,
    prediction: YoloeDetectionPrediction,
    image_payload: dict[str, object],
) -> dict[str, object]:
    """构建 prompt-free 节点 summary payload。"""

    return {
        **prediction.summary,
        "source_image": build_source_image_summary_payload(image_payload),
    }


def build_visual_prompt_summary_payload(
    *,
    prediction: YoloeDetectionPrediction,
    prompts: tuple[YoloeVisualPromptItem, ...],
    image_payload: dict[str, object],
    prompt_image_payload: dict[str, object],
) -> dict[str, object]:
    """构建 visual-prompt-detect 节点 summary payload。"""

    return {
        **prediction.summary,
        "prompt_items": [
            _build_visual_prompt_summary_item(item)
            for item in prompts
        ],
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_image": build_source_image_summary_payload(prompt_image_payload),
    }


def _build_visual_prompt_summary_item(item: YoloeVisualPromptItem) -> dict[str, object]:
    """构造单条视觉提示的 summary 字段。"""

    payload: dict[str, object] = {
        "prompt_id": item.prompt_id,
        "prompt_kind": item.prompt_kind,
        "display_name": item.display_name,
    }
    if item.prompt_kinds:
        payload["prompt_kinds"] = list(item.prompt_kinds)
    payload["raw_item_count"] = int(item.raw_item_count)
    if item.bbox_xyxy is not None:
        payload["bbox_xyxy"] = list(item.bbox_xyxy)
    if item.point_xy is not None:
        payload["point_xy"] = list(item.point_xy)
    if item.point_label is not None:
        payload["point_label"] = item.point_label
    if item.polygon_xy is not None:
        payload["polygon_xy"] = [list(point) for point in item.polygon_xy]
    if item.prompt_mask is not None:
        payload["has_prompt_mask"] = True
    return payload


def build_source_image_summary_payload(image_payload: dict[str, object]) -> dict[str, object]:
    """提取图片摘要里需要保留的 source image 字段。"""

    return {
        key: image_payload.get(key)
        for key in ("transport_kind", "media_type", "width", "height", "object_key", "image_handle")
        if image_payload.get(key) is not None
    }


def _resolve_visual_prompt_image_size(
    *,
    prompt_image_payload: dict[str, object] | None,
    prompt_image_bytes: bytes | None,
) -> tuple[int, int]:
    """解析视觉提示参考图尺寸。"""

    width_value = None if prompt_image_payload is None else prompt_image_payload.get("width")
    height_value = None if prompt_image_payload is None else prompt_image_payload.get("height")
    try:
        width = int(width_value) if width_value is not None else 0
        height = int(height_value) if height_value is not None else 0
    except Exception:
        width = 0
        height = 0
    if width > 0 and height > 0:
        return width, height
    if isinstance(prompt_image_bytes, bytes) and prompt_image_bytes:
        prompt_image = decode_image_bytes(prompt_image_bytes)
        return int(prompt_image.width), int(prompt_image.height)
    raise InvalidRequestError("YOLOE visual-prompt 无法解析 prompt_image 尺寸")


def _normalize_visual_prompt_bbox(payload: object) -> tuple[float, float, float, float]:
    """规范化 box prompt。"""

    if not isinstance(payload, list) or len(payload) != 4:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 bbox_xyxy 必须是长度为 4 的数组")
    try:
        x1_value, y1_value, x2_value, y2_value = (float(value) for value in payload)
    except Exception as exc:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 bbox_xyxy 必须是数字数组") from exc
    return x1_value, y1_value, x2_value, y2_value


def _normalize_visual_prompt_point_xy(payload: object) -> tuple[float, float]:
    """规范化 point prompt 坐标。"""

    if not isinstance(payload, list) or len(payload) != 2:
        raise InvalidRequestError("YOLOE point visual prompt 要求 point_xy 是长度为 2 的数组")
    try:
        x_value, y_value = (float(value) for value in payload)
    except Exception as exc:
        raise InvalidRequestError("YOLOE point visual prompt 要求 point_xy 必须是数字数组") from exc
    return x_value, y_value


def _normalize_visual_prompt_point_label(value: object) -> str:
    """规范化 point prompt 正负标签。"""

    normalized_value = str(value or "positive").strip().lower()
    if normalized_value not in {"positive", "negative"}:
        raise InvalidRequestError("YOLOE point visual prompt 的 point_label 只能是 positive 或 negative")
    if normalized_value == "negative":
        raise InvalidRequestError("YOLOE visual-prompt 第一阶段暂不支持 negative point")
    return normalized_value


def _normalize_visual_prompt_polygon(payload: object) -> tuple[tuple[float, float], ...]:
    """规范化 polygon prompt 点集。"""

    if not isinstance(payload, list) or len(payload) < 3:
        raise InvalidRequestError("YOLOE polygon visual prompt 要求 polygon_xy 至少包含 3 个点")
    normalized_points: list[tuple[float, float]] = []
    for point in payload:
        if not isinstance(point, list) or len(point) != 2:
            raise InvalidRequestError("YOLOE polygon visual prompt 要求每个 polygon 点都是长度为 2 的数组")
        try:
            normalized_points.append((float(point[0]), float(point[1])))
        except Exception as exc:
            raise InvalidRequestError("YOLOE polygon visual prompt 点坐标必须是数字") from exc
    return tuple(normalized_points)


def _rasterize_visual_prompt_polygon_mask(
    *,
    prompt_image_size: tuple[int, int],
    polygon_xy: tuple[tuple[float, float], ...],
) -> np.ndarray:
    """把 polygon prompt 栅格化成参考图尺寸的二值 mask。"""

    prompt_image_width, prompt_image_height = prompt_image_size
    prompt_mask_image = Image.new("L", (int(prompt_image_width), int(prompt_image_height)), 0)
    draw = ImageDraw.Draw(prompt_mask_image)
    draw.polygon([tuple(float(value) for value in point) for point in polygon_xy], fill=255)
    prompt_mask = np.asarray(prompt_mask_image, dtype=np.uint8)
    return (prompt_mask > 0).astype(np.uint8)


def _rasterize_visual_prompt_box_mask(
    *,
    prompt_image_size: tuple[int, int],
    bbox_xyxy: tuple[float, float, float, float],
) -> np.ndarray:
    """把 box prompt 栅格化成参考图尺寸的二值 mask。"""

    prompt_image_width, prompt_image_height = prompt_image_size
    prompt_mask = np.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np.uint8)
    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    x1_index = max(0, min(int(prompt_image_width), int(np.floor(float(x1_value)))))
    y1_index = max(0, min(int(prompt_image_height), int(np.floor(float(y1_value)))))
    x2_index = max(x1_index + 1, min(int(prompt_image_width), int(np.ceil(float(x2_value)))))
    y2_index = max(y1_index + 1, min(int(prompt_image_height), int(np.ceil(float(y2_value)))))
    if x2_index <= x1_index or y2_index <= y1_index:
        return prompt_mask
    prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
    return prompt_mask


def _rasterize_visual_prompt_point_mask(
    *,
    prompt_image_size: tuple[int, int],
    point_xy: tuple[float, float],
) -> np.ndarray:
    """把 point prompt 栅格化成参考图尺寸的二值 mask。"""

    prompt_image_width, prompt_image_height = prompt_image_size
    prompt_mask = np.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np.uint8)
    point_x_value, point_y_value = point_xy
    point_x_index = max(0, min(int(prompt_image_width) - 1, int(round(float(point_x_value)))))
    point_y_index = max(0, min(int(prompt_image_height) - 1, int(round(float(point_y_value)))))
    radius = max(1, int(round(min(prompt_image_width, prompt_image_height) / 64.0)))
    x1_index = max(0, point_x_index - radius)
    y1_index = max(0, point_y_index - radius)
    x2_index = min(int(prompt_image_width), point_x_index + radius + 1)
    y2_index = min(int(prompt_image_height), point_y_index + radius + 1)
    prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
    return prompt_mask


def _load_visual_prompt_mask(
    *,
    request: WorkflowNodeExecutionRequest,
    mask_image_payload: object,
    prompt_image_size: tuple[int, int],
) -> np.ndarray:
    """读取 mask prompt 并规整到参考图尺寸。"""

    _normalized_payload, mask_image_bytes = load_image_bytes_from_payload(request, image_payload=mask_image_payload)
    mask_image = Image.open(io.BytesIO(mask_image_bytes)).convert("L")
    prompt_image_width, prompt_image_height = prompt_image_size
    if mask_image.width != int(prompt_image_width) or mask_image.height != int(prompt_image_height):
        mask_image = mask_image.resize((int(prompt_image_width), int(prompt_image_height)), resample=Image.NEAREST)
    mask_array = np.asarray(mask_image, dtype=np.uint8)
    return (mask_array > 0).astype(np.uint8)


def _merge_visual_prompt_records(
    raw_prompt_records: list[dict[str, object]],
    *,
    prompt_image_size: tuple[int, int],
) -> tuple[YoloeVisualPromptItem, ...]:
    """按 prompt_id 合并多条视觉提示记录。"""

    grouped_records: dict[str, list[dict[str, object]]] = {}
    display_name_map: dict[str, str] = {}
    for record in raw_prompt_records:
        prompt_id = str(record["prompt_id"])
        display_name = str(record["display_name"])
        previous_display_name = display_name_map.get(prompt_id)
        if previous_display_name is not None and previous_display_name != display_name:
            raise InvalidRequestError(
                "同一个 YOLOE visual prompt_id 只能对应一个 display_name",
                details={
                    "prompt_id": prompt_id,
                    "display_name": display_name,
                    "previous_display_name": previous_display_name,
                },
            )
        display_name_map[prompt_id] = display_name
        grouped_records.setdefault(prompt_id, []).append(record)

    merged_items: list[YoloeVisualPromptItem] = []
    prompt_image_width, prompt_image_height = prompt_image_size
    for prompt_id, records in grouped_records.items():
        prompt_kinds = tuple(sorted({str(record["prompt_kind"]) for record in records}))
        merged_mask = np.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np.uint8)
        for record in records:
            prompt_mask = record.get("prompt_mask")
            if isinstance(prompt_mask, np.ndarray):
                merged_mask = np.maximum(merged_mask, prompt_mask.astype(np.uint8))
        if int(np.count_nonzero(merged_mask)) <= 0:
            merged_prompt_mask: np.ndarray | None = None
        else:
            merged_prompt_mask = merged_mask

        bbox_xyxy: tuple[float, float, float, float] | None = None
        point_xy: tuple[float, float] | None = None
        point_label: str | None = None
        polygon_xy: tuple[tuple[float, float], ...] | None = None
        if len(records) == 1 and len(prompt_kinds) == 1:
            bbox_xyxy = records[0].get("bbox_xyxy") if isinstance(records[0].get("bbox_xyxy"), tuple) else None
            point_xy = records[0].get("point_xy") if isinstance(records[0].get("point_xy"), tuple) else None
            point_label = str(records[0].get("point_label")) if records[0].get("point_label") is not None else None
            polygon_xy = records[0].get("polygon_xy") if isinstance(records[0].get("polygon_xy"), tuple) else None
        elif merged_prompt_mask is not None:
            bbox_xyxy = _compute_visual_prompt_bbox_from_mask(merged_prompt_mask)

        merged_items.append(
            YoloeVisualPromptItem(
                prompt_id=prompt_id,
                prompt_kind=prompt_kinds[0] if len(prompt_kinds) == 1 else "mixed",
                bbox_xyxy=bbox_xyxy,
                point_xy=point_xy,
                point_label=point_label,
                polygon_xy=polygon_xy,
                prompt_mask=merged_prompt_mask,
                display_name=display_name_map[prompt_id],
                prompt_kinds=prompt_kinds,
                raw_item_count=len(records),
            )
        )
    return tuple(merged_items)


def _compute_visual_prompt_bbox_from_mask(prompt_mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """从聚合后的 prompt mask 反推外接框。"""

    if prompt_mask.ndim != 2:
        return None
    mask_indices = np.argwhere(prompt_mask > 0)
    if int(mask_indices.shape[0]) <= 0:
        return None
    y1_index = int(mask_indices[:, 0].min())
    y2_index = int(mask_indices[:, 0].max()) + 1
    x1_index = int(mask_indices[:, 1].min())
    x2_index = int(mask_indices[:, 1].max()) + 1
    return float(x1_index), float(y1_index), float(x2_index), float(y2_index)


def build_regions_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    prediction: YoloeDetectionPrediction,
    image_payload: dict[str, object],
) -> dict[str, object]:
    """把内部 region 结果转换为 workflow regions.v1 payload。"""

    region_items: list[dict[str, object]] = []
    for item in prediction.regions:
        normalized_item = {
            "region_id": item["region_id"],
            "score": item["score"],
            "class_id": item["class_id"],
            "class_name": item["class_name"],
            "bbox_xyxy": list(item["bbox_xyxy"]),
            "polygon_xy": [list(point) for point in item.get("polygon_xy", [])],
            "area": int(item.get("area") or 0),
        }
        if item.get("prompt_id") is not None:
            normalized_item["prompt_id"] = item["prompt_id"]
        if item.get("source_prompt_text") is not None:
            normalized_item["source_prompt_text"] = item["source_prompt_text"]
        if item.get("source_prompt_positive_texts") is not None:
            normalized_item["source_prompt_positive_texts"] = list(item["source_prompt_positive_texts"])
        if item.get("source_prompt_negative_texts") is not None:
            normalized_item["source_prompt_negative_texts"] = list(item["source_prompt_negative_texts"])
        mask_png_bytes = item.get("mask_png_bytes")
        mask_width = item.get("mask_width")
        mask_height = item.get("mask_height")
        if isinstance(mask_png_bytes, bytes) and isinstance(mask_width, int) and isinstance(mask_height, int):
            normalized_item["mask_image"] = register_image_bytes(
                request,
                content=mask_png_bytes,
                media_type="image/png",
                width=mask_width,
                height=mask_height,
            )
        region_items.append(normalized_item)
    return {
        "source_image": build_source_image_summary_payload(image_payload),
        "count": len(region_items),
        "items": region_items,
    }


def get_or_create_yoloe_visual_prompt_runtime_session(
    *,
    model_family: str,
    model_scale: str,
    device: str,
    precision: str,
) -> object:
    """返回可复用的 YOLOE 视觉提示推理会话。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_family=model_family,
        model_scale=model_scale,
        prompt_free=False,
    )
    from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._project_native_runtime import (
        get_or_create_visual_prompt_runtime_session,
    )

    return get_or_create_visual_prompt_runtime_session(
        variant=variant,
        device_name=normalized_device,
        precision=normalized_precision,
    )


__all__ = [
    "YoloePromptItem",
    "YoloePromptGroup",
    "YoloePretrainedVariant",
    "YoloeDetectionPrediction",
    "YoloeTextPromptPrediction",
    "YoloeVisualPromptItem",
    "build_prompt_free_summary_payload",
    "build_regions_payload",
    "build_text_prompt_summary_payload",
    "build_visual_prompt_summary_payload",
    "decode_image_bytes",
    "build_detection_items_from_runtime_result",
    "build_predict_kwargs",
    "get_or_create_yoloe_text_prompt_runtime_session",
    "get_or_create_yoloe_prompt_free_runtime_session",
    "get_or_create_yoloe_visual_prompt_runtime_session",
    "merge_text_prompt_items",
    "normalize_confidence_threshold",
    "normalize_device",
    "normalize_iou_threshold",
    "normalize_max_detections",
    "normalize_model_family",
    "normalize_model_scale",
    "normalize_precision",
    "raise_not_implemented",
    "read_image_bytes",
    "read_text_prompt_items",
    "read_visual_prompt_items",
    "resolve_yoloe_pretrained_variant",
]
