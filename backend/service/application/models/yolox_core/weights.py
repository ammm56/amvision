"""YOLOX core 权重读取、覆盖率和加载入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torch import nn

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.model_core_validation import (
    StateDictCoverageSummary,
    analyze_state_dict_coverage,
)


@dataclass(frozen=True)
class YoloXStateDictLoadResult:
    """描述一次 YOLOX state_dict 加载结果。"""

    coverage: StateDictCoverageSummary
    loaded_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    unexpected_keys: tuple[str, ...]
    shape_mismatch_keys: tuple[str, ...]
    skipped_shape_keys: tuple[str, ...]
    checkpoint_path: str | None = None


def extract_yolox_checkpoint_state_dict(checkpoint_payload: object) -> dict[str, Any]:
    """从 YOLOX checkpoint 载荷中提取可加载的 state_dict。"""

    if _looks_like_state_dict(checkpoint_payload):
        return dict(checkpoint_payload)

    if isinstance(checkpoint_payload, dict):
        for candidate_key in ("model", "ema_model", "state_dict", "model_state_dict"):
            candidate_value = checkpoint_payload.get(candidate_key)
            if _looks_like_state_dict(candidate_value):
                return dict(candidate_value)

    if hasattr(checkpoint_payload, "state_dict"):
        state_dict = checkpoint_payload.state_dict()
        if _looks_like_state_dict(state_dict):
            return dict(state_dict)

    raise InvalidRequestError("YOLOX checkpoint 缺少可识别的模型参数字典")


def analyze_yolox_state_dict_coverage(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> StateDictCoverageSummary:
    """分析 YOLOX source_state_dict 对目标模型的覆盖率。"""

    return analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        key_prefixes_to_strip=("model.", "module."),
    )


def load_yolox_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
    minimum_loadable_ratio: float = 0.0,
    strict_shape: bool = False,
) -> YoloXStateDictLoadResult:
    """把 YOLOX state_dict 加载到模型，并返回覆盖率报告。

    YOLOX warm start 常见场景会因为类别数不同跳过 head 参数，因此默认允许
    shape mismatch 被跳过；需要完整覆盖时由调用方传入更高的
    minimum_loadable_ratio 或 strict_shape=True。
    """

    coverage = analyze_yolox_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )
    if coverage.loadable_ratio < float(minimum_loadable_ratio):
        raise ServiceConfigurationError(
            "YOLOX state_dict 覆盖率低于要求",
            details={
                "minimum_loadable_ratio": float(minimum_loadable_ratio),
                "loadable_ratio": coverage.loadable_ratio,
                "missing_keys": list(coverage.missing_keys),
                "unexpected_keys": list(coverage.unexpected_keys),
                "shape_mismatch_keys": list(coverage.shape_mismatch_keys),
            },
        )
    if strict_shape and coverage.shape_mismatch_keys:
        raise ServiceConfigurationError(
            "YOLOX state_dict 存在 shape mismatch",
            details={"shape_mismatch_keys": list(coverage.shape_mismatch_keys)},
        )

    loadable_state_dict = _build_loadable_state_dict(
        model=model,
        source_state_dict=source_state_dict,
    )
    if not loadable_state_dict:
        raise InvalidRequestError("YOLOX checkpoint 与当前模型结构不兼容")

    incompatible_keys = model.load_state_dict(loadable_state_dict, strict=False)
    skipped_shape_keys = tuple(coverage.shape_mismatch_keys)
    return YoloXStateDictLoadResult(
        coverage=coverage,
        loaded_keys=tuple(sorted(loadable_state_dict)),
        missing_keys=tuple(str(item) for item in incompatible_keys.missing_keys),
        unexpected_keys=tuple(str(item) for item in incompatible_keys.unexpected_keys),
        shape_mismatch_keys=coverage.shape_mismatch_keys,
        skipped_shape_keys=skipped_shape_keys,
    )


def load_yolox_checkpoint_file(
    *,
    torch_module: Any,
    model: nn.Module,
    checkpoint_path: Path,
    minimum_loadable_ratio: float = 0.0,
    strict_shape: bool = False,
) -> YoloXStateDictLoadResult:
    """读取并加载 YOLOX checkpoint 文件。"""

    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "YOLOX checkpoint 不存在",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        )
    try:
        checkpoint_payload = torch_module.load(str(checkpoint_path), map_location="cpu")
    except Exception as error:
        raise ServiceConfigurationError(
            "YOLOX checkpoint 读取失败",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        ) from error

    source_state_dict = extract_yolox_checkpoint_state_dict(checkpoint_payload)
    load_result = load_yolox_state_dict(
        model=model,
        source_state_dict=source_state_dict,
        minimum_loadable_ratio=minimum_loadable_ratio,
        strict_shape=strict_shape,
    )
    return YoloXStateDictLoadResult(
        coverage=load_result.coverage,
        loaded_keys=load_result.loaded_keys,
        missing_keys=load_result.missing_keys,
        unexpected_keys=load_result.unexpected_keys,
        shape_mismatch_keys=load_result.shape_mismatch_keys,
        skipped_shape_keys=load_result.skipped_shape_keys,
        checkpoint_path=checkpoint_path.as_posix(),
    )


def load_yolox_warm_start_checkpoint(
    *,
    torch_module: Any,
    model: nn.Module,
    checkpoint_path: Path,
    source_summary: dict[str, object],
) -> dict[str, object]:
    """加载 YOLOX warm start checkpoint 并生成摘要。"""

    load_result = load_yolox_checkpoint_file(
        torch_module=torch_module,
        model=model,
        checkpoint_path=checkpoint_path,
        minimum_loadable_ratio=0.0,
        strict_shape=False,
    )
    loaded_parameter_count = sum(
        int(model.state_dict()[key].numel())
        for key in load_result.loaded_keys
        if key in model.state_dict()
    )
    warm_start_summary = dict(source_summary)
    warm_start_summary.update(
        {
            "enabled": True,
            "checkpoint_path": checkpoint_path.as_posix(),
            "loaded_tensor_count": len(load_result.loaded_keys),
            "loaded_parameter_count": loaded_parameter_count,
            "loadable_ratio": load_result.coverage.loadable_ratio,
            "missing_key_count": len(load_result.missing_keys),
            "unexpected_key_count": len(load_result.unexpected_keys),
            "skipped_shape_key_count": len(load_result.skipped_shape_keys),
            "missing_keys_preview": list(load_result.missing_keys[:10]),
            "unexpected_keys_preview": list(load_result.unexpected_keys[:10]),
            "skipped_shape_keys_preview": list(load_result.skipped_shape_keys[:10]),
        }
    )
    return warm_start_summary


def _build_loadable_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> dict[str, Any]:
    """按目标模型结构筛出可直接加载的 tensor。"""

    model_state_dict = model.state_dict()
    loadable_state_dict: dict[str, Any] = {}
    for raw_key, value in source_state_dict.items():
        normalized_key = _normalize_source_key(str(raw_key), model_state_dict)
        target_value = model_state_dict.get(normalized_key)
        if target_value is None or not hasattr(value, "shape"):
            continue
        if tuple(value.shape) != tuple(target_value.shape):
            continue
        loadable_state_dict[normalized_key] = value
    return loadable_state_dict


def _normalize_source_key(key: str, model_state_dict: dict[str, Any]) -> str:
    """按目标模型 key 优先匹配，必要时剥离常见外层前缀。"""

    if key in model_state_dict:
        return key
    normalized_key = key
    for prefix in ("model.", "module."):
        if normalized_key.startswith(prefix):
            candidate = normalized_key.removeprefix(prefix)
            if candidate in model_state_dict:
                return candidate
            normalized_key = candidate
    return normalized_key


def _looks_like_state_dict(value: object) -> bool:
    """判断对象是否像 PyTorch state_dict。"""

    if not isinstance(value, dict) or not value:
        return False
    for key, item in value.items():
        if not isinstance(key, str):
            return False
        if not hasattr(item, "shape") and not hasattr(item, "dtype"):
            return False
    return True
