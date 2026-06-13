"""模型 core 验收工具。

本模块只做结构、输出和 state_dict 覆盖率检查，不参与训练和推理业务逻辑。
后续拆分 yolov8_core / yolo11_core / yolo26_core / rf_detr_core 时，先用这里的工具
固定验收口径，避免模型结构改动后只靠人工比对。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn


@dataclass(frozen=True)
class ModelParameterSummary:
    """模型参数和模块数量摘要。"""

    total_parameter_count: int
    trainable_parameter_count: int
    buffer_count: int
    state_dict_key_count: int
    module_count: int
    leaf_module_counts: dict[str, int]


@dataclass(frozen=True)
class ModelCoreSnapshot:
    """单个模型 core 的结构和输出快照。"""

    model_type: str
    task_type: str
    model_scale: str
    num_classes: int
    parameters: ModelParameterSummary
    output_summary: dict[str, Any] | None


@dataclass(frozen=True)
class StateDictCoverageSummary:
    """state_dict 加载覆盖率摘要。"""

    model_key_count: int
    source_key_count: int
    loadable_key_count: int
    missing_keys: tuple[str, ...]
    unexpected_keys: tuple[str, ...]
    shape_mismatch_keys: tuple[str, ...]
    ignored_missing_keys: tuple[str, ...]
    ignored_source_keys: tuple[str, ...]
    loadable_ratio: float


def summarize_model_parameters(model: nn.Module) -> ModelParameterSummary:
    """统计模型参数、buffer、state_dict key 和叶子模块类型。"""

    total_parameter_count = sum(parameter.numel() for parameter in model.parameters())
    trainable_parameter_count = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    buffer_count = sum(buffer.numel() for buffer in model.buffers())
    state_dict_key_count = len(model.state_dict())
    leaf_module_counts = _count_leaf_modules(model)
    module_count = sum(1 for _ in model.modules())
    return ModelParameterSummary(
        total_parameter_count=total_parameter_count,
        trainable_parameter_count=trainable_parameter_count,
        buffer_count=buffer_count,
        state_dict_key_count=state_dict_key_count,
        module_count=module_count,
        leaf_module_counts=leaf_module_counts,
    )


def summarize_model_output(output: Any) -> dict[str, Any]:
    """把模型输出收成稳定、可断言的形状摘要。"""

    if isinstance(output, torch.Tensor):
        return {
            "kind": "tensor",
            "shape": tuple(int(size) for size in output.shape),
            "dtype": str(output.dtype),
        }
    if isinstance(output, tuple):
        return {
            "kind": "tuple",
            "items": tuple(summarize_model_output(item) for item in output),
        }
    if isinstance(output, list):
        return {
            "kind": "list",
            "items": tuple(summarize_model_output(item) for item in output),
        }
    if isinstance(output, dict):
        return {
            "kind": "dict",
            "items": {str(key): summarize_model_output(value) for key, value in output.items()},
        }
    if output is None:
        return {"kind": "none"}
    return {"kind": type(output).__name__}


def build_model_core_snapshot(
    *,
    model: nn.Module,
    model_type: str,
    task_type: str,
    model_scale: str,
    num_classes: int,
    example_input: torch.Tensor | None = None,
) -> ModelCoreSnapshot:
    """生成模型 core 验收快照，可选执行一次前向并记录输出形状。"""

    output_summary: dict[str, Any] | None = None
    if example_input is not None:
        was_training = model.training
        model.eval()
        with torch.inference_mode():
            output_summary = summarize_model_output(model(example_input))
        model.train(was_training)
    return ModelCoreSnapshot(
        model_type=model_type,
        task_type=task_type,
        model_scale=model_scale,
        num_classes=num_classes,
        parameters=summarize_model_parameters(model),
        output_summary=output_summary,
    )


def analyze_state_dict_coverage(
    *,
    model: nn.Module,
    source_state_dict: dict[str, torch.Tensor],
    key_prefixes_to_strip: tuple[str, ...] = ("model.", "module."),
    ignored_model_key_suffixes: tuple[str, ...] = (),
    ignored_source_key_suffixes: tuple[str, ...] = (),
) -> StateDictCoverageSummary:
    """分析 source_state_dict 对目标模型 state_dict 的可加载覆盖率。"""

    model_state_dict = model.state_dict()
    model_keys = set(model_state_dict)
    normalized_source_state_dict = {}
    for key, tensor in source_state_dict.items():
        normalized_key = _resolve_source_key(
            key=key,
            model_keys=model_keys,
            prefixes=key_prefixes_to_strip,
        )
        normalized_source_state_dict[normalized_key] = tensor

    loadable_keys: set[str] = set()
    shape_mismatch_keys: set[str] = set()
    ignored_source_keys: set[str] = set()
    unexpected_keys: set[str] = set()
    for source_key, source_tensor in normalized_source_state_dict.items():
        if _matches_suffix(source_key, ignored_source_key_suffixes):
            ignored_source_keys.add(source_key)
            continue
        model_tensor = model_state_dict.get(source_key)
        if model_tensor is None:
            unexpected_keys.add(source_key)
            continue
        if tuple(model_tensor.shape) != tuple(source_tensor.shape):
            shape_mismatch_keys.add(source_key)
            continue
        loadable_keys.add(source_key)

    ignored_missing_keys: set[str] = set()
    missing_keys: set[str] = set()
    for model_key in model_state_dict:
        if model_key in loadable_keys or model_key in shape_mismatch_keys:
            continue
        if _matches_suffix(model_key, ignored_model_key_suffixes):
            ignored_missing_keys.add(model_key)
            continue
        missing_keys.add(model_key)

    model_key_count = len(model_state_dict)
    loadable_ratio = round(len(loadable_keys) / model_key_count, 6) if model_key_count else 1.0
    return StateDictCoverageSummary(
        model_key_count=model_key_count,
        source_key_count=len(source_state_dict),
        loadable_key_count=len(loadable_keys),
        missing_keys=tuple(sorted(missing_keys)),
        unexpected_keys=tuple(sorted(unexpected_keys)),
        shape_mismatch_keys=tuple(sorted(shape_mismatch_keys)),
        ignored_missing_keys=tuple(sorted(ignored_missing_keys)),
        ignored_source_keys=tuple(sorted(ignored_source_keys)),
        loadable_ratio=loadable_ratio,
    )


def _count_leaf_modules(model: nn.Module) -> dict[str, int]:
    """统计没有子模块的叶子模块类型数量。"""

    leaf_module_counts: dict[str, int] = {}
    for module in model.modules():
        if any(module.children()):
            continue
        module_name = module.__class__.__name__
        leaf_module_counts[module_name] = leaf_module_counts.get(module_name, 0) + 1
    return dict(sorted(leaf_module_counts.items()))


def _resolve_source_key(
    *,
    key: str,
    model_keys: set[str],
    prefixes: tuple[str, ...],
) -> str:
    """按目标模型 key 优先匹配，必要时再剥离 checkpoint 外层前缀。"""

    if key in model_keys:
        return key
    normalized_key = key
    prefix_removed = True
    while prefix_removed:
        prefix_removed = False
        for prefix in prefixes:
            if normalized_key.startswith(prefix):
                normalized_key = normalized_key[len(prefix) :]
                if normalized_key in model_keys:
                    return normalized_key
                prefix_removed = True
    return normalized_key


def _matches_suffix(key: str, suffixes: tuple[str, ...]) -> bool:
    """判断 key 是否匹配任意忽略后缀。"""

    return any(key.endswith(suffix) for suffix in suffixes)
