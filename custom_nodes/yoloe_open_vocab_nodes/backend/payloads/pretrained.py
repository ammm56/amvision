"""YOLOE 预训练资产与参数规范化 helper。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.types import YoloePretrainedVariant


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
YOLOE_PRETRAINED_ROOT = REPOSITORY_ROOT / "data" / "files" / "models" / "pretrained" / "yoloe" / "segmentation"
SUPPORTED_MODEL_SERIES = frozenset({"v8", "11", "26"})
SUPPORTED_MODEL_SCALES = frozenset({"nano", "tiny", "s", "m", "l", "x", "xx"})
SUPPORTED_PRECISIONS = frozenset({"fp32", "fp16", "bf16"})
DEFAULT_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_IOU_THRESHOLD = 0.7
DEFAULT_MAX_DETECTIONS = 100
DEFAULT_DEVICE = "cpu"
DEFAULT_PRECISION = "fp32"


def raise_project_native_runtime_not_implemented(
    *,
    mode_name: str,
    model_series: str,
    model_scale: str,
    prompt_free: bool,
) -> None:
    """抛出统一的 project-native YOLOE runtime 未接通错误。"""

    variant = resolve_yoloe_pretrained_variant(
        model_series=model_series,
        model_scale=model_scale,
        prompt_free=prompt_free,
    )
    raise InvalidRequestError(
        f"YOLOE {mode_name} 的 project-native 推理实现尚未接通，当前节点不会回退到外部 Python 包或 projectsrc 参考代码",
        details={
            "mode_name": mode_name,
            "model_series": variant.model_series,
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
    model_series: str,
    model_scale: str,
    prompt_free: bool,
) -> YoloePretrainedVariant:
    """按系列、尺寸和变体解析 YOLOE 预训练目录。"""

    normalized_series = normalize_model_series(model_series)
    normalized_scale = normalize_model_scale(model_scale)
    variant_name = f"{normalized_series}-{'prompt-free' if prompt_free else 'default'}"
    variant_dir = YOLOE_PRETRAINED_ROOT / normalized_scale / variant_name
    manifest_path = variant_dir / "manifest.json"
    if not manifest_path.is_file():
        raise InvalidRequestError(
            "找不到指定的 YOLOE 预训练 manifest",
            details={
                "model_series": normalized_series,
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
        model_series=normalized_series,
        model_scale=normalized_scale,
        prompt_free=prompt_free,
        variant_name=variant_name,
        manifest_path=manifest_path,
        checkpoint_path=checkpoint_path,
        model_name=str(manifest_payload.get("model_name") or f"yoloe-{normalized_series}"),
        task_type=str(manifest_payload.get("task_type") or "segmentation"),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def normalize_model_series(value: object) -> str:
    """规范化模型系列。"""

    normalized_value = str(value or "").strip().lower()
    if normalized_value not in SUPPORTED_MODEL_SERIES:
        raise InvalidRequestError(
            "YOLOE 节点要求 model_series 只能是 v8、11 或 26",
            details={"model_series": value, "supported": sorted(SUPPORTED_MODEL_SERIES)},
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




__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_DEVICE",
    "DEFAULT_IOU_THRESHOLD",
    "DEFAULT_MAX_DETECTIONS",
    "DEFAULT_PRECISION",
    "SUPPORTED_MODEL_SCALES",
    "SUPPORTED_MODEL_SERIES",
    "SUPPORTED_PRECISIONS",
    "YOLOE_PRETRAINED_ROOT",
    "normalize_confidence_threshold",
    "normalize_device",
    "normalize_iou_threshold",
    "normalize_max_detections",
    "normalize_model_scale",
    "normalize_model_series",
    "normalize_precision",
    "raise_not_implemented",
    "raise_project_native_runtime_not_implemented",
    "resolve_yoloe_pretrained_variant",
]
