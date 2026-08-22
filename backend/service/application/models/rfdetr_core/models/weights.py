"""RF-DETR core 模型结构模块：`models.weights`。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

import torch
import torch.nn.functional as F  # noqa: N812

from backend.service.application.models.validation.model_core_validation import (
    StateDictCoverageSummary,
    analyze_state_dict_coverage,
)
from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig
from backend.service.application.models.rfdetr_core.utilities.decorators import deprecated
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger
from backend.service.application.models.rfdetr_core.utilities.state_dict import _ckpt_args_get, validate_checkpoint_compatibility

logger = get_logger()

__all__ = [
    "analyze_rfdetr_checkpoint_coverage",
    "analyze_rfdetr_checkpoint_load_coverage",
    "apply_lora",
    "interpolate_position_embeddings",
    "load_rfdetr_deployment_weights",
    "load_pretrain_weights",
    "load_rfdetr_checkpoint_state_dict",
    "RfdetrDeploymentLoadReport",
    "RfdetrWarmStartLoadReport",
]

_PE_KEY_SUFFIX = "embeddings.position_embeddings"

_QUERY_PARAM_SUFFIXES: tuple[str, ...] = ("refpoint_embed.weight", "query_feat.weight")


@dataclass(frozen=True)
class RfdetrDeploymentLoadReport:
    """描述一次 RF-DETR 部署权重的严格加载结果。"""

    checkpoint_path: str
    source_name: str
    model_key_count: int
    source_key_count: int
    loaded_key_count: int
    model_numel: int
    loaded_numel: int

    @property
    def key_coverage(self) -> float:
        """返回按 state_dict key 计算的覆盖率。"""

        if self.model_key_count == 0:
            return 1.0
        return self.loaded_key_count / self.model_key_count

    @property
    def numel_coverage(self) -> float:
        """返回按参数和 buffer 元素数量计算的覆盖率。"""

        if self.model_numel == 0:
            return 1.0
        return self.loaded_numel / self.model_numel


@dataclass(frozen=True)
class RfdetrWarmStartLoadReport:
    """描述 warm-start 明确允许忽略的参数差异。"""

    checkpoint_path: str
    allowed_missing_keys: tuple[str, ...]
    allowed_unexpected_keys: tuple[str, ...]


def _require_local_checkpoint(path: str) -> Path:
    """执行 `_require_local_checkpoint`。
    
    参数：
    - `path`：传入的 `path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    checkpoint_path = Path(path).expanduser().resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(
            "RF-DETR 预训练 checkpoint 不存在。"
            f"请先把文件放到本地模型目录，或显式传入有效路径：{checkpoint_path}"
        )
    if checkpoint_path.stat().st_size <= 0:
        raise ValueError(f"RF-DETR 预训练 checkpoint 是空文件：{checkpoint_path}")
    return checkpoint_path


def load_rfdetr_checkpoint_state_dict(path: str | Path) -> dict[str, torch.Tensor]:
    """执行 `load_rfdetr_checkpoint_state_dict`。
    
    参数：
    - `path`：传入的 `path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    checkpoint_path = _require_local_checkpoint(str(path))
    normalized, _ = _load_normalized_checkpoint(checkpoint_path)
    return dict(normalized["model"])


def load_rfdetr_deployment_weights(
    *,
    model: torch.nn.Module,
    checkpoint_path: str | Path,
) -> RfdetrDeploymentLoadReport:
    """严格加载 RF-DETR 部署或转换权重。

    部署链路不允许 warm-start 适配。checkpoint 必须覆盖目标模型的全部
    state_dict key，不能包含未知 key，也不能存在 shape mismatch。完成显式
    覆盖检查后仍使用 ``strict=True``，避免后续模型结构变化绕过本门禁。
    """

    checkpoint_path_obj = _require_local_checkpoint(str(checkpoint_path))
    normalized_checkpoint, source_name = _load_normalized_checkpoint(
        checkpoint_path_obj
    )
    source_state_dict = _normalize_state_dict_for_model(
        model=model,
        source_state_dict=dict(normalized_checkpoint["model"]),
        checkpoint_path=checkpoint_path_obj,
    )
    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        key_prefixes_to_strip=(),
    )
    model_state_dict = model.state_dict()
    loaded_numel = sum(
        int(model_state_dict[key].numel())
        for key in source_state_dict
        if key in model_state_dict
        and tuple(source_state_dict[key].shape) == tuple(model_state_dict[key].shape)
    )
    model_numel = sum(int(tensor.numel()) for tensor in model_state_dict.values())
    report = RfdetrDeploymentLoadReport(
        checkpoint_path=str(checkpoint_path_obj),
        source_name=source_name,
        model_key_count=coverage.model_key_count,
        source_key_count=coverage.source_key_count,
        loaded_key_count=coverage.loadable_key_count,
        model_numel=model_numel,
        loaded_numel=loaded_numel,
    )
    if (
        coverage.missing_keys
        or coverage.unexpected_keys
        or coverage.shape_mismatch_keys
        or coverage.loadable_key_count != coverage.model_key_count
        or loaded_numel != model_numel
    ):
        raise ValueError(
            "RF-DETR 部署 checkpoint 与目标模型不完全匹配："
            f"source={source_name}, "
            f"key_coverage={report.key_coverage:.6f}, "
            f"numel_coverage={report.numel_coverage:.6f}, "
            f"missing={_sample_keys(coverage.missing_keys)}, "
            f"unexpected={_sample_keys(coverage.unexpected_keys)}, "
            f"shape_mismatch={_sample_keys(coverage.shape_mismatch_keys)}, "
            f"checkpoint={checkpoint_path_obj}"
        )
    model.load_state_dict(source_state_dict, strict=True)
    return report


def analyze_rfdetr_checkpoint_coverage(
    *,
    model: torch.nn.Module,
    checkpoint_path: str | Path,
    ignored_model_key_suffixes: tuple[str, ...] = (),
    ignored_source_key_suffixes: tuple[str, ...] = (),
) -> StateDictCoverageSummary:
    """执行 `analyze_rfdetr_checkpoint_coverage`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `ignored_model_key_suffixes`：传入的 `ignored_model_key_suffixes` 参数。
    - `ignored_source_key_suffixes`：传入的 `ignored_source_key_suffixes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    source_state_dict = load_rfdetr_checkpoint_state_dict(checkpoint_path)
    return analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        ignored_model_key_suffixes=ignored_model_key_suffixes,
        ignored_source_key_suffixes=ignored_source_key_suffixes,
    )


def analyze_rfdetr_checkpoint_load_coverage(
    *,
    model: torch.nn.Module,
    checkpoint_path: str | Path,
    ignored_model_key_suffixes: tuple[str, ...] = (),
    ignored_source_key_suffixes: tuple[str, ...] = (),
) -> StateDictCoverageSummary:
    """执行 `analyze_rfdetr_checkpoint_load_coverage`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `ignored_model_key_suffixes`：传入的 `ignored_model_key_suffixes` 参数。
    - `ignored_source_key_suffixes`：传入的 `ignored_source_key_suffixes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    checkpoint_path_obj = _require_local_checkpoint(str(checkpoint_path))
    normalized, _ = _load_normalized_checkpoint(checkpoint_path_obj)
    source_state_dict = _build_load_path_coverage_state_dict(
        model=model,
        checkpoint=normalized,
        checkpoint_path=checkpoint_path_obj,
    )
    return analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        ignored_model_key_suffixes=ignored_model_key_suffixes,
        ignored_source_key_suffixes=ignored_source_key_suffixes,
    )


def _build_load_path_coverage_state_dict(
    *,
    model: torch.nn.Module,
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
) -> dict[str, torch.Tensor]:
    """执行 `_build_load_path_coverage_state_dict`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `checkpoint`：传入的 `checkpoint` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    source_state_dict = dict(checkpoint["model"])
    _adapt_query_params_for_load_coverage(
        model=model,
        source_state_dict=source_state_dict,
        checkpoint_args=checkpoint.get("args"),
        checkpoint_path=checkpoint_path,
    )
    return source_state_dict


def _adapt_query_params_for_load_coverage(
    *,
    model: torch.nn.Module,
    source_state_dict: dict[str, torch.Tensor],
    checkpoint_args: Any,
    checkpoint_path: Path,
) -> None:
    """执行 `_adapt_query_params_for_load_coverage`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `source_state_dict`：传入的 `source_state_dict` 参数。
    - `checkpoint_args`：传入的 `checkpoint_args` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    model_state_dict = model.state_dict()
    target_num_queries = _coerce_positive_int(getattr(model, "num_queries", None))
    target_group_detr = _coerce_positive_int(getattr(model, "group_detr", None))
    ckpt_num_queries, ckpt_group_detr = _resolve_checkpoint_query_layout(
        checkpoint_args=checkpoint_args,
        checkpoint_path=checkpoint_path,
    )
    has_query_parameters = any(
        any(name.endswith(suffix) for suffix in _QUERY_PARAM_SUFFIXES)
        for name in source_state_dict
    )
    if (
        has_query_parameters
        and target_group_detr is not None
        and target_group_detr > 1
        and (ckpt_num_queries is None or ckpt_group_detr is None)
    ):
        raise ValueError(
            "RF-DETR grouped-query warm-start 缺少来源 query 布局元数据："
            f"checkpoint={checkpoint_path}"
        )

    for name, tensor in list(source_state_dict.items()):
        if not any(name.endswith(suffix) for suffix in _QUERY_PARAM_SUFFIXES):
            continue
        target_tensor = model_state_dict.get(name)
        if target_tensor is None or tuple(tensor.shape) == tuple(target_tensor.shape):
            continue
        if len(tensor.shape) != len(target_tensor.shape) or tuple(tensor.shape[1:]) != tuple(target_tensor.shape[1:]):
            continue
        if tensor.shape[0] < target_tensor.shape[0]:
            continue
        if (
            ckpt_num_queries is None
            or ckpt_group_detr is None
            or target_num_queries is None
            or target_group_detr is None
        ):
            continue
        source_state_dict[name] = _slice_query_param_per_group(
            tensor,
            ckpt_num_queries=ckpt_num_queries,
            ckpt_group_detr=ckpt_group_detr,
            target_num_queries=target_num_queries,
            target_group_detr=target_group_detr,
        )


def _coerce_positive_int(value: Any) -> int | None:
    """执行 `_coerce_positive_int`。
    
    参数：
    - `value`：传入的 `value` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    if integer <= 0:
        return None
    return integer


def _normalize_checkpoint_payload(
    checkpoint: Any,
    checkpoint_path: Path,
) -> dict[str, Any]:
    """执行 `_normalize_checkpoint_payload`。
    
    参数：
    - `checkpoint`：传入的 `checkpoint` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if not isinstance(checkpoint, Mapping):
        raise ValueError(f"RF-DETR checkpoint 不是有效字典：{checkpoint_path}")

    if "model" in checkpoint:
        model_state = _coerce_tensor_state_dict(
            checkpoint["model"],
            checkpoint_path=checkpoint_path,
            source_name="model",
        )
        normalized = dict(checkpoint)
        normalized["model"] = model_state
        return normalized

    if "model_state_dict" in checkpoint:
        model_state = _coerce_tensor_state_dict(
            checkpoint["model_state_dict"],
            checkpoint_path=checkpoint_path,
            source_name="model_state_dict",
        )
        normalized = dict(checkpoint)
        normalized["model"] = model_state
        return normalized

    if "state_dict" in checkpoint:
        model_state = _normalize_lightning_state_dict(
            checkpoint["state_dict"],
            checkpoint_path=checkpoint_path,
        )
        normalized = dict(checkpoint)
        normalized["model"] = model_state
        if "args" not in normalized and "hyper_parameters" in normalized:
            normalized["args"] = normalized["hyper_parameters"]
        return normalized

    if _looks_like_tensor_state_dict(checkpoint):
        return {"model": _coerce_tensor_state_dict(checkpoint, checkpoint_path=checkpoint_path, source_name="raw")}

    raise ValueError(
        "RF-DETR checkpoint 缺少可识别的权重字段。"
        "需要顶层包含 model、model_state_dict、state_dict，"
        f"或文件本身是裸 state_dict：{checkpoint_path}"
    )


def _load_normalized_checkpoint(
    checkpoint_path: Path,
) -> tuple[dict[str, Any], str]:
    """读取 checkpoint，并返回归一化 payload 与实际选中的权重来源。"""

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    if not isinstance(checkpoint, Mapping):
        raise ValueError(f"RF-DETR checkpoint 不是有效字典：{checkpoint_path}")
    if "model" in checkpoint:
        source_name = "model"
    elif "model_state_dict" in checkpoint:
        source_name = "model_state_dict"
    elif "state_dict" in checkpoint:
        source_name = "state_dict"
    elif _looks_like_tensor_state_dict(checkpoint):
        source_name = "raw"
    else:
        source_name = "unknown"
    return _normalize_checkpoint_payload(checkpoint, checkpoint_path), source_name


def _normalize_state_dict_for_model(
    *,
    model: torch.nn.Module,
    source_state_dict: dict[str, torch.Tensor],
    checkpoint_path: Path,
) -> dict[str, torch.Tensor]:
    """按目标模型 key 规范化外层包装前缀，并拒绝规范化后的重复 key。"""

    model_keys = set(model.state_dict())
    prefixes = ("model.", "module.", "_orig_mod.")
    normalized: dict[str, torch.Tensor] = {}
    for source_key, tensor in source_state_dict.items():
        target_key = source_key
        if target_key not in model_keys:
            changed = True
            while changed and target_key not in model_keys:
                changed = False
                for prefix in prefixes:
                    if target_key.startswith(prefix):
                        target_key = target_key[len(prefix) :]
                        changed = True
                        break
        if target_key in normalized:
            raise ValueError(
                "RF-DETR checkpoint 规范化后包含重复参数 key："
                f"key={target_key}, checkpoint={checkpoint_path}"
            )
        normalized[target_key] = tensor
    return normalized


def _sample_keys(keys: tuple[str, ...], *, limit: int = 8) -> str:
    """把不兼容 key 收成有界错误摘要。"""

    if not keys:
        return "[]"
    sample = list(keys[:limit])
    suffix = ", ..." if len(keys) > limit else ""
    return f"[{', '.join(sample)}{suffix}]"


def _normalize_lightning_state_dict(
    state_dict: Any,
    *,
    checkpoint_path: Path,
) -> dict[str, torch.Tensor]:
    """执行 `_normalize_lightning_state_dict`。
    
    参数：
    - `state_dict`：传入的 `state_dict` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    tensor_state_dict = _coerce_tensor_state_dict(
        state_dict,
        checkpoint_path=checkpoint_path,
        source_name="state_dict",
    )
    prefix = "model."
    compile_prefix = "_orig_mod."
    model_state: dict[str, torch.Tensor] = {}
    for key, tensor in tensor_state_dict.items():
        if not key.startswith(prefix):
            continue
        stripped = key[len(prefix) :]
        if stripped.startswith(compile_prefix):
            stripped = stripped[len(compile_prefix) :]
        model_state[stripped] = tensor
    if not model_state:
        raise ValueError(
            f"RF-DETR Lightning checkpoint 的 state_dict 中没有 model. 前缀参数：{checkpoint_path}"
        )
    return model_state


def _coerce_tensor_state_dict(
    value: Any,
    *,
    checkpoint_path: Path,
    source_name: str,
) -> dict[str, torch.Tensor]:
    """执行 `_coerce_tensor_state_dict`。
    
    参数：
    - `value`：传入的 `value` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `source_name`：传入的 `source_name` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if not isinstance(value, Mapping):
        raise ValueError(f"RF-DETR checkpoint 的 {source_name} 不是字典：{checkpoint_path}")
    tensor_state_dict = {
        str(key): tensor for key, tensor in value.items() if torch.is_tensor(tensor)
    }
    if not tensor_state_dict:
        raise ValueError(f"RF-DETR checkpoint 的 {source_name} 中没有 Tensor 权重：{checkpoint_path}")
    return tensor_state_dict


def _looks_like_tensor_state_dict(value: Mapping[Any, Any]) -> bool:
    """执行 `_looks_like_tensor_state_dict`。
    
    参数：
    - `value`：传入的 `value` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return bool(value) and all(isinstance(key, str) and torch.is_tensor(tensor) for key, tensor in value.items())


def _slice_query_param_per_group(
    tensor: torch.Tensor,
    ckpt_num_queries: int,
    ckpt_group_detr: int,
    target_num_queries: int,
    target_group_detr: int,
) -> torch.Tensor:
    """执行 `_slice_query_param_per_group`。
    
    参数：
    - `tensor`：传入的 `tensor` 参数。
    - `ckpt_num_queries`：传入的 `ckpt_num_queries` 参数。
    - `ckpt_group_detr`：传入的 `ckpt_group_detr` 参数。
    - `target_num_queries`：传入的 `target_num_queries` 参数。
    - `target_group_detr`：传入的 `target_group_detr` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if ckpt_num_queries <= 0 or ckpt_group_detr <= 0 or target_num_queries <= 0 or target_group_detr <= 0:
        raise ValueError(
            f"_slice_query_param_per_group: all dimension args must be positive; "
            f"got ckpt_num_queries={ckpt_num_queries}, ckpt_group_detr={ckpt_group_detr}, "
            f"target_num_queries={target_num_queries}, target_group_detr={target_group_detr}."
        )

    expected_total = ckpt_num_queries * ckpt_group_detr
    if tensor.shape[0] != expected_total:
        raise ValueError(
            "RF-DETR checkpoint query 布局元数据与 Tensor 行数不一致："
            f"num_queries={ckpt_num_queries}, group_detr={ckpt_group_detr}, "
            f"expected_rows={expected_total}, actual_rows={tensor.shape[0]}"
        )

    if target_num_queries == ckpt_num_queries and target_group_detr == ckpt_group_detr:
        return tensor

    keep_groups = min(target_group_detr, ckpt_group_detr)
    keep_per_group = min(target_num_queries, ckpt_num_queries)
    if keep_groups != target_group_detr or keep_per_group != target_num_queries:
        raise ValueError(
            "RF-DETR warm-start 不能从较小的 query 布局扩展到较大布局："
            f"source={ckpt_num_queries}x{ckpt_group_detr}, "
            f"target={target_num_queries}x{target_group_detr}"
        )
    pieces = [tensor[g * ckpt_num_queries : g * ckpt_num_queries + keep_per_group] for g in range(keep_groups)]
    return torch.cat(pieces, dim=0)


def _resolve_checkpoint_query_layout(
    *,
    checkpoint_args: Any,
    checkpoint_path: Path,
) -> tuple[int | None, int | None]:
    """读取 checkpoint 自带或 catalog manifest 固化的 query 分组布局。"""

    raw_num_queries = _ckpt_args_get(checkpoint_args, "num_queries")
    raw_group_detr = _ckpt_args_get(checkpoint_args, "group_detr")
    has_checkpoint_layout = raw_num_queries is not None or raw_group_detr is not None
    if has_checkpoint_layout:
        num_queries = _coerce_positive_int(raw_num_queries)
        group_detr = _coerce_positive_int(raw_group_detr)
        if num_queries is None or group_detr is None:
            raise ValueError(
                "RF-DETR checkpoint 的 args.num_queries 和 args.group_detr "
                "必须同时存在且为正整数："
                f"checkpoint={checkpoint_path}"
            )
        return num_queries, group_detr

    manifest_path = checkpoint_path.parent.parent / "manifest.json"
    if not manifest_path.is_file():
        return None, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"RF-DETR 预训练资产 manifest 无法读取：{manifest_path}"
        ) from error
    if not isinstance(manifest, Mapping):
        raise ValueError(f"RF-DETR 预训练资产 manifest 不是 JSON 对象：{manifest_path}")
    configured_checkpoint_path = manifest.get("checkpoint_path")
    if not isinstance(configured_checkpoint_path, str):
        return None, None
    resolved_manifest_checkpoint = (
        manifest_path.parent / configured_checkpoint_path
    ).resolve()
    if resolved_manifest_checkpoint != checkpoint_path:
        return None, None
    model_config = manifest.get("checkpoint_model_config")
    if model_config is None:
        return None, None
    if not isinstance(model_config, Mapping):
        raise ValueError(
            f"RF-DETR checkpoint_model_config 不是 JSON 对象：{manifest_path}"
        )
    num_queries = _coerce_positive_int(model_config.get("num_queries"))
    group_detr = _coerce_positive_int(model_config.get("group_detr"))
    if num_queries is None or group_detr is None:
        raise ValueError(
            "RF-DETR checkpoint_model_config 必须包含正整数 "
            f"num_queries/group_detr：{manifest_path}"
        )
    return num_queries, group_detr


def _filter_intentional_keys(keys: list[str]) -> list[str]:
    """执行 `_filter_intentional_keys`。
    
    参数：
    - `keys`：传入的 `keys` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    intentional_patterns: tuple[str, ...] = (
        "class_embed.",
        "bbox_embed.",
        *_QUERY_PARAM_SUFFIXES,
        "enc_out_class_embed.",
        "enc_out_bbox_embed.",
    )

    def _is_intentional(key: str) -> bool:
        return any(key.startswith(pat) or f".{pat}" in key for pat in intentional_patterns)

    return [k for k in keys if not _is_intentional(k)]


def _validate_warm_start_partial_load(
    incompatible: Any,
    pretrain_weights_path: str,
) -> RfdetrWarmStartLoadReport:
    """只允许 head/query 适配产生的 warm-start 参数差异。
    
    参数：
    - `incompatible`：传入的 `incompatible` 参数。
    - `pretrain_weights_path`：传入的 `pretrain_weights_path` 参数。
    
    非白名单差异说明模型结构与 checkpoint 不兼容。继续训练会把未覆盖的
    backbone 等参数留在随机初始化状态，因此必须直接拒绝。
    """
    missing_keys_raw = getattr(incompatible, "missing_keys", None)
    unexpected_keys_raw = getattr(incompatible, "unexpected_keys", None)
    try:
        missing_keys = [str(k) for k in missing_keys_raw] if missing_keys_raw else []
        unexpected_keys = [str(k) for k in unexpected_keys_raw] if unexpected_keys_raw else []
    except TypeError as error:
        raise ValueError(
            "RF-DETR warm-start load_state_dict 返回了无效的不兼容参数报告："
            f"checkpoint={pretrain_weights_path}"
        ) from error

    rejected_missing = _filter_intentional_keys(missing_keys)
    rejected_unexpected = _filter_intentional_keys(unexpected_keys)
    if rejected_missing or rejected_unexpected:
        raise ValueError(
            "RF-DETR warm-start checkpoint 包含白名单之外的模型差异："
            f"missing={_sample_keys(tuple(rejected_missing))}, "
            f"unexpected={_sample_keys(tuple(rejected_unexpected))}, "
            f"checkpoint={pretrain_weights_path}"
        )

    allowed_missing = tuple(
        key for key in missing_keys if key not in rejected_missing
    )
    allowed_unexpected = tuple(
        key for key in unexpected_keys if key not in rejected_unexpected
    )
    report = RfdetrWarmStartLoadReport(
        checkpoint_path=pretrain_weights_path,
        allowed_missing_keys=allowed_missing,
        allowed_unexpected_keys=allowed_unexpected,
    )
    if allowed_missing or allowed_unexpected:
        logger.info(
            "RF-DETR warm-start applied allowed head/query adaptation: "
            "checkpoint=%s, allowed_missing=%s, allowed_unexpected=%s",
            pretrain_weights_path,
            list(allowed_missing),
            list(allowed_unexpected),
        )
    return report


def interpolate_position_embeddings(
    checkpoint_state: dict,
    pe_size: int,
) -> None:
    """执行 `interpolate_position_embeddings`。
    
    参数：
    - `checkpoint_state`：传入的 `checkpoint_state` 参数。
    - `pe_size`：传入的 `pe_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    n_target = pe_size * pe_size

    pe_keys = [k for k in checkpoint_state if k.endswith(_PE_KEY_SUFFIX)]
    for key in pe_keys:
        ckpt_pe = checkpoint_state[key]
        n_source = ckpt_pe.shape[1] - 1
        if n_source == n_target:
            continue

        h_src = int(math.isqrt(n_source))
        h_tgt = int(math.isqrt(n_target))
        if h_src * h_src != n_source or h_tgt * h_tgt != n_target:
            logger.warning(
                f"Skipping PE interpolation for {key}:"
                f" grid size is not a perfect square (source {n_source}, target {n_target}).",
            )
            continue

        dim = ckpt_pe.shape[-1]
        class_token = ckpt_pe[:, :1]
        patch_pe = ckpt_pe[:, 1:]

        patch_pe = patch_pe.reshape(1, h_src, h_src, dim).permute(0, 3, 1, 2)
        patch_pe = F.interpolate(
            patch_pe.float(),
            size=(h_tgt, h_tgt),
            mode="bicubic",
            align_corners=False,
            antialias=False,
        ).to(ckpt_pe.dtype)
        patch_pe = patch_pe.permute(0, 2, 3, 1).reshape(1, n_target, dim)

        checkpoint_state[key] = torch.cat([class_token, patch_pe], dim=1)
        logger.debug(
            "Interpolated positional embeddings %s: %s → %s.",
            key,
            tuple(ckpt_pe.shape),
            tuple(checkpoint_state[key].shape),
        )


@deprecated(target=True, args_mapping={"train_config": None}, deprecated_in="1.7.0", remove_in="1.9.0", num_warns=-1)
def load_pretrain_weights(
    nn_model: torch.nn.Module,
    model_config: ModelConfig,
    train_config: TrainConfig | None = None,
) -> List[str]:
    """执行 `load_pretrain_weights`。
    
    参数：
    - `nn_model`：传入的 `nn_model` 参数。
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    mc = model_config
    pretrain_weights = mc.pretrain_weights
    if pretrain_weights is None:
        return []
    class_names: List[str] = []
    checkpoint_path = _require_local_checkpoint(pretrain_weights)

    try:
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except Exception:
        logger.info("Failed to load RF-DETR pretrain weights from %s", checkpoint_path)
        raise
    checkpoint = _normalize_checkpoint_payload(checkpoint, checkpoint_path)

    if "args" in checkpoint:
        raw_class_names = _ckpt_args_get(checkpoint["args"], "class_names")
        if raw_class_names:
            if isinstance(raw_class_names, str):
                class_names = [raw_class_names]
            else:
                try:
                    iterator = iter(raw_class_names)
                except TypeError:
                    class_names = []
                else:
                    class_names = [name for name in iterator if isinstance(name, str)]

    validate_checkpoint_compatibility(checkpoint, mc)

    user_set_num_classes = False
    if hasattr(mc, "model_fields_set"):
        user_set_num_classes = "num_classes" in getattr(mc, "model_fields_set", set())
    default_num_classes = type(mc).model_fields["num_classes"].default
    num_classes = mc.num_classes
    user_overrode_default_num_classes = user_set_num_classes and num_classes != default_num_classes

    checkpoint_num_classes = checkpoint["model"]["class_embed.bias"].shape[0]
    configured_num_classes_plus_bg = num_classes + 1
    if checkpoint_num_classes != configured_num_classes_plus_bg:
        if checkpoint_num_classes < configured_num_classes_plus_bg:
            if not user_overrode_default_num_classes:
                num_classes = checkpoint_num_classes - 1
                configured_num_classes_plus_bg = checkpoint_num_classes
                mc.num_classes = num_classes
        nn_model.reinitialize_detection_head(checkpoint_num_classes)

    ckpt_num_queries, ckpt_group_detr = _resolve_checkpoint_query_layout(
        checkpoint_args=checkpoint.get("args"),
        checkpoint_path=checkpoint_path,
    )
    if mc.group_detr > 1 and (
        ckpt_num_queries is None or ckpt_group_detr is None
    ):
        raise ValueError(
            "RF-DETR grouped-query warm-start 缺少来源 query 布局元数据："
            f"checkpoint={checkpoint_path}"
        )
    target_query_rows = mc.num_queries * mc.group_detr
    for name in list(checkpoint["model"].keys()):
        if any(name.endswith(x) for x in _QUERY_PARAM_SUFFIXES):
            tensor = checkpoint["model"][name]
            if (
                tensor.shape[0] == target_query_rows
                and (
                    (
                        ckpt_num_queries == mc.num_queries
                        and ckpt_group_detr == mc.group_detr
                    )
                    or (
                        mc.group_detr == 1
                        and ckpt_num_queries is None
                        and ckpt_group_detr is None
                    )
                )
            ):
                continue
            if ckpt_num_queries is None or ckpt_group_detr is None:
                raise ValueError(
                    "RF-DETR warm-start 需要改变 query Tensor 布局，但 checkpoint "
                    "及其 catalog manifest 均未声明 num_queries/group_detr："
                    f"parameter={name}, source_rows={tensor.shape[0]}, "
                    f"target_rows={target_query_rows}, checkpoint={checkpoint_path}"
                )
            checkpoint["model"][name] = _slice_query_param_per_group(
                tensor,
                ckpt_num_queries=ckpt_num_queries,
                ckpt_group_detr=ckpt_group_detr,
                target_num_queries=mc.num_queries,
                target_group_detr=mc.group_detr,
            )

    interpolate_position_embeddings(checkpoint["model"], mc.positional_encoding_size)
    incompatible = nn_model.load_state_dict(checkpoint["model"], strict=False)
    _validate_warm_start_partial_load(incompatible, str(checkpoint_path))

    if checkpoint_num_classes < configured_num_classes_plus_bg and user_overrode_default_num_classes:
        nn_model.reinitialize_detection_head(configured_num_classes_plus_bg)

    if num_classes + 1 < checkpoint_num_classes:
        nn_model.reinitialize_detection_head(num_classes + 1)

    return class_names


def apply_lora(nn_model: torch.nn.Module) -> None:
    """执行 `apply_lora`。
    
    参数：
    - `nn_model`：传入的 `nn_model` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    _ = nn_model
    raise NotImplementedError("当前 RF-DETR core 未启用 LoRA/PEFT 微调；如需该能力，应单独规划并显式引入依赖。")
