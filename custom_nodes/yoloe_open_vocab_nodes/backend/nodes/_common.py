"""YOLOE open vocabulary 节点公共 helper。"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
import torch

from backend.nodes.runtime_support import load_image_bytes, register_image_bytes
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


@dataclass(frozen=True)
class YoloeVisualPromptItem:
    """描述一条视觉提示。"""

    prompt_id: str
    prompt_kind: str
    bbox_xyxy: tuple[float, float, float, float]
    display_name: str


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
        if not prompt_id:
            raise InvalidRequestError("YOLOE 文本提示节点要求 prompt_id 不能为空")
        if not text:
            raise InvalidRequestError("YOLOE 文本提示节点要求 text 不能为空")
        if negative:
            raise InvalidRequestError("YOLOE 文本提示节点第一阶段暂不支持 negative prompts")
        prompt_items.append(YoloePromptItem(prompt_id=prompt_id, text=text, display_name=display_name or text))
    return tuple(prompt_items)


def read_visual_prompt_items(payload: object) -> tuple[YoloeVisualPromptItem, ...]:
    """把 prompt-regions.v1 payload 规范化为第一阶段 box prompt 列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("YOLOE 视觉提示节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 prompts.items 必须是非空数组")
    prompt_items: list[YoloeVisualPromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("YOLOE 视觉提示节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        prompt_kind = str(item.get("prompt_kind") or "").strip().lower()
        display_name = str(item.get("display_name") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("YOLOE 视觉提示节点要求 prompt_id 不能为空")
        if prompt_kind != "box":
            raise InvalidRequestError(
                "YOLOE 视觉提示节点第一阶段只支持 box prompt",
                details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
            )
        bbox_xyxy = item.get("bbox_xyxy")
        if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
            raise InvalidRequestError("YOLOE 视觉提示节点要求 bbox_xyxy 必须是长度为 4 的数组")
        try:
            normalized_bbox = tuple(float(value) for value in bbox_xyxy)
        except Exception as exc:
            raise InvalidRequestError("YOLOE 视觉提示节点要求 bbox_xyxy 必须是数字数组") from exc
        prompt_items.append(
            YoloeVisualPromptItem(
                prompt_id=prompt_id,
                prompt_kind=prompt_kind,
                bbox_xyxy=normalized_bbox,
                display_name=display_name,
            )
        )
    return tuple(prompt_items)


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
            {"prompt_id": item.prompt_id, "text": item.text, "display_name": item.display_name}
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
            {
                "prompt_id": item.prompt_id,
                "prompt_kind": item.prompt_kind,
                "bbox_xyxy": list(item.bbox_xyxy),
                "display_name": item.display_name,
            }
            for item in prompts
        ],
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_image": build_source_image_summary_payload(prompt_image_payload),
    }


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
