"""SAM3 预训练模型选择、参数规范化和未实现错误。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.payloads.types import Sam3PretrainedVariant


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SAM3_PRETRAINED_ROOT = REPOSITORY_ROOT / "data" / "files" / "models" / "pretrained" / "sam3" / "segmentation"
SUPPORTED_MODEL_SCALES = frozenset({"nano", "tiny", "s", "m", "l", "x", "xx"})
SUPPORTED_PRECISIONS = frozenset({"fp32", "fp16", "bf16"})
SUPPORTED_POINT_LABELS = frozenset({"positive", "negative"})
DEFAULT_MODEL_SCALE = "l"
DEFAULT_VARIANT_NAME = "default"
DEFAULT_DEVICE = "cpu"
DEFAULT_PRECISION = "fp32"


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
    "DEFAULT_DEVICE",
    "DEFAULT_MODEL_SCALE",
    "DEFAULT_PRECISION",
    "DEFAULT_VARIANT_NAME",
    "SAM3_PRETRAINED_ROOT",
    "SUPPORTED_MODEL_SCALES",
    "SUPPORTED_POINT_LABELS",
    "SUPPORTED_PRECISIONS",
    "normalize_device",
    "normalize_model_scale",
    "normalize_precision",
    "raise_not_implemented",
    "resolve_sam3_pretrained_variant",
]
