"""SAM3 模型资产解析和运行参数规范化。"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from backend.service.application.errors import InvalidRequestError
from custom_nodes.sam3_segment_nodes.backend.payloads.types import Sam3PretrainedVariant


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SAM3_PRETRAINED_ROOT = (
    REPOSITORY_ROOT
    / "data"
    / "files"
    / "models"
    / "pretrained"
    / "sam3"
    / "segmentation"
)
DEFAULT_MODEL_ASSET_ID = "sam3/default"
DEFAULT_DEVICE = "auto"
DEFAULT_PRECISION = "auto"
SUPPORTED_PRECISIONS = frozenset({"auto", "fp32", "fp16", "bf16"})
SUPPORTED_POINT_LABELS = frozenset({"positive", "negative"})
_CUDA_DEVICE_PATTERN = re.compile(r"^cuda:(0|[1-9][0-9]*)$")


@lru_cache(maxsize=1)
def list_sam3_pretrained_variants() -> tuple[Sam3PretrainedVariant, ...]:
    """扫描并返回全部有效 SAM3 本地模型资产。"""

    if not SAM3_PRETRAINED_ROOT.is_dir():
        return ()
    variants: list[Sam3PretrainedVariant] = []
    seen_asset_ids: set[str] = set()
    for manifest_path in sorted(SAM3_PRETRAINED_ROOT.rglob("manifest.json")):
        variant = _read_sam3_pretrained_manifest(manifest_path)
        if variant.model_asset_id in seen_asset_ids:
            raise InvalidRequestError(
                "SAM3 模型资产 id 重复",
                details={
                    "model_asset_id": variant.model_asset_id,
                    "manifest_path": str(manifest_path),
                },
            )
        seen_asset_ids.add(variant.model_asset_id)
        variants.append(variant)
    return tuple(variants)


def resolve_sam3_pretrained_variant(
    *,
    model_asset_id: object = DEFAULT_MODEL_ASSET_ID,
) -> Sam3PretrainedVariant:
    """按稳定资产 id 解析 SAM3 checkpoint。"""

    normalized_asset_id = normalize_model_asset_id(model_asset_id)
    for variant in list_sam3_pretrained_variants():
        if variant.model_asset_id == normalized_asset_id:
            _validate_checkpoint_digest(variant)
            return variant
    raise InvalidRequestError(
        "找不到指定的 SAM3 模型资产",
        details={
            "model_asset_id": normalized_asset_id,
            "available_model_asset_ids": [
                item.model_asset_id for item in list_sam3_pretrained_variants()
            ],
            "pretrained_root": str(SAM3_PRETRAINED_ROOT),
        },
    )


def normalize_model_asset_id(value: object) -> str:
    """规范化模型资产 id。"""

    normalized_value = str(value or DEFAULT_MODEL_ASSET_ID).strip()
    if not normalized_value:
        return DEFAULT_MODEL_ASSET_ID
    if normalized_value.startswith("/") or ".." in normalized_value.split("/"):
        raise InvalidRequestError(
            "SAM3 model_asset_id 不是合法资产 id",
            details={"model_asset_id": value},
        )
    return normalized_value


def normalize_device(value: object) -> str:
    """规范化并限制 PyTorch SAM3 设备名称。"""

    normalized_value = str(value or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
    if normalized_value == "cuda":
        return "cuda:0"
    if normalized_value in {"auto", "cpu"} or _CUDA_DEVICE_PATTERN.fullmatch(
        normalized_value
    ):
        return normalized_value
    raise InvalidRequestError(
        "SAM3 device 必须是 auto、cpu 或 cuda:<index>",
        details={"device": value},
    )


def normalize_precision(value: object) -> str:
    """规范化精度参数。"""

    normalized_value = (
        str(value or DEFAULT_PRECISION).strip().lower() or DEFAULT_PRECISION
    )
    if normalized_value not in SUPPORTED_PRECISIONS:
        raise InvalidRequestError(
            "SAM3 precision 只能是 auto、fp32、fp16 或 bf16",
            details={"precision": value, "supported": sorted(SUPPORTED_PRECISIONS)},
        )
    return normalized_value


def _read_sam3_pretrained_manifest(manifest_path: Path) -> Sam3PretrainedVariant:
    """读取并校验一份 SAM3 模型资产 manifest。"""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InvalidRequestError(
            "SAM3 模型资产 manifest 不是合法 JSON",
            details={"manifest_path": str(manifest_path)},
        ) from exc
    model_asset_id = normalize_model_asset_id(payload.get("model_asset_id"))
    architecture_id = str(payload.get("architecture_id") or "").strip()
    checkpoint_path_value = str(payload.get("checkpoint_path") or "").strip()
    if not architecture_id:
        raise InvalidRequestError(
            "SAM3 模型资产 manifest 缺少 architecture_id",
            details={"manifest_path": str(manifest_path)},
        )
    if not checkpoint_path_value:
        raise InvalidRequestError(
            "SAM3 模型资产 manifest 缺少 checkpoint_path",
            details={"manifest_path": str(manifest_path)},
        )
    checkpoint_path = (manifest_path.parent / checkpoint_path_value).resolve()
    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "SAM3 模型资产 checkpoint 不存在",
            details={
                "manifest_path": str(manifest_path),
                "checkpoint_path": str(checkpoint_path),
            },
        )
    metadata = payload.get("metadata")
    normalized_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    capabilities = payload.get("capabilities")
    if isinstance(capabilities, list):
        normalized_metadata["capabilities"] = tuple(
            str(item).strip() for item in capabilities if str(item).strip()
        )
    minimum_runtime = payload.get("minimum_runtime")
    if isinstance(minimum_runtime, dict):
        normalized_metadata["minimum_runtime"] = dict(minimum_runtime)
    sha256 = str(payload.get("checkpoint_sha256") or "").strip().lower()
    if sha256:
        normalized_metadata["checkpoint_sha256"] = sha256
    return Sam3PretrainedVariant(
        model_asset_id=model_asset_id,
        architecture_id=architecture_id,
        manifest_path=manifest_path,
        checkpoint_path=checkpoint_path,
        model_name=str(payload.get("model_name") or "sam3"),
        model_version=str(payload.get("model_version") or "sam3"),
        task_type=str(payload.get("task_type") or "segmentation"),
        metadata=normalized_metadata,
    )


def _validate_checkpoint_digest(variant: Sam3PretrainedVariant) -> None:
    """在 manifest 声明 SHA-256 时校验 checkpoint 完整性。"""

    expected_digest = (
        str(variant.metadata.get("checkpoint_sha256") or "").strip().lower()
    )
    if not expected_digest:
        return
    checkpoint_stat = variant.checkpoint_path.stat()
    actual_digest = _compute_checkpoint_sha256(
        str(variant.checkpoint_path),
        checkpoint_stat.st_size,
        checkpoint_stat.st_mtime_ns,
    )
    if actual_digest != expected_digest:
        raise InvalidRequestError(
            "SAM3 checkpoint SHA-256 校验失败",
            details={
                "model_asset_id": variant.model_asset_id,
                "expected_sha256": expected_digest,
                "actual_sha256": actual_digest,
            },
        )


@lru_cache(maxsize=8)
def _compute_checkpoint_sha256(
    checkpoint_path: str,
    checkpoint_size: int,
    checkpoint_mtime_ns: int,
) -> str:
    """按路径和文件状态缓存大 checkpoint 的 SHA-256。"""

    del checkpoint_size, checkpoint_mtime_ns
    hasher = hashlib.sha256()
    with Path(checkpoint_path).open("rb") as checkpoint_file:
        for chunk in iter(lambda: checkpoint_file.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


__all__ = [
    "DEFAULT_DEVICE",
    "DEFAULT_MODEL_ASSET_ID",
    "DEFAULT_PRECISION",
    "SAM3_PRETRAINED_ROOT",
    "SUPPORTED_POINT_LABELS",
    "SUPPORTED_PRECISIONS",
    "list_sam3_pretrained_variants",
    "normalize_device",
    "normalize_model_asset_id",
    "normalize_precision",
    "resolve_sam3_pretrained_variant",
]
